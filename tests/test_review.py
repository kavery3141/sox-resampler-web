from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db
from app.profiles import FOOBAR_ULTRA_37
from app.review import build_batch_review


class _FakeFlac:
    def __init__(self) -> None:
        self._tags = {
            "albumartist": ["Artist"],
            "album": ["Album"],
            "releasetype": ["album"],
            "musicbrainz_albumid": ["11111111-2222-3333-4444-555555555555"],
        }

    def get(self, key: str):
        return self._tags.get(key.lower())


class BatchReviewTest(unittest.TestCase):
    def test_ultra_profile_readiness_uses_current_profile_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "test.db"
            db.init(db_path)
            review = build_batch_review(
                db_path=db_path,
                music_root=root,
                album_keys=[],
                rates=[96000, 192000],
                above=None,
                profile=FOOBAR_ULTRA_37,
                workers=1,
                reserve_bytes=10 * 1024**3,
            )
            self.assertTrue(review["profile"]["implementation_ready"])
            self.assertFalse(review["can_start"])
            self.assertEqual(review["albums"], [])

    def test_multi_disc_album_review_includes_all_physical_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            music = root / "music"
            disc1 = music / "Artist" / "Album" / "Disc 1"
            disc2 = music / "Artist" / "Album" / "Disc 2"
            disc1.mkdir(parents=True)
            disc2.mkdir(parents=True)
            paths = [disc1 / "01.flac", disc2 / "01.flac"]
            for path in paths:
                path.write_bytes(b"placeholder-flac")

            db_path = root / "test.db"
            db.init(db_path)
            for index, path in enumerate(paths, start=1):
                stat = path.stat()
                with db.session(db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO tracks(
                          path,rel_path,folder,filename,size_bytes,mtime_ns,sample_rate,bits_per_sample,
                          channels,duration,albumartist,album,releasetype,musicbrainz_albumid,artist,title,
                          tracknumber,discnumber,replaygain_track_gain,replaygain_track_peak,
                          replaygain_album_gain,replaygain_album_peak,picture_count,first_seen,last_seen,tag_json
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            str(path),
                            path.relative_to(music).as_posix(),
                            str(path.parent),
                            path.name,
                            stat.st_size,
                            stat.st_mtime_ns,
                            96000,
                            24,
                            2,
                            1.0,
                            "Artist",
                            "Album",
                            "album",
                            "11111111-2222-3333-4444-555555555555",
                            "Artist",
                            f"Disc {index}",
                            "1",
                            str(index),
                            "-1.0 dB",
                            "0.5",
                            "-1.0 dB",
                            "0.5",
                            0,
                            "2026-09-01T10:00:00-04:00",
                            "2026-09-01T10:00:00-04:00",
                            "{}",
                        ),
                    )

            def fake_preview(source: Path, profile):
                return {
                    "sample_rate": 96000,
                    "bits_per_sample": 24,
                    "channels": 2,
                    "preservation_blockers": [],
                    "command": ["sox", str(source), "temp.flac", "rate", "48000"],
                    "profile_available": True,
                    "profile_error": None,
                }

            def fake_source_snapshot(source: Path):
                stat = source.stat()
                return {
                    "device": int(stat.st_dev),
                    "inode": int(stat.st_ino),
                    "size_bytes": int(stat.st_size),
                    "mtime_ns": int(stat.st_mtime_ns),
                    "sample_rate": 96000,
                    "bits_per_sample": 24,
                    "channels": 2,
                    "critical_tags": {
                        "ALBUMARTIST": "Artist",
                        "ALBUM": "Album",
                        "RELEASETYPE": "album",
                        "MUSICBRAINZ_ALBUMID": "11111111-2222-3333-4444-555555555555",
                    },
                }

            with (
                patch("app.review._physical_album_track_count", return_value=1),
                patch("app.review.preview", side_effect=fake_preview),
                patch("app.review.capture_source_snapshot", side_effect=fake_source_snapshot),
                patch("app.review.FLAC", return_value=_FakeFlac()),
            ):
                review = build_batch_review(
                    db_path=db_path,
                    music_root=music,
                    album_keys=[{"albumartist": "Artist", "album": "Album", "folder": str(disc1)}],
                    rates=[96000],
                    above=None,
                    profile=FOOBAR_ULTRA_37,
                    workers=1,
                    reserve_bytes=10 * 1024**3,
                )

            self.assertEqual(review["album_count"], 1)
            album = review["albums"][0]
            self.assertEqual(album["indexed_tracks"], 2)
            self.assertEqual(album["matching_tracks"], 2)
            self.assertEqual(album["folder_count"], 2)
            self.assertEqual(album["folders"], sorted([str(disc1), str(disc2)], key=str.casefold))
            self.assertEqual({track["folder"] for track in album["tracks"]}, {str(disc1), str(disc2)})
            self.assertTrue(review["can_start"])


if __name__ == "__main__":
    unittest.main()
