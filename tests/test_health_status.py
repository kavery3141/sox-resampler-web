from __future__ import annotations

import unittest

from app.health_status import summarize_health


class HealthStatusTests(unittest.TestCase):
    def healthy(self, **overrides):
        values = {
            "music_exists": True,
            "music_readable": True,
            "music_writable": True,
            "data_exists": True,
            "data_writable": True,
            "db_ok": True,
            "stock_sox": "SoX v14.4.2",
            "ultra_sox": "SoX v14.4.2",
            "flac": "flac 1.4.2",
            "zfs": {"ok": True, "pool": "MainStorage", "state": "ONLINE"},
            "read_only_mode": False,
        }
        values.update(overrides)
        return summarize_health(**values)

    def test_all_required_components_are_conversion_ready(self) -> None:
        result = self.healthy()
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["conversion_ready"])
        self.assertEqual(result["health_reasons"], [])
        self.assertEqual(result["conversion_blockers"], [])

    def test_read_only_mode_keeps_service_healthy_but_blocks_conversion(self) -> None:
        result = self.healthy(read_only_mode=True)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["conversion_ready"])
        self.assertEqual(result["health_reasons"], [])
        self.assertIn("Read-only Scan Mode is enabled", result["conversion_blockers"])

    def test_nonwritable_music_blocks_conversion_without_hiding_read_health(self) -> None:
        result = self.healthy(music_writable=False)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["conversion_ready"])
        self.assertIn("Music root is not writable", result["conversion_blockers"])

    def test_degraded_pool_marks_service_degraded_and_conversion_blocked(self) -> None:
        result = self.healthy(
            zfs={
                "ok": False,
                "pool": "MainStorage",
                "state": "DEGRADED",
                "reason": "ZFS pool MainStorage is DEGRADED, not ONLINE",
            }
        )
        self.assertEqual(result["status"], "degraded")
        self.assertFalse(result["conversion_ready"])
        self.assertIn("DEGRADED", " ".join(result["health_reasons"]))

    def test_missing_ultra_backend_is_visible_and_blocks_conversion(self) -> None:
        result = self.healthy(ultra_sox=None)
        self.assertEqual(result["status"], "degraded")
        self.assertFalse(result["conversion_ready"])
        self.assertIn("Ultra 37 SoX backend is unavailable", result["health_reasons"])

    def test_enabled_cpu_cap_without_runtime_blocks_conversion_only(self) -> None:
        result = self.healthy(cpu_limit_percent=50, cpu_limiter_available=False)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["conversion_ready"])
        self.assertIn("cpulimit runtime is unavailable", " ".join(result["conversion_blockers"]))


if __name__ == "__main__":
    unittest.main()
