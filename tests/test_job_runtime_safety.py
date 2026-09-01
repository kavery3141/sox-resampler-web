from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db
from app.jobs import ConversionJobManager


HEALTHY_ZFS = {"ok": True, "pool": "MainStorage", "reason": None, "detail": "pool 'MainStorage' is healthy"}


class RuntimeSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.music = root / "music"
        self.music.mkdir()
        self.db_path = root / "data" / "test.db"
        db.init(self.db_path)
        self.manager = ConversionJobManager(self.db_path, self.music, "America/Indiana/Indianapolis")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_unhealthy_zfs_pauses_before_new_file(self) -> None:
        unhealthy = {
            "ok": False,
            "pool": "MainStorage",
            "reason": "ZFS pool health is not confirmed healthy: pool is DEGRADED",
            "detail": "pool is DEGRADED",
        }
        with patch("app.jobs.zfs_pool_health", return_value=unhealthy):
            reason = self.manager._runtime_gate(0)
        self.assertIsNotNone(reason)
        self.assertIn("ZFS pool health", reason)

    def test_read_only_mode_pauses_before_new_file(self) -> None:
        db.set_setting(self.db_path, "read_only_mode", True)
        with patch("app.jobs.zfs_pool_health", return_value=HEALTHY_ZFS):
            reason = self.manager._runtime_gate(0)
        self.assertIsNotNone(reason)
        self.assertIn("Read-only Scan Mode", reason)

    def test_free_space_reserve_is_checked_before_new_file(self) -> None:
        db.set_setting(self.db_path, "free_space_reserve_bytes", 10_000)
        fake = type("Usage", (), {"total": 100_000, "used": 95_000, "free": 5_000})()
        with patch("app.jobs.zfs_pool_health", return_value=HEALTHY_ZFS), patch(
            "app.jobs.shutil.disk_usage", return_value=fake
        ):
            reason = self.manager._runtime_gate(1_000)
        self.assertIsNotNone(reason)
        self.assertIn("Free space", reason)

    def test_runtime_gate_allows_work_when_storage_is_safe(self) -> None:
        db.set_setting(self.db_path, "read_only_mode", False)
        db.set_setting(self.db_path, "free_space_reserve_bytes", 10_000)
        fake = type("Usage", (), {"total": 100_000, "used": 10_000, "free": 90_000})()
        with patch("app.jobs.zfs_pool_health", return_value=HEALTHY_ZFS), patch(
            "app.jobs.shutil.disk_usage", return_value=fake
        ):
            reason = self.manager._runtime_gate(20_000)
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
