from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_ZFS_POOL = "MainStorage"
DEFAULT_ZFS_KSTAT_ROOT = Path("/proc/spl/kstat/zfs")
HEALTHY_POOL_STATES = {"ONLINE"}


def _kstat_pool_health(pool: str) -> dict[str, Any] | None:
    """Read the kernel-exported OpenZFS pool state without requiring /dev/zfs access.

    OpenZFS exposes ``/proc/spl/kstat/zfs/<pool>/state`` as a lightweight pool heartbeat. That
    proc entry is read-only and normally visible inside Linux containers because it comes from the
    host kernel, which makes it a much better primary health source for this unprivileged TrueNAS
    app than invoking libzfs from inside the container.

    ``None`` means the proc entry is not present and callers may try a secondary backend. Any
    present-but-unreadable or unrecognized state fails closed.
    """
    root = Path(os.getenv("ZFS_KSTAT_ROOT", str(DEFAULT_ZFS_KSTAT_ROOT)))
    state_path = root / pool / "state"
    try:
        state = state_path.read_text(encoding="utf-8").strip().upper()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return {
            "ok": False,
            "pool": pool,
            "state": None,
            "source": "kstat",
            "reason": f"ZFS pool state exists but cannot be read: {exc}",
            "detail": str(state_path),
        }

    if not state:
        return {
            "ok": False,
            "pool": pool,
            "state": None,
            "source": "kstat",
            "reason": "ZFS pool state is empty; health cannot be verified",
            "detail": str(state_path),
        }

    ok = state in HEALTHY_POOL_STATES
    return {
        "ok": ok,
        "pool": pool,
        "state": state,
        "source": "kstat",
        "reason": None if ok else f"ZFS pool {pool} is {state}, not ONLINE",
        "detail": str(state_path),
    }


def _zpool_cli_health(pool: str) -> dict[str, Any]:
    """Fallback for hosts where the OpenZFS proc kstat is not visible in the container."""
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
            "state": None,
            "source": "zpool",
            "reason": "ZFS kstat is unavailable and the zpool command is unavailable; pool health cannot be verified",
            "detail": None,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "pool": pool,
            "state": None,
            "source": "zpool",
            "reason": f"ZFS health check failed: {exc}",
            "detail": None,
        }

    detail = (result.stdout or result.stderr or "").strip()
    healthy_phrase = f"pool '{pool}' is healthy"
    ok = result.returncode == 0 and healthy_phrase.lower() in detail.lower()
    if ok:
        return {
            "ok": True,
            "pool": pool,
            "state": "ONLINE",
            "source": "zpool",
            "reason": None,
            "detail": detail,
        }

    reason = detail or f"zpool status exited with code {result.returncode}"
    return {
        "ok": False,
        "pool": pool,
        "state": None,
        "source": "zpool",
        "reason": f"ZFS pool health is not confirmed healthy: {reason}",
        "detail": detail or None,
    }


def zfs_pool_health() -> dict[str, Any]:
    """Return fail-closed health for the configured ZFS pool.

    The read-only OpenZFS kernel kstat is preferred so conversion does not require privileged
    ``/dev/zfs`` access. If that state file is absent, the existing ``zpool status -x`` check is
    retained as a fallback. Conversion is permitted only when one backend positively confirms the
    configured pool is healthy/ONLINE.
    """
    pool = os.getenv("ZFS_POOL", DEFAULT_ZFS_POOL).strip() or DEFAULT_ZFS_POOL
    kstat = _kstat_pool_health(pool)
    if kstat is not None:
        return kstat
    return _zpool_cli_health(pool)
