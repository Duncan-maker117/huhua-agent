import sys
import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Settings


class RuntimeConfigTests(unittest.TestCase):
    def test_production_requires_safe_origin_and_access(self):
        valid = Settings(_env_file=None, APP_ENV="production", APP_ORIGIN="https://resume.example.test", REQUIRE_ACCOUNT=True, AUTH_COOKIE_SECURE=True, ALLOW_INSECURE_LOCAL_STORAGE=False)
        valid.validate_runtime()
        for changes in ({"APP_ORIGIN": ""}, {"APP_ORIGIN": "http://resume.example.test"},
                        {"APP_ORIGIN": "https://resume.example.test/wrong-path"},
                        {"REQUIRE_ACCOUNT": False}, {"AUTH_COOKIE_SECURE": False},
                        {"ALLOW_INSECURE_LOCAL_STORAGE": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                valid.model_copy(update=changes).validate_runtime()

    def test_limits_must_be_positive(self):
        for field in ("MODEL_MAX_CONCURRENT", "ACCOUNT_DAILY_TURN_LIMIT", "CHAT_TIMEOUT_SECONDS", "ARCHIVE_POLL_SECONDS"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                Settings(_env_file=None, **{field: 0})


class RuntimeLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_releases_concurrency_slot(self):
        from app.services.runtime_limits import model_slot
        settings = SimpleNamespace(MODEL_MAX_CONCURRENT=1, CHAT_TIMEOUT_SECONDS=.02)
        with patch("app.services.runtime_limits.get_settings", return_value=settings):
            with self.assertRaises(TimeoutError):
                async with model_slot():
                    await asyncio.sleep(.1)
            async with model_slot():
                pass

    async def test_full_concurrency_reports_busy_without_entering(self):
        from app.services.runtime_limits import model_slot
        from fastapi import HTTPException
        settings = SimpleNamespace(MODEL_MAX_CONCURRENT=1, CHAT_TIMEOUT_SECONDS=5)
        with patch("app.services.runtime_limits.get_settings", return_value=settings):
            async with model_slot():
                with self.assertRaises(HTTPException) as raised:
                    async with model_slot():
                        self.fail("A full slot must not enter a second generation")
                self.assertEqual(raised.exception.status_code, 503)
            async with model_slot():
                pass
