from __future__ import annotations

import unittest
from pathlib import Path

from app.path_display import (
    decorate_issue_paths,
    decorate_job_report_paths,
    decorate_review_paths,
    host_music_path,
)


class HostMusicPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.music_root = Path("/music")
        self.host_root = Path("/mnt/MainStorage/StorageDataset/Music")

    def test_internal_music_path_maps_to_true_nas_path(self) -> None:
        self.assertEqual(
            host_music_path(
                "/music/Artist/Album/01.flac", self.music_root, self.host_root
            ),
            "/mnt/MainStorage/StorageDataset/Music/Artist/Album/01.flac",
        )

    def test_unrelated_path_is_not_rewritten(self) -> None:
        self.assertEqual(
            host_music_path("/data/file.txt", self.music_root, self.host_root),
            "/data/file.txt",
        )

    def test_review_keeps_operational_path_and_adds_display_path(self) -> None:
        review = {
            "albums": [
                {
                    "folder": "/music/Artist/Album",
                    "folders": ["/music/Artist/Album"],
                    "tracks": [{"path": "/music/Artist/Album/01.flac"}],
                }
            ]
        }
        decorate_review_paths(review, self.music_root, self.host_root)
        album = review["albums"][0]
        track = album["tracks"][0]
        self.assertEqual(album["folder"], "/music/Artist/Album")
        self.assertEqual(
            album["display_folder"],
            "/mnt/MainStorage/StorageDataset/Music/Artist/Album",
        )
        self.assertEqual(track["path"], "/music/Artist/Album/01.flac")
        self.assertEqual(
            track["display_path"],
            "/mnt/MainStorage/StorageDataset/Music/Artist/Album/01.flac",
        )

    def test_issue_and_job_report_paths_are_decorated(self) -> None:
        issues = [
            {
                "folder": "/music/Artist/Album",
                "folders": ["/music/Artist/Album"],
                "affected_tracks": [{"path": "/music/Artist/Album/01.flac"}],
            }
        ]
        decorate_issue_paths(issues, self.music_root, self.host_root)
        self.assertTrue(
            issues[0]["affected_tracks"][0]["display_path"].startswith(
                "/mnt/MainStorage/StorageDataset/Music/"
            )
        )

        report = {"files": [{"path": "/music/Artist/Album/01.flac"}]}
        decorate_job_report_paths(report, self.music_root, self.host_root)
        self.assertEqual(
            report["files"][0]["display_path"],
            "/mnt/MainStorage/StorageDataset/Music/Artist/Album/01.flac",
        )


if __name__ == "__main__":
    unittest.main()
