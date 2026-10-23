"""Answer handoff, shared interview budget and receipts; all providers are stubs."""
import asyncio
from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests")]
from app.agents import orchestrator as loop, orchestrator_tools as tools, resume_graph as graph  # noqa: E402
from app.agents.loop_followup import question_rounds, questions_allowed  # noqa: E402
from app.config import Settings  # noqa: E402
from app.services.answer_facts import apply_answers  # noqa: E402
from app.services.ask_user import close_answers, pending_card, question_dimension  # noqa: E402
from app.services.intake import MAX_FOLLOWUP_ROUNDS  # noqa: E402
from app.services.resume_facts import normalize_fact_store  # noqa: E402
from app.services.resume_versions import text_hash  # noqa: E402
from test_orchestrator import Model, call, registry  # noqa: E402
from test_orchestrator_tools import PHONE, EMAIL, measured, state_with_draft  # noqa: E402
from test_orchestrator_p2h import draft_outcome, followup_state  # noqa: E402


def question(identifier, prompt):
    return {"id": identifier, "prompt": prompt, "kind": "text"}


def answer_state(questions=None, values=None):
    value = state_with_draft()
    value["collected_info"]["projects"][0]["name"] = "项目（待补名称）"
    value["resume_data"]["projects"][0]["name"] = "项目（待补名称）"
    questions = questions or [question("project_name", "这个项目叫什么名字？"),
        question("start_date", "项目开始时间是哪年哪月？"), question("end_date", "项目结束时间？"),
        question("role", "在项目中是什么角色？")]
    values = values or ["文档比对工具", "2025-04", "至今", "独立开发者"]
    card = {"kind": "ask_user", "turn_id": "card-original", "subject": "项目（待补名称）", "questions": questions}
    items = [{"id": q["id"], "value": v} if isinstance(v, str) else {"id": q["id"], **v}
             for q, v in zip(questions, values)]
    value["messages"] = [HumanMessage(content="项目原始材料", id="first"),
        AIMessage(content="请填写补充卡。", additional_kwargs={"ask_user": card}),
        HumanMessage(content="已提交问题卡", id="answer-turn", additional_kwargs={
            "answers": {"turn_id": card["turn_id"], "items": items}, "answer_card": card})]
    return value


