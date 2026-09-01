from __future__ import annotations

import fnmatch
import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import psutil
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import db
from .force_stop import request_abort
from .job_maintenance import clear_terminal_history, history_summary
from .operations_log import log_disk_usage, recent_events, record_event
from .storage_health import zfs_pool_health

DEFAULT_RESERVE_BYTES = 10 * 1024**3


class ReadOnlyRequest(BaseModel):
    enabled: bool
    confirmed_disable: bool = False


class StorageSettingsRequest(BaseModel):
    free_space_reserve_gb: float = Field(ge=1, le=10240)
    exclude_paths: list[str] = Field(default_factory=list, max_length=250)
    exclude_globs: list[str] = Field(default_factory=list, max_length=250)


class ExclusionPreviewRequest(BaseModel):
    exclude_paths: list[str] = Field(default_factory=list, max_length=250)
    exclude_globs: list[str] = Field(default_factory=list, max_length=250)


class ConfirmMaintenanceRequest(BaseModel):
    confirmed: bool = False


class ForceStopRequest(BaseModel):
    file_id: int = Field(gt=0)


def _tool_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def _normalize_exclusions(music_root: Path, paths: list[str], globs: list[str]) -> tuple[list[str], list[str]]:
    root = music_root.resolve()
    normalized_paths: list[str] = []
    for raw in paths:
        text = str(raw).strip()
        if not text:
            continue
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve(strict=False)
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"Excluded path must be inside the music root: {text}")
        normalized_paths.append(str(resolved))

    normalized_globs: list[str] = []
    for raw in globs:
        pattern = str(raw).strip().replace("\\", "/")
        if not pattern:
            continue
        if "\x00" in pattern:
            raise ValueError("Exclusion glob contains an invalid NUL character")
        normalized_globs.append(pattern)

    return sorted(set(normalized_paths)), sorted(set(normalized_globs))


def _excluded(path: Path, music_root: Path, exact: set[str], globs: list[str]) -> bool:
    text = str(path.resolve(strict=False))
    if text in exact:
        return True
    try:
        rel = path.resolve(strict=False).relative_to(music_root.resolve()).as_posix()
    except ValueError:
        return False
    return any(fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(text, pattern) for pattern in globs)


def _preview_exclusions(music_root: Path, exact: list[str], globs: list[str]) -> dict[str, int]:
    if not music_root.exists():
        return {"folders": 0, "flac_files": 0}
    exact_set = set(exact)
    folder_count = 0
    flac_count = 0
    for root, dirs, files in os.walk(music_root, followlinks=False):
        root_path = Path(root)
        kept: list[str] = []
        for dirname in dirs:
            child = root_path / dirname
            if child.is_symlink():
                continue
            if _excluded(child, music_root, exact_set, globs):
                folder_count += 1
                for _, _, subfiles in os.walk(child, followlinks=False):
                    flac_count += sum(1 for name in subfiles if name.lower().endswith(".flac") and not name.startswith("."))
                continue
            kept.append(dirname)
        dirs[:] = kept
        if _excluded(root_path, music_root, exact_set, globs):
            continue
        for name in files:
            path = root_path / name
            if name.startswith(".") or path.is_symlink() or not name.lower().endswith(".flac"):
                continue
            if _excluded(path, music_root, exact_set, globs):
                flac_count += 1
    return {"folders": folder_count, "flac_files": flac_count}


def _timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return None


