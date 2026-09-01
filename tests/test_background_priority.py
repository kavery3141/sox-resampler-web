from __future__ import annotations

import subprocess
import threading
import unittest
from unittest.mock import patch

from app.background_priority import apply_background_priority


class BackgroundPriorityTests(unittest.TestCase):
    def test_background_thread_gets_cpu_and_io_priority_hints(self) -> None:
        completed = subprocess.CompletedProcess(args=["ionice"], returncode=0, stdout="", stderr="")
        with (
            patch("app.background_priority.threading.current_thread", return_value=object()),
            patch("app.background_priority.threading.main_thread", return_value=object()),
            patch("app.background_priority.threading.get_native_id", return_value=4321),
            patch("app.background_priority.os.setpriority") as setpriority,
            patch("app.background_priority.subprocess.run", return_value=completed) as run,
        ):
            result = apply_background_priority()

        setpriority.assert_called_once_with(0, 4321, 10)
        run.assert_called_once_with(
            ["ionice", "-c", "2", "-n", "7", "-p", "4321"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        self.assertTrue(result["cpu_applied"])
        self.assertTrue(result["io_applied"])
        self.assertEqual(result["warnings"], [])

    def test_priority_failures_are_advisory_not_fatal(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["ionice"], returncode=1, stdout="", stderr="operation not permitted"
        )
        with (
            patch("app.background_priority.threading.current_thread", return_value=object()),
            patch("app.background_priority.threading.main_thread", return_value=object()),
            patch("app.background_priority.threading.get_native_id", return_value=55),
            patch("app.background_priority.os.setpriority", side_effect=PermissionError("denied")),
            patch("app.background_priority.subprocess.run", return_value=completed),
        ):
            result = apply_background_priority()

        self.assertFalse(result["cpu_applied"])
        self.assertFalse(result["io_applied"])
        self.assertEqual(len(result["warnings"]), 2)
        self.assertIn("CPU priority hint unavailable", result["warnings"][0])
        self.assertIn("operation not permitted", result["warnings"][1])

    def test_main_thread_is_left_unchanged(self) -> None:
        main = threading.main_thread()
        with (
            patch("app.background_priority.threading.current_thread", return_value=main),
            patch("app.background_priority.threading.main_thread", return_value=main),
            patch("app.background_priority.os.setpriority") as setpriority,
            patch("app.background_priority.subprocess.run") as run,
        ):
            result = apply_background_priority()

        setpriority.assert_not_called()
        run.assert_not_called()
        self.assertEqual(result["skipped"], "main-thread invocation")


if __name__ == "__main__":
    unittest.main()
