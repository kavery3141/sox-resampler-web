from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class _ActiveFile:
    token: str
    abort_requested: bool = False


_lock = threading.RLock()
_active: dict[str, _ActiveFile] = {}


def _key(path: Path | str) -> str:
    return str(Path(path).resolve(strict=False))


def register_active(path: Path | str) -> str:
    """Register one active converter instance and return its unguessable generation token."""
    token = uuid.uuid4().hex
    key = _key(path)
    with _lock:
        _active[key] = _ActiveFile(token=token)
    return token


def unregister_active(path: Path | str, token: str) -> None:
    key = _key(path)
    with _lock:
        current = _active.get(key)
        if current is not None and current.token == token:
            _active.pop(key, None)


def request_abort(path: Path | str) -> bool:
    """Request abort only for a converter that is active at this exact moment."""
    key = _key(path)
    with _lock:
        current = _active.get(key)
        if current is None:
            return False
        current.abort_requested = True
        return True


def abort_requested(path: Path | str, token: str) -> bool:
    key = _key(path)
    with _lock:
        current = _active.get(key)
        return bool(current is not None and current.token == token and current.abort_requested)


def active_paths() -> list[str]:
    with _lock:
        return sorted(_active)
