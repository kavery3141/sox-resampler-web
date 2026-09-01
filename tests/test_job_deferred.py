from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app import db
from app.busy_guard import SourceBusyError
from app.jobs import ConversionJobManager, recover_interrupted
from app.profiles import FOOBAR_ULTRA_37


@contextmanager
def always_busy(_path: Path):
    raise SourceBusyError("busy")
    yield  # pragma: no cover


class DeferredBusyFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.music = root / "music"
        self.music.mkdir()
        self.db_path = root / "data" / "test.db"
        db.init(self.db_path)
        self.manager = ConversionJobManager(
            self.db_path,
            self.music,
            "America/Indiana/Indianapolis",
        )
        self.path = self.music / "track.flac"
        self.path.write_bytes(b"source")
        with db.session(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO conversion_jobs(
                  created_at,status,profile_id,profile_json,workers,source_filter_json,album_order_json
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    self.manager._now(),
                    "running",
                    FOOBAR_ULTRA_37.id,
                    None,
                    1,
                    '{"rates":[96000],"above":null}',
                    '[]',
                ),
            )
            self.job_id = int(cur.lastrowid)
            cur = conn.execute(
                """
                INSERT INTO conversion_files(
                  job_id,album_index,file_index,albumartist,album,path,source_bytes,status
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    self.job_id,
                    0,
                    0,
                    "Artist",
                    "Album",
                    str(self.path),
                    self.path.stat().st_size,
                    "pending",
                ),
            )
            self.file_id = int(cur.lastrowid)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_busy_file_defers_once_then_fails_if_still_busy(self) -> None:
        with patch("app.jobs.source_read_guard", always_busy):
            first = self.manager._run_file(
                self.job_id,
                self.file_id,
                str(self.path),
                FOOBAR_ULTRA_37,
                self.path.stat().st_size,
            )
            self.assertEqual(first["status"], "deferred")
            with db.session(self.db_path) as conn:
                row = conn.execute(
                    "SELECT status,defer_count,error_text FROM conversion_files WHERE id=?",
                    (self.file_id,),
                ).fetchone()
            self.assertEqual(row["status"], "deferred")
            self.assertEqual(int(row["defer_count"]), 1)
            self.assertIn("deferred until the end of the batch", row["error_text"])

            second = self.manager._run_file(
                self.job_id,
                self.file_id,
                str(self.path),
                FOOBAR_ULTRA_37,
                self.path.stat().st_size,
            )
            self.assertEqual(second["status"], "failed")
            with db.session(self.db_path) as conn:
                row = conn.execute(
                    "SELECT status,defer_count,error_text FROM conversion_files WHERE id=?",
                    (self.file_id,),
                ).fetchone()
            self.assertEqual(row["status"], "failed")
            self.assertEqual(int(row["defer_count"]), 1)
            self.assertIn("remained busy after the one deferred", row["error_text"])

    def test_interrupted_end_retry_returns_to_deferred_not_pending(self) -> None:
        with db.session(self.db_path) as conn:
            conn.execute(
                "UPDATE conversion_files SET status='running',defer_count=1 WHERE id=?",
                (self.file_id,),
            )
        recover_interrupted(self.db_path, "America/Indiana/Indianapolis")
        with db.session(self.db_path) as conn:
            row = conn.execute(
                "SELECT status,defer_count FROM conversion_files WHERE id=?",
                (self.file_id,),
            ).fetchone()
        self.assertEqual(row["status"], "deferred")
        self.assertEqual(int(row["defer_count"]), 1)

    def test_end_of_batch_retry_visits_each_deferred_file_once(self) -> None:
        with db.session(self.db_path) as conn:
            conn.execute(
                "UPDATE conversion_files SET status='deferred',defer_count=1 WHERE id=?",
                (self.file_id,),
            )
        with patch.object(self.manager, "_runtime_gate", return_value=None), patch.object(
            self.manager,
            "_run_file",
            return_value={"status": "completed"},
        ) as run_file:
            status, error = self.manager._retry_deferred_files(self.job_id, FOOBAR_ULTRA_37)
        self.assertEqual(status, "completed")
        self.assertIsNone(error)
        run_file.assert_called_once()

    def test_job_status_exposes_deferred_files_without_counting_them_processed(self) -> None:
        with db.session(self.db_path) as conn:
            conn.execute(
                "UPDATE conversion_files SET status='deferred',defer_count=1,error_text='busy' WHERE id=?",
                (self.file_id,),
            )
        job = self.manager.get_job(self.job_id)
        self.assertEqual(job["counts"]["deferred"], 1)
        self.assertEqual(job["processed_files"], 0)
        self.assertEqual(job["progress_percent"], 0.0)
        self.assertEqual(len(job["deferred_files"]), 1)
        self.assertEqual(job["deferred_files"][0]["path"], str(self.path))


if __name__ == "__main__":
    unittest.main()
