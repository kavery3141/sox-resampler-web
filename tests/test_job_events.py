from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import db
from app.job_events import load_job_events, record_job_event
from app.jobs import ConversionJobManager
from app.reports import load_job_report, render_job_csv, render_job_txt


class JobEventAuditTests(unittest.TestCase):
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
                  created_at,started_at,status,profile_id,workers,source_filter_json,album_order_json
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    "2026-09-01T10:00:00-04:00",
                    "2026-09-01T10:00:00-04:00",
                    "running",
                    "foobar-ultra-37-48k",
                    1,
                    '{"rates":[96000,192000]}',
                    '[]',
                ),
            )
            self.job_id = int(cur.lastrowid)
            conn.execute(
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
                    str(self.music / "01.flac"),
                    1000,
                    "pending",
                ),
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_worker_and_pause_controls_are_audited(self) -> None:
        self.manager.set_workers(self.job_id, 2)
        self.manager.request_pause(self.job_id)
        events = load_job_events(self.db_path, self.job_id)
        self.assertEqual([event["event_type"] for event in events], ["workers_changed", "pause_requested"])
        self.assertEqual(events[0]["detail"]["from"], 1)
        self.assertEqual(events[0]["detail"]["to"], 2)
        self.assertEqual(events[0]["detail"]["takes_effect"], "between-files")
        self.assertEqual(events[1]["detail"]["previous_status"], "running")

    def test_job_report_exports_event_timeline(self) -> None:
        record_job_event(
            self.db_path,
            self.job_id,
            "2026-09-01T10:05:00-04:00",
            "workers_changed",
            {"from": 1, "to": 2, "takes_effect": "between-files"},
        )
        report = load_job_report(self.db_path, self.job_id, "America/Indiana/Indianapolis")
        self.assertIsNotNone(report)
        self.assertEqual(len(report["events"]), 1)
        txt = render_job_txt(report)
        csv_text = render_job_csv(report)
        self.assertIn("Job event timeline", txt)
        self.assertIn("workers 1 -> 2 (between files)", txt)
        self.assertIn("job_event_timeline", csv_text)
        self.assertIn("workers 1 -> 2 (between files)", csv_text)


if __name__ == "__main__":
    unittest.main()
