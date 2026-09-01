from __future__ import annotations

import unittest
from unittest.mock import patch

from app.converter import ConversionError, ProfileUnavailable, apply_cpu_limit


class CpuLimitCommandTests(unittest.TestCase):
    def test_disabled_limit_leaves_command_unchanged(self) -> None:
        command = ["nice", "-n", "10", "sox", "in.flac", "out.flac"]
        self.assertIs(apply_cpu_limit(command, None), command)

    def test_enabled_limit_wraps_complete_execution_command(self) -> None:
        command = ["nice", "-n", "10", "ionice", "-c", "2", "sox", "in.flac", "out.flac"]
        with patch("app.converter.shutil.which", return_value="/usr/bin/cpulimit"):
            wrapped = apply_cpu_limit(command, 55)
        self.assertEqual(wrapped[:6], ["cpulimit", "-q", "-l", "55", "--", "nice"])
        self.assertEqual(wrapped[5:], command)

    def test_invalid_limit_is_rejected(self) -> None:
        with self.assertRaises(ConversionError):
            apply_cpu_limit(["sox"], 9)
        with self.assertRaises(ConversionError):
            apply_cpu_limit(["sox"], 101)

    def test_missing_cpulimit_fails_before_conversion(self) -> None:
        with patch("app.converter.shutil.which", return_value=None):
            with self.assertRaises(ProfileUnavailable):
                apply_cpu_limit(["sox"], 50)


if __name__ == "__main__":
    unittest.main()
