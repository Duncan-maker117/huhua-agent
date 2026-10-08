"""Isolated security regressions: no developer DB, SMTP or model calls."""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from typing_extensions import TypedDict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402

# The first database module import constructs an engine. Make even that engine
# isolated and explicitly bypass backend/.env before importing account models.
with patch("app.config.get_settings", return_value=Settings(_env_file=None, DATABASE_URL="sqlite:///:memory:", LLM_API_KEY="")):
    from app.api.account import router
    from app.models.account import Account, AccountSession, LoginChallenge
    from app.services.account_service import AccountService
    from app.services.data_crypto import CryptoConfigurationError, DataCrypto, DataDecryptionError, crypto_from_settings
    from app.services.secure_checkpoint import SecureCheckpointSaver


def settings_for(crypto):
    return SimpleNamespace(
        APP_ENV="local", REQUIRE_ACCOUNT=True, ALLOW_INSECURE_LOCAL_STORAGE=False,
        ACCOUNT_SECRET=base64.b64encode(os.urandom(32)).decode(), AUTH_COOKIE_SECURE=False,
        APP_ORIGIN="http://testserver", DATA_ENCRYPTION_KEYS=json.dumps({k: base64.b64encode(v).decode() for k, v in crypto.keys.items()}),
        DATA_ENCRYPTION_ACTIVE_KEY=crypto.active_key, SMTP_HOST="", SMTP_FROM="", SMTP_STARTTLS=True,
    )


class MemoryMail:
    def __init__(self):
        self.deliveries = []

    def available(self):
        return True

    def send(self, email, code):
        self.deliveries.append((email, code))


class CryptoTest(unittest.TestCase):
    def setUp(self):
        self.crypto = DataCrypto({"first": os.urandom(32)}, "first")
        self.context = {"owner": "account:one", "record": "row-one", "field": "resume"}

    def test_round_trip_random_nonce_and_no_plaintext(self):
        value = {"name": "私有标记PRIVATE_MARKER", "skills": ["Python"]}
        first = self.crypto.encrypt_json(value, **self.context)
        second = self.crypto.encrypt_json(value, **self.context)
        self.assertNotEqual(first, second)
        self.assertNotIn("PRIVATE_MARKER", json.dumps(first))
        self.assertEqual(self.crypto.decrypt_json(first, **self.context), value)
        text = self.crypto.encrypt_text("秘密", **self.context)
        self.assertEqual(self.crypto.decrypt_text(text, **self.context), "秘密")

    def test_tamper_and_wrong_owner_record_field_fail_closed(self):
        sealed = self.crypto.encrypt_json({"private": 1}, **self.context)
        for field in self.context:
            with self.assertRaises(DataDecryptionError):
                self.crypto.decrypt_json(sealed, **{**self.context, field: "wrong"})
        sealed["ciphertext"] = base64.b64encode(b"tampered").decode()
        with self.assertRaises(DataDecryptionError):
            self.crypto.decrypt_json(sealed, **self.context)

    def test_key_rotation_retains_reads_and_missing_old_key_fails(self):
        sealed = self.crypto.encrypt_text("private", **self.context)
        rotated = DataCrypto({**self.crypto.keys, "new": os.urandom(32)}, "new")
        self.assertEqual(rotated.decrypt_text(sealed, **self.context), "private")
        next_value = rotated.encrypt_json({"new": 1}, **self.context)
        self.assertEqual(next_value["kid"], "new")
        with self.assertRaises(DataDecryptionError):
            DataCrypto({"new": rotated.keys["new"]}, "new").decrypt_text(sealed, **self.context)

    def test_configuration_strict_by_default_and_production_forbids_legacy(self):
        with self.assertRaises(CryptoConfigurationError):
            crypto_from_settings(SimpleNamespace())
        local = crypto_from_settings(SimpleNamespace(APP_ENV="local", ALLOW_INSECURE_LOCAL_STORAGE=True))
        self.assertFalse(local.enabled)
        self.assertEqual(local.decrypt_json({"name": "plain"}, **self.context), {"name": "plain"})
        with self.assertRaises(CryptoConfigurationError):
            crypto_from_settings(SimpleNamespace(APP_ENV="production", ALLOW_INSECURE_LOCAL_STORAGE=True))
        with self.assertRaises(CryptoConfigurationError):
            crypto_from_settings(SimpleNamespace(APP_ENV="staging", ALLOW_INSECURE_LOCAL_STORAGE=True))
        with self.assertRaises(DataDecryptionError):
            self.crypto.decrypt_json({"name": "plain"}, **self.context)


class AccountTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="huhua-account-test-")
        self.path = Path(self.directory.name) / "account.sqlite3"
        self.engine = create_engine(f"sqlite:///{self.path}", connect_args={"check_same_thread": False})
        for table in (Account.__table__, AccountSession.__table__, LoginChallenge.__table__):
            table.create(self.engine)
        from app.models.account import AuthRateBucket
        AuthRateBucket.__table__.create(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.crypto = DataCrypto({"one": os.urandom(32)}, "one")
        self.settings = settings_for(self.crypto)
        self.now = datetime(2026, 10, 4, 0, 0, 0)
        self.mail = MemoryMail()
        self.service = AccountService(self.factory, self.settings, crypto=self.crypto, transport=self.mail, clock=lambda: self.now)
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api")
        self.app.state.account_service = self.service
        self.config_patch = patch("app.config.get_settings", return_value=self.settings)
        self.config_patch.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.config_patch.stop()
        self.engine.dispose()
        self.directory.cleanup()

    async def login(self, email="person@example.test"):
        response = await self.client.post("/api/account/login/start", json={"email": email})
        self.assertEqual(response.status_code, 200, response.text)
        code = self.mail.deliveries[-1][1]
        response = await self.client.post("/api/account/login/verify", json={"email": email, "code": code})
        self.assertEqual(response.status_code, 200, response.text)
        return response, code

    async def test_login_cookie_logout_and_storage_is_private(self):
        self.assertFalse((await self.client.get("/api/account/me")).json()["authenticated"])
        response, code = await self.login()
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=lax", response.headers["set-cookie"])
        self.assertNotIn(code, response.text)
        self.assertEqual((await self.client.get("/api/account/me")).json()["account"]["email"], "person@example.test")
        token = self.client.cookies["huhua_account"]
        with self.factory() as db:
            row = db.execute(select(Account)).scalar_one()
            self.assertNotIn("person", row.email_ciphertext)
            session = db.execute(select(AccountSession)).scalar_one()
            self.assertNotEqual(session.token_hash, token)
        blob = self.path.read_bytes()
        self.assertNotIn(b"person@example.test", blob)
        self.assertNotIn(token.encode(), blob)
        self.assertEqual((await self.client.post("/api/account/logout")).status_code, 200)
        self.assertFalse((await self.client.get("/api/account/me")).json()["authenticated"])
        self.assertIsNone(self.service.authenticate(token))

    async def test_code_replay_expiry_and_persistent_attempt_limit(self):
        _, code = await self.login()
        replay = await self.client.post("/api/account/login/verify", json={"email": "person@example.test", "code": code})
        self.assertEqual(replay.status_code, 400)
        self.now += timedelta(minutes=2)
        self.service.start("person@example.test", client_ip="test")
        code = self.mail.deliveries[-1][1]
        for _ in range(5):
            with self.assertRaises(HTTPException):
                self.service.verify("person@example.test", "not-a-code", client_ip="test")
        restarted = AccountService(self.factory, self.settings, crypto=self.crypto, transport=self.mail, clock=lambda: self.now)
        with self.assertRaises(HTTPException):
            restarted.verify("person@example.test", code, client_ip="test")
        self.now += timedelta(minutes=2)
        self.service.start("new@example.test", client_ip="test")
        code = self.mail.deliveries[-1][1]
        self.now += timedelta(minutes=11)
        with self.assertRaises(HTTPException):
            self.service.verify("new@example.test", code, client_ip="test")

    async def test_start_rate_limit_survives_service_restart(self):
        self.service.start("limited@example.test", client_ip="test")
        restarted = AccountService(self.factory, self.settings, crypto=self.crypto, transport=self.mail, clock=lambda: self.now)
        with self.assertRaises(HTTPException) as caught:
            restarted.start("limited@example.test", client_ip="test")
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(len(self.mail.deliveries), 1)

    async def test_concurrent_otp_consumption_creates_only_one_session(self):
        self.service.start("concurrent@example.test", client_ip="issuer")
        code = self.mail.deliveries[-1][1]
        def attempt(ip):
            try:
                self.service.verify("concurrent@example.test", code, client_ip=ip)
                return 200
            except HTTPException as exc:
                return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, ["client1", "client2"]))
        self.assertEqual(sorted(outcomes), [200, 400])
        with self.factory() as db:
            self.assertEqual(len(db.execute(select(AccountSession)).scalars().all()), 1)

    async def test_missing_mail_configuration_and_cross_origin_write_fail(self):
        self.app.state.account_service = AccountService(self.factory, self.settings, crypto=self.crypto)
        response = await self.client.post("/api/account/login/start", json={"email": "x@example.test"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.mail.deliveries, [])
        self.app.state.account_service = self.service
        response = await self.client.post("/api/account/login/start", headers={"Origin": "http://evil.test"}, json={"email": "x@example.test"})
        self.assertEqual(response.status_code, 403)
        response = await self.client.post("/api/account/login/start", headers={"Sec-Fetch-Site": "cross-site"}, json={"email": "x@example.test"})
        self.assertEqual(response.status_code, 403)

    async def test_claim_requires_login_and_original_cookie_not_body_session_id(self):
        response = await self.client.post("/api/account/claim-browser", json={"session_id": "stolen"})
        self.assertEqual(response.status_code, 401)
        await self.login()
        calls = []
        async def claim(old, new):
            calls.append((old, new))
            return {"claimed": 2}
        self.app.state.claim_browser = claim
        response = await self.client.post("/api/account/claim-browser", json={"session_id": "stolen"})
        self.assertEqual(response.json()["claimed"], 0)
        self.assertEqual(calls, [])
        self.client.cookies.set("huhua_workspace", "a" * 43)
        response = await self.client.post("/api/account/claim-browser")
        self.assertEqual(response.json()["claimed"], 2)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1].startswith("account:"))
        self.assertNotEqual(calls[0][0], "a" * 43)

    async def test_production_origin_required_and_https_cookie(self):
        self.settings.APP_ENV = "production"
        self.settings.APP_ORIGIN = "https://service.test"
        self.settings.AUTH_COOKIE_SECURE = True
        response = await self.client.post("/api/account/login/start", json={"email": "x@example.test"})
        self.assertEqual(response.status_code, 403)
        response = await self.client.post("/api/account/login/start", headers={"Origin": "https://service.test"}, json={"email": "x@example.test"})
        self.assertEqual(response.status_code, 200)


class SecureCheckpointTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="huhua-checkpoint-security-")
        self.path = Path(self.directory.name) / "checkpoints.sqlite3"
        self.crypto = DataCrypto({"key": os.urandom(32)}, "key")
        self.context = AsyncSqliteSaver.from_conn_string(str(self.path))
        self.raw = await self.context.__aenter__()
        await self.raw.setup()
        self.secured = SecureCheckpointSaver(self.raw, self.crypto, lambda thread: "storage:one")

    async def asyncTearDown(self):
        await self.context.__aexit__(None, None, None)
        self.directory.cleanup()

    async def test_state_metadata_pending_writes_and_config_are_encrypted(self):
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"messages": [HumanMessage(content="PRIVATE_CHECKPOINT_MARKER")]}
        config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "user_private": "PRIVATE_CONFIG_MARKER"},
                  "metadata": {"personal": "PRIVATE_CONFIG_METADATA"}}
        stored = await self.secured.aput(config, checkpoint, {"source": "input", "step": 0, "name": "PRIVATE_METADATA_MARKER"}, {})
        await self.secured.aput_writes(stored, [("messages", "PRIVATE_PENDING_MARKER")], "task1")
        value = await self.secured.aget_tuple(stored)
        self.assertEqual(value.checkpoint, checkpoint)
        self.assertEqual(value.metadata["name"], "PRIVATE_METADATA_MARKER")
        self.assertEqual(value.pending_writes, [("task1", "messages", "PRIVATE_PENDING_MARKER")])
        self.assertEqual(len([item async for item in self.secured.alist(stored, filter={"name": "PRIVATE_METADATA_MARKER"})]), 1)
        async with self.raw.conn.execute("SELECT checkpoint, metadata FROM checkpoints") as cursor:
            rows = await cursor.fetchall()
        async with self.raw.conn.execute("SELECT value FROM writes") as cursor:
            rows += await cursor.fetchall()
        for row in rows:
            for part in row:
                self.assertNotIn(b"PRIVATE_", part.encode() if isinstance(part, str) else part)
        other = SecureCheckpointSaver(self.raw, self.crypto, lambda thread: "storage:other")
        with self.assertRaises(DataDecryptionError):
            await other.aget_tuple(stored)

    async def test_real_langgraph_async_resume_survives_new_adapter(self):
        class State(TypedDict):
            text: str
            count: int
        builder = StateGraph(State)
        builder.add_node("append", lambda state: {"text": state["text"] + "!", "count": state["count"] + 1})
        builder.add_edge(START, "append")
        builder.add_edge("append", END)
        graph = builder.compile(checkpointer=self.secured)
        config = {"configurable": {"thread_id": "graph"}}
        first = await graph.ainvoke({"text": "PRIVATE_GRAPH_MARKER", "count": 0}, config)
        self.assertEqual(first["count"], 1)
        restarted = builder.compile(checkpointer=SecureCheckpointSaver(self.raw, self.crypto, lambda thread: "storage:one"))
        state = await restarted.aget_state(config)
        self.assertEqual(state.values, first)
        updated = await restarted.ainvoke({"text": first["text"], "count": first["count"]}, config)
        self.assertEqual(updated["count"], 2)
        await self.secured.adelete_thread("graph")
        self.assertIsNone(await self.secured.aget_tuple(config))

    async def test_plaintext_checkpoints_rejected_when_encryption_enabled(self):
        checkpoint = empty_checkpoint()
        config = {"configurable": {"thread_id": "plain", "checkpoint_ns": ""}}
        await self.raw.aput(config, checkpoint, {"step": 0}, {})
        with self.assertRaises(DataDecryptionError):
            await self.secured.aget_tuple(config)

    async def test_checkpoint_copy_migration_encrypts_all_and_rotates(self):
        spec = importlib.util.spec_from_file_location("checkpoint_operations", ROOT / "backend/scripts/security_migrate.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"text": "PRIVATE_MIGRATION_MARKER"}
        config = {"configurable": {"thread_id": "legacy", "checkpoint_ns": ""}}
        saved = await self.raw.aput(config, checkpoint, {"private": "PRIVATE_MIGRATION_META"}, {})
        await self.raw.aput_writes(saved, [("text", "PRIVATE_MIGRATION_PENDING")], "task-1")
        migrated = Path(self.directory.name) / "migrated.sqlite3"
        result = await module.checkpoint_migrate(self.path, migrated, {"legacy": "storage:one"}, self.crypto)
        self.assertEqual(result["checkpoints_verified"], 1)
        self.assertNotIn(b"PRIVATE_MIGRATION", migrated.read_bytes())
        rotated = DataCrypto({**self.crypto.keys, "next": os.urandom(32)}, "next")
        rotated_path = Path(self.directory.name) / "rotated.sqlite3"
        await module.checkpoint_migrate(migrated, rotated_path, {"legacy": "storage:one"}, rotated)
        async with AsyncSqliteSaver.from_conn_string(str(rotated_path)) as raw:
            adapter = SecureCheckpointSaver(raw, DataCrypto({"next": rotated.keys["next"]}, "next"), lambda _: "storage:one")
            value = await adapter.aget_tuple(config)
            self.assertEqual(value.checkpoint, checkpoint)
            self.assertEqual(value.pending_writes, [("task-1", "text", "PRIVATE_MIGRATION_PENDING")])


class BackupTest(unittest.TestCase):
    def test_unknown_database_backup_and_restore_without_privacy_anchor_are_refused(self):
        spec = importlib.util.spec_from_file_location("security_operations", ROOT / "backend/scripts/security_migrate.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="huhua-backup-test-") as directory:
            root = Path(directory)
            source, target, restored = root / "source.sqlite3", root / "encrypted.backup", root / "restored.sqlite3"
            with closing(sqlite3.connect(source)) as db:
                db.execute("CREATE TABLE examples (value TEXT)")
                db.execute("INSERT INTO examples VALUES ('PRIVATE_BACKUP_MARKER')")
                db.commit()
            crypto = DataCrypto({"key": os.urandom(32)}, "key")
            with self.assertRaises(ValueError):
                module.backup(source, target, crypto)
            self.assertFalse(target.exists())
            with self.assertRaises(ValueError):
                module.restore(target, restored, crypto)
            self.assertFalse(restored.exists())

    def test_application_copy_migration_fresh_pages_null_fields_rotation(self):
        spec = importlib.util.spec_from_file_location("app_operations", ROOT / "backend/scripts/security_migrate.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="huhua-app-migration-") as directory:
            root = Path(directory)
            source, target, rotated_path = root / "source.sqlite3", root / "target.sqlite3", root / "rotated.sqlite3"
            with closing(sqlite3.connect(source)) as db:
                db.execute("CREATE TABLE resume_sessions (session_id TEXT PRIMARY KEY, resume_data JSON, resume_draft TEXT, stage TEXT, updated_at DATETIME)")
                db.execute("CREATE TABLE conversations (session_id TEXT PRIMARY KEY, owner_hash TEXT, title TEXT, created_at DATETIME)")
                db.execute("CREATE TABLE resume_suggestions (id TEXT PRIMARY KEY, owner TEXT, session_id TEXT, status TEXT, payload JSON, created_at DATETIME)")
                db.execute("INSERT INTO resume_sessions VALUES ('session', ?, NULL, 'BUILDING', '2026-10-04 00:00:00')", (json.dumps({"name": "PRIVATE_APP_MIGRATION"}),))
                db.execute("INSERT INTO resume_sessions VALUES ('empty', 'null', NULL, 'JD_INPUT', '2026-10-04 00:00:00')")
                db.execute("INSERT INTO conversations VALUES ('session', 'storage:one', 'PRIVATE_APP_TITLE', '2026-10-04 00:00:00')")
                db.execute("INSERT INTO resume_suggestions VALUES ('suggestion', 'storage:one', 'session', 'pending', ?, '2026-10-04 00:00:00')", (json.dumps({"suggested_text": "PRIVATE_APP_SUGGESTION"}),))
                db.commit()
            before = source.read_bytes()
            crypto = DataCrypto({"one": os.urandom(32)}, "one")
            result = module.application_migrate(source, target, {"empty": "storage:one"}, crypto)
            self.assertEqual(result["tables_verified"]["resume_sessions"], 2)
            self.assertEqual(source.read_bytes(), before)
            self.assertNotIn(b"PRIVATE_APP", target.read_bytes())
            with closing(sqlite3.connect(target)) as db:
                value, draft, owner = db.execute("SELECT resume_data,resume_draft,owner_key FROM resume_sessions WHERE session_id='session'").fetchone()
                self.assertEqual(owner, "storage:one")
                self.assertEqual(crypto.decrypt_json(json.loads(value), owner=owner, record="session", field="resume_data"), {"name": "PRIVATE_APP_MIGRATION"})
                self.assertEqual(crypto.decrypt_text(draft, owner=owner, record="session", field="resume_draft"), "")
            rotated = DataCrypto({**crypto.keys, "next": os.urandom(32)}, "next")
            module.application_migrate(target, rotated_path, {}, rotated)
            with closing(sqlite3.connect(rotated_path)) as db:
                value = json.loads(db.execute("SELECT resume_data FROM resume_sessions WHERE session_id='session'").fetchone()[0])
                self.assertEqual(value["kid"], "next")
                self.assertEqual(DataCrypto({"next": rotated.keys["next"]}, "next").decrypt_json(value, owner="storage:one", record="session", field="resume_data"), {"name": "PRIVATE_APP_MIGRATION"})
                suggestion = json.loads(db.execute("SELECT payload FROM resume_suggestions WHERE id='suggestion'").fetchone()[0])
                self.assertEqual(suggestion["kid"], "next")
                self.assertEqual(DataCrypto({"next": rotated.keys["next"]}, "next").decrypt_json(suggestion, owner="storage:one", record="suggestion", field="suggestion"), {"suggested_text": "PRIVATE_APP_SUGGESTION"})


if __name__ == "__main__":
    unittest.main()
