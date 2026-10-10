"""Editor persistence regressions use an isolated database and no model calls."""

import asyncio
import copy
import hashlib
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi import HTTPException, Request
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.resume_graph import _init_state, build_graph
from app.api.resume import SaveResumeRequest, current_resume, save_current_resume
from app.database import Base
from app.models.models import Conversation, ResumeSession
from app.schemas.editor import ResumeData
from app.services.canonical_resume import resume_revision
from app.services.session_store import DELETED_STAGE, load_resume_session, save_resume_session
from app.services.data_crypto import DataCrypto


def candidate():
    return ResumeData.model_validate({
        "basic_info": {"name": "测试候选人", "email": "demo@example.test", "birthday": "2004.05", "photo": "data:image/png;base64,dGVzdA=="},
        "education": [{"school": "示例大学", "start_date": "2023.09", "end_date": "2027.06", "highlights": "课程作业"}],
        "work_experience": [{"company": "示例公司", "title": "实习", "bullets": ["协助整理用户反馈"]}],
        "projects": [{"name": "课程原型", "description": "旧描述", "polished_bullets": ["画了5个界面，未上线"]}],
        "skill_groups": {"工具": ["Excel"]}, "certificates": ["示例证书"],
        "verification_notes": ["教育时间需要核对"],
        "sections": [{"id": "custom-awards", "kind": "custom", "title": "竞赛", "content": "校级获奖"},
                     {"id": "projects", "kind": "projects", "title": "课程项目"}],
    }).model_dump()


class EditorPersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.graph = build_graph(object(), checkpointer=MemorySaver())
        self.cookie = "test-persistence-cookie-" + "x" * 32
        self.owner = hashlib.sha256(self.cookie.encode()).hexdigest()
        self.request = Request({"type": "http", "method": "GET", "path": "/", "scheme": "http",
                                "headers": [(b"cookie", ("huhua_workspace=" + self.cookie).encode())],
                                "server": ("testserver", 80)})
        settings = SimpleNamespace(LLM_API_KEY="unit-test-placeholder", SESSION_RETENTION_DAYS=7,
                                   APP_ENV="local", REQUIRE_ACCOUNT=False)
        crypto = DataCrypto({"test": b"x" * 32}, "test")
        self.patches = [
            patch("app.services.session_store.SessionLocal", self.factory),
            patch("app.services.canonical_resume.SessionLocal", self.factory),
            patch("app.services.conversation_store.SessionLocal", self.factory),
            patch("app.config.get_settings", return_value=settings),
            patch("app.services.data_crypto.get_crypto", return_value=crypto),
            patch("app.services.session_store.get_settings", return_value=settings),
            patch("app.api.resume.get_settings", return_value=settings),
            patch("app.api.resume._llm_for_graph", return_value=object()),
            patch("app.api.resume.get_graph", return_value=self.graph),
        ]
        for item in self.patches:
            item.start()
        self.addAsyncCleanup(self.cleanup)

    async def cleanup(self):
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()

    def seed(self, session="live", data=None, stage="COLLECTING", updated=None):
        with self.factory() as db:
            db.add(ResumeSession(session_id=session, owner_key=self.owner, resume_data=data or {}, stage=stage,
                                 updated_at=updated or datetime.now(UTC).replace(tzinfo=None)))
            db.add(Conversation(session_id=session, owner_hash=self.owner, title="隔离测试"))
            db.commit()

    async def checkpoint(self, data, session="live", **kwargs):
        values = {**_init_state(), "resume_data": data, "stage": "EVALUATING", **kwargs}
        await self.graph.aupdate_state({"configurable": {"thread_id": session}}, values, as_node="building")

    async def save(self, data, revision=None, session="live"):
        if revision is None:
            revision = (await current_resume(self.request, session))["revision"]
        return await save_current_resume(SaveResumeRequest(session_id=session, expected_revision=revision, resume_data=data), self.request)

    async def test_edits_survive_refresh_and_append_chat_facts(self):
        original = candidate()
        self.seed(data=original)
        await self.checkpoint(original, collected_info={"internship": [{"company": "旧实习"}]})
        edited = copy.deepcopy(original)
        edited["basic_info"]["name"] = "已编辑姓名"
        edited["projects"][0]["polished_bullets"] = ["完成5个静态界面，未上线"]
        result = await self.save(edited)
        current = await current_resume(self.request, "live")
        self.assertTrue(result["saved"])
        self.assertEqual(current["data"], result["data"])
        self.assertEqual(current["revision"], result["revision"])
        self.assertEqual(load_resume_session("live")["resume_data"], result["data"])
        checkpoint = await self.graph.aget_state({"configurable": {"thread_id": "live"}})
        facts = checkpoint.values["collected_info"]
        self.assertEqual(facts["basic_info"]["name"], "已编辑姓名")
        self.assertIn("完成5个静态界面，未上线", [f["text"] for f in facts["projects"][0]["facts"]])
        self.assertEqual(facts["internship"][0]["company"], "旧实习")
        self.assertEqual(current["data"]["sections"][0]["kind"], "custom")
        self.assertEqual(current["data"]["skill_groups"], {"工具": ["Excel"]})
        self.assertEqual(current["data"]["verification_notes"], edited["verification_notes"])
        self.assertNotIn("旧描述", checkpoint.values["resume_draft"])

    async def test_stale_simultaneous_saves_cannot_overwrite_each_other(self):
        self.seed(data=candidate())
        await self.checkpoint(candidate())
        revision = (await current_resume(self.request, "live"))["revision"]
        first, second = candidate(), candidate()
        first["basic_info"]["name"] = "第一编辑页"
        second["basic_info"]["name"] = "第二编辑页"
        outcomes = await asyncio.gather(self.save(first, revision), self.save(second, revision), return_exceptions=True)
        self.assertEqual(sum(isinstance(item, dict) for item in outcomes), 1)
        conflict = next(item for item in outcomes if isinstance(item, HTTPException))
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual((await current_resume(self.request, "live"))["data"]["basic_info"]["name"], "第一编辑页")

    async def test_committed_chat_change_invalidates_editor_revision(self):
        original = candidate()
        self.seed(data=original)
        revision = (await current_resume(self.request, "live"))["revision"]
        changed = copy.deepcopy(original)
        changed["projects"][0]["polished_bullets"] = ["聊天中明确更新"]
        await self.checkpoint(changed)
        save_resume_session("live", changed, stage="EVALUATING")
        with self.assertRaises(HTTPException) as caught:
            await self.save(original, revision)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail["revision"], resume_revision(changed))

    async def test_checkpoint_ahead_of_committed_row_is_not_reported_saved(self):
        original = candidate()
        self.seed(data=original)
        changed = copy.deepcopy(original)
        changed["basic_info"]["name"] = "未提交的图状态"
        await self.checkpoint(changed)
        current = await current_resume(self.request, "live")
        self.assertEqual(current["data"], original)
        self.assertEqual(current["revision"], resume_revision(original))

    async def test_unknown_deleted_and_expired_sessions_never_reappear(self):
        self.seed("deleted", stage=DELETED_STAGE)
        self.seed("expired", updated=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=8))
        for session in ("unknown", "deleted", "expired"):
            with self.subTest(session=session):
                with self.assertRaises(HTTPException) as read:
                    await current_resume(self.request, session)
                self.assertEqual(read.exception.status_code, 404)
                with self.assertRaises(HTTPException) as caught:
                    await self.save(candidate(), "0" * 64, session)
                self.assertEqual(caught.exception.status_code, 404)
        with self.factory() as db:
            self.assertIsNone(db.get(ResumeSession, "unknown"))
            self.assertEqual(db.get(ResumeSession, "deleted").stage, DELETED_STAGE)

    async def test_temporary_database_failure_is_not_misreported_as_deleted(self):
        self.seed()
        with patch("app.api.resume.session_can_read_checkpoint", return_value=False), \
             patch("app.services.canonical_resume.SessionLocal", side_effect=RuntimeError("storage temporarily unavailable")):
            with self.assertRaises(HTTPException) as read:
                await current_resume(self.request, "live")
            with self.assertRaises(HTTPException) as write:
                await self.save(candidate(), "0" * 64)
        self.assertEqual(read.exception.status_code, 503)
        self.assertEqual(write.exception.status_code, 503)
        self.assertEqual(load_resume_session("live")["stage"], "COLLECTING")

    async def test_blank_valid_session_can_start_without_a_checkpoint(self):
        self.seed(stage="JD_INPUT")
        result = await self.save(candidate())
        self.assertTrue(result["saved"])
        self.assertTrue((await current_resume(self.request, "live"))["has_data"])

    async def test_saved_checkpoint_survives_reopening_the_durable_graph(self):
        self.seed(data=candidate())
        with tempfile.TemporaryDirectory(prefix="huhua-editor-test-") as directory:
            path = str(Path(directory) / "isolated-checkpoints.sqlite3")
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                self.graph = build_graph(object(), checkpointer=saver)
                self.patches[-1].stop()
                with patch("app.api.resume.get_graph", return_value=self.graph):
                    await self.checkpoint(candidate())
                    result = await self.save(candidate())
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                restored_graph = build_graph(object(), checkpointer=saver)
                with patch("app.api.resume.get_graph", return_value=restored_graph):
                    current = await current_resume(self.request, "live")
                checkpoint = await restored_graph.aget_state({"configurable": {"thread_id": "live"}})
                self.assertEqual(current["revision"], result["revision"])
                self.assertEqual(current["data"]["sections"], candidate()["sections"])
                self.assertEqual(checkpoint.values["collected_info"], load_resume_session("live")["collected_info"])
                self.assertNotIn("画了5个界面，未上线", str(checkpoint.values["collected_info"].get("projects", [])))

    async def test_database_reads_and_form_saves_do_not_require_a_model_key(self):
        self.seed(data=candidate())
        await self.checkpoint(candidate(), jd_text="产品岗位要求访谈分析")
        offline = SimpleNamespace(LLM_API_KEY="", SESSION_RETENTION_DAYS=0)
        with patch("app.api.resume.get_settings", return_value=offline):
            current = await current_resume(self.request, "live")
            self.assertTrue(current["can_save"])
            self.assertTrue(current["has_jd"])
            edited = candidate()
            edited["basic_info"]["name"] = "离线手动编辑"
            self.assertTrue((await self.save(edited))["saved"])
        self.assertEqual(load_resume_session("live")["resume_data"]["basic_info"]["name"], "离线手动编辑")

    async def test_missing_conversation_checkpoint_cannot_be_silently_overwritten(self):
        self.seed(data=candidate())
        current = await current_resume(self.request, "live")
        self.assertTrue(current["has_data"])
        self.assertFalse(current["can_save"])
        with self.assertRaises(HTTPException) as caught:
            await self.save(candidate())
        self.assertEqual(caught.exception.status_code, 503)

    async def test_cleared_canonical_never_revives_removed_fields(self):
        self.seed(data=candidate())
        await self.checkpoint(candidate(), messages=[HumanMessage(content="我做过旧项目", id="old")],
                              collected_info={"basic_info": {"name": "旧姓名"}, "projects": [{"name": "旧项目"}]})
        empty = ResumeData(sections=[]).model_dump()
        await self.save(empty)
        current = await current_resume(self.request, "live")
        self.assertFalse(current["has_data"])
        self.assertIsNone(current["data"])
        self.assertEqual(current["revision"], resume_revision(empty))
        self.assertEqual(load_resume_session("live")["resume_data"]["sections"], [])

    async def test_contact_skill_and_custom_only_drafts_are_readable(self):
        for data in ({"basic_info": {"email": "a@example.test"}}, {"skills": ["Excel"]},
                     {"sections": [{"id": "c", "kind": "custom", "title": "其他", "content": "课程成果"}]}):
            self.seed("variant", data=ResumeData.model_validate(data).model_dump())
            self.assertTrue((await current_resume(self.request, "variant"))["has_data"])
            with self.factory() as db:
                db.delete(db.get(Conversation, "variant"))
                db.delete(db.get(ResumeSession, "variant"))
                db.commit()

    async def test_row_commit_failure_restores_checkpoint_and_returns_failure(self):
        original = candidate()
        self.seed(data=original)
        await self.checkpoint(original)
        changed = copy.deepcopy(original)
        changed["basic_info"]["name"] = "不能假装保存成功"
        real_session = self.factory()
        with patch.object(real_session, "commit", side_effect=RuntimeError("simulated disk failure")), \
             patch("app.services.canonical_resume.SessionLocal", return_value=real_session):
            with self.assertRaises(HTTPException) as caught:
                await self.save(changed)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual((await current_resume(self.request, "live"))["data"], original)
        self.assertEqual(load_resume_session("live")["resume_data"], original)


if __name__ == "__main__":
    unittest.main()
