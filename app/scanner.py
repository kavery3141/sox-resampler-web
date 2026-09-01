from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo

from mutagen.flac import FLAC

from . import db as dbmod


HIDDEN_DIRS = {".snapshots", ".snapshot", ".trash", ".recycle", "@recycle", "$recycle.bin"}
TEMP_SUFFIX = ".sox-resampler.tmp.flac"
FULL_SCAN_MODES = {"full", "full-resume"}


class ScanPaused(RuntimeError):
    pass


@dataclass
class ScanState:
    running: bool = False
    status: str = "idle"
    mode: str | None = None
    run_id: int | None = None
    pause_requested: bool = False
    folders_scanned: int = 0
    files_seen: int = 0
    files_read: int = 0
    errors: int = 0
    current_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    last_error: str | None = None


def recover_interrupted_scan_runs(db_path: Path, timezone: str) -> int:
    """Mark scans that died mid-run as interrupted without auto-resuming them."""
    dbmod.init(db_path)
    now = datetime.now(ZoneInfo(timezone)).isoformat(timespec="seconds")
    with dbmod.session(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE scan_runs
            SET status='interrupted',finished_at=COALESCE(finished_at,?),
                error_text=COALESCE(error_text,'App or NAS restart interrupted this scan')
            WHERE status IN ('running','pausing')
            """,
            (now,),
        )
    return int(cur.rowcount or 0)


class LibraryScanner:
    def __init__(self, music_root: Path, db_path: Path, timezone: str) -> None:
        self.music_root = music_root
        self.db_path = db_path
        self.timezone = timezone
        self.tz = ZoneInfo(timezone)
        self.state = ScanState()
        self._lock = RLock()
        self._pause_requested = False
        self._run_id: int | None = None
        recover_interrupted_scan_runs(self.db_path, self.timezone)

    def _now(self) -> str:
        return datetime.now(self.tz).isoformat(timespec="seconds")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.state.__dict__.copy()

    def _set_state(self, **values: Any) -> None:
        with self._lock:
            for key, value in values.items():
                setattr(self.state, key, value)

    def _excluded(self, path: Path, exact: list[str], globs: list[str]) -> bool:
        text = str(path)
        if text in exact:
            return True
        rel = path.relative_to(self.music_root).as_posix() if path != self.music_root else ""
        return any(fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(text, pattern) for pattern in globs)

    @staticmethod
    def _first(tags: FLAC, key: str) -> str | None:
        vals = tags.get(key)
        if not vals:
            return None
        value = str(vals[0]).strip()
        return value or None

    def request_pause(self) -> bool:
        """Ask an active full scan to stop cleanly after its current small unit of work."""
        with self._lock:
            if not self.state.running or self.state.mode not in FULL_SCAN_MODES:
                return False
            if self._pause_requested:
                return True
            self._pause_requested = True
            self.state.pause_requested = True
            self.state.status = "pausing"
            run_id = self._run_id
        if run_id is not None:
            with dbmod.session(self.db_path) as conn:
                conn.execute("UPDATE scan_runs SET status='pausing' WHERE id=?", (run_id,))
        return True

    def _pause_checkpoint(self) -> None:
        with self._lock:
            requested = self._pause_requested
        if requested:
            raise ScanPaused("Full scan paused by user")

    def resumable(self) -> dict[str, Any] | None:
        """Return the latest paused/interrupted full scan that can be resumed manually."""
        with dbmod.session(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM scan_runs
                WHERE status IN ('paused','interrupted') AND mode IN ('full','full-resume')
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def run(self, mode: str = "incremental") -> dict[str, Any]:
        if mode not in {"incremental", "full", "full-resume"}:
            raise ValueError(f"Unsupported scan mode: {mode}")
        with self._lock:
            if self.state.running:
                return self.state.__dict__.copy()
            self._pause_requested = False
            self.state = ScanState(
                running=True,
                status="running",
                mode=mode,
                started_at=self._now(),
            )

        dbmod.init(self.db_path)
        exact = dbmod.get_setting(self.db_path, "exclude_paths", []) or []
        globs = dbmod.get_setting(self.db_path, "exclude_globs", []) or []
        run_id: int | None = None
        traversal_safe = True

        try:
            with dbmod.session(self.db_path) as conn:
                cur = conn.execute(
                    "INSERT INTO scan_runs(started_at,mode,status) VALUES(?,?,?)",
                    (self.state.started_at, mode, "running"),
                )
                run_id = int(cur.lastrowid)
            with self._lock:
                self._run_id = run_id
                self.state.run_id = run_id

            if not self.music_root.exists() or not self.music_root.is_dir():
                raise RuntimeError(f"Music root is unavailable: {self.music_root}")

            seen_paths: set[str] = set()

            def walk_error(exc: OSError) -> None:
                nonlocal traversal_safe
                traversal_safe = False
                with self._lock:
                    self.state.errors += 1
                    self.state.last_error = f"Library traversal error: {exc}"

            for root, dirs, files in os.walk(
                self.music_root,
                followlinks=False,
                onerror=walk_error,
            ):
                self._pause_checkpoint()
                root_path = Path(root)
                with self._lock:
                    self.state.folders_scanned += 1
                    self.state.current_path = str(root_path)

                dirs[:] = [
                    d for d in dirs
                    if not d.startswith(".")
                    and d.lower() not in HIDDEN_DIRS
                    and not (root_path / d).is_symlink()
                    and not self._excluded(root_path / d, exact, globs)
                ]
                if self._excluded(root_path, exact, globs):
                    dirs[:] = []
                    continue

                for filename in files:
                    self._pause_checkpoint()
                    lower_name = filename.lower()
                    # Hidden files and our own hidden conversion temp files are never library
                    # content. This also keeps interrupted transaction files out of reports.
                    if filename.startswith(".") or lower_name.endswith(TEMP_SUFFIX):
                        continue
                    if not lower_name.endswith(".flac"):
                        continue
                    path = root_path / filename
                    if path.is_symlink() or self._excluded(path, exact, globs):
                        continue
                    with self._lock:
                        self.state.files_seen += 1
                        self.state.current_path = str(path)
                    seen_paths.add(str(path))
                    try:
                        st = path.stat()
                        with dbmod.session(self.db_path) as conn:
                            old = conn.execute(
                                "SELECT size_bytes,mtime_ns,first_seen FROM tracks WHERE path=?",
                                (str(path),),
                            ).fetchone()
                        skip_unchanged = mode in {"incremental", "full-resume"}
                        if skip_unchanged and old and old["size_bytes"] == st.st_size and old["mtime_ns"] == st.st_mtime_ns:
                            with dbmod.session(self.db_path) as conn:
                                conn.execute("UPDATE tracks SET last_seen=? WHERE path=?", (self._now(), str(path)))
                            continue

                        audio = FLAC(path)
                        info = audio.info
                        now = self._now()
                        first_seen = old["first_seen"] if old else now
                        tag_json = {k: list(v) for k, v in audio.tags.items()} if audio.tags else {}
                        row = (
                            str(path), path.relative_to(self.music_root).as_posix(), str(root_path), filename,
                            st.st_size, st.st_mtime_ns, int(info.sample_rate), int(info.bits_per_sample), int(info.channels),
                            float(info.length), self._first(audio, "albumartist"), self._first(audio, "album"),
                            self._first(audio, "releasetype"), self._first(audio, "musicbrainz_albumid"),
                            self._first(audio, "artist"), self._first(audio, "title"), self._first(audio, "tracknumber"),
                            self._first(audio, "discnumber"), self._first(audio, "replaygain_track_gain"),
                            self._first(audio, "replaygain_track_peak"), self._first(audio, "replaygain_album_gain"),
                            self._first(audio, "replaygain_album_peak"), len(audio.pictures), first_seen, now,
                            __import__("json").dumps(tag_json, separators=(",", ":")),
                        )
                        with dbmod.session(self.db_path) as conn:
                            conn.execute(
                                """
                                INSERT INTO tracks(
                                  path,rel_path,folder,filename,size_bytes,mtime_ns,sample_rate,bits_per_sample,channels,duration,
                                  albumartist,album,releasetype,musicbrainz_albumid,artist,title,tracknumber,discnumber,
                                  replaygain_track_gain,replaygain_track_peak,replaygain_album_gain,replaygain_album_peak,
                                  picture_count,first_seen,last_seen,tag_json
                                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                ON CONFLICT(path) DO UPDATE SET
                                  rel_path=excluded.rel_path,folder=excluded.folder,filename=excluded.filename,
                                  size_bytes=excluded.size_bytes,mtime_ns=excluded.mtime_ns,sample_rate=excluded.sample_rate,
                                  bits_per_sample=excluded.bits_per_sample,channels=excluded.channels,duration=excluded.duration,
                                  albumartist=excluded.albumartist,album=excluded.album,releasetype=excluded.releasetype,
                                  musicbrainz_albumid=excluded.musicbrainz_albumid,artist=excluded.artist,title=excluded.title,
                                  tracknumber=excluded.tracknumber,discnumber=excluded.discnumber,
                                  replaygain_track_gain=excluded.replaygain_track_gain,replaygain_track_peak=excluded.replaygain_track_peak,
                                  replaygain_album_gain=excluded.replaygain_album_gain,replaygain_album_peak=excluded.replaygain_album_peak,
                                  picture_count=excluded.picture_count,last_seen=excluded.last_seen,tag_json=excluded.tag_json
                                """,
                                row,
                            )
                        with self._lock:
                            self.state.files_read += 1
                    except Exception as exc:  # one bad file must not abort a scan
                        with self._lock:
                            self.state.errors += 1
                            self.state.last_error = f"{path}: {exc}"

            self._pause_checkpoint()
            # Deletion detection happens only after a complete, traversal-safe pass while the
            # source is reachable. A transient scandir/storage error must never look like mass
            # deletion and purge local index state.
            if self.music_root.exists() and traversal_safe:
                with dbmod.session(self.db_path) as conn:
                    rows = conn.execute("SELECT path FROM tracks").fetchall()
                    stale = [(r["path"],) for r in rows if r["path"] not in seen_paths]
                    if stale:
                        conn.executemany("DELETE FROM tracks WHERE path=?", stale)
            elif not traversal_safe:
                with self._lock:
                    note = "Traversal errors occurred; stale index entries were preserved"
                    self.state.last_error = f"{self.state.last_error}; {note}" if self.state.last_error else note

            finished = self._now()
            with self._lock:
                self.state.finished_at = finished
                self.state.status = "completed"
            with dbmod.session(self.db_path) as conn:
                conn.execute(
                    "UPDATE scan_runs SET finished_at=?,status='completed',files_seen=?,files_read=?,errors=?,current_path=NULL,error_text=? WHERE id=?",
                    (finished, self.state.files_seen, self.state.files_read, self.state.errors, self.state.last_error, run_id),
                )
        except ScanPaused as exc:
            finished = self._now()
            with self._lock:
                self.state.finished_at = finished
                self.state.status = "paused"
                self.state.last_error = str(exc)
            if run_id is not None:
                with dbmod.session(self.db_path) as conn:
                    conn.execute(
                        "UPDATE scan_runs SET finished_at=?,status='paused',files_seen=?,files_read=?,errors=?,current_path=?,error_text=? WHERE id=?",
                        (
                            finished,
                            self.state.files_seen,
                            self.state.files_read,
                            self.state.errors,
                            self.state.current_path,
                            str(exc),
                            run_id,
                        ),
                    )
        except Exception as exc:
            finished = self._now()
            with self._lock:
                self.state.finished_at = finished
                self.state.status = "failed"
                self.state.last_error = str(exc)
                self.state.errors += 1
            if run_id is not None:
                with dbmod.session(self.db_path) as conn:
                    conn.execute(
                        "UPDATE scan_runs SET finished_at=?,status='failed',files_seen=?,files_read=?,errors=?,error_text=? WHERE id=?",
                        (finished, self.state.files_seen, self.state.files_read, self.state.errors, self.state.last_error, run_id),
                    )
        finally:
            with self._lock:
                self.state.current_path = None
                self.state.running = False
                self.state.pause_requested = False
                self._pause_requested = False
                self._run_id = None
        return self.snapshot()
