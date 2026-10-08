"""SMTP acceptance and durable calendar budgets, with no external mail sent."""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import smtplib
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402

with patch("app.config.get_settings", return_value=Settings(_env_file=None, DATABASE_URL="sqlite:///:memory:", LLM_API_KEY="")):
    from app.models.account import AuthRateBucket, LoginChallenge
    from app.services.account_service import AccountService, SMTPTransport
    from app.services.data_crypto import CryptoConfigurationError, DataCrypto


class RecordingMail:
    def __init__(self):
        self.calls = []
        self.fail = False

    def available(self):
        return True

    def send(self, email, code):
        self.calls.append((email, code))
        if self.fail:
            raise HTTPException(503, "验证码暂时发送失败，请稍后重试")


class EmailBudgetTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="huhua-email-budget-")
        self.engine = create_engine(f"sqlite:///{Path(self.directory.name) / 'auth.db'}",
                                    connect_args={"check_same_thread": False, "timeout": 20})
        AuthRateBucket.__table__.create(self.engine)
        LoginChallenge.__table__.create(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.crypto = DataCrypto({"test": os.urandom(32)}, "test")
        self.settings = SimpleNamespace(ACCOUNT_SECRET=base64.b64encode(os.urandom(32)).decode(),
                                        AUTH_EMAIL_DAILY_LIMIT=3, AUTH_EMAIL_MONTHLY_LIMIT=5)
        self.clock = datetime(2026, 10, 31, 20, 0, 0)
        self.mail = RecordingMail()
        self.service = self.new_service()

    def tearDown(self):
        self.engine.dispose()
        self.directory.cleanup()

    def new_service(self):
        return AccountService(self.factory, self.settings, crypto=self.crypto,
                              transport=self.mail, clock=lambda: self.clock)

    def start(self, suffix, service=None):
        return (service or self.service).start(f"person{suffix}@example.test", client_ip=f"client-{suffix}")

    def test_positive_settings_and_default_safety_margin(self):
        defaults = Settings(_env_file=None)
        self.assertEqual((defaults.AUTH_EMAIL_DAILY_LIMIT, defaults.AUTH_EMAIL_MONTHLY_LIMIT), (90, 2800))
        for name in ("AUTH_EMAIL_DAILY_LIMIT", "AUTH_EMAIL_MONTHLY_LIMIT"):
            for value in (0, -1):
                with self.assertRaises(ValidationError):
                    Settings(_env_file=None, **{name: value})
            setattr(self.settings, name, 0)
            with self.assertRaises(CryptoConfigurationError):
                self.new_service()
            setattr(self.settings, name, 3)

    def test_daily_global_budget_survives_restart_and_has_exact_retry(self):
        for number in range(3):
            response = self.start(number)
            self.assertEqual(response["delivery_status"], "provider_accepted")
            self.assertNotIn(self.mail.calls[-1][1], json.dumps(response))
        with self.assertRaises(HTTPException) as caught:
            self.start("blocked", self.new_service())
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.headers["Retry-After"], str(4 * 3600))
        self.assertIn("2026-11-01 00:00:00 UTC", caught.exception.detail)
        self.assertEqual(len(self.mail.calls), 3)
        self.clock = datetime(2026, 11, 1)
        self.assertTrue(self.start("next-day")["sent"])

    def test_monthly_budget_is_shared_across_days_and_accounts(self):
        self.settings.AUTH_EMAIL_DAILY_LIMIT = 10
        self.settings.AUTH_EMAIL_MONTHLY_LIMIT = 2
        self.clock = datetime(2026, 10, 29, 12)
        self.start(1)
        self.clock = datetime(2026, 10, 30, 12)
        self.start(2)
        self.clock = datetime(2026, 10, 31, 12)
        with self.assertRaises(HTTPException) as caught:
            self.start(3)
        self.assertIn("本月", caught.exception.detail)
        self.assertEqual(caught.exception.headers["Retry-After"], str(12 * 3600))
        # Rejected calls reserve neither a daily attempt nor a challenge.
        with self.factory() as db:
            daily = db.execute(select(AuthRateBucket).where(
                AuthRateBucket.expires_at == datetime(2026, 11, 1))).scalars().all()
            self.assertEqual(sorted(row.count for row in daily), [2])
            self.assertIsNone(db.get(LoginChallenge, self.service.email_index("person3@example.test")))
        self.settings.AUTH_EMAIL_MONTHLY_LIMIT = 3
        self.assertTrue(self.start(3)["sent"])

    def test_utc_boundary_ignores_local_date_and_handles_year_rollover(self):
        self.settings.AUTH_EMAIL_MONTHLY_LIMIT = 1
        self.clock = datetime(2026, 12, 31, 20, 0)
        self.start(1)
        self.clock = datetime(2027, 1, 1, 7, 59, 59, tzinfo=timezone(timedelta(hours=8)))
        with self.assertRaises(HTTPException) as caught:
            self.start(2)
        self.assertEqual(caught.exception.headers["Retry-After"], "1")
        self.assertIn("2027-01-01 00:00:00 UTC", caught.exception.detail)
        self.clock += timedelta(seconds=1)
        self.assertTrue(self.start(2)["sent"])

    def test_leap_february_uses_calendar_month(self):
        self.settings.AUTH_EMAIL_MONTHLY_LIMIT = 1
        self.clock = datetime(2028, 2, 28, 12)
        self.start(1)
        self.clock = datetime(2028, 2, 29, 12)
        with self.assertRaises(HTTPException) as caught:
            self.start(2)
        self.assertIn("2028-03-01 00:00:00 UTC", caught.exception.detail)
        self.assertEqual(caught.exception.headers["Retry-After"], str(12 * 3600))
        self.clock = datetime(2028, 3, 1)
        self.assertTrue(self.start(2)["sent"])

    def test_provider_failure_consumes_budget_and_discards_code(self):
        self.settings.AUTH_EMAIL_DAILY_LIMIT = 1
        self.mail.fail = True
        with self.assertRaises(HTTPException) as caught:
            self.start(1)
        self.assertEqual(caught.exception.status_code, 503)
        with self.factory() as db:
            self.assertEqual(db.execute(select(LoginChallenge)).scalars().all(), [])
        self.mail.fail = False
        with self.assertRaises(HTTPException) as caught:
            self.start(2, self.new_service())
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(len(self.mail.calls), 1)

    def test_concurrent_global_budget_allows_exactly_configured_attempts(self):
        self.settings.AUTH_EMAIL_DAILY_LIMIT = 4
        self.settings.AUTH_EMAIL_MONTHLY_LIMIT = 20

        def attempt(number):
            try:
                self.start(number, self.new_service())
                return 200
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(attempt, range(12)))
        self.assertEqual(results.count(200), 4)
        self.assertEqual(results.count(429), 8)
        self.assertEqual(len(self.mail.calls), 4)

    def test_concurrent_monthly_budget_prevents_overshoot(self):
        self.settings.AUTH_EMAIL_DAILY_LIMIT = 20
        self.settings.AUTH_EMAIL_MONTHLY_LIMIT = 3

        def attempt(number):
            try:
                self.start(number, self.new_service())
                return 200
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(results.count(200), 3)
        self.assertEqual(results.count(429), 5)
        self.assertEqual(len(self.mail.calls), 3)


