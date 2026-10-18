"""A–D：合成档案、临时加密 SQLite、真实图与离线工具桩。"""

from importlib import import_module
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

import test_profile_archive as fixture
from test_batch14b_intake import FlowModel, PAGES
from test_campus_and_naming import semantic_stub
from app.agents import resume_graph as graph
from app.agents.profile_archivist import ArchiveProposal, ArchiveBatch
from app.agents.public_reply import stream_public_reply
from app.models.models import ResumeSession, Conversation
from app.models.profile import ProfileFact, ProfileConflict, ProfileArchiveEvent
from app.services import profile_bridge as bridge, profile_service as archive
from app.services.data_crypto import DataDecryptionError
from app.services.intake import intake_guidance, intake_update, deepen_context
from app.services.profile_tools import execute_profile_tool, profile_runtime, relevance
from app.services.renderer import TEMPLATES, render_resume

returning = import_module("evaluation.persona-ux.returning")
runner = import_module("evaluation.persona-ux.run_persona")


class ReturningModel(FlowModel):
    def __init__(self, chunks=True):
        super().__init__()
        self.bound = []
        self.used = []
        self.chunks = chunks

    def bind_tools(self, tools, **kwargs):
        self.bound.append([tool["function"]["name"] for tool in tools])
        return self

    async def astream(self, messages):
        self.public_messages.append(messages)
        tool = next((m for m in reversed(messages) if isinstance(m, ToolMessage)), None)
        if tool:
            result = json.loads(tool.content)
            if "items" in result:
                call = {"name": "use_profile_items", "args": {"item_ids": [i["id"] for i in result["items"] if i["category"] == "project"]}}
            else:
                yield AIMessageChunk(content="这两段包含开发与核对细节，可以继续生成草稿。")
                return
        else:
            call = {"name": "read_profile", "args": {"query": returning.ROLE}}
        self.used.append(call["name"])
        arguments = json.dumps(call["args"], ensure_ascii=False)
        if self.chunks:
            for index, fragment in enumerate((arguments[:7], arguments[7:])):
                yield AIMessageChunk(content="", tool_call_chunks=[{"index": 0, "id": "call" if index == 0 else None,
                    "name": call["name"] if index == 0 else None, "args": fragment}])
        else:
            yield AIMessageChunk(content="", tool_calls=[{**call, "id": "call"}])


