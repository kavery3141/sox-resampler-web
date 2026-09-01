from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from mutagen.flac import FLAC

from . import db as dbmod


def _first(audio: FLAC, key: str) -> str | None:
    values = audio.get(key)
    if not values:
        return None
    value = str(values[0]).strip()
    return value or None


def refresh_track(
    db_path: Path,
    music_root: Path,
    path: Path,
    timezone: str,
) -> dict[str, Any]:
    """Re-probe one FLAC and immediately refresh its indexed row.

    This is intended for the successful end of a user-initiated conversion so an
    album naturally disappears from high-rate candidate views without waiting for
    the next library crawl. It only updates SQLite; it never starts conversion or
    modifies library audio.
    """
    music_root = music_root.resolve()
    path = path.resolve(strict=True)
    if music_root != path and music_root not in path.parents:
        raise ValueError(f"Track is outside music root: {path}")
    if path.suffix.lower() != ".flac":
        raise ValueError("Only FLAC tracks may be refreshed")

    audio = FLAC(path)
    info = audio.info
    st = path.stat()
    now = datetime.now(ZoneInfo(timezone)).isoformat(timespec="seconds")
    tags = {k: list(v) for k, v in audio.tags.items()} if audio.tags else {}

    with dbmod.session(db_path) as conn:
        old = conn.execute(
            "SELECT first_seen FROM tracks WHERE path=?",
            (str(path),),
        ).fetchone()
        first_seen = old["first_seen"] if old else now
        row = (
            str(path),
            path.relative_to(music_root).as_posix(),
            str(path.parent),
            path.name,
            int(st.st_size),
            int(st.st_mtime_ns),
            int(info.sample_rate),
            int(info.bits_per_sample),
            int(info.channels),
            float(info.length),
            _first(audio, "albumartist"),
            _first(audio, "album"),
            _first(audio, "releasetype"),
            _first(audio, "musicbrainz_albumid"),
            _first(audio, "artist"),
            _first(audio, "title"),
            _first(audio, "tracknumber"),
            _first(audio, "discnumber"),
            _first(audio, "replaygain_track_gain"),
            _first(audio, "replaygain_track_peak"),
            _first(audio, "replaygain_album_gain"),
            _first(audio, "replaygain_album_peak"),
            len(audio.pictures),
            first_seen,
            now,
            json.dumps(tags, separators=(",", ":")),
        )
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

    return {
        "path": str(path),
        "sample_rate": int(info.sample_rate),
        "bits_per_sample": int(info.bits_per_sample),
        "channels": int(info.channels),
        "size_bytes": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "first_seen": first_seen,
        "last_seen": now,
    }
