from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileIdentity:
    inode: int
    device: int
    size: int
    mtime_ns: int


def identity(path: Path) -> FileIdentity:
    st = path.stat()
    return FileIdentity(st.st_ino, st.st_dev, st.st_size, st.st_mtime_ns)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".new")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


class ReplacementJournal:
    """Durable per-file journal for replace-in-place recovery.

    The journal does not initiate conversions. It only records a conversion that the user
    already started, allowing startup recovery to restore or finish that interrupted file
    transaction deterministically.
    """

    def __init__(self, root: Path, source: Path) -> None:
        digest = hashlib.sha256(os.fsencode(str(source))).hexdigest()
        self.path = root / f"{digest}.json"
        self.payload: dict[str, Any] = {}

    def prepare(
        self,
        source: Path,
        temp: Path,
        original_identity: FileIdentity,
        new_sha256: str,
    ) -> None:
        self.payload = {
            "version": 1,
            "state": "prepared",
            "source": str(source),
            "temp": str(temp),
            "original_identity": asdict(original_identity),
            "new_sha256": new_sha256,
        }
        _atomic_json(self.path, self.payload)

    def mark_exchanged(self) -> None:
        self.payload["state"] = "exchanged"
        _atomic_json(self.path, self.payload)

    def mark_verified(self) -> None:
        self.payload["state"] = "verified"
        _atomic_json(self.path, self.payload)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            return
        _fsync_dir(self.path.parent)


def _matches_identity(path: Path, raw: dict[str, Any]) -> bool:
    if not path.exists():
        return False
    got = identity(path)
    return (
        got.inode == int(raw["inode"])
        and got.device == int(raw["device"])
        and got.size == int(raw["size"])
        and got.mtime_ns == int(raw["mtime_ns"])
    )


def recover_journals(root: Path, rename_exchange) -> list[dict[str, str]]:
    """Recover interrupted replacement transactions without starting new conversions.

    prepared: exchange was not durably recorded; remove only a generated temp whose checksum
    matches the journal, leaving the original untouched.
    exchanged: restore the old original by exchanging the paths back, then remove generated temp.
    verified: replacement had already passed final checksum; remove only the positively identified
    old original left at the temp path.
    Ambiguous states are never modified and are reported for manual attention.
    """
    root.mkdir(parents=True, exist_ok=True)
    outcomes: list[dict[str, str]] = []
    for journal_path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(journal_path.read_text(encoding="utf-8"))
            source = Path(payload["source"])
            temp = Path(payload["temp"])
            old_id = payload["original_identity"]
            new_sha = str(payload["new_sha256"])
            state = str(payload["state"])

            source_is_old = _matches_identity(source, old_id)
            temp_is_old = _matches_identity(temp, old_id)
            source_is_new = source.exists() and sha256(source) == new_sha
            temp_is_new = temp.exists() and sha256(temp) == new_sha

            if state == "prepared":
                if source_is_old and temp_is_new:
                    temp.unlink()
                    _fsync_dir(temp.parent)
                    journal_path.unlink()
                    _fsync_dir(journal_path.parent)
                    outcomes.append({"source": str(source), "action": "discarded_uncommitted_temp"})
                elif source_is_old and not temp.exists():
                    journal_path.unlink()
                    _fsync_dir(journal_path.parent)
                    outcomes.append({"source": str(source), "action": "cleared_prepared_journal"})
                else:
                    outcomes.append({"source": str(source), "action": "manual_attention"})
                continue

            if state == "exchanged":
                if source_is_new and temp_is_old:
                    rename_exchange(source, temp)
                    # Old original is back at source; generated output is now temp.
                    if not _matches_identity(source, old_id) or sha256(temp) != new_sha:
                        raise RuntimeError("post-rollback identity verification failed")
                    temp.unlink()
                    _fsync_dir(temp.parent)
                    journal_path.unlink()
                    _fsync_dir(journal_path.parent)
                    outcomes.append({"source": str(source), "action": "rolled_back_interrupted_exchange"})
                else:
                    outcomes.append({"source": str(source), "action": "manual_attention"})
                continue

            if state == "verified":
                if source_is_new and temp_is_old:
                    temp.unlink()
                    _fsync_dir(temp.parent)
                    journal_path.unlink()
                    _fsync_dir(journal_path.parent)
                    outcomes.append({"source": str(source), "action": "finished_verified_cleanup"})
                elif source_is_new and not temp.exists():
                    journal_path.unlink()
                    _fsync_dir(journal_path.parent)
                    outcomes.append({"source": str(source), "action": "cleared_verified_journal"})
                else:
                    outcomes.append({"source": str(source), "action": "manual_attention"})
                continue

            outcomes.append({"source": str(source), "action": "manual_attention"})
        except Exception as exc:
            outcomes.append({"source": str(journal_path), "action": f"recovery_error: {exc}"})
    return outcomes
