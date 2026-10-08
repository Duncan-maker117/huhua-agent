"""Full account/profile/canonical/checkpoint flow on disposable encrypted stores."""

import base64
import copy
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Settings

with patch("app.config.get_settings", return_value=Settings(_env_file=None, DATABASE_URL="sqlite:///:memory:", LLM_API_KEY="")):
    from app.database import Base
    from app.api import account, conversations, chat, profile, resume, resume_changes
    from app.agents.resume_graph import _init_state, build_graph
    from app.models.models import Conversation
    from app.services.account_service import AccountService
    from app.services.conversation_store import checkpoint_owner
    from app.services.data_crypto import crypto_from_settings
    from app.services.profile_service import process_pending_events, enqueue_archive_event
    from app.services.secure_checkpoint import SecureCheckpointSaver
    from app.services.canonical_resume import resume_revision
    from app.services.session_store import save_resume_session


class Mailbox:
    def __init__(self):
        self.sent = {}

    def available(self):
        return True

    def send(self, email, code):
        self.sent[email] = code


class ProductSecurityFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="huhua-product-flow-")
        self.path = Path(self.temp.name)
        self.settings = Settings(_env_file=None, APP_ENV="local", REQUIRE_ACCOUNT=True,
            DATA_ENCRYPTION_KEYS=json.dumps({"test": base64.b64encode(os.urandom(32)).decode()}),
            DATA_ENCRYPTION_ACTIVE_KEY="test", ACCOUNT_SECRET=base64.b64encode(os.urandom(32)).decode(),
            AUTH_COOKIE_SECURE=False, APP_ORIGIN="http://testserver", LLM_API_KEY="",
            DATABASE_URL=f"sqlite:///{self.path / 'app.db'}", CHECKPOINT_DB_PATH=str(self.path / "graph.db"))
        self.engine = create_engine(self.settings.DATABASE_URL, connect_args={"check_same_thread": False})
        self.factory = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)
        self.patches = []
        for name in ("app.database", "app.services.session_store", "app.services.conversation_store",
                     "app.services.canonical_resume", "app.services.profile_bridge", "app.services.runtime_limits",
                     "app.services.resume_suggestions", "app.api.resume_changes"):
            self.patches.append(patch(name + ".SessionLocal", self.factory))
        for name in ("app.config", "app.services.session_store", "app.services.runtime_limits",
                     "app.services.resume_suggestions", "app.api.conversations", "app.api.chat", "app.api.resume"):
            self.patches.append(patch(name + ".get_settings", return_value=self.settings))
        for p in self.patches:
            p.start()
        self.mail = Mailbox()
        self.service = AccountService(self.factory, self.settings, transport=self.mail)
        self.saver_context = AsyncSqliteSaver.from_conn_string(str(self.path / "graph.db"))
        self.inner = await self.saver_context.__aenter__()
        await self.inner.setup()
        self.saver = SecureCheckpointSaver(self.inner, crypto_from_settings(self.settings), checkpoint_owner)
        self.graph = build_graph(object(), checkpointer=self.saver)
        for name in ("app.api.chat", "app.api.resume", "app.api.resume_changes"):
            p = patch(name + ".get_graph", return_value=self.graph)
            p.start()
            self.patches.append(p)
        self.app = FastAPI()
        self.app.state.account_service = self.service
        self.app.state.checkpointer = self.saver
        from app.services.conversation_store import claim_browser
        self.app.state.claim_browser = claim_browser
        self.app.include_router(account.router, prefix="/api")
        self.app.include_router(conversations.router, prefix="/api/chat")
        self.app.include_router(chat.router, prefix="/api/chat")
        self.app.include_router(resume.router, prefix="/api/resume")
        self.app.include_router(resume_changes.router, prefix="/api/resume")
        self.app.include_router(profile.router, prefix="/api/profile")
        self.a = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver", headers={"Origin": "http://testserver"})
        self.b = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver", headers={"Origin": "http://testserver"})
        self.addAsyncCleanup(self.cleanup)
        self.account_a = await self.login(self.a, "a@example.test")
        self.account_b = await self.login(self.b, "b@example.test")

    async def cleanup(self):
        await self.a.aclose()
        await self.b.aclose()
        await self.saver_context.__aexit__(None, None, None)
        for p in reversed(self.patches):
            p.stop()
        self.engine.dispose()
        self.temp.cleanup()

    async def login(self, client, email):
        started = await client.post("/api/account/login/start", json={"email": email})
        self.assertEqual(started.status_code, 200, started.text)
        logged = await client.post("/api/account/login/verify", json={"email": email, "code": self.mail.sent[email]})
        self.assertEqual(logged.status_code, 200, logged.text)
        return logged.json()["account"]["id"]

    async def fixture(self, client=None, marker="PRIVATE_CANARY_723"):
        client = client or self.a
        created = await client.post("/api/chat/conversations")
        self.assertEqual(created.status_code, 200, created.text)
        sid = created.json()["session_id"]
        data = {"basic_info": {"name": marker}, "projects": [{"name": "课程工具", "description": "参与需求整理。", "role": "后端参与者"}]}
        values = {**_init_state(), "stage": "EVALUATING", "resume_data": data,
                  "collected_info": {"basic_info": data["basic_info"], "projects": data["projects"]},
                  "messages": [HumanMessage(content=marker, id="human-" + sid)]}
        await self.graph.aupdate_state({"configurable": {"thread_id": sid}}, values, as_node="building")
        save_resume_session(sid, data, marker, "EVALUATING")
        return sid, data

    async def test_every_private_session_endpoint_denies_other_account(self):
        sid, data = await self.fixture()
        calls = [
            ("GET", f"/api/chat/conversations/{sid}", None),
            ("GET", f"/api/resume/current?session_id={sid}", None),
            ("GET", f"/api/chat/export/docx?session_id={sid}", None),
            ("DELETE", f"/api/chat/session/{sid}", None),
            ("PUT", "/api/resume/current", {"session_id": sid, "expected_revision": resume_revision(data), "resume_data": data}),
            ("POST", "/api/chat/stream", {"session_id": sid, "messages": [{"role": "user", "content": "请继续"}]}),
            ("POST", "/api/resume/match", {"session_id": sid}),
        ]
        for method, path, body in calls:
            with self.subTest(path=path):
                r = await self.b.request(method, path, json=body)
                self.assertEqual(r.status_code, 404, r.text)
                self.assertNotIn("PRIVATE_CANARY", r.text)
        self.assertEqual((await self.a.get(f"/api/resume/current?session_id={sid}")).status_code, 200)

    async def test_resume_checkpoint_sources_and_titles_have_no_plaintext(self):
        sid, data = await self.fixture()
        with self.factory() as db:
            conversation = db.get(Conversation, sid)
            conversation.title = "PRIVATE_TITLE_723"
            enqueue_archive_event(db, self.account_a, "source-723", sid,
                                  {"human_text": "我的姓名是PRIVATE_SOURCE_723", "source_kind": "self"})
            db.commit()
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT resume_data,resume_draft FROM resume_sessions")).all()
            titles = conn.execute(text("SELECT title FROM conversations")).all()
            sources = conn.execute(text("SELECT payload FROM profile_sources")).all()
        self.assertNotIn("PRIVATE_", str(rows) + str(titles) + str(sources))
        async with self.inner.conn.execute("SELECT checkpoint,metadata FROM checkpoints") as cursor:
            records = await cursor.fetchall()
        self.assertNotIn(b"PRIVATE_", repr(records).encode())
        loaded = await self.a.get(f"/api/chat/conversations/{sid}")
        self.assertEqual(loaded.json()["resume_data"]["basic_info"]["name"], data["basic_info"]["name"])

    async def test_apply_and_undo_are_idempotent_revision_bound_and_not_facts(self):
        sid, data = await self.fixture()
        preview = await self.a.post(f"/api/resume/session/{sid}/suggestions/preview", json={"source_text": "参与需求整理。", "suggested_text": "参与需求整理；"})
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()["can_apply"])
        body = {"suggestion_id": preview.json()["suggestion_id"], "expected_revision": preview.json()["revision"]}
        applied = await self.a.post(f"/api/resume/session/{sid}/suggestions/apply", json=body)
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(applied.json()["data"]["projects"][0]["description"], "参与需求整理；")
        self.assertEqual((await self.a.post(f"/api/resume/session/{sid}/suggestions/apply", json=body)).status_code, 409)
        undo = await self.a.post(f"/api/resume/session/{sid}/suggestions/undo", json={"change_id": applied.json()["change_id"], "expected_revision": applied.json()["revision"]})
        self.assertEqual(undo.status_code, 200, undo.text)
        self.assertEqual(undo.json()["data"]["projects"][0]["description"], "参与需求整理。")
        self.assertEqual((await self.a.get("/api/profile")).json()["facts"], [])

    async def test_numbers_and_strengthened_roles_cannot_be_adopted(self):
        sid, _ = await self.fixture()
        for proposed in ("主导需求整理。", "参与需求整理，效率提升50%。"):
            result = await self.a.post(f"/api/resume/session/{sid}/suggestions/preview", json={"source_text": "参与需求整理。", "suggested_text": proposed})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertFalse(result.json()["can_apply"])

    async def test_profile_facts_are_scoped_and_explicitly_imported(self):
        added = await self.a.post("/api/profile/facts", json={"category": "project", "subject": "课程工具", "field": "description", "value": "参与需求整理"})
        self.assertEqual(added.status_code, 200, added.text)
        fact = added.json()["facts"][0]
        self.assertEqual((await self.b.get("/api/profile")).json()["facts"], [])
        sid, _ = await self.fixture(marker="IMPORT_MARKER")
        applied = await self.a.post(f"/api/resume/session/{sid}/profile-facts", json={"fact_ids": [fact["id"]]})
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual((await self.b.post(f"/api/resume/session/{sid}/profile-facts", json={"fact_ids": [fact["id"]]})).status_code, 404)

    async def test_deleted_fact_cannot_return_through_current_export_or_undo(self):
        marker = "DELETE_CANARY_723"
        added = await self.a.post("/api/profile/facts", json={"category": "basic", "subject": "本人", "field": "name", "value": marker})
        self.assertEqual(added.status_code, 200, added.text)
        fact = added.json()["facts"][0]
        sid, data = await self.fixture(marker=marker)
        deleted = await self.a.delete(f"/api/profile/facts/{fact['id']}?expected_revision={fact['revision']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        current = await self.a.get(f"/api/resume/current?session_id={sid}")
        self.assertNotIn(marker, current.text)
        saved = await self.a.put("/api/resume/current", json={"session_id": sid, "expected_revision": resume_revision(data), "resume_data": data})
        self.assertEqual(saved.status_code, 409, saved.text)
        exported = await self.a.post("/api/resume/export/docx/t001", json=data)
        self.assertEqual(exported.status_code, 409, exported.text)

    async def test_outbox_survives_store_reopen_and_retries_do_not_duplicate(self):
        sid, data = await self.fixture()
        event = {"source_id": "durable-source", "event_type": "human_message", "payload": {
            "human_text": "我叫耐久测试", "source_kind": "self", "collected_info_delta": {"basic_info": {"name": "耐久测试"}},
        }}
        save_resume_session(sid, data, stage="EVALUATING", archive_event=event)
        save_resume_session(sid, data, stage="EVALUATING", archive_event=event)
        await process_pending_events(self.factory)
        await process_pending_events(self.factory)
        view = (await self.a.get("/api/profile")).json()
        self.assertEqual([fact["value"] for fact in view["facts"]], ["耐久测试"])

    async def test_checkpoint_ahead_of_failed_sql_save_is_not_current(self):
        sid, data = await self.fixture()
        newer = copy.deepcopy(data)
        newer["basic_info"]["name"] = "UNCOMMITTED_MARKER"
        await self.graph.aupdate_state({"configurable": {"thread_id": sid}}, {"resume_data": newer}, as_node="building")
        current = await self.a.get(f"/api/resume/current?session_id={sid}")
        self.assertEqual(current.json()["data"], data)

    async def test_failed_save_callback_restores_checkpoint_and_sql(self):
        from app.agents.resume_graph import _serialize_to_resume_data
        from app.services.canonical_resume import save_canonical_resume
        sid, data = await self.fixture()
        newer = copy.deepcopy(data)
        newer["basic_info"]["name"] = "MUST_NOT_SAVE"

        def conflict(*args):
            raise HTTPException(409, "资料已变化")

        with self.assertRaises(HTTPException) as raised:
            await save_canonical_resume(sid, resume_revision(data), newer, self.graph,
                                        _serialize_to_resume_data, after_save=conflict)
        self.assertEqual(raised.exception.status_code, 409)
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": sid}})
        self.assertEqual(snapshot.values["resume_data"], data)
        self.assertNotIn("MUST_NOT_SAVE", str(snapshot.values["collected_info"]))
        current = await self.a.get(f"/api/resume/current?session_id={sid}")
        self.assertEqual(current.json()["data"], data)

    async def test_next_turn_repairs_checkpoint_left_ahead_after_crash(self):
        from app.services.profile_bridge import prepare_graph_context
        sid, data = await self.fixture()
        newer = copy.deepcopy(data)
        newer["basic_info"]["name"] = "UNCOMMITTED_FIELD"
        config = {"configurable": {"thread_id": sid}}
        await self.graph.aupdate_state(config, {"resume_data": newer, "collected_info": newer}, as_node="building")
        await prepare_graph_context("account:" + self.account_a, sid, self.graph)
        snapshot = await self.graph.aget_state(config)
        self.assertEqual(snapshot.values["resume_data"], data)
        self.assertEqual(snapshot.values["collected_info"]["basic_info"], data["basic_info"])

    async def test_invalid_selection_and_conflicting_import_never_mutate_draft(self):
        from app.services.profile_service import ProfileRevisionConflict
        added = await self.a.post("/api/profile/facts", json={"category": "project", "subject": "新的课程", "field": "description", "value": "独立整理测试案例"})
        fact = added.json()["facts"][0]
        sid, data = await self.fixture()
        config = {"configurable": {"thread_id": sid}}
        rejected = await self.a.post(f"/api/resume/session/{sid}/profile-facts", json={"fact_ids": [fact["id"], "foreign-or-deleted"]})
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertNotIn("新的课程", str((await self.graph.aget_state(config)).values))
        with patch("app.api.resume_changes.merge_job_version_import", side_effect=ProfileRevisionConflict()):
            conflicted = await self.a.post(f"/api/resume/session/{sid}/profile-facts", json={"fact_ids": [fact["id"]]})
        self.assertEqual(conflicted.status_code, 409, conflicted.text)
        self.assertNotIn("新的课程", str((await self.graph.aget_state(config)).values))
        self.assertEqual((await self.a.get(f"/api/resume/current?session_id={sid}")).json()["data"], data)

    async def test_bad_history_job_cannot_block_other_imports_and_retry_is_bounded(self):
        from app.services.profile_bridge import ClaimedHistoryImport, import_claimed_history
        sid, _ = await self.fixture()
        broken, _ = await self.fixture(marker="BROKEN_JOB")
        with self.factory() as db:
            for value in (broken, sid):
                db.add(ClaimedHistoryImport(session_id=value, owner="account:" + self.account_a))
            db.commit()
        original = self.saver.aget_tuple

        async def load(config):
            if config["configurable"]["thread_id"] == broken:
                raise ValueError("synthetic corrupt checkpoint")
            return await original(config)

        with patch.object(self.saver, "aget_tuple", side_effect=load):
            for _ in range(4):
                await import_claimed_history(self.saver)
        with self.factory() as db:
            self.assertEqual(db.get(ClaimedHistoryImport, sid).status, "completed")
            failed = db.get(ClaimedHistoryImport, broken)
            self.assertEqual(failed.status, "failed")
            self.assertEqual(failed.attempts, 3)

    async def test_foreign_origin_account_write_is_blocked_and_logout_revokes(self):
        denied = await self.a.post("/api/account/logout", headers={"Origin": "https://other.example"})
        self.assertEqual(denied.status_code, 403)
        logged = await self.a.post("/api/account/logout")
        self.assertEqual(logged.status_code, 200)
        self.assertEqual((await self.a.get("/api/chat/conversations")).status_code, 401)

    async def test_explicit_browser_claim_keeps_ciphertext_readable_but_transfers_access(self):
        from app.services.conversation_store import create_conversation, WORKSPACE_COOKIE, assert_session_owner, ConversationNotFound
        from app.models.models import ResumeSession
        token = "a-valid-original-browser-token-with-entropy-723"
        original_owner = hashlib.sha256(token.encode()).hexdigest()
        sid = create_conversation(original_owner)["session_id"]
        data = {"basic_info": {"name": "CLAIM_CANARY"}}
        await self.graph.aupdate_state({"configurable": {"thread_id": sid}},
            {**_init_state(), "resume_data": data, "messages": [HumanMessage(content="我叫CLAIM_CANARY", id="claim-source")]}, as_node="building")
        save_resume_session(sid, data, "CLAIM_CANARY", "EVALUATING")
        self.assertEqual((await self.a.get(f"/api/resume/current?session_id={sid}")).status_code, 404)
        self.a.cookies.set(WORKSPACE_COOKIE, token)
        claimed = await self.a.post("/api/account/claim-browser")
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertEqual(claimed.json()["claimed"], 1)
        self.assertEqual((await self.a.get(f"/api/resume/current?session_id={sid}")).json()["data"], data)
        self.assertEqual((await self.b.get(f"/api/chat/conversations/{sid}")).status_code, 404)
        with self.assertRaises(ConversationNotFound):
            assert_session_owner(original_owner, sid)
        with self.factory() as db:
            self.assertEqual(db.get(ResumeSession, sid).owner_key, original_owner)
            self.assertEqual(db.get(Conversation, sid).owner_hash, "account:" + self.account_a)
            self.assertTrue(db.get(Conversation, sid).title)
        self.assertEqual((await self.a.post("/api/account/claim-browser")).json()["claimed"], 0)

    async def test_daily_budget_persists_but_does_not_block_reads(self):
        from app.services.runtime_limits import reserve_turn
        sid, _ = await self.fixture()
        settings = self.settings.model_copy(update={"ACCOUNT_DAILY_TURN_LIMIT": 1})
        with patch("app.services.runtime_limits.get_settings", return_value=settings):
            reserve_turn("account:" + self.account_a)
            with self.assertRaises(HTTPException) as raised:
                reserve_turn("account:" + self.account_a)
            self.assertEqual(raised.exception.status_code, 429)
            reserve_turn("account:" + self.account_b)
        self.assertEqual((await self.a.get(f"/api/resume/current?session_id={sid}")).status_code, 200)

    async def test_filtered_revision_can_save_after_cleanup_is_deferred(self):
        marker = "DEFERRED_DELETE_MARKER"
        added = await self.a.post("/api/profile/facts", json={"category": "basic", "subject": "本人", "field": "name", "value": marker})
        fact = added.json()["facts"][0]
        sid, _ = await self.fixture(marker=marker)
        await self.a.delete(f"/api/profile/facts/{fact['id']}?expected_revision={fact['revision']}")
        # This router-only app deliberately has no background projection purge.
        current = (await self.a.get(f"/api/resume/current?session_id={sid}")).json()
        response = await self.a.put("/api/resume/current", json={"session_id": sid, "expected_revision": current["revision"], "resume_data": current["data"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(marker, response.text)