class SMTPTransportTest(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(SMTP_HOST="smtp.example.test", SMTP_PORT=587,
                                        SMTP_USERNAME="private-user", SMTP_PASSWORD="private-token",
                                        SMTP_FROM="login@example.test", SMTP_STARTTLS=True)
        self.transport = SMTPTransport(self.settings)

    def test_diagnostics_reveal_only_field_names_and_do_not_claim_connectivity(self):
        status = self.transport.configuration_status()
        self.assertEqual(status, {"available": True, "missing": [], "invalid": [], "transport": "smtp_starttls", "provider": "smtp"})
        output = json.dumps(status)
        for value in (self.settings.SMTP_HOST, self.settings.SMTP_USERNAME, self.settings.SMTP_PASSWORD, self.settings.SMTP_FROM):
            self.assertNotIn(value, output)
        self.settings.SMTP_PASSWORD = ""
        self.assertEqual(self.transport.configuration_status()["missing"], ["SMTP_PASSWORD"])
        self.assertFalse(self.transport.available())
        self.settings.SMTP_STARTTLS = False
        self.assertEqual(self.transport.configuration_status()["invalid"], ["SMTP_STARTTLS"])

    def test_requires_authenticated_tls_and_does_not_connect_when_unconfigured(self):
        self.settings.SMTP_STARTTLS = False
        with patch("app.services.account_service.smtplib.SMTP") as smtp:
            with self.assertRaises(HTTPException) as caught:
                self.transport.send("person@example.test", "123456")
            self.assertEqual(caught.exception.status_code, 503)
            smtp.assert_not_called()

    def test_tls_precedes_auth_and_submission(self):
        smtp = MagicMock()
        smtp.send_message.return_value = {}
        with patch("app.services.account_service.smtplib.SMTP") as connection:
            connection.return_value.__enter__.return_value = smtp
            self.transport.send("person@example.test", "123456")
        self.assertEqual([call[0] for call in smtp.mock_calls], ["starttls", "login", "send_message"])
        context = smtp.starttls.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(smtp.send_message.call_args.args[0]["To"], "person@example.test")

    def test_provider_errors_are_sanitized_and_refusals_are_not_success(self):
        for refusal in (False, True):
            smtp = MagicMock()
            smtp.send_message.side_effect = None if refusal else smtplib.SMTPAuthenticationError(535, b"private-token 123456")
            smtp.send_message.return_value = {"person@example.test": (550, b"private provider reason")} if refusal else {}
            with patch("app.services.account_service.smtplib.SMTP") as connection:
                connection.return_value.__enter__.return_value = smtp
                with self.assertRaises(HTTPException) as caught:
                    self.transport.send("person@example.test", "123456")
            self.assertEqual(caught.exception.status_code, 503)
            for secret in ("private-token", "123456", "person@example.test", "private provider reason"):
                self.assertNotIn(secret, caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
