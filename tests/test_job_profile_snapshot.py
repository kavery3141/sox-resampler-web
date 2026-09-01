from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import db
from app.jobs import ConversionJobManager
from app.profiles import FOOBAR_ULTRA_37, apply_profile_override


class JobProfileSnapshotTests(unittest.TestCase):
    def test_job_keeps_exact_resolved_dsp_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            music = root / "music"
            album_folder = music / "Artist" / "Album"
            album_folder.mkdir(parents=True)
            source = album_folder / "track.flac"
            source.write_bytes(b"placeholder")
            db_path = root / "data" / "test.db"
            db.init(db_path)
            manager = ConversionJobManager(db_path, music, "America/Indiana/Indianapolis")

            resolved = apply_profile_override(
                FOOBAR_ULTRA_37,
                {
                    "target_rate": 44100,
                    "bit_depth": 16,
                    "dither": "shibata",
                    "headroom_db": -1.0,
                    "flac_compression": 6,
                },
            )
            review = {
                "blockers": [],
                "can_start": True,
                "profile": resolved.to_dict(),
                "albums": [
                    {
                        "albumartist": "Artist",
                        "album": "Album",
                        "folder": str(album_folder),
                        "tracks": [{"path": str(source), "source_bytes": source.stat().st_size}],
                    }
                ],
            }
            job_id = manager.create_job(
                review,
                "foobar-ultra-37-48k",
                1,
                {"rates": [96000], "above": None},
            )

            # Mutating the caller's review after job creation must not alter queued work.
            review["profile"]["target_rate"] = 32000
            job = manager.get_job(job_id)
            self.assertIsNotNone(job)
            self.assertEqual(job["profile"]["target_rate"], 44100)
            self.assertEqual(job["profile"]["bit_depth"], 16)
            self.assertEqual(job["profile"]["dither"], "shibata")
            self.assertEqual(job["profile"]["headroom_db"], -1.0)
            self.assertEqual(job["profile"]["flac_compression"], 6)


if __name__ == "__main__":
    unittest.main()
