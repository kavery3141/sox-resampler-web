from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app import db
from app.jobs import ensure_tables
from app.reports import load_job_report, render_job_csv, render_job_txt, render_review_csv, render_review_txt


class ReportsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db_path = root / "data" / "test.db"
        db.init(self.db_path)
        ensure_tables(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_review_txt_and_csv_include_exact_paths_and_commands(self) -> None:
        review = {
            "profile": {
                "id": "foobar-ultra-37-48k",
                "name": "Foobar Ultra 37 - 48 kHz",
                "target_rate": 48000,
                "bit_depth": "preserve",
                "flac_compression": 4,
            },
            "workers": 1,
            "album_count": 1,
            "matching_tracks": 1,
            "source_bytes": 1000,
            "estimated_output_bytes": 600,
            "estimated_savings_bytes": 400,
            "free_bytes": 999999,
            "required_free_bytes": 10000,
            "can_start": True,
            "blockers": [],
            "albums": [
                {
                    "albumartist": "Artist",
                    "album": "Album",
                    "folder": "/music/Artist/Album",
                    "matching_tracks": 1,
                    "source_bytes": 1000,
                    "estimated_output_bytes": 600,
                    "estimated_savings_bytes": 400,
                    "warnings": ["ReplayGain incomplete"],
                    "blockers": [],
                    "tracks": [
                        {
                            "path": "/music/Artist/Album/01.flac",
                            "sample_rate": 96000,
                            "bits_per_sample": 24,
                            "channels": 2,
                            "source_bytes": 1000,
                            "estimated_output_bytes": 600,
                            "replaygain_complete": False,
                            "blockers": [],
                            "command": ["sox", "input.flac", "output.flac", "rate", "48000"],
                        }
                    ],
                }
            ],
        }
        txt = render_review_txt(review, "America/Indiana/Indianapolis")
        csv_text = render_review_csv(review, "America/Indiana/Indianapolis")
        self.assertIn("/music/Artist/Album/01.flac", txt)
        self.assertIn("sox input.flac output.flac rate 48000", txt)
        self.assertIn("Foobar Ultra 37 - 48 kHz", csv_text)
        self.assertIn("ReplayGain incomplete", csv_text)

    def test_job_report_uses_post_conversion_size_and_checksum(self) -> None:
        with db.session(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO conversion_jobs(
                  created_at,started_at,finished_at,status,profile_id,workers,source_filter_json,album_order_json
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    "2026-09-01T01:00:00-05:00",
                    "2026-09-01T01:01:00-05:00",
                    "2026-09-01T01:02:00-05:00",
                    "completed",
                    "foobar-ultra-37-48k",
                    1,
                    '{"rates":[96000]}',
                    '[]',
                ),
            )
            job_id = int(cur.lastrowid)
            payload = {
                "status": "completed",
                "source_rate": 96000,
                "target_rate": 48000,
                "source_bits": 24,
                "target_bits": 24,
                "index_refresh": {"size_bytes": 600},
                "index_refresh_error": None,
            }
            conn.execute(
                """
                INSERT INTO conversion_files(
                  job_id,album_index,file_index,albumartist,album,path,source_bytes,status,
                  started_at,finished_at,temp_sha256,final_sha256,result_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    0,
                    0,
                    "Artist",
                    "Album",
                    "/music/Artist/Album/01.flac",
                    1000,
                    "completed",
                    "2026-09-01T01:01:00-05:00",
                    "2026-09-01T01:01:30-05:00",
                    "abc",
                    "abc",
                    json.dumps(payload),
                ),
            )
        report = load_job_report(self.db_path, job_id, "America/Indiana/Indianapolis")
        self.assertIsNotNone(report)
        self.assertEqual(report["totals"]["source_bytes"], 1000)
        self.assertEqual(report["totals"]["final_bytes"], 600)
        self.assertEqual(report["totals"]["savings_bytes"], 400)
        self.assertEqual(report["timing"]["wall_seconds"], 60.0)
        self.assertEqual(report["timing"]["active_seconds"], 30.0)
        self.assertEqual(report["timing"]["idle_seconds"], 30.0)
        txt = render_job_txt(report)
        csv_text = render_job_csv(report)
        self.assertIn("SHA-256: abc", txt)
        self.assertIn("File-active seconds: 30.0", txt)
        self.assertIn("Idle/between-file seconds: 30.0", txt)
        self.assertIn("job_paused_seconds", csv_text)
        self.assertIn("400", csv_text)
        self.assertIn("America/Indiana/Indianapolis", csv_text)


if __name__ == "__main__":
    unittest.main()
