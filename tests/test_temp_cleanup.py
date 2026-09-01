from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from mutagen.flac import FLAC

from app import db
from app.index_update import refresh_track
from app.temp_cleanup import cleanup_orphan_temps


class OrphanTempCleanupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.music = root / "music"
        self.folder = self.music / "Artist" / "Album"
        self.folder.mkdir(parents=True)
        self.data = root / "data"
        self.db_path = self.data / "test.db"
        self.journals = self.data / "transactions"
        self.journals.mkdir(parents=True)
        db.init(self.db_path)
        self.source = self.folder / "01 - Test.flac"
        subprocess.run(
            ["sox", "-n", "-r", "96000", "-b", "24", str(self.source), "synth", "0.03", "sine", "997", "vol", "0.05"],
            check=True,
            capture_output=True,
        )
        audio = FLAC(self.source)
        audio["ALBUMARTIST"] = ["Artist"]
        audio["ALBUM"] = ["Album"]
        audio["RELEASETYPE"] = ["album"]
        audio["MUSICBRAINZ_ALBUMID"] = ["00000000-0000-0000-0000-000000000001"]
        audio.save()
        refresh_track(
            self.db_path,
            self.music,
            self.source,
            "America/Indiana/Indianapolis",
        )
        self.temp = self.source.with_name(f".{self.source.name}.sox-resampler.tmp.flac")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_unjournaled_temp_is_removed_only_when_original_still_matches_index(self) -> None:
        self.temp.write_bytes(b"partial generated output")
        outcomes = cleanup_orphan_temps(self.music, self.db_path, self.journals)
        self.assertFalse(self.temp.exists())
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["action"], "removed_orphan_temp")

    def test_ambiguous_temp_is_left_untouched_after_original_changes(self) -> None:
        self.temp.write_bytes(b"unknown temp")
        audio = FLAC(self.source)
        audio["COMMENT"] = ["changed after indexing"]
        audio.save()
        outcomes = cleanup_orphan_temps(self.music, self.db_path, self.journals)
        self.assertTrue(self.temp.exists())
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["action"], "manual_attention")
        self.assertIn("no longer matches", outcomes[0]["reason"])

    def test_journal_owned_temp_is_never_touched_by_orphan_cleanup(self) -> None:
        self.temp.write_bytes(b"journal owned")
        journal = self.journals / "known.json"
        journal.write_text(
            json.dumps({"temp": str(self.temp), "source": str(self.source)}),
            encoding="utf-8",
        )
        outcomes = cleanup_orphan_temps(self.music, self.db_path, self.journals)
        self.assertTrue(self.temp.exists())
        self.assertEqual(outcomes, [])

    def test_malformed_journal_forces_unknown_temp_to_manual_attention(self) -> None:
        self.temp.write_bytes(b"unknown temp")
        (self.journals / "broken.json").write_text("{not-json", encoding="utf-8")
        outcomes = cleanup_orphan_temps(self.music, self.db_path, self.journals)
        self.assertTrue(self.temp.exists())
        self.assertEqual(outcomes[0]["action"], "manual_attention")
        self.assertIn("malformed transaction journal", outcomes[0]["reason"])


if __name__ == "__main__":
    unittest.main()
