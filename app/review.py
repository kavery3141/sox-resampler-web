from __future__ import annotations

from pathlib import Path
from typing import Any

from mutagen.flac import FLAC

from . import db
from .converter import preview
from .profiles import ResampleProfile


KEY_TAGS = (
    ("albumartist", "ALBUMARTIST"),
    ("album", "ALBUM"),
    ("releasetype", "RELEASETYPE"),
    ("musicbrainz_albumid", "MUSICBRAINZ_ALBUMID"),
)


def _matches_rate(sample_rate: int, rates: set[int], above: int | None) -> bool:
    return sample_rate in rates or (above is not None and sample_rate > above)


def _first(audio: FLAC, key: str) -> str | None:
    values = audio.get(key)
    if not values:
        return None
    value = str(values[0]).strip()
    return value or None


def _physical_album_track_count(folder: Path, albumartist: str, album: str) -> int:
    if not folder.is_dir():
        return 0
    count = 0
    for path in folder.iterdir():
        if path.name.startswith(".") or path.is_symlink() or not path.is_file() or path.suffix.lower() != ".flac":
            continue
        try:
            audio = FLAC(path)
        except Exception:
            continue
        if (_first(audio, "albumartist") or "") == albumartist and (_first(audio, "album") or "") == album:
            count += 1
    return count


