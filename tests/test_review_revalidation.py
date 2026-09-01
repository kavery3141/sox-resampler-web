from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from mutagen.flac import FLAC

from app import db
from app.index_update import refresh_track
from app.profiles import FOOBAR_ULTRA_37
from app.review import build_batch_review


class ReviewRevalidationTest(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def review(self) -> dict:
        return build_batch_review(
            db_path=self.db_path,
            music_root=self.music,
            album_keys=[
                {
                    "albumartist": "Artist",
                    "album": "Album",
                    "folder": str(self.folder),
                }
            ],
            rates=[96000],
            above=None,
            profile=FOOBAR_ULTRA_37,
            workers=1,
            reserve_bytes=10 * 1024**3,
        )

    def test_unchanged_indexed_album_passes_source_revalidation(self) -> None:
        review = self.review()
        self.assertTrue(review["can_start"], review["blockers"])
        self.assertEqual(review["matching_tracks"], 1)

    def test_tag_change_after_scan_blocks_start_until_rescan(self) -> None:
        audio = FLAC(self.track)
        audio["ALBUM"] = ["Changed Album"]
        audio.save()
        review = self.review()
        self.assertFalse(review["can_start"])
        text = " | ".join(review["blockers"])
        self.assertIn("rescan required", text)

    def test_new_track_after_scan_blocks_album_track_count(self) -> None:
        second = self.folder / "02 - New.flac"
        second.write_bytes(self.track.read_bytes())
        audio = FLAC(second)
        audio["TRACKNUMBER"] = ["2"]
        audio.save()
        review = self.review()
        self.assertFalse(review["can_start"])
        text = " | ".join(review["blockers"])
        self.assertIn("Album track count changed since scan", text)


if __name__ == "__main__":
    unittest.main()
