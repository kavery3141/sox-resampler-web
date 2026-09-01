from __future__ import annotations

import os
import subprocess
from typing import Any


DEFAULT_ZFS_POOL = "MainStorage"


def zfs_pool_health() -> dict[str, Any]:
    """Return the health of the configured ZFS pool.

    This check is intentionally fail-closed. Conversion must not proceed when the
    pool status cannot be verified, the command fails, or ZFS reports anything
    other than a healthy pool.
    """
    pool = os.getenv("ZFS_POOL", DEFAULT_ZFS_POOL).strip() or DEFAULT_ZFS_POOL
    try:
        result = subprocess.run(
            ["zpool", "status", "-x", pool],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "pool": pool,
            "reason": "zpool command is unavailable; ZFS health cannot be verified",
            "detail": None,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "pool": pool,
            "reason": f"ZFS health check failed: {exc}",
            "detail": None,
        }

    detail = (result.stdout or result.stderr or "").strip()
    healthy_phrase = f"pool '{pool}' is healthy"
    ok = result.returncode == 0 and healthy_phrase.lower() in detail.lower()
    if ok:
        return {"ok": True, "pool": pool, "reason": None, "detail": detail}

    reason = detail or f"zpool status exited with code {result.returncode}"
    return {
        "ok": False,
        "pool": pool,
        "reason": f"ZFS pool health is not confirmed healthy: {reason}",
        "detail": detail or None,
    }
