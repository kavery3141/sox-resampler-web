from __future__ import annotations

from typing import Any


def summarize_health(
    *,
    music_exists: bool,
    music_readable: bool,
    music_writable: bool,
    data_exists: bool,
    data_writable: bool,
    db_ok: bool,
    stock_sox: str | None,
    ultra_sox: str | None,
    flac: str | None,
    rsgain: str | None,
    zfs: dict[str, Any],
    read_only_mode: bool,
    cpu_limit_percent: int | None = None,
    cpu_limiter_available: bool = True,
) -> dict[str, Any]:
    """Separate service health from destructive-conversion readiness.

    ``status`` is deliberately informational; the HTTP health endpoint still returns 200 so a
    degraded pool or intentionally enabled read-only mode cannot create a container restart loop.
    ``conversion_ready`` is the stricter gate an administrator can use to see whether new
    destructive conversion work is safe to start.
    """
    health_reasons: list[str] = []
    conversion_blockers: list[str] = []

    if not music_exists:
        health_reasons.append("Music root is unavailable")
    elif not music_readable:
        health_reasons.append("Music root is not readable")

    if not data_exists:
        health_reasons.append("App data root is unavailable")
    elif not data_writable:
        health_reasons.append("App data root is not writable")

    if not db_ok:
        health_reasons.append("SQLite database is unavailable")
    if not stock_sox:
        health_reasons.append("Stock SoX tool is unavailable")
    if not ultra_sox:
        health_reasons.append("Ultra 37 SoX backend is unavailable")
    if not flac:
        health_reasons.append("FLAC verification tool is unavailable")
    if not rsgain:
        health_reasons.append("ReplayGain 2.0 rsgain tool is unavailable")
    if not bool(zfs.get("ok")):
        health_reasons.append(str(zfs.get("reason") or "ZFS pool health is not confirmed healthy"))

    conversion_blockers.extend(health_reasons)
    if music_exists and music_readable and not music_writable:
        conversion_blockers.append("Music root is not writable")
    if read_only_mode:
        conversion_blockers.append("Read-only Scan Mode is enabled")
    if cpu_limit_percent is not None and not cpu_limiter_available:
        conversion_blockers.append(
            "A conversion CPU cap is configured but the cpulimit runtime is unavailable"
        )

    health_reasons = list(dict.fromkeys(health_reasons))
    conversion_blockers = list(dict.fromkeys(conversion_blockers))
    return {
        "status": "ok" if not health_reasons else "degraded",
        "conversion_ready": not conversion_blockers,
        "health_reasons": health_reasons,
        "conversion_blockers": conversion_blockers,
        "read_only_mode": bool(read_only_mode),
    }