class Batch16ProfileTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.ArchiveTests.asyncSetUp
    asyncTearDown = fixture.ArchiveTests.asyncTearDown
    event = fixture.ArchiveTests.event
    profile = fixture.ArchiveTests.profile
    add = fixture.ArchiveTests.add

    def seed(self):
        with self.factory() as db:
            returning.seed(db, "a")
            db.add(ResumeSession(session_id="returning", owner_key="account:a", resume_data={}, resume_draft="", stage="JD_INPUT"))
            db.add(Conversation(session_id="returning", owner_hash="account:a", title="合成回放"))
            db.commit()
        self.enterContext(patch.object(bridge, "SessionLocal", self.factory))

    async def initial(self, compiled=None):
        self.seed()
        compiled = compiled or graph.build_graph(None)
        await bridge.prepare_graph_context("account:a", "returning", compiled)
        state = (await compiled.aget_state({"configurable": {"thread_id": "returning"}})).values
        return state, compiled

    async def test_profile_first_projects_wait_for_selection_contacts_render_in_all_seven_templates(self):
        state, _ = await self.initial()
        self.assertEqual(state["intake_progress"]["basics"], "from_profile")
        self.assertNotEqual((intake_guidance(state) or {}).get("kind"), "intake_basics")
        self.assertFalse(state["collected_info"]["projects"])
        self.assertEqual(len(state["collected_info"]["education"]), 1)
        self.assertEqual(state["collected_info"]["education"][0]["school"], "青川大学")
        data = graph._serialize_to_resume_data(state)
        self.assertEqual(len(TEMPLATES), 7)
        for template in TEMPLATES:
            html = render_resume(template["id"], data)
            self.assertIn("13900001234", html)
            self.assertIn("returning@example.test", html)
            self.assertNotIn("可实习时间：", html)

    async def test_partial_profile_missing_fields_and_contacts_optional(self):
        state = {"intake_account": True, "intake_profile": {"basic_info": {"name": "仅有姓名", "phone": "13900001234"}}}
        card = intake_guidance(state)
        self.assertNotIn("name", card["missing_fields"])
        self.assertNotIn("phone", card["missing_fields"])
        self.assertIn("school", card["missing_fields"])
        self.assertEqual(card["values"]["phone"], "13900001234")

    async def test_experience_card_selection_rank_unknown_and_provenance(self):
        state, _ = await self.initial()
        state.update(jd_info={"job_title": returning.ROLE})
        state.update(intake_update(state))
        card = intake_guidance(state)
        self.assertEqual(card["title"], "从档案选经历")
        self.assertEqual(card["items"], [])
        self.assertEqual(len(card["profile_items"]), 3)
        self.assertTrue(card["selected_profile_ids"])
        token = profile_runtime.set(("account:a", "returning"))
        try:
            ids = [i["id"] for i in card["profile_items"] if i["category"] == "project"]
            result, update = await execute_profile_tool("use_profile_items", {"item_ids": ids}, state)
            self.assertEqual(set(result["imported"]), set(returning.PROJECTS))
            self.assertEqual(len(update["collected_info"]["projects"]), 2)
            for item in update["collected_info"]["projects"]:
                self.assertTrue(item["facts"])
                self.assertTrue(all(f["profile_refs"] for f in item["facts"]))
            self.assertNotIn(update["intake_stage"], {"basics", "target", "experiences"})
            self.assertIsNone(deepen_context({**state, **update}).get("subject"))
            bad, no_update = await execute_profile_tool("use_profile_items", {"item_ids": ["other-account"]}, state)
            self.assertEqual(bad["status"], "invalid_items")
            self.assertEqual(no_update, {})
        finally:
            profile_runtime.reset(token)
        state["jd_info"] = {}
        self.assertEqual(intake_guidance(state)["selected_profile_ids"], [])

    async def test_experience_form_imports_two_items_and_known_dimensions_are_not_reasked(self):
        state, _ = await self.initial()
        state.update(jd_info={"job_title": returning.ROLE, "role_profile": {"role_family": "ai_pm"}})
        ids = [item["id"] for item in state["profile_items"] if item["category"] == "project"]
        message = HumanMessage(content="从档案选用两段经历", id="form-selection",
            additional_kwargs={"intake": {"kind": "experiences", "items": [], "profile_item_ids": ids}})
        state["messages"] = [message]
        token = profile_runtime.set(("account:a", "returning"))
        try:
            update = await graph._intake_form_turn(state, None, message)
        finally:
            profile_runtime.reset(token)
        self.assertEqual(len(update["collected_info"]["projects"]), 2)
        self.assertEqual(update["intake_progress"]["experiences"], "confirmed")
        project = update["collected_info"]["projects"][0]
        self.assertTrue(all(f["profile_refs"] for f in project["facts"]))
        project["facts"] = [f for f in project["facts"] if f.get("profile_field") != "status"]
        partial = {**state, **update, "intake_stage": "deepen", "stage": "COLLECTING",
                   "intake_progress": {"basics": "from_profile", "experiences": "confirmed"}}
        context = deepen_context(partial)
        self.assertNotIn("my_work", context["remaining_dimensions"])
        self.assertNotIn("tech_stack", context["remaining_dimensions"])
        self.assertIn("status", context["remaining_dimensions"])

    async def test_tool_stream_fragments_read_import_and_complete_call_arguments_are_private(self):
        state, _ = await self.initial()
        token = profile_runtime.set(("account:a", "returning"))
        try:
            for chunks in (True, False):
                model = ReturningModel(chunks)
                response = await stream_public_reply(model, [HumanMessage(content=returning.FIRST)], ask_state=state)
                self.assertEqual(model.used, ["read_profile", "use_profile_items"])
                self.assertIn("read_profile", model.bound[0])
                self.assertIn("use_profile_items", model.bound[0])
                self.assertEqual(len(response.additional_kwargs["profile_update"]["collected_info"]["projects"]), 2)
                for name in returning.PROJECTS:
                    self.assertIn(name, response.content)
                sent = str(model.public_messages)
                self.assertNotIn("13900001234", sent)
                self.assertNotIn("returning@example.test", sent)
        finally:
            profile_runtime.reset(token)

    async def test_guest_does_not_receive_profile_tools(self):
        class Plain(ReturningModel):
            async def astream(self, messages):
                yield AIMessageChunk(content="你好")
        model = Plain()
        await stream_public_reply(model, [HumanMessage(content="你好")], ask_state={})
        self.assertNotIn("read_profile", model.bound[0])
        self.assertNotIn("use_profile_items", model.bound[0])

    async def test_returning_real_graph_read_import_then_offline_writer(self):
        model = ReturningModel()
        compiled = graph.build_graph(model)
        state, _ = await self.initial(compiled)
        token = profile_runtime.set(("account:a", "returning"))
        try:
            config = {"configurable": {"thread_id": "returning"}}
            with patch.object(graph, "_extract_info_from_message", side_effect=AssertionError("request is not a fact")), \
                 patch("app.services.llm_compat.without_thinking", side_effect=lambda llm: llm) as no_thinking:
                state = await compiled.ainvoke({"messages": [HumanMessage(content=returning.FIRST, id="returning-request")]}, config)
            self.assertEqual(model.used, ["read_profile", "use_profile_items"])
            # 真实 DeepSeek：思考模式续写要求回传 reasoning_content，工具结果后的续写必须关闭思考。
            self.assertTrue(no_thinking.called)
            # 回执在正文之后落库，与流式顺序一致；前端按最后一条回复核对保存。
            self.assertTrue([m for m in state["messages"] if isinstance(m, AIMessage)][-1].content.startswith("已沿用档案"))
            self.assertEqual(len(state["collected_info"]["projects"]), 2)
            replies = "".join(m.content for m in state["messages"] if isinstance(m, AIMessage))
            self.assertIn("已沿用档案", replies)
            self.assertNotIn("没记下来", replies)
            self.assertEqual(state["resume_data"]["basic_info"]["phone"], "13900001234")
            # 真写稿节点由现有 EchoWriter 桩驱动，保留事实、引用和头部。
            with patch.object(graph, "_make_non_streaming_llm", side_effect=lambda llm, **kwargs: llm), \
                 patch("app.services.fact_guard.verify_semantics", semantic_stub), \
                 patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value=PAGES):
                drafted = await graph.building_node({**state, "intake_stage": "ready", "stage": "BUILDING",
                    "messages": [*state["messages"], HumanMessage(content="直接生成简历，不再追问。")],
                    "plan_required": False}, FlowModel())
            self.assertTrue(drafted.get("resume_data"), drafted)
            for name in returning.PROJECTS:
                self.assertIn(name, str(drafted["resume_data"]))
            self.assertEqual(drafted["resume_data"]["basic_info"]["email"], "returning@example.test")
        finally:
            profile_runtime.reset(token)

    async def test_structured_basics_archive_bypasses_model_and_splits_all_fields(self):
        text = "基本信息：姓名：测试用户，所在城市：https://github.com/example，手机：13900001234，邮箱：test@example.test，可实习时间：5天/6个月，学校：测试大学，专业：计算机，学历：本科，毕业时间：2027-06"
        self.event(text)
        extractor = AsyncMock(side_effect=AssertionError("structured form must not invoke model"))
        self.assertEqual((await archive.process_pending_events(self.factory, extractor))["completed"], 1)
        extractor.assert_not_called()
        facts = self.profile()["facts"]
        values = {f["field"]: f["value"] for f in facts}
        self.assertEqual(values["availability"], "5天/6个月")
        self.assertEqual(values["school"], "测试大学")
        self.assertEqual(values["link"], "https://github.com/example")
        self.assertNotIn("location", values)
        self.assertEqual(values["phone"], "13900001234")

    async def test_basic_validation_and_cross_source_conflict_deduplication(self):
        for value in ("https://github.com/example", "姓名：甲，学校：乙"):
            with self.assertRaises(ValidationError):
                ArchiveProposal(category="basic", subject="本人", field="name", value=value, evidence_quote=value)
        self.add(category="basic", subject="基础信息", field="location", value="深圳")
        self.add(category="basic", subject="本人", field="location", value="北京")
        self.add(category="basic", subject="测试姓名", field="location", value="北京")
        self.assertEqual(len(self.profile()["conflicts"]), 1)
        self.assertEqual(self.profile()["facts"][0]["subject"], "本人")

    async def test_dirty_migration_is_scoped_idempotent_and_retains_superseded_rows(self):
        original = []
        with self.factory() as db:
            archive.ensure_profile(db, "a")
            for account in ("a", "b"):
                entries = [("基础信息", "name", "测试姓名"), ("测试姓名", "name", "测试姓名"),
                    ("基础信息", "email", "test@example.test"), ("本人", "email", "test@example.test"),
                    ("基础信息", "location", "https://github.com/example"), ("本人", "location", "https://github.com/example"),
                    ("GitHub", "link", "https://github.com/example"),
                    ("本人", "availability", "5天/6个月，学校：测试大学，专业：计算机，学历：本科，毕业时间：2027-06")]
                for subject, field, value in entries:
                    row = ProfileFact(id=archive.new_id(), account_id=account, category="basic", revision=1, status="active",
                                      slot_key=archive._key(account, ["basic", subject, field]))
                    row.payload = archive._seal(row, {"subject": subject, "field": field, "value": value, "source_ids": []})
                    db.add(row)
                    if account == "a":
                        original.append(row.id)
                    if field == "location":
                        conflict = ProfileConflict(id=archive.new_id(), account_id=account, fact_id=row.id,
                            event_id=archive.new_id(), expected_revision=1, status="pending")
                        conflict.payload = archive._seal(conflict, {"subject": subject, "field": field,
                            "current_value": value, "proposed_value": "深圳", "source_id": None})
                        db.add(conflict)
            db.commit()
            other_before = [(r.id, r.payload, r.status) for r in db.scalars(select(ProfileFact).where(ProfileFact.account_id == "b"))]
            self.assertGreater(archive.migrate_legacy_basic_facts(db, "a"), 0)
            db.commit()
            self.assertEqual(archive.migrate_legacy_basic_facts(db, "a"), 0)
            other_after = [(r.id, r.payload, r.status) for r in db.scalars(select(ProfileFact).where(ProfileFact.account_id == "b"))]
            self.assertEqual(other_before, other_after)
            self.assertTrue(all(db.get(ProfileFact, i) is not None for i in original))
            self.assertTrue(any(db.get(ProfileFact, i).status == "superseded" for i in original))
        facts = self.profile()["facts"]
        for field in ("name", "email", "link", "availability"):
            self.assertEqual(len([f for f in facts if f["field"] == field]), 1)
        self.assertEqual(next(f["value"] for f in facts if f["field"] == "availability"), "5天/6个月")
        self.assertFalse(any(f["field"] == "location" and "http" in f["value"] for f in facts))
        self.assertLessEqual(len(self.profile()["conflicts"]), 1)

    async def test_migration_same_event_conflicts_do_not_violate_unique_constraint(self):
        with self.factory() as db:
            archive.ensure_profile(db, "a")
            for subject in ("本人", "基础信息"):
                row = ProfileFact(id=archive.new_id(), account_id="a", category="basic", revision=1, status="active",
                                  slot_key=archive._key("a", ["basic", subject, "location"]))
                row.payload = archive._seal(row, {"subject": subject, "field": "location", "value": "深圳", "source_ids": []})
                db.add(row)
                conflict = ProfileConflict(id=archive.new_id(), account_id="a", fact_id=row.id,
                    event_id="same-event", expected_revision=1, status="pending")
                conflict.payload = archive._seal(conflict, {"subject": subject, "field": "location",
                    "current_value": "深圳", "proposed_value": "北京", "source_id": None})
                db.add(conflict)
            db.commit()
            archive.migrate_legacy_basic_facts(db, "a")
            db.commit()
        self.assertEqual(len(self.profile()["conflicts"]), 1)

    async def test_returning_bootstrap_only_creates_synthetic_account_and_runner_uses_it(self):
        from http.cookiejar import CookieJar
        from app.models.account import Account, AccountSession
        client = SimpleNamespace(base="http://127.0.0.1:18888", cookies=CookieJar())
        def request(path, body=None):
            with self.factory() as db:
                if path == "/api/chat/conversations":
                    self.assertEqual(db.query(Account).count(), 1)
                    self.assertEqual(db.query(AccountSession).count(), 1)
                    self.assertEqual(len(client.cookies), 1)
                    return {"session_id": "seeded-local-session"}
                account = db.scalar(select(Account))
                return archive.get_profile(db, account.id)
        client.json = request
        with patch("app.services.data_crypto.get_crypto", return_value=self.crypto), \
             patch("app.services.account_service.blind_index", side_effect=archive.blind_index):
            returning.start(client, self.path)
        self.assertEqual(client.session_id, "seeded-local-session")
        with self.factory() as db:
            account = db.scalar(select(Account))
            self.assertEqual(len(archive.get_profile(db, account.id)["facts"]), len(returning.FACTS))
            self.assertEqual(archive.get_profile(db, "existing-account")["facts"], [])

    async def test_archive_errors_are_classified_safe_logged_and_retryable(self):
        for index, (error, code) in enumerate(((RuntimeError("PRIVATE-SOURCE"), "archive_model_error"),
                (DataDecryptionError("PRIVATE-SOURCE"), "archive_decryption_error"),
                (OperationalError("PRIVATE-SOURCE", {}, Exception()), "archive_database_error"))):
            event_id = self.event("合成项目的说明", source_id=str(index))
            with self.assertLogs("app.services.profile_service", level="WARNING") as logs:
                await archive.process_pending_events(self.factory, AsyncMock(side_effect=error))
            self.assertNotIn("PRIVATE-SOURCE", str(logs.output))
            self.assertIn(type(error).__name__, str(logs.output))
            with self.factory() as db:
                event = db.get(ProfileArchiveEvent, event_id)
                self.assertEqual(event.error_code, code)
                self.assertTrue(archive._archive_task_view(event)["retryable"])
                archive.retry_task(db, "a", event_id)
                db.commit()
            result = await archive.process_pending_events(self.factory, AsyncMock(return_value=ArchiveBatch()))
            self.assertEqual(result["failed"], 0)


