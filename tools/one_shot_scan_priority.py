from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match in {path}, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def write_new(path: str, content: str) -> None:
    file_path = Path(path)
    if file_path.exists():
        raise SystemExit(f"refusing to overwrite existing file: {path}")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


write_new(
    "app/background_priority.py",
    '''from __future__ import annotations

import os
import subprocess
import threading
from typing import Any


DEFAULT_CPU_NICE = 10
DEFAULT_IO_LEVEL = 7


def apply_background_priority(
    *,
    cpu_nice: int = DEFAULT_CPU_NICE,
    io_level: int = DEFAULT_IO_LEVEL,
    skip_main_thread: bool = True,
) -> dict[str, Any]:
    """Best-effort Linux per-thread priority reduction for background storage work."""
    result: dict[str, Any] = {
        "cpu_nice": int(cpu_nice),
        "io_class": "best-effort",
        "io_level": int(io_level),
        "cpu_applied": False,
        "io_applied": False,
        "warnings": [],
    }
    if skip_main_thread and threading.current_thread() is threading.main_thread():
        result["skipped"] = "main-thread invocation"
        return result

    native_id = int(threading.get_native_id())
    result["native_thread_id"] = native_id
    try:
        os.setpriority(os.PRIO_PROCESS, native_id, int(cpu_nice))
        result["cpu_applied"] = True
    except (AttributeError, OSError) as exc:
        result["warnings"].append(f"CPU priority hint unavailable: {exc}")

    try:
        proc = subprocess.run(
            ["ionice", "-c", "2", "-n", str(int(io_level)), "-p", str(native_id)],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if proc.returncode == 0:
            result["io_applied"] = True
        else:
            detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
            result["warnings"].append(f"I/O priority hint unavailable: {detail}")
    except (OSError, subprocess.SubprocessError) as exc:
        result["warnings"].append(f"I/O priority hint unavailable: {exc}")

    return result
''',
)

replace_once(
    "app/scanner.py",
    "from .artwork import prune_album_artwork, refresh_album_artwork\n",
    "from .artwork import prune_album_artwork, refresh_album_artwork\nfrom .background_priority import apply_background_priority\n",
    "scanner priority import",
)
replace_once(
    "app/scanner.py",
    "    last_error: str | None = None\n",
    "    last_error: str | None = None\n    background_priority: dict[str, Any] | None = None\n",
    "scanner priority state",
)
replace_once(
    "app/scanner.py",
    '''        dbmod.init(self.db_path)\n        exact = dbmod.get_setting(self.db_path, "exclude_paths", []) or []\n''',
    '''        self._set_state(background_priority=apply_background_priority())\n        dbmod.init(self.db_path)\n        exact = dbmod.get_setting(self.db_path, "exclude_paths", []) or []\n''',
    "scanner priority application",
)

write_new(
    "tests/test_background_priority.py",
    '''from __future__ import annotations

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
''',
)

print("Low-priority scan implementation applied")
