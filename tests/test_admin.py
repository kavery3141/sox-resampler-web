from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.admin import _normalize_exclusions, _preview_exclusions


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


if __name__ == "__main__":
    unittest.main()
