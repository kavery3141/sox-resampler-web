from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import db


class CandidateAlbumsTests(unittest.TestCase):
    def _insert_track(
        self,
        db_path: Path,
        *,
        path: str,
        rate: int,
        size: int,
        tracknumber: str,
    ) -> None:
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
                    path,
                    Path(path).name,
                    "/music/Test Artist/Test Album",
                    Path(path).name,
                    size,
                    1,
                    rate,
                    24,
                    2,
                    1.0,
                    "Test Artist",
                    "Test Album",
                    "album",
                    "11111111-2222-3333-4444-555555555555",
                    "Test Artist",
                    f"Track {tracknumber}",
                    tracknumber,
                    "1",
                    "-1.00 dB",
                    "0.5",
                    "-1.00 dB",
                    "0.5",
                    0,
                    "2026-09-01T10:00:00-04:00",
                    "2026-09-01T10:00:00-04:00",
                    "{}",
                ),
            )

    def test_rate_predicate_bindings_and_48k_estimate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "library.db"
            db.init(db_path)
            self._insert_track(
                db_path,
                path="/music/Test Artist/Test Album/01.flac",
                rate=96000,
                size=1000,
                tracknumber="1",
            )
            self._insert_track(
                db_path,
                path="/music/Test Artist/Test Album/02.flac",
                rate=48000,
                size=500,
                tracknumber="2",
            )

            rows = db.candidate_albums(db_path, [88200, 96000], above=None)
            self.assertEqual(len(rows), 1)
            album = rows[0]
            self.assertEqual(album["matching_tracks"], 1)
            self.assertEqual(album["untouched_tracks"], 1)
            self.assertEqual(album["matching_bytes"], 1000)
            self.assertEqual(album["source_rates"], [96000])
            self.assertEqual(album["estimated_output_48k_bytes"], 550)
            self.assertEqual(album["estimated_savings_48k_bytes"], 450)
            self.assertTrue(album["selectable"])

    def test_combined_exact_and_above_rate_filter_uses_or_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "library.db"
            db.init(db_path)
            self._insert_track(
                db_path,
                path="/music/Test Artist/Test Album/01.flac",
                rate=88200,
                size=1000,
                tracknumber="1",
            )
            self._insert_track(
                db_path,
                path="/music/Test Artist/Test Album/02.flac",
                rate=176400,
                size=1000,
                tracknumber="2",
            )

            rows = db.candidate_albums(db_path, [88200], above=100000)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["matching_tracks"], 2)
            self.assertEqual(rows[0]["source_rates"], [88200, 176400])


if __name__ == "__main__":
    unittest.main()
