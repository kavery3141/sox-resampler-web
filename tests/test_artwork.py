from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app import db
from app.artwork import artwork_summary, prune_album_artwork, refresh_album_artwork


class ArtworkCacheTests(unittest.TestCase):
    def _insert_track(
        self,
        db_path: Path,
        *,
        path: Path,
        folder: Path,
        picture_count: int = 0,
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
                    str(path),
                    path.name,
                    str(folder),
                    path.name,
                    1000,
                    123456,
                    96000,
                    24,
                    2,
                    1.0,
                    "Artist",
                    "Album",
                    "album",
                    "11111111-2222-3333-4444-555555555555",
                    "Artist",
                    "Track",
                    "1",
                    "1",
                    "-1.00 dB",
                    "0.5",
                    "-1.00 dB",
                    "0.5",
                    picture_count,
                    "2026-09-01T10:00:00-04:00",
                    "2026-09-01T10:00:00-04:00",
                    "{}",
                ),
            )

    @staticmethod
    def _png_bytes(size: tuple[int, int] = (640, 480)) -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", size).save(buffer, format="PNG")
        return buffer.getvalue()

    def test_fallback_folder_art_is_resized_and_exposed_to_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_root = root / "data"
            album = root / "music" / "Artist" / "Album"
            album.mkdir(parents=True)
            db_path = data_root / "library.db"
            db.init(db_path)
            track = album / "01.flac"
            track.write_bytes(b"indexed-placeholder")
            self._insert_track(db_path, path=track, folder=album)
            Image.new("RGB", (1000, 700)).save(album / "folder.jpg", format="JPEG")
            Image.new("RGB", (800, 800)).save(album / "cover.jpg", format="JPEG")

            result = refresh_album_artwork(
                db_path,
                data_root,
                album,
                "2026-09-01T12:00:00-04:00",
            )
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["source_kind"], "file")
            self.assertLessEqual(result["width"], 320)
            self.assertLessEqual(result["height"], 320)

            with db.session(db_path) as conn:
                row = dict(conn.execute("SELECT * FROM album_art WHERE folder=?", (str(album),)).fetchone())
            self.assertEqual(Path(row["source_path"]).name.lower(), "folder.jpg")
            self.assertTrue(Path(row["cache_path"]).is_file())

            candidates = db.candidate_albums(db_path, [96000])
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["artwork_id"], row["id"])
            self.assertEqual(candidates[0]["artwork_url"], f"/api/artwork/albums/{row['id']}")

    def test_embedded_art_has_priority_over_external_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_root = root / "data"
            album = root / "music" / "Artist" / "Album"
            album.mkdir(parents=True)
            db_path = data_root / "library.db"
            db.init(db_path)
            track = album / "01.flac"
            track.write_bytes(b"indexed-placeholder")
            self._insert_track(db_path, path=track, folder=album, picture_count=1)
            Image.new("RGB", (500, 500)).save(album / "folder.jpg", format="JPEG")

            with patch("app.artwork._embedded_image_bytes", return_value=self._png_bytes()):
                result = refresh_album_artwork(
                    db_path,
                    data_root,
                    album,
                    "2026-09-01T12:00:00-04:00",
                )
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["source_kind"], "embedded")
            with db.session(db_path) as conn:
                row = conn.execute("SELECT source_kind,source_path FROM album_art WHERE folder=?", (str(album),)).fetchone()
            self.assertEqual(row["source_kind"], "embedded")
            self.assertEqual(row["source_path"], str(track))

    def test_missing_art_uses_indexed_missing_state_without_library_reads_at_serve_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_root = root / "data"
            album = root / "music" / "Artist" / "Album"
            album.mkdir(parents=True)
            db_path = data_root / "library.db"
            db.init(db_path)
            track = album / "01.flac"
            track.write_bytes(b"indexed-placeholder")
            self._insert_track(db_path, path=track, folder=album)

            result = refresh_album_artwork(
                db_path,
                data_root,
                album,
                "2026-09-01T12:00:00-04:00",
            )
            self.assertEqual(result["status"], "missing")
            self.assertEqual(artwork_summary(db_path)["missing"], 1)
            candidates = db.candidate_albums(db_path, [96000])
            self.assertIsNone(candidates[0]["artwork_url"])

    def test_prune_removes_cache_only_after_folder_leaves_track_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_root = root / "data"
            album = root / "music" / "Artist" / "Album"
            album.mkdir(parents=True)
            db_path = data_root / "library.db"
            db.init(db_path)
            track = album / "01.flac"
            track.write_bytes(b"indexed-placeholder")
            self._insert_track(db_path, path=track, folder=album)
            Image.new("RGB", (400, 400)).save(album / "folder.png", format="PNG")
            refresh_album_artwork(db_path, data_root, album, "2026-09-01T12:00:00-04:00")
            with db.session(db_path) as conn:
                row = conn.execute("SELECT cache_path FROM album_art WHERE folder=?", (str(album),)).fetchone()
            cache_path = Path(row["cache_path"])
            self.assertTrue(cache_path.exists())

            with db.session(db_path) as conn:
                conn.execute("DELETE FROM tracks WHERE folder=?", (str(album),))
            result = prune_album_artwork(db_path, data_root)
            self.assertEqual(result["removed"], 1)
            self.assertFalse(cache_path.exists())
            self.assertEqual(artwork_summary(db_path)["total"], 0)


if __name__ == "__main__":
    unittest.main()
