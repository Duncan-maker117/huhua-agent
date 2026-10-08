"""Offline Resend HTTPS contract and shared-budget regressions."""

import base64
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402

with patch("app.config.get_settings", return_value=Settings(_env_file=None, DATABASE_URL="sqlite:///:memory:", LLM_API_KEY="")):
    from app.models.account import AuthRateBucket, LoginChallenge
    from app.services.account_service import AccountService, ResendTransport, SMTPTransport
    from app.services.data_crypto import CryptoConfigurationError, DataCrypto


ACCEPTED_ID = "ea590efd-3c55-46a1-bf8c-31a5a8436685"


class ResendTransportTest(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(EMAIL_PROVIDER="resend", RESEND_API_KEY="private-test-key",
                                        RESEND_FROM="sender@example.test")
        self.transport = ResendTransport(self.settings)
        self.client = MagicMock()
        self.client.post.return_value = httpx.Response(200, json={"id": ACCEPTED_ID})
        self.client_patch = patch("app.services.account_service.httpx.Client")
        self.constructor = self.client_patch.start()
        self.constructor.return_value.__enter__.return_value = self.client
        self.addCleanup(self.client_patch.stop)

    def test_fixed_https_tls_timeout_and_no_redirects(self):
        self.transport.send("recipient@example.test", "314159")
        self.constructor.assert_called_once_with(verify=True, timeout=10.0, follow_redirects=False)
        args, kwargs = self.client.post.call_args
        self.assertEqual(args, ("https://api.resend.com/emails",))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer private-test-key")
        self.assertEqual(kwargs["json"]["from"], "sender@example.test")
        self.assertEqual(kwargs["json"]["to"], ["recipient@example.test"])
        self.assertEqual(kwargs["json"]["subject"], "胡话简历登录验证码")
        self.assertIn("314159", kwargs["json"]["text"])
        self.assertEqual(self.client.post.call_count, 1)

    def test_any_success_status_needs_valid_provider_id(self):
        for status in (200, 201, 202):
            with self.subTest(status=status):
                self.client.post.return_value = httpx.Response(status, json={"id": ACCEPTED_ID})
                self.assertIsNone(self.transport.send("recipient@example.test", "314159"))

    def assert_sanitized_failure(self):
        with self.assertRaises(HTTPException) as caught:
            self.transport.send("recipient@example.test", "314159")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertTrue(caught.exception.__suppress_context__)
        for private in ("private-test-key", "recipient@example.test", "314159", "provider-private-response"):
            self.assertNotIn(private, caught.exception.detail)

    def test_auth_permission_rate_and_server_errors_do_not_retry_or_leak(self):
        for status in (401, 403, 429, 500, 503):
            with self.subTest(status=status):
                self.client.post.reset_mock()
                self.client.post.return_value = httpx.Response(status, json={
                    "message": "private-test-key recipient@example.test 314159 provider-private-response"})
                self.assert_sanitized_failure()
                self.assertEqual(self.client.post.call_count, 1)

    def test_redirect_is_rejected_without_following_credentials(self):
        self.client.post.return_value = httpx.Response(307, headers={"Location": "https://untrusted.example.test"})
        self.assert_sanitized_failure()
        self.assertEqual(self.client.post.call_count, 1)

    def test_network_and_tls_errors_do_not_retry_or_leak(self):
        for error in (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError):
            with self.subTest(error=error):
                self.client.post.reset_mock()
                self.client.post.side_effect = error("private-test-key recipient@example.test 314159")
                self.assert_sanitized_failure()
                self.assertEqual(self.client.post.call_count, 1)

    def test_malformed_success_never_claims_acceptance(self):
        responses = [
            httpx.Response(204), httpx.Response(200, text="provider-private-response"),
            *[httpx.Response(200, json=value) for value in (
                {}, None, [], {"id": ""}, {"id": "   "}, {"id": 123},
                {"id": "invalid-id"}, {"id": {"private": "314159"}},
            )],
        ]
        for response in responses:
            with self.subTest(response=response):
                self.client.post.return_value = response
                self.assert_sanitized_failure()

    def test_safe_diagnostics_and_missing_configuration_do_not_connect(self):
        status = self.transport.configuration_status()
        self.assertEqual(status, {"available": True, "missing": [], "invalid": [],
                                  "transport": "resend_https", "provider": "resend"})
        serialized = json.dumps(status)
        self.assertNotIn(self.settings.RESEND_API_KEY, serialized)
        self.assertNotIn(self.settings.RESEND_FROM, serialized)
        self.settings.RESEND_API_KEY = ""
        self.settings.RESEND_FROM = ""
        self.assertEqual(self.transport.configuration_status()["missing"], ["RESEND_API_KEY", "RESEND_FROM"])
        with self.assertRaises(HTTPException) as caught:
            self.transport.send("recipient@example.test", "314159")
        self.assertEqual(caught.exception.status_code, 503)
        self.constructor.assert_not_called()

    def test_provider_selection_and_injected_transport(self):
        crypto = DataCrypto({"test": os.urandom(32)}, "test")
        self.settings.ACCOUNT_SECRET = base64.b64encode(os.urandom(32)).decode()
        service = AccountService(None, self.settings, crypto=crypto)
        self.assertIsInstance(service.transport, ResendTransport)
        self.assertEqual(service.mail_configuration_status()["provider"], "resend")
        self.settings.EMAIL_PROVIDER = "smtp"
        self.assertIsInstance(AccountService(None, self.settings, crypto=crypto).transport, SMTPTransport)
        injected = object()
        self.assertIs(AccountService(None, self.settings, crypto=crypto, transport=injected).transport, injected)
        self.settings.EMAIL_PROVIDER = "unknown"
        with self.assertRaises(CryptoConfigurationError):
            AccountService(None, self.settings, crypto=crypto)
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, EMAIL_PROVIDER="unknown")
        self.assertEqual(Settings(_env_file=None).EMAIL_PROVIDER, "smtp")

    def test_failure_consumes_shared_budget_and_transport_switch_cannot_reset_it(self):
        with tempfile.TemporaryDirectory(prefix="huhua-resend-budget-") as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'auth.db'}")
            self.addCleanup(engine.dispose)
            AuthRateBucket.__table__.create(engine)
            LoginChallenge.__table__.create(engine)
            factory = sessionmaker(bind=engine)
            crypto = DataCrypto({"test": os.urandom(32)}, "test")
            self.settings.ACCOUNT_SECRET = base64.b64encode(os.urandom(32)).decode()
            self.settings.AUTH_EMAIL_DAILY_LIMIT = 1
            self.settings.AUTH_EMAIL_MONTHLY_LIMIT = 3
            self.client.post.return_value = httpx.Response(403, json={"message": "private provider response"})
            service = AccountService(factory, self.settings, crypto=crypto, clock=lambda: datetime(2026, 10, 4, 12))
            with self.assertRaises(HTTPException) as caught:
                service.start("recipient@example.test", client_ip="first-client")
            self.assertEqual(caught.exception.status_code, 503)
            with factory() as db:
                self.assertEqual(db.execute(select(LoginChallenge)).scalars().all(), [])
            self.settings.EMAIL_PROVIDER = "smtp"
            service = AccountService(factory, self.settings, crypto=crypto, clock=lambda: datetime(2026, 10, 4, 12))
            with patch.object(service.transport, "available", return_value=True), patch.object(service.transport, "send") as send:
                with self.assertRaises(HTTPException) as caught:
                    service.start("another@example.test", client_ip="second-client")
                self.assertEqual(caught.exception.status_code, 429)
                send.assert_not_called()
            self.assertEqual(self.client.post.call_count, 1)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
