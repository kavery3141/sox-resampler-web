from __future__ import annotations

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
