from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from . import db
from .job_events import load_job_events


def _result_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _event_detail_text(event: dict[str, Any]) -> str:
    detail = event.get("detail") or {}
    event_type = str(event.get("event_type") or "")
    if event_type == "workers_changed":
        return f"workers {detail.get('from')} -> {detail.get('to')} (between files)"
    if event_type == "runtime_pause":
        return str(detail.get("reason") or "runtime safety pause")
    if event_type == "restart_interrupted":
        return f"restart interrupted previous status {detail.get('previous_status') or 'unknown'}"
    if event_type == "job_finished":
        text = f"status {detail.get('status') or ''}".strip()
        if detail.get("message"):
            text += f"; {detail['message']}"
        return text
    if event_type == "job_created":
        return f"workers {detail.get('workers')}; profile {detail.get('profile_id') or ''}"
    if event_type in {"job_started", "job_resumed"}:
        return f"from {detail.get('previous_status') or 'unknown'} with {detail.get('workers')} worker(s)"
    if event_type == "file_deferred_busy":
        return f"deferred {detail.get('path') or ''}; one end-of-batch retry"
    if event_type in {"pause_requested", "stop_after_album_requested", "cancel_requested"}:
        return f"from {detail.get('previous_status') or 'unknown'}"
    if detail:
        return json.dumps(detail, sort_keys=True, separators=(",", ":"))
    return ""


def _event_timeline_text(events: list[dict[str, Any]]) -> str:
    return " | ".join(
        f"{event.get('occurred_at') or ''} {event.get('event_type') or ''}: {_event_detail_text(event)}".strip()
        for event in events
    )


def render_review_txt(review: dict[str, Any], timezone: str) -> str:
    profile = review.get("profile") or {}
    lines = [
        "SoX Resampler Web - Pre-Conversion Review",
        f"Timezone: {timezone}",
        f"Preset: {profile.get('name') or profile.get('id') or ''}",
        f"Target sample rate: {profile.get('target_rate') or ''}",
        f"Bit depth: {profile.get('bit_depth') or ''}",
        f"Quality: {profile.get('quality') or ''}",
        f"Passband: {profile.get('passband_percent') if profile.get('passband_percent') is not None else ''}%",
        f"Phase response: {profile.get('phase_percent') if profile.get('phase_percent') is not None else ''}%",
        f"Allow aliasing: {'yes' if profile.get('allow_aliasing') else 'no'}",
        f"Dither: {profile.get('dither') or 'automatic TPDF when reducing bit depth'}",
        f"Headroom: {profile.get('headroom_db') if profile.get('headroom_db') is not None else 0.0} dB",
        f"FLAC compression: {profile.get('flac_compression') if profile.get('flac_compression') is not None else ''}",
        f"Workers: {review.get('workers') or ''}",
        f"Albums: {review.get('album_count') or 0}",
        f"Matching tracks: {review.get('matching_tracks') or 0}",
        f"Source bytes: {review.get('source_bytes') or 0}",
        f"Estimated output bytes: {review.get('estimated_output_bytes') or 0}",
        f"Estimated savings bytes: {review.get('estimated_savings_bytes') or 0}",
        f"Free bytes: {review.get('free_bytes') or 0}",
        f"Required free bytes: {review.get('required_free_bytes') or 0}",
        f"Can start: {'yes' if review.get('can_start') else 'no'}",
    ]
    blockers = review.get("blockers") or []
    if blockers:
        lines.extend(["", "Blockers:"])
        lines.extend(f"- {item}" for item in blockers)
    lines.extend(["", "Albums:"])
    for album in review.get("albums") or []:
        lines.append(
            f"{album.get('albumartist') or ''} / {album.get('album') or ''} / {album.get('folder') or ''}"
        )
        lines.append(
            "  "
            f"Matching tracks: {album.get('matching_tracks') or 0}; "
            f"Source bytes: {album.get('source_bytes') or 0}; "
            f"Estimated output bytes: {album.get('estimated_output_bytes') or 0}; "
            f"Estimated savings bytes: {album.get('estimated_savings_bytes') or 0}"
        )
        for warning in album.get("warnings") or []:
            lines.append(f"  Warning: {warning}")
        for blocker in album.get("blockers") or []:
            lines.append(f"  Blocker: {blocker}")
        for track in album.get("tracks") or []:
            lines.append(
                "  Track: "
                f"{track.get('path') or ''}; "
                f"{track.get('sample_rate') or ''} -> {track.get('target_rate') or profile.get('target_rate') or ''} Hz; "
                f"ratio {track.get('resample_ratio') or ''}; "
                f"{track.get('bits_per_sample') or ''} -> {track.get('target_bits_per_sample') or track.get('bits_per_sample') or ''}-bit; "
                f"dither {track.get('dither') or 'not applied'}; "
                f"{track.get('channels') or ''} channels; "
                f"{track.get('source_bytes') or 0} bytes"
            )
            if track.get("command"):
                lines.append(f"    Command: {' '.join(str(x) for x in track['command'])}")
    return "\n".join(lines) + "\n"