class Batch16RequestTests(unittest.TestCase):
    def test_explicit_generate_with_session_experiences_goes_to_drafting_not_profile(self):
        text = "用刚选的经历直接生成简历，不再追问。"
        self.assertTrue(graph._explicit_generate_requested(text))
        state = {"messages": [HumanMessage(content=text)], "intake_account": True,
                 "profile_summary": {"has_facts": True}, "collected_info": {}}
        self.assertEqual(graph.route_by_stage(state), "dialogue")
        state["collected_info"] = {"projects": [{"item_id": "p1", "name": "任务编排器", "facts": []}]}
        self.assertNotEqual(graph.route_by_stage(state), "dialogue")
        self.assertFalse(graph._explicit_generate_requested("不要直接生成"))

    def test_profile_query_is_not_a_missing_fact_but_real_development_still_is(self):
        from app.agents.fact_extractor import uncovered_action_clauses
        from app.services.candidate_language import non_fact
        self.assertEqual(uncovered_action_clauses(returning.FIRST, []), [])
        self.assertFalse(non_fact("我用Python开发了档案管理项目"))
        pending = {"unrecorded": {"source": graph._hash_text(returning.FIRST), "clauses": [returning.FIRST]}}
        self.assertEqual(graph.unrecorded_notice(pending, returning.FIRST), "")

    def test_runner_registers_returning_and_requires_explicit_fixture_database(self):
        self.assertIs(runner.CARD_PERSONAS["returning"], returning)
        with self.assertRaisesRegex(ValueError, "returning-db"):
            runner.run_replay("http://127.0.0.1:18888", Path("unused"), ["returning"])

    def test_runner_returning_runs_preloaded_offline_persona(self):
        from http.cookiejar import CookieJar
        requests = []
        class Client:
            def __init__(self, base, timeout):
                self.base, self.cookies, self.seeded = base, CookieJar(), False
            def start(self):
                raise AssertionError("returning must not use guest bootstrap")
            def turn(self, action, text, **kwargs):
                assert self.seeded
                requests.append((action, text))
                return {"action": action, "input": text, "reply": "已从档案导入：" + "、".join(returning.PROJECTS),
                    "status": "ok", "sse_done": True, "stage": "EVALUATING", "workspace": {},
                    "resume_data": {"basic_info": {"phone": "13900001234", "email": "returning@example.test"},
                                    "projects": [{"name": name} for name in returning.PROJECTS]}}
        def seed(client, database):
            self.assertEqual(database, "explicit-isolated-db")
            client.seeded = True
        with tempfile.TemporaryDirectory(prefix="huhua-returning-runner-") as directory, \
             patch.object(runner, "GuestClient", Client), patch.object(returning, "start", side_effect=seed):
            run = runner.run_replay("http://127.0.0.1:18888", Path(directory) / "run", ["returning"],
                                    returning_db="explicit-isolated-db")
            self.assertEqual(run["status"], "pass")
            self.assertEqual(run["stream_requests"], 3)
            self.assertEqual(requests[0][1], returning.FIRST)
            self.assertIn("returning_fixture_sha256", run)

    def test_ranking_prefers_word_overlap_and_has_no_unknown_role_defaults(self):
        item = {"category": "project", "name": "文档检索", "summary": "Python RAG", "role": "开发者"}
        self.assertEqual(relevance(item, ""), 0)
        self.assertGreater(relevance(item, "Python RAG 开发"), relevance(item, "校园活动"))


