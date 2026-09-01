from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db
from app.scanner import LibraryScanner, ScanState, recover_interrupted_scan_runs


class ScannerControlsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.music = root / "music"
        self.music.mkdir()
        self.db_path = root / "data" / "test.db"
        db.init(self.db_path)
        self.scanner = LibraryScanner(
            self.music,
            self.db_path,
            "America/Indiana/Indianapolis",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_request_pause_is_only_available_for_active_full_scan(self) -> None:
        self.scanner.state = ScanState(running=True, status="running", mode="incremental")
        self.assertFalse(self.scanner.request_pause())

        with db.session(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO scan_runs(started_at,mode,status) VALUES(?,?,?)",
                (self.scanner._now(), "full", "running"),
            )
            run_id = int(cur.lastrowid)
        self.scanner.state = ScanState(
            running=True,
            status="running",
            mode="full",
            run_id=run_id,
        )
        self.scanner._run_id = run_id
        self.assertTrue(self.scanner.request_pause())
        self.assertEqual(self.scanner.snapshot()["status"], "pausing")
        with db.session(self.db_path) as conn:
            status = conn.execute("SELECT status FROM scan_runs WHERE id=?", (run_id,)).fetchone()["status"]
        self.assertEqual(status, "pausing")

    def test_full_scan_pause_exits_cleanly_without_stale_deletion_and_is_resumable(self) -> None:
        stale = self.music / "Artist" / "Album" / "stale.flac"
        with db.session(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO tracks(
                  path,rel_path,folder,filename,size_bytes,mtime_ns,sample_rate,bits_per_sample,
                  channels,duration,first_seen,last_seen,tag_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(stale),
                    "Artist/Album/stale.flac",
                    str(stale.parent),
                    stale.name,
                    100,
                    1,
                    96000,
                    24,
                    2,
                    1.0,
                    self.scanner._now(),
                    self.scanner._now(),
                    "{}",
                ),
            )

        def paused_walk(*args, **kwargs):
            self.scanner.request_pause()
            yield str(self.music), [], []

        with patch("app.scanner.os.walk", paused_walk):
            result = self.scanner.run("full")
        self.assertEqual(result["status"], "paused")
        self.assertFalse(result["running"])
        with db.session(self.db_path) as conn:
            self.assertIsNotNone(conn.execute("SELECT 1 FROM tracks WHERE path=?", (str(stale),)).fetchone())
        resumable = self.scanner.resumable()
        self.assertIsNotNone(resumable)
        self.assertEqual(resumable["status"], "paused")

        resumed = self.scanner.run("full-resume")
        self.assertEqual(resumed["status"], "completed")

    def test_traversal_error_never_purges_unseen_index_entries(self) -> None:
        stale = self.music / "Unavailable" / "track.flac"
        with db.session(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO tracks(
                  path,rel_path,folder,filename,size_bytes,mtime_ns,sample_rate,bits_per_sample,
                  channels,duration,first_seen,last_seen,tag_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(stale),
                    "Unavailable/track.flac",
                    str(stale.parent),
                    stale.name,
                    100,
                    1,
                    96000,
                    24,
                    2,
                    1.0,
                    self.scanner._now(),
                    self.scanner._now(),
                    "{}",
                ),
            )

        def broken_walk(*args, **kwargs):
            kwargs["onerror"](OSError("simulated storage traversal failure"))
            yield str(self.music), [], []

        with patch("app.scanner.os.walk", broken_walk):
            result = self.scanner.run("incremental")
        self.assertEqual(result["status"], "completed")
        self.assertGreaterEqual(result["errors"], 1)
        self.assertIn("stale index entries were preserved", result["last_error"])
        with db.session(self.db_path) as conn:
            self.assertIsNotNone(conn.execute("SELECT 1 FROM tracks WHERE path=?", (str(stale),)).fetchone())

    def test_restart_marks_running_scan_interrupted_but_preserves_paused_scan(self) -> None:
        stamp = self.scanner._now()
        with db.session(self.db_path) as conn:
            running = int(
                conn.execute(
                    "INSERT INTO scan_runs(started_at,mode,status) VALUES(?,?,?)",
                    (stamp, "full", "running"),
                ).lastrowid
            )
            paused = int(
                conn.execute(
                    "INSERT INTO scan_runs(started_at,mode,status) VALUES(?,?,?)",
                    (stamp, "full", "paused"),
                ).lastrowid
            )
        changed = recover_interrupted_scan_runs(
            self.db_path,
            "America/Indiana/Indianapolis",
        )
        self.assertGreaterEqual(changed, 1)
        with db.session(self.db_path) as conn:
            statuses = {
                int(row["id"]): row["status"]
                for row in conn.execute("SELECT id,status FROM scan_runs WHERE id IN (?,?)", (running, paused))
            }
        self.assertEqual(statuses[running], "interrupted")
        self.assertEqual(statuses[paused], "paused")


if __name__ == "__main__":
    unittest.main()
