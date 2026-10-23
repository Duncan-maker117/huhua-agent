"""Offline adapter contracts: real validators/pipeline, isolated stores and model doubles."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents import orchestrator_tools as tools  # noqa: E402
from app.agents import resume_graph as graph  # noqa: E402
from app.services.resume_facts import new_fact, normalize_fact_store  # noqa: E402
from app.services.resume_versions import text_hash  # noqa: E402
from app.services.resume_review import resume_to_text  # noqa: E402


PHONE, EMAIL = "13912345678", "adapter@example.invalid"


def collected():
    return normalize_fact_store({"basic_info": {"name": "离线候选人", "phone": PHONE, "email": EMAIL},
        "projects": [{"item_id": "p1", "name": "资料核对项目", "facts": [
            {**new_fact("核对重复记录并提交核对表", kind="action"), "id": "f1"}]},
            {"item_id": "p2", "name": "页面原型项目", "facts": [
                {**new_fact("完成页面原型并记录评审意见", kind="deliverable"), "id": "f2"}]}]})


def state_with_draft():
    facts = collected()
    data = {"basic_info": deepcopy(facts["basic_info"]), "projects": [
        {"item_id": row["item_id"], "name": row["name"], "polished_bullets": [row["facts"][0]["text"]]}
        for row in facts["projects"]]}
    meta = {"version_id": "v-original", "bullets": {row["item_id"]: [
        {"fact_ids": [row["facts"][0]["id"]], "text_hash": text_hash(row["facts"][0]["text"])}]
        for row in facts["projects"]}}
    return {**graph._init_state(), "collected_info": facts, "resume_data": data, "resume_meta": meta,
            "messages": [HumanMessage(content="请把第二个项目改短", id="edit-turn")]}


class Extractor:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def ainvoke(self, messages):
        self.requests.append(deepcopy(messages))
        return AIMessage(content=json.dumps(self.response, ensure_ascii=False))


class Writer:
    def __init__(self, *, invented=False, fail=False):
        self.requests = []
        self.invented, self.fail = invented, fail

    def with_structured_output(self, schema):
        async def invoke(messages):
            self.requests.append((schema.__name__, deepcopy(messages)))
            if self.fail:
                raise RuntimeError("offline writer failure")
            payload = json.loads(messages[-1].content)
            if schema.__name__ in {"OnePassOutput", "WriterDraft"}:
                rows = []
                for section in ("projects", "work_experience", "campus", "open_source", "awards"):
                    for item in payload["evidence"].get(section) or []:
                        rows.append({"section": section, "item_id": item["item_id"], "bullets": [
                            {"text": "服务900万用户" if self.invented else fact["text"], "fact_ids": [fact["id"]]}
                            for fact in item["facts"] if not fact.get("field")]})
                value = {"items": rows}
                return {"match_plan": {}, "writer": value} if schema.__name__ == "OnePassOutput" else value
            if schema.__name__ == "RepairOutput":
                return {"bullets": []}
            if schema.__name__ == "SemanticBatch":
                return {"decisions": [{"id": row["id"], "verdict": "fail", "reason": "offline conservative guard"}
                                      for row in payload]}
            raise AssertionError(schema.__name__)
        return SimpleNamespace(ainvoke=invoke)


def measured(data, constraints):
    from app.services.resume_capacity import resume_data_hash
    return {"status": "rendered", "pages": 1, "within_page_limit": True,
            "page_limit": constraints["page_limit"], "template_id": constraints["template_id"],
            "data_hash": resume_data_hash(data)}


class OrchestratorToolsTest(unittest.IsolatedAsyncioTestCase):
    def assert_private(self, value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        self.assertNotIn(PHONE, text)
        self.assertNotIn(EMAIL, text)

    def test_document_outcome_filters_diagnostics_without_losing_state_or_result(self):
        for changed, diagnostic, status in ((True, {}, 'ok'), (False, {}, 'unchanged'),
                                            (True, {'status': 'model_fallback'}, 'partial')):
            with self.subTest(status=status):
                data = state_with_draft()['resume_data']
                update = {'resume_data': data, 'resume_meta': {'version_id': 'v-next'},
                          'resume_versions': [{'version_id': 'v-old'}], 'page_check': {'pages': 1},
                          'changed': changed, 'writer_diagnostic': diagnostic, 'version_id': 'v-next',
                          'change_summary': ['已核对'], 'guard_fallbacks': ['fallback'],
                          'edit_contract': {'scope': 'whole'}, 'future_diagnostic': {'internal': True}}
                outcome = tools._document_outcome(deepcopy(update))
                self.assertEqual(outcome.result['status'], status)
                for key in ('changed', 'writer_diagnostic', 'version_id', 'change_summary', 'guard_fallbacks', 'edit_contract'):
                    self.assertEqual(outcome.result[key], update[key])
                expected = {key: update[key] for key in ('resume_data', 'resume_meta', 'resume_versions',
                            'page_check', 'version_id', 'change_summary', 'guard_fallbacks')}
                self.assertEqual(outcome.update, {**expected, 'stage': 'EVALUATING',
                    'resume_draft': resume_to_text(data)})
                self.assertNotIn('future_diagnostic', outcome.update)

    async def test_registry_and_source_only_strict_parameters(self):
        self.assertEqual(set(tools.TOOLS), {"use_skill", "read_profile", "use_profile_items", "read_jd", "search_company",
            "record_facts", "ask_user", "propose_plan", "write_draft", "edit_resume", "check_layout", "check_resume"})
        schemas = {row["function"]["name"]: row["function"]["parameters"] for row in tools.tool_schemas()}
        for name in ("record_facts", "read_jd"):
            self.assertEqual(set(schemas[name]["properties"]), {"source_id"})
            for args in ({}, {"source_id": 7}, {"source_id": " "}, {"source_id": "current", "text": "new fact"}):
                outcome = await tools.execute_tool(name, {}, args, tools.ToolContext())
                self.assertEqual(outcome.result["code"], "invalid_arguments")
                self.assertEqual(outcome.update, {})
        self.assertEqual((await tools.execute_tool("missing", {}, {}, tools.ToolContext())).result["code"], "unknown_tool")

    async def test_unknown_or_assistant_source_is_never_extracted(self):
        state = {"messages": [AIMessage(content="模型建议", id="assistant-id")]}
        model = Extractor({})
        for source_id in ("current", "assistant-id", "absent"):
            outcome = await tools.record_facts(state, {"source_id": source_id}, tools.ToolContext(llm=model))
            self.assertEqual(outcome.result["code"], "unknown_source")
        self.assertFalse(model.requests)

    async def test_external_and_excluded_sources_are_rejected_before_models(self):
        for text, metadata in (("岗位职责：编写统计报告", {}), ("我的经历：整理材料", {"career_material_type": "reference"}),
                               ("他人简历：协助整理材料", {}), ("参考简历：协助整理材料", {})):
            with self.subTest(text=text):
                state = {"messages": [HumanMessage(content=text, id="source", additional_kwargs=metadata)]}
                model = Extractor({})
                outcome = await tools.record_facts(state, {"source_id": "source"}, tools.ToolContext(llm=model))
                self.assertEqual(outcome.result["code"], "not_candidate_material")
                self.assertFalse(model.requests)
        state = {"messages": [HumanMessage(content="我的经历：整理材料", id="source")], "non_candidate_message_ids": ["source"]}
        self.assertEqual((await tools.record_facts(state, {"source_id": "source"}, tools.ToolContext())).result["code"],
                         "not_candidate_material")

    async def test_record_uses_historical_original_provenance_and_saves_before_return(self):
        source = "我在资料核对项目中核对重复记录并提交核对表。"
        model = Extractor({"items": [{"section": "projects", "name": "资料核对项目", "facts": [
            {"kind": "action", "text": "核对重复记录并提交核对表", "source_quote": "核对重复记录并提交核对表"}]}]})
        state = {**graph._init_state(), "messages": [HumanMessage(content=source, id="original"),
                                                   HumanMessage(content="直接生成", id="latest")]}
        before, saved = deepcopy(state), []
        async def save(values):
            saved.append(deepcopy(values))
        token = graph._intake_saver.set(save)
        try:
            ctx = tools.ToolContext(llm=model)
            outcome = await tools.record_facts(state, {"source_id": "original"}, ctx)
            repeated = await tools.record_facts({**state, **outcome.update}, {"source_id": "original"}, ctx)
        finally:
            graph._intake_saver.reset(token)
        self.assertEqual(outcome.result["status"], "ok")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["collected_info"], outcome.update["collected_info"])
        facts = outcome.update["collected_info"]["projects"][0]["facts"]
        self.assertEqual(facts[0]["turn_id"], "original")
        self.assertEqual(facts[0]["sources"][0]["turn_id"], "original")
        self.assertEqual(json.loads(model.requests[0][-1].content)["message"], source)
        self.assertEqual(repeated.result["code"], "source_already_recorded")
        self.assertNotIn("resume_data", outcome.update)
        self.assertEqual(state, before)

    async def test_save_failure_never_claims_recorded_or_marks_source_done(self):
        state = {**graph._init_state(), "messages": [HumanMessage(content="姓名：离线候选人\n教育背景\n示例学院 | 计算机 | 本科", id="source")]}
        ctx = tools.ToolContext(llm=Extractor({"basic_info": {"name": "离线候选人"}}))
        token = graph._intake_saver.set(AsyncMock(side_effect=RuntimeError("private provider body")))
        try:
            result = await tools.record_facts(state, {"source_id": "current"}, ctx)
        finally:
            graph._intake_saver.reset(token)
        self.assertEqual(result.result["status"], "error")
        self.assertEqual(result.update, {})
        self.assertFalse(ctx.recorded_sources)
        self.assertNotIn("private provider body", str(result))

    async def test_uncovered_material_is_reported_without_fabricated_experience(self):
        state = {**graph._init_state(), "messages": [HumanMessage(content="我还整理过反馈清单", id="source")]}
        result = await tools.record_facts(state, {"source_id": "current"}, tools.ToolContext(llm=Extractor({})))
        self.assertEqual(result.result["status"], "partial")
        self.assertTrue(result.result["uncovered"])
        self.assertTrue(result.update["collected_info"]["verification_notes"])
        self.assertFalse(result.update["collected_info"].get("projects"))

    async def test_import_preserves_contacts_locally_and_result_is_redacted(self):
        text = f"姓名：离线候选人\n电话：{PHONE}\n邮箱：{EMAIL}\n教育背景\n示例学院 | 计算机 | 本科\n项目经历\n资料核对项目 | 2025.03-2025.06\n核对重复记录并提交核对表\n专业技能\nPython（基础）"
        state = {**graph._init_state(), "messages": [HumanMessage(content=text, id="upload")]}
        result = await tools.record_facts(state, {"source_id": "current"}, tools.ToolContext())
        self.assertEqual(result.result["status"], "ok")
        self.assertEqual(result.update["collected_info"]["basic_info"]["phone"], PHONE)
        self.assertEqual(result.update["collected_info"]["basic_info"]["email"], EMAIL)
        self.assertIn("基础", str(result.update["collected_info"]["skills"]))
        for fact in result.update["collected_info"]["projects"][0]["facts"]:
            self.assertEqual(fact["turn_id"], "upload")
        self.assert_private(result.result)
        self.assert_private(result.events)

    async def test_extractor_contact_boundary_and_unsupported_claim_rejection(self):
        text = f"我在资料核对项目中核对重复记录并提交核对表。电话：{PHONE}，邮箱：{EMAIL}。"
        model = Extractor({"basic_info": {"phone": PHONE, "email": EMAIL}, "items": [
            {"section": "projects", "name": "资料核对项目", "facts": [
                {"text": "服务900万用户", "source_quote": "核对重复记录并提交核对表", "kind": "result_metric"},
                {"text": "核对重复记录并提交核对表", "source_quote": "核对重复记录并提交核对表", "kind": "action"}]}]})
        result = await tools.record_facts({"messages": [HumanMessage(content=text, id="contact-turn")]},
                                         {"source_id": "current"}, tools.ToolContext(llm=model))
        self.assertEqual(result.result["status"], "ok")
        self.assertGreater(result.result["rejected_count"], 0)
        self.assertNotIn("900万", json.dumps(result.update, ensure_ascii=False))
        self.assert_private(model.requests)
        self.assert_private(result.result)
        self.assertEqual(result.update["collected_info"]["basic_info"]["phone"], PHONE)

    async def test_read_jd_updates_only_target_and_blocks_later_fact_record(self):
        state = {**graph._init_state(), "messages": [HumanMessage(content="岗位职责：核对业务记录。任职要求：SQL。", id="jd")],
                 "collected_info": collected(), "pending_plan": {"old": True}}
        ctx = tools.ToolContext(llm=object())
        with patch("app.agents.decoder_chain.run_decoder_chain", new=AsyncMock(return_value={
                "jd_info": {"job_title": "数据助理", "required_skills": ["SQL"]}, "summary": "来源描述"})) as decoder:
            result = await tools.read_jd(state, {"source_id": "current"}, ctx)
        self.assertEqual(result.result["status"], "ok")
        self.assertEqual(decoder.call_args.args[0], state["messages"][0].content)
        self.assertEqual(result.update["pending_plan"], {})
        self.assertNotIn("collected_info", result.update)
        self.assertEqual(result.update["non_candidate_message_ids"], ["jd"])
        blocked = await tools.record_facts({**state, **result.update}, {"source_id": "jd"}, ctx)
        self.assertEqual(blocked.result["code"], "not_candidate_material")

    async def test_mixed_jd_message_keeps_candidate_source_available(self):
        text = "我的经历：我在资料核对项目中核对重复记录并提交核对表。\nJD：岗位职责：整理报表。任职要求：SQL。"
        state = {**graph._init_state(), "messages": [HumanMessage(content=text, id="mixed")]}
        ctx = tools.ToolContext(llm=Extractor({}))
        with patch("app.agents.decoder_chain.run_decoder_chain", new=AsyncMock(return_value={
                "jd_info": {"job_title": "数据助理"}})):
            jd = await tools.read_jd(state, {"source_id": "current"}, ctx)
        self.assertNotIn("mixed", jd.update.get("non_candidate_message_ids", []))
        facts = await tools.record_facts({**state, **jd.update}, {"source_id": "mixed"}, ctx)
        self.assertNotEqual(facts.result.get("code"), "not_candidate_material")
        self.assertNotIn("岗位职责", ctx.llm.requests[0][-1].content)

    async def test_personal_material_cannot_overwrite_jd_and_decode_failure_preserves_state(self):
        ctx = tools.ToolContext(llm=object())
        state = {"jd_info": {"job_title": "旧岗位"}, "messages": [HumanMessage(content="我负责整理材料", id="personal")]}
        with patch("app.agents.decoder_chain.run_decoder_chain", new=AsyncMock(return_value={})) as decoder:
            rejected = await tools.read_jd(state, {"source_id": "current"}, ctx)
            self.assertEqual(rejected.result["code"], "not_job_material")
            decoder.assert_not_called()
            state["messages"] = [HumanMessage(content="岗位职责：整理材料", id="jd")]
            failed = await tools.read_jd(state, {"source_id": "current"}, ctx)
            self.assertEqual(failed.result["status"], "insufficient")
            self.assertEqual(failed.update, {})

    async def test_read_job_url_reuses_safe_reader_and_no_fetch_failure_decode(self):
        state = {"messages": [HumanMessage(content="请读 https://jobs.example.invalid/job", id="url")]}
        fetched = {"status": "ok", "page": {"content": "岗位职责：核对材料", "kind": "job_page", "url": "https://jobs.example.invalid/job"},
                   "card": {"url": "https://jobs.example.invalid/job", "fetched_at": "2026-10-19", "job_title": "助理"}}
        with patch("app.services.job_intel.read_job_url", new=AsyncMock(return_value=fetched)) as reader, \
                patch("app.agents.decoder_chain.run_decoder_chain", new=AsyncMock(return_value={"jd_info": {"job_title": "助理"}})) as decoder:
            outcome = await tools.read_jd(state, {"source_id": "url"}, tools.ToolContext(llm=object()))
            self.assertEqual(outcome.update["jd_info"]["source"], "job_url")
            self.assertEqual(outcome.update["jd_text"], fetched["page"]["content"])
            self.assertTrue(outcome.update["web_sources"])
            reader.return_value = {"status": "needs_manual", "message": "复制正文"}
            blocked = await tools.read_jd(state, {"source_id": "url"}, tools.ToolContext(llm=object()))
            self.assertEqual(blocked.result["status"], "needs_manual")
            self.assertEqual(decoder.await_count, 1)

    async def test_company_search_once_even_on_exception_and_per_turn_isolation(self):
        ctx = tools.ToolContext()
        with patch("app.services.job_intel.search_company", new=AsyncMock(side_effect=RuntimeError(EMAIL))) as search:
            first = await tools.search_company({}, {"name": "示例公司"}, ctx)
            second = await tools.search_company({}, {"name": "另一个公司"}, ctx)
            self.assertEqual(first.result["code"], "tool_exception")
            self.assertEqual(second.result["status"], "limited")
            self.assertEqual(search.await_count, 1)
            await tools.search_company({}, {"name": "示例公司"}, tools.ToolContext())
            self.assertEqual(search.await_count, 2)
            self.assert_private(first.result)

    async def test_company_result_is_reference_only_and_contact_name_is_not_sent(self):
        with patch("app.services.job_intel.search_company", new=AsyncMock(return_value={
                "status": "ok", "company": {"name": "示例公司", "description": {"text": EMAIL}}})) as search:
            result = await tools.search_company({"jd_info": {"job_title": "助理"}}, {"name": "示例公司"}, tools.ToolContext())
            self.assertEqual(result.update["jd_info"]["job_title"], "助理")
            self.assertNotIn("collected_info", result.update)
            self.assert_private(result.result)
            rejected = await tools.search_company({}, {"name": EMAIL}, tools.ToolContext())
            self.assertEqual(rejected.result["code"], "contacts_in_company_name")
            self.assertEqual(search.await_count, 1)

    async def test_profile_read_before_use_and_server_side_import(self):
        ctx = tools.ToolContext()
        with patch("app.services.profile_tools.execute_profile_tool", new=AsyncMock(side_effect=[
                ({"status": "ok", "items": [{"id": "owned", "name": "项目"}]}, {}),
                ({"status": "ok", "facts": [{"text": PHONE}]}, {"collected_info": collected()})])) as execute:
            denied = await tools.use_profile_items({}, {"item_ids": ["owned"]}, ctx)
            self.assertEqual(denied.result["code"], "read_profile_first_or_unknown_item")
            execute.assert_not_called()
            await tools.read_profile({}, {}, ctx)
            foreign = await tools.use_profile_items({}, {"item_ids": ["foreign"]}, ctx)
            self.assertEqual(foreign.update, {})
            used = await tools.use_profile_items({}, {"item_ids": ["owned"]}, ctx)
            self.assertEqual(used.update["collected_info"]["basic_info"]["phone"], PHONE)
            self.assert_private(used.result)

    async def test_profile_guest_is_unavailable_without_database_access(self):
        with patch("app.services.profile_tools.runtime", return_value=None), \
                patch("app.services.profile_bridge.SessionLocal") as database:
            result = await tools.read_profile({}, {}, tools.ToolContext())
            self.assertEqual(result.result["status"], "unavailable")
            database.assert_not_called()

    async def test_ask_user_works_at_cold_start_and_keeps_question_metadata(self):
        args = {"card": {"questions": [{"id": "experience", "prompt": "做过哪些事情？", "kind": "text"}]}}
        outcome = await tools.ask_user(graph._init_state(), args, tools.ToolContext(turn_id="question-turn"))
        self.assertEqual(outcome.result["status"], "ok")
        self.assertTrue(outcome.stop)
        message = outcome.update["messages"][0]
        self.assertEqual(message.additional_kwargs["ask_user"]["turn_id"], "question-turn")
        self.assertEqual(outcome.events[-1]["guidance"], message.additional_kwargs["ask_user"])
        self.assertNotIn("collected_info", outcome.update)

    async def test_ask_user_rejects_invalid_cards_and_suppresses_closed_dimensions(self):
        ctx = tools.ToolContext()
        invalid = await tools.ask_user({}, {"card": {"questions": [
            {"id": "bad", "prompt": "选择", "kind": "single", "options": ["一项"]}]}}, ctx)
        self.assertEqual(invalid.result["code"], "invalid_arguments")
        args = {"card": {"questions": [{"id": "fresh_slug", "prompt": "有多少人用过？", "kind": "text"}]}}
        state = {"closed_questions": [{"id": "users", "dimension": "adoption", "reason": "unknown"}]}
        closed = await tools.ask_user(state, args, ctx)
        self.assertEqual(closed.result["code"], "questions_closed")
        for state in ({"pending_plan": {"recommended": {}}}, {"collected_info": {"no_more_questions": True}}):
            disabled = await tools.ask_user(state, args, ctx)
            self.assertEqual(disabled.result["code"], "questions_disabled")
            self.assertFalse(disabled.stop)

    async def test_draft_minimum_and_contacts_are_results_not_stage_routing(self):
        for facts in ({}, {"education": [{"school": "示例学院"}]}, {"projects": [{"name": "空项目"}]},
                      {"projects": [{"name": "未知", "facts": [new_fact("未上线", kind="status_limit")]}]}):
            outcome = await tools.write_draft({"collected_info": facts}, {}, tools.ToolContext())
            self.assertEqual(outcome.result["status"], "insufficient")
            self.assertFalse(outcome.stop)
        facts = collected()
        facts["basic_info"] = {"name": "离线候选人"}
        # 先写后问：缺联系方式照常出稿，结果带 contacts_missing 供编排出稿后一次问齐。
        written = tools.ToolOutcome({"status": "ok"}, {"resume_data": {}})
        with patch.object(tools, "_write", AsyncMock(return_value=written)) as write:
            result = await tools.write_draft({"collected_info": facts}, {}, tools.ToolContext())
        write.assert_awaited_once()
        self.assertEqual(result.result["status"], "ok")
        self.assertEqual(result.result["contacts_missing"], ["phone", "email"])
        self.assertEqual(result.result["experience_inventory"]["included"], [])
        self.assertTrue(result.stop)

    async def test_draft_real_pipeline_guard_privacy_and_no_intake_stage_gate(self):
        state = {**graph._init_state(), "collected_info": collected()}
        before = deepcopy(state)
        model = Writer(invented=True)
        # Benchmark imports opt into rejected-text diagnostics; this contract
        # checks the production result, including its metadata, without them.
        with patch.dict(os.environ, {"HUHUA_RECORD_REJECTED_TEXT": "0"}), \
                patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=measured), \
                patch("app.agents.resume_graph._recover_candidate_history", side_effect=AssertionError("no intake here")), \
                patch("app.agents.resume_graph.building_node", side_effect=AssertionError("no stage node")):
            outcome = await tools.write_draft(state, {}, tools.ToolContext(llm=model))
        self.assertEqual(outcome.result["status"], "ok", outcome.result)
        self.assertTrue(outcome.stop)
        self.assertNotIn("900万", json.dumps(outcome.update, ensure_ascii=False))
        self.assertTrue(outcome.result["guard_fallbacks"])
        self.assertEqual(outcome.update["resume_data"]["basic_info"]["phone"], PHONE)
        self.assert_private(outcome.result)
        self.assert_private(model.requests)
        self.assertNotIn("collected_info", outcome.update)
        self.assertEqual(state, before)
        self.assertTrue(outcome.update["version_id"])

    async def test_edit_keeps_untargeted_content_and_emits_reversible_version(self):
        state = state_with_draft()
        before = deepcopy(state)
        from app.services.resume_versions import prepare_version
        async def pipeline(working, base, llm, **kwargs):
            self.assertEqual(kwargs["scope"], "item")
            self.assertEqual(kwargs["targets"], ["p2"])
            data = deepcopy(base)
            data["projects"][1]["polished_bullets"] = ["完成页面原型；记录评审意见"]
            return {**prepare_version(working["resume_data"], working["resume_meta"], [], data, {}),
                    "edit_contract": {"p2": {"status": "applied"}}}
        with patch("app.agents.tailor_pipeline.run_tailor_pipeline", side_effect=pipeline):
            outcome = await tools.edit_resume(state, {"instruction": "请把第二个项目改短"}, tools.ToolContext(llm=object()))
        self.assertEqual(outcome.result["status"], "ok")
        self.assertEqual(outcome.update["resume_data"]["projects"][0], before["resume_data"]["projects"][0])
        self.assertEqual(outcome.update["resume_versions"][0]["resume_data"], before["resume_data"])
        restored = await tools.edit_resume({**state, **outcome.update}, {"instruction": "撤销"}, tools.ToolContext())
        self.assertEqual(restored.update["resume_data"], before["resume_data"])
        self.assertNotIn("collected_info", restored.update)
        self.assertEqual(state, before)

    async def test_edit_real_pipeline_preserves_scope_on_writer_failure(self):
        state = state_with_draft()
        before = deepcopy(state)
        with patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=measured):
            result = await tools.edit_resume(state, {"instruction": "把第二个项目改短"}, tools.ToolContext(llm=Writer(fail=True)))
        self.assertEqual(result.result["status"], "error")
        self.assertEqual(result.result["error_type"], "ChatTurnError")
        self.assertEqual(result.update, {})
        self.assertEqual(state, before)

    async def test_edit_missing_target_does_not_call_writer_or_collect_new_facts(self):
        state = state_with_draft()
        with patch("app.agents.tailor_pipeline.run_tailor_pipeline") as writer:
            result = await tools.edit_resume(state, {"instruction": "把第九个项目改短"}, tools.ToolContext(llm=object()))
            self.assertEqual(result.result["status"], "insufficient")
            writer.assert_not_called()
        empty = await tools.edit_resume({}, {"instruction": "简洁一些"}, tools.ToolContext())
        self.assertEqual(empty.result["status"], "insufficient")

    async def test_direction_changes_only_target_not_personal_facts(self):
        state = state_with_draft()
        state["jd_info"] = {"job_title": "旧岗位", "required_skills": ["旧要求"]}
        state["jd_text"] = "旧岗位原文"
        with patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=measured):
            outcome = await tools.write_draft(state, {"direction": "后端开发", "emphasis": "突出实现方法"}, tools.ToolContext(llm=Writer()))
        self.assertEqual(outcome.update["jd_text"], "")
        self.assertEqual(outcome.update["jd_info"]["role_direction"], "后端开发")
        self.assertNotIn("required_skills", outcome.update["jd_info"])
        self.assertNotIn("collected_info", outcome.update)

    async def test_propose_plan_is_plan_only_and_reuses_pending_card(self):
        card = {"recommended": {"label": "推荐", "positioning": "按事实组织", "thesis": "保留具体做法",
                "experience_plan": [{"item_id": "p1", "treatment": "lead", "target_bullets": 1}],
                "section_order": ["projects"]}, "alternatives": []}
        state = {**graph._init_state(), "collected_info": collected()}
        with patch("app.agents.resume_writer.run_resume_writer", new=AsyncMock(return_value={"structure_plan": card})) as planner:
            outcome = await tools.propose_plan(state, {}, tools.ToolContext(llm=object(), turn_id="plan-turn"))
            self.assertEqual(outcome.result["status"], "ok")
            self.assertEqual(planner.call_args.kwargs["phase"], "plan")
            self.assertTrue(outcome.stop)
            self.assertNotIn("resume_data", outcome.update)
            self.assertEqual(outcome.events[-1]["guidance"]["kind"], "structure_plan")
            repeated = await tools.propose_plan({**state, **outcome.update}, {}, tools.ToolContext())
            self.assertEqual(repeated.result["status"], "ok")
            self.assertEqual(planner.await_count, 1)

    async def test_layout_measures_current_copy_without_pdf_output_or_body_mutation(self):
        state = state_with_draft()
        before = deepcopy(state)
        with patch("app.services.resume_pdf.measure_resume_pdf_layout", return_value={"pages": 2}) as layout, \
                patch("app.services.resume_pdf.render_resume_pdf", side_effect=AssertionError("no PDF writing")):
            outcome = await tools.check_layout(state, {}, tools.ToolContext())
        self.assertEqual(outcome.result["page_check"]["pages"], 2)
        self.assertFalse(outcome.result["page_check"]["within_page_limit"])
        self.assertEqual(layout.call_args.args[1], before["resume_data"])
        self.assertEqual(state, before)
        self.assertNotIn("resume_data", outcome.update)
        self.assertEqual(outcome.update["resume_meta"]["version_id"], "v-original")

    async def test_layout_failure_does_not_overwrite_old_measurement(self):
        state = state_with_draft()
        state["page_check"] = {"status": "rendered", "pages": 1}
        with patch("app.services.resume_pdf.measure_resume_pdf_layout", side_effect=RuntimeError(EMAIL)):
            result = await tools.check_layout(state, {}, tools.ToolContext())
        self.assertEqual(result.update, {})
        self.assert_private(result.result)
        self.assertEqual(result.result["error_type"], "RuntimeError")

    async def test_progress_stream_order_and_cancellation_propagates(self):
        events = []
        async def search(name, **kwargs):
            self.assertEqual(events[-1]["status"], "running")
            return {"status": "unavailable"}
        with patch("app.services.job_intel.search_company", side_effect=search):
            result = await tools.search_company({}, {"name": "示例公司"}, tools.ToolContext(emit=events.append))
        self.assertEqual([row["status"] for row in result.events], ["running", "completed"])
        self.assertEqual(events, result.events)
        import asyncio
        with patch("app.services.job_intel.search_company", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await tools.search_company({}, {"name": "示例公司"}, tools.ToolContext())


    async def test_real_decoder_redacts_contacts_and_keeps_jd_as_data(self):
        model = Extractor({"job_title": "数据助理", "required_skills": ["SQL"]})
        text = f"岗位职责：整理报表。任职要求：SQL。招聘联系电话：{PHONE}，邮箱：{EMAIL}。"
        result = await tools.read_jd({"messages": [HumanMessage(content=text, id="jd-contact")]},
                                    {"source_id": "current"}, tools.ToolContext(llm=model))
        self.assertEqual(result.result["status"], "ok")
        self.assertTrue(model.requests)
        self.assert_private(model.requests)
        self.assertNotIn(text, model.requests[0][0].content)
        self.assertEqual(result.update["jd_text"], text)

    async def test_deterministic_hide_and_undo_do_not_rewrite_or_delete_facts(self):
        state = state_with_draft()
        state["messages"] = [HumanMessage(content="删除第二个项目", id="hide")]
        before = deepcopy(state)
        with patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=measured), \
                patch("app.agents.tailor_pipeline.run_tailor_pipeline", side_effect=AssertionError("no writer")):
            result = await tools.edit_resume(state, {"instruction": "删除第二个项目"}, tools.ToolContext())
        self.assertEqual(result.result["status"], "ok", result.result)
        self.assertTrue(result.update["resume_data"]["projects"][1]["hidden"])
        self.assertEqual(result.update["resume_data"]["projects"][0], state["resume_data"]["projects"][0])
        restored = await tools.edit_resume({**state, **result.update}, {"instruction": "撤销"}, tools.ToolContext())
        self.assertEqual(restored.update["resume_data"], before["resume_data"])
        self.assertNotIn("collected_info", result.update)
        self.assertEqual(state, before)

    async def test_model_field_value_is_not_user_authorization(self):
        state = state_with_draft()
        with patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=measured):
            outcome = await tools.edit_resume(state, {"instruction": "姓名改成冒名"}, tools.ToolContext())
        self.assertNotEqual(outcome.result["status"], "ok")
        self.assertNotIn("冒名", json.dumps(outcome.update.get("resume_data"), ensure_ascii=False))
        self.assertNotIn("collected_info", outcome.update)

    async def test_real_layout_without_pdf_serialization(self):
        from app.services.resume_capacity import resume_data_hash
        state = state_with_draft()
        with patch("weasyprint.document.Document.write_pdf", side_effect=AssertionError("no PDF")):
            outcome = await tools.check_layout(state, {}, tools.ToolContext())
        self.assertEqual(outcome.result["status"], "ok", outcome.result)
        self.assertGreaterEqual(outcome.result["page_check"]["pages"], 1)
        self.assertEqual(outcome.result["page_check"]["data_hash"], resume_data_hash(state["resume_data"]))

    async def test_second_question_card_is_limited_in_same_turn(self):
        args = {"card": {"questions": [{"id": "task", "prompt": "具体做了什么？", "kind": "text"}]}}
        ctx = tools.ToolContext()
        await tools.ask_user({}, args, ctx)
        again = await tools.ask_user({}, args, ctx)
        self.assertEqual(again.result["code"], "question_card_already_used")

    async def test_writing_cannot_harvest_unrecorded_history_and_same_direction_keeps_jd(self):
        state = {**graph._init_state(), "collected_info": collected(), "jd_text": "岗位职责：核对数据",
                 "jd_info": {"job_title": "数据助理", "required_skills": ["SQL"]},
                 "messages": [HumanMessage(content="我身高178cm", id="unrecorded")]}
        from app.services.resume_versions import prepare_version
        async def pipeline(working, base, llm, **kwargs):
            self.assertFalse(base["basic_info"]["height"])
            self.assertEqual(working["jd_text"], state["jd_text"])
            self.assertEqual(working["jd_info"], state["jd_info"])
            return prepare_version({}, {}, [], base, {})
        with patch("app.agents.tailor_pipeline.run_tailor_pipeline", side_effect=pipeline):
            outcome = await tools.write_draft(state, {"direction": "数据助理"}, tools.ToolContext(llm=object()))
        self.assertEqual(outcome.result["status"], "ok", outcome.result)
        self.assertNotIn("collected_info", outcome.update)


import test_profile_archive as archive_fixture  # noqa: E402


class OrchestratorToolsStorageTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = archive_fixture.ArchiveTests.asyncSetUp
    asyncTearDown = archive_fixture.ArchiveTests.asyncTearDown
    add = archive_fixture.ArchiveTests.add

    async def test_record_facts_commits_sql_without_changing_saved_document(self):
        from app.models.models import ResumeSession
        from app.services.session_store import save_candidate_intake, load_resume_session
        from app.services.data_crypto import get_crypto
        state = state_with_draft()
        source = "我在资料核对项目中整理归档记录。"
        state["messages"] = [HumanMessage(content=source, id="new-source")]
        model = Extractor({"items": [{"section": "projects", "item_id": "p1", "name": "资料核对项目", "facts": [
            {"text": "整理归档记录", "source_quote": "整理归档记录", "kind": "action"}]}]})
        # ResumeSession uses the application's encrypted JSON type; keep its
        # crypto context stable while this isolated SQLite database is alive.
        self.enterContext(patch("app.services.data_crypto.get_crypto", return_value=get_crypto()))
        self.enterContext(patch("app.services.session_store.SessionLocal", self.factory))
        with self.factory() as db:
            db.add(ResumeSession(session_id="adapter", resume_data=state["resume_data"], stage="EVALUATING",
                resume_state={"collected_info": state["collected_info"], "resume_meta": state["resume_meta"], "resume_versions": []}))
            db.commit()
        async def save(values):
            save_candidate_intake("adapter", values["collected_info"], values["session_constraints"], "EVALUATING")
        token = graph._intake_saver.set(save)
        try:
            result = await tools.record_facts(state, {"source_id": "current"}, tools.ToolContext(llm=model))
        finally:
            graph._intake_saver.reset(token)
        self.assertEqual(result.result["status"], "ok", result.result)
        saved = load_resume_session("adapter")
        self.assertIn("整理归档记录", str(saved["collected_info"]))
        self.assertEqual(saved["resume_data"], state["resume_data"])
        self.assertEqual(saved["resume_meta"], state["resume_meta"])
        with patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=measured):
            failed = await tools.write_draft({**state, **result.update}, {}, tools.ToolContext(llm=Writer(fail=True)))
        self.assertEqual(failed.result["status"], "error")
        self.assertEqual(load_resume_session("adapter")["collected_info"], saved["collected_info"])

    async def test_profile_account_boundary_and_provenance_use_real_service(self):
        from app.models.models import Conversation
        from app.services import profile_bridge
        from app.services.profile_tools import profile_runtime
        owned = self.add(subject="本人核对项目", field="description", value="核对重复记录并提交核对表")
        foreign = self.add(account="b", subject="其他账号项目", field="description", value="不应导入的材料")
        with self.factory() as db:
            db.add(Conversation(session_id="adapter-profile", owner_hash="account:a", title="离线隔离测试"))
            db.commit()
        state = {**graph._init_state(), "intake_account": True, "profile_summary": {"has_facts": True}}
        token = profile_runtime.set(("account:a", "adapter-profile"))
        ctx = tools.ToolContext()
        try:
            with patch.object(profile_bridge, "SessionLocal", self.factory):
                read = await tools.read_profile(state, {}, ctx)
                self.assertEqual([row["id"] for row in read.result["items"]], [owned["id"]])
                used = await tools.use_profile_items(state, {"item_ids": [owned["id"]]}, ctx)
                self.assertEqual(used.result["status"], "ok", used.result)
                self.assertTrue(used.update["collected_info"]["projects"][0]["facts"][0]["profile_refs"])
                # Even a compromised caller-side catalog cannot bypass the service.
                ctx.profile_item_ids.add(foreign["id"])
                denied = await tools.use_profile_items(state, {"item_ids": [foreign["id"]]}, ctx)
                self.assertEqual(denied.result["status"], "invalid_items")
                self.assertEqual(denied.update, {})
        finally:
            profile_runtime.reset(token)


if __name__ == "__main__":
    unittest.main()
