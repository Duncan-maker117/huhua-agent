"""Heading answers continue the same bounded interview; offline providers only."""
import asyncio
from copy import deepcopy
from importlib import import_module
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from test_orchestrator import Model, call
from test_orchestrator_p2h import followup_state
from test_orchestrator_p2i import answer_state, question
from test_orchestrator_tools import PHONE, EMAIL, measured
from test_batch14c5_labeled import WrongModel
from app.agents import orchestrator as loop, orchestrator_tools as tools, resume_graph as graph
from app.agents.loop_followup import question_rounds
from app.config import Settings
from app.services.answer_facts import apply_answers
from app.services.ask_user import is_closed, pending_card, question_dimension
from app.services.intake import MAX_FOLLOWUP_ROUNDS, deepen_dimensions
from app.services.resume_facts import new_fact, normalize_fact_store
from app.services.resume_versions import text_hash


def submit(state, card, items, turn="answer"):
    state = deepcopy(state)
    state["messages"] = [*state.get("messages", []),
        AIMessage(content="补充卡。", additional_kwargs={"ask_user": card}),
        HumanMessage(content="已提交补充信息", id=turn, additional_kwargs={
            "answers": {"turn_id": card["turn_id"], "items": items}, "answer_card": card})]
    return state


class P2kTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch("app.config.get_settings", return_value=Settings(_env_file=None, AGENT_MODE="loop")))
        self.enterContext(patch("app.services.resume_capacity.measure_rendered_pages", side_effect=measured))

    def test_dates_project_both_fields_with_original_answer_and_retry_is_idempotent(self):
        for text in ("2026-08 / 至今", "2025年3月—2025年8月", "2025.03 至 2025.08", "2025-03-2025-08"):
            with self.subTest(text=text):
                value = answer_state([question("dates", "这段经历的起止时间？")], [text])
                message = value["messages"][-1]
                result = apply_answers(value["collected_info"], message, project_fields=True)
                item = result["projects"][0]
                self.assertTrue(item["start_date"])
                self.assertTrue(item["end_date"])
                self.assertEqual(result, apply_answers(result, message, project_fields=True))
                facts = [f for f in item["facts"] if f.get("turn_id") == message.id]
                self.assertEqual({f["field"] for f in facts}, {"start_date", "end_date"})
                for fact in facts:
                    self.assertEqual(fact["dimension"], "dates")
                    self.assertEqual(fact["answer_value"], text)
                    self.assertEqual(fact["sources"][0]["answer_value"], text)
        for text in ("不知道", "2025-18 / 至今", "2025-03", "至今", "春天到夏天"):
            value = answer_state([question("dates", "这段经历的起止时间？")], [text])
            item = apply_answers(value["collected_info"], value["messages"][-1], project_fields=True)["projects"][0]
            self.assertFalse(item.get("start_date"))
            self.assertFalse(item.get("end_date"))
        value = answer_state([question("dates", "这段经历的结束时间？")], ["至今"])
        value["collected_info"]["projects"][0]["start_date"] = "2025-03"
        item = apply_answers(value["collected_info"], value["messages"][-1], project_fields=True)["projects"][0]
        self.assertEqual((item["start_date"], item["end_date"]), ("2025-03", "至今"))

    async def test_heading_and_model_cards_never_split_same_dimension(self):
        value = followup_state()
        questions = [question("start_date", "开始时间？"), question("end_date", "结束时间？"),
                     question("name", "经历名称？"), question("project_name", "项目叫什么？"),
                     question("role", "你的角色？")]
        # AskUser allows four questions, so use independent duplicate pairs.
        for rows in (questions[:4], [*questions[2:], question("my_role", "担任什么角色？")]):
            outcome = await tools.ask_user(value, {"card": {"subject": "资料核对项目", "questions": rows}}, tools.ToolContext())
            dims = [question_dimension(q["id"], q["prompt"]) for q in outcome.result["card"]["questions"]]
            self.assertEqual(len(dims), len(set(dims)))
        value["closed_questions"] = [{"subject": "p1", "dimension": "start_date", "reason": "skipped"}]
        self.assertTrue(is_closed(value, "p1", "dates", "起止时间？"))

    async def test_heading_answer_continues_even_when_final_model_fails_without_writer(self):
        value = answer_state([question("dates", "这段经历的起止时间？")], ["2026-08 / 至今"])
        value["jd_info"] = {"role_profile": {"role_family": "ai_pm"}}
        # A real heading is already present, so no other identity question remains.
        for store in (value["collected_info"], value["resume_data"]):
            store["projects"][0].update(name="材料核对", role="开发者")
        value["messages"][-1].additional_kwargs["answer_card"]["subject"] = "p1"
        value["messages"][-2].additional_kwargs["ask_user"]["subject"] = "p1"
        events = []
        with patch.object(tools, "_write", AsyncMock()) as writer:
            result = await loop.run_orchestrator(value, Model([RuntimeError("offline")]), registry=tools.TOOLS, emit=events.append)
        writer.assert_not_awaited()
        self.assertEqual(result["resume_data"]["projects"][0]["start_date"], "2026-08")
        self.assertEqual(pending_card({**value, **result})["questions"][0]["id"], "problem")
        self.assertEqual(len([e for e in events if e["type"] == "guidance"]), 1)
        self.assertTrue(result["messages"][-1].content)

    async def test_heading_answer_already_closed_before_node_still_counts_as_answering_card(self):
        # 真实回放：答案的关闭记录在进入编排前已写入，旧卡重新校验会变空卡；仍须识别为答卡并续出深挖卡。
        from app.services.ask_user import close_answers
        value = answer_state([question("dates", "这段经历的起止时间？")], ["2026-08 / 至今"])
        value["jd_info"] = {"role_profile": {"role_family": "ai_pm"}}
        for store in (value["collected_info"], value["resume_data"]):
            store["projects"][0].update(name="材料核对", role="开发者")
        value["messages"][-1].additional_kwargs["answer_card"]["subject"] = "p1"
        value["messages"][-2].additional_kwargs["ask_user"]["subject"] = "p1"
        before = {**value, "messages": value["messages"][:-1]}
        answer = value["messages"][-1]
        value["closed_questions"] = close_answers(before, answer.content, answer.additional_kwargs["answers"])
        self.assertTrue(is_closed(value, "p1", "dates", "这段经历的起止时间？"))
        events = []
        with patch.object(tools, "_write", AsyncMock()) as writer:
            result = await loop.run_orchestrator(value, Model([RuntimeError("offline")]), registry=tools.TOOLS, emit=events.append)
        writer.assert_not_awaited()
        self.assertEqual(pending_card({**value, **result})["questions"][0]["id"], "problem")
        self.assertEqual(len([e for e in events if e["type"] == "guidance"]), 1)

    async def test_unknown_and_skip_close_one_dimension_until_all_dimensions_close(self):
        value = followup_state()
        value["jd_info"] = {"role_profile": {"role_family": "ai_pm"}}
        value["resume_data"]["projects"] = value["resume_data"]["projects"][:1]
        dimensions = deepen_dimensions("ai_pm")
        value["closed_questions"] = [{"subject": "p1", "id": d, "dimension": d, "reason": "unknown"}
                                     for d in dimensions if d not in {"problem", "decision"}]
        for dimension, answer in (("problem", {"unknown": True}), ("decision", {"skipped": True})):
            card = tools._draft_followup(value, tools.ToolContext())
            self.assertEqual(card["questions"][0]["id"], dimension)
            card["turn_id"] = dimension
            value = submit(value, card, [{"id": dimension, **answer}], dimension)
            events = []
            result = await loop.run_orchestrator(value, Model([{"content": "还有什么具体做法？"}]), registry=tools.TOOLS, emit=events.append)
            value.update(result)
            self.assertTrue(is_closed(value, "p1", dimension))
            self.assertNotIn("还有什么", result["messages"][-1].content)
            self.assertEqual(len([e for e in events if e["type"] == "guidance"]), int(dimension == "problem"))
        self.assertFalse(pending_card(value))
        self.assertFalse(tools._draft_followup(value, tools.ToolContext()))

    async def test_new_answer_rewrites_only_its_item_even_at_budget_end(self):
        value = followup_state()
        value["messages"] = []
        for i in range(MAX_FOLLOWUP_ROUNDS - 1):
            value["messages"] += [HumanMessage(content="材料"), AIMessage(content="还有什么做法？")]
        card = {"turn_id": "last", "subject": "p1", "questions": [question("decision", "关键决策是什么？")]}
        value = submit(value, card, [{"id": "decision", "value": "先核对来源，再生成汇总"}])
        # submit starts a new user round before this last question card.
        value["messages"].insert(-2, HumanMessage(content="继续"))
        self.assertEqual(question_rounds(value), MAX_FOLLOWUP_ROUNDS)
        async def rewrite(state, ctx, instruction, **kwargs):
            self.assertEqual(kwargs["scope"], "item")
            self.assertEqual(kwargs["targets"], ["p1"])
            self.assertTrue(kwargs["plan_draft"])
            self.assertEqual(kwargs["base"]["projects"][1], value["resume_data"]["projects"][1])
            self.assertTrue(any(f.get("answer_value") == "先核对来源，再生成汇总" for f in state["collected_info"]["projects"][0]["facts"]))
            return tools.ToolOutcome({"status": "unchanged"})
        with patch.object(tools, "_write", AsyncMock(side_effect=rewrite)) as writer:
            result = await loop.run_orchestrator(value, Model([{"content": "已处理。"}]), registry=tools.TOOLS)
        writer.assert_awaited_once()
        self.assertFalse(pending_card({**value, **result}))
        self.assertEqual(result["collected_info"]["projects"][1], value["collected_info"]["projects"][1])

    async def test_writer_failure_preserves_answer_and_draft_but_still_attaches_one_card(self):
        value = answer_state([question("decision", "关键决策是什么？")], ["先核对来源，再生成汇总"])
        events = []
        with patch.object(tools, "_write", AsyncMock(side_effect=RuntimeError("offline"))):
            result = await loop.run_orchestrator(value, Model([{"content": "已处理。"}]), registry=tools.TOOLS, emit=events.append)
        self.assertEqual(value["resume_data"], result.get("resume_data", value["resume_data"]))
        self.assertEqual(result["collected_info"]["projects"][0]["facts"][-1]["answer_value"], "先核对来源，再生成汇总")
        self.assertEqual(len([e for e in events if e["type"] == "guidance"]), 1)

    async def test_stale_card_and_explicit_stop_do_not_add_followup(self):
        for stale in (True, False):
            value = answer_state([question("evaluation", "怎么评测？")], [{"unknown": True}])
            if stale:
                value["messages"][-1].additional_kwargs["answers"]["turn_id"] = "stale"
            else:
                value["collected_info"]["no_more_questions"] = True
            with patch.object(tools, "_write", AsyncMock()) as writer:
                result = await loop.run_orchestrator(value, Model([{"content": "已处理。"}]), registry=tools.TOOLS)
            writer.assert_not_awaited()
            self.assertFalse(pending_card({**value, **result}))


