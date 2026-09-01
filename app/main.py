from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import psutil
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .admin import build_admin_router
from .converter import recover_pending_transactions
from .issues import build_metadata_issues, filter_issues, render_issues_csv, render_issues_txt
from .jobs import ConversionJobManager, JobError
from .profile_store import get_profile as get_stored_profile, list_all_profiles
from .profiles import apply_profile_override
from .profiles_api import build_profiles_router
from .reports import (
    load_job_report,
    render_job_csv,
    render_job_txt,
    render_review_csv,
    render_review_txt,
)
from .review import build_batch_review
from .scanner import LibraryScanner
from .storage_health import zfs_pool_health

APP_VERSION = "0.6.0-dev"
TIMEZONE = os.getenv("TZ", "America/Indiana/Indianapolis")
MUSIC_ROOT = Path(os.getenv("MUSIC_ROOT", "/music"))
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))
DB_PATH = DATA_ROOT / "sox-resampler.db"
STATIC_ROOT = Path(__file__).resolve().parent / "static"
DEFAULT_RESERVE_BYTES = 10 * 1024**3

app = FastAPI(title="SoX Resampler Web", version=APP_VERSION)
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")
scanner = LibraryScanner(MUSIC_ROOT, DB_PATH, TIMEZONE)
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="library-scan")
scheduler = BackgroundScheduler(timezone=TIMEZONE)
job_manager = ConversionJobManager(DB_PATH, MUSIC_ROOT, TIMEZONE)
recovery_status: list[dict[str, str]] = []


class AlbumKey(BaseModel):
    albumartist: str
    album: str
    folder: str


class BatchReviewRequest(BaseModel):
    albums: list[AlbumKey] = Field(min_length=1, max_length=500)
    rates: list[int] = Field(default_factory=lambda: [96000, 192000])
    above: int | None = None
    profile_id: str = "foobar-ultra-37-48k"
    profile_override: dict[str, Any] | None = None
    workers: int = 1


class BatchStartRequest(BatchReviewRequest):
    acknowledged_replace_in_place: bool = False


class WorkersRequest(BaseModel):
    workers: int


def _tool_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def _scan_async(mode: str) -> dict[str, Any]:
    if job_manager.is_running():
        raise HTTPException(status_code=409, detail="A conversion job is running; scans wait until it finishes or pauses")
    state = scanner.snapshot()
    if state["running"]:
        return state
    executor.submit(scanner.run, mode)
    return {**scanner.snapshot(), "queued": True}


app.include_router(
    build_admin_router(
        db_path=DB_PATH,
        music_root=MUSIC_ROOT,
        data_root=DATA_ROOT,
        timezone=TIMEZONE,
        app_version=APP_VERSION,
        scanner=scanner,
        job_manager=job_manager,
        scan_async=_scan_async,
        recovery_status=lambda: recovery_status,
    )
)
app.include_router(build_profiles_router(DB_PATH))


def _daily_scan() -> None:
    # Discovery only. Conversion is intentionally never launched by a schedule.
    if not scanner.snapshot()["running"] and not job_manager.is_running():
        executor.submit(scanner.run, "incremental")


