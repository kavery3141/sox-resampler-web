from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import db
from app.jobs import ConversionJobManager


class JobProgressTest(unittest.TestCase):
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
        with db.session(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO conversion_jobs(
                  created_at,status,profile_id,workers,source_filter_json,album_order_json
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    self.manager._now(),
                    "running",
                    "foobar-ultra-37-48k",
                    1,
                    '{"rates":[96000],"above":null}',
                    '[]',
                ),
            )
            self.job_id = int(cur.lastrowid)
            for index, status in enumerate(("completed", "failed", "pending", "running")):
                conn.execute(
                    """
                    INSERT INTO conversion_files(
                      job_id,album_index,file_index,albumartist,album,path,source_bytes,status,error_text
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        self.job_id,
                        0,
                        index,
                        "Artist",
                        "Album",
                        str(self.music / f"{index}.flac"),
                        1000 * (index + 1),
                        status,
                        "boom" if status == "failed" else None,
                    ),
                )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_get_job_reports_processed_progress_current_and_failures(self) -> None:
        job = self.manager.get_job(self.job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job["total_files"], 4)
        self.assertEqual(job["processed_files"], 2)
        self.assertEqual(job["progress_percent"], 50.0)
        self.assertEqual(job["counts"]["completed"], 1)
        self.assertEqual(job["counts"]["failed"], 1)
        self.assertEqual(len(job["current_files"]), 1)
        self.assertEqual(len(job["recent_failures"]), 1)
        self.assertEqual(job["recent_failures"][0]["error_text"], "boom")

    def test_run_file_exception_is_durably_recorded_as_failed(self) -> None:
        with db.session(self.db_path) as conn:
            row = conn.execute(
                "SELECT id,path FROM conversion_files WHERE job_id=? AND status='pending' LIMIT 1",
                (self.job_id,),
            ).fetchone()
        payload = self.manager._run_file(
            self.job_id,
            int(row["id"]),
            str(row["path"]),
            "foobar-ultra-37-48k",
            3000,
        )
        self.assertEqual(payload["status"], "failed")
        with db.session(self.db_path) as conn:
            saved = conn.execute("SELECT status,error_text FROM conversion_files WHERE id=?", (row["id"],)).fetchone()
        self.assertEqual(saved["status"], "failed")
        self.assertIn("Source unavailable", saved["error_text"])


if __name__ == "__main__":
    unittest.main()
