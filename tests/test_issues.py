from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import db
from app.issues import build_metadata_issues, render_issues_csv, render_issues_txt


class MetadataIssuesTest(unittest.TestCase):
    def _insert_track(self, db_path: Path, **overrides) -> None:
        values = {
            "path": "/music/Test Artist/Test Album/01.flac",
            "rel_path": "Test Artist/Test Album/01.flac",
            "folder": "/music/Test Artist/Test Album",
            "filename": "01.flac",
            "size_bytes": 1000,
            "mtime_ns": 1,
            "sample_rate": 96000,
            "bits_per_sample": 24,
            "channels": 2,
            "duration": 180.0,
            "albumartist": "Test Artist",
            "album": "Test Album",
            "releasetype": "album",
            "musicbrainz_albumid": "mbid-1",
            "artist": "Test Artist",
            "title": "Track",
            "tracknumber": "1",
            "discnumber": "1",
            "replaygain_track_gain": "-5.0 dB",
            "replaygain_track_peak": "0.9",
            "replaygain_album_gain": "-4.0 dB",
            "replaygain_album_peak": "0.95",
            "picture_count": 1,
            "first_seen": "2026-09-01T10:00:00-04:00",
            "last_seen": "2026-09-01T10:00:00-04:00",
            "tag_json": "{}",
        }
        values.update(overrides)
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        with db.session(db_path) as conn:
            conn.execute(f"INSERT INTO tracks({columns}) VALUES({placeholders})", tuple(values.values()))

    def test_missing_critical_tag_and_replaygain_include_exact_track(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            db.init(db_path)
            self._insert_track(
                db_path,
                albumartist=None,
                replaygain_album_gain=None,
                replaygain_album_peak=None,
            )
            issues = build_metadata_issues(db_path)
            missing = next(i for i in issues if i["issue_type"] == "missing_albumartist")
            self.assertEqual(missing["severity"], "blocking")
            self.assertEqual(missing["affected_tracks"][0]["filename"], "01.flac")
            replaygain = next(i for i in issues if i["issue_type"] == "replaygain_incomplete")
            self.assertEqual(replaygain["severity"], "warning")
            self.assertIn("REPLAYGAIN_ALBUM_GAIN", replaygain["affected_tracks"][0]["value"])

    def test_inconsistent_mbid_is_detected_within_physical_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            db.init(db_path)
            self._insert_track(db_path)
            self._insert_track(
                db_path,
                path="/music/Test Artist/Test Album/02.flac",
                rel_path="Test Artist/Test Album/02.flac",
                filename="02.flac",
                tracknumber="2",
                musicbrainz_albumid="mbid-2",
            )
            issues = build_metadata_issues(db_path)
            issue = next(i for i in issues if i["issue_type"] == "inconsistent_musicbrainz_albumid")
            self.assertEqual(len(issue["affected_tracks"]), 2)
            self.assertEqual({t["value"] for t in issue["affected_tracks"]}, {"mbid-1", "mbid-2"})

    def test_cross_folder_releasetype_conflict_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            db.init(db_path)
            self._insert_track(
                db_path,
                folder="/music/Test Artist/Test Album/Disc 1",
                path="/music/Test Artist/Test Album/Disc 1/01.flac",
                rel_path="Test Artist/Test Album/Disc 1/01.flac",
            )
            self._insert_track(
                db_path,
                folder="/music/Test Artist/Test Album/Disc 2",
                path="/music/Test Artist/Test Album/Disc 2/02.flac",
                rel_path="Test Artist/Test Album/Disc 2/02.flac",
                filename="02.flac",
                tracknumber="2",
                discnumber="2",
                releasetype="album; compilation",
            )
            issues = build_metadata_issues(db_path)
            issue = next(i for i in issues if i["issue_type"] == "inconsistent_releasetype_across_folders")
            self.assertEqual(issue["severity"], "blocking")
            self.assertEqual(len(issue["folders"]), 2)
            self.assertEqual({t["value"] for t in issue["affected_tracks"]}, {"album", "album; compilation"})

    def test_shared_mbid_identity_conflict_is_blocking_not_duplicate_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            db.init(db_path)
            self._insert_track(db_path, musicbrainz_albumid="shared-mbid")
            self._insert_track(
                db_path,
                path="/music/Other Artist/Other Album/01.flac",
                rel_path="Other Artist/Other Album/01.flac",
                folder="/music/Other Artist/Other Album",
                albumartist="Other Artist",
                album="Other Album",
                musicbrainz_albumid="shared-mbid",
            )
            issues = build_metadata_issues(db_path)
            conflict = next(i for i in issues if i["issue_type"] == "musicbrainz_albumid_identity_conflict")
            self.assertEqual(conflict["severity"], "blocking")
            self.assertEqual(len(conflict["affected_tracks"]), 2)
            self.assertFalse(any(
                i["issue_type"] == "duplicate_musicbrainz_albumid"
                and any(t["value"] == "shared-mbid" for t in i["affected_tracks"])
                for i in issues
            ))

    def test_issue_exports_contain_severity_path_and_track(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            db.init(db_path)
            self._insert_track(db_path, releasetype=None)
            issues = build_metadata_issues(db_path)
            text = render_issues_txt(issues, "America/Indiana/Indianapolis")
            csv_text = render_issues_csv(issues)
            self.assertIn("[BLOCKING]", text)
            self.assertIn("/music/Test Artist/Test Album", text)
            self.assertIn("01.flac", text)
            self.assertIn("severity,issue_type", csv_text)
            self.assertIn("path,track,current_value", csv_text)
            self.assertIn("/music/Test Artist/Test Album/01.flac", csv_text)
            self.assertIn("missing_releasetype", csv_text)


if __name__ == "__main__":
    unittest.main()