def render_review_csv(review: dict[str, Any], timezone: str) -> str:
    output = io.StringIO(newline="")
    fieldnames = [
        "timezone",
        "profile_id",
        "profile_name",
        "target_rate",
        "target_bit_depth",
        "quality",
        "passband_percent",
        "phase_percent",
        "allow_aliasing",
        "dither",
        "headroom_db",
        "flac_compression",
        "workers",
        "albumartist",
        "album",
        "folder",
        "path",
        "sample_rate",
        "resample_ratio",
        "bits_per_sample",
        "track_target_bits",
        "track_dither",
        "channels",
        "source_bytes",
        "estimated_output_bytes",
        "replaygain_complete",
        "warnings",
        "blockers",
        "command",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    profile = review.get("profile") or {}
    for album in review.get("albums") or []:
        warnings = " | ".join(str(x) for x in album.get("warnings") or [])
        album_blockers = " | ".join(str(x) for x in album.get("blockers") or [])
        for track in album.get("tracks") or []:
            track_blockers = " | ".join(str(x) for x in track.get("blockers") or [])
            writer.writerow(
                {
                    "timezone": timezone,
                    "profile_id": profile.get("id") or "",
                    "profile_name": profile.get("name") or "",
                    "target_rate": profile.get("target_rate") or "",
                    "target_bit_depth": profile.get("bit_depth") or "",
                    "quality": profile.get("quality") or "",
                    "passband_percent": profile.get("passband_percent") if profile.get("passband_percent") is not None else "",
                    "phase_percent": profile.get("phase_percent") if profile.get("phase_percent") is not None else "",
                    "allow_aliasing": bool(profile.get("allow_aliasing")),
                    "dither": profile.get("dither") or "automatic-tpdf",
                    "headroom_db": profile.get("headroom_db") if profile.get("headroom_db") is not None else 0.0,
                    "flac_compression": profile.get("flac_compression") if profile.get("flac_compression") is not None else "",
                    "workers": review.get("workers") or "",
                    "albumartist": album.get("albumartist") or "",
                    "album": album.get("album") or "",
                    "folder": album.get("folder") or "",
                    "path": track.get("path") or "",
                    "sample_rate": track.get("sample_rate") or "",
                    "resample_ratio": track.get("resample_ratio") or "",
                    "bits_per_sample": track.get("bits_per_sample") or "",
                    "track_target_bits": track.get("target_bits_per_sample") or "",
                    "track_dither": track.get("dither") or "",
                    "channels": track.get("channels") or "",
                    "source_bytes": track.get("source_bytes") or 0,
                    "estimated_output_bytes": track.get("estimated_output_bytes") or 0,
                    "replaygain_complete": bool(track.get("replaygain_complete")),
                    "warnings": warnings,
                    "blockers": " | ".join(x for x in (album_blockers, track_blockers) if x),
                    "command": " ".join(str(x) for x in track.get("command") or []),
                }
            )
    return output.getvalue()


def load_job_report(db_path: Path, job_id: int, timezone: str) -> dict[str, Any] | None:
    with db.session(db_path) as conn:
        job = conn.execute("SELECT * FROM conversion_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            return None
        files = conn.execute(
            "SELECT * FROM conversion_files WHERE job_id=? ORDER BY album_index,file_index",
            (job_id,),
        ).fetchall()

    file_rows: list[dict[str, Any]] = []
    source_bytes = 0
    final_bytes = 0
    completed = 0
    failed = 0
    pending = 0
    for row in files:
        item = dict(row)
        payload = _result_payload(item.get("result_json"))
        source_size = int(item.get("source_bytes") or 0)
        source_bytes += source_size
        final_size = source_size
        index_refresh = payload.get("index_refresh")
        if isinstance(index_refresh, dict) and index_refresh.get("size_bytes") is not None:
            final_size = int(index_refresh["size_bytes"])
        final_bytes += final_size
        status = str(item.get("status") or "")
        if status == "completed":
            completed += 1
        elif status == "failed":
            failed += 1
        else:
            pending += 1
        file_rows.append(
            {
                "albumartist": item.get("albumartist"),
                "album": item.get("album"),
                "path": item.get("path"),
                "status": status,
                "source_bytes": source_size,
                "final_bytes": final_size,
                "savings_bytes": max(0, source_size - final_size) if status == "completed" else 0,
                "started_at": item.get("started_at"),
                "finished_at": item.get("finished_at"),
                "error": item.get("error_text"),
                "source_rate": payload.get("source_rate"),
                "target_rate": payload.get("target_rate"),
                "source_bits": payload.get("source_bits"),
                "target_bits": payload.get("target_bits"),
                "temp_sha256": item.get("temp_sha256"),
                "final_sha256": item.get("final_sha256"),
                "index_refresh_error": payload.get("index_refresh_error"),
            }
        )

    job_data = dict(job)
    try:
        source_filter = json.loads(job_data.get("source_filter_json") or "{}")
    except json.JSONDecodeError:
        source_filter = {}
    try:
        album_order = json.loads(job_data.get("album_order_json") or "[]")
    except json.JSONDecodeError:
        album_order = []
    try:
        profile = json.loads(job_data.get("profile_json") or "{}")
    except json.JSONDecodeError:
        profile = {}
    if not isinstance(profile, dict):
        profile = {}
    events = load_job_events(db_path, job_id)

    return {
        "job_id": int(job_id),
        "timezone": timezone,
        "status": job_data.get("status"),
        "created_at": job_data.get("created_at"),
        "started_at": job_data.get("started_at"),
        "finished_at": job_data.get("finished_at"),
        "profile_id": job_data.get("profile_id"),
        "profile": profile,
        "workers": int(job_data.get("workers") or 1),
        "source_filter": source_filter,
        "album_order": album_order,
        "job_error": job_data.get("error_text"),
        "events": events,
        "totals": {
            "files": len(file_rows),
            "completed": completed,
            "failed": failed,
            "remaining": pending,
            "source_bytes": source_bytes,
            "final_bytes": final_bytes,
            "savings_bytes": max(0, source_bytes - final_bytes),
        },
        "files": file_rows,
    }


def render_job_txt(report: dict[str, Any]) -> str:
    totals = report["totals"]
    profile = report.get("profile") or {}
    lines = [
        "SoX Resampler Web - Conversion Report",
        f"Job: {report['job_id']}",
        f"Timezone: {report['timezone']}",
        f"Status: {report['status']}",
        f"Created: {report.get('created_at') or ''}",
        f"Started: {report.get('started_at') or ''}",
        f"Finished: {report.get('finished_at') or ''}",
        f"Preset: {profile.get('name') or report.get('profile_id') or ''}",
        f"Preset ID: {report.get('profile_id') or ''}",
        f"Target sample rate: {profile.get('target_rate') or ''}",
        f"Bit depth: {profile.get('bit_depth') or ''}",
        f"Quality: {profile.get('quality') or ''}",
        f"Passband: {profile.get('passband_percent') if profile.get('passband_percent') is not None else ''}%",
        f"Phase response: {profile.get('phase_percent') if profile.get('phase_percent') is not None else ''}%",
        f"Allow aliasing: {'yes' if profile.get('allow_aliasing') else 'no'}",
        f"Dither: {profile.get('dither') or 'automatic TPDF when reducing bit depth'}",
        f"Headroom: {profile.get('headroom_db') if profile.get('headroom_db') is not None else 0.0} dB",
        f"FLAC compression: {profile.get('flac_compression') if profile.get('flac_compression') is not None else ''}",
        f"Final concurrency: {report.get('workers')}",
        f"Files: {totals['files']} total, {totals['completed']} completed, {totals['failed']} failed, {totals['remaining']} remaining",
        f"Source bytes: {totals['source_bytes']}",
        f"Final bytes: {totals['final_bytes']}",
        f"Savings bytes: {totals['savings_bytes']}",
    ]
    if report.get("job_error"):
        lines.append(f"Job message: {report['job_error']}")
    events = report.get("events") or []
    if events:
        lines.extend(["", "Job event timeline:"])
        for event in events:
            detail = _event_detail_text(event)
            suffix = f" - {detail}" if detail else ""
            lines.append(
                f"- {event.get('occurred_at') or ''} [{event.get('event_type') or ''}]{suffix}"
            )
    lines.extend(["", "Files:"])
    for item in report["files"]:
        lines.append(
            f"[{item['status']}] {item.get('albumartist') or ''} / {item.get('album') or ''} / {item.get('path') or ''}"
        )
        lines.append(
            "  "
            f"Rate: {item.get('source_rate') or ''} -> {item.get('target_rate') or ''}; "
            f"Bits: {item.get('source_bits') or ''} -> {item.get('target_bits') or ''}; "
            f"Bytes: {item['source_bytes']} -> {item['final_bytes']}; "
            f"Savings: {item['savings_bytes']}"
        )
        if item.get("error"):
            lines.append(f"  Error: {item['error']}")
        if item.get("index_refresh_error"):
            lines.append(f"  Index refresh warning: {item['index_refresh_error']}")
        if item.get("final_sha256"):
            lines.append(f"  SHA-256: {item['final_sha256']}")
    return "\n".join(lines) + "\n"


def render_job_csv(report: dict[str, Any]) -> str:
    output = io.StringIO(newline="")
    profile = report.get("profile") or {}
    event_timeline = _event_timeline_text(report.get("events") or [])
    fieldnames = [
        "job_id",
        "timezone",
        "status",
        "profile_id",
        "profile_name",
        "quality",
        "passband_percent",
        "phase_percent",
        "allow_aliasing",
        "dither",
        "headroom_db",
        "flac_compression",
        "final_concurrency",
        "job_event_timeline",
        "albumartist",
        "album",
        "path",
        "source_rate",
        "target_rate",
        "source_bits",
        "target_bits",
        "source_bytes",
        "final_bytes",
        "savings_bytes",
        "started_at",
        "finished_at",
        "error",
        "index_refresh_error",
        "final_sha256",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for item in report["files"]:
        writer.writerow(
            {
                "job_id": report["job_id"],
                "timezone": report["timezone"],
                "status": item["status"],
                "profile_id": report.get("profile_id") or "",
                "profile_name": profile.get("name") or "",
                "quality": profile.get("quality") or "",
                "passband_percent": profile.get("passband_percent") if profile.get("passband_percent") is not None else "",
                "phase_percent": profile.get("phase_percent") if profile.get("phase_percent") is not None else "",
                "allow_aliasing": bool(profile.get("allow_aliasing")),
                "dither": profile.get("dither") or "automatic-tpdf",
                "headroom_db": profile.get("headroom_db") if profile.get("headroom_db") is not None else 0.0,
                "flac_compression": profile.get("flac_compression") if profile.get("flac_compression") is not None else "",
                "final_concurrency": report.get("workers") or "",
                "job_event_timeline": event_timeline,
                "albumartist": item.get("albumartist") or "",
                "album": item.get("album") or "",
                "path": item.get("path") or "",
                "source_rate": item.get("source_rate") or "",
                "target_rate": item.get("target_rate") or "",
                "source_bits": item.get("source_bits") or "",
                "target_bits": item.get("target_bits") or "",
                "source_bytes": item["source_bytes"],
                "final_bytes": item["final_bytes"],
                "savings_bytes": item["savings_bytes"],
                "started_at": item.get("started_at") or "",
                "finished_at": item.get("finished_at") or "",
                "error": item.get("error") or "",
                "index_refresh_error": item.get("index_refresh_error") or "",
                "final_sha256": item.get("final_sha256") or "",
            }
        )
    return output.getvalue()
