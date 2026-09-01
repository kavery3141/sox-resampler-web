from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import db
from .operations_log import record_event

CPU_LIMIT_SETTING = "conversion_cpu_limit_percent"
CPU_LIMIT_MIN = 10
CPU_LIMIT_MAX = 100


class ResourceSettingsRequest(BaseModel):
    cpu_limit_percent: int | None = Field(default=None, ge=CPU_LIMIT_MIN, le=CPU_LIMIT_MAX)


def configured_cpu_limit(db_path: Path) -> int | None:
    raw = db.get_setting(db_path, CPU_LIMIT_SETTING, None)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if not CPU_LIMIT_MIN <= value <= CPU_LIMIT_MAX:
        return None
    return value


def cpulimit_available() -> bool:
    return shutil.which("cpulimit") is not None


def resource_status(db_path: Path, *, active_job_id: int | None = None) -> dict[str, Any]:
    limit = configured_cpu_limit(db_path)
    return {
        "cpu_limit_percent": limit,
        "enabled": limit is not None,
        "available": cpulimit_available(),
        "min_percent": CPU_LIMIT_MIN,
        "max_percent": CPU_LIMIT_MAX,
        "scope": "per-worker-sox",
        "takes_effect": "next-file",
        "active_job_id": active_job_id,
    }


def build_resource_control_router(
    db_path: Path,
    timezone: str,
    job_manager: Any,
) -> APIRouter:
    router = APIRouter()
    tz = ZoneInfo(timezone)

    def active_job_id() -> int | None:
        return job_manager.active_job_id()

    @router.get("/api/settings/resources")
    def get_resource_settings() -> dict[str, Any]:
        return resource_status(db_path, active_job_id=active_job_id())

    @router.post("/api/settings/resources")
    def set_resource_settings(request: ResourceSettingsRequest) -> dict[str, Any]:
        limit = request.cpu_limit_percent
        if limit is not None and not cpulimit_available():
            raise HTTPException(
                status_code=409,
                detail="Cannot enable the conversion CPU cap because cpulimit is unavailable",
            )
        db.set_setting(db_path, CPU_LIMIT_SETTING, limit)
        current_job = active_job_id()
        record_event(
            db_path,
            datetime.now(tz).isoformat(timespec="seconds"),
            "conversion_cpu_limit_changed",
            {
                "cpu_limit_percent": limit,
                "scope": "per-worker-sox",
                "takes_effect": "next-file",
                "active_job_id": current_job,
            },
        )
        return resource_status(db_path, active_job_id=current_job)

    return router
