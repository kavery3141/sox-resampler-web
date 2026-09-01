from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from mutagen.flac import FLAC

from . import db
from .converter import preview
from .profiles import ResampleProfile
from .resource_control import configured_cpu_limit


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


def _ratio_label(source_rate: int, target_rate: int) -> str:
    if source_rate <= 0 or target_rate <= 0:
        return "unknown"
    factor = source_rate / target_rate
    if factor >= 1:
        rounded = round(factor)
        if math.isclose(factor, rounded, rel_tol=0, abs_tol=1e-9):
            return f"{rounded}:1"
        return f"{factor:.4f}:1"
    inverse = target_rate / source_rate
    rounded = round(inverse)
    if math.isclose(inverse, rounded, rel_tol=0, abs_tol=1e-9):
        return f"1:{rounded}"
    return f"1:{inverse:.4f}"


def _dither_label(profile: ResampleProfile) -> str:
    if profile.dither in (None, "tpdf"):
        return "TPDF"
    if profile.dither == "shibata":
        return "Shibata noise-shaped"
    if profile.dither == "none":
        return "disabled"
    return str(profile.dither)


def _technical_warnings(source_rate: int, source_bits: int, profile: ResampleProfile) -> list[str]:
    warnings: list[str] = []
    target_rate = int(profile.target_rate)
    target_bits = source_bits if profile.bit_depth == "preserve" else int(profile.bit_depth)
    if target_rate > source_rate > 0:
        warnings.append(
            f"Upsampling {source_rate / 1000:g} kHz to {target_rate / 1000:g} kHz"
        )
    if source_rate > 0 and source_rate % 44100 == 0 and target_rate % 48000 == 0:
        warnings.append(
            "44.1 kHz-family source to 48 kHz-family target uses a non-integer resampling ratio"
        )
    if target_bits < source_bits:
        dither = _dither_label(profile)
        warnings.append(
            f"Bit-depth reduction {source_bits}-bit to {target_bits}-bit; dither: {dither}"
        )
    return warnings


