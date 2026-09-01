from __future__ import annotations

import unittest
from unittest.mock import patch

from app.update_check import (
    check_for_updates,
    newer_release_available,
    reset_update_cache_for_tests,
)


class UpdateCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_update_cache_for_tests()

    def test_semver_comparison_handles_development_build(self) -> None:
        self.assertTrue(newer_release_available("0.7.0-dev", "0.7.0"))
        self.assertTrue(newer_release_available("0.7.0", "0.8.0"))
        self.assertFalse(newer_release_available("0.8.0", "0.7.9"))
        self.assertFalse(newer_release_available("0.8.0", "0.8.0"))
        self.assertIsNone(newer_release_available("dev", "0.8.0"))

    def test_available_release_is_reported_without_install_action(self) -> None:
        with patch(
            "app.update_check._fetch_latest_release",
            return_value={
                "check_status": "ok",
                "latest_version": "0.8.0",
                "release_url": "https://github.com/kavery3141/sox-resampler-web/releases/tag/v0.8.0",
                "published_at": "2026-09-01T20:00:00Z",
                "release_name": "v0.8.0",
                "prerelease": False,
                "draft": False,
            },
        ):
            result = check_for_updates("0.7.0")
        self.assertTrue(result["update_available"])
        self.assertEqual(result["comparison_status"], "update-available")
        self.assertFalse(result["automatic_install"])

    def test_unavailable_release_check_is_nonfatal(self) -> None:
        with patch(
            "app.update_check._fetch_latest_release",
            return_value={"check_status": "unavailable", "reason": "No published GitHub release is available yet"},
        ):
            result = check_for_updates("0.7.0-dev")
        self.assertIsNone(result["update_available"])
        self.assertEqual(result["comparison_status"], "unavailable")
        self.assertIn("No published", result["reason"])

    def test_successful_result_is_cached_until_forced(self) -> None:
        payload = {
            "check_status": "ok",
            "latest_version": "0.7.0",
            "release_url": None,
            "published_at": None,
            "release_name": "v0.7.0",
            "prerelease": False,
            "draft": False,
        }
        with patch("app.update_check._fetch_latest_release", return_value=payload) as fetch:
            first = check_for_updates("0.7.0")
            second = check_for_updates("0.7.0")
            forced = check_for_updates("0.7.0", force=True)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(first["comparison_status"], "up-to-date")
        self.assertEqual(second["comparison_status"], "up-to-date")
        self.assertEqual(forced["comparison_status"], "up-to-date")


if __name__ == "__main__":
    unittest.main()
