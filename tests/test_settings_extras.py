from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db
from app.settings_extras import (
    DEFAULT_DAILY_SCAN_TIME,
    DEFAULT_RESERVE_BYTES,
    build_settings_extras_router,
    configure_daily_scan_job,
    configured_daily_scan_time,
    normalize_daily_scan_time,
)


class _IdleScanner:
    def snapshot(self) -> dict[str, bool]:
        return {"running": False}


class _IdleJobManager:
    def is_running(self) -> bool:
        return False


class SettingsExtrasTests(unittest.TestCase):
    def test_daily_scan_time_validation(self) -> None:
        self.assertEqual(normalize_daily_scan_time("07:45"), ("07:45", 7, 45))
        self.assertEqual(normalize_daily_scan_time("23:59"), ("23:59", 23, 59))
        for value in ("7:45", "24:00", "10:60", "nope", "10:00:00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_daily_scan_time(value)

    def test_configure_daily_scan_job_uses_persisted_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "settings.db"
            db.init(db_path)
            db.set_setting(db_path, "daily_scan_time", "07:45")
            scheduler = BackgroundScheduler(timezone="America/Indiana/Indianapolis")
            try:
                result = configure_daily_scan_job(scheduler, lambda: None, db_path)
                self.assertEqual(result["daily_scan_time"], "07:45")
                job = scheduler.get_job("daily-library-scan")
                self.assertIsNotNone(job)
                self.assertIn("hour='7'", str(job.trigger))
                self.assertIn("minute='45'", str(job.trigger))
            finally:
                if scheduler.running:
                    scheduler.shutdown(wait=False)

    def test_schedule_api_persists_and_reset_preserves_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "settings.db"
            db.init(db_path)
            db.set_setting(db_path, "exclude_paths", ["/music/Archive"])
            db.set_setting(db_path, "exclude_globs", ["*/Samples/*"])
            db.set_setting(db_path, "free_space_reserve_bytes", 99 * 1024**3)
            db.set_setting(db_path, "read_only_mode", True)

            scheduler = BackgroundScheduler(timezone="America/Indiana/Indianapolis")
            app = FastAPI()
            app.include_router(
                build_settings_extras_router(
                    db_path=db_path,
                    timezone="America/Indiana/Indianapolis",
                    scheduler=scheduler,
                    daily_scan=lambda: None,
                    scanner=_IdleScanner(),
                    job_manager=_IdleJobManager(),
                )
            )
            client = TestClient(app)
            try:
                response = client.post("/api/settings/schedule", json={"daily_scan_time": "06:30"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["daily_scan_time"], "06:30")
                self.assertEqual(configured_daily_scan_time(db_path), ("06:30", 6, 30))

                blocked = client.post("/api/settings/reset-defaults", json={"confirmed": True})
                self.assertEqual(blocked.status_code, 400)
                self.assertIn("Read-only", blocked.json()["detail"])

                reset = client.post(
                    "/api/settings/reset-defaults",
                    json={"confirmed": True, "confirmed_disable_read_only": True},
                )
                self.assertEqual(reset.status_code, 200)
                body = reset.json()
                self.assertEqual(body["daily_scan_time"], DEFAULT_DAILY_SCAN_TIME)
                self.assertEqual(body["free_space_reserve_bytes"], DEFAULT_RESERVE_BYTES)
                self.assertFalse(body["read_only_mode"])
                self.assertEqual(db.get_setting(db_path, "exclude_paths"), ["/music/Archive"])
                self.assertEqual(db.get_setting(db_path, "exclude_globs"), ["*/Samples/*"])
                self.assertEqual(body["preserved"]["exclude_paths"], 1)
                self.assertEqual(body["preserved"]["exclude_globs"], 1)
            finally:
                if scheduler.running:
                    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    unittest.main()