class P2iTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = Settings(_env_file=None, AGENT_MODE="loop")
        self.enterContext(patch("app.config.get_settings", return_value=self.settings))
        self.enterContext(patch("app.services.resume_capacity.measure_rendered_pages", side_effect=measured))

    async def test_answers_persist_before_model_and_headings_survive_failed_final(self):
        value = answer_state()
        saved = []
        saver = AsyncMock(side_effect=lambda state: saved.append(deepcopy(state)))
        token = graph._intake_saver.set(saver)
        class FailingModel:
            async def complete(inner, messages, **kwargs):
                self.assertTrue(saved)
                self.assertEqual(saved[-1]["collected_info"]["projects"][0]["name"], "文档比对工具")
                self.assertEqual(len(saved[-1]["closed_questions"]), 4)
                self.assertNotIn(PHONE, str(messages))
                self.assertNotIn(EMAIL, str(messages))
                raise RuntimeError("offline failure")
        events = []
        try:
            result = await loop.run_orchestrator(value, FailingModel(), registry=tools.TOOLS, emit=events.append)
        finally:
            graph._intake_saver.reset(token)
        item = result["resume_data"]["projects"][0]
        for field, expected in (("name", "文档比对工具"), ("start_date", "2025.04"), ("end_date", "至今"), ("role", "独立开发者")):
            self.assertEqual(item[field], expected)
        self.assertNotEqual(result["version_id"], "v-original")
        self.assertEqual(result["resume_meta"]["bullets"], value["resume_meta"]["bullets"])
        self.assertEqual(result["messages"][-1].content, "".join(e["content"] for e in events if e["type"] == loop.PUBLIC_REPLY_EVENT))
        self.assertIn("已记下：经历名称", result["messages"][-1].content)
        self.assertIn("稿子已更新", result["messages"][-1].content)

    def test_answer_projection_is_idempotent_bound_to_subject_and_shared_by_default(self):
        value = answer_state()
        message = value["messages"][-1]
        original = deepcopy(value["collected_info"])
        applied = apply_answers(original, message, project_fields=True)
        self.assertEqual(applied, apply_answers(applied, message, project_fields=True))
        self.assertEqual(original, value["collected_info"])
        self.assertEqual(apply_answers(original, message)["projects"][0]["name"], "文档比对工具")
        for fact in applied["projects"][0]["facts"][-4:]:
            self.assertEqual(fact["turn_id"], message.id)
            self.assertEqual(fact["sources"][0]["question_id"], fact["question_id"])
        named = deepcopy(original)
        named["projects"][0]["name"] = "已有真实名称"
        message.additional_kwargs["answer_card"]["subject"] = "p1"
        self.assertEqual(apply_answers(named, message, project_fields=True)["projects"][0]["name"], "已有真实名称")
        message.additional_kwargs["answer_card"]["subject"] = "无法归属"
        self.assertEqual(apply_answers(original, message, project_fields=True), original)
        message.additional_kwargs["answers"]["turn_id"] = "stale"
        self.assertEqual(apply_answers(original, message, project_fields=True), original)

    def test_unknown_skipped_invalid_options_and_invalid_dates_never_become_fields(self):
        for supplied in ({"unknown": True, "value": "误填"}, {"skipped": True, "value": "误填"}, "不知道", ""):
            value = answer_state([question("project_name", "项目名称？")], [supplied])
            result = apply_answers(value["collected_info"], value["messages"][-1], project_fields=True)
            self.assertEqual(result, value["collected_info"])
        for date in ("2025-18", "明年随便", "至今"):
            value = answer_state([question("start_date", "项目开始时间？")], [date])
            result = apply_answers(value["collected_info"], value["messages"][-1], project_fields=True)
            self.assertNotIn("start_date", result["projects"][0])
        value = answer_state([{"id": "project_name", "prompt": "项目名称？", "kind": "single",
                               "options": ["甲", "乙"], "allow_other": False}], ["丙"])
        self.assertEqual(apply_answers(value["collected_info"], value["messages"][-1], project_fields=True), value["collected_info"])

    async def test_answers_never_reenter_extraction_and_empty_reply_gets_receipt(self):
        value = answer_state([question("decision", "关键决策是什么？")], ["根据用户反馈简化操作"])
        events = []
        with patch("app.agents.fact_extractor.extract_facts_patch", new_callable=AsyncMock) as extractor:
            result = await loop.run_orchestrator(value,
                Model([call("record_facts", source_id="current"), {"content": ""}]), registry=tools.TOOLS, emit=events.append)
        extractor.assert_not_awaited()
        self.assertIn("关键决策", result["messages"][-1].content)
        self.assertIn("稿子未更新", result["messages"][-1].content)
        self.assertEqual(len([f for f in result["collected_info"]["projects"][0]["facts"] if f.get("turn_id") == "answer-turn"]), 1)
        self.assertTrue(result["messages"][-1].content.strip())

    async def test_all_unknown_closes_only_answered_dimension_and_continues(self):
        value = answer_state([question("evaluation", "怎么评测？")], [{"unknown": True}])
        args = {"subject": "项目（待补名称）", "questions": [question("tech_stack", "用什么技术？")]}
        result = await loop.run_orchestrator(value, Model([call("ask_user", card=args),
            {"content": "请补充技术栈？", "deltas": list("请补充技术栈？")}]), registry=tools.TOOLS)
        self.assertFalse(result["session_constraints"].get("questions_finished", False))
        self.assertEqual(result["closed_questions"][0]["reason"], "unknown")
        self.assertTrue(pending_card({**value, **result}))
        self.assertNotIn("技术栈", result["messages"][-1].content)
        self.assertIn("稿子未更新", result["messages"][-1].content)
        self.assertTrue(tools._draft_followup({**value, **result}, tools.ToolContext()))
        self.assertTrue(all(q["id"] != "evaluation" for q in pending_card({**value, **result})["questions"]))

    async def test_literal_unknown_option_and_skipped_answer_continue_without_new_facts(self):
        for answer in ("不知道 / 没有", {"skipped": True}):
            value = answer_state([question("evaluation", "怎么评测？")], [answer])
            result = await loop.run_orchestrator(value, Model([{"content": ""}]), registry=tools.TOOLS)
            self.assertFalse(result["session_constraints"].get("questions_finished", False))
            self.assertEqual(result["collected_info"], value["collected_info"])
            self.assertEqual(result["closed_questions"][0]["dimension"], "evaluation")

    async def test_card_and_free_questions_share_cap_and_last_card_can_still_be_answered(self):
        value = followup_state()
        value["messages"] = []
        for index in range(MAX_FOLLOWUP_ROUNDS - 1):
            value["messages"].extend([HumanMessage(content="材料", id=f"u{index}"),
                AIMessage(content="还有什么具体做法？" if index % 2 else "卡片已展示。",
                    additional_kwargs={} if index % 2 else {"ask_user": {"turn_id": f"q{index}"}})])
        value["messages"].append(HumanMessage(content="补充", id="last"))
        self.assertEqual(question_rounds(value), MAX_FOLLOWUP_ROUNDS - 1)
        args = {"card": {"subject": "资料核对项目", "questions": [question("evaluation", "怎么评测？")]}}
        outcome = await tools.ask_user(value, args, tools.ToolContext(turn_id="last-card"))
        value["messages"] += outcome.update["messages"]
        # The checkpoint may contain the same card again on the final reply.
        value["messages"].append(AIMessage(content="卡片已展示。",
            additional_kwargs={"ask_user": outcome.update["messages"][0].additional_kwargs["ask_user"]}))
        self.assertEqual(question_rounds(value), MAX_FOLLOWUP_ROUNDS)
        self.assertFalse(questions_allowed(value))
        card = pending_card(value)
        self.assertEqual(card["turn_id"], "last-card")
        answers = {"turn_id": card["turn_id"], "items": [{"id": "evaluation", "value": "逐项人工核对"}]}
        self.assertEqual(close_answers(value, "逐项人工核对", answers)[-1]["reason"], "answered")
        rejected = await tools.ask_user(value, args, tools.ToolContext())
        self.assertEqual(rejected.result["code"], "question_budget_exhausted")
        result = await loop.run_orchestrator(value, Model([{"content": "还用了什么工具？"}]), registry=tools.TOOLS)
        self.assertNotIn("工具", result["messages"][-1].content)
        self.assertTrue(result["messages"][-1].content.strip())

    async def test_contacts_once_even_for_repeated_model_text_export_and_split_deltas(self):
        value = followup_state()
        value["collected_info"]["basic_info"] = {}
        value["resume_data"]["basic_info"] = {}
        specs = registry()
        specs["write_draft"] = tools.TOOLS["write_draft"]
        specs["ask_user"] = tools.TOOLS["ask_user"]
        prose = "稿子已生成。头部电话、邮箱还空着。想补的话一次发给我。请补充手机、邮箱。"
        with patch.object(tools, "_write", AsyncMock(return_value=draft_outcome(value))):
            events = []
            result = await loop.run_orchestrator(value, Model([call("write_draft"),
                {"content": prose, "deltas": list(prose)}]), registry=specs, emit=events.append)
        text = result["messages"][-1].content
        self.assertEqual(text.count("手机"), 1)
        self.assertEqual(text.count("邮箱"), 1)
        self.assertEqual(text, "".join(e["content"] for e in events if e["type"] == loop.PUBLIC_REPLY_EVENT))
        value.update({k: v for k, v in result.items() if k != "messages"})
        value["messages"] += result["messages"] + [HumanMessage(content="导出PDF", id="export")]
        for prose in ("请提供手机和邮箱。稿件已保留。", "邮箱已记下，但还缺手机。稿件已保留。"):
            next_turn = await loop.run_orchestrator(value, Model([{"content": prose}]), registry=specs)
            self.assertEqual(next_turn["messages"][-1].content, "稿件已保留。")

    def test_loop_dates_share_dimension_and_off_contract_is_unchanged(self):
        self.assertEqual(question_dimension("x", "项目开始时间？"), "dates")
        self.assertEqual(question_dimension("x", "项目结束时间？"), "dates")
        self.settings.AGENT_MODE = "off"
        self.assertEqual(question_dimension("x", "项目开始时间？"), "dates")
        self.assertEqual(question_dimension("x", "项目结束时间？"), "dates")