class EvidenceWriter(WrongModel):
    """Generate solely from the current evidence; no persona answers preloaded."""
    def with_structured_output(self, schema):
        if schema.__name__ not in {"WriterDraft", "FactSlots", "StructurePlan"}:
            return super().with_structured_output(schema)
        async def invoke(messages):
            from app.services.labeled_writer import SLOTS, fallback_row, rule_slot
            data = json.loads(messages[-1].content)
            self.calls.append((schema.__name__, data))
            if schema.__name__ == "FactSlots":
                return {"assignments": [{"fact_id": f["id"], "slot": rule_slot(f)} for f in data["facts"]]}
            if schema.__name__ == "StructurePlan":
                return {"recommended": {"bullet_style": "labeled", "experience_plan": [
                    {"item_id": p["item_id"], "treatment": "lead", "target_bullets": 4} for p in data["evidence"]["projects"]]}}
            items = []
            for p in data["evidence"]["projects"]:
                facts = {f["id"]: f for f in p["facts"]}
                rows = []
                for slot in SLOTS:
                    ids = [fid for fid, fact in facts.items() if rule_slot(fact) == slot]
                    if ids:
                        row = fallback_row(slot, ids, p["item_id"], facts, p["name"])
                        text = row["text"].replace("自己的", "自身").replace("需要通过", "需借助")
                        rows.append({"text": slot + "：" + text, "fact_ids": row["fact_ids"]})
                items.append({"item_id": p["item_id"], "section": "projects", "bullets": rows})
            return {"items": items}
        return SimpleNamespace(ainvoke=invoke)