def _job_runtime_times(db_path: Path, job_id: int) -> dict[str, float | int | str | None]:
    now = datetime.now().astimezone().timestamp()
    terminal = {"completed", "cancelled", "stopped"}
    with db.session(db_path) as conn:
        job = conn.execute(
            "SELECT status,started_at,finished_at FROM conversion_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if not job:
            return {
                "status": None,
                "wall_seconds": 0.0,
                "active_seconds": 0.0,
                "paused_or_idle_seconds": 0.0,
                "active_files": 0,
            }
        rows = conn.execute(
            "SELECT status,started_at,finished_at FROM conversion_files "
            "WHERE job_id=? AND started_at IS NOT NULL",
            (job_id,),
        ).fetchall()

    start = _timestamp(job["started_at"])
    if start is None:
        return {
            "status": str(job["status"]),
            "wall_seconds": 0.0,
            "active_seconds": 0.0,
            "paused_or_idle_seconds": 0.0,
            "active_files": 0,
        }
    end = _timestamp(job["finished_at"]) if str(job["status"]) in terminal else now
    end = max(start, end if end is not None else now)

    intervals: list[tuple[float, float]] = []
    active_files = 0
    for row in rows:
        row_start = _timestamp(row["started_at"])
        if row_start is None:
            continue
        row_end = _timestamp(row["finished_at"])
        if row_end is None and str(row["status"]) == "running":
            row_end = now
            active_files += 1
        if row_end is None:
            continue
        a = max(start, row_start)
        b = min(end, max(row_start, row_end))
        if b > a:
            intervals.append((a, b))

    intervals.sort()
    merged: list[list[float]] = []
    for a, b in intervals:
        if not merged or a > merged[-1][1]:
            merged.append([a, b])
        else:
            merged[-1][1] = max(merged[-1][1], b)
    active_seconds = sum(b - a for a, b in merged)
    wall_seconds = max(0.0, end - start)
    return {
        "status": str(job["status"]),
        "wall_seconds": round(wall_seconds, 3),
        "active_seconds": round(active_seconds, 3),
        "paused_or_idle_seconds": round(max(0.0, wall_seconds - active_seconds), 3),
        "active_files": active_files,
    }


def build_admin_router(
    *,
    db_path: Path,
    music_root: Path,
    data_root: Path,
    timezone: str,
    app_version: str,
    scanner: Any,
    job_manager: Any,
    scan_async: Callable[[str], dict[str, Any]],
    recovery_status: Callable[[], list[dict[str, str]]],
) -> APIRouter:
    router = APIRouter()
    tz = ZoneInfo(timezone)

    def event_time() -> str:
        return datetime.now(tz).isoformat(timespec="seconds")

    def resumable_scan() -> dict[str, Any] | None:
        latest = db.latest_scan(db_path)
        if not latest:
            return None
        if latest.get("status") not in {"paused", "interrupted"}:
            return None
        if latest.get("mode") not in {"full", "full-resume"}:
            return None
        return latest

    @router.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        reserve = int(db.get_setting(db_path, "free_space_reserve_bytes", DEFAULT_RESERVE_BYTES))
        return {
            "read_only_mode": bool(db.get_setting(db_path, "read_only_mode", False)),
            "free_space_reserve_bytes": reserve,
            "free_space_reserve_gb": round(reserve / 1024**3, 3),
            "exclude_paths": db.get_setting(db_path, "exclude_paths", []) or [],
            "exclude_globs": db.get_setting(db_path, "exclude_globs", []) or [],
            "timezone": timezone,
        }

    @router.post("/api/settings/read-only")
    def set_read_only(request: ReadOnlyRequest) -> dict[str, Any]:
        current = bool(db.get_setting(db_path, "read_only_mode", False))
        if current and not request.enabled and not request.confirmed_disable:
            raise HTTPException(status_code=400, detail="Disabling Read-only Scan Mode requires explicit confirmation")
        if not request.enabled and job_manager.is_running():
            raise HTTPException(status_code=409, detail="Cannot disable Read-only Scan Mode while a conversion job is active")
        db.set_setting(db_path, "read_only_mode", bool(request.enabled))
        record_event(db_path, event_time(), "read_only_mode_changed", {"enabled": bool(request.enabled)})
        return {"read_only_mode": bool(request.enabled)}

    @router.post("/api/settings/storage")
    def set_storage_settings(request: StorageSettingsRequest) -> dict[str, Any]:
        if job_manager.is_running() or scanner.snapshot()["running"]:
            raise HTTPException(status_code=409, detail="Storage settings cannot change while a conversion or scan is active")
        try:
            exact, globs = _normalize_exclusions(music_root, request.exclude_paths, request.exclude_globs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        reserve = int(request.free_space_reserve_gb * 1024**3)
        db.set_setting(db_path, "free_space_reserve_bytes", reserve)
        db.set_setting(db_path, "exclude_paths", exact)
        db.set_setting(db_path, "exclude_globs", globs)
        record_event(
            db_path,
            event_time(),
            "storage_settings_changed",
            {"free_space_reserve_bytes": reserve, "exclude_paths": len(exact), "exclude_globs": len(globs)},
        )
        return {
            "free_space_reserve_bytes": reserve,
            "free_space_reserve_gb": round(reserve / 1024**3, 3),
            "exclude_paths": exact,
            "exclude_globs": globs,
        }

    @router.post("/api/settings/exclusions/preview")
    def preview_exclusions(request: ExclusionPreviewRequest) -> dict[str, Any]:
        try:
            exact, globs = _normalize_exclusions(music_root, request.exclude_paths, request.exclude_globs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {**_preview_exclusions(music_root, exact, globs), "exclude_paths": exact, "exclude_globs": globs}

    @router.get("/api/runtime/metrics")
    def runtime_metrics(job_id: int | None = None) -> dict[str, Any]:
        disk = psutil.disk_io_counters()
        process = psutil.Process()
        selected_job_id = job_id if job_id is not None else job_manager.active_job_id()
        job_times = _job_runtime_times(db_path, selected_job_id) if selected_job_id is not None else {
            "status": None,
            "wall_seconds": 0.0,
            "active_seconds": 0.0,
            "paused_or_idle_seconds": 0.0,
            "active_files": 0,
        }
        recovery = recovery_status()
        recovery_blocked = any(
            item.get("action") == "manual_attention"
            or str(item.get("action", "")).startswith("recovery_error")
            for item in recovery
        )
        active_files = int(job_times["active_files"] or 0)
        safe_to_restart = active_files == 0 and not recovery_blocked
        if recovery_blocked:
            restart_reason = "An interrupted file transaction or orphan temp needs manual attention"
        elif active_files:
            restart_reason = "Wait for the current file conversion to finish"
        else:
            restart_reason = "No audio file is actively being converted"
        return {
            "scope": "system-visible-from-container",
            "cpu_percent": psutil.cpu_percent(interval=0.05),
            "memory_percent": psutil.virtual_memory().percent,
            "process_rss_bytes": process.memory_info().rss,
            "disk_read_bytes_total": int(disk.read_bytes) if disk else None,
            "disk_write_bytes_total": int(disk.write_bytes) if disk else None,
            "job_id": selected_job_id,
            "job_time": job_times,
            "safe_to_restart": safe_to_restart,
            "safe_to_restart_reason": restart_reason,
        }

    @router.get("/api/maintenance/status")
    def maintenance_status() -> dict[str, Any]:
        db_size = db_path.stat().st_size if db_path.exists() else 0
        wal = db_path.with_name(db_path.name + "-wal")
        shm = db_path.with_name(db_path.name + "-shm")
        usage = psutil.disk_usage(str(music_root)) if music_root.exists() else None
        return {
            "app_version": app_version,
            "db_schema": db.SCHEMA_VERSION,
            "database": {
                "path": str(db_path),
                "size_bytes": db_size,
                "wal_bytes": wal.stat().st_size if wal.exists() else 0,
                "shm_bytes": shm.stat().st_size if shm.exists() else 0,
            },
            "library": db.library_summary(db_path),
            "history": history_summary(db_path),
            "logs": log_disk_usage(data_root),
            "maintenance_events": recent_events(db_path, 25),
            "latest_scan": db.latest_scan(db_path),
            "scan": scanner.snapshot(),
            "scan_resumable": resumable_scan(),
            "conversion_running": bool(job_manager.is_running()),
            "music_root": str(music_root),
            "data_root": str(data_root),
            "free_bytes": usage.free if usage else None,
            "timezone": timezone,
            "zfs": zfs_pool_health(),
            "transaction_recovery": recovery_status(),
            "tools": {
                "sox": _tool_version(["sox", "--version"]),
                "flac": _tool_version(["flac", "--version"]),
                "metaflac": _tool_version(["metaflac", "--version"]),
                "python": _tool_version(["python", "--version"]),
            },
        }

    @router.post("/api/convert/jobs/{job_id}/force-stop")
    def force_stop_file(job_id: int, request: ForceStopRequest) -> dict[str, Any]:
        with db.session(db_path) as conn:
            row = conn.execute(
                "SELECT id,path,status FROM conversion_files WHERE id=? AND job_id=?",
                (request.file_id, job_id),
            ).fetchone()
            job = conn.execute("SELECT id,status FROM conversion_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if not row:
            raise HTTPException(status_code=404, detail="File is not part of this conversion job")
        if row["status"] != "running":
            raise HTTPException(status_code=409, detail="That file is no longer actively converting")
        if not request_abort(row["path"]):
            raise HTTPException(
                status_code=409,
                detail="The converter is between cancellable stages; refresh before trying again",
            )
        result = {
            "job_id": job_id,
            "file_id": int(row["id"]),
            "path": row["path"],
            "status": "force-stop-requested",
        }
        record_event(db_path, event_time(), "force_stop_requested", result)
        return result

    @router.post("/api/scan/pause")
    def pause_full_scan() -> dict[str, Any]:
        if not scanner.request_pause():
            raise HTTPException(status_code=409, detail="Only an active full scan or index rebuild can be paused")
        result = scanner.snapshot()
        record_event(
            db_path,
            event_time(),
            "scan_pause_requested",
            {"scan_id": result.get("run_id"), "mode": result.get("mode")},
        )
        return result

    @router.post("/api/scan/resume")
    def resume_full_scan() -> dict[str, Any]:
        if job_manager.is_running():
            raise HTTPException(status_code=409, detail="A conversion job is running; scan resume waits until it finishes or pauses")
        if scanner.snapshot()["running"]:
            raise HTTPException(status_code=409, detail="A scan is already active")
        previous = resumable_scan()
        if not previous:
            raise HTTPException(status_code=409, detail="There is no paused or interrupted full scan to resume")
        result = scan_async("full-resume")
        record_event(
            db_path,
            event_time(),
            "scan_resume_requested",
            {"resume_of_scan_id": previous.get("id"), "previous_status": previous.get("status")},
        )
        return {**result, "resume_of_scan_id": previous.get("id")}

    @router.post("/api/maintenance/vacuum")
    def vacuum_database() -> dict[str, Any]:
        if job_manager.is_running() or scanner.snapshot()["running"]:
            raise HTTPException(status_code=409, detail="Database maintenance waits until conversion and scanning are idle")
        with sqlite3.connect(db_path, timeout=30) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("VACUUM")
        result = {"ok": True, "size_bytes": db_path.stat().st_size if db_path.exists() else 0}
        record_event(db_path, event_time(), "database_vacuum", result)
        return result

    @router.post("/api/maintenance/full-rescan")
    def full_rescan() -> dict[str, Any]:
        result = scan_async("full")
        record_event(db_path, event_time(), "full_rescan_requested", {})
        return result

    @router.post("/api/maintenance/rebuild-index")
    def rebuild_index() -> dict[str, Any]:
        if job_manager.is_running() or scanner.snapshot()["running"]:
            raise HTTPException(status_code=409, detail="Index rebuild waits until conversion and scanning are idle")
        with db.session(db_path) as conn:
            conn.execute("DELETE FROM tracks")
        result = scan_async("full")
        record_event(db_path, event_time(), "index_rebuild_requested", {})
        return result

    @router.post("/api/maintenance/history/clear")
    def clear_history(request: ConfirmMaintenanceRequest) -> dict[str, Any]:
        if not request.confirmed:
            raise HTTPException(status_code=400, detail="Clearing terminal conversion history requires explicit confirmation")
        if job_manager.is_running():
            raise HTTPException(status_code=409, detail="Conversion history cannot be cleared while a job is active")
        result = clear_terminal_history(db_path)
        record_event(db_path, event_time(), "conversion_history_cleared", result)
        return {**result, "history": history_summary(db_path)}

    return router
