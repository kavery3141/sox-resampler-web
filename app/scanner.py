from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from mutagen.flac import FLAC

from . import db as dbmod


HIDDEN_DIRS = {".snapshots", ".snapshot", ".trash", ".recycle", "@recycle", "$recycle.bin"}
TEMP_SUFFIX = ".sox-resampler.tmp.flac"


@dataclass
class ScanState:
    running: bool = False
    mode: str | None = None
    files_seen: int = 0
    files_read: int = 0
    errors: int = 0
    current_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    last_error: str | None = None


class LibraryScanner:
    def __init__(self, music_root: Path, db_path: Path, timezone: str) -> None:
        self.music_root = music_root
        self.db_path = db_path
        self.tz = ZoneInfo(timezone)
        self.state = ScanState()
        self._lock = Lock()

    def _now(self) -> str:
        return datetime.now(self.tz).isoformat(timespec="seconds")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.state.__dict__.copy()

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

    def run(self, mode: str = "incremental") -> dict[str, Any]:
        with self._lock:
            if self.state.running:
                return self.snapshot()
            self.state = ScanState(running=True, mode=mode, started_at=self._now())

        dbmod.init(self.db_path)
        exact = dbmod.get_setting(self.db_path, "exclude_paths", []) or []
        globs = dbmod.get_setting(self.db_path, "exclude_globs", []) or []
        run_id: int | None = None

        try:
            with dbmod.session(self.db_path) as conn:
                cur = conn.execute(
                    "INSERT INTO scan_runs(started_at,mode,status) VALUES(?,?,?)",
                    (self.state.started_at, mode, "running"),
                )
                run_id = int(cur.lastrowid)

            seen_paths: set[str] = set()
            for root, dirs, files in os.walk(self.music_root, followlinks=False):
                root_path = Path(root)
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
                        if mode == "incremental" and old and old["size_bytes"] == st.st_size and old["mtime_ns"] == st.st_mtime_ns:
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
                        self.state.files_read += 1
                    except Exception as exc:  # one bad file must not abort a scan
                        self.state.errors += 1
                        self.state.last_error = f"{path}: {exc}"

            # Deletion detection only after a completed scan while the source is reachable.
            if self.music_root.exists():
                with dbmod.session(self.db_path) as conn:
                    rows = conn.execute("SELECT path FROM tracks").fetchall()
                    stale = [(r["path"],) for r in rows if r["path"] not in seen_paths]
                    if stale:
                        conn.executemany("DELETE FROM tracks WHERE path=?", stale)

            self.state.finished_at = self._now()
            with dbmod.session(self.db_path) as conn:
                conn.execute(
                    "UPDATE scan_runs SET finished_at=?,status='completed',files_seen=?,files_read=?,errors=?,current_path=NULL,error_text=? WHERE id=?",
                    (self.state.finished_at, self.state.files_seen, self.state.files_read, self.state.errors, self.state.last_error, run_id),
                )
        except Exception as exc:
            self.state.finished_at = self._now()
            self.state.last_error = str(exc)
            self.state.errors += 1
            if run_id is not None:
                with dbmod.session(self.db_path) as conn:
                    conn.execute(
                        "UPDATE scan_runs SET finished_at=?,status='failed',files_seen=?,files_read=?,errors=?,error_text=? WHERE id=?",
                        (self.state.finished_at, self.state.files_seen, self.state.files_read, self.state.errors, self.state.last_error, run_id),
                    )
        finally:
            self.state.current_path = None
            self.state.running = False
        return self.snapshot()
