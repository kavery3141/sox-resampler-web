from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 3


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=NORMAL")
    return db


@contextmanager
def session(path: Path) -> Iterator[sqlite3.Connection]:
    db = connect(path)
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init(path: Path) -> None:
    with session(path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tracks (
                path TEXT PRIMARY KEY,
                rel_path TEXT NOT NULL,
                folder TEXT NOT NULL,
                filename TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                sample_rate INTEGER,
                bits_per_sample INTEGER,
                channels INTEGER,
                duration REAL,
                albumartist TEXT,
                album TEXT,
                releasetype TEXT,
                musicbrainz_albumid TEXT,
                artist TEXT,
                title TEXT,
                tracknumber TEXT,
                discnumber TEXT,
                replaygain_track_gain TEXT,
                replaygain_track_peak TEXT,
                replaygain_album_gain TEXT,
                replaygain_album_peak TEXT,
                picture_count INTEGER NOT NULL DEFAULT 0,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                tag_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(albumartist, album);
            CREATE INDEX IF NOT EXISTS idx_tracks_rate ON tracks(sample_rate);
            CREATE INDEX IF NOT EXISTS idx_tracks_last_seen ON tracks(last_seen);

            CREATE TABLE IF NOT EXISTS scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                files_seen INTEGER NOT NULL DEFAULT 0,
                files_read INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                current_path TEXT,
                error_text TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS custom_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                profile_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        db.execute(
            "INSERT INTO app_meta(key,value) VALUES('schema_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )


def get_setting(path: Path, key: str, default: Any = None) -> Any:
    with session(path) as db:
        row = db.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value_json"])
    except json.JSONDecodeError:
        return default


def set_setting(path: Path, key: str, value: Any) -> None:
    payload = json.dumps(value, separators=(",", ":"))
    with session(path) as db:
        db.execute(
            "INSERT INTO settings(key,value_json) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (key, payload),
        )


def latest_scan(path: Path) -> dict[str, Any] | None:
    with session(path) as db:
        row = db.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def library_summary(path: Path) -> dict[str, int]:
    with session(path) as db:
        tracks = db.execute("SELECT COUNT(*) c FROM tracks").fetchone()["c"]
        albums = db.execute(
            "SELECT COUNT(*) c FROM (SELECT albumartist,album FROM tracks GROUP BY albumartist,album)"
        ).fetchone()["c"]
        hi = db.execute("SELECT COUNT(*) c FROM tracks WHERE sample_rate IN (96000,192000)").fetchone()["c"]
    return {"tracks": tracks, "albums": albums, "high_rate_tracks": hi}


def candidate_albums(path: Path, rates: list[int], above: int | None = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if rates:
        clauses.append("sample_rate IN (%s)" % ",".join("?" for _ in rates))
        args.extend(rates)
    if above is not None:
        clauses.append("sample_rate > ?")
        args.append(above)
    where = " OR ".join(clauses) if clauses else "1=1"

    sql = f"""
    SELECT
      COALESCE(albumartist,'') albumartist,
      COALESCE(album,'') album,
      MIN(folder) folder,
      COUNT(*) total_tracks,
      SUM(CASE WHEN ({where}) THEN 1 ELSE 0 END) matching_tracks,
      SUM(CASE WHEN NOT ({where}) THEN 1 ELSE 0 END) untouched_tracks,
      SUM(CASE WHEN ({where}) THEN size_bytes ELSE 0 END) matching_bytes,
      GROUP_CONCAT(DISTINCT CASE WHEN ({where}) THEN sample_rate END) source_rates,
      GROUP_CONCAT(DISTINCT CASE WHEN ({where}) THEN bits_per_sample END) bit_depths,
      GROUP_CONCAT(DISTINCT channels) channels,
      GROUP_CONCAT(DISTINCT releasetype) releasetypes,
      GROUP_CONCAT(DISTINCT musicbrainz_albumid) mbids,
      MIN(first_seen) first_seen,
      SUM(CASE WHEN replaygain_track_gain IS NULL OR replaygain_track_peak IS NULL
                OR replaygain_album_gain IS NULL OR replaygain_album_peak IS NULL THEN 1 ELSE 0 END) replaygain_incomplete,
      SUM(CASE WHEN channels > 2 THEN 1 ELSE 0 END) multichannel_tracks,
      SUM(CASE WHEN albumartist IS NULL OR TRIM(albumartist)='' THEN 1 ELSE 0 END) missing_albumartist,
      SUM(CASE WHEN album IS NULL OR TRIM(album)='' THEN 1 ELSE 0 END) missing_album,
      SUM(CASE WHEN releasetype IS NULL OR TRIM(releasetype)='' THEN 1 ELSE 0 END) missing_releasetype,
      SUM(CASE WHEN musicbrainz_albumid IS NULL OR TRIM(musicbrainz_albumid)='' THEN 1 ELSE 0 END) missing_mbid,
      COUNT(DISTINCT NULLIF(TRIM(albumartist),'')) albumartist_values,
      COUNT(DISTINCT NULLIF(TRIM(album),'')) album_values,
      COUNT(DISTINCT NULLIF(TRIM(releasetype),'')) releasetype_values,
      COUNT(DISTINCT NULLIF(TRIM(musicbrainz_albumid),'')) mbid_values
    FROM tracks
    GROUP BY albumartist, album
    HAVING matching_tracks > 0
    ORDER BY albumartist COLLATE NOCASE, album COLLATE NOCASE
    """

    # the rate predicate appears four times in the SELECT expression
    qargs = args * 4
    with session(path) as db:
        rows = [dict(r) for r in db.execute(sql, qargs).fetchall()]

    for row in rows:
        blockers: list[str] = []
        warnings: list[str] = []
        if row["missing_albumartist"] or row["albumartist_values"] != 1:
            blockers.append("ALBUMARTIST missing or inconsistent")
        if row["missing_album"] or row["album_values"] != 1:
            blockers.append("ALBUM missing or inconsistent")
        if row["missing_releasetype"] or row["releasetype_values"] != 1:
            blockers.append("RELEASETYPE missing or inconsistent")
        if row["missing_mbid"] or row["mbid_values"] != 1:
            blockers.append("MUSICBRAINZ_ALBUMID missing or inconsistent")
        if row["multichannel_tracks"]:
            blockers.append("Multichannel FLAC requires review")
        if row["replaygain_incomplete"]:
            warnings.append("ReplayGain incomplete")
        row["blockers"] = blockers
        row["warnings"] = warnings
        row["selectable"] = not blockers
        row["source_rates"] = sorted(int(x) for x in (row["source_rates"] or "").split(",") if x)
        row["bit_depths"] = sorted(int(x) for x in (row["bit_depths"] or "").split(",") if x)
    return rows
