from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app import db
from app.resource_control import (
    ResourceSettingsRequest,
    build_resource_control_router,
    configured_cpu_limit,
    resource_status,
)


class DummyJobs:
    def __init__(self, active: int | None = None) -> None:
        self.active = active

    def active_job_id(self) -> int | None:
        return self.active


class ResourceControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "data" / "test.db"
        db.init(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def post_endpoint(self, active: int | None = None):
        router = build_resource_control_router(
            self.db_path,
            "America/Indiana/Indianapolis",
            DummyJobs(active),
        )
        return next(
            route.endpoint
            for route in router.routes
            if getattr(route, "path", None) == "/api/settings/resources"
            and "POST" in getattr(route, "methods", set())
        )

    def test_default_is_uncapped(self) -> None:
        with patch("app.resource_control.shutil.which", return_value="/usr/bin/cpulimit"):
            status = resource_status(self.db_path)
        self.assertIsNone(configured_cpu_limit(self.db_path))
        self.assertFalse(status["enabled"])
        self.assertEqual(status["scope"], "per-worker-sox")

    def test_enabling_and_disabling_persists_setting(self) -> None:
        endpoint = self.post_endpoint(active=12)
        with patch("app.resource_control.shutil.which", return_value="/usr/bin/cpulimit"):
            enabled = endpoint(ResourceSettingsRequest(cpu_limit_percent=60))
            self.assertEqual(enabled["cpu_limit_percent"], 60)
            self.assertEqual(enabled["active_job_id"], 12)
            disabled = endpoint(ResourceSettingsRequest(cpu_limit_percent=None))
        self.assertIsNone(disabled["cpu_limit_percent"])
        self.assertIsNone(configured_cpu_limit(self.db_path))

    def test_enabling_without_runtime_is_rejected(self) -> None:
        endpoint = self.post_endpoint()
        with patch("app.resource_control.shutil.which", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                endpoint(ResourceSettingsRequest(cpu_limit_percent=50))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIsNone(configured_cpu_limit(self.db_path))

    def test_request_bounds_are_validated(self) -> None:
        with self.assertRaises(ValidationError):
            ResourceSettingsRequest(cpu_limit_percent=9)
        with self.assertRaises(ValidationError):
            ResourceSettingsRequest(cpu_limit_percent=101)


if __name__ == "__main__":
    unittest.main()