def build_batch_review(
    db_path: Path,
    music_root: Path,
    album_keys: list[dict[str, str]],
    rates: list[int],
    above: int | None,
    profile: ResampleProfile,
    workers: int,
    reserve_bytes: int,
) -> dict[str, Any]:
    if workers not in (1, 2):
        raise ValueError("Workers must be 1 or 2")
    music_root = music_root.resolve()
    rate_set = set(rates)
    albums: list[dict[str, Any]] = []
    all_output_estimates: list[int] = []
    total_source = 0
    total_output = 0
    total_matching = 0
    hard_blockers: list[str] = []

    with db.session(db_path) as conn:
        for key in album_keys:
            albumartist = key.get("albumartist", "")
            album = key.get("album", "")
            folder = key.get("folder", "")
            folder_path = Path(folder)
            rows = conn.execute(
                """
                SELECT * FROM tracks
                WHERE COALESCE(albumartist,'')=? AND COALESCE(album,'')=? AND folder=?
                ORDER BY CAST(COALESCE(discnumber,'1') AS INTEGER),
                         CAST(COALESCE(tracknumber,'0') AS INTEGER), filename COLLATE NOCASE
                """,
                (albumartist, album, folder),
            ).fetchall()
            tracks: list[dict[str, Any]] = []
            album_source = 0
            album_output = 0
            album_warnings: list[str] = []
            album_blockers: list[str] = []
            matching = 0

            if rows:
                try:
                    resolved_folder = folder_path.resolve(strict=True)
                    if music_root != resolved_folder and music_root not in resolved_folder.parents:
                        album_blockers.append("Album folder is outside the configured music root")
                    else:
                        current_album_count = _physical_album_track_count(resolved_folder, albumartist, album)
                        if current_album_count != len(rows):
                            album_blockers.append(
                                f"Album track count changed since scan (indexed {len(rows)}, current {current_album_count}); rescan required"
                            )
                except OSError:
                    album_blockers.append("Album folder no longer exists; rescan required")

            for row in rows:
                item = dict(row)
                source_rate = int(item["sample_rate"] or 0)
                if not _matches_rate(source_rate, rate_set, above):
                    continue
                matching += 1
                source_size = int(item["size_bytes"])
                ratio = profile.target_rate / source_rate if source_rate else 1.0
                estimated = max(1, int(source_size * ratio * 1.10))
                source_path = Path(item["path"])
                track_blockers: list[str] = []
                command: list[str] = []
                profile_available = True
                profile_error = None
                current_mtime_ns: int | None = None
                if not source_path.exists():
                    track_blockers.append("Source file no longer exists; rescan required")
                else:
                    try:
                        resolved_source = source_path.resolve(strict=True)
                        if music_root not in resolved_source.parents:
                            track_blockers.append("Source file is outside the configured music root")
                        st = resolved_source.stat()
                        current_mtime_ns = int(st.st_mtime_ns)
                        if int(st.st_size) != source_size:
                            track_blockers.append(
                                f"Source size changed since scan ({source_size} -> {st.st_size}); rescan required"
                            )
                        if int(item.get("mtime_ns") or 0) != current_mtime_ns:
                            track_blockers.append("Source modification time changed since scan; rescan required")

                        detail = preview(resolved_source, profile)
                        if int(detail["sample_rate"]) != source_rate:
                            track_blockers.append(
                                f"Source sample rate changed since scan ({source_rate} -> {detail['sample_rate']}); rescan required"
                            )
                        if int(detail["bits_per_sample"]) != int(item.get("bits_per_sample") or 0):
                            track_blockers.append("Source bit depth changed since scan; rescan required")
                        if int(detail["channels"]) != int(item.get("channels") or 0):
                            track_blockers.append("Source channel count changed since scan; rescan required")

                        live_audio = FLAC(resolved_source)
                        for db_name, tag_name in KEY_TAGS:
                            indexed_value = (item.get(db_name) or "").strip()
                            live_value = (_first(live_audio, tag_name) or "").strip()
                            if live_value != indexed_value:
                                track_blockers.append(
                                    f"{tag_name} changed since scan ({indexed_value or '<missing>'} -> {live_value or '<missing>'}); rescan required"
                                )

                        track_blockers.extend(detail["preservation_blockers"])
                        command = detail["command"]
                        profile_available = bool(detail["profile_available"])
                        profile_error = detail["profile_error"]
                    except Exception as exc:
                        track_blockers.append(f"Preflight failed: {exc}")
                if not profile_available and profile_error and profile_error not in album_blockers:
                    album_blockers.append(profile_error)
                if track_blockers:
                    album_blockers.extend(f"{item['filename']}: {message}" for message in track_blockers)

                replaygain_complete = all(
                    item.get(name) is not None
                    for name in (
                        "replaygain_track_gain",
                        "replaygain_track_peak",
                        "replaygain_album_gain",
                        "replaygain_album_peak",
                    )
                )
                if not replaygain_complete and "ReplayGain incomplete" not in album_warnings:
                    album_warnings.append("ReplayGain incomplete")

                tracks.append(
                    {
                        "path": item["path"],
                        "filename": item["filename"],
                        "sample_rate": source_rate,
                        "bits_per_sample": item["bits_per_sample"],
                        "channels": item["channels"],
                        "duration": item["duration"],
                        "source_bytes": source_size,
                        "indexed_mtime_ns": int(item.get("mtime_ns") or 0),
                        "current_mtime_ns": current_mtime_ns,
                        "estimated_output_bytes": estimated,
                        "command": command,
                        "blockers": track_blockers,
                        "replaygain_complete": replaygain_complete,
                    }
                )
                album_source += source_size
                album_output += estimated
                all_output_estimates.append(estimated)

            if not matching:
                continue
            album_blockers = list(dict.fromkeys(album_blockers))
            album_entry = {
                "albumartist": albumartist,
                "album": album,
                "folder": folder,
                "indexed_tracks": len(rows),
                "matching_tracks": matching,
                "source_bytes": album_source,
                "estimated_output_bytes": album_output,
                "estimated_savings_bytes": max(0, album_source - album_output),
                "warnings": album_warnings,
                "blockers": album_blockers,
                "tracks": tracks,
            }
            albums.append(album_entry)
            total_source += album_source
            total_output += album_output
            total_matching += matching
            hard_blockers.extend(f"{albumartist} / {album}: {x}" for x in album_blockers)

    simultaneous_temp = sum(sorted(all_output_estimates, reverse=True)[:workers])
    profile_ready = bool(profile.implementation_ready)
    if not profile_ready:
        hard_blockers.append(f"Profile backend is not ready: {profile.name}")

    return {
        "profile": profile.to_dict(),
        "workers": workers,
        "albums": albums,
        "album_count": len(albums),
        "matching_tracks": total_matching,
        "source_bytes": total_source,
        "estimated_output_bytes": total_output,
        "estimated_savings_bytes": max(0, total_source - total_output),
        "estimated_peak_temp_bytes": simultaneous_temp,
        "reserve_bytes": reserve_bytes,
        "blockers": list(dict.fromkeys(hard_blockers)),
        "can_start": not hard_blockers and bool(albums) and profile_ready,
    }