def _review(request: BatchReviewRequest) -> dict[str, Any]:
    cleaned_rates = sorted({r for r in request.rates if 8000 <= r <= 768000})
    if request.above is not None and not 0 <= request.above <= 768000:
        raise HTTPException(status_code=400, detail="Invalid above sample rate")
    try:
        stored_profile = get_stored_profile(DB_PATH, request.profile_id)
        profile = apply_profile_override(stored_profile, request.profile_override)
        reserve = int(db.get_setting(DB_PATH, "free_space_reserve_bytes", DEFAULT_RESERVE_BYTES))
        review = build_batch_review(
            DB_PATH,
            MUSIC_ROOT,
            [a.model_dump() for a in request.albums],
            cleaned_rates,
            request.above,
            profile,
            request.workers,
            reserve,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    usage = psutil.disk_usage(str(MUSIC_ROOT)) if MUSIC_ROOT.exists() else None
    free_bytes = usage.free if usage else 0
    required = review["estimated_peak_temp_bytes"] + reserve
    review["free_bytes"] = free_bytes
    review["free_space_ok"] = free_bytes >= required
    review["required_free_bytes"] = required
    if not review["free_space_ok"]:
        review["blockers"].append("Insufficient free space for temp output plus configured reserve")
    if not os.access(MUSIC_ROOT, os.W_OK):
        review["blockers"].append("Music dataset is not writable")
    if scanner.snapshot()["running"]:
        review["blockers"].append("A library scan is currently running")
    if job_manager.is_running():
        review["blockers"].append("Another conversion job is currently running")
    if bool(db.get_setting(DB_PATH, "read_only_mode", False)):
        review["blockers"].append("Read-only Scan Mode is enabled")
    if any(
        item.get("action") in {"manual_attention"}
        or str(item.get("action", "")).startswith("recovery_error")
        for item in recovery_status
    ):
        review["blockers"].append("An interrupted file transaction needs manual attention before conversion")
    zfs = zfs_pool_health()
    review["zfs"] = zfs
    if not zfs["ok"]:
        review["blockers"].append(str(zfs["reason"]))
    review["blockers"] = list(dict.fromkeys(review["blockers"]))
    review["can_start"] = bool(review["can_start"] and not review["blockers"])
    return review


def _attachment(content: str, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.on_event("startup")
def startup() -> None:
    global recovery_status
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    recovery_status = recover_pending_transactions(DATA_ROOT)
    db.init(DB_PATH)
    if not scheduler.running:
        scheduler.add_job(
            _daily_scan,
            "cron",
            hour=10,
            minute=0,
            id="daily-library-scan",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        scheduler.start()


@app.on_event("shutdown")
def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
    executor.shutdown(wait=False, cancel_futures=False)


@app.get("/health")
def health() -> dict[str, Any]:
    music_exists = MUSIC_ROOT.exists()
    data_exists = DATA_ROOT.exists()
    data_writable = os.access(DATA_ROOT, os.W_OK) if data_exists else False
    music_readable = os.access(MUSIC_ROOT, os.R_OK) if music_exists else False
    music_writable = os.access(MUSIC_ROOT, os.W_OK) if music_exists else False
    sox = _tool_version(["sox", "--version"])
    flac = _tool_version(["flac", "--version"])
    zfs = zfs_pool_health()
    try:
        db.init(DB_PATH)
        db_ok = True
    except Exception:
        db_ok = False
    healthy = bool(music_exists and music_readable and data_writable and sox and flac and db_ok)
    return {
        "status": "ok" if healthy else "degraded",
        "app_version": APP_VERSION,
        "db_schema": db.SCHEMA_VERSION,
        "music_root": {
            "path": str(MUSIC_ROOT),
            "exists": music_exists,
            "readable": music_readable,
            "writable": music_writable,
        },
        "data_root": {"path": str(DATA_ROOT), "exists": data_exists, "writable": data_writable},
        "database": {"path": str(DB_PATH), "ok": db_ok},
        "tools": {"sox": sox, "flac": flac},
        "zfs": zfs,
        "transaction_recovery": recovery_status,
    }


@app.get("/api/status")
def status() -> dict[str, Any]:
    usage = psutil.disk_usage(str(MUSIC_ROOT)) if MUSIC_ROOT.exists() else None
    reserve = int(db.get_setting(DB_PATH, "free_space_reserve_bytes", DEFAULT_RESERVE_BYTES))
    active_job_id = job_manager.active_job_id()
    return {
        "app_version": APP_VERSION,
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_percent": psutil.virtual_memory().percent,
        "music_root": str(MUSIC_ROOT),
        "data_root": str(DATA_ROOT),
        "timezone": TIMEZONE,
        "default_target_rate": int(os.getenv("DEFAULT_TARGET_RATE", "48000")),
        "default_flac_compression": int(os.getenv("DEFAULT_FLAC_COMPRESSION", "4")),
        "default_workers": int(os.getenv("DEFAULT_WORKERS", "1")),
        "max_workers": int(os.getenv("MAX_WORKERS", "2")),
        "free_bytes": usage.free if usage else None,
        "free_space_reserve_bytes": reserve,
        "read_only_mode": bool(db.get_setting(DB_PATH, "read_only_mode", False)),
        "library": db.library_summary(DB_PATH),
        "scan": scanner.snapshot(),
        "latest_scan": db.latest_scan(DB_PATH),
        "transaction_recovery": recovery_status,
        "zfs": zfs_pool_health(),
        "conversion": {
            "running": job_manager.is_running(),
            "active_job_id": active_job_id,
            "active": job_manager.get_job(active_job_id) if active_job_id is not None else None,
        },
    }


@app.get("/api/profiles")
def profiles() -> dict[str, Any]:
    return {
        "profiles": [profile.to_dict() for profile in list_all_profiles(DB_PATH)],
        "default": "foobar-ultra-37-48k",
    }


@app.get("/api/library/candidates")
def candidates(
    rates: list[int] = Query(default=[96000, 192000]),
    above: int | None = Query(default=None),
) -> dict[str, Any]:
    cleaned = sorted({r for r in rates if 8000 <= r <= 768000})
    if above is not None and not 0 <= above <= 768000:
        raise HTTPException(status_code=400, detail="Invalid above sample rate")
    albums = db.candidate_albums(DB_PATH, cleaned, above)
    return {"rates": cleaned, "above": above, "count": len(albums), "albums": albums}


@app.get("/api/library/issues")
def metadata_issues(severity: str = Query(default="all")) -> dict[str, Any]:
    try:
        issues = filter_issues(build_metadata_issues(DB_PATH), severity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    counts = {"blocking": 0, "warning": 0, "info": 0}
    for issue in issues:
        counts[issue["severity"]] += 1
    return {"severity": severity, "count": len(issues), "counts": counts, "issues": issues}


@app.get("/api/library/issues/report.txt")
def metadata_issues_report_txt(severity: str = Query(default="all")) -> Response:
    try:
        issues = filter_issues(build_metadata_issues(DB_PATH), severity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _attachment(
        render_issues_txt(issues, TIMEZONE),
        "text/plain; charset=utf-8",
        "sox-resampler-metadata-issues.txt",
    )


@app.get("/api/library/issues/report.csv")
def metadata_issues_report_csv(severity: str = Query(default="all")) -> Response:
    try:
        issues = filter_issues(build_metadata_issues(DB_PATH), severity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _attachment(
        render_issues_csv(issues),
        "text/csv; charset=utf-8",
        "sox-resampler-metadata-issues.csv",
    )


@app.post("/api/convert/review")
def review_batch(request: BatchReviewRequest) -> dict[str, Any]:
    return _review(request)


@app.post("/api/convert/review/report.txt")
def review_report_txt(request: BatchReviewRequest) -> Response:
    review = _review(request)
    return _attachment(
        render_review_txt(review, TIMEZONE),
        "text/plain; charset=utf-8",
        "sox-resampler-pre-conversion.txt",
    )


@app.post("/api/convert/review/report.csv")
def review_report_csv(request: BatchReviewRequest) -> Response:
    review = _review(request)
    return _attachment(
        render_review_csv(review, TIMEZONE),
        "text/csv; charset=utf-8",
        "sox-resampler-pre-conversion.csv",
    )


@app.post("/api/convert/start")
def start_batch(request: BatchStartRequest) -> dict[str, Any]:
    if not request.acknowledged_replace_in_place:
        raise HTTPException(status_code=400, detail="In-place replacement acknowledgment is required")
    review = _review(request)
    if not review["can_start"]:
        raise HTTPException(
            status_code=409,
            detail={"message": "Batch preflight failed", "blockers": review["blockers"]},
        )
    try:
        job_id = job_manager.create_job(
            review,
            request.profile_id,
            request.workers,
            {"rates": request.rates, "above": request.above},
        )
        job_manager.start(job_id)
    except JobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id, "status": "running"}


@app.get("/api/convert/jobs")
def recent_jobs(limit: int = 50) -> dict[str, Any]:
    return {"jobs": job_manager.recent_jobs(limit)}


@app.get("/api/convert/jobs/{job_id}")
def conversion_job(job_id: int) -> dict[str, Any]:
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/convert/jobs/{job_id}/report.txt")
def conversion_report_txt(job_id: int) -> Response:
    report = load_job_report(DB_PATH, job_id, TIMEZONE)
    if not report:
        raise HTTPException(status_code=404, detail="Job not found")
    return _attachment(
        render_job_txt(report),
        "text/plain; charset=utf-8",
        f"sox-resampler-job-{job_id}.txt",
    )


@app.get("/api/convert/jobs/{job_id}/report.csv")
def conversion_report_csv(job_id: int) -> Response:
    report = load_job_report(DB_PATH, job_id, TIMEZONE)
    if not report:
        raise HTTPException(status_code=404, detail="Job not found")
    return _attachment(
        render_job_csv(report),
        "text/csv; charset=utf-8",
        f"sox-resampler-job-{job_id}.csv",
    )


@app.post("/api/convert/jobs/{job_id}/resume")
def resume_job(job_id: int) -> dict[str, Any]:
    if scanner.snapshot()["running"]:
        raise HTTPException(status_code=409, detail="A library scan is running")
    if bool(db.get_setting(DB_PATH, "read_only_mode", False)):
        raise HTTPException(status_code=409, detail="Read-only Scan Mode is enabled")
    if any(
        item.get("action") == "manual_attention"
        or str(item.get("action", "")).startswith("recovery_error")
        for item in recovery_status
    ):
        raise HTTPException(status_code=409, detail="An interrupted file transaction needs manual attention")
    try:
        job_manager.start(job_id)
    except JobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id, "status": "running"}


@app.post("/api/convert/jobs/{job_id}/pause")
def pause_job(job_id: int) -> dict[str, Any]:
    try:
        job_manager.request_pause(job_id)
    except JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"job_id": job_id, "status": "pausing"}


@app.post("/api/convert/jobs/{job_id}/stop-after-album")
def stop_after_album(job_id: int) -> dict[str, Any]:
    try:
        job_manager.request_stop_after_album(job_id)
    except JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"job_id": job_id, "status": "stopping"}


@app.post("/api/convert/jobs/{job_id}/cancel")
def cancel_job(job_id: int) -> dict[str, Any]:
    try:
        job_manager.request_cancel(job_id)
    except JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"job_id": job_id, "status": "cancelling"}


@app.post("/api/convert/jobs/{job_id}/workers")
def change_workers(job_id: int, request: WorkersRequest) -> dict[str, Any]:
    try:
        job_manager.set_workers(job_id, request.workers)
    except JobError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job_id": job_id, "workers": request.workers, "takes_effect": "between active files"}


@app.get("/api/scan/status")
def scan_status() -> dict[str, Any]:
    return {"active": scanner.snapshot(), "latest": db.latest_scan(DB_PATH)}


@app.post("/api/scan/incremental")
def scan_incremental() -> dict[str, Any]:
    return _scan_async("incremental")


@app.post("/api/scan/full")
def scan_full() -> dict[str, Any]:
    return _scan_async("full")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")
