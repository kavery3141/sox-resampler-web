from __future__ import annotations

from pathlib import Path
from typing import Any

from mutagen.flac import FLAC


CRITICAL_TAGS = (
    "ALBUMARTIST",
    "ALBUM",
    "RELEASETYPE",
    "MUSICBRAINZ_ALBUMID",
)


def _first(audio: FLAC, key: str) -> str:
    values = audio.get(key)
    if not values:
        return ""
    return str(values[0]).strip()


def capture_source_snapshot(path: Path) -> dict[str, Any]:
    """Capture the review-time identity and conversion-critical state of one FLAC."""
    st = path.stat(follow_symlinks=False)
    audio = FLAC(path)
    return {
        "device": int(st.st_dev),
        "inode": int(st.st_ino),
        "size_bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "sample_rate": int(audio.info.sample_rate),
        "bits_per_sample": int(audio.info.bits_per_sample),
        "channels": int(audio.info.channels),
        "critical_tags": {tag: _first(audio, tag) for tag in CRITICAL_TAGS},
    }


def compare_source_snapshots(expected: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Return exact safety-relevant changes between review time and file start."""
    changes: list[str] = []
    numeric_fields = (
        ("device", "filesystem device"),
        ("inode", "inode"),
        ("size_bytes", "size"),
        ("mtime_ns", "modification time"),
        ("sample_rate", "sample rate"),
        ("bits_per_sample", "bit depth"),
        ("channels", "channel count"),
    )
    for key, label in numeric_fields:
        old = expected.get(key)
        new = current.get(key)
        try:
            same = int(old) == int(new)
        except (TypeError, ValueError):
            same = old == new
        if not same:
            changes.append(f"{label} changed ({old!r} -> {new!r})")

    expected_tags = expected.get("critical_tags")
    current_tags = current.get("critical_tags")
    if not isinstance(expected_tags, dict):
        expected_tags = {}
    if not isinstance(current_tags, dict):
        current_tags = {}
    for tag in CRITICAL_TAGS:
        old = str(expected_tags.get(tag) or "").strip()
        new = str(current_tags.get(tag) or "").strip()
        if old != new:
            changes.append(
                f"{tag} changed ({old or '<missing>'!r} -> {new or '<missing>'!r})"
            )
    return changes
