from __future__ import annotations

import json
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import db
from .busy_guard import SourceBusyError, source_read_guard
from .converter import convert_file
from .index_update import refresh_track
from .job_events import load_job_events, record_job_event
from .profiles import ResampleProfile, get_profile, profile_from_dict
from .resource_control import configured_cpu_limit
from .replaygain import ReplayGainError, apply_replaygain_transaction, scan_album
from .source_snapshot import capture_source_snapshot, compare_source_snapshots
from .storage_health import zfs_pool_health


class JobError(RuntimeError):
    pass


DEFAULT_RESERVE_BYTES = 10 * 1024**3


def ensure_tables(db_path: Path) -> None:
    with db.session(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversion_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                status TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                profile_json TEXT,
                workers INTEGER NOT NULL,
                source_filter_json TEXT NOT NULL,
                operational_json TEXT NOT NULL DEFAULT '{}',
                album_order_json TEXT NOT NULL,
                pause_requested INTEGER NOT NULL DEFAULT 0,
                stop_after_album INTEGER NOT NULL DEFAULT 0,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                error_text TEXT
            );

            CREATE TABLE IF NOT EXISTS conversion_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES conversion_jobs(id) ON DELETE CASCADE,
                album_index INTEGER NOT NULL,
                file_index INTEGER NOT NULL,
                albumartist TEXT NOT NULL,
                album TEXT NOT NULL,
                path TEXT NOT NULL,
                source_bytes INTEGER NOT NULL DEFAULT 0,
                source_snapshot_json TEXT,
                status TEXT NOT NULL,
                defer_count INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                finished_at TEXT,
                error_text TEXT,
                source_sha256 TEXT,
                temp_sha256 TEXT,
                final_sha256 TEXT,
                result_json TEXT,
                UNIQUE(job_id, path)
            );
            CREATE INDEX IF NOT EXISTS idx_conversion_files_job_status
              ON conversion_files(job_id,status,album_index,file_index);
            """
        )
        job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(conversion_jobs)").fetchall()}
        if "profile_json" not in job_columns:
            conn.execute("ALTER TABLE conversion_jobs ADD COLUMN profile_json TEXT")
        if "operational_json" not in job_columns:
            conn.execute("ALTER TABLE conversion_jobs ADD COLUMN operational_json TEXT NOT NULL DEFAULT '{}'")
        file_columns = {row["name"] for row in conn.execute("PRAGMA table_info(conversion_files)").fetchall()}
        if "defer_count" not in file_columns:
            conn.execute("ALTER TABLE conversion_files ADD COLUMN defer_count INTEGER NOT NULL DEFAULT 0")
        if "source_sha256" not in file_columns:
            conn.execute("ALTER TABLE conversion_files ADD COLUMN source_sha256 TEXT")
        if "source_snapshot_json" not in file_columns:
            conn.execute("ALTER TABLE conversion_files ADD COLUMN source_snapshot_json TEXT")


def recover_interrupted(db_path: Path, timezone: str) -> None:
    ensure_tables(db_path)
    now = datetime.now(ZoneInfo(timezone)).isoformat(timespec="seconds")
    interrupted: list[tuple[int, str]] = []
    with db.session(db_path) as conn:
        interrupted = [
            (int(row["id"]), str(row["status"]))
            for row in conn.execute(
                "SELECT id,status FROM conversion_jobs WHERE status IN ('running','pausing','stopping','cancelling')"
            ).fetchall()
        ]
        # If the container died while doing the one allowed end-of-batch busy retry, restore the
        # file to deferred rather than pending so restart cannot accidentally grant extra retries.
        conn.execute(
            """
            UPDATE conversion_files
            SET status=CASE WHEN defer_count>0 THEN 'deferred' ELSE 'pending' END,
                started_at=NULL
            WHERE status='running'
            """
        )
        conn.execute(
            "UPDATE conversion_jobs SET status='interrupted', finished_at=?, "
            "error_text=COALESCE(error_text,'Container or NAS restart interrupted this job') "
            "WHERE status IN ('running','pausing','stopping','cancelling')",
            (now,),
        )
    for job_id, previous_status in interrupted:
        record_job_event(
            db_path,
            job_id,
            now,
            "restart_interrupted",
            {"previous_status": previous_status, "reason": "Container or NAS restart"},
        )


class ConversionJobManager:
    def __init__(self, db_path: Path, music_root: Path, timezone: str) -> None:
        self.db_path = db_path
        self.music_root = music_root.resolve()
        self.timezone = timezone
        self.tz = ZoneInfo(timezone)
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._active_job_id: int | None = None
        ensure_tables(db_path)
        recover_interrupted(db_path, timezone)

    def _now(self) -> str:
        return datetime.now(self.tz).isoformat(timespec="seconds")

    def _event(self, job_id: int, event_type: str, detail: dict[str, Any] | None = None) -> None:
        record_job_event(self.db_path, job_id, self._now(), event_type, detail)

    def is_running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def active_job_id(self) -> int | None:
        with self._lock:
            return self._active_job_id if self.is_running() else None

    def _runtime_gate(self, required_temp_bytes: int) -> str | None:
        """Return a reason to pause before starting more file work, or None when safe."""
        zfs = zfs_pool_health()
        if not zfs["ok"]:
            return f"{zfs['reason']}; conversion paused before the next file"
        if bool(db.get_setting(self.db_path, "read_only_mode", False)):
            return "Read-only Scan Mode was enabled; conversion paused before the next file"
        if not self.music_root.exists():
            return "Music dataset is unavailable; conversion paused before the next file"
        if not os.access(self.music_root, os.R_OK | os.W_OK):
            return "Music dataset is not readable/writable; conversion paused before the next file"
        try:
            free_bytes = shutil.disk_usage(self.music_root).free
        except OSError as exc:
            return f"Unable to verify free space ({exc}); conversion paused before the next file"
        reserve = int(db.get_setting(self.db_path, "free_space_reserve_bytes", DEFAULT_RESERVE_BYTES))
        if free_bytes < reserve + max(0, int(required_temp_bytes)):
            return (
                "Free space fell below the configured reserve plus estimated temp requirement; "
                "conversion paused before the next file"
            )
        return None

    def create_job(
        self,
        review: dict[str, Any],
        profile_id: str,
        workers: int,
        source_filter: dict[str, Any],
        operational: dict[str, Any] | None = None,
    ) -> int:
        if workers not in (1, 2):
            raise JobError("Workers must be 1 or 2")
        if review.get("blockers") or not review.get("can_start"):
            raise JobError("Batch review contains blockers")
        profile_payload = review.get("profile")
        if not isinstance(profile_payload, dict):
            raise JobError("Batch review is missing the resolved DSP profile")
        try:
            resolved_profile = profile_from_dict(profile_payload)
        except ValueError as exc:
            raise JobError(f"Batch review contains an invalid DSP profile: {exc}") from exc
        album_order = [
            {"albumartist": a["albumartist"], "album": a["album"], "folder": a["folder"]}
            for a in review["albums"]
        ]
        operational_payload = {
            "source_pre_hash": bool((operational or {}).get("source_pre_hash", False)),
        }
        created_at = self._now()
        with db.session(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO conversion_jobs(
                  created_at,status,profile_id,profile_json,workers,source_filter_json,operational_json,album_order_json
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    created_at,
                    "queued",
                    profile_id,
                    json.dumps(resolved_profile.to_dict(), separators=(",", ":"), sort_keys=True),
                    workers,
                    json.dumps(source_filter, separators=(",", ":")),
                    json.dumps(operational_payload, separators=(",", ":"), sort_keys=True),
                    json.dumps(album_order, separators=(",", ":")),
                ),
            )
            job_id = int(cur.lastrowid)
            for album_index, album in enumerate(review["albums"]):
                for file_index, track in enumerate(album["tracks"]):
                    path = Path(track["path"]).resolve()
                    if self.music_root not in path.parents:
                        raise JobError(f"Track is outside music root: {path}")
                    source_snapshot = track.get("source_snapshot")
                    source_snapshot_json = (
                        json.dumps(source_snapshot, separators=(",", ":"), sort_keys=True)
                        if isinstance(source_snapshot, dict)
                        else None
                    )
                    conn.execute(
                        """
                        INSERT INTO conversion_files(
                          job_id,album_index,file_index,albumartist,album,path,source_bytes,source_snapshot_json,status
                        ) VALUES(?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            job_id, album_index, file_index, album["albumartist"], album["album"],
                            str(path), int(track["source_bytes"]), source_snapshot_json, "pending",
                        ),
                    )
        record_job_event(
            self.db_path,
            job_id,
            created_at,
            "job_created",
            {
                "workers": workers,
                "profile_id": profile_id,
                "albums": len(album_order),
                "source_pre_hash": operational_payload["source_pre_hash"],
            },
        )
        return job_id

    def start(self, job_id: int) -> None:
        with self._lock:
            if self.is_running():
                raise JobError(f"Conversion job {self._active_job_id} is already running")
            gate = self._runtime_gate(0)
            if gate:
                raise JobError(gate)
            started_at = self._now()
            previous_status = ""
            workers = 1
            with db.session(self.db_path) as conn:
                job = conn.execute("SELECT * FROM conversion_jobs WHERE id=?", (job_id,)).fetchone()
                if not job:
                    raise JobError("Job not found")
                if job["status"] not in ("queued", "paused", "interrupted"):
                    raise JobError(f"Job cannot start from status {job['status']}")
                previous_status = str(job["status"])
                workers = int(job["workers"])
                conn.execute(
                    "UPDATE conversion_jobs SET status='running',started_at=COALESCE(started_at,?),"
                    "finished_at=NULL,pause_requested=0,stop_after_album=0,cancel_requested=0,error_text=NULL WHERE id=?",
                    (started_at, job_id),
                )
            record_job_event(
                self.db_path,
                job_id,
                started_at,
                "job_started" if previous_status == "queued" else "job_resumed",
                {"previous_status": previous_status, "workers": workers},
            )
            self._active_job_id = job_id
            self._thread = threading.Thread(
                target=self._run_job,
                args=(job_id,),
                daemon=True,
                name=f"convert-{job_id}",
            )
            self._thread.start()

    def _controls(self, job_id: int) -> dict[str, bool]:
        with db.session(self.db_path) as conn:
            row = conn.execute(
                "SELECT pause_requested,stop_after_album,cancel_requested FROM conversion_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        if not row:
            return {"pause": False, "stop_album": False, "cancel": True}
        return {
            "pause": bool(row["pause_requested"]),
            "stop_album": bool(row["stop_after_album"]),
            "cancel": bool(row["cancel_requested"]),
        }

    def _record_file_failure(self, file_id: int, error: str) -> dict[str, Any]:
        finished = self._now()
        payload = {"status": "failed", "error": error}
        with db.session(self.db_path) as conn:
            conn.execute(
                """
                UPDATE conversion_files
                SET status='failed',finished_at=?,error_text=?,result_json=?
                WHERE id=?
                """,
                (finished, error, json.dumps(payload, separators=(",", ":")), file_id),
            )
        return payload

    def _record_file_deferred(self, job_id: int, file_id: int, path: str, error: str) -> dict[str, Any]:
        finished = self._now()
        payload = {"status": "deferred", "error": error, "retry": "end-of-batch-once"}
        with db.session(self.db_path) as conn:
            conn.execute(
                """
                UPDATE conversion_files
                SET status='deferred',defer_count=defer_count+1,started_at=NULL,finished_at=?,
                    error_text=?,result_json=?
                WHERE id=?
                """,
                (finished, error, json.dumps(payload, separators=(",", ":")), file_id),
            )
        record_job_event(
            self.db_path,
            job_id,
            finished,
            "file_deferred_busy",
            {"file_id": file_id, "path": path, "retry": "end-of-batch-once"},
        )
        return payload

    def _run_file(
        self,
        job_id: int,
        file_id: int,
        path: str,
        profile: ResampleProfile,
        expected_bytes: int,
        source_pre_hash: bool = False,
    ) -> dict[str, Any]:
        source = Path(path)
        with db.session(self.db_path) as conn:
            row = conn.execute(
                "SELECT defer_count,source_snapshot_json FROM conversion_files WHERE id=?",
                (file_id,),
            ).fetchone()
        if not row:
            return self._record_file_failure(file_id, "Conversion file record disappeared")
        prior_defers = int(row["defer_count"] or 0)

        try:
            expected_snapshot: dict[str, Any] | None = None
            raw_snapshot = row["source_snapshot_json"]
            if raw_snapshot:
                try:
                    parsed_snapshot = json.loads(raw_snapshot)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise JobError("Stored source identity snapshot is invalid; fresh review required") from exc
                if not isinstance(parsed_snapshot, dict):
                    raise JobError("Stored source identity snapshot is invalid; fresh review required")
                expected_snapshot = parsed_snapshot

            with source_read_guard(source) as guard:
                if expected_snapshot is not None:
                    current_snapshot = capture_source_snapshot(source)
                    changes = compare_source_snapshots(expected_snapshot, current_snapshot)
                    if changes:
                        self._event(
                            job_id,
                            "source_revalidation_failed",
                            {"file_id": file_id, "path": str(source), "changes": changes},
                        )
                        raise JobError(
                            "Source changed after batch review; original left untouched; "
                            "rescan/review required: " + "; ".join(changes)
                        )

                started = self._now()
                with db.session(self.db_path) as conn:
                    conn.execute(
                        "UPDATE conversion_files SET status='running',started_at=?,finished_at=NULL,error_text=NULL WHERE id=?",
                        (started, file_id),
                    )

                try:
                    current_size = source.stat().st_size
                except OSError as exc:
                    raise JobError(f"Source unavailable before conversion: {source}: {exc}") from exc
                if current_size != int(expected_bytes):
                    raise JobError(
                        f"Source size changed after batch review ({expected_bytes} -> {current_size}); "
                        f"rescan/review required: {source}"
                    )

                cpu_limit_percent = configured_cpu_limit(self.db_path)
                result = convert_file(
                    source,
                    profile,
                    cpu_limit_percent=cpu_limit_percent,
                    source_pre_hash=source_pre_hash,
                )
                payload = asdict(result)
                payload["cpu_limit_percent"] = cpu_limit_percent
                payload["source_pre_hash"] = bool(source_pre_hash)
                payload["advisory_busy_guard_supported"] = bool(guard.supported)
                finished = self._now()

                if result.status == "completed":
                    try:
                        payload["index_refresh"] = refresh_track(
                            self.db_path,
                            self.music_root,
                            source,
                            self.timezone,
                        )
                        payload["index_refresh_error"] = None
                    except Exception as exc:
                        # The audio conversion is already safely committed at this point. A local
                        # SQLite refresh failure must not mislabel the audio operation as failed.
                        payload["index_refresh"] = None
                        payload["index_refresh_error"] = str(exc)

                with db.session(self.db_path) as conn:
                    conn.execute(
                        """
                        UPDATE conversion_files
                        SET status=?,finished_at=?,error_text=?,source_sha256=?,temp_sha256=?,final_sha256=?,result_json=?
                        WHERE id=?
                        """,
                        (
                            "completed" if result.status == "completed" else "failed",
                            finished,
                            result.error,
                            result.source_sha256,
                            result.temp_sha256,
                            result.final_sha256,
                            json.dumps(payload, separators=(",", ":")),
                            file_id,
                        ),
                    )
                return payload
        except SourceBusyError as exc:
            if prior_defers >= 1:
                return self._record_file_failure(
                    file_id,
                    f"Source remained busy after the one deferred end-of-batch retry; original left untouched: {source}",
                )
            return self._record_file_deferred(
                job_id,
                file_id,
                str(source),
                f"Source is busy under advisory-lock detection; deferred until the end of the batch: {source}",
            )
        except Exception as exc:
            return self._record_file_failure(file_id, str(exc))

    def _refresh_album_replaygain(self, job_id: int, album_index: int) -> None:
        with db.session(self.db_path) as conn:
            identity_row = conn.execute(
                "SELECT albumartist,album FROM conversion_files WHERE job_id=? AND album_index=? LIMIT 1",
                (job_id, album_index),
            ).fetchone()
            if not identity_row:
                return
            converted = conn.execute(
                "SELECT id,path,result_json FROM conversion_files "
                "WHERE job_id=? AND album_index=? AND status='completed' ORDER BY file_index",
                (job_id, album_index),
            ).fetchall()
            if not converted:
                return
            album_rows = conn.execute(
                "SELECT path FROM tracks WHERE COALESCE(albumartist,'')=? AND COALESCE(album,'')=? "
                "ORDER BY folder COLLATE NOCASE, filename COLLATE NOCASE",
                (str(identity_row['albumartist']), str(identity_row['album'])),
            ).fetchall()
        album_paths = [Path(str(row['path'])).resolve() for row in album_rows]
        if not album_paths:
            raise JobError('ReplayGain recalculation could not resolve the logical album from the local index')
        missing = [str(path) for path in album_paths if not path.is_file()]
        if missing:
            raise JobError('ReplayGain recalculation requires every logical-album track to be readable: ' + '; '.join(missing[:5]))
        try:
            values = scan_album(album_paths)
            for row in converted:
                path = Path(str(row['path'])).resolve()
                rg = values.get(path)
                if rg is None:
                    raise ReplayGainError(f'rsgain returned no track result for {path}')
                final_sha = apply_replaygain_transaction(path, rg, self.db_path.parent)
                try:
                    payload = json.loads(row['result_json'] or '{}')
                except (TypeError, json.JSONDecodeError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                payload['replaygain'] = {
                    'recalculated': True,
                    'algorithm': 'ReplayGain 2.0 / BS.1770',
                    'true_peak': True,
                    'target_loudness_lufs': -18,
                    'clip_mode': 'always',
                    'max_peak_db': 0,
                    'track_gain': rg.track_gain,
                    'track_peak': rg.track_peak,
                    'album_gain': rg.album_gain,
                    'album_peak': rg.album_peak,
                    'reference_loudness': rg.reference_loudness,
                }
                payload['final_sha256'] = final_sha
                refresh_track(self.db_path, self.music_root, path, self.timezone)
                with db.session(self.db_path) as conn:
                    conn.execute(
                        'UPDATE conversion_files SET final_sha256=?,result_json=? WHERE id=?',
                        (final_sha, json.dumps(payload, separators=(',', ':')), int(row['id'])),
                    )
            self._event(
                job_id,
                'replaygain_album_updated',
                {
                    'album_index': album_index,
                    'albumartist': str(identity_row['albumartist']),
                    'album': str(identity_row['album']),
                    'logical_album_tracks': len(album_paths),
                    'converted_tracks_updated': len(converted),
                    'true_peak': True,
                    'target_loudness_lufs': -18,
                },
            )
        except Exception as exc:
            self._event(
                job_id,
                'replaygain_album_error',
                {'album_index': album_index, 'error_type': type(exc).__name__, 'error': str(exc)},
            )
            raise JobError(f'ReplayGain recalculation failed after audio conversion: {type(exc).__name__}: {exc}') from exc

    def _retry_deferred_files(
        self,
        job_id: int,
        profile: ResampleProfile,
        source_pre_hash: bool = False,
    ) -> tuple[str, str | None]:
        """Retry each advisory-busy source once, in original batch order."""
        terminal_status = "completed"
        terminal_error: str | None = None
        with db.session(self.db_path) as conn:
            deferred = conn.execute(
                """
                SELECT id,path,source_bytes FROM conversion_files
                WHERE job_id=? AND status='deferred'
                ORDER BY album_index,file_index
                """,
                (job_id,),
            ).fetchall()
        for row in deferred:
            controls = self._controls(job_id)
            if controls["cancel"]:
                return "cancelled", terminal_error
            if controls["pause"]:
                return "paused", terminal_error
            if controls["stop_album"]:
                return "stopped", terminal_error
            gate = self._runtime_gate(int(row["source_bytes"]))
            if gate:
                self._event(
                    job_id,
                    "runtime_pause",
                    {"reason": gate, "stage": "deferred-retry", "required_temp_bytes": int(row["source_bytes"])},
                )
                return "paused", gate
            payload = self._run_file(
                job_id,
                int(row["id"]),
                str(row["path"]),
                profile,
                int(row["source_bytes"]),
                source_pre_hash,
            )
            if payload.get("status") == "failed":
                terminal_error = payload.get("error") or terminal_error
        return terminal_status, terminal_error

    def _run_job(self, job_id: int) -> None:
        terminal_status = "completed"
        terminal_error: str | None = None
        try:
            with db.session(self.db_path) as conn:
                job = conn.execute("SELECT * FROM conversion_jobs WHERE id=?", (job_id,)).fetchone()
                if not job:
                    raise JobError("Job disappeared")
                profile_id = str(job["profile_id"])
                raw_profile = job["profile_json"]
                if raw_profile:
                    try:
                        profile = profile_from_dict(json.loads(raw_profile))
                    except (ValueError, json.JSONDecodeError) as exc:
                        raise JobError(f"Stored DSP profile snapshot is invalid: {exc}") from exc
                else:
                    # Compatibility for jobs created before profile snapshots were introduced.
                    profile = get_profile(profile_id)
                try:
                    operational = json.loads(job["operational_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    operational = {}
                if not isinstance(operational, dict):
                    operational = {}
                source_pre_hash = bool(operational.get("source_pre_hash", False))
                album_indices = [
                    r["album_index"] for r in conn.execute(
                        "SELECT DISTINCT album_index FROM conversion_files WHERE job_id=? ORDER BY album_index",
                        (job_id,),
                    ).fetchall()
                ]

            for album_index in album_indices:
                controls = self._controls(job_id)
                if controls["cancel"]:
                    terminal_status = "cancelled"
                    break
                if controls["pause"]:
                    terminal_status = "paused"
                    break

                with db.session(self.db_path) as conn:
                    files = conn.execute(
                        """
                        SELECT id,path,source_bytes FROM conversion_files
                        WHERE job_id=? AND album_index=? AND status='pending'
                        ORDER BY file_index
                        """,
                        (job_id, album_index),
                    ).fetchall()

                # Process an album in small waves so pause/cancel/concurrency changes can take
                # effect between files without killing an active SoX process.
                cursor = 0
                while cursor < len(files):
                    controls = self._controls(job_id)
                    if controls["cancel"]:
                        terminal_status = "cancelled"
                        break
                    if controls["pause"]:
                        terminal_status = "paused"
                        break
                    with db.session(self.db_path) as conn:
                        current_workers = int(
                            conn.execute(
                                "SELECT workers FROM conversion_jobs WHERE id=?",
                                (job_id,),
                            ).fetchone()["workers"]
                        )
                    wave = files[cursor: cursor + max(1, min(2, current_workers))]
                    required_temp = sum(int(r["source_bytes"]) for r in wave)
                    gate = self._runtime_gate(required_temp)
                    if gate:
                        terminal_status = "paused"
                        terminal_error = gate
                        self._event(
                            job_id,
                            "runtime_pause",
                            {"reason": gate, "stage": "main-batch", "required_temp_bytes": required_temp},
                        )
                        break
                    cursor += len(wave)
                    with ThreadPoolExecutor(
                        max_workers=len(wave),
                        thread_name_prefix=f"job-{job_id}",
                    ) as pool:
                        futures = [
                            pool.submit(
                                self._run_file,
                                job_id,
                                r["id"],
                                r["path"],
                                profile,
                                int(r["source_bytes"]),
                                source_pre_hash,
                            )
                            for r in wave
                        ]
                        for future in as_completed(futures):
                            payload = future.result()
                            if payload.get("status") == "failed":
                                terminal_error = payload.get("error") or terminal_error
                    # Control requests and runtime safeguards are honored between active waves.
                # ReplayGain is recalculated from the full current logical album and written only
                # to tracks converted by this job. This is a user-initiated conversion stage, never
                # a scheduled/background library write. Re-running it on resume is intentional.
                self._refresh_album_replaygain(job_id, album_index)
                if terminal_status in ("paused", "cancelled"):
                    break
                if self._controls(job_id)["stop_album"]:
                    terminal_status = "stopped"
                    break

            if terminal_status == "completed":
                deferred_status, deferred_error = self._retry_deferred_files(
                    job_id, profile, source_pre_hash
                )
                terminal_status = deferred_status
                terminal_error = deferred_error or terminal_error
                # A deferred source may have changed the final logical-album audio set; refresh
                # album/track ReplayGain once more after the one allowed deferred retry pass.
                for album_index in album_indices:
                    self._refresh_album_replaygain(job_id, album_index)
        except Exception as exc:
            terminal_status = "interrupted"
            terminal_error = str(exc)
        finally:
            finished_at = self._now()
            with db.session(self.db_path) as conn:
                conn.execute(
                    "UPDATE conversion_jobs SET status=?,finished_at=?,error_text=? WHERE id=?",
                    (terminal_status, finished_at, terminal_error, job_id),
                )
            record_job_event(
                self.db_path,
                job_id,
                finished_at,
                "job_finished",
                {"status": terminal_status, "message": terminal_error},
            )
            with self._lock:
                self._active_job_id = None

    def request_pause(self, job_id: int) -> None:
        self._set_flag(job_id, "pause_requested", 1, "pausing", "pause_requested")

    def request_stop_after_album(self, job_id: int) -> None:
        self._set_flag(job_id, "stop_after_album", 1, "stopping", "stop_after_album_requested")

    def request_cancel(self, job_id: int) -> None:
        self._set_flag(job_id, "cancel_requested", 1, "cancelling", "cancel_requested")

    def set_workers(self, job_id: int, workers: int) -> None:
        if workers not in (1, 2):
            raise JobError("Workers must be 1 or 2")
        previous_workers = 0
        with db.session(self.db_path) as conn:
            row = conn.execute("SELECT id,workers FROM conversion_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise JobError("Job not found")
            previous_workers = int(row["workers"])
            conn.execute("UPDATE conversion_jobs SET workers=? WHERE id=?", (workers, job_id))
        if previous_workers != workers:
            self._event(
                job_id,
                "workers_changed",
                {"from": previous_workers, "to": workers, "takes_effect": "between-files"},
            )

    def _set_flag(
        self,
        job_id: int,
        column: str,
        value: int,
        status: str,
        event_type: str,
    ) -> None:
        if column not in {"pause_requested", "stop_after_album", "cancel_requested"}:
            raise JobError("Invalid control flag")
        previous_status = ""
        with db.session(self.db_path) as conn:
            row = conn.execute("SELECT id,status FROM conversion_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise JobError("Job not found")
            previous_status = str(row["status"])
            conn.execute(
                f"UPDATE conversion_jobs SET {column}=?,status=? WHERE id=?",
                (value, status, job_id),
            )
        self._event(
            job_id,
            event_type,
            {"previous_status": previous_status, "requested_status": status},
        )

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with db.session(self.db_path) as conn:
            job = conn.execute("SELECT * FROM conversion_jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                return None
            count_rows = conn.execute(
                "SELECT status,COUNT(*) count,SUM(source_bytes) bytes "
                "FROM conversion_files WHERE job_id=? GROUP BY status",
                (job_id,),
            ).fetchall()
            counts = {row["status"]: int(row["count"] or 0) for row in count_rows}
            bytes_by_status = {row["status"]: int(row["bytes"] or 0) for row in count_rows}
            total = conn.execute(
                "SELECT COUNT(*) count,COALESCE(SUM(source_bytes),0) bytes "
                "FROM conversion_files WHERE job_id=?",
                (job_id,),
            ).fetchone()
            current = conn.execute(
                "SELECT * FROM conversion_files WHERE job_id=? AND status='running' "
                "ORDER BY album_index,file_index",
                (job_id,),
            ).fetchall()
            deferred = conn.execute(
                "SELECT id,albumartist,album,path,error_text,finished_at,defer_count "
                "FROM conversion_files WHERE job_id=? AND status='deferred' "
                "ORDER BY album_index,file_index LIMIT 20",
                (job_id,),
            ).fetchall()
            recent_failures = conn.execute(
                "SELECT id,albumartist,album,path,error_text,finished_at "
                "FROM conversion_files WHERE job_id=? AND status='failed' "
                "ORDER BY id DESC LIMIT 20",
                (job_id,),
            ).fetchall()

        total_files = int(total["count"] or 0)
        processed_files = counts.get("completed", 0) + counts.get("failed", 0)
        result = dict(job)
        if result.get("profile_json"):
            try:
                result["profile"] = json.loads(result["profile_json"])
            except json.JSONDecodeError:
                result["profile"] = None
        else:
            result["profile"] = None
        result.pop("profile_json", None)
        try:
            operational = json.loads(result.get("operational_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            operational = {}
        result["operational"] = operational if isinstance(operational, dict) else {}
        result.pop("operational_json", None)
        result["counts"] = counts
        result["bytes_by_status"] = bytes_by_status
        result["total_files"] = total_files
        result["total_source_bytes"] = int(total["bytes"] or 0)
        result["processed_files"] = processed_files
        result["progress_percent"] = (
            round(processed_files * 100.0 / total_files, 1) if total_files else 0.0
        )
        result["current_files"] = [dict(r) for r in current]
        result["deferred_files"] = [dict(r) for r in deferred]
        result["recent_failures"] = [dict(r) for r in recent_failures]
        result["recent_events"] = load_job_events(self.db_path, job_id, limit=30)
        return result

    def recent_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with db.session(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id,created_at,started_at,finished_at,status,profile_id,workers,source_filter_json,album_order_json,"
                "pause_requested,stop_after_album,cancel_requested,error_text "
                "FROM conversion_jobs ORDER BY id DESC LIMIT ?",
                (max(1, min(200, limit)),),
            ).fetchall()
        return [dict(r) for r in rows]
