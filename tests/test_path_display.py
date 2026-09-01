from __future__ import annotations

import unittest
from pathlib import Path

from app.issues import render_issues_csv, render_issues_txt
from app.path_display import (
    decorate_issue_paths,
    decorate_job_report_paths,
    decorate_review_paths,
    host_music_path,
    internal_music_path,
)
from app.reports import render_job_csv, render_job_txt


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

    def test_true_nas_path_maps_back_to_internal_music_path(self) -> None:
        self.assertEqual(
            internal_music_path(
                "/mnt/MainStorage/StorageDataset/Music/Artist/Album",
                self.music_root,
                self.host_root,
            ),
            "/music/Artist/Album",
        )
        self.assertEqual(
            internal_music_path("Artist/Album", self.music_root, self.host_root),
            "/music/Artist/Album",
        )

    def test_unrelated_path_is_not_rewritten(self) -> None:
        self.assertEqual(
            host_music_path("/data/file.txt", self.music_root, self.host_root),
            "/data/file.txt",
        )
        self.assertEqual(
            internal_music_path("/data/file.txt", self.music_root, self.host_root),
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

    def test_exports_prefer_true_nas_display_paths(self) -> None:
        issues = [{
            "severity": "blocking",
            "issue_type": "missing_album",
            "albumartist": "Artist",
            "album": "Album",
            "folder": "/music/Artist/Album",
            "folders": ["/music/Artist/Album"],
            "summary": "ALBUM missing",
            "affected_tracks": [{"path": "/music/Artist/Album/01.flac", "filename": "01.flac", "value": "(missing)"}],
        }]
        decorate_issue_paths(issues, self.music_root, self.host_root)
        txt = render_issues_txt(issues, "America/Indiana/Indianapolis")
        csv_text = render_issues_csv(issues)
        self.assertIn("/mnt/MainStorage/StorageDataset/Music/Artist/Album/01.flac", txt)
        self.assertIn("/mnt/MainStorage/StorageDataset/Music/Artist/Album/01.flac", csv_text)

        report = {
            "job_id": 1, "timezone": "America/Indiana/Indianapolis", "status": "completed",
            "created_at": "", "started_at": "", "finished_at": "", "profile_id": "test",
            "profile": {}, "workers": 1, "operational": {}, "events": [], "job_error": None,
            "totals": {"files": 1, "completed": 1, "failed": 0, "remaining": 0, "source_bytes": 1, "final_bytes": 1, "savings_bytes": 0},
            "files": [{"status": "completed", "albumartist": "Artist", "album": "Album", "path": "/music/Artist/Album/01.flac", "source_bytes": 1, "final_bytes": 1, "savings_bytes": 0}],
        }
        decorate_job_report_paths(report, self.music_root, self.host_root)
        self.assertIn("/mnt/MainStorage/StorageDataset/Music/Artist/Album/01.flac", render_job_txt(report))
        self.assertIn("/mnt/MainStorage/StorageDataset/Music/Artist/Album/01.flac", render_job_csv(report))


if __name__ == "__main__":
    unittest.main()
