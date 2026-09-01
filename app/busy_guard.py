from __future__ import annotations

import errno
import fcntl
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class SourceBusyError(RuntimeError):
    pass


class SourceAccessError(RuntimeError):
    pass


@dataclass(frozen=True)
class BusyGuardState:
    supported: bool


_UNSUPPORTED = {
    errno.ENOSYS,
    errno.EOPNOTSUPP,
}
if hasattr(errno, "ENOTSUP"):
    _UNSUPPORTED.add(errno.ENOTSUP)


@contextmanager
def source_read_guard(path: Path) -> Iterator[BusyGuardState]:
    """Hold a non-blocking advisory shared lock while one source file is processed.

    This detects cooperative writers that already hold an advisory exclusive flock and prevents
    cooperative exclusive writers from entering while conversion is underway. It intentionally
    does not pretend to detect ordinary readers or applications that ignore advisory locks. On a
    filesystem that does not support flock, conversion continues with ``supported=False`` and the
    existing source-identity/revalidation safeguards remain authoritative.
    """
    try:
        handle = path.open("rb")
    except OSError as exc:
        raise SourceAccessError(f"Source unavailable before conversion: {path}: {exc}") from exc

    locked = False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            locked = True
            state = BusyGuardState(supported=True)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                raise SourceBusyError(
                    f"Source has a conflicting advisory file lock and is currently busy: {path}"
                ) from exc
            if exc.errno in _UNSUPPORTED:
                state = BusyGuardState(supported=False)
            else:
                raise
        yield state
    finally:
        if locked:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()