from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db
from app.admin import (
    _job_runtime_times,
    _normalize_exclusions,
    _preview_exclusions,
    _recovery_summary,
    build_admin_router,
)
from app.job_events import record_job_event
from app.jobs import ensure_tables


class AdminSettingsTests(unittest.TestCase):
    def test_exclusions_are_normalized_under_music_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            exact, globs = _normalize_exclusions(root, ["Archive", str(root / "Test")], ["*/Samples/*", ""])
            self.assertEqual(exact, sorted([str(root / "Archive"), str(root / "Test")]))
            self.assertEqual(globs, ["*/Samples/*"])

    def test_exclusion_cannot_escape_music_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            with self.assertRaises(ValueError):
                _normalize_exclusions(root, [str(Path(tmp) / "other")], [])

    def test_preview_counts_excluded_flacs_without_following_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            keep = root / "Artist" / "Album"
            archive = root / "Archive" / "Old"
            keep.mkdir(parents=True)
            archive.mkdir(parents=True)
            (keep / "track.flac").write_bytes(b"not-real-audio")
            (archive / "one.flac").write_bytes(b"x")
            (archive / "two.FLAC").write_bytes(b"x")
            exact, globs = _normalize_exclusions(root, ["Archive"], [])
            result = _preview_exclusions(root, exact, globs)
            self.assertEqual(result["folders"], 1)
            self.assertEqual(result["flac_files"], 2)

    def test_recovery_summary_marks_manual_attention_and_errors_as_blocking(self) -> None:
        result = _recovery_summary(
            [
                {"action": "finished_verified_cleanup"},
                {"action": "manual_attention"},
                {"action": "recovery_error: permission denied"},
            ]
        )
        self.assertEqual(result["items"], 3)
        self.assertEqual(result["automatic_actions"], 1)
        self.assertEqual(result["manual_attention"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertTrue(result["blocked"])

    def test_manual_recovery_recheck_replaces_stale_runtime_status(self) -> None:
        class IdleScanner:
            def snapshot(self):
                return {"running": False}

        class IdleJobs:
            def is_running(self):
                return False

            def active_job_id(self):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            music = root / "music"
            data_root = root / "data"
            music.mkdir()
            data_root.mkdir()
            status = [{"action": "manual_attention", "source": "/old/problem.flac"}]
            router = build_admin_router(
                db_path=data_root / "test.db",
                music_root=music,
                data_root=data_root,
                timezone="America/Indiana/Indianapolis",
                app_version="test",
                scanner=IdleScanner(),
                job_manager=IdleJobs(),
                scan_async=lambda mode: {"mode": mode},
                recovery_status=lambda: status,
            )
            endpoint = next(
                route.endpoint
                for route in router.routes
                if getattr(route, "path", None) == "/api/maintenance/recovery/recheck"
            )
            transaction = [{"action": "cleared_prepared_journal", "source": "/music/a.flac"}]
            orphan = [{"action": "manual_attention", "source": "/music/b.flac", "reason": "ambiguous"}]
            with (
                patch("app.admin.recover_pending_transactions", return_value=transaction),
                patch("app.admin.cleanup_orphan_temps", return_value=orphan),
                patch("app.admin.record_event"),
            ):
                result = endpoint()

            self.assertEqual(status, transaction + orphan)
            self.assertFalse(result["safe_for_conversion"])
            self.assertEqual(result["summary"]["manual_attention"], 1)
            self.assertEqual(result["summary"]["automatic_actions"], 1)

    def test_job_runtime_times_union_parallel_files_and_preserve_idle_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime.db"
            db.init(db_path)
            ensure_tables(db_path)
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
                        "2026-09-01T10:00:40-04:00",
                        "completed",
                        "foobar-ultra-37-48k",
                        2,
                        "{}",
                        "[]",
                    ),
                )
                job_id = int(cur.lastrowid)
                rows = [
                    (0, "a.flac", "2026-09-01T10:00:00-04:00", "2026-09-01T10:00:10-04:00"),
                    (1, "b.flac", "2026-09-01T10:00:05-04:00", "2026-09-01T10:00:15-04:00"),
                    (2, "c.flac", "2026-09-01T10:00:25-04:00", "2026-09-01T10:00:40-04:00"),
                ]
                for index, filename, started, finished in rows:
                    conn.execute(
                        """
                        INSERT INTO conversion_files(
                          job_id,album_index,file_index,albumartist,album,path,source_bytes,status,
                          started_at,finished_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?)
                        """,
                        (job_id, 0, index, "Artist", "Album", f"/music/{filename}", 1000, "completed", started, finished),
                    )
            result = _job_runtime_times(db_path, job_id)
            self.assertEqual(result["wall_seconds"], 40.0)
            self.assertEqual(result["active_seconds"], 30.0)
            self.assertEqual(result["paused_seconds"], 0.0)
            self.assertEqual(result["interrupted_seconds"], 0.0)
            self.assertEqual(result["idle_seconds"], 10.0)
            self.assertEqual(result["paused_or_idle_seconds"], 10.0)
            self.assertEqual(result["active_files"], 0)

    def test_job_runtime_times_separates_real_pause_from_between_file_idle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "runtime-paused.db"
            db.init(db_path)
            ensure_tables(db_path)
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
                        "2026-09-01T10:00:35-04:00",
                        "completed",
                        "foobar-ultra-37-48k",
                        1,
                        "{}",
                        "[]",
                    ),
                )
                job_id = int(cur.lastrowid)
                for index, filename, started, finished in [
                    (0, "a.flac", "2026-09-01T10:00:00-04:00", "2026-09-01T10:00:10-04:00"),
                    (1, "b.flac", "2026-09-01T10:00:20-04:00", "2026-09-01T10:00:30-04:00"),
                ]:
                    conn.execute(
                        """
                        INSERT INTO conversion_files(
                          job_id,album_index,file_index,albumartist,album,path,source_bytes,status,
                          started_at,finished_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?)
                        """,
                        (job_id, 0, index, "Artist", "Album", f"/music/{filename}", 1000, "completed", started, finished),
                    )
            record_job_event(
                db_path, job_id, "2026-09-01T10:00:10-04:00", "job_finished", {"status": "paused"}
            )
            record_job_event(
                db_path, job_id, "2026-09-01T10:00:20-04:00", "job_resumed", {"previous_status": "paused", "workers": 1}
            )
            record_job_event(
                db_path, job_id, "2026-09-01T10:00:35-04:00", "job_finished", {"status": "completed"}
            )
            result = _job_runtime_times(db_path, job_id)
            self.assertEqual(result["wall_seconds"], 35.0)
            self.assertEqual(result["active_seconds"], 20.0)
            self.assertEqual(result["paused_seconds"], 10.0)
            self.assertEqual(result["interrupted_seconds"], 0.0)
            self.assertEqual(result["idle_seconds"], 5.0)
            self.assertEqual(result["paused_or_idle_seconds"], 15.0)


if __name__ == "__main__":
    unittest.main()
