"""Archive acceptance cases use synthetic people, temporary SQLite and fake LLMs."""

import asyncio
import hashlib
import hmac
import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents.profile_archivist import ArchiveBatch, ArchiveProposal, make_archivist, validate_grounding
from app.api import profile as profile_api
from app.database import Base, get_db
from app.models.profile import ProfileArchiveEvent, ProfileFact, ProfileSource
from app.services.account_service import AccountPrincipal
from app.services.data_crypto import DataCrypto, DataDecryptionError
from app.services import profile_service as archive
from app.services.profile_bridge import ClaimedHistoryImport


class ArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="huhua-profile-")
        self.path = Path(self.tmp.name) / "test.sqlite3"
        self.engine = create_engine(f"sqlite:///{self.path}")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.crypto = DataCrypto({"test": b"x" * 32}, "test")
        self.patches = [
            patch.object(archive, "get_crypto", return_value=self.crypto),
            patch.object(archive, "blind_index", side_effect=lambda value, scope: hmac.new(
                b"index-test-only" * 3, (scope + value).encode(), hashlib.sha256).hexdigest()),
        ]
        for item in self.patches:
            item.start()
        self.app = FastAPI()
        self.app.include_router(profile_api.router, prefix="/api/profile")

        def db_override():
            with self.factory() as db:
                yield db

        def principal(request):
            account_id = request.headers.get("x-test-account")
            if not account_id:
                raise HTTPException(401)
            return AccountPrincipal(account_id, f"{account_id}@example.test")

        self.app.dependency_overrides[get_db] = db_override
        self.auth_patch = patch.object(profile_api, "require_account", side_effect=principal)
        self.auth_patch.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.auth_patch.stop()
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()
        self.tmp.cleanup()

    def add(self, *, account="a", category="project", subject="测试项目", field="role", value="后端参与者", **kwargs):
        with self.factory() as db:
            result = archive.add_fact(db, account, category=category, subject=subject, field=field, value=value, **kwargs)
            db.commit()
            return next(f for f in result["facts"] + result["preferences"]
                        if f["field"] == field and f["subject"] == ("本人" if category == "basic" else subject) and f["category"] == category
                        and (field not in {"link", "github", "website"} or f["value"] == value))

    def profile(self, account="a"):
        with self.factory() as db:
            result = archive.get_profile(db, account)
            db.commit()
            return result

    def event(self, text, *, source_id="message-1", account="a", source_kind="self", session="chat-1", **extra):
        recorded_at = extra.pop("recorded_at", None)
        with self.factory() as db:
            event = archive.enqueue_archive_event(db, account, source_id, session,
                                                  {"human_text": text, "source_kind": source_kind, **extra},
                                                  recorded_at=recorded_at)
            event_id = event.id
            db.commit()
            return event_id

    async def run_proposals(self, proposals):
        async def extractor(payload, context):
            return ArchiveBatch(proposals=proposals)
        return await archive.process_pending_events(self.factory, extractor)

    def proposal(self, value, *, field="role", category="project", subject="测试项目", **kwargs):
        return ArchiveProposal(category=category, subject=subject, field=field, value=value,
                               evidence_quote=value, **kwargs)

    async def test_one_account_one_profile_and_isolation(self):
        first = self.profile()
        self.assertEqual(first["profile_id"], self.profile()["profile_id"])
        self.assertNotEqual(first["profile_id"], self.profile("b")["profile_id"])
        self.add(value="synthetic-private-marker")
        self.assertEqual(self.profile("b")["facts"], [])

    async def test_rows_encrypt_values_subjects_sources_and_preferences(self):
        self.add(subject="secret-project-marker", value="private-role-marker")
        self.add(category="preference", subject="表达", field="preference", value="私密偏好标记")
        self.event("这是一条私密来源标记", source_id="raw-msg")
        data = self.path.read_bytes()
        for marker in ["secret-project-marker", "private-role-marker", "私密偏好标记", "私密来源标记"]:
            self.assertNotIn(marker.encode(), data)
        with self.factory() as db:
            source = db.scalar(select(ProfileSource))
            with self.assertRaises(DataDecryptionError):
                self.crypto.decrypt_text(source.payload, owner="account:b", record=source.id, field="payload")

    async def test_atomic_source_outbox_rollback(self):
        with self.factory() as db:
            archive.enqueue_archive_event(db, "a", "not-saved", "chat", {"human_text": "王小明", "source_kind": "self"})
            db.rollback()
        with self.factory() as db:
            self.assertIsNone(db.scalar(select(ProfileSource)))
            self.assertIsNone(db.scalar(select(ProfileArchiveEvent)))

    async def test_idempotent_event_and_duplicate_mentions_keep_revision(self):
        text = "测试项目里我是后端参与者"
        event_id = self.event(text)
        self.assertEqual(event_id, self.event(text))
        await self.run_proposals([self.proposal("后端参与者")])
        fact = self.profile()["facts"][0]
        self.event(text, source_id="message-2")
        await self.run_proposals([self.proposal("后端参与者")])
        new = self.profile()["facts"][0]
        self.assertEqual((new["id"], new["revision"]), (fact["id"], fact["revision"]))
        self.assertEqual(len(new["sources"]), 2)
        self.assertEqual(new["source_type"], "user_provided")

    async def test_same_message_id_cannot_change_content(self):
        self.event("第一次输入")
        with self.assertRaises(archive.ProfileValidationError):
            self.event("替换之前来源")

    async def test_jd_reference_and_ai_never_become_user_facts(self):
        for index, kind in enumerate(("jd", "reference", "ai", "unknown")):
            self.event("测试项目我负责后端", source_id=f"m-{index}", source_kind=kind)
        answer = await self.run_proposals([self.proposal("负责后端")])
        self.assertEqual(answer["completed"], 0)
        self.assertEqual(self.profile()["facts"], [])

    async def test_deterministic_basic_fields_require_original_evidence(self):
        self.event("我叫测试小安", collected_info_delta={"basic_info": {"name": "测试小安", "phone": "18800008888"},
                                                      "projects": [{"name": "夸大项目", "role": "负责人"}]})
        await archive.process_pending_events(self.factory)
        facts = self.profile()["facts"]
        self.assertEqual([(f["field"], f["value"]) for f in facts], [("name", "测试小安")])

    async def test_contradiction_requires_versioned_resolution(self):
        fact = self.add(value="项目负责人")
        self.event("测试项目中我是后端参与者")
        await self.run_proposals([self.proposal("后端参与者")])
        profile = self.profile()
        self.assertEqual(profile["facts"][0]["value"], "项目负责人")
        conflict = profile["conflicts"][0]
        with self.factory() as db:
            archive.resolve_conflict(db, "a", conflict["id"], choice="replace", expected_revision=fact["revision"])
            db.commit()
        self.assertEqual(self.profile()["facts"][0]["value"], "后端参与者")
        with self.factory() as db:
            with self.assertRaises(archive.ProfileRevisionConflict):
                archive.resolve_conflict(db, "a", conflict["id"], choice="keep", expected_revision=fact["revision"])

    async def test_explicit_correction_overrides_repetition_and_blocks_old_source(self):
        fact = self.add(value="项目负责人")
        self.event("更正，测试项目中我实际是后端参与者", subject_ids=[fact["id"]])
        await self.run_proposals([self.proposal("后端参与者", operation="correct", expected_revision=fact["revision"])])
        self.assertEqual(self.profile()["facts"][0]["value"], "后端参与者")
        with self.factory() as db:
            clean, changed = archive.sanitize_projection(db, "a", {"resume": "担任项目负责人", "current": "后端参与者"})
            self.assertTrue(changed)
            self.assertEqual(clean, {"resume": "", "current": "后端参与者"})

    async def test_old_event_cannot_override_new_manual_correction(self):
        fact = self.add(value="项目负责人")
        self.event("更正测试项目中实际是其他职责", recorded_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1))
        with self.factory() as db:
            archive.edit_fact(db, "a", fact["id"], value="后端参与者", expected_revision=1)
            db.commit()
        await self.run_proposals([self.proposal("其他职责", operation="correct", expected_revision=2)])
        self.assertEqual(self.profile()["facts"][0]["value"], "后端参与者")

    async def test_earlier_effective_state_does_not_replace_later_launch(self):
        fact = self.add(field="status", value="已经上线", effective_at=datetime(2026, 10, 1))
        self.event("测试项目在2026-08-01只有Demo", subject_ids=[fact["id"]])
        await self.run_proposals([self.proposal("只有Demo", field="status", effective_at=datetime(2026, 8, 1), operation="state_change")])
        new = self.profile()["facts"][0]
        self.assertEqual(new["value"], "已经上线")
        self.assertEqual(new["history"][0]["value"], "只有Demo")
        with self.factory() as db:
            context = archive.get_context(db, "a", subject_ids=[fact["id"]])
        self.assertNotIn("history", context["facts"][0])

    async def test_later_effective_state_changes_current(self):
        fact = self.add(field="status", value="尚未上线", effective_at=datetime(2026, 9, 1))
        self.event("测试项目在2026-10-01已经上线", subject_ids=[fact["id"]])
        await self.run_proposals([self.proposal("已经上线", field="status", effective_at=datetime(2026, 10, 1), operation="state_change")])
        self.assertEqual(self.profile()["facts"][0]["value"], "已经上线")

    async def test_deletion_blocks_pending_old_jobs_and_new_restatement(self):
        fact = self.add(value="秘密职责")
        self.event("测试项目的秘密职责", source_id="old-pending")
        with self.factory() as db:
            archive.delete_fact(db, "a", fact["id"], fact["revision"])
            db.commit()
        await self.run_proposals([self.proposal("秘密职责")])
        self.event("测试项目的秘密职责", source_id="another-old")
        await self.run_proposals([self.proposal("秘密职责")])
        self.assertEqual(self.profile()["facts"], [])
        with self.factory() as db:
            clean, changed = archive.sanitize_projection(db, "a", {"resume_data": {"description": "曾从事秘密职责"}})
        self.assertTrue(changed)
        self.assertEqual(clean["resume_data"]["description"], "")
        # Explicit user re-entry is distinct from a queued model proposal.
        restored = self.add(value="重新明确的职责")
        self.assertEqual(restored["id"], fact["id"])
        self.assertGreater(restored["revision"], fact["revision"])

    async def test_delete_while_extractor_waits_does_not_resurrect(self):
        fact = self.add()
        self.event("测试项目的后端参与者")
        async def extractor(payload, context):
            with self.factory() as db:
                archive.delete_fact(db, "a", fact["id"], fact["revision"])
                db.commit()
            return ArchiveBatch(proposals=[self.proposal("后端参与者")])
        await archive.process_pending_events(self.factory, extractor)
        self.assertEqual(self.profile()["facts"], [])

    async def test_stale_fact_and_profile_revision_rejected(self):
        fact = self.add()
        with self.factory() as stale:
            stale_profile = archive.ensure_profile(stale, "a")
            with self.factory() as fresh:
                archive.edit_fact(fresh, "a", fact["id"], value="新职责", expected_revision=1)
                fresh.commit()
            with self.assertRaises(archive.ProfileRevisionConflict):
                archive._bump(stale, stale_profile)
            stale.rollback()
        with self.factory() as db:
            with self.assertRaises(archive.ProfileRevisionConflict):
                archive.edit_fact(db, "a", fact["id"], value="过期覆盖", expected_revision=1)

    async def test_failed_task_can_be_retried_and_repeated_worker_is_idempotent(self):
        event_id = self.event("测试项目的后端参与者")
        async def broken(payload, context):
            raise RuntimeError("private error must never appear in status")
        self.assertEqual((await archive.process_pending_events(self.factory, broken))["failed"], 1)
        task = self.profile()["archive_status"]["tasks"][0]
        self.assertEqual(task["error_code"], "archive_model_error")
        with self.factory() as db:
            archive.retry_task(db, "a", event_id)
            db.commit()
        self.assertEqual((await self.run_proposals([self.proposal("后端参与者")]))["completed"], 1)
        self.assertEqual((await self.run_proposals([self.proposal("后端参与者")]))["completed"], 0)
        self.assertEqual(len(self.profile()["facts"]), 1)

    async def test_timeout_and_expired_lease_recovery(self):
        event_id = self.event("测试项目的后端参与者")
        async def slow(payload, context):
            await asyncio.sleep(1)
        await archive.process_pending_events(self.factory, slow, timeout_seconds=0.01)
        self.assertEqual(self.profile()["archive_status"]["tasks"][0]["error_code"], "archive_timeout")
        with self.factory() as db:
            row = db.get(ProfileArchiveEvent, event_id)
            row.status = "running"
            row.available_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=5)
            row.lease_until = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
            db.commit()
        self.assertEqual((await self.run_proposals([self.proposal("后端参与者")]))["completed"], 1)

    async def test_compensation_repairs_missing_event_once(self):
        event_id = self.event("我叫测试小安", collected_info_delta={"basic_info": {"name": "测试小安"}})
        with self.factory() as db:
            db.execute(delete(ProfileArchiveEvent).where(ProfileArchiveEvent.id == event_id))
            db.commit()
        with self.factory() as db:
            self.assertEqual(archive.compensate_archive_events(db), 1)
            db.commit()
        with self.factory() as db:
            self.assertEqual(archive.compensate_archive_events(db), 0)
        await archive.process_pending_events(self.factory)
        self.assertEqual(self.profile()["facts"][0]["value"], "测试小安")

    async def test_context_requires_project_selection_and_excludes_contacts(self):
        project = self.add()
        self.add(category="basic", subject="基础信息", field="name", value="测试小安")
        self.add(category="basic", subject="基础信息", field="phone", value="18800008888")
        with self.factory() as db:
            context = archive.get_context(db, "a")
            selected = archive.get_context(db, "a", subject_ids=[project["id"]])
            other = archive.get_context(db, "b", subject_ids=[project["id"]])
        self.assertEqual([f["field"] for f in context["facts"]], ["name"])
        self.assertEqual(selected["facts"][0]["id"], project["id"])
        self.assertEqual(other["facts"], [])
        merged = archive.context_to_collected_info(selected, {"projects": [{"name": "测试项目", "role": "用户当前编辑"}]})
        self.assertEqual(merged["projects"][0]["role"], "用户当前编辑")

    async def test_job_reference_stale_after_correction_not_removal(self):
        fact = self.add()
        with self.factory() as db:
            job = archive.save_job_version(db, "a", session_id="chat", name="产品岗位")
            db.commit()
        with self.factory() as db:
            archive.save_job_version(db, "a", session_id="chat", name="产品岗位", fact_refs=[])
            db.commit()
        self.assertEqual(len(self.profile()["facts"]), 1)
        with self.factory() as db:
            archive.save_job_version(db, "a", session_id="chat", name="产品岗位", fact_refs=job["fact_refs"])
            archive.edit_fact(db, "a", fact["id"], value="后端开发", expected_revision=1)
            db.commit()
        self.assertTrue(self.profile()["jobs"][0]["stale"])

    async def test_delete_source_retains_already_archived_fact_but_blocks_reimport(self):
        self.event("测试项目我是后端参与者")
        await self.run_proposals([self.proposal("后端参与者")])
        with self.factory() as db:
            archive.disable_session_sources(db, "a", "chat-1")
            db.commit()
        self.assertEqual(self.profile()["facts"][0]["value"], "后端参与者")
        self.assertEqual(self.profile()["facts"][0]["sources"], [])
        self.assertEqual((await self.run_proposals([self.proposal("后端参与者")]))["completed"], 0)

    async def test_two_workers_claim_event_only_once(self):
        self.event("测试项目我是后端参与者")
        calls = 0
        async def extractor(payload, context):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return ArchiveBatch(proposals=[self.proposal("后端参与者")])
        await asyncio.gather(archive.process_pending_events(self.factory, extractor),
                             archive.process_pending_events(self.factory, extractor))
        self.assertEqual(calls, 1)
        self.assertEqual(len(self.profile()["facts"]), 1)

    async def test_ten_source_quality_cases(self):
        cases = [
            ("测试项目尚未上线", "上线", False),
            ("测试项目尚未上线", "尚未上线", True),
            ("测试项目计划上线", "上线", False),
            ("测试项目计划上线", "计划上线", True),
            ("测试项目仅做后端", "后端", False),
            ("测试项目仅做后端", "仅做后端", True),
            ("测试项目打算重构", "重构", False),
            ("测试项目打算重构", "打算重构", True),
            ("测试项目用户反馈不错", "提升效率80%", False),
            ("测试项目完成演示", "完成演示", True),
        ]
        for text, value, expected in cases:
            with self.subTest(text=text, value=value):
                proposal = self.proposal(value)
                proposal.evidence_quote = text
                self.assertEqual(validate_grounding(proposal, {"human_text": text, "source_kind": "self"}, {"facts": []}), expected)

    async def test_short_quote_cannot_strip_negation_or_attribute_others(self):
        for text, value in (("测试项目尚未上线", "上线"),
                            ("测试项目我不是负责人", "负责人"),
                            ("请写测试项目已经上线", "已经上线"),
                            ("我朋友是测试项目的负责人", "负责人")):
            proposal = self.proposal(value)
            self.assertFalse(validate_grounding(proposal, {"human_text": text, "source_kind": "self"}, {}))
        self.assertTrue(validate_grounding(self.proposal("已经上线"),
                                          {"human_text": "测试项目之前尚未上线，现在已经上线", "source_kind": "self"}, {}))

    async def test_api_invalid_category_field_returns_validation_error(self):
        response = await self.client.post("/api/profile/facts", headers={"x-test-account": "a"},
                                          json={"category": "basic", "field": "role", "subject": "基本资料", "value": "负责人"})
        self.assertEqual(response.status_code, 422)

    async def test_short_lived_preferences_are_not_long_term_memory(self):
        proposal = self.proposal("中文", category="preference", subject="表达", field="preference", long_term_preference=True)
        self.assertFalse(validate_grounding(proposal, {"source_kind": "self", "human_text": "这次使用中文"}, {}))
        self.assertTrue(validate_grounding(proposal, {"source_kind": "self", "human_text": "以后默认使用中文"}, {}))

    async def test_archivist_minimizes_contact_data_before_model_call(self):
        captured = []
        class FakeLLM:
            def with_structured_output(self, schema):
                return self

            async def ainvoke(self, messages):
                captured.extend(messages)
                return ArchiveBatch()

        extractor = make_archivist(FakeLLM())
        await extractor({"source_kind": "self", "human_text": "我是测试小安，电话18800008888，邮箱private@example.test"},
                        {"facts": [{"field": "phone", "value": "18800008888"},
                                   {"category": "project", "subject": "项目nested@example.test",
                                    "field": "description", "value": "联系18800009999处理反馈",
                                    "source_ids": ["private-source-id"]}]})
        self.assertNotIn("18800008888", str(captured))
        self.assertNotIn("private@example.test", str(captured))
        self.assertNotIn("18800009999", str(captured))
        self.assertNotIn("nested@example.test", str(captured))
        self.assertNotIn("private-source-id", str(captured))

    async def test_archivist_restores_literal_evidence_before_source_validation(self):
        original = "我为测试项目整理邮箱private@example.test收到的反馈"
        captured = []

        class FakeLLM:
            def with_structured_output(self, schema):
                return self

            async def ainvoke(self, messages):
                captured.extend(messages)
                text = json.loads(messages[1]["content"])["human_text"]
                return ArchiveBatch(proposals=[ArchiveProposal(category="project", subject="测试项目",
                                                                field="description", value=text, evidence_quote=text)])

        payload = {"source_kind": "self", "human_text": original}
        result = await make_archivist(FakeLLM())(payload, {"facts": []})
        self.assertNotIn("private@example.test", str(captured))
        self.assertEqual(result.proposals[0].value, original)
        self.assertEqual(result.proposals[0].evidence_quote, original)
        self.assertTrue(validate_grounding(result.proposals[0], payload, {"facts": []}))

    async def test_stale_delete_cannot_overwrite_concurrent_correction(self):
        fact = self.add()
        with self.factory() as stale:
            # Keep an ORM identity cached while another transaction commits.
            cached = stale.get(ProfileFact, fact["id"])
            with self.factory() as fresh:
                archive.edit_fact(fresh, "a", fact["id"], value="已确认新职责", expected_revision=1)
                fresh.commit()
            self.assertEqual(cached.revision, 1)
            with self.assertRaises(archive.ProfileRevisionConflict):
                archive.delete_fact(stale, "a", fact["id"], 1)
            stale.rollback()
        self.assertEqual(self.profile()["facts"][0]["value"], "已确认新职责")

    async def test_background_retry_cannot_bypass_account_budget(self):
        event_id = self.event("测试项目我是后端参与者")
        calls = []

        def budget(account_id):
            calls.append(account_id)
            raise HTTPException(429, "budget exhausted")

        async def extractor(payload, context):
            self.fail("a denied budget must never call the model")

        result = await archive.process_pending_events(self.factory, extractor, budget_reserver=budget)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(calls, ["a"])
        self.assertEqual(self.profile()["archive_status"]["tasks"][0]["error_code"], "budget_exhausted")
        # Automatic sweeps do not spend all retries before the daily reset.
        await archive.process_pending_events(self.factory, extractor, budget_reserver=budget)
        self.assertEqual(len(calls), 1)
        with self.factory() as db:
            archive.retry_task(db, "a", event_id)
            db.commit()
        await archive.process_pending_events(self.factory, extractor, budget_reserver=budget)
        self.assertEqual(calls, ["a", "a"])

    async def test_claimed_history_status_is_account_scoped_and_content_free(self):
        with self.factory() as db:
            db.add_all([
                ClaimedHistoryImport(session_id="my-pending-chat", owner="account:a", status="pending", attempts=1, error_code="TimeoutError"),
                ClaimedHistoryImport(session_id="my-failed-chat", owner="account:a", status="failed", attempts=3, error_code="DataDecryptionError"),
                ClaimedHistoryImport(session_id="my-completed-chat", owner="account:a", status="completed", attempts=0, error_code=""),
                ClaimedHistoryImport(session_id="other-private-chat", owner="account:b", status="failed", attempts=3, error_code="RuntimeError"),
            ])
            db.commit()
        response = await self.client.get("/api/profile", headers={"x-test-account": "a"})
        self.assertEqual(response.status_code, 200)
        status = response.json()["import_status"]
        self.assertEqual((status["pending"], status["running"], status["failed"], status["completed"]), (1, 0, 1, 1))
        failed = next(task for task in status["tasks"] if task["status"] == "failed")
        self.assertEqual(failed["reason_type"], "DataDecryptionError")
        self.assertEqual(failed["attempts"], 3)
        self.assertNotIn("other-private-chat", response.text)
        self.assertNotIn("human_text", response.text)
        self.assertEqual(response.json()["archive_status"]["failed"], 0)

    async def test_no_model_saves_basic_subset_without_completing_project_work(self):
        event_id = self.event("我叫测试小安，测试项目我是后端参与者",
                              collected_info_delta={"basic_info": {"name": "测试小安"}})
        result = await archive.process_pending_events(self.factory)
        self.assertEqual(result, {"completed": 0, "failed": 1, "skipped": 0})
        profile = self.profile()
        self.assertEqual([(fact["field"], fact["value"]) for fact in profile["facts"]], [("name", "测试小安")])
        task = profile["archive_status"]["tasks"][0]
        self.assertEqual((task["id"], task["status"], task["error_code"], task["attempts"]),
                         (event_id, "failed", "model_unavailable", 0))
        self.assertEqual(task["reason_type"], "model_unavailable")
        self.assertIn("无需反复重试", task["message"])
        self.assertFalse(task["retryable"])
        # Polls with the same unavailable configuration do not keep retrying.
        self.assertEqual(await archive.process_pending_events(self.factory),
                         {"completed": 0, "failed": 0, "skipped": 0})
        await self.run_proposals([self.proposal("后端参与者")])
        profile = self.profile()
        self.assertEqual(len(profile["facts"]), 2)
        self.assertEqual(profile["archive_status"]["failed"], 0)
        self.assertEqual(next(f for f in profile["facts"] if f["field"] == "name")["revision"], 1)

    async def test_no_model_project_only_event_stays_visible_and_manual_facts_complete(self):
        self.event("测试项目我是后端参与者", source_id="free-text-project")
        await archive.process_pending_events(self.factory)
        self.assertEqual(self.profile()["facts"], [])
        self.assertEqual(self.profile()["archive_status"]["tasks"][0]["error_code"], "model_unavailable")
        self.event("测试项目我是后端参与者", source_id="explicit-manual", source_kind="manual",
                   confirmed_facts=[self.proposal("后端参与者").model_dump(mode="json")])
        result = await archive.process_pending_events(self.factory)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(self.profile()["facts"][0]["value"], "后端参与者")

    async def test_incremental_import_preserves_named_job_and_all_dependencies(self):
        first = self.add(subject="项目A", value="负责后端")
        second = self.add(subject="项目B", value="负责测试")
        refs_a = [{"fact_id": first["id"], "revision": first["revision"]}]
        refs_b = [{"fact_id": second["id"], "revision": second["revision"]}]
        with self.factory() as db:
            job = archive.save_job_version(db, "a", session_id="chat", name="我命名的产品岗位", fact_refs=refs_a)
            db.commit()
        with self.factory() as db:
            merged = archive.merge_job_version_import(db, "a", "chat", refs_b + refs_b)
            db.commit()
        self.assertEqual(merged["name"], "我命名的产品岗位")
        self.assertEqual(merged["id"], job["id"])
        self.assertEqual({r["fact_id"] for r in merged["fact_refs"]}, {first["id"], second["id"]})
        self.assertFalse(merged["stale"])
        with self.factory() as db:
            archive.edit_fact(db, "a", first["id"], value="负责后端一部分", expected_revision=first["revision"])
            db.commit()
        self.assertTrue(self.profile()["jobs"][0]["stale"])

    async def test_new_import_does_not_clear_old_version_risk_and_rolls_back(self):
        first = self.add(subject="项目A", value="负责后端")
        second = self.add(subject="项目B", value="负责测试")
        old_ref = {"fact_id": first["id"], "revision": first["revision"]}
        with self.factory() as db:
            archive.save_job_version(db, "a", session_id="chat", name="保留岗位名", fact_refs=[old_ref])
            archive.edit_fact(db, "a", first["id"], value="负责后端一部分", expected_revision=1)
            db.commit()
        new_ref = {"fact_id": first["id"], "revision": 2}
        with self.factory() as db:
            merged = archive.merge_job_version_import(db, "a", "chat", [new_ref, {"fact_id": second["id"], "revision": 1}])
            db.commit()
        self.assertTrue(merged["stale"])
        self.assertIn(old_ref, merged["outdated_refs"])
        self.assertEqual([r for r in merged["fact_refs"] if r["fact_id"] == first["id"]], [new_ref])
        before = self.profile()["jobs"][0]
        with self.factory() as db:
            archive.merge_job_version_import(db, "a", "chat", [new_ref])
            db.rollback()
        self.assertEqual(self.profile()["jobs"][0], before)

    async def test_api_auth_cross_account_revision_and_csrf(self):
        self.assertEqual((await self.client.get("/api/profile")).status_code, 401)
        fact = self.add()
        headers = {"x-test-account": "b"}
        response = await self.client.patch(f"/api/profile/facts/{fact['id']}",
                                           headers=headers, json={"value": "窃取", "expected_revision": 1})
        self.assertEqual(response.status_code, 404)
        headers = {"x-test-account": "a"}
        response = await self.client.patch(f"/api/profile/facts/{fact['id']}",
                                           headers=headers, json={"value": "新职责", "expected_revision": 1})
        self.assertEqual(response.status_code, 200)
        response = await self.client.patch(f"/api/profile/facts/{fact['id']}",
                                           headers=headers, json={"value": "旧覆盖", "expected_revision": 1})
        self.assertEqual(response.status_code, 409)
        response = await self.client.delete(f"/api/profile/facts/{fact['id']}?expected_revision=2",
                                            headers={**headers, "origin": "https://attacker.example"})
        self.assertEqual(response.status_code, 403)

    async def test_api_conflict_is_stale_after_manual_edit(self):
        fact = self.add(value="项目负责人")
        self.event("测试项目中我是后端参与者")
        await self.run_proposals([self.proposal("后端参与者")])
        conflict = self.profile()["conflicts"][0]
        with self.factory() as db:
            archive.edit_fact(db, "a", fact["id"], value="后端开发", expected_revision=1)
            db.commit()
        response = await self.client.post(f"/api/profile/conflicts/{conflict['id']}/resolve",
                                          headers={"x-test-account": "a"}, json={"choice": "replace", "expected_revision": 1})
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
