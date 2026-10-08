import asyncio
import io
import sys
import tempfile
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from app.config import Settings  # noqa: E402

# Imports may construct an engine but cannot select a developer DB or read .env.
with patch("app.config.get_settings", return_value=Settings(
    _env_file=None, DATABASE_URL="sqlite:///:memory:", CHECKPOINT_DB_PATH=":memory:",
    LLM_API_KEY="", ENABLE_RAG=False, REQUIRE_ACCOUNT=False, ALLOW_INSECURE_LOCAL_STORAGE=True,
)):
    import main

from app.models.models import ResumeSession  # noqa: E402
from app.services.file_extractor import FileLimitError, extract_text  # noqa: E402
from app.services.session_store import (  # noqa: E402
    ensure_resume_session,
    load_resume_session,
    save_resume_session,
    session_can_read_checkpoint,
    session_is_blocked,
    SessionStorageUnavailable,
)


class PrivacyRegressionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="huhua-privacy-test-")
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(
            _env_file=None, DATABASE_URL=f"sqlite:///{Path(self.directory.name) / 'sessions.sqlite3'}",
            CHECKPOINT_DB_PATH=str(Path(self.directory.name) / "checkpoints.sqlite3"),
            LLM_API_KEY="", ENABLE_RAG=False, APP_ENV="local", REQUIRE_ACCOUNT=False,
            ALLOW_INSECURE_LOCAL_STORAGE=True, DATA_ENCRYPTION_KEYS="{}", DATA_ENCRYPTION_ACTIVE_KEY="",
            SESSION_RETENTION_DAYS=7, APP_ORIGIN="http://testserver",
        )
        self.engine = create_engine(self.settings.DATABASE_URL, connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        self.factory = sessionmaker(bind=self.engine)
        patches = [patch("app.database.engine", self.engine), patch.object(main, "engine", self.engine)]
        for module in ("app.database", "app.services.session_store", "app.services.conversation_store",
                       "app.services.profile_bridge", "app.services.runtime_limits", "app.services.resume_suggestions", "main"):
            patches.append(patch(module + ".SessionLocal", self.factory))
        for module in ("app.config", "app.database", "app.services.session_store", "app.services.runtime_limits",
                       "app.services.resume_suggestions", "app.api.chat", "app.api.conversations", "app.api.resume", "main"):
            patches.append(patch(module + ".get_settings", return_value=self.settings))
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        # These regressions explicitly exercise local anonymous mode. Account
        # authorization and encrypted-mode cases live in test_account_security.
        self.session_id = str(uuid.uuid4())
        main._chat_requests.clear()
        main._all_paid_requests.clear()

    def _create_owned_session(self, client):
        response = client.post("/api/chat/conversations")
        self.assertEqual(response.status_code, 200, response.text)
        self.session_id = response.json()["session_id"]

    def _age_session(self, days=8):
        with self.factory() as db:
            row = db.get(ResumeSession, self.session_id)
            row.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
            db.commit()

    def test_expired_session_is_unreadable_and_cleanup_retries_failed_checkpoint(self):
        with TestClient(main.app) as client:
            self._create_owned_session(client)
            save_resume_session(self.session_id, {"basic_info": {"name": "private"}}, stage="BUILDING")
            self._age_session()
            self.assertIsNone(load_resume_session(self.session_id))
            self.assertFalse(session_can_read_checkpoint(self.session_id))
            self.assertTrue(session_is_blocked(self.session_id))
            current = client.get("/api/resume/current", params={"session_id": self.session_id})
            self.assertEqual(current.status_code, 404)
            self.assertNotIn("private", current.text)

            class FailingSaver:
                async def adelete_thread(self, _):
                    raise RuntimeError("checkpoint unavailable")

            asyncio.run(main._cleanup_expired_sessions(FailingSaver()))
            with self.factory() as db:
                self.assertIsNotNone(db.get(ResumeSession, self.session_id))

            removed = []

            class WorkingSaver:
                async def adelete_thread(self, session_id):
                    removed.append(session_id)

            asyncio.run(main._cleanup_expired_sessions(WorkingSaver()))
            self.assertIn(self.session_id, removed)
            with self.factory() as db:
                self.assertIsNone(db.get(ResumeSession, self.session_id))

    def test_delete_failure_does_not_report_success_or_allow_resurrection(self):
        with TestClient(main.app) as client:
            self._create_owned_session(client)
            save_resume_session(self.session_id, {"basic_info": {"name": "private"}}, stage="BUILDING")

            class FailingSaver:
                async def adelete_thread(self, _):
                    raise RuntimeError("private checkpoint error")

            with patch.object(main.app.state, "checkpointer", FailingSaver()):
                deleted = client.delete(f"/api/chat/session/{self.session_id}")
            self.assertEqual(deleted.status_code, 503)
            self.assertNotIn("private checkpoint error", deleted.text)
            self.assertIsNone(load_resume_session(self.session_id))
            self.assertTrue(session_is_blocked(self.session_id))
            self.assertFalse(ensure_resume_session(self.session_id))
            with self.assertRaises(SessionStorageUnavailable):
                save_resume_session(self.session_id, {"basic_info": {"name": "resurrected"}}, stage="BUILDING")
            self.assertIsNone(load_resume_session(self.session_id))

            retried = []

            class WorkingSaver:
                async def adelete_thread(self, session_id):
                    retried.append(session_id)

            asyncio.run(main._cleanup_expired_sessions(WorkingSaver()))
            self.assertIn(self.session_id, retried)

            deleted = client.delete(f"/api/chat/session/{self.session_id}")
            # Once catalog ownership is removed, the public API gives the same
            # 404 as an unknown ID; retries are handled by the private cleanup.
            self.assertEqual(deleted.status_code, 404)

    def test_untrusted_forwarded_header_cannot_reset_paid_request_limit(self):
        with patch.object(main, "CHAT_REQUEST_LIMIT", 2), TestClient(main.app) as client:
            for i in range(2):
                response = client.post(
                    "/api/chat/stream",
                    json={"messages": [{"role": "user", "content": "hi"}]},
                    headers={"X-Forwarded-For": f"203.0.113.{i + 1}"},
                )
                self.assertNotEqual(response.status_code, 429)
            blocked = client.post(
                "/api/chat/stream",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Forwarded-For": "203.0.113.99"},
            )
            self.assertEqual(blocked.status_code, 429)

    def test_chat_body_and_upload_limits_and_error_redaction(self):
        with TestClient(main.app) as client:
            huge_message = "a" * (main.chat.MAX_CHAT_BODY_BYTES + 1)
            chat = client.post(
                "/api/chat/stream",
                json={"messages": [{"role": "user", "content": huge_message}]},
            )
            self.assertEqual(chat.status_code, 413)
            upload = client.post(
                "/api/chat/upload",
                files={"file": ("resume.txt", b"x" * (10 * 1024 * 1024 + 1))},
            )
            self.assertEqual(upload.status_code, 413)
            early = client.post(
                "/api/chat/upload",
                files={"file": ("resume.txt", b"small")},
                headers={"Content-Length": str(12 * 1024 * 1024)},
            )
            self.assertEqual(early.status_code, 413)
            with patch("app.api.chat.extract_text", side_effect=RuntimeError("secret parse detail")):
                bad = client.post(
                    "/api/chat/upload",
                    files={"file": ("resume.pdf", b"%PDF-1.4")},
                )
            self.assertEqual(bad.status_code, 422)
            self.assertNotIn("secret parse detail", bad.text)

    def test_pdf_pages_and_docx_expansion_are_bounded(self):
        class FakePdf:
            pages = [object()] * 21

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

        with patch("pdfplumber.open", return_value=FakePdf()):
            with self.assertRaises(FileLimitError):
                extract_text("resume.pdf", b"%PDF")

        output = io.BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("word/document.xml", "x" * 101)
        with patch("app.services.file_extractor.MAX_DOCX_UNCOMPRESSED_BYTES", 100):
            with self.assertRaises(FileLimitError):
                extract_text("resume.docx", output.getvalue())


if __name__ == "__main__":
    unittest.main()
