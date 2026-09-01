from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from app.converter import ConversionError, _run_sox_command, convert_file
from app.profiles import FACTORY_DEFAULTS


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ForceStopTest(unittest.TestCase):
    def test_cancellable_process_terminates_process_group_promptly(self) -> None:
        calls = 0

        def abort() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 2

        started = time.monotonic()
        with self.assertRaises(ConversionError) as ctx:
            _run_sox_command(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                abort,
            )
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 5.0)
        self.assertIn("SoX terminated", str(ctx.exception))

    def test_force_stop_before_conversion_leaves_original_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "01 - Test.flac"
            subprocess.run(
                [
                    "sox", "-n", "-r", "96000", "-b", "24", "-c", "2",
                    str(source), "synth", "0.05", "sine", "997", "vol", "0.1",
                ],
                check=True,
                capture_output=True,
            )
            before = sha256(source)
            temp = source.with_name(f".{source.name}.sox-resampler.tmp.flac")
            result = convert_file(source, FACTORY_DEFAULTS, abort_check=lambda: True)
            self.assertEqual(result.status, "failed")
            self.assertIn("Force stop requested", result.error or "")
            self.assertEqual(sha256(source), before)
            self.assertFalse(temp.exists())


if __name__ == "__main__":
    unittest.main()
