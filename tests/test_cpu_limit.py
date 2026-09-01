from __future__ import annotations

import unittest
from unittest.mock import patch

from app.converter import (
    ConversionError,
    ProfileUnavailable,
    cpu_limiter_command,
    validate_cpu_limit,
)


class CpuLimitCommandTests(unittest.TestCase):
    def test_disabled_limit_requires_no_limiter(self) -> None:
        self.assertIsNone(validate_cpu_limit(None))

    def test_enabled_limit_validates_and_builds_pid_controller(self) -> None:
        with patch("app.converter.shutil.which", return_value="/usr/bin/cpulimit"):
            limit = validate_cpu_limit(55)
        self.assertEqual(limit, 55)
        self.assertEqual(
            cpu_limiter_command(1234, limit),
            ["cpulimit", "-q", "-z", "-l", "55", "-p", "1234"],
        )

    def test_invalid_limit_is_rejected(self) -> None:
        with self.assertRaises(ConversionError):
            validate_cpu_limit(9)
        with self.assertRaises(ConversionError):
            validate_cpu_limit(101)
        with self.assertRaises(ConversionError):
            cpu_limiter_command(0, 50)

    def test_missing_cpulimit_fails_before_conversion(self) -> None:
        with patch("app.converter.shutil.which", return_value=None):
            with self.assertRaises(ProfileUnavailable):
                validate_cpu_limit(50)


if __name__ == "__main__":
    unittest.main()
