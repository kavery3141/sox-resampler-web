from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import db
from .profile_store import get_profile as get_stored_profile
from .profiles import ResampleProfile, profile_from_dict

TERMINAL_HISTORY_STATUSES = ("completed", "cancelled", "stopped")
RESUMABLE_STATUSES = ("queued", "paused", "interrupted")
DEFAULT_HISTORY_DAYS = 180


class RetrySpecError(ValueError):
    pass


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _resolved_profile(db_path: Path, profile_id: str, raw_profile: str | None) -> ResampleProfile:
    if raw_profile:
        try:
            payload = json.loads(raw_profile)
        except json.JSONDecodeError as exc:
            raise RetrySpecError(f"Stored DSP snapshot is invalid: {exc}") from exc
        if not isinstance(payload, dict):
            raise RetrySpecError("Stored DSP snapshot is not an object")
        try:
            return profile_from_dict(payload)
        except ValueError as exc:
            raise RetrySpecError(f"Stored DSP snapshot is invalid: {exc}") from exc
    try:
        return get_stored_profile(db_path, profile_id)
    except ValueError as exc:
        raise RetrySpecError(
            "This legacy job does not contain a DSP snapshot and its original preset is unavailable"
        ) from exc


def is_clipping_failure(error: str | None) -> bool:
    text = str(error or "").casefold()
    return "clipping" in text or "clipped" in text or "exceeds full scale" in text


def _retry_spec(
    db_path: Path,
    job_id: int,
    *,
    predicate: Callable[[str | None], bool] | None = None,
    empty_message: str = "This job has no failed files to retry",
) -> dict[str, Any]:
    with db.session(db_path) as conn:
        job = conn.execute(
            "SELECT id,status,profile_id,profile_json,workers,source_filter_json FROM conversion_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if not job:
            raise RetrySpecError("Job not found")
        failed = conn.execute(
            """
            SELECT f.album_index,f.file_index,f.albumartist,f.album,f.path,f.error_text,t.folder
            FROM conversion_files f
            LEFT JOIN tracks t ON t.path=f.path
            WHERE f.job_id=? AND f.status='failed'
            ORDER BY f.album_index,f.file_index
            """,
            (job_id,),
        ).fetchall()

    selected = [row for row in failed if predicate is None or predicate(row["error_text"])]
    if not selected:
        raise RetrySpecError(empty_message)

    profile_id = str(job["profile_id"])
    profile = _resolved_profile(db_path, profile_id, job["profile_json"])
    source_filter = _json_object(job["source_filter_json"])
    rates = source_filter.get("rates")
    if not isinstance(rates, list):
        rates = []
    cleaned_rates: list[int] = []
    for value in rates:
        try:
            rate = int(value)
        except (TypeError, ValueError):
            continue
        if 8000 <= rate <= 768000:
            cleaned_rates.append(rate)
    above = source_filter.get("above")
    if above is not None:
        try:
            above = int(above)
        except (TypeError, ValueError):
            above = None

    albums: list[dict[str, str]] = []
    album_keys: set[tuple[str, str, str]] = set()
    paths: list[str] = []
    failures: list[dict[str, str]] = []
    for row in selected:
        path = str(row["path"])
        folder = str(row["folder"] or Path(path).parent)
        albumartist = str(row["albumartist"])
        album = str(row["album"])
        key = (albumartist, album, folder)
        if key not in album_keys:
            album_keys.add(key)
            albums.append({"albumartist": key[0], "album": key[1], "folder": key[2]})
        paths.append(path)
        failures.append(
            {
                "path": path,
                "error": str(row["error_text"] or "Conversion failed"),
                "albumartist": albumartist,
                "album": album,
                "folder": folder,
            }
        )

    return {
        "source_job_id": int(job_id),
        "source_job_status": str(job["status"]),
        "profile_id": profile_id,
        "profile": profile,
        "workers": 1,
        "original_workers": int(job["workers"] or 1),
        "rates": sorted(set(cleaned_rates)),
        "above": above,
        "albums": albums,
        "paths": paths,
        "failures": failures,
    }


def failed_retry_spec(db_path: Path, job_id: int) -> dict[str, Any]:
    """Return an exact-file retry specification without creating or starting a job."""
    return _retry_spec(db_path, job_id)


def clipping_retry_spec(
    db_path: Path,
    job_id: int,
    headroom_db: float | None = None,
) -> dict[str, Any]:
    """Return exact clipping failures with a more-negative headroom DSP snapshot.

    Headroom is an absolute value in the resolved retry profile. When omitted, the default adds
    1 dB of attenuation to the original job snapshot. The retry must always add headroom; it may
    never silently reuse or reduce the attenuation that already failed.
    """
    spec = _retry_spec(
        db_path,
        job_id,
        predicate=is_clipping_failure,
        empty_message="This job has no clipping failures eligible for Retry with Headroom",
    )
    original = float(spec["profile"].headroom_db or 0.0)
    if original <= -30.0:
        raise RetrySpecError("The original job already used the maximum supported -30 dB headroom")
    resolved = max(-30.0, original - 1.0) if headroom_db is None else float(headroom_db)
    if not -30.0 <= resolved < 0.0:
        raise RetrySpecError("Retry headroom must be between -30.0 dB and less than 0.0 dB")
    if resolved >= original:
        raise RetrySpecError(
            f"Retry headroom must add attenuation beyond the original {original:.1f} dB setting"
        )
    spec["original_headroom_db"] = original
    spec["headroom_db"] = resolved
    spec["profile"] = replace(spec["profile"], headroom_db=resolved)
    return spec


def _finished_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=ZoneInfo("UTC"))


