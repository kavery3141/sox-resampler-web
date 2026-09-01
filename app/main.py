from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import psutil
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .scanner import LibraryScanner

APP_VERSION = "0.2.0-dev"
TIMEZONE = os.getenv("TZ", "America/Indiana/Indianapolis")
MUSIC_ROOT = Path(os.getenv("MUSIC_ROOT", "/music"))
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))
DB_PATH = DATA_ROOT / "sox-resampler.db"
STATIC_ROOT = Path(__file__).resolve().parent / "static"

app = FastAPI(title="SoX Resampler Web", version=APP_VERSION)
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")
scanner = LibraryScanner(MUSIC_ROOT, DB_PATH, TIMEZONE)
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="library-scan")
scheduler = BackgroundScheduler(timezone=TIMEZONE)


def _tool_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def _scan_async(mode: str) -> dict[str, Any]:
    state = scanner.snapshot()
    if state["running"]:
        return state
    executor.submit(scanner.run, mode)
    return {**scanner.snapshot(), "queued": True}


def _daily_scan() -> None:
    # Discovery only. Conversion is intentionally never launched by a schedule.
    if not scanner.snapshot()["running"]:
        executor.submit(scanner.run, "incremental")


@app.on_event("startup")
def startup() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
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
    sox = _tool_version(["sox", "--version"])
    flac = _tool_version(["flac", "--version"])
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
        "music_root": {"path": str(MUSIC_ROOT), "exists": music_exists, "readable": music_readable},
        "data_root": {"path": str(DATA_ROOT), "exists": data_exists, "writable": data_writable},
        "database": {"path": str(DB_PATH), "ok": db_ok},
        "tools": {"sox": sox, "flac": flac},
    }


@app.get("/api/status")
def status() -> dict[str, Any]:
    usage = psutil.disk_usage(str(MUSIC_ROOT)) if MUSIC_ROOT.exists() else None
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
        "library": db.library_summary(DB_PATH),
        "scan": scanner.snapshot(),
        "latest_scan": db.latest_scan(DB_PATH),
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
