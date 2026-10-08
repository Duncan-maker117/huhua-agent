"""Temporary guest capabilities and account claiming on isolated encrypted stores."""

import asyncio
import base64
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Request, Response
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Settings

with patch("app.config.get_settings", return_value=Settings(_env_file=None, DATABASE_URL="sqlite:///:memory:", LLM_API_KEY="")):
    from app.database import Base
    from app.api import account
    from app.models.models import Conversation, ResumeSession
    from app.models.profile import ProfileSource
    from app.services.account_service import AccountService, resolve_owner
    from app.services.access_control import authorize_session
    from app.services.conversation_store import (
        GUEST_COOKIE, WORKSPACE_COOKIE, ConversationNotFound, assert_session_owner,
        checkpoint_owner, create_conversation, guest_identity, load_conversation,
        remove_conversation,
    )
    from app.services.data_crypto import crypto_from_settings
    from app.services.profile_bridge import ClaimedHistoryImport, import_claimed_history
    from app.services.runtime_limits import reserve_turn
    from app.models.legacy_suggestions import ResumeSuggestion
    from app.services.secure_checkpoint import SecureCheckpointSaver
    from app.services.session_store import (
        list_sessions_needing_checkpoint_cleanup, load_resume_session,
        save_resume_session, session_can_read_checkpoint,
        session_lock, session_needs_checkpoint_cleanup,
    )


class Mailbox:
    def __init__(self):
        self.codes = {}

    def available(self):
        return True

    def send(self, email, code):
        self.codes[email] = code


class GuestIdentityTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="huhua-guest-test-")
        root = Path(self.directory.name)
        self.settings = Settings(_env_file=None, APP_ENV="production", REQUIRE_ACCOUNT=True,
            ALLOW_INSECURE_LOCAL_STORAGE=False,
            ALLOW_GUEST_EXPERIENCE=True, GUEST_RETENTION_HOURS=24,
            DATA_ENCRYPTION_KEYS=json.dumps({"test": base64.b64encode(os.urandom(32)).decode()}),
            DATA_ENCRYPTION_ACTIVE_KEY="test", ACCOUNT_SECRET=base64.b64encode(os.urandom(32)).decode(),
            AUTH_COOKIE_SECURE=True, APP_ORIGIN="https://testserver", LLM_API_KEY="",
            DATABASE_URL=f"sqlite:///{root / 'app.db'}", CHECKPOINT_DB_PATH=str(root / "graph.db"))
        self.settings.validate_runtime()
        self.engine = create_engine(self.settings.DATABASE_URL, connect_args={"check_same_thread": False})
        self.factory = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)
        self.patches = [patch("app.config.get_settings", return_value=self.settings)]
        for module in ("app.database", "app.services.session_store", "app.services.conversation_store",
                       "app.services.profile_bridge", "app.services.runtime_limits"):
            self.patches.append(patch(module + ".SessionLocal", self.factory))
        for module in ("app.services.session_store", "app.services.runtime_limits"):
            self.patches.append(patch(module + ".get_settings", return_value=self.settings))
        for item in self.patches:
            item.start()
        self.mail = Mailbox()
        self.app = FastAPI()
        self.app.state.account_service = AccountService(self.factory, self.settings, transport=self.mail)
        self.app.include_router(account.router, prefix="/api")

        @self.app.post("/test/guest")
        async def new_guest(request: Request, response: Response):
            owner = resolve_owner(request, response, allow_guest=True)
            return {**create_conversation(owner), "owner": owner}

        @self.app.get("/test/session/{session_id}")
        async def guest_session(session_id: str, request: Request):
            owner = authorize_session(request, session_id)
            return load_conversation(owner, session_id)

        @self.app.get("/test/account-only")
        async def account_only(request: Request):
            return {"owner": resolve_owner(request)}

        self.client = self.new_client()
        self.other = self.new_client()
        self.saver_context = AsyncSqliteSaver.from_conn_string(self.settings.CHECKPOINT_DB_PATH)
        self.inner = await self.saver_context.__aenter__()
        await self.inner.setup()
        self.saver = SecureCheckpointSaver(self.inner, crypto_from_settings(self.settings), checkpoint_owner)
        self.addAsyncCleanup(self.cleanup)

    def new_client(self):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                 base_url="https://testserver", headers={"Origin": "https://testserver"})

    async def cleanup(self):
        await self.client.aclose()
        await self.other.aclose()
        await self.saver_context.__aexit__(None, None, None)
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()
        self.directory.cleanup()

    async def create(self, client=None):
        result = await (client or self.client).post("/test/guest")
        self.assertEqual(result.status_code, 200, result.text)
        return result.json(), result

    async def login(self, client=None, email="guest@example.test"):
        client = client or self.client
        started = await client.post("/api/account/login/start", json={"email": email})
        self.assertEqual(started.status_code, 200, started.text)
        result = await client.post("/api/account/login/verify", json={"email": email, "code": self.mail.codes[email]})
        self.assertEqual(result.status_code, 200, result.text)
        return "account:" + result.json()["account"]["id"]

    async def claim(self, session_id, client=None):
        return await (client or self.client).post("/api/account/claim-guest", json={"session_id": session_id})

    def age(self, session_id, hours):
        with self.factory() as db:
            row = db.get(ResumeSession, session_id)
            row.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
            db.commit()

    async def payload(self, session_id):
        data = {"basic_info": {"name": "GUEST_PRIVATE_CANARY"}}
        source = HumanMessage(content="我的名字是 GUEST_PRIVATE_CANARY", id="source-" + session_id)
        state = empty_checkpoint()
        state["channel_values"] = {"messages": [source], "resume_data": data}
        await self.saver.aput({"configurable": {"thread_id": session_id, "checkpoint_ns": ""}}, state, {}, {})
        save_resume_session(session_id, data, "GUEST_PRIVATE_CANARY", "EVALUATING",
                            archive_event={"source_id": source.id, "payload": {"human_text": source.content, "source_kind": "self"}})
        with self.factory() as db:
            db.get(Conversation, session_id).title = "GUEST_PRIVATE_TITLE"
            db.commit()
        return data

    async def test_guest_cookie_is_separate_secure_session_cookie_and_browser_isolation(self):
        old_cookie = "legacy-browser-token-not-for-automatic-transfer-723"
        self.client.cookies.set(WORKSPACE_COOKIE, old_cookie)
        first, response = await self.create()
        other, _ = await self.create(self.other)
        self.assertTrue(first["owner"].startswith("guest:"))
        self.assertLessEqual(len(first["owner"]), 64)
        self.assertNotEqual(first["owner"], other["owner"])
        self.assertNotEqual(first["owner"], hashlib.sha256(old_cookie.encode()).hexdigest())
        cookie = response.headers["set-cookie"]
        for flag in ("HttpOnly", "Secure", "SameSite=lax"):
            self.assertIn(flag, cookie)
        self.assertNotIn("Max-Age", cookie)
        self.assertNotIn("expires=", cookie.lower())
        self.assertEqual((await self.other.get("/test/session/" + first["session_id"])).status_code, 404)
        self.assertEqual((await self.client.get("/test/account-only")).status_code, 401)
        me = (await self.client.get("/api/account/me")).json()
        self.assertTrue(me["guest_allowed"])
        self.assertEqual(me["guest_retention_hours"], 24)

    async def test_claim_reseals_suggestion_and_cleanup_removes_temporary_payloads(self):
        first, _ = await self.create()
        second, _ = await self.create()
        payload = {"source_text": "GUEST_PRIVATE_SOURCE", "before_data": {"projects": []}}
        with self.factory() as db:
            db.add(ResumeSuggestion(id="claimed-suggestion", owner=first["owner"],
                                   session_id=first["session_id"], payload=payload, status="applied"))
            db.add(ResumeSuggestion(id="temporary-suggestion", owner=first["owner"],
                                   session_id=second["session_id"], payload=payload))
            db.commit()
        owner = await self.login()
        self.assertEqual((await self.claim(first["session_id"])).status_code, 200)
        with self.factory() as db:
            suggestion = db.get(ResumeSuggestion, "claimed-suggestion")
            self.assertEqual(suggestion.owner, owner)
            self.assertEqual(suggestion.payload, payload)
            self.assertEqual(suggestion.status, "applied")
        remove_conversation(second["session_id"])
        with self.factory() as db:
            self.assertIsNone(db.get(ResumeSuggestion, "temporary-suggestion"))
            self.assertIsNotNone(db.get(ResumeSuggestion, "claimed-suggestion"))

    async def test_request_reuses_new_identity_without_duplicate_cookie_token(self):
        request = Request({"type": "http", "method": "GET", "scheme": "https", "path": "/", "headers": []})
        self.assertIsNone(guest_identity(request))
        first, second = Response(), Response()
        owner = guest_identity(request, first)
        self.assertEqual(guest_identity(request), owner)
        self.assertEqual(guest_identity(request, second), owner)
        self.assertEqual(first.headers["set-cookie"], second.headers["set-cookie"])

    async def test_claim_only_current_session_preserves_encryption_and_imports_after_login(self):
        first, _ = await self.create()
        second, _ = await self.create()
        legacy_token = "legacy-browser-token-keeps-unrelated-history-723"
        legacy = create_conversation(hashlib.sha256(legacy_token.encode()).hexdigest())
        self.client.cookies.set(WORKSPACE_COOKIE, legacy_token)
        sid = first["session_id"]
        data = await self.payload(sid)
        with self.factory() as db:
            self.assertEqual(db.query(ProfileSource).count(), 0)
        owner = await self.login()
        claimed = await self.claim(sid)
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertEqual(claimed.json(), {"claimed": 1, "session_id": sid})
        self.assertIsNone(self.client.cookies.get(GUEST_COOKIE))
        with self.factory() as db:
            self.assertEqual(db.get(Conversation, sid).owner_hash, owner)
            self.assertEqual(db.get(Conversation, sid).title, "GUEST_PRIVATE_TITLE")
            self.assertEqual(db.get(ResumeSession, sid).owner_key, first["owner"])
            self.assertEqual(db.get(ResumeSession, sid).resume_data, data)
            self.assertEqual(db.get(Conversation, second["session_id"]).owner_hash, first["owner"])
            self.assertEqual(db.get(Conversation, legacy["session_id"]).owner_hash, hashlib.sha256(legacy_token.encode()).hexdigest())
            self.assertEqual(db.query(ClaimedHistoryImport).count(), 1)
        with self.assertRaises(ConversationNotFound):
            assert_session_owner(first["owner"], sid)
        snapshot = await self.saver.aget_tuple({"configurable": {"thread_id": sid}})
        self.assertEqual(snapshot.checkpoint["channel_values"]["resume_data"], data)
        await import_claimed_history(self.saver)
        with self.factory() as db:
            self.assertEqual(db.query(ProfileSource).count(), 1)
            self.assertEqual(db.get(ClaimedHistoryImport, sid).status, "completed")
        with self.engine.connect() as conn:
            raw = conn.execute(text("SELECT resume_data,resume_draft FROM resume_sessions")).all()
            titles = conn.execute(text("SELECT title FROM conversations")).all()
        self.assertNotIn("GUEST_PRIVATE", str(raw) + str(titles))

    async def test_claim_is_idempotent_only_for_the_owning_account(self):
        first, _ = await self.create()
        token = self.client.cookies.get(GUEST_COOKIE)
        await self.login()
        self.assertEqual((await self.claim(first["session_id"])).json()["claimed"], 1)
        again = await self.claim(first["session_id"])
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["claimed"], 0)
        await self.login(self.other, "other@example.test")
        self.other.cookies.set(GUEST_COOKIE, token)
        self.assertEqual((await self.claim(first["session_id"], self.other)).status_code, 404)

    async def test_no_cookie_fake_id_or_wrong_browser_cannot_claim(self):
        first, _ = await self.create()
        self.assertEqual((await self.claim(first["session_id"])).status_code, 401)
        await self.login(self.other, "other@example.test")
        self.assertEqual((await self.claim(first["session_id"], self.other)).status_code, 404)
        # Obtaining one's own unrelated token still confers no access.
        self.other.cookies.set(GUEST_COOKIE, "different-valid-browser-token-with-entropy-723")
        self.assertEqual((await self.claim(first["session_id"], self.other)).status_code, 404)
        await self.login()
        self.assertEqual((await self.claim("forged-session-id")).status_code, 404)

    async def test_expired_guest_is_not_readable_claimable_or_checkpoint_readable(self):
        first, _ = await self.create()
        sid = first["session_id"]
        self.age(sid, 25)
        self.assertEqual((await self.client.get("/test/session/" + sid)).status_code, 404)
        self.assertIsNone(load_resume_session(sid))
        self.assertFalse(session_can_read_checkpoint(sid))
        self.assertIn(sid, list_sessions_needing_checkpoint_cleanup(0))
        self.assertTrue(session_needs_checkpoint_cleanup(sid, 0))
        await self.login()
        self.assertEqual((await self.claim(sid)).status_code, 404)

    async def test_claimed_guest_uses_account_retention_despite_immutable_guest_key(self):
        first, _ = await self.create()
        sid = first["session_id"]
        await self.login()
        self.assertEqual((await self.claim(sid)).status_code, 200)
        self.age(sid, 48)
        self.assertIsNotNone(load_resume_session(sid))
        self.assertTrue(session_can_read_checkpoint(sid))
        self.assertNotIn(sid, list_sessions_needing_checkpoint_cleanup(0))
        self.assertFalse(session_needs_checkpoint_cleanup(sid, 0))
        self.assertEqual((await self.client.get("/test/session/" + sid)).status_code, 200)

    async def test_claim_waits_for_session_lock_and_rechecks_expiry(self):
        first, _ = await self.create()
        sid = first["session_id"]
        await self.login()
        lock = session_lock(sid)
        await lock.acquire()
        pending = asyncio.create_task(self.claim(sid))
        try:
            await asyncio.sleep(0.01)
            self.assertFalse(pending.done())
            self.age(sid, 25)
        finally:
            lock.release()
        self.assertEqual((await pending).status_code, 404)

    async def test_guest_quota_and_account_quota_are_separate(self):
        first, _ = await self.create()
        self.settings.GUEST_DAILY_TURN_LIMIT = 1
        self.settings.ACCOUNT_DAILY_TURN_LIMIT = 2
        reserve_turn(first["owner"])
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as result:
            reserve_turn(first["owner"])
        self.assertEqual(result.exception.status_code, 429)
        owner = await self.login()
        reserve_turn(owner)
        reserve_turn(owner)
        with self.assertRaises(HTTPException):
            reserve_turn(owner)

    async def test_disabled_guest_setting_denies_new_guest_and_logout_rotates_identity(self):
        first, _ = await self.create()
        await self.login()
        await self.client.post("/api/account/logout")
        self.assertIsNone(self.client.cookies.get(GUEST_COOKIE))
        second, _ = await self.create()
        self.assertNotEqual(first["owner"], second["owner"])
        self.settings.ALLOW_GUEST_EXPERIENCE = False
        self.assertEqual((await self.client.post("/test/guest")).status_code, 401)


if __name__ == "__main__":
    unittest.main()
