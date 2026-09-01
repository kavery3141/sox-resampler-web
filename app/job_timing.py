from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from . import db
from .job_events import load_job_events

_TERMINAL_STATUSES = {"completed", "cancelled", "stopped"}
_RESUMABLE_STATUSES = {"paused", "interrupted"}


def _timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return None


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted((a, b) for a, b in intervals if b > a)
    merged: list[list[float]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _duration(intervals: list[tuple[float, float]]) -> float:
    return sum(end - start for start, end in _merge_intervals(intervals))


def _clip(interval: tuple[float, float], start: float, end: float) -> tuple[float, float] | None:
    a = max(start, interval[0])
    b = min(end, interval[1])
    return (a, b) if b > a else None


def _subtract_intervals(
    intervals: list[tuple[float, float]],
    blockers: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Return interval portions not covered by blockers."""
    remaining = _merge_intervals(intervals)
    for block_start, block_end in _merge_intervals(blockers):
        next_remaining: list[tuple[float, float]] = []
        for start, end in remaining:
            if block_end <= start or block_start >= end:
                next_remaining.append((start, end))
                continue
            if block_start > start:
                next_remaining.append((start, min(end, block_start)))
            if block_end < end:
                next_remaining.append((max(start, block_end), end))
        remaining = next_remaining
    return _merge_intervals(remaining)


def job_runtime_times(
    db_path: Path,
    job_id: int,
    *,
    now: float | None = None,
) -> dict[str, float | int | str | None]:
    """Calculate wall, file-active, paused, interrupted and idle job time.

    File-active time is the union of conversion-file intervals, so two parallel workers never
    double-count elapsed processing time. Paused/interrupted intervals come from the durable job
    event stream. Idle time is whatever remains inside the job wall-clock window after those
    classified intervals are removed; this includes ordinary between-file scheduling gaps.
    """
    now_ts = float(now) if now is not None else datetime.now().astimezone().timestamp()
    with db.session(db_path) as conn:
        job = conn.execute(
            "SELECT status,started_at,finished_at FROM conversion_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if not job:
            return {
                "status": None,
                "wall_seconds": 0.0,
                "active_seconds": 0.0,
                "paused_seconds": 0.0,
                "interrupted_seconds": 0.0,
                "idle_seconds": 0.0,
                "paused_or_idle_seconds": 0.0,
                "active_files": 0,
            }
        rows = conn.execute(
            "SELECT status,started_at,finished_at FROM conversion_files "
            "WHERE job_id=? AND started_at IS NOT NULL",
            (job_id,),
        ).fetchall()

    status = str(job["status"])
    wall_start = _timestamp(job["started_at"])
    if wall_start is None:
        return {
            "status": status,
            "wall_seconds": 0.0,
            "active_seconds": 0.0,
            "paused_seconds": 0.0,
            "interrupted_seconds": 0.0,
            "idle_seconds": 0.0,
            "paused_or_idle_seconds": 0.0,
            "active_files": 0,
        }
    wall_end = _timestamp(job["finished_at"]) if status in _TERMINAL_STATUSES else now_ts
    wall_end = max(wall_start, wall_end if wall_end is not None else now_ts)

    active_intervals: list[tuple[float, float]] = []
    active_files = 0
    for row in rows:
        file_start = _timestamp(row["started_at"])
        if file_start is None:
            continue
        file_end = _timestamp(row["finished_at"])
        if file_end is None and str(row["status"]) == "running":
            file_end = now_ts
            active_files += 1
        if file_end is None:
            continue
        clipped = _clip((file_start, max(file_start, file_end)), wall_start, wall_end)
        if clipped:
            active_intervals.append(clipped)
    active_intervals = _merge_intervals(active_intervals)

    paused_intervals: list[tuple[float, float]] = []
    interrupted_intervals: list[tuple[float, float]] = []
    open_kind: str | None = None
    open_start: float | None = None

    def close_open(at: float) -> None:
        nonlocal open_kind, open_start
        if open_kind is None or open_start is None:
            return
        clipped = _clip((open_start, max(open_start, at)), wall_start, wall_end)
        if clipped:
            if open_kind == "paused":
                paused_intervals.append(clipped)
            else:
                interrupted_intervals.append(clipped)
        open_kind = None
        open_start = None

    for event in load_job_events(db_path, job_id):
        event_time = _timestamp(str(event.get("occurred_at") or ""))
        if event_time is None or event_time < wall_start:
            continue
        event_type = str(event.get("event_type") or "")
        detail = event.get("detail") or {}
        if event_type == "job_finished":
            event_status = str(detail.get("status") or "")
            if event_status in _RESUMABLE_STATUSES:
                close_open(event_time)
                open_kind = event_status
                open_start = event_time
            elif event_status in _TERMINAL_STATUSES:
                close_open(event_time)
        elif event_type == "restart_interrupted":
            close_open(event_time)
            open_kind = "interrupted"
            open_start = event_time
        elif event_type in {"job_started", "job_resumed"}:
            close_open(event_time)

    if open_kind is None and status in _RESUMABLE_STATUSES:
        # Compatibility for a paused/interrupted job created before detailed events existed.
        fallback = _timestamp(job["finished_at"])
        if fallback is not None:
            open_kind = status
            open_start = fallback
    if open_kind is not None:
        close_open(wall_end)

    # These states should not overlap active file work. Subtracting active intervals makes the
    # accounting fail-safe against old or malformed event timestamps rather than over-counting.
    paused_effective = _subtract_intervals(paused_intervals, active_intervals)
    interrupted_effective = _subtract_intervals(
        interrupted_intervals,
        [*active_intervals, *paused_effective],
    )
    classified = _merge_intervals([*active_intervals, *paused_effective, *interrupted_effective])

    wall_seconds = max(0.0, wall_end - wall_start)
    active_seconds = _duration(active_intervals)
    paused_seconds = _duration(paused_effective)
    interrupted_seconds = _duration(interrupted_effective)
    idle_seconds = max(0.0, wall_seconds - _duration(classified))
    return {
        "status": status,
        "wall_seconds": round(wall_seconds, 3),
        "active_seconds": round(active_seconds, 3),
        "paused_seconds": round(paused_seconds, 3),
        "interrupted_seconds": round(interrupted_seconds, 3),
        "idle_seconds": round(idle_seconds, 3),
        # Compatibility for older UI clients during rolling upgrades.
        "paused_or_idle_seconds": round(paused_seconds + interrupted_seconds + idle_seconds, 3),
        "active_files": active_files,
    }
