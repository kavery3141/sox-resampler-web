from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.busy_guard import SourceAccessError, SourceBusyError, source_read_guard


class BusyGuardTest(unittest.TestCase):
    def test_missing_source_keeps_clear_unavailable_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.flac"
            with self.assertRaises(SourceAccessError) as ctx:
                with source_read_guard(missing):
                    pass
            self.assertIn("Source unavailable before conversion", str(ctx.exception))
            self.assertIn(str(missing), str(ctx.exception))

    def test_unlocked_source_gets_supported_shared_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "track.flac"
            path.write_bytes(b"test")
            with source_read_guard(path) as state:
                self.assertTrue(state.supported)

    def test_conflicting_exclusive_flock_is_reported_busy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "track.flac"
            path.write_bytes(b"test")
            code = (
                "import fcntl,sys,time; "
                "f=open(sys.argv[1],'rb'); "
                "fcntl.flock(f.fileno(),fcntl.LOCK_EX); "
                "print('locked',flush=True); "
                "time.sleep(30)"
            )
            child = subprocess.Popen(
                [sys.executable, "-c", code, str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(child.stdout.readline().strip(), "locked")
                with self.assertRaises(SourceBusyError):
                    with source_read_guard(path):
                        pass
            finally:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