def build_batch_review(
    db_path: Path,
    music_root: Path,
    album_keys: list[dict[str, str]],
    rates: list[int],
    above: int | None,
    profile: ResampleProfile,
    workers: int,
    reserve_bytes: int,
    include_paths: set[str] | None = None,
) -> dict[str, Any]:
    """Build and revalidate a destructive batch review.

    Album identity is ALBUMARTIST + ALBUM. All indexed physical folders carrying that identity are
    reviewed together so multi-disc releases remain one batch album even when discs are stored in
    separate subfolders. Retry batches pass ``include_paths`` so only exact failed source files are
    selected while the complete album identity is still revalidated.
    """
    if workers not in (1, 2):
        raise ValueError("Workers must be 1 or 2")
    music_root = music_root.resolve()
    rate_set = set(rates)
    exact_paths = {str(Path(path)) for path in include_paths} if include_paths is not None else None
    albums: list[dict[str, Any]] = []
    all_output_estimates: list[int] = []
    total_source = 0
    total_output = 0
    total_matching = 0
    hard_blockers: list[str] = []
    seen_exact_paths: set[str] = set()
    cpu_limit_percent = configured_cpu_limit(db_path)

    with db.session(db_path) as conn:
        mbid_identity_rows = conn.execute(
            """
            SELECT
              TRIM(musicbrainz_albumid) mbid,
              COALESCE(TRIM(albumartist),'') albumartist,
              COALESCE(TRIM(album),'') album
            FROM tracks
            WHERE musicbrainz_albumid IS NOT NULL AND TRIM(musicbrainz_albumid)<>''
            GROUP BY mbid,albumartist,album
            """
        ).fetchall()
        mbid_identities: dict[str, set[tuple[str, str]]] = {}
        for item in mbid_identity_rows:
            mbid_identities.setdefault(str(item["mbid"]), set()).add(
                (str(item["albumartist"]), str(item["album"]))
            )

        for key in album_keys:
            albumartist = key.get("albumartist", "")
            album = key.get("album", "")
            requested_folder = key.get("folder", "")
            rows = conn.execute(
                """
                SELECT * FROM tracks
                WHERE COALESCE(albumartist,'')=? AND COALESCE(album,'')=?
                ORDER BY CAST(COALESCE(discnumber,'1') AS INTEGER),
                         CAST(COALESCE(tracknumber,'0') AS INTEGER),
                         folder COLLATE NOCASE,filename COLLATE NOCASE
                """,
                (albumartist, album),
            ).fetchall()
            tracks: list[dict[str, Any]] = []
            album_source = 0
            album_output = 0
            album_warnings: list[str] = []
            album_blockers: list[str] = []
            matching = 0

            indexed_items = [dict(row) for row in rows]
            for field, tag_name in KEY_TAGS:
                values = sorted({
                    str(item.get(field) or "").strip()
                    for item in indexed_items
                    if str(item.get(field) or "").strip()
                }, key=str.casefold)
                missing_count = sum(
                    1 for item in indexed_items if not str(item.get(field) or "").strip()
                )
                if missing_count:
                    album_blockers.append(
                        f"{tag_name} missing on {missing_count} indexed track(s) across logical album"
                    )
                if len(values) > 1:
                    album_blockers.append(
                        f"{tag_name} inconsistent across logical album: {' | '.join(values)}"
                    )

            selected_mbids = sorted({
                str(item.get("musicbrainz_albumid") or "").strip()
                for item in indexed_items
                if str(item.get("musicbrainz_albumid") or "").strip()
            })
            for mbid in selected_mbids:
                identities = mbid_identities.get(mbid, set())
                if len(identities) > 1:
                    identity_text = "; ".join(
                        f"{artist or '<missing>'} / {title or '<missing>'}"
                        for artist, title in sorted(identities, key=lambda value: (value[0].casefold(), value[1].casefold()))
                    )
                    album_blockers.append(
                        f"MUSICBRAINZ_ALBUMID {mbid} maps to conflicting ALBUMARTIST/ALBUM identities in the index: {identity_text}"
                    )

            folder_counts: dict[str, int] = {}
            for row in rows:
                folder_text = str(row["folder"])
                folder_counts[folder_text] = folder_counts.get(folder_text, 0) + 1
            folders = sorted(folder_counts, key=str.casefold)
            display_folder = requested_folder if requested_folder in folder_counts else (folders[0] if folders else requested_folder)

            # Revalidate every physical directory participating in this logical album. This catches
            # added/removed tracks without splitting Disc 1 / Disc 2 into separate conversion rows.
            for folder_text in folders:
                folder_path = Path(folder_text)
                try:
                    resolved_folder = folder_path.resolve(strict=True)
                    if music_root != resolved_folder and music_root not in resolved_folder.parents:
                        album_blockers.append(f"Album folder is outside the configured music root: {folder_text}")
                        continue
                    current_album_count = _physical_album_track_count(resolved_folder, albumartist, album)
                    indexed_count = folder_counts[folder_text]
                    if current_album_count != indexed_count:
                        album_blockers.append(
                            f"Album track count changed since scan in {folder_text} "
                            f"(indexed {indexed_count}, current {current_album_count}); rescan required"
                        )
                except OSError:
                    album_blockers.append(f"Album folder no longer exists; rescan required: {folder_text}")

            for row in rows:
                item = dict(row)
                indexed_path = str(item["path"])
                source_rate = int(item["sample_rate"] or 0)
                if exact_paths is not None:
                    if indexed_path not in exact_paths:
                        continue
                    seen_exact_paths.add(indexed_path)
                elif not _matches_rate(source_rate, rate_set, above):
                    continue
                matching += 1
                source_size = int(item["size_bytes"])
                source_bits = int(item.get("bits_per_sample") or 0)
                target_bits = source_bits if profile.bit_depth == "preserve" else int(profile.bit_depth)
                ratio = profile.target_rate / source_rate if source_rate else 1.0
                estimated = max(1, int(source_size * ratio * 1.10))
                source_path = Path(indexed_path)
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

                        if cpu_limit_percent is None:
                            # Keep the default uncapped preflight call compatible with ordinary
                            # preview consumers and mocks. CPU control is operational, not DSP.
                            detail = preview(resolved_source, profile)
                        else:
                            detail = preview(
                                resolved_source,
                                profile,
                                cpu_limit_percent=cpu_limit_percent,
                            )
                        if int(detail["sample_rate"]) != source_rate:
                            track_blockers.append(
                                f"Source sample rate changed since scan ({source_rate} -> {detail['sample_rate']}); rescan required"
                            )
                        if int(detail["bits_per_sample"]) != source_bits:
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
                for warning in _technical_warnings(source_rate, source_bits, profile):
                    if warning not in album_warnings:
                        album_warnings.append(warning)

                dither_applied = None
                if target_bits < source_bits:
                    dither_applied = _dither_label(profile)
                tracks.append(
                    {
                        "path": indexed_path,
                        "folder": item["folder"],
                        "filename": item["filename"],
                        "discnumber": item.get("discnumber"),
                        "tracknumber": item.get("tracknumber"),
                        "sample_rate": source_rate,
                        "target_rate": profile.target_rate,
                        "resample_ratio": _ratio_label(source_rate, profile.target_rate),
                        "bits_per_sample": source_bits,
                        "target_bits_per_sample": target_bits,
                        "dither": dither_applied,
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
                "folder": display_folder,
                "folders": folders,
                "folder_count": len(folders),
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

    if exact_paths is not None:
        missing_from_index = sorted(exact_paths - seen_exact_paths)
        for path in missing_from_index:
            hard_blockers.append(f"Retry source is no longer present in the local index: {path}; rescan required")

    simultaneous_temp = sum(sorted(all_output_estimates, reverse=True)[:workers])
    profile_ready = bool(profile.implementation_ready)
    if not profile_ready:
        hard_blockers.append(f"Profile backend is not ready: {profile.name}")

    return {
        "profile": profile.to_dict(),
        "workers": workers,
        "cpu_limit_percent": cpu_limit_percent,
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
