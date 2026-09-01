from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mutagen.flac import FLAC

from . import db

TEMP_SUFFIX = ".sox-resampler.tmp.flac"
HIDDEN_DIRS = {".snapshots", ".snapshot", ".trash", ".recycle", "@recycle", "$recycle.bin"}


def _journal_temp_paths(journal_root: Path) -> tuple[set[str], bool]:
    referenced: set[str] = set()
    uncertain = False
    if not journal_root.exists():
        return referenced, uncertain
    for path in journal_root.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            temp = payload.get("temp")
            if not isinstance(temp, str) or not temp:
                uncertain = True
                continue
            referenced.add(str(Path(temp).resolve(strict=False)))
        except Exception:
            # A malformed transaction journal already requires recovery attention. Do not remove
            # any unknown temp while journal ownership is uncertain.
            uncertain = True
    return referenced, uncertain


def _original_for_temp(temp: Path) -> Path | None:
    name = temp.name
    if not name.startswith(".") or not name.lower().endswith(TEMP_SUFFIX):
        return None
    original_name = name[1 : len(name) - len(TEMP_SUFFIX)]
    if not original_name.lower().endswith(".flac"):
        return None
    return temp.with_name(original_name)


def _original_matches_index(db_path: Path, original: Path) -> tuple[bool, str]:
    try:
        stat = original.stat()
        audio = FLAC(original)
    except Exception as exc:
        return False, f"cannot verify current original: {exc}"

    with db.session(db_path) as conn:
        row = conn.execute(
            """
            SELECT size_bytes,mtime_ns,sample_rate,bits_per_sample,channels
            FROM tracks WHERE path=?
            """,
            (str(original.resolve(strict=False)),),
        ).fetchone()
    if not row:
        return False, "original is not present in the local library index"

    indexed_rate = int(row["sample_rate"] or 0)
    if indexed_rate <= 48000:
        return False, "indexed source is not a high-rate source; automatic temp classification is intentionally conservative"

    checks = (
        int(row["size_bytes"] or 0) == int(stat.st_size),
        int(row["mtime_ns"] or 0) == int(stat.st_mtime_ns),
        indexed_rate == int(audio.info.sample_rate),
        int(row["bits_per_sample"] or 0) == int(audio.info.bits_per_sample),
        int(row["channels"] or 0) == int(audio.info.channels),
    )
    if not all(checks):
        return False, "current original no longer matches its indexed pre-conversion identity"
    return True, "current original matches indexed high-rate source identity"


def cleanup_orphan_temps(
    music_root: Path,
    db_path: Path,
    journal_root: Path,
    *,
    max_results: int = 200,
) -> list[dict[str, Any]]:
    """Remove only positively classified, unjournaled conversion temp files.

    Journal-owned temps are handled by transaction recovery. For an unjournaled temp, deletion is
    allowed only when the real source path still exists and matches the local index's high-rate
    source identity (size, mtime, rate, bit depth and channels). Ambiguous files are left in place
    and reported for manual attention. This function never promotes a temp into the library.
    """
    root = music_root.resolve(strict=False)
    referenced, journal_uncertain = _journal_temp_paths(journal_root)
    outcomes: list[dict[str, Any]] = []
    if not root.exists():
        return outcomes

    for walk_root, dirs, files in os.walk(root, followlinks=False):
        base = Path(walk_root)
        dirs[:] = [
            name
            for name in dirs
            if not name.startswith(".")
            and name.lower() not in HIDDEN_DIRS
            and not (base / name).is_symlink()
        ]
        for name in files:
            if not name.startswith(".") or not name.lower().endswith(TEMP_SUFFIX):
                continue
            temp = base / name
            if temp.is_symlink():
                continue
            resolved_temp = str(temp.resolve(strict=False))
            if resolved_temp in referenced:
                continue
            original = _original_for_temp(temp)
            if original is None:
                continue

            if journal_uncertain:
                outcomes.append(
                    {
                        "source": str(original),
                        "temp": str(temp),
                        "action": "manual_attention",
                        "reason": "A malformed transaction journal makes temp ownership uncertain",
                    }
                )
            elif not original.exists():
                outcomes.append(
                    {
                        "source": str(original),
                        "temp": str(temp),
                        "action": "manual_attention",
                        "reason": "Original path is missing; orphan temp was left untouched",
                    }
                )
            else:
                safe, reason = _original_matches_index(db_path, original)
                if safe:
                    try:
                        temp.unlink()
                        outcomes.append(
                            {
                                "source": str(original),
                                "temp": str(temp),
                                "action": "removed_orphan_temp",
                                "reason": reason,
                            }
                        )
                    except OSError as exc:
                        outcomes.append(
                            {
                                "source": str(original),
                                "temp": str(temp),
                                "action": "recovery_error",
                                "reason": f"Unable to remove positively identified orphan temp: {exc}",
                            }
                        )
                else:
                    outcomes.append(
                        {
                            "source": str(original),
                            "temp": str(temp),
                            "action": "manual_attention",
                            "reason": reason,
                        }
                    )
            if len(outcomes) >= max(1, int(max_results)):
                return outcomes
    return outcomes
