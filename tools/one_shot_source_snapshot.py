from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match in {path}, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def write_new(path: str, content: str) -> None:
    file_path = Path(path)
    if file_path.exists():
        raise SystemExit(f"refusing to overwrite existing file: {path}")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


write_new(
    "app/source_snapshot.py",
    '''from __future__ import annotations

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
''',
)

replace_once(
    "app/review.py",
    "from .resource_control import configured_cpu_limit\n",
    "from .resource_control import configured_cpu_limit\nfrom .source_snapshot import capture_source_snapshot\n",
    "review source snapshot import",
)
replace_once(
    "app/review.py",
    "                current_mtime_ns: int | None = None\n",
    "                current_mtime_ns: int | None = None\n                source_snapshot: dict[str, Any] | None = None\n",
    "review source snapshot state",
)
replace_once(
    "app/review.py",
    '''                        st = resolved_source.stat()\n                        current_mtime_ns = int(st.st_mtime_ns)\n                        if int(st.st_size) != source_size:\n                            track_blockers.append(\n                                f"Source size changed since scan ({source_size} -> {st.st_size}); rescan required"\n                            )\n                        if int(item.get("mtime_ns") or 0) != current_mtime_ns:\n                            track_blockers.append("Source modification time changed since scan; rescan required")\n''',
    '''                        source_snapshot = capture_source_snapshot(resolved_source)\n                        current_mtime_ns = int(source_snapshot["mtime_ns"])\n                        if int(source_snapshot["size_bytes"]) != source_size:\n                            track_blockers.append(\n                                f"Source size changed since scan ({source_size} -> {source_snapshot['size_bytes']}); rescan required"\n                            )\n                        if int(item.get("mtime_ns") or 0) != current_mtime_ns:\n                            track_blockers.append("Source modification time changed since scan; rescan required")\n''',
    "review identity snapshot capture",
)
replace_once(
    "app/review.py",
    '''                        live_audio = FLAC(resolved_source)\n                        for db_name, tag_name in KEY_TAGS:\n                            indexed_value = (item.get(db_name) or "").strip()\n                            live_value = (_first(live_audio, tag_name) or "").strip()\n                            if live_value != indexed_value:\n                                track_blockers.append(\n                                    f"{tag_name} changed since scan ({indexed_value or '<missing>'} -> {live_value or '<missing>'}); rescan required"\n                                )\n''',
    '''                        for db_name, tag_name in KEY_TAGS:\n                            indexed_value = (item.get(db_name) or "").strip()\n                            live_value = str(source_snapshot["critical_tags"].get(tag_name) or "").strip()\n                            if live_value != indexed_value:\n                                track_blockers.append(\n                                    f"{tag_name} changed since scan ({indexed_value or '<missing>'} -> {live_value or '<missing>'}); rescan required"\n                                )\n''',
    "review critical tag snapshot comparison",
)
replace_once(
    "app/review.py",
    '''                        "current_mtime_ns": current_mtime_ns,\n                        "estimated_output_bytes": estimated,\n''',
    '''                        "current_mtime_ns": current_mtime_ns,\n                        "source_snapshot": source_snapshot,\n                        "estimated_output_bytes": estimated,\n''',
    "review snapshot payload",
)

