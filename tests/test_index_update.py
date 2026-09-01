from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from mutagen.flac import FLAC

from app import db
from app.index_update import refresh_track


class IndexUpdateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.music = root / "music"
        self.music.mkdir()
        self.db_path = root / "data" / "test.db"
        db.init(self.db_path)
        self.track = self.music / "01 - Test.flac"
        subprocess.run(
            ["sox", "-n", "-r", "48000", "-b", "24", str(self.track), "synth", "0.03", "sine", "997", "vol", "0.05"],
            check=True,
            capture_output=True,
        )
        audio = FLAC(self.track)
        audio["ALBUMARTIST"] = ["Index Artist"]
        audio["ALBUM"] = ["Index Album"]
        audio["RELEASETYPE"] = ["album"]
        audio["MUSICBRAINZ_ALBUMID"] = ["00000000-0000-0000-0000-000000000001"]
        audio["TITLE"] = ["Test"]
        audio["TRACKNUMBER"] = ["1"]
        audio.save()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_refresh_track_inserts_current_technical_and_tag_data(self) -> None:
        result = refresh_track(
            self.db_path,
            self.music,
            self.track,
            "America/Indiana/Indianapolis",
        )
        self.assertEqual(result["sample_rate"], 48000)
        self.assertEqual(result["bits_per_sample"], 24)

        with db.session(self.db_path) as conn:
            row = conn.execute("SELECT * FROM tracks WHERE path=?", (str(self.track.resolve()),)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["sample_rate"], 48000)
        self.assertEqual(row["bits_per_sample"], 24)
        self.assertEqual(row["albumartist"], "Index Artist")
        self.assertEqual(row["album"], "Index Album")
        self.assertEqual(row["releasetype"], "album")
        self.assertEqual(row["musicbrainz_albumid"], "00000000-0000-0000-0000-000000000001")

    def test_refresh_track_preserves_first_seen_on_reprobe(self) -> None:
        first = refresh_track(self.db_path, self.music, self.track, "America/Indiana/Indianapolis")
        second = refresh_track(self.db_path, self.music, self.track, "America/Indiana/Indianapolis")
        self.assertEqual(first["first_seen"], second["first_seen"])

    def test_refresh_track_rejects_path_outside_music_root(self) -> None:
        other = Path(self.tmp.name) / "outside.flac"
        other.write_bytes(self.track.read_bytes())
        with self.assertRaises(ValueError):
            refresh_track(self.db_path, self.music, other, "America/Indiana/Indianapolis")


if __name__ == "__main__":
    unittest.main()