class P2iGraphTests(unittest.IsolatedAsyncioTestCase):
    # Reuse the isolated in-memory database setup, not its test cases.
    async def asyncSetUp(self):
        from test_orchestrator import OrchestratorGraphTests
        await OrchestratorGraphTests.asyncSetUp(self)
        self.enterContext(patch("app.services.resume_capacity.measure_rendered_pages", side_effect=measured))

    async def asyncTearDown(self):
        self.engine.dispose()

    async def test_answer_stream_persists_fields_closures_and_nonempty_receipt(self):
        value = answer_state()
        message = value["messages"].pop()
        events = []
        async def node(value, llm):
            from langgraph.config import get_stream_writer
            return await loop.run_orchestrator(value, Model([{"content": ""}]), registry=tools.TOOLS,
                                               emit=get_stream_writer())
        with patch.object(loop, "orchestrator_node", node):
            compiled = graph.build_graph(SimpleNamespace(model_name="offline"), MemorySaver())
        config = {"configurable": {"thread_id": self.session}}
        await compiled.aupdate_state(config, value)
        with patch.object(graph, "get_graph", return_value=compiled):
            events = [e async for e in graph.stream_agent([{"content": message.content}], self.session, object(),
                answers=message.additional_kwargs["answers"])]
        reply = "".join(e for e in events if isinstance(e, str))
        self.assertTrue(reply.strip())
        self.assertIn("已记下：经历名称", reply)
        stored = self.store.load_resume_session(self.session)
        self.assertEqual(stored["collected_info"]["projects"][0]["name"], "文档比对工具")
        self.assertEqual(stored["resume_data"]["projects"][0]["start_date"], "2025.04")
        snapshot = (await compiled.aget_state(config)).values
        self.assertEqual(len(snapshot["closed_questions"]), 3)
        self.assertEqual(snapshot["messages"][-1].content, reply)