replace_once(
    "app/jobs.py",
    "from .resource_control import configured_cpu_limit\nfrom .storage_health import zfs_pool_health\n",
    "from .resource_control import configured_cpu_limit\nfrom .source_snapshot import capture_source_snapshot, compare_source_snapshots\nfrom .storage_health import zfs_pool_health\n",
    "job snapshot import",
)
replace_once(
    "app/jobs.py",
    '''                source_bytes INTEGER NOT NULL DEFAULT 0,\n                status TEXT NOT NULL,\n''',
    '''                source_bytes INTEGER NOT NULL DEFAULT 0,\n                source_snapshot_json TEXT,\n                status TEXT NOT NULL,\n''',
    "job snapshot schema",
)
replace_once(
    "app/jobs.py",
    '''        if "source_sha256" not in file_columns:\n            conn.execute("ALTER TABLE conversion_files ADD COLUMN source_sha256 TEXT")\n''',
    '''        if "source_sha256" not in file_columns:\n            conn.execute("ALTER TABLE conversion_files ADD COLUMN source_sha256 TEXT")\n        if "source_snapshot_json" not in file_columns:\n            conn.execute("ALTER TABLE conversion_files ADD COLUMN source_snapshot_json TEXT")\n''',
    "job snapshot migration",
)
replace_once(
    "app/jobs.py",
    '''                    conn.execute(\n                        """\n                        INSERT INTO conversion_files(\n                          job_id,album_index,file_index,albumartist,album,path,source_bytes,status\n                        ) VALUES(?,?,?,?,?,?,?,?)\n                        """,\n                        (\n                            job_id, album_index, file_index, album["albumartist"], album["album"],\n                            str(path), int(track["source_bytes"]), "pending",\n                        ),\n                    )\n''',
    '''                    source_snapshot = track.get("source_snapshot")\n                    source_snapshot_json = (\n                        json.dumps(source_snapshot, separators=(",", ":"), sort_keys=True)\n                        if isinstance(source_snapshot, dict)\n                        else None\n                    )\n                    conn.execute(\n                        """\n                        INSERT INTO conversion_files(\n                          job_id,album_index,file_index,albumartist,album,path,source_bytes,source_snapshot_json,status\n                        ) VALUES(?,?,?,?,?,?,?,?,?)\n                        """,\n                        (\n                            job_id, album_index, file_index, album["albumartist"], album["album"],\n                            str(path), int(track["source_bytes"]), source_snapshot_json, "pending",\n                        ),\n                    )\n''',
    "job snapshot persistence",
)
replace_once(
    "app/jobs.py",
    '''        with db.session(self.db_path) as conn:\n            row = conn.execute("SELECT defer_count FROM conversion_files WHERE id=?", (file_id,)).fetchone()\n        if not row:\n            return self._record_file_failure(file_id, "Conversion file record disappeared")\n        prior_defers = int(row["defer_count"] or 0)\n\n        try:\n            with source_read_guard(source) as guard:\n                started = self._now()\n''',
    '''        with db.session(self.db_path) as conn:\n            row = conn.execute(\n                "SELECT defer_count,source_snapshot_json FROM conversion_files WHERE id=?",\n                (file_id,),\n            ).fetchone()\n        if not row:\n            return self._record_file_failure(file_id, "Conversion file record disappeared")\n        prior_defers = int(row["defer_count"] or 0)\n\n        try:\n            expected_snapshot: dict[str, Any] | None = None\n            raw_snapshot = row["source_snapshot_json"]\n            if raw_snapshot:\n                try:\n                    parsed_snapshot = json.loads(raw_snapshot)\n                except (TypeError, json.JSONDecodeError) as exc:\n                    raise JobError("Stored source identity snapshot is invalid; fresh review required") from exc\n                if not isinstance(parsed_snapshot, dict):\n                    raise JobError("Stored source identity snapshot is invalid; fresh review required")\n                expected_snapshot = parsed_snapshot\n\n            with source_read_guard(source) as guard:\n                if expected_snapshot is not None:\n                    current_snapshot = capture_source_snapshot(source)\n                    changes = compare_source_snapshots(expected_snapshot, current_snapshot)\n                    if changes:\n                        self._event(\n                            job_id,\n                            "source_revalidation_failed",\n                            {"file_id": file_id, "path": str(source), "changes": changes},\n                        )\n                        raise JobError(\n                            "Source changed after batch review; original left untouched; "\n                            "rescan/review required: " + "; ".join(changes)\n                        )\n\n                started = self._now()\n''',
    "job source snapshot revalidation",
)

replace_once(
    "README.md",
    '''Each source FLAC is converted to a hidden same-directory temporary file. Before replacement the app verifies technical output properties, user metadata and embedded pictures, performs a full FLAC decode test, checks clipping, preserves filesystem metadata, revalidates source identity, and hashes the verified output. Advanced batch safety can optionally SHA-256 pre-hash each source before SoX; this is disabled by default, is recorded in the job/report, and is deliberately not stored in DSP presets. Replacement uses a persistent crash-recovery journal and an atomic same-filesystem exchange. The old source remains available until the new file has passed final verification; failures leave the original untouched.\n''',
    '''Each source FLAC is converted to a hidden same-directory temporary file. A destructive review now persists a per-file source snapshot covering filesystem device/inode, size, mtime, sample rate, bit depth, channels, and the four conversion-critical album tags; each file is revalidated against that snapshot immediately before work begins. Before replacement the app verifies technical output properties, user metadata and embedded pictures, performs a full FLAC decode test, checks clipping, preserves filesystem metadata, revalidates source identity again, and hashes the verified output. Advanced batch safety can optionally SHA-256 pre-hash each source before SoX; this is disabled by default, is recorded in the job/report, and is deliberately not stored in DSP presets. Replacement uses a persistent crash-recovery journal and an atomic same-filesystem exchange. The old source remains available until the new file has passed final verification; failures leave the original untouched.\n''',
    "README source snapshot documentation",
)

