from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.transactions import ReplacementJournal, identity, recover_journals, sha256


def fake_exchange(a: Path, b: Path) -> None:
    swap = a.with_name(a.name + ".swap-test")
    os.replace(a, swap)
    os.replace(b, a)
    os.replace(swap, b)


class TransactionRecoveryTest(unittest.TestCase):
    def _files(self, root: Path) -> tuple[Path, Path, Path]:
        source = root / "track.flac"
        temp = root / ".track.flac.sox-resampler.tmp.flac"
        journal_root = root / "journals"
        source.write_bytes(b"ORIGINAL AUDIO BYTES")
        temp.write_bytes(b"NEW RESAMPLED AUDIO BYTES")
        return source, temp, journal_root

    def test_prepared_discards_only_known_new_temp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, temp, journals = self._files(Path(tmp))
            old = identity(source)
            new_sha = sha256(temp)
            journal = ReplacementJournal(journals, source)
            journal.prepare(source, temp, old, new_sha)

            outcomes = recover_journals(journals, fake_exchange)

            self.assertEqual(source.read_bytes(), b"ORIGINAL AUDIO BYTES")
            self.assertFalse(temp.exists())
            self.assertEqual(outcomes[0]["action"], "discarded_uncommitted_temp")
            self.assertFalse(journal.path.exists())

    def test_exchanged_rolls_back_to_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, temp, journals = self._files(Path(tmp))
            old = identity(source)
            new_sha = sha256(temp)
            journal = ReplacementJournal(journals, source)
            journal.prepare(source, temp, old, new_sha)
            fake_exchange(source, temp)
            journal.mark_exchanged()

            outcomes = recover_journals(journals, fake_exchange)

            self.assertEqual(source.read_bytes(), b"ORIGINAL AUDIO BYTES")
            self.assertFalse(temp.exists())
            self.assertEqual(outcomes[0]["action"], "rolled_back_interrupted_exchange")
            self.assertFalse(journal.path.exists())

    def test_verified_finishes_cleanup_without_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, temp, journals = self._files(Path(tmp))
            old = identity(source)
            new_sha = sha256(temp)
            journal = ReplacementJournal(journals, source)
            journal.prepare(source, temp, old, new_sha)
            fake_exchange(source, temp)
            journal.mark_exchanged()
            journal.mark_verified()

            outcomes = recover_journals(journals, fake_exchange)

            self.assertEqual(source.read_bytes(), b"NEW RESAMPLED AUDIO BYTES")
            self.assertFalse(temp.exists())
            self.assertEqual(outcomes[0]["action"], "finished_verified_cleanup")
            self.assertFalse(journal.path.exists())

    def test_ambiguous_state_is_never_modified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, temp, journals = self._files(Path(tmp))
            old = identity(source)
            new_sha = sha256(temp)
            journal = ReplacementJournal(journals, source)
            journal.prepare(source, temp, old, new_sha)
            source.write_bytes(b"UNEXPECTED EXTERNAL CHANGE")

            outcomes = recover_journals(journals, fake_exchange)

            self.assertTrue(source.exists())
            self.assertTrue(temp.exists())
            self.assertTrue(journal.path.exists())
            self.assertEqual(outcomes[0]["action"], "manual_attention")


if __name__ == "__main__":
    unittest.main()