class P2iEvaluationTests(unittest.TestCase):
    def test_import_receipts_require_each_name_under_a_completed_action(self):
        module = import_module("evaluation.persona-ux.returning")
        a, b = module.PROJECTS
        data = {"projects": [{"name": a}, {"name": b}]}
        for reply in (f"直接采用了两段：{a}、{b}。", f"导入的：从档案选了两段，{a}、{b}。",
                      f"**从档案里导入的，是三段：**\n- **{a}**：已有经历。\n- **{b}**：已有经历。",
                      f"已采用{a}。已导入{b}。"):
            self.assertTrue(module.import_receipt({"reply": reply, "resume_data": data}), reply)
        for reply in ("直接采用了两段。", f"直接采用了{a}。档案里还有{b}。",
                      f"已采用{a}，但没有导入{b}。", f"将采用{a}、{b}。", f"是否采用{a}、{b}？",
                      f"未采用{a}、{b}。", f"已采用{a}、{b}，但导入失败。"):
            self.assertFalse(module.import_receipt({"reply": reply, "resume_data": data}), reply)
        self.assertFalse(module.import_receipt({"reply": f"已采用{a}、{b}。", "resume_data": {}}))

    def test_phone_as_camera_is_not_contact_request_but_mixed_request_still_is(self):
        module = import_module("evaluation.persona-ux.loop_checks")
        self.assertFalse(module.contact_request({"reply": "写了手机拍摄素材、文案由店长提供。联系方式按你说的留空。"}))
        self.assertTrue(module.contact_request({"reply": "手机拍摄素材已记下，请提供手机和邮箱。"}))
        self.assertTrue(module.contact_request({"reply": "邮箱已记下，但还缺手机。"}))