write_new(
    "tests/test_job_source_snapshot.py",
    '''from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mutagen.flac import FLAC

from app import db
from app.index_update import refresh_track
from app.jobs import ConversionJobManager
from app.profiles import FACTORY_DEFAULTS
from app.review import build_batch_review
from app.source_snapshot import compare_source_snapshots


class JobSourceSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.music = root / "music"
        self.folder = self.music / "Artist" / "Album"
        self.folder.mkdir(parents=True)
        self.db_path = root / "data" / "test.db"
        db.init(self.db_path)
        self.track = self.folder / "01 - Test.flac"
        subprocess.run(
            ["sox", "-n", "-r", "96000", "-b", "24", str(self.track), "synth", "0.03", "sine", "997", "vol", "0.05"],
            check=True,
            capture_output=True,
        )
        audio = FLAC(self.track)
        audio["ALBUMARTIST"] = ["Artist"]
        audio["ALBUM"] = ["Album"]
        audio["RELEASETYPE"] = ["album"]
        audio["MUSICBRAINZ_ALBUMID"] = ["00000000-0000-0000-0000-000000000001"]
        audio["TITLE"] = ["Test"]
        audio["TRACKNUMBER"] = ["1"]
        audio.save()
        refresh_track(
            self.db_path,
            self.music,
            self.track,
            "America/Indiana/Indianapolis",
        )
        self.manager = ConversionJobManager(
            self.db_path,
            self.music,
            "America/Indiana/Indianapolis",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _review(self) -> dict:
        return build_batch_review(
            db_path=self.db_path,
            music_root=self.music,
            album_keys=[
                {"albumartist": "Artist", "album": "Album", "folder": str(self.folder)}
            ],
            rates=[96000],
            above=None,
            profile=FACTORY_DEFAULTS,
            workers=1,
            reserve_bytes=0,
        )

    def test_review_snapshot_is_persisted_with_job(self) -> None:
        review = self._review()
        self.assertTrue(review["can_start"], review["blockers"])
        snapshot = review["albums"][0]["tracks"][0]["source_snapshot"]
        self.assertEqual(snapshot["sample_rate"], 96000)
        self.assertEqual(snapshot["bits_per_sample"], 24)
        self.assertEqual(snapshot["critical_tags"]["ALBUMARTIST"], "Artist")
        self.assertGreater(snapshot["inode"], 0)

        job_id = self.manager.create_job(review, FACTORY_DEFAULTS.id, 1, {"rates": [96000]})
        with db.session(self.db_path) as conn:
            row = conn.execute(
                "SELECT source_snapshot_json FROM conversion_files WHERE job_id=?",
                (job_id,),
            ).fetchone()
        stored = json.loads(row["source_snapshot_json"])
        self.assertEqual(stored, snapshot)

    def test_inode_replacement_after_review_is_rejected_before_converter(self) -> None:
        review = self._review()
        self.assertTrue(review["can_start"], review["blockers"])
        job_id = self.manager.create_job(review, FACTORY_DEFAULTS.id, 1, {"rates": [96000]})
        with db.session(self.db_path) as conn:
            row = conn.execute(
                "SELECT id,path,source_bytes,source_snapshot_json FROM conversion_files WHERE job_id=?",
                (job_id,),
            ).fetchone()
        expected = json.loads(row["source_snapshot_json"])

        original_stat = self.track.stat()
        replacement = self.folder / "replacement.flac"
        shutil.copyfile(self.track, replacement)
        os.utime(
            replacement,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )
        os.replace(replacement, self.track)
        os.utime(
            self.track,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )
        self.assertEqual(self.track.stat().st_size, int(row["source_bytes"]))
        self.assertEqual(self.track.stat().st_mtime_ns, expected["mtime_ns"])
        self.assertNotEqual(self.track.stat().st_ino, expected["inode"])

        with patch("app.jobs.convert_file") as convert:
            payload = self.manager._run_file(
                job_id,
                int(row["id"]),
                str(row["path"]),
                FACTORY_DEFAULTS,
                int(row["source_bytes"]),
            )

        convert.assert_not_called()
        self.assertEqual(payload["status"], "failed")
        self.assertIn("inode changed", payload["error"])
        self.assertIn("original left untouched", payload["error"])
        with db.session(self.db_path) as conn:
            events = conn.execute(
                "SELECT event_type FROM conversion_job_events WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        self.assertIn("source_revalidation_failed", [event["event_type"] for event in events])

    def test_snapshot_comparison_reports_critical_tag_change(self) -> None:
        expected = {
            "device": 1,
            "inode": 2,
            "size_bytes": 3,
            "mtime_ns": 4,
            "sample_rate": 96000,
            "bits_per_sample": 24,
            "channels": 2,
            "critical_tags": {
                "ALBUMARTIST": "Artist",
                "ALBUM": "Album",
                "RELEASETYPE": "album",
                "MUSICBRAINZ_ALBUMID": "mbid",
            },
        }
        current = json.loads(json.dumps(expected))
        current["critical_tags"]["ALBUM"] = "Changed Album"
        changes = compare_source_snapshots(expected, current)
        self.assertEqual(len(changes), 1)
        self.assertIn("ALBUM changed", changes[0])


if __name__ == "__main__":
    unittest.main()
''',
)

print("Source identity snapshot implementation applied")
