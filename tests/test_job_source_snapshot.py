from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mutagen.flac import FLAC

from app import db
from app.index_update import refresh_track
from app.jobs import ConversionJobManager
from app.profiles import FACTORY_DEFAULTS
from app.review import build_batch_review
from app.source_snapshot import compare_source_snapshots


class JobSourceSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.music = root / "music"
        self.folder = self.music / "Artist" / "Album"
        self.folder.mkdir(parents=True)
        self.db_path = root / "data" / "test.db"
        db.init(self.db_path)
        self.track = self.folder / "01 - Test.flac"
        subprocess.run(
            ["sox", "-n", "-r", "96000", "-b", "24", str(self.track), "synth", "0.03", "sine", "997", "vol", "0.05"],
            check=True,
            capture_output=True,
        )
        audio = FLAC(self.track)
        audio["ALBUMARTIST"] = ["Artist"]
        audio["ALBUM"] = ["Album"]
        audio["RELEASETYPE"] = ["album"]
        audio["MUSICBRAINZ_ALBUMID"] = ["00000000-0000-0000-0000-000000000001"]
        audio["TITLE"] = ["Test"]
        audio["TRACKNUMBER"] = ["1"]
        audio.save()
        refresh_track(
            self.db_path,
            self.music,
            self.track,
            "America/Indiana/Indianapolis",
        )
        self.manager = ConversionJobManager(
            self.db_path,
            self.music,
            "America/Indiana/Indianapolis",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _review(self) -> dict:
        return build_batch_review(
            db_path=self.db_path,
            music_root=self.music,
            album_keys=[
                {"albumartist": "Artist", "album": "Album", "folder": str(self.folder)}
            ],
            rates=[96000],
            above=None,
            profile=FACTORY_DEFAULTS,
            workers=1,
            reserve_bytes=0,
        )

    def test_review_snapshot_is_persisted_with_job(self) -> None:
        review = self._review()
        self.assertTrue(review["can_start"], review["blockers"])
        snapshot = review["albums"][0]["tracks"][0]["source_snapshot"]
        self.assertEqual(snapshot["sample_rate"], 96000)
        self.assertEqual(snapshot["bits_per_sample"], 24)
        self.assertEqual(snapshot["critical_tags"]["ALBUMARTIST"], "Artist")
        self.assertGreater(snapshot["inode"], 0)

        job_id = self.manager.create_job(review, FACTORY_DEFAULTS.id, 1, {"rates": [96000]})
        with db.session(self.db_path) as conn:
            row = conn.execute(
                "SELECT source_snapshot_json FROM conversion_files WHERE job_id=?",
                (job_id,),
            ).fetchone()
        stored = json.loads(row["source_snapshot_json"])
        self.assertEqual(stored, snapshot)

    def test_inode_replacement_after_review_is_rejected_before_converter(self) -> None:
        review = self._review()
        self.assertTrue(review["can_start"], review["blockers"])
        job_id = self.manager.create_job(review, FACTORY_DEFAULTS.id, 1, {"rates": [96000]})
        with db.session(self.db_path) as conn:
            row = conn.execute(
                "SELECT id,path,source_bytes,source_snapshot_json FROM conversion_files WHERE job_id=?",
                (job_id,),
            ).fetchone()
        expected = json.loads(row["source_snapshot_json"])

        original_stat = self.track.stat()
        replacement = self.folder / "replacement.flac"
        shutil.copyfile(self.track, replacement)
        os.utime(
            replacement,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )
        os.replace(replacement, self.track)
        os.utime(
            self.track,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )
        self.assertEqual(self.track.stat().st_size, int(row["source_bytes"]))
        self.assertEqual(self.track.stat().st_mtime_ns, expected["mtime_ns"])
        self.assertNotEqual(self.track.stat().st_ino, expected["inode"])

        with patch("app.jobs.convert_file") as convert:
            payload = self.manager._run_file(
                job_id,
                int(row["id"]),
                str(row["path"]),
                FACTORY_DEFAULTS,
                int(row["source_bytes"]),
            )

        convert.assert_not_called()
        self.assertEqual(payload["status"], "failed")
        self.assertIn("inode changed", payload["error"])
        self.assertIn("original left untouched", payload["error"])
        with db.session(self.db_path) as conn:
            events = conn.execute(
                "SELECT event_type FROM conversion_job_events WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        self.assertIn("source_revalidation_failed", [event["event_type"] for event in events])

    def test_snapshot_comparison_reports_critical_tag_change(self) -> None:
        expected = {
            "device": 1,
            "inode": 2,
            "size_bytes": 3,
            "mtime_ns": 4,
            "sample_rate": 96000,
            "bits_per_sample": 24,
            "channels": 2,
            "critical_tags": {
                "ALBUMARTIST": "Artist",
                "ALBUM": "Album",
                "RELEASETYPE": "album",
                "MUSICBRAINZ_ALBUMID": "mbid",
            },
        }
        current = json.loads(json.dumps(expected))
        current["critical_tags"]["ALBUM"] = "Changed Album"
        changes = compare_source_snapshots(expected, current)
        self.assertEqual(len(changes), 1)
        self.assertIn("ALBUM changed", changes[0])


if __name__ == "__main__":
    unittest.main()