class P2kReplayTests(unittest.TestCase):
    def test_sparse_aipm_runner_reaches_labeled_body_from_card_answers(self):
        module = import_module("evaluation.persona-ux.aipm")
        model, requests, events_by_turn = EvidenceWriter(), [], []
        async def record(value, args, ctx):
            item = {"item_id": "p1", "name": module.INTAKE["items"][0]["name"], "role": "独立开发者", "facts": []}
            for text, kind in (("从需求到开发都是我一个人做的", "role"), ("现在已经上线了", "status_limit"),
                               ("能通过对话帮学生挖经历写简历", "action")):
                self.assertIn(text, module.FIRST)
                item["facts"].append(new_fact(text, kind=kind, quote=text, turn_id="initial"))
            facts = normalize_fact_store({"basic_info": {"phone": PHONE, "email": EMAIL}, "projects": [item]})
            return tools.ToolOutcome({"status": "ok"}, {"collected_info": facts,
                "jd_info": {"role_profile": {"role_family": "ai_pm"}}})
        specs = {**tools.TOOLS, "record_facts": SimpleNamespace(args_model=tools.TOOLS["record_facts"].args_model, handler=record)}
        async def node(value, llm):
            script = ([{"content": "已按补充信息更新。"}] if value["messages"][-1].additional_kwargs.get("answers")
                      else [call("record_facts", source_id="current"), call("write_draft"), {"content": "初稿已生成。"}])
            scripted, events = Model(script), []
            result = await loop.run_orchestrator(value, scripted, registry=specs, llm=model, emit=events.append)
            requests.extend(scripted.requests)
            events_by_turn.append(events)
            return result
        class Client:
            def __init__(self, compiled):
                self.compiled, self.config = compiled, {"configurable": {"thread_id": "sparse-aipm"}}
            def turn(self, action, text, **payload):
                async def run():
                    old = (await self.compiled.aget_state(self.config)).values
                    kwargs = deepcopy(payload)
                    if kwargs.get("answers"):
                        kwargs["answer_card"] = pending_card(old)
                    incoming = HumanMessage(content=text, id=action, additional_kwargs=kwargs)
                    result = await self.compiled.ainvoke({"messages": [incoming]}, self.config)
                    return {"action": action, "input": text, **payload, "reply": result["messages"][-1].content,
                        "status": "ok", "sse_done": True, "stage": result["stage"], "revision": result.get("version_id"),
                        "resume_data": result["resume_data"], "collected_info": result["collected_info"],
                        "workspace": {"guidance": pending_card(result), "tailor": {"resume_meta": result["resume_meta"]}}}
                return asyncio.run(run())
        with (patch("app.config.get_settings", return_value=Settings(_env_file=None, AGENT_MODE="loop")),
              patch.object(loop, "orchestrator_node", node),
              patch("app.services.resume_capacity.measure_rendered_pages", side_effect=measured),
              patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=measured)):
            turns = list(module.replay(Client(graph.build_graph(SimpleNamespace(model_name="offline"), MemorySaver())), agent_mode="loop"))
        self.assertEqual([q["id"] for q in turns[0]["workspace"]["guidance"]["questions"]], ["dates"])
        self.assertEqual([q["id"] for q in turns[1]["workspace"]["guidance"]["questions"]], ["problem"])
        self.assertEqual(len(turns[0]["resume_data"]["projects"][0]["polished_bullets"]), 1)
        checks = module.evaluate_persona("aipm", turns)
        for suffix in ("labels", "answers_used", "no_repeated_dimension", "heading", "depth_within_limit"):
            row = next(c for c in checks if c["id"].endswith("." + suffix))
            self.assertEqual(row["status"], "pass", row)
        self.assertTrue(all(row["status"] == "pass" for row in checks), checks)
        self.assertEqual(len(turns), MAX_FOLLOWUP_ROUNDS + 1)
        self.assertFalse(turns[-1]["workspace"]["guidance"])
        for i, events in enumerate(events_by_turn):
            self.assertLessEqual(sum(e["type"] == "guidance" for e in events), 1)
            self.assertTrue(turns[i]["reply"].strip())
        final = turns[-1]
        item = final["resume_data"]["projects"][0]
        facts = {f["id"]: f for f in final["collected_info"]["projects"][0]["facts"]}
        meta = final["workspace"]["tailor"]["resume_meta"]["bullets"][item["item_id"]]
        for bullet, row in zip(item["polished_bullets"], meta):
            self.assertEqual(row["text_hash"], text_hash(bullet))
            self.assertTrue(row["fact_ids"])
            self.assertTrue(set(row["fact_ids"]) <= facts.keys())
            expected = {"问题": {"problem"}, "决策": {"decision"}, "迭代": {"iteration", "evaluation"}}.get(bullet.split("：")[0])
            if expected:
                self.assertTrue(expected & {facts[fid].get("dimension") for fid in row["fact_ids"]})
        self.assertTrue(any(facts[fid].get("turn_id", "").startswith("answers_") for row in meta for fid in row["fact_ids"]))
        outbound = json.dumps([requests, model.calls], ensure_ascii=False)
        self.assertNotIn(PHONE, outbound)
        self.assertNotIn(EMAIL, outbound)
        self.replay = {"mode": "offline_stubs", "turns": [{"action": t["action"],
            "questions": [q["id"] for q in t["workspace"]["guidance"].get("questions", [])],
            "bullets": t["resume_data"]["projects"][0]["polished_bullets"]} for t in turns], "checks": checks,
            "answer_evidence": [{"question_id": f["question_id"], "answer": f["answer_value"], "turn": f["turn_id"]}
                                for f in facts.values() if f.get("answer_value")]}


if __name__ == "__main__":
    unittest.main()