import test_product_security_flow as security_fixture  # noqa: E402


class Batch16HttpTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = security_fixture.ProductSecurityFlow.asyncSetUp
    cleanup = security_fixture.ProductSecurityFlow.cleanup
    login = security_fixture.ProductSecurityFlow.login

    async def test_account_stream_persists_tool_import_and_fresh_greeting_projects_contacts(self):
        from app.api import chat
        from app.services.session_store import load_resume_session
        with self.factory() as db:
            returning.seed(db, self.account_a)
            db.commit()
        model = ReturningModel()
        self.graph = graph.build_graph(model, self.saver)
        for name in ("app.api.chat", "app.api.resume", "app.agents.resume_graph"):
            self.enterContext(patch(name + ".get_graph", return_value=self.graph))
        self.enterContext(patch.object(chat, "_get_llm", return_value=model))
        self.enterContext(patch.object(graph, "_make_non_streaming_llm", side_effect=lambda llm, **kwargs: llm))
        self.enterContext(patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value=PAGES))
        for text in ("你好", returning.FIRST):
            session = (await self.a.post("/api/chat/conversations", json={})).json()["session_id"]
            response = await self.a.post("/api/chat/stream", json={"session_id": session,
                "messages": [{"role": "user", "content": text}]})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('"error"', response.text)
            self.assertIn("[DONE]", response.text)
            self.assertIn("已沿用档案", response.text)
            current = (await self.a.get("/api/resume/current", params={"session_id": session})).json()
            self.assertEqual(current["data"]["basic_info"]["phone"], "13900001234")
            self.assertEqual(current["data"]["basic_info"]["email"], "returning@example.test")
            self.assertNotEqual((current["workspace"].get("guidance") or {}).get("kind"), "intake_basics")
            stored = load_resume_session(session)
            if text == returning.FIRST:
                self.assertEqual(len(stored["collected_info"]["projects"]), 2)
                self.assertTrue(all(f.get("profile_refs") for i in stored["collected_info"]["projects"] for f in i["facts"]))
                for name in returning.PROJECTS:
                    self.assertIn(name, str(current["data"]))
        self.assertEqual(model.used, ["read_profile", "use_profile_items"])
        self.assertNotIn("13900001234", str(model.public_messages))
        self.assertNotIn("returning@example.test", str(model.public_messages))
