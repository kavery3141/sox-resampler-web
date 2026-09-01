from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import db
from .artwork import build_artwork_router
from .operations_log import record_event

DEFAULT_DAILY_SCAN_TIME = "10:00"
DEFAULT_RESERVE_BYTES = 10 * 1024**3
DAILY_SCAN_JOB_ID = "daily-library-scan"
DEFERRED_SCAN_JOB_ID = "deferred-daily-library-scan"


class DailyScanScheduleRequest(BaseModel):
    daily_scan_time: str = Field(min_length=5, max_length=5)


class ResetDefaultsRequest(BaseModel):
    confirmed: bool = False
    confirmed_disable_read_only: bool = False


def normalize_daily_scan_time(value: str) -> tuple[str, int, int]:
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
        raise ValueError("Daily scan time must use 24-hour HH:MM format")
    if not all(part.isdigit() for part in parts):
        raise ValueError("Daily scan time must use 24-hour HH:MM format")
    hour, minute = (int(parts[0]), int(parts[1]))
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Daily scan time is outside the valid 00:00 through 23:59 range")
    return f"{hour:02d}:{minute:02d}", hour, minute


def configured_daily_scan_time(db_path: Path) -> tuple[str, int, int]:
    raw = db.get_setting(db_path, "daily_scan_time", DEFAULT_DAILY_SCAN_TIME)
    try:
        return normalize_daily_scan_time(str(raw))
    except ValueError:
        return normalize_daily_scan_time(DEFAULT_DAILY_SCAN_TIME)


def _job_next_run(job: Any) -> str | None:
    if job is None:
        return None
    value = getattr(job, "next_run_time", None)
    return value.isoformat(timespec="seconds") if value is not None else None


def schedule_status(scheduler: Any, db_path: Path, timezone: str) -> dict[str, Any]:
    configured, _, _ = configured_daily_scan_time(db_path)
    return {
        "daily_scan_time": configured,
        "timezone": timezone,
        "next_run_time": _job_next_run(scheduler.get_job(DAILY_SCAN_JOB_ID)),
        "deferred_next_run_time": _job_next_run(scheduler.get_job(DEFERRED_SCAN_JOB_ID)),
        "defer_minutes_when_busy": 30,
    }


def configure_daily_scan_job(
    scheduler: Any,
    daily_scan: Callable[[], None],
    db_path: Path,
) -> dict[str, Any]:
    configured, hour, minute = configured_daily_scan_time(db_path)
    scheduler.add_job(
        daily_scan,
        "cron",
        hour=hour,
        minute=minute,
        id=DAILY_SCAN_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return {"daily_scan_time": configured, "hour": hour, "minute": minute}


def schedule_deferred_daily_scan(
    scheduler: Any,
    daily_scan: Callable[[], None],
    *,
    minutes: int = 30,
) -> str:
    delay = max(1, int(minutes))
    run_date = datetime.now(scheduler.timezone) + timedelta(minutes=delay)
    scheduler.add_job(
        daily_scan,
        "date",
        run_date=run_date,
        id=DEFERRED_SCAN_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return run_date.isoformat(timespec="seconds")


def build_settings_extras_router(
    *,
    db_path: Path,
    timezone: str,
    scheduler: Any,
    daily_scan: Callable[[], None],
    scanner: Any,
    job_manager: Any,
) -> APIRouter:
    router = APIRouter()
    tz = ZoneInfo(timezone)

    # This application-level router is already mounted by main.py. Compose the read-only artwork
    # serving API here so album thumbnails remain a distinct module without adding music-mount
    # reads to candidate/UI endpoints.
    router.include_router(build_artwork_router(db_path, db_path.parent))

    def now() -> str:
        return datetime.now(tz).isoformat(timespec="seconds")

    @router.get("/api/settings/schedule")
    def get_schedule() -> dict[str, Any]:
        return schedule_status(scheduler, db_path, timezone)

    @router.post("/api/settings/schedule")
    def set_schedule(request: DailyScanScheduleRequest) -> dict[str, Any]:
        try:
            normalized, _, _ = normalize_daily_scan_time(request.daily_scan_time)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.set_setting(db_path, "daily_scan_time", normalized)
        configure_daily_scan_job(scheduler, daily_scan, db_path)
        record_event(
            db_path,
            now(),
            "daily_scan_schedule_changed",
            {"daily_scan_time": normalized, "timezone": timezone},
        )
        return schedule_status(scheduler, db_path, timezone)

    @router.post("/api/settings/reset-defaults")
    def reset_defaults(request: ResetDefaultsRequest) -> dict[str, Any]:
        if not request.confirmed:
            raise HTTPException(status_code=400, detail="Reset to Defaults requires explicit confirmation")
        if job_manager.is_running() or scanner.snapshot()["running"]:
            raise HTTPException(
                status_code=409,
                detail="Defaults cannot be reset while a conversion or library scan is active",
            )
        read_only = bool(db.get_setting(db_path, "read_only_mode", False))
        if read_only and not request.confirmed_disable_read_only:
            raise HTTPException(
                status_code=400,
                detail="Resetting while Read-only Scan Mode is enabled requires explicit confirmation to disable it",
            )

        # Deliberately preserve exclusions, index data, history/logs and all custom presets.
        db.set_setting(db_path, "free_space_reserve_bytes", DEFAULT_RESERVE_BYTES)
        db.set_setting(db_path, "read_only_mode", False)
        db.set_setting(db_path, "daily_scan_time", DEFAULT_DAILY_SCAN_TIME)
        configure_daily_scan_job(scheduler, daily_scan, db_path)

        with db.session(db_path) as conn:
            custom_profiles = int(conn.execute("SELECT COUNT(*) c FROM custom_profiles").fetchone()["c"])
        exclude_paths = db.get_setting(db_path, "exclude_paths", []) or []
        exclude_globs = db.get_setting(db_path, "exclude_globs", []) or []
        result = {
            **schedule_status(scheduler, db_path, timezone),
            "read_only_mode": False,
            "free_space_reserve_bytes": DEFAULT_RESERVE_BYTES,
            "free_space_reserve_gb": 10.0,
            "preserved": {
                "exclude_paths": len(exclude_paths),
                "exclude_globs": len(exclude_globs),
                "custom_profiles": custom_profiles,
                "index": True,
                "history": True,
                "logs": True,
            },
        }
        record_event(db_path, now(), "settings_reset_defaults", result)
        return result

    return router
