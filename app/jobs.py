from __future__ import annotations

import json
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import db
from .converter import convert_file
from .profiles import get_profile


class JobError(RuntimeError):
    pass


DEFAULT_RESERVE_BYTES = 10 * 1024**3


def ensure_tables(db_path: Path) -> None:
    with db.session(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversion_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                status TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                workers INTEGER NOT NULL,
                source_filter_json TEXT NOT NULL,
                album_order_json TEXT NOT NULL,
                pause_requested INTEGER NOT NULL DEFAULT 0,
                stop_after_album INTEGER NOT NULL DEFAULT 0,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                error_text TEXT
            );

            CREATE TABLE IF NOT EXISTS conversion_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES conversion_jobs(id) ON DELETE CASCADE,
                album_index INTEGER NOT NULL,
                file_index INTEGER NOT NULL,
                albumartist TEXT NOT NULL,
                album TEXT NOT NULL,
                path TEXT NOT NULL,
                source_bytes INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                error_text TEXT,
                temp_sha256 TEXT,
                final_sha256 TEXT,
                result_json TEXT,
                UNIQUE(job_id, path)
            );
            CREATE INDEX IF NOT EXISTS idx_conversion_files_job_status
              ON conversion_files(job_id,status,album_index,file_index);
            """
        )


def recover_interrupted(db_path: Path, timezone: str) -> None:
    ensure_tables(db_path)
    now = datetime.now(ZoneInfo(timezone)).isoformat(timespec="seconds")
    with db.session(db_path) as conn:
        conn.execute(
            "UPDATE conversion_files SET status='pending', started_at=NULL "
            "WHERE status='running'"
        )
        conn.execute(
            "UPDATE conversion_jobs SET status='interrupted', finished_at=?, "
            "error_text=COALESCE(error_text,'Container or NAS restart interrupted this job') "
            "WHERE status IN ('running','pausing','stopping','cancelling')",
            (now,),
        )


class ConversionJobManager:
    def __init__(self, db_path: Path, music_root: Path, timezone: str) -> None:
        self.db_path = db_path
        self.music_root = music_root.resolve()
        self.tz = ZoneInfo(timezone)
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._active_job_id: int | None = None
        ensure_tables(db_path)
        recover_interrupted(db_path, timezone)

    def _now(self) -> str:
        return datetime.now(self.tz).isoformat(timespec="seconds")

    def is_running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def active_job_id(self) -> int | None:
        with self._lock:
            return self._active_job_id if self.is_running() else None

    def _runtime_gate(self, required_temp_bytes: int) -> str | None:
        """Return a reason to pause before starting more file work, or None when safe."""
        if bool(db.get_setting(self.db_path, "read_only_mode", False)):
            return "Read-only Scan Mode was enabled; conversion paused before the next file"
        if not self.music_root.exists():
            return "Music dataset is unavailable; conversion paused before the next file"
        if not os.access(self.music_root, os.R_OK | os.W_OK):
            return "Music dataset is not readable/writable; conversion paused before the next file"
        try:
            free_bytes = shutil.disk_usage(self.music_root).free
        except OSError as exc:
            return f"Unable to verify free space ({exc}); conversion paused before the next file"
        reserve = int(db.get_setting(self.db_path, "free_space_reserve_bytes", DEFAULT_RESERVE_BYTES))
        if free_bytes < reserve + max(0, int(required_temp_bytes)):
            return (
                "Free space fell below the configured reserve plus estimated temp requirement; "
                "conversion paused before the next file"
            )
        return None

    def create_job(
        self,
        review: dict[str, Any],
        profile_id: str,
        workers: int,
        source_filter: dict[str, Any],
    ) -> int:
        if workers not in (1, 2):
            raise JobError("Workers must be 1 or 2")
        if review.get("blockers") or not review.get("can_start"):
            raise JobError("Batch review contains blockers")
        album_order = [
            {"albumartist": a["albumartist"], "album": a["album"], "folder": a["folder"]}
            for a in review["albums"]
        ]
        with db.session(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO conversion_jobs(
                  created_at,status,profile_id,workers,source_filter_json,album_order_json
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    self._now(), "queued", profile_id, workers,
                    json.dumps(source_filter, separators=(",", ":")),
                    json.dumps(album_order, separators=(",", ":")),
                ),
            )
            job_id = int(cur.lastrowid)
            for album_index, album in enumerate(review["albums"]):
                for file_index, track in enumerate(album["tracks"]):
                    path = Path(track["path"]).resolve()
                    if self.music_root not in path.parents:
                        raise JobError(f"Track is outside music root: {path}")
                    conn.execute(
                        """
                        INSERT INTO conversion_files(
                          job_id,album_index,file_index,albumartist,album,path,source_bytes,status
                        ) VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (
                            job_id, album_index, file_index, album["albumartist"], album["album"],
                            str(path), int(track["source_bytes"]), "pending",
                        ),
                    )
        return job_id

    def start(self, job_id: int) -> None:
        with self._lock:
            if self.is_running():
                raise JobError(f"Conversion job {self._active_job_id} is already running")
            gate = self._runtime_gate(0)
            if gate:
                raise JobError(gate)
            with db.session(self.db_path) as conn:
                job = conn.execute("SELECT * FROM conversion_jobs WHERE id=?", (job_id,)).fetchone()
                if not job:
                    raise JobError("Job not found")
                if job["status"] not in ("queued", "paused", "interrupted"):
                    raise JobError(f"Job cannot start from status {job['status']}")
                conn.execute(
                    "UPDATE conversion_jobs SET status='running',started_at=COALESCE(started_at,?),"
                    "finished_at=NULL,pause_requested=0,stop_after_album=0,cancel_requested=0,error_text=NULL WHERE id=?",
                    (self._now(), job_id),
                )
            self._active_job_id = job_id
            self._thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True, name=f"convert-{job_id}")
            self._thread.start()

    def _controls(self, job_id: int) -> dict[str, bool]:
        with db.session(self.db_path) as conn:
            row = conn.execute(
                "SELECT pause_requested,stop_after_album,cancel_requested FROM conversion_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        if not row:
            return {"pause": False, "stop_album": False, "cancel": True}
        return {
            "pause": bool(row["pause_requested"]),
            "stop_album": bool(row["stop_after_album"]),
            "cancel": bool(row["cancel_requested"]),
        }

    def _run_file(self, job_id: int, file_id: int, path: str, profile_id: str, expected_bytes: int) -> dict[str, Any]:
        source = Path(path)
        try:
            current_size = source.stat().st_size
        except OSError as exc:
            raise JobError(f"Source unavailable before conversion: {source}: {exc}") from exc
        if current_size != int(expected_bytes):
            raise JobError(
                f"Source size changed after batch review ({expected_bytes} -> {current_size}); rescan/review required: {source}"
            )
        started = self._now()
        with db.session(self.db_path) as conn:
            conn.execute(
                "UPDATE conversion_files SET status='running',started_at=?,error_text=NULL WHERE id=?",
                (started, file_id),
            )
        profile = get_profile(profile_id)
        result = convert_file(source, profile)
        payload = asdict(result)
        finished = self._now()
        with db.session(self.db_path) as conn:
            conn.execute(
                """
                UPDATE conversion_files SET status=?,finished_at=?,error_text=?,temp_sha256=?,final_sha256=?,result_json=?
                WHERE id=?
                """,
                (
                    "completed" if result.status == "completed" else "failed",
                    finished, result.error, result.temp_sha256, result.final_sha256,
                    json.dumps(payload, separators=(",", ":")), file_id,
                ),
            )
        return payload

    def _run_job(self, job_id: int) -> None:
        terminal_status = "completed"
        terminal_error: str | None = None
        try:
            with db.session(self.db_path) as conn:
                job = conn.execute("SELECT * FROM conversion_jobs WHERE id=?", (job_id,)).fetchone()
                if not job:
                    raise JobError("Job disappeared")
                profile_id = str(job["profile_id"])
                album_indices = [
                    r["album_index"] for r in conn.execute(
                        "SELECT DISTINCT album_index FROM conversion_files WHERE job_id=? ORDER BY album_index",
                        (job_id,),
                    ).fetchall()
                ]

            for album_index in album_indices:
                controls = self._controls(job_id)
                if controls["cancel"]:
                    terminal_status = "cancelled"
                    break
                if controls["pause"]:
                    terminal_status = "paused"
                    break

                with db.session(self.db_path) as conn:
                    files = conn.execute(
                        """
                        SELECT id,path,source_bytes FROM conversion_files
                        WHERE job_id=? AND album_index=? AND status='pending'
                        ORDER BY file_index
                        """,
                        (job_id, album_index),
                    ).fetchall()

                # Process an album in small waves so pause/cancel/concurrency changes can take
                # effect between files without killing an active SoX process.
                cursor = 0
                while cursor < len(files):
                    controls = self._controls(job_id)
                    if controls["cancel"]:
                        terminal_status = "cancelled"
                        break
                    if controls["pause"]:
                        terminal_status = "paused"
                        break
                    with db.session(self.db_path) as conn:
                        current_workers = int(conn.execute(
                            "SELECT workers FROM conversion_jobs WHERE id=?", (job_id,)
                        ).fetchone()["workers"])
                    wave = files[cursor: cursor + max(1, min(2, current_workers))]
                    required_temp = sum(int(r["source_bytes"]) for r in wave)
                    gate = self._runtime_gate(required_temp)
                    if gate:
                        terminal_status = "paused"
                        terminal_error = gate
                        break
                    cursor += len(wave)
                    with ThreadPoolExecutor(max_workers=len(wave), thread_name_prefix=f"job-{job_id}") as pool:
                        futures = [
                            pool.submit(
                                self._run_file, job_id, r["id"], r["path"], profile_id, int(r["source_bytes"])
                            )
                            for r in wave
                        ]
                        for future in as_completed(futures):
                            try:
                                future.result()
                            except Exception as exc:
                                terminal_error = str(exc)
                    # Control requests and runtime storage safeguards are honored between active files/waves.
                if terminal_status in ("paused", "cancelled"):
                    break
                if self._controls(job_id)["stop_album"]:
                    terminal_status = "stopped"
                    break
        except Exception as exc:
            terminal_status = "interrupted"
            terminal_error = str(exc)
        finally:
            with db.session(self.db_path) as conn:
                conn.execute(
                    "UPDATE conversion_jobs SET status=?,finished_at=?,error_text=? WHERE id=?",
                    (terminal_status, self._now(), terminal_error, job_id),
                )
            with self._lock:
                self._active_job_id = None

    def request_pause(self, job_id: int) -> None:
        self._set_flag(job_id, "pause_requested", 1, "pausing")

    def request_stop_after_album(self, job_id: int) -> None:
        self._set_flag(job_id, "stop_after_album", 1, "stopping")

    def request_cancel(self, job_id: int) -> None:
        self._set_flag(job_id, "cancel_requested", 1, "cancelling")

    def set_workers(self, job_id: int, workers: int) -> None:
        if workers not in (1, 2):
            raise JobError("Workers must be 1 or 2")
        with db.session(self.db_path) as conn:
            conn.execute("UPDATE conversion_jobs SET workers=? WHERE id=?", (workers, job_id))

    def _set_flag(self, job_id: int, column: str, value: int, status: str) -> None:
        if column not in {"pause_requested", "stop_after_album", "cancel_requested"}:
            raise JobError("Invalid control flag")
        with db.session(self.db_path) as conn:
            exists = conn.execute("SELECT id FROM conversion_jobs WHERE id=?", (job_id,)).fetchone()
            if not exists:
                raise JobError("Job not found")
            conn.execute(f"UPDATE conversion_jobs SET {column}=?,status=? WHERE id=?", (value, status, job_id))

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with db.session(self.db_path) as conn:
            job = conn.execute("SELECT * FROM conversion_jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                return None
            counts = {
                row["status"]: row["count"] for row in conn.execute(
                    "SELECT status,COUNT(*) count FROM conversion_files WHERE job_id=? GROUP BY status",
                    (job_id,),
                ).fetchall()
            }
            current = conn.execute(
                "SELECT * FROM conversion_files WHERE job_id=? AND status='running' ORDER BY album_index,file_index",
                (job_id,),
            ).fetchall()
        result = dict(job)
        result["counts"] = counts
        result["current_files"] = [dict(r) for r in current]
        return result

    def recent_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with db.session(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM conversion_jobs ORDER BY id DESC LIMIT ?", (max(1, min(200, limit)),)
            ).fetchall()
        return [dict(r) for r in rows]
