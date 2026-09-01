from __future__ import annotations

from pathlib import Path
from typing import Any

from . import db
from .converter import preview
from .profiles import ResampleProfile


def _matches_rate(sample_rate: int, rates: set[int], above: int | None) -> bool:
    return sample_rate in rates or (above is not None and sample_rate > above)


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

            for row in rows:
                item = dict(row)
                source_rate = int(item["sample_rate"] or 0)
                if not _matches_rate(source_rate, rate_set, above):
                    continue
                matching += 1
                source_size = int(item["size_bytes"])
                # FLAC ratio is content-dependent. Scale by PCM sample-rate ratio and add 10%
                # conservatism for temporary-space planning; this is explicitly an estimate.
                ratio = profile.target_rate / source_rate if source_rate else 1.0
                estimated = max(1, int(source_size * ratio * 1.10))
                source_path = Path(item["path"])
                track_blockers: list[str] = []
                command: list[str] = []
                profile_available = True
                profile_error = None
                if not source_path.exists():
                    track_blockers.append("Source file no longer exists; rescan required")
                else:
                    try:
                        detail = preview(source_path, profile)
                        track_blockers.extend(detail["preservation_blockers"])
                        command = detail["command"]
                        profile_available = bool(detail["profile_available"])
                        profile_error = detail["profile_error"]
                    except Exception as exc:
                        track_blockers.append(f"Preflight failed: {exc}")
                if not profile_available and profile_error:
                    if profile_error not in album_blockers:
                        album_blockers.append(profile_error)
                if track_blockers:
                    album_blockers.extend(f"{item['filename']}: {message}" for message in track_blockers)

                replaygain_complete = all(
                    item.get(name) is not None
                    for name in (
                        "replaygain_track_gain", "replaygain_track_peak",
                        "replaygain_album_gain", "replaygain_album_peak",
                    )
                )
                if not replaygain_complete and "ReplayGain incomplete" not in album_warnings:
                    album_warnings.append("ReplayGain incomplete")

                tracks.append({
                    "path": item["path"],
                    "filename": item["filename"],
                    "sample_rate": source_rate,
                    "bits_per_sample": item["bits_per_sample"],
                    "channels": item["channels"],
                    "duration": item["duration"],
                    "source_bytes": source_size,
                    "estimated_output_bytes": estimated,
                    "command": command,
                    "blockers": track_blockers,
                    "replaygain_complete": replaygain_complete,
                })
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

    statvfs = music_root.stat().st_dev if music_root.exists() else None
    del statvfs  # Path-level disk usage is supplied by the caller/status API; kept explicit here.
    simultaneous_temp = sum(sorted(all_output_estimates, reverse=True)[:workers])

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
        "can_start": not hard_blockers and bool(albums) and profile.exact_foobar_match,
    }
