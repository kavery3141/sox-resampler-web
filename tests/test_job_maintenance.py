from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app import db
from app.job_maintenance import (
    clear_terminal_history,
    failed_retry_spec,
    history_summary,
    prune_job_history,
)
from app.jobs import ensure_tables
from app.profiles import FOOBAR_ULTRA_37


class JobMaintenanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init(self.db_path)
        ensure_tables(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _job(self, *, created: str, finished: str | None, status: str, error: str | None = None) -> int:
        with db.session(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO conversion_jobs(
                    created_at,started_at,finished_at,status,profile_id,profile_json,workers,
                    source_filter_json,album_order_json,error_text
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    created,
                    created,
                    finished,
                    status,
                    FOOBAR_ULTRA_37.id,
                    json.dumps(FOOBAR_ULTRA_37.to_dict()),
                    1,
                    json.dumps({"rates": [96000, 192000], "above": None}),
                    "[]",
                    error,
                ),
            )
            return int(cur.lastrowid)

    def _track(self, path: str) -> None:
        p = Path(path)
        values = {
            "path": path,
            "rel_path": str(p).removeprefix("/music/"),
            "folder": str(p.parent),
            "filename": p.name,
            "size_bytes": 1000,
            "mtime_ns": 1,
            "sample_rate": 96000,
            "bits_per_sample": 24,
            "channels": 2,
            "duration": 180.0,
            "albumartist": "Artist",
            "album": "Album",
            "releasetype": "album",
            "musicbrainz_albumid": "mbid",
            "artist": "Artist",
            "title": p.stem,
            "tracknumber": "1",
            "discnumber": "1",
            "replaygain_track_gain": "-5 dB",
            "replaygain_track_peak": "0.9",
            "replaygain_album_gain": "-4 dB",
            "replaygain_album_peak": "0.95",
            "picture_count": 1,
            "first_seen": "2026-01-01T00:00:00-05:00",
            "last_seen": "2026-01-01T00:00:00-05:00",
            "tag_json": "{}",
        }
        with db.session(self.db_path) as conn:
            cols = ",".join(values)
            q = ",".join("?" for _ in values)
            conn.execute(f"INSERT INTO tracks({cols}) VALUES({q})", tuple(values.values()))

    def _file(self, job_id: int, path: str, status: str, error: str | None = None, index: int = 0) -> None:
        with db.session(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO conversion_files(
                    job_id,album_index,file_index,albumartist,album,path,source_bytes,status,error_text
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (job_id, 0, index, "Artist", "Album", path, 1000, status, error),
            )

    def test_retry_spec_contains_only_failed_paths_and_original_dsp_snapshot(self) -> None:
        created = "2026-09-01T10:00:00-04:00"
        job_id = self._job(created=created, finished=created, status="completed", error="one file failed")
        failed = "/music/Artist/Album/01.flac"
        completed = "/music/Artist/Album/02.flac"
        self._track(failed)
        self._track(completed)
        self._file(job_id, failed, "failed", "SoX failed", 0)
        self._file(job_id, completed, "completed", None, 1)

        spec = failed_retry_spec(self.db_path, job_id)
        self.assertEqual(spec["paths"], [failed])
        self.assertEqual(spec["profile"].quality, "ultra-37")
        self.assertEqual(spec["workers"], 1)
        self.assertEqual(spec["albums"], [{
            "albumartist": "Artist",
            "album": "Album",
            "folder": "/music/Artist/Album",
        }])

    def test_retention_prunes_old_clean_jobs_but_protects_failures_and_errors(self) -> None:
        tz = ZoneInfo("America/Indiana/Indianapolis")
        now = datetime(2026, 9, 1, 12, 0, tzinfo=tz)
        old = (now - timedelta(days=200)).isoformat(timespec="seconds")
        recent = (now - timedelta(days=10)).isoformat(timespec="seconds")

        clean_old = self._job(created=old, finished=old, status="completed")
        failed_old = self._job(created=old, finished=old, status="completed", error="file failed")
        self._file(failed_old, "/music/A/B/failed.flac", "failed", "failure")
        clean_recent = self._job(created=recent, finished=recent, status="completed")

        result = prune_job_history(self.db_path, "America/Indiana/Indianapolis", now=now)
        self.assertEqual(result["deleted_jobs"], 1)
        with db.session(self.db_path) as conn:
            ids = {int(row["id"]) for row in conn.execute("SELECT id FROM conversion_jobs").fetchall()}
        self.assertNotIn(clean_old, ids)
        self.assertIn(failed_old, ids)
        self.assertIn(clean_recent, ids)

    def test_clear_history_preserves_resumable_jobs(self) -> None:
        stamp = "2026-09-01T10:00:00-04:00"
        terminal = self._job(created=stamp, finished=stamp, status="completed", error="retained error")
        paused = self._job(created=stamp, finished=stamp, status="paused")
        result = clear_terminal_history(self.db_path)
        self.assertEqual(result["deleted_jobs"], 1)
        summary = history_summary(self.db_path)
        self.assertEqual(summary["total_jobs"], 1)
        with db.session(self.db_path) as conn:
            ids = {int(row["id"]) for row in conn.execute("SELECT id FROM conversion_jobs").fetchall()}
        self.assertNotIn(terminal, ids)
        self.assertIn(paused, ids)


if __name__ == "__main__":
    unittest.main()
