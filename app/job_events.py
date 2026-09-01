from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import db


def ensure_event_table(db_path: Path) -> None:
    with db.session(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversion_job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES conversion_jobs(id) ON DELETE CASCADE,
                occurred_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                detail_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_conversion_job_events_job_time
              ON conversion_job_events(job_id,id);
            """
        )


def record_job_event(
    db_path: Path,
    job_id: int,
    occurred_at: str,
    event_type: str,
    detail: dict[str, Any] | None = None,
) -> None:
    ensure_event_table(db_path)
    payload = json.dumps(detail or {}, separators=(",", ":"), sort_keys=True)
    with db.session(db_path) as conn:
        exists = conn.execute("SELECT id FROM conversion_jobs WHERE id=?", (job_id,)).fetchone()
        if not exists:
            return
        conn.execute(
            "INSERT INTO conversion_job_events(job_id,occurred_at,event_type,detail_json) VALUES(?,?,?,?)",
            (job_id, occurred_at, event_type, payload),
        )


def load_job_events(db_path: Path, job_id: int, limit: int | None = None) -> list[dict[str, Any]]:
    ensure_event_table(db_path)
    with db.session(db_path) as conn:
        if limit is None:
            rows = conn.execute(
                "SELECT id,occurred_at,event_type,detail_json FROM conversion_job_events "
                "WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id,occurred_at,event_type,detail_json FROM ("
                "SELECT id,occurred_at,event_type,detail_json FROM conversion_job_events "
                "WHERE job_id=? ORDER BY id DESC LIMIT ?) ORDER BY id",
                (job_id, max(1, min(500, int(limit)))),
            ).fetchall()

    events: list[dict[str, Any]] = []
    for row in rows:
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except json.JSONDecodeError:
            detail = {"raw": row["detail_json"]}
        if not isinstance(detail, dict):
            detail = {"value": detail}
        events.append(
            {
                "id": int(row["id"]),
                "occurred_at": row["occurred_at"],
                "event_type": row["event_type"],
                "detail": detail,
            }
        )
    return events
