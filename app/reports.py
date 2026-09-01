from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from . import db


def _result_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


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

    return {
        "job_id": int(job_id),
        "timezone": timezone,
        "status": job_data.get("status"),
        "created_at": job_data.get("created_at"),
        "started_at": job_data.get("started_at"),
        "finished_at": job_data.get("finished_at"),
        "profile_id": job_data.get("profile_id"),
        "workers": int(job_data.get("workers") or 1),
        "source_filter": source_filter,
        "album_order": album_order,
        "job_error": job_data.get("error_text"),
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
    lines = [
        "SoX Resampler Web - Conversion Report",
        f"Job: {report['job_id']}",
        f"Timezone: {report['timezone']}",
        f"Status: {report['status']}",
        f"Created: {report.get('created_at') or ''}",
        f"Started: {report.get('started_at') or ''}",
        f"Finished: {report.get('finished_at') or ''}",
        f"Preset: {report.get('profile_id') or ''}",
        f"Workers: {report.get('workers')}",
        f"Files: {totals['files']} total, {totals['completed']} completed, {totals['failed']} failed, {totals['remaining']} remaining",
        f"Source bytes: {totals['source_bytes']}",
        f"Final bytes: {totals['final_bytes']}",
        f"Savings bytes: {totals['savings_bytes']}",
    ]
    if report.get("job_error"):
        lines.append(f"Job message: {report['job_error']}")
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
    fieldnames = [
        "job_id",
        "timezone",
        "status",
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
