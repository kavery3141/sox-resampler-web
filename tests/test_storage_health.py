from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.storage_health import zfs_pool_health


class StorageHealthTests(unittest.TestCase):
    def _write_state(self, root: Path, pool: str, state: str) -> None:
        path = root / pool / "state"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(state + "\n", encoding="utf-8")

    def test_online_kstat_is_healthy_without_invoking_zpool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_state(root, "MainStorage", "ONLINE")
            with patch.dict(os.environ, {"ZFS_KSTAT_ROOT": str(root), "ZFS_POOL": "MainStorage"}, clear=False), \
                 patch("app.storage_health.subprocess.run") as run:
                result = zfs_pool_health()
            self.assertTrue(result["ok"])
            self.assertEqual(result["state"], "ONLINE")
            self.assertEqual(result["source"], "kstat")
            run.assert_not_called()

    def test_degraded_kstat_fails_closed_without_invoking_zpool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_state(root, "MainStorage", "DEGRADED")
            with patch.dict(os.environ, {"ZFS_KSTAT_ROOT": str(root), "ZFS_POOL": "MainStorage"}, clear=False), \
                 patch("app.storage_health.subprocess.run") as run:
                result = zfs_pool_health()
            self.assertFalse(result["ok"])
            self.assertEqual(result["state"], "DEGRADED")
            self.assertIn("not ONLINE", result["reason"])
            run.assert_not_called()

    def test_missing_kstat_falls_back_to_zpool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = Mock(
                returncode=0,
                stdout="pool 'MainStorage' is healthy\n",
                stderr="",
            )
            with patch.dict(os.environ, {"ZFS_KSTAT_ROOT": tmp, "ZFS_POOL": "MainStorage"}, clear=False), \
                 patch("app.storage_health.subprocess.run", return_value=completed) as run:
                result = zfs_pool_health()
            self.assertTrue(result["ok"])
            self.assertEqual(result["source"], "zpool")
            self.assertEqual(result["state"], "ONLINE")
            run.assert_called_once()

    def test_missing_kstat_and_failed_zpool_remains_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = Mock(
                returncode=1,
                stdout="",
                stderr="cannot open 'MainStorage': no such pool\n",
            )
            with patch.dict(os.environ, {"ZFS_KSTAT_ROOT": tmp, "ZFS_POOL": "MainStorage"}, clear=False), \
                 patch("app.storage_health.subprocess.run", return_value=completed):
                result = zfs_pool_health()
            self.assertFalse(result["ok"])
            self.assertEqual(result["source"], "zpool")
            self.assertIn("not confirmed healthy", result["reason"])


if __name__ == "__main__":
    unittest.main()
