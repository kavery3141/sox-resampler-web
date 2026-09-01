from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import db
from app.admin import _job_runtime_times, _normalize_exclusions, _preview_exclusions
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
            self.assertEqual(result["paused_or_idle_seconds"], 10.0)
            self.assertEqual(result["active_files"], 0)


if __name__ == "__main__":
    unittest.main()
