from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import psutil
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

APP_VERSION = "0.1.0-dev"
DB_SCHEMA_VERSION = 1
MUSIC_ROOT = Path(os.getenv("MUSIC_ROOT", "/music"))
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))
DB_PATH = DATA_ROOT / "sox-resampler.db"
STATIC_ROOT = Path(__file__).resolve().parent / "static"

app = FastAPI(title="SoX Resampler Web", version=APP_VERSION)
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


def _tool_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def _db_ok() -> bool:
    try:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as db:
            db.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute(
                "INSERT INTO app_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(DB_SCHEMA_VERSION),),
            )
        return True
    except (OSError, sqlite3.Error):
        return False


@app.on_event("startup")
def startup() -> None:
    _db_ok()


@app.get("/health")
def health() -> dict[str, Any]:
    music_exists = MUSIC_ROOT.exists()
    data_exists = DATA_ROOT.exists()
    data_writable = os.access(DATA_ROOT, os.W_OK) if data_exists else False
    sox = _tool_version(["sox", "--version"])
    flac = _tool_version(["flac", "--version"])
    db_ok = _db_ok()
    healthy = bool(music_exists and data_writable and sox and flac and db_ok)
    return {
        "status": "ok" if healthy else "degraded",
        "app_version": APP_VERSION,
        "db_schema": DB_SCHEMA_VERSION,
        "music_root": {"path": str(MUSIC_ROOT), "exists": music_exists},
        "data_root": {"path": str(DATA_ROOT), "exists": data_exists, "writable": data_writable},
        "database": {"path": str(DB_PATH), "ok": db_ok},
        "tools": {"sox": sox, "flac": flac},
    }


@app.get("/api/status")
def status() -> dict[str, Any]:
    return {
        "app_version": APP_VERSION,
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_percent": psutil.virtual_memory().percent,
        "music_root": str(MUSIC_ROOT),
        "data_root": str(DATA_ROOT),
        "timezone": os.getenv("TZ", "America/Indiana/Indianapolis"),
        "default_target_rate": int(os.getenv("DEFAULT_TARGET_RATE", "48000")),
        "default_flac_compression": int(os.getenv("DEFAULT_FLAC_COMPRESSION", "4")),
        "default_workers": int(os.getenv("DEFAULT_WORKERS", "1")),
        "max_workers": int(os.getenv("MAX_WORKERS", "2")),
    }


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")