def prune_job_history(
    db_path: Path,
    timezone: str,
    days: int = DEFAULT_HISTORY_DAYS,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prune only clean terminal jobs older than retention.

    Any job with a job-level error, failed file, or file-level error remains indefinitely until a
    deliberate Clear History action. Resumable jobs are never touched by retention pruning.
    """
    if days < 1:
        raise ValueError("History retention must be at least one day")
    tz = ZoneInfo(timezone)
    current = now.astimezone(tz) if now is not None else datetime.now(tz)
    cutoff = current - timedelta(days=days)
    with db.session(db_path) as conn:
        rows = conn.execute(
            "SELECT id,finished_at,error_text,status FROM conversion_jobs WHERE status IN (?,?,?)",
            TERMINAL_HISTORY_STATUSES,
        ).fetchall()
        delete_ids: list[int] = []
        protected = 0
        for row in rows:
            finished = _finished_timestamp(row["finished_at"])
            if finished is None or finished.astimezone(tz) >= cutoff:
                continue
            if str(row["error_text"] or "").strip():
                protected += 1
                continue
            file_problem = conn.execute(
                """
                SELECT 1 FROM conversion_files
                WHERE job_id=? AND (status='failed' OR COALESCE(TRIM(error_text),'')<>'')
                LIMIT 1
                """,
                (int(row["id"]),),
            ).fetchone()
            if file_problem:
                protected += 1
                continue
            delete_ids.append(int(row["id"]))
        for job_id in delete_ids:
            conn.execute("DELETE FROM conversion_jobs WHERE id=?", (job_id,))
    return {
        "retention_days": days,
        "cutoff": cutoff.isoformat(timespec="seconds"),
        "deleted_jobs": len(delete_ids),
        "protected_error_jobs": protected,
    }


def clear_terminal_history(db_path: Path) -> dict[str, int]:
    """Deliberately clear terminal history, including retained failures/errors.

    Queued, paused and interrupted jobs are intentionally preserved because they may still be
    resumed. Active running/control-transition jobs are also outside this operation.
    """
    with db.session(db_path) as conn:
        rows = conn.execute(
            "SELECT id FROM conversion_jobs WHERE status IN (?,?,?)",
            TERMINAL_HISTORY_STATUSES,
        ).fetchall()
        ids = [int(row["id"]) for row in rows]
        for job_id in ids:
            conn.execute("DELETE FROM conversion_jobs WHERE id=?", (job_id,))
    return {"deleted_jobs": len(ids)}


def history_summary(db_path: Path) -> dict[str, Any]:
    with db.session(db_path) as conn:
        total = int(conn.execute("SELECT COUNT(*) c FROM conversion_jobs").fetchone()["c"] or 0)
        terminal = int(
            conn.execute(
                "SELECT COUNT(*) c FROM conversion_jobs WHERE status IN (?,?,?)",
                TERMINAL_HISTORY_STATUSES,
            ).fetchone()["c"]
            or 0
        )
        resumable = int(
            conn.execute(
                "SELECT COUNT(*) c FROM conversion_jobs WHERE status IN (?,?,?)",
                RESUMABLE_STATUSES,
            ).fetchone()["c"]
            or 0
        )
        protected = int(
            conn.execute(
                """
                SELECT COUNT(DISTINCT j.id) c
                FROM conversion_jobs j
                LEFT JOIN conversion_files f ON f.job_id=j.id
                WHERE COALESCE(TRIM(j.error_text),'')<>''
                   OR f.status='failed'
                   OR COALESCE(TRIM(f.error_text),'')<>''
                """
            ).fetchone()["c"]
            or 0
        )
        oldest = conn.execute(
            "SELECT created_at FROM conversion_jobs ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
    return {
        "total_jobs": total,
        "terminal_jobs": terminal,
        "resumable_jobs": resumable,
        "protected_error_jobs": protected,
        "retention_days": DEFAULT_HISTORY_DAYS,
        "oldest_job_created_at": oldest["created_at"] if oldest else None,
    }
