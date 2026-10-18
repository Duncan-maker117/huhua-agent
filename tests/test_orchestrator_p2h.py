"""P2h delivery regressions; offline tools, writer doubles and protocol scripts."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests")]
from app.agents import orchestrator as loop, orchestrator_tools as tools  # noqa: E402
from app.agents import resume_graph as graph  # noqa: E402
from app.agents.orchestrator_context import project_tool_result, OrchestratorSettings  # noqa: E402
from app.config import Settings  # noqa: E402
from app.services.ask_user import close_answers, pending_card  # noqa: E402
from app.services.model_privacy import ContactRedactor  # noqa: E402
from app.services.resume_facts import new_fact, normalize_fact_store  # noqa: E402
from app.services.resume_versions import text_hash  # noqa: E402
from test_orchestrator import Model, call, registry, state  # noqa: E402
from test_orchestrator_tools import PHONE, EMAIL, Writer, measured, state_with_draft  # noqa: E402


def followup_state():
    value = state_with_draft()
    value["match_plan"] = {"questions": [{"q": "如何验证核对结果？", "value": 5,
        "improves": {"item_id": "p1", "req_id": ""}}]}
    return value


def draft_outcome(value):
    return tools.ToolOutcome({"status": "ok", "resume_data": deepcopy(value["resume_data"])},
        {key: deepcopy(value[key]) for key in ("resume_data", "resume_meta", "match_plan")})


def campus_facts():
    def fact(text, kind, fid, field=None):
        row = {**new_fact(text, kind=kind, quote=text, turn_id="campus-turn"), "id": fid}
        if field:
            row["field"] = field
        return row
    return normalize_fact_store({"basic_info": {"name": "候选人", "phone": PHONE, "email": EMAIL}, "campus": [
        {"item_id": "named", "name": "校内资料社", "start_date": "2025.03", "end_date": "2025.05", "facts": [
            fact("2025.03", "context", "start", "start_date"), fact("2025.05", "context", "end", "end_date"),
            fact("不是活动负责人", "status_limit", "limit")]},
        {"item_id": "unnamed", "name": "校园经历（待补组织名）", "facts": [
            fact("在校内资料社担任志愿者", "role", "role"),
            fact("用表格核对了36条登记记录", "action", "action"),
            fact("整理成3张汇总表交给社长", "deliverable", "delivery"),
            fact("只负责登记和核对", "role", "scope"),
            fact("没有统计活动增长", "status_limit", "no-growth")]}]})


class P2hLoopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch("app.config.get_settings", return_value=Settings(_env_file=None, AGENT_MODE="loop")))

    def draft_tools(self, value):
        self.enterContext(patch.object(tools, "_write", AsyncMock(side_effect=lambda *a, **kw: draft_outcome(value))))
        specs = registry()
        specs.update({name: tools.TOOLS[name] for name in ("write_draft", "ask_user")})
        return specs

    async def test_write_then_one_ask_same_turn_and_closed_dimension_stays_closed(self):
        value = followup_state()
        card = tools._draft_followup(value, tools.ToolContext())
        specs = self.draft_tools(value)
        model = Model([call("write_draft"), call("ask_user", card=card), {"content": "稿件已生成，卡片补充一点即可。"}])
        events = []
        result = await loop.run_orchestrator(value, model, registry=specs, emit=events.append)
        self.assertEqual([r["allow_tools"] for r in model.requests], [True, True, False])
        self.assertEqual([r["mode"] for r in model.requests], ["thinking", "thinking", "off"])
        cards = [e["guidance"] for e in events if e["type"] == "guidance"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0], pending_card({**value, **result}))
        self.assertEqual(len(cards[0]["questions"]), 1)
        self.assertEqual(cards[0]["questions"][0]["id"], "evaluation")
        self.assertEqual(result["resume_data"], value["resume_data"])
        closed = close_answers({**value, **result}, "", {"turn_id": cards[0]["turn_id"],
            "items": [{"id": "evaluation", "unknown": True}]})
        outcome = await tools.write_draft({**value, **result, "closed_questions": closed}, {}, tools.ToolContext())
        self.assertTrue(all(q["id"] != "evaluation" for q in outcome.result.get("followup", {}).get("questions", [])))
        self.assertEqual([r["name"] for r in result["messages"][-1].additional_kwargs["orchestrator"]["tools"]],
                         ["write_draft", "ask_user"])

    async def test_tool_budget_attaches_card_without_fifth_model_tool(self):
        value = followup_state()
        specs = self.draft_tools(value)
        model = Model([call("check_layout"), call("check_layout"), call("check_layout"),
                       call("write_draft"), {"content": "完成。"}])
        result = await loop.run_orchestrator(value, model, registry=specs)
        self.assertTrue(pending_card({**value, **result}))
        metrics = result["messages"][-1].additional_kwargs["orchestrator"]
        self.assertEqual((metrics["tool_steps"], metrics["model_calls"]), (4, 5))
        self.assertEqual(len([r for r in metrics["tools"] if r.get("automatic")]), 1)
        raw = next(m for m in model.requests[-1]["messages"] if m.get("role") == "tool"
                   and json.loads(m["content"])["untrusted_data"].get("followup_attached"))
        self.assertTrue(json.loads(raw["content"])["untrusted_data"]["followup_attached"])

    async def test_model_budget_attaches_card_even_with_tool_slot_left(self):
        from test_orchestrator import BadRequest
        value = followup_state()
        specs = self.draft_tools(value)
        model = Model([BadRequest("protocol"), call("check_layout"), call("check_layout"),
                       call("write_draft"), {"content": "完成。"}])
        result = await loop.run_orchestrator(value, model, registry=specs)
        self.assertTrue(pending_card({**value, **result}))
        metrics = result["messages"][-1].additional_kwargs["orchestrator"]
        self.assertEqual((metrics["tool_steps"], metrics["model_calls"]), (3, 5))

    async def test_followup_survives_text_only_invalid_ask_and_final_failure(self):
        value = followup_state()
        specs = self.draft_tools(value)
        scripts = [
            [call("write_draft"), {"content": "稿件已生成。"}],
            [call("write_draft"), RuntimeError("offline")],
            [call("write_draft"), call("ask_user", card={"questions": []}), {"content": "完成。"}],
            [call("write_draft"), call("edit_resume", instruction="再次改写"), {"content": "完成。"}],
        ]
        for script in scripts:
            with self.subTest(script=script):
                events = []
                result = await loop.run_orchestrator(value, Model(script), registry=specs, emit=events.append)
                self.assertTrue(pending_card({**value, **result}))
                self.assertEqual(len([e for e in events if e["type"] == "guidance"]), 1)
        specs["edit_resume"].handler.assert_not_awaited()

    async def test_no_draft_no_candidates_or_stop_request_never_inserts_followup(self):
        value = followup_state()
        for change in ({"collected_info": {}}, {"match_plan": {}, "resume_data": {"education": [{"school": "测试学院"}]}},
                       {"collected_info": {**value["collected_info"], "no_more_questions": True}}):
            with self.subTest(change=change):
                current = {**value, **change}
                with patch.object(tools, "_write", AsyncMock(return_value=draft_outcome(current))) as writer:
                    outcome = await tools.write_draft(current, {}, tools.ToolContext(followup_available=False))
                self.assertNotIn("followup", outcome.result)
                self.assertFalse(any(e["type"] == "guidance" for e in outcome.events))
                if not current["collected_info"]:
                    writer.assert_not_awaited()

    async def test_followup_context_survives_large_document_and_keeps_question_id(self):
        value = followup_state()
        value["resume_data"]["summary"] = "大段正文" * 4000
        with patch.object(tools, "_write", AsyncMock(return_value=draft_outcome(value))):
            outcome = await tools.write_draft(value, {}, tools.ToolContext())
        projected = project_tool_result("write_draft", outcome.result, ContactRedactor())
        self.assertEqual(projected["followup"]["questions"][0]["id"], "evaluation")
        self.assertNotIn(PHONE, str(projected))
        self.assertNotIn(EMAIL, str(projected))

    async def test_contacts_are_requested_after_draft_once_even_if_final_omits_or_fails(self):
        for final in ({"content": "稿件已生成。"}, RuntimeError("offline"),
                      {"content": "请补充姓名、手机和邮箱。"}, {"content": "请补充姓名。"}):
            with self.subTest(final=final):
                value = followup_state()
                value["collected_info"]["basic_info"] = {}
                value["resume_data"]["basic_info"] = {}
                value["match_plan"] = {}
                specs = self.draft_tools(value)
                model = Model([call("write_draft"), final])
                events = []
                result = await loop.run_orchestrator(value, model, registry=specs, emit=events.append)
                content = result["messages"][-1].content
                for name in ("姓名", "手机", "邮箱"):
                    self.assertEqual(content.count(name), 1, content)
                self.assertEqual(content, "".join(e["content"] for e in events if e["type"] == loop.PUBLIC_REPLY_EVENT))
                self.assertTrue(result["session_constraints"]["contacts_requested"])
                again = await loop.run_orchestrator({**value, **result},
                    Model([call("write_draft"), {"content": "已更新。"}]), registry=specs)
                self.assertEqual(again["messages"][-1].content, "已更新。")

    def test_contact_receipt_does_not_treat_received_or_negated_as_request(self):
        for text in ("邮箱已经收到。", "已记下手机和邮箱。", "不用补手机和邮箱。"):
            self.assertEqual(loop._unrequested_contacts(text, ["phone", "email"]), ["手机", "邮箱"])
        self.assertEqual(loop._unrequested_contacts("邮箱已收到，但还差手机，请补充。", ["phone"]), [])

    async def test_profile_receipt_names_each_import_and_deduplicates_like_public_reply(self):
        for final, appended in (("已选用甲项目。", True), ("已选用甲项目、乙项目。", False)):
            specs = registry(use_profile_items=AsyncMock(return_value=tools.ToolOutcome(
                {"status": "ok", "imported": ["甲项目", "乙项目"]})))
            model = Model([call("use_profile_items", item_ids=["one"]), {"content": final}])
            events = []
            result = await loop.run_orchestrator(state(), model, registry=specs, emit=events.append)
            content = result["messages"][-1].content
            self.assertEqual("已从档案导入：甲项目、乙项目。" in content, appended)
            self.assertEqual(content, "".join(e["content"] for e in events if e["type"] == loop.PUBLIC_REPLY_EVENT))

    async def test_per_tool_durations_have_no_arguments_results_or_error_body(self):
        specs = registry(check_layout=AsyncMock(side_effect=RuntimeError("PRIVATE_BODY")))
        with self.assertLogs(loop.logger, level="INFO") as logs:
            result = await loop.run_orchestrator(state("PRIVATE_INPUT"),
                Model([call("check_layout"), {"content": "完成。"}]), registry=specs)
        metrics = result["messages"][-1].additional_kwargs["orchestrator"]
        row = metrics["tools"][0]
        self.assertEqual(row["name"], "check_layout")
        self.assertGreaterEqual(row["seconds"], 0)
        self.assertEqual(set(row), {"name", "seconds", "status", "code"})
        self.assertNotIn("PRIVATE", str(logs.output))
        self.assertEqual(OrchestratorSettings(_env_file=None).AGENT_FINAL_MODE, "off")


class P2hWritingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=measured))
        self.enterContext(patch("app.services.resume_capacity.measure_rendered_pages", side_effect=measured))

    def test_campus_identity_merge_is_same_turn_unique_and_preserves_fact_sources(self):
        value = campus_facts()
        original = {f["id"]: deepcopy(f) for row in value["campus"] for f in row["facts"]}
        tools._bind_campus_identity(value)
        self.assertEqual(len(value["campus"]), 1)
        self.assertEqual(value["campus"][0]["item_id"], "named")
        self.assertEqual(value["campus"][0]["merged_from"][0]["item_id"], "unnamed")
        self.assertEqual({f["id"]: f for f in value["campus"][0]["facts"]}, original)
        for variant in ("ambiguous", "other_turn", "mixed_turns", "different_period", "named_source"):
            current = campus_facts()
            if variant == "ambiguous":
                current["campus"].append({**deepcopy(current["campus"][0]), "item_id": "another"})
            if variant == "other_turn":
                for fact in current["campus"][0]["facts"]:
                    fact["turn_id"] = "earlier"
            if variant == "mixed_turns":
                current["campus"][1]["facts"][1]["turn_id"] = "earlier"
            if variant == "different_period":
                current["campus"][1]["start_date"] = "2024.03"
            if variant == "named_source":
                current["campus"][1]["name"] = "另一个社团"
            before = deepcopy(current)
            tools._bind_campus_identity(current)
            self.assertEqual(current, before, variant)

    async def test_record_facts_binds_campus_before_persistence_then_writes_plain(self):
        facts = campus_facts()
        saved = []
        async def persist(value, collected):
            saved.append(deepcopy(collected))
            return {"collected_info": collected}
        with patch("app.agents.fact_extractor.extract_facts_patch", AsyncMock(return_value={})), \
                patch("app.agents.fact_extractor.apply_fact_patch", return_value=facts), \
                patch.object(graph, "_persist_intake", side_effect=persist):
            recorded = await tools.record_facts(state("补充资料", collected_info={}), {"source_id": "current"},
                                                tools.ToolContext(llm=object()))
        self.assertEqual(len(saved[0]["campus"]), 1)
        for family in ("data", "ai_pm"):
            current = {**state(), **recorded.update, "jd_info": {"role_direction": "数据运营实习",
                        "role_profile": {"role_family": family}}}
            model = Writer(invented=True)
            outcome = await tools.write_draft(current, {}, tools.ToolContext(llm=model))
            self.assertIn(outcome.result["status"], {"ok", "partial"})
            self.assertNotIn("FactSlots", [name for name, _ in model.requests])
            item = outcome.update["resume_data"]["campus"][0]
            body = " ".join(item["bullets"])
            for word in ("36条", "3张", "核对", "汇总表"):
                self.assertIn(word, body)
            self.assertFalse(any(line.startswith(("问题：", "决策：", "迭代：", "技术：", "现状：")) for line in item["bullets"]))
            self.assertNotIn("900万", body)
            self.assertFalse(item.get("hidden"))
            self.assertEqual((item["start_date"], item["end_date"]), ("2025.03", "2025.05"))
            self.assertNotIn(PHONE, str(model.requests))
            self.assertNotIn(EMAIL, str(model.requests))

    async def test_empty_body_fallback_is_deterministic_cited_versioned_and_measured(self):
        facts = campus_facts()
        tools._bind_campus_identity(facts)
        value = state(collected_info=facts, confirmed_plan={"bullet_style": "plain"})
        data = graph._serialize_to_resume_data({**value, "messages": []})
        data["campus"][0]["bullets"] = []
        notice = "方案中保留的「校内资料社」未能形成通过事实校验的正文，请在核对页检查这段经历。"
        data["verification_notes"] = [notice, "保留其它核对项"]
        value["resume_data"] = deepcopy(data)
        value["resume_meta"] = {"version_id": "previous"}
        failed = {"resume_data": data, "resume_meta": {}, "changed": False,
            "match_plan": {"bullet_style": "plain", "experience_plan": [{"item_id": "named", "treatment": "lead", "target_bullets": 2}]},
            "writer_diagnostic": {"undelivered_items": ["named"]}, "change_summary": [notice]}
        with patch("app.agents.tailor_pipeline.run_tailor_pipeline", AsyncMock(return_value=failed)), \
                patch("app.services.fact_guard.verify_semantics", side_effect=AssertionError("fallback must not call model")):
            outcome = await tools._write(value, tools.ToolContext(llm=object()), "")
        result = outcome.update
        item = result["resume_data"]["campus"][0]
        body = " ".join(item["bullets"])
        self.assertIn("36条", body)
        self.assertIn("3张", body)
        self.assertNotIn("活动增长", body)
        self.assertEqual(result["resume_data"]["verification_notes"], ["保留其它核对项"])
        self.assertEqual(result["resume_versions"][0]["version_id"], "previous")
        self.assertEqual(result["page_check"]["data_hash"], measured(result["resume_data"], {"page_limit": 1, "template_id": "t001-jianyue"})["data_hash"])
        for text, record in zip(item["bullets"], result["resume_meta"]["bullets"]["named"]):
            self.assertEqual(record["text_hash"], text_hash(text))
            self.assertTrue(record["fact_ids"])
            self.assertTrue(set(record["fact_ids"]) <= {f["id"] for f in facts["campus"][0]["facts"]})
        self.assertEqual(outcome.result["writer_diagnostic"]["deterministic_body_fallbacks"], ["named"])

    def test_fallback_respects_backup_zero_hidden_scope_and_deleted_facts(self):
        for variant in ("backup", "zero", "hidden", "item_scope", "bullet_scope", "deleted"):
            facts = campus_facts()
            tools._bind_campus_identity(facts)
            value = state(collected_info=facts)
            data = graph._serialize_to_resume_data({**value, "messages": []})
            data["campus"][0]["bullets"] = []
            selection = {"item_id": "named", "treatment": "lead", "target_bullets": 2}
            if variant == "backup":
                selection["treatment"] = "backup"
            if variant == "zero":
                selection["target_bullets"] = 0
            if variant == "hidden":
                value["resume_data"] = deepcopy(data)
                value["resume_data"]["campus"][0]["hidden"] = True
            if variant == "deleted":
                for fact in facts["campus"][0]["facts"]:
                    fact["status"] = "deleted"
            update = {"resume_data": data, "match_plan": {"experience_plan": [selection]}}
            tools._restore_unwritten_items(value, update, "item" if variant == "item_scope" else
                                          "bullet" if variant == "bullet_scope" else "whole", ("other",))
            self.assertFalse(update["resume_data"]["campus"][0]["bullets"], variant)

    async def test_draft_and_polish_keep_conversation_objective_without_sending_contacts(self):
        value = state_with_draft()
        value["resume_data"]["basic_info"]["objective"] = ""
        value["collected_info"]["basic_info"]["objective"] = ""
        value["jd_info"] = {"role_direction": "后端开发实习（实习，目标：数据库、缓存、服务接口，参与协作排查问题）",
                            "role_profile": {"role_family": "backend"}}
        value["messages"] = [HumanMessage(content="生成简历")]
        model = Writer()
        first = await tools.write_draft(value, {}, tools.ToolContext(llm=model))
        self.assertEqual(first.update["resume_data"]["basic_info"]["objective"], "后端开发实习")
        edited = await tools.edit_resume({**value, **first.update}, {"instruction": "润色第一段项目"}, tools.ToolContext(llm=model))
        self.assertEqual(edited.update["resume_data"]["basic_info"], first.update["resume_data"]["basic_info"])
        self.assertNotIn(PHONE, str(model.requests))
        self.assertNotIn(EMAIL, str(model.requests))

    def test_objective_projection_respects_custom_heading_and_updated_direction(self):
        for saved, fact, direction, expected in (("", "", "前端开发", "前端开发"),
            ("", "", "后端开发校招（校招，目标：数据库、缓存、服务接口，参与协作排查问题）", "后端开发校招"),
            ("后端开发", "后端开发", "前端开发", "前端开发"),
            ("全栈开发工程师", "后端开发", "前端开发", "全栈开发工程师")):
            data = {"basic_info": {"objective": ""}}
            tools._project_identity(data, {"collected_info": {"basic_info": {"objective": fact}},
                "resume_data": {"basic_info": {"objective": saved}}, "jd_info": {"role_direction": direction}})
            self.assertEqual(data["basic_info"]["objective"], expected)


if __name__ == "__main__":
    unittest.main()
