from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app import db
from app.job_events import record_job_event
from app.job_timing import job_runtime_times
from app.jobs import ensure_tables


def ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


class JobTimingTests(unittest.TestCase):
    def _job(self, db_path: Path, *, status: str, finished_at: str | None) -> int:
        with db.session(db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO conversion_jobs(
                  created_at,started_at,finished_at,status,profile_id,workers,
                  source_filter_json,album_order_json
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    "2026-09-01T10:00:00-04:00",
                    "2026-09-01T10:00:00-04:00",
                    finished_at,
                    status,
                    "foobar-ultra-37-48k",
                    1,
                    "{}",
                    "[]",
                ),
            )
            return int(cur.lastrowid)

    def _file(self, db_path: Path, job_id: int, index: int, started: str, finished: str) -> None:
        with db.session(db_path) as conn:
            conn.execute(
                """
                INSERT INTO conversion_files(
                  job_id,album_index,file_index,albumartist,album,path,source_bytes,status,
                  started_at,finished_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    0,
                    index,
                    "Artist",
                    "Album",
                    f"/music/{index:02d}.flac",
                    1000,
                    "completed",
                    started,
                    finished,
                ),
            )

    def test_interrupted_wait_is_not_counted_as_pause_or_idle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timing.db"
            db.init(db_path)
            ensure_tables(db_path)
            job_id = self._job(
                db_path,
                status="completed",
                finished_at="2026-09-01T10:00:40-04:00",
            )
            self._file(
                db_path,
                job_id,
                0,
                "2026-09-01T10:00:00-04:00",
                "2026-09-01T10:00:10-04:00",
            )
            self._file(
                db_path,
                job_id,
                1,
                "2026-09-01T10:00:25-04:00",
                "2026-09-01T10:00:35-04:00",
            )
            record_job_event(
                db_path,
                job_id,
                "2026-09-01T10:00:15-04:00",
                "restart_interrupted",
                {"previous_status": "running", "reason": "Container or NAS restart"},
            )
            record_job_event(
                db_path,
                job_id,
                "2026-09-01T10:00:25-04:00",
                "job_resumed",
                {"previous_status": "interrupted", "workers": 1},
            )
            record_job_event(
                db_path,
                job_id,
                "2026-09-01T10:00:40-04:00",
                "job_finished",
                {"status": "completed"},
            )

            result = job_runtime_times(db_path, job_id)
            self.assertEqual(result["wall_seconds"], 40.0)
            self.assertEqual(result["active_seconds"], 20.0)
            self.assertEqual(result["paused_seconds"], 0.0)
            self.assertEqual(result["interrupted_seconds"], 10.0)
            self.assertEqual(result["idle_seconds"], 10.0)

    def test_current_pause_keeps_accumulating_until_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timing.db"
            db.init(db_path)
            ensure_tables(db_path)
            job_id = self._job(
                db_path,
                status="paused",
                finished_at="2026-09-01T10:00:10-04:00",
            )
            self._file(
                db_path,
                job_id,
                0,
                "2026-09-01T10:00:00-04:00",
                "2026-09-01T10:00:10-04:00",
            )
            record_job_event(
                db_path,
                job_id,
                "2026-09-01T10:00:10-04:00",
                "job_finished",
                {"status": "paused"},
            )

            result = job_runtime_times(
                db_path,
                job_id,
                now=ts("2026-09-01T10:00:25-04:00"),
            )
            self.assertEqual(result["wall_seconds"], 25.0)
            self.assertEqual(result["active_seconds"], 10.0)
            self.assertEqual(result["paused_seconds"], 15.0)
            self.assertEqual(result["interrupted_seconds"], 0.0)
            self.assertEqual(result["idle_seconds"], 0.0)


if __name__ == "__main__":
    unittest.main()
