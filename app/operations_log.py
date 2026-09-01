from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from . import db

LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5


def configure_file_logging(data_root: Path) -> Path:
    """Configure one bounded persistent application log under the app dataset."""
    log_dir = data_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "sox-resampler.log"
    root = logging.getLogger()
    marker = str(log_path)
    if not any(getattr(handler, "baseFilename", None) == marker for handler in root.handlers):
        handler = RotatingFileHandler(
            log_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
        if root.level > logging.INFO:
            root.setLevel(logging.INFO)
    return log_path


def ensure_events_table(db_path: Path) -> None:
    with db.session(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS maintenance_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                detail_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_maintenance_events_time ON maintenance_events(occurred_at)"
        )


def record_event(db_path: Path, occurred_at: str, event_type: str, detail: dict[str, Any] | None = None) -> None:
    ensure_events_table(db_path)
    payload = json.dumps(detail or {}, separators=(",", ":"), sort_keys=True)
    with db.session(db_path) as conn:
        conn.execute(
            "INSERT INTO maintenance_events(occurred_at,event_type,detail_json) VALUES(?,?,?)",
            (occurred_at, str(event_type), payload),
        )
    logging.getLogger("sox_resampler.maintenance").info("%s %s", event_type, payload)


def recent_events(db_path: Path, limit: int = 50) -> list[dict[str, Any]]:
    ensure_events_table(db_path)
    with db.session(db_path) as conn:
        rows = conn.execute(
            "SELECT id,occurred_at,event_type,detail_json FROM maintenance_events ORDER BY id DESC LIMIT ?",
            (max(1, min(200, int(limit))),),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except json.JSONDecodeError:
            detail = {}
        result.append(
            {
                "id": int(row["id"]),
                "occurred_at": row["occurred_at"],
                "event_type": row["event_type"],
                "detail": detail if isinstance(detail, dict) else {},
            }
        )
    return result


def log_disk_usage(data_root: Path) -> dict[str, Any]:
    log_dir = data_root / "logs"
    files = sorted(log_dir.glob("sox-resampler.log*")) if log_dir.exists() else []
    return {
        "path": str(log_dir / "sox-resampler.log"),
        "active_max_bytes": LOG_MAX_BYTES,
        "rotated_files": LOG_BACKUP_COUNT,
        "files": len(files),
        "total_bytes": sum(path.stat().st_size for path in files if path.is_file()),
    }