class P2iOfflineReplayTests(unittest.TestCase):
    def test_aipm_and_real_runner_through_graph_answers_and_writer_stubs(self):
        from test_batch14c5_labeled import WrongModel, collected as labeled_facts
        for name in ("aipm", "aipm_real"):
            with self.subTest(persona=name):
                module = import_module("evaluation.persona-ux." + name)
                settings = Settings(_env_file=None, AGENT_MODE="loop")
                requests, calls = [], []
                model = WrongModel()
                async def record(value, args, ctx):
                    facts = labeled_facts(name)
                    item = facts["projects"][0]
                    item.update(name=module.INTAKE["items"][0]["name"] if name == "aipm" else "项目（待补名称）",
                                start_date="", end_date="", role=module.INTAKE["items"][0]["role"] if name == "aipm" else "")
                    item["facts"] = [f for f in item["facts"] if f.get("field") not in {"name", "start_date", "end_date", "role"}]
                    facts["basic_info"] = {"phone": PHONE, "email": EMAIL}
                    return tools.ToolOutcome({"status": "ok"}, {"collected_info": normalize_fact_store(facts),
                        "jd_info": {"role_profile": {"role_family": "ai_pm"}}})
                specs = {**tools.TOOLS, "record_facts": SimpleNamespace(args_model=tools.TOOLS["record_facts"].args_model,
                    description="offline extraction", handler=record)}
                async def node(value, llm):
                    human = value["messages"][-1]
                    answers = human.additional_kwargs.get("answers")
                    facts_ready = bool(value.get("collected_info", {}).get("projects"))
                    if name == "aipm_real" and not answers and len([m for m in value["messages"] if isinstance(m, HumanMessage)]) < 4:
                        script = [{"content": "已记下当前方向。"}]
                    elif not facts_ready:
                        script = [call("record_facts", source_id="current"), call("write_draft"), {"content": "初稿已生成。"}]
                    else:
                        script = [{"content": "已按本轮信息处理。"}]
                    scripted = Model(script)
                    def candidates(current):
                        item = current["resume_data"]["projects"][0]
                        return [{"question_id": "evaluation", "q": "这段经历怎么评测？",
                                 "improves": {"item_id": item["item_id"]}}]
                    with patch("app.agents.interviewer.question_candidates", side_effect=candidates):
                        result = await loop.run_orchestrator(value, scripted, registry=specs, llm=model)
                    requests.extend(scripted.requests)
                    calls.append(graph.route_by_stage(value))
                    return result
                class Client:
                    def __init__(self, compiled):
                        self.compiled, self.config = compiled, {"configurable": {"thread_id": name}}
                    def turn(self, action, text, **payload):
                        async def run():
                            old = (await self.compiled.aget_state(self.config)).values
                            kwargs = deepcopy(payload)
                            if kwargs.get("answers"):
                                kwargs["answer_card"] = pending_card(old)
                            incoming = HumanMessage(content=text, id=action, additional_kwargs=kwargs)
                            result = await self.compiled.ainvoke({"messages": [incoming]}, self.config)
                            reply = result["messages"][-1].content
                            return {"action": action, "input": text, **payload, "reply": reply, "status": "ok",
                                "sse_done": True, "stage": result.get("stage"), "revision": result.get("version_id"),
                                "resume_data": result.get("resume_data") or {}, "workspace": {"guidance": pending_card(result),
                                "tailor": {"resume_meta": result.get("resume_meta") or {}}}}
                        return asyncio.run(run())
                with (patch("app.config.get_settings", return_value=settings), patch.object(loop, "orchestrator_node", node),
                      patch("app.services.resume_capacity.measure_rendered_pages", side_effect=measured),
                      patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=measured),
                      patch.object(graph, "collecting_node", AsyncMock(side_effect=AssertionError("legacy collecting called")))):
                    compiled = graph.build_graph(SimpleNamespace(model_name="offline"), MemorySaver())
                    turns = list(module.replay(Client(compiled), agent_mode="loop"))
                self.assertTrue(all(t["reply"].strip() for t in turns))
                self.assertTrue(all(route == "orchestrator" for route in calls))
                self.assertFalse(any(t.get("depth_limit_exceeded") for t in turns))
                first = 0 if name == "aipm" else 3
                card = turns[first]["workspace"]["guidance"]
                self.assertTrue(turns[first]["resume_data"]["projects"][0]["polished_bullets"])
                self.assertEqual({q["id"] for q in card["questions"]},
                                 {"dates"} if name == "aipm" else {"name", "dates", "role"})
                self.assertTrue(module.delivered(turns[first + 1]))
                # A labeled problem already present in the draft is not asked again.
                from app.services.ask_user import draft_dimensions
                draft = turns[first + 1]['resume_data']
                known = draft_dimensions({'resume_data': draft}, draft['projects'][0]['item_id'])
                self.assertFalse({q['id'] for q in turns[first + 1]['workspace']['guidance']['questions']} & known)
                self.assertTrue(module.delivered(turns[-1]), turns[-1])
                item = turns[-1]["resume_data"]["projects"][0]
                expected = module.INTAKE["items"][0]
                for field, key in (("name", "name"), ("start_date", "start"), ("end_date", "end"), ("role", "role")):
                    from app.services.resume_preflight import normalize_date
                    self.assertEqual(normalize_date(item[field]) if field.endswith('_date') else item[field],
                                     normalize_date(expected[key]) if field.endswith('_date') else expected[key])
                self.assertTrue(item["positioning"])
                meta = turns[-1]["workspace"]["tailor"]["resume_meta"]
                for bullet, evidence in zip(item["polished_bullets"], meta["bullets"][item["item_id"]]):
                    self.assertEqual(evidence["text_hash"], text_hash(bullet))
                    self.assertTrue(evidence["fact_ids"])
                for captured in (requests, model.calls):
                    self.assertNotIn(PHONE, json.dumps(captured, ensure_ascii=False))
                    self.assertNotIn(EMAIL, json.dumps(captured, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
