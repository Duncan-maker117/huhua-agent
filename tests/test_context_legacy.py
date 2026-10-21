"""Model-boundary regressions for bounded, evidence-preserving legacy replies.

All identities and histories are synthetic; no provider or persistent store is
read. The suite runner supplies isolated application/checkpoint databases.
"""

import copy
from contextlib import nullcontext
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents import resume_graph as graph
from app.agents.context_memory import ensure_context_budget
from app.agents.triage_chain import TriageAction, TriageDecision
from app.services.error_codes import ChatTurnError
from app.services.resume_facts import new_fact

advice = importlib.import_module("app.agents.wording_advice")

BOUNDARY = "我没有训练过模型，没有企业实习；后端由队友开发，我只做反馈整理，项目没有上线。"


def long_state(stage="JD_INPUT", current="还没有想好先说哪段。"):
    old = "项目甲的过程记录：" + "synthetic detail; " * 450 + BOUNDARY
    messages = [HumanMessage(content=old, id="old-boundary")]
    for number in range(18):
        messages += [AIMessage(content=f"旧助手回复{number}：" + "话" * 8000, id=f"a{number}"),
                     HumanMessage(content=f"补充说明第{number}轮。", id=f"u{number}")]
    messages.append(HumanMessage(content=current, id="current"))
    result = graph._init_state()
    result.update(stage=stage, candidate_history_reconciled=True, messages=messages,
                  collected_info={"projects": [{"item_id": "p1", "name": "项目甲", "facts": [
                      {**new_fact("整理反馈并分类", quote="我整理反馈并分类"), "id": "f1"}]}]})
    return result


class CaptureModel:
    def __init__(self, *, fail_advice=False):
        self.calls = []
        self.fail_advice = fail_advice

    async def ainvoke(self, messages):
        self.calls.append(("public", copy.deepcopy(messages)))
        return AIMessage(content="可以继续补充项目甲的实际分工。")

    def with_structured_output(self, schema):
        async def invoke(messages):
            self.calls.append((schema.__name__, copy.deepcopy(messages)))
            if schema.__name__ == "WordingAdvice":
                if self.fail_advice:
                    raise RuntimeError("synthetic offline response failure")
                return {"options": [
                    {"text": "整理反馈并分类", "style": "concise", "fact_ids": ["f1"]},
                    {"text": "对反馈进行整理与分类", "style": "action", "fact_ids": ["f1"]},
                ]}
            if schema.__name__ == "SemanticBatch":
                return {"decisions": [
                    {"id": pair["id"], "subject_ok": True, "actions_supported": True,
                     "objects_supported": True, "results_supported": True, "limits_kept": True,
                     "unsupported_spans": [], "verdict": "pass"}
                    for pair in json.loads(messages[-1].content)
                ]}
            raise AssertionError(schema.__name__)
        return SimpleNamespace(ainvoke=invoke)


def flattened(messages):
    return "\n".join(str(message.content) for message in messages)


class LegacyContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_jd_reply_preserves_old_tail_and_current_turn_without_all_assistant_history(self):
        state, model = long_state(), CaptureModel()
        before = copy.deepcopy(state)
        with (
            patch.object(graph, "_make_non_streaming_llm", return_value=model),
            patch.object(graph, "run_triage", AsyncMock(return_value=TriageDecision(
                action=TriageAction.ASK_CLARIFY, reason="synthetic"))),
        ):
            await graph._jd_input_turn(state, model)
        self.assertEqual(state, before)
        self.assertEqual(len(model.calls), 1)
        messages = model.calls[0][1]
        text = flattened(messages)
        self.assertIn(BOUNDARY, text)
        self.assertIn(state["messages"][-1].content, text)
        self.assertNotIn("旧助手回复0：", text)
        self.assertNotIn("话" * 1500, text)
        self.assertLess(len(text), 30000)
        self.assertEqual(len([m for m in messages if m.additional_kwargs.get("candidate_memory")]), 1)
        self.assertNotIn('"candidate_facts"', text)

    async def test_collecting_reply_keeps_protected_boundaries_and_current_facts(self):
        state, model = long_state("COLLECTING", "继续"), CaptureModel()
        # An existing draft avoids the unrelated implicit first-draft branch.
        state["resume_versions"] = [{"version_id": "synthetic-existing"}]
        before = copy.deepcopy(state)
        with (
            patch.object(graph, "_make_non_streaming_llm", return_value=model),
            patch.object(graph, "run_triage", AsyncMock(return_value=TriageDecision(
                action=TriageAction.ASK_EXPERIENCE, reason="synthetic"))),
        ):
            await graph._collecting_turn_node(state, model)
        messages = next(messages for kind, messages in model.calls if kind == "public")
        self.assertIn(BOUNDARY, flattened(messages))
        self.assertIn("整理反馈并分类", flattened(messages))
        self.assertEqual(state, before)
        self.assertIn("继续", [m.content for m in messages if isinstance(m, HumanMessage)])

    async def test_oversized_protected_source_stops_before_public_model_call(self):
        state, model = long_state(), CaptureModel()
        state["messages"][0].content = "synthetic private payload " * 8000 + BOUNDARY
        before = copy.deepcopy(state)
        with (
            patch.object(graph, "_make_non_streaming_llm", return_value=model),
            patch.object(graph, "run_triage", AsyncMock(return_value=TriageDecision(
                action=TriageAction.ASK_CLARIFY, reason="synthetic"))),
        ):
            with self.assertRaises(ChatTurnError) as raised:
                await graph._jd_input_turn(state, model)
        self.assertEqual(raised.exception.code, "E-CONTEXT-LIMIT")
        self.assertNotIn("synthetic private payload", raised.exception.message)
        self.assertEqual(model.calls, [])
        self.assertEqual(state, before)

    async def test_stage_redaction_is_consistent_and_applies_before_budget(self):
        state = long_state(current="邮箱是 synthetic@example.test，继续。")
        state["collected_info"]["basic_info"] = {"email": "synthetic@example.test"}
        checked = []

        def check(messages, **kwargs):
            checked.append(copy.deepcopy(messages))
            return ensure_context_budget(messages, **kwargs)

        with patch.object(graph, "ensure_context_budget", side_effect=check):
            messages = graph._stage_messages(state, SystemMessage(content="可信任务规则"))
        self.assertEqual(len(checked), 1)
        self.assertNotIn("synthetic@example.test", flattened(checked[0]))
        import re
        tokens = re.findall(r"⟦邮箱:[a-z]+:[A-Z]+⟧", flattened(messages))
        self.assertGreater(len(tokens), 1)
        self.assertEqual(len(set(tokens)), 1)
        self.assertIn("synthetic@example.test", state["messages"][-1].content)
        model = CaptureModel()
        await graph.stream_public_reply(model, messages, ask_state=state)
        outbound = flattened(model.calls[0][1])
        self.assertNotIn("synthetic@example.test", outbound)
        self.assertEqual(len(set(re.findall(r"⟦邮箱:[a-z]+:[A-Z]+⟧", outbound))), 1)


class ToolCaptureModel(CaptureModel):
    def bind_tools(self, *args, **kwargs):
        return self


def budget_boundary(boundary):
    # Leave the public boundary's real budget check intact. Bypass only the
    # earlier duplicate check to exercise the appended-contract/tool boundary.
    return patch.object(graph, "ensure_context_budget", return_value=0) if boundary == "public" else nullcontext()


def oversized_state(stage, current):
    state = long_state(stage, current)
    state["messages"][0].content = "synthetic protected original " * 8000 + BOUNDARY
    return state


class RetainedUpdatesOnBudgetStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_build_and_edit_survive_both_optional_followup_budget_boundaries(self):
        for node in (graph.building_node, graph._evaluating_turn_node):
            for boundary in ("stage", "public"):
                with self.subTest(node=node.__name__, boundary=boundary):
                    state = oversized_state("BUILDING" if node is graph.building_node else "EVALUATING",
                                            "把项目甲简练一点")
                    state["intake_stage"] = "ready"
                    state["resume_data"] = {"projects": [{"item_id": "p1", "name": "项目甲",
                                                          "polished_bullets": ["上版：整理反馈并分类"]}]}
                    written = {"collected_info": copy.deepcopy(state["collected_info"]),
                               "resume_data": {"projects": [{"item_id": "p1", "name": "项目甲",
                                                              "polished_bullets": ["整理反馈并分类"]}]},
                               "resume_meta": {"synthetic_receipt": "verified"}, "version_id": "saved-new-version",
                               "resume_versions": [{"version_id": "old-version", "resume_data": state["resume_data"]}],
                               "changed": True, "change_summary": ["精简项目甲"]}
                    before, model = copy.deepcopy(state), ToolCaptureModel()
                    with (
                        patch.object(graph, "_write_resume_update", AsyncMock(return_value=copy.deepcopy(written))) as writer,
                        patch.object(graph, "_generation_contains_facts", return_value=False),
                        patch("app.agents.router.route_intents", AsyncMock(return_value={"intents": ["edit"], "edit_plan": []})),
                        patch("app.agents.interviewer.question_candidates", return_value=[{"subject": "项目甲"}]),
                        budget_boundary(boundary),
                    ):
                        result = await node(state, model)
                    writer.assert_awaited_once()
                    for key in ("resume_data", "resume_meta", "collected_info", "resume_versions", "version_id"):
                        self.assertEqual(result[key], written[key])
                    self.assertEqual(result["stage"], "EVALUATING")
                    self.assertIn("后续追问因上下文容量不足暂停", result["messages"][-1].content)
                    self.assertEqual(result["messages"][-1].additional_kwargs["turn_error"]["code"], "E-CONTEXT-LIMIT")
                    self.assertEqual(model.calls, [])
                    self.assertEqual(state, before)

    async def test_collected_new_fact_and_live_resume_survive_guidance_budget_stop(self):
        for boundary in ("stage", "public"):
            with self.subTest(boundary=boundary):
                source = "项目甲：我整理了反馈清单，没有上线。"
                state, model = oversized_state("COLLECTING", source), ToolCaptureModel()
                state["resume_versions"] = [{"version_id": "synthetic-existing"}]
                updated = copy.deepcopy(state["collected_info"])
                updated["projects"][0]["facts"].append({**new_fact(source, quote=source), "id": "new-fact"})
                before = copy.deepcopy(state)
                with (
                    patch.object(graph, "_make_non_streaming_llm", return_value=model),
                    patch.object(graph, "run_triage", AsyncMock(return_value=TriageDecision(
                        action=TriageAction.WRAP_EXPERIENCE, reason="synthetic", experience_snippet=source))),
                    patch.object(graph, "_extract_with_previous_assistant", AsyncMock(return_value=updated)),
                    budget_boundary(boundary),
                ):
                    result = await graph._collecting_turn_node(state, model)
                self.assertEqual(result["collected_info"]["projects"][0]["facts"][-1]["source_quote"], source)
                self.assertIn("反馈清单", json.dumps(result["resume_data"], ensure_ascii=False))
                self.assertIn("后续回复因上下文容量不足暂停", result["messages"][0].content)
                self.assertEqual(model.calls, [])
                self.assertEqual(state, before)

    async def test_submitted_intake_survives_both_guidance_budget_boundaries(self):
        for boundary in ("stage", "public"):
            with self.subTest(boundary=boundary):
                state, model = oversized_state("COLLECTING", "提交经历清单"), ToolCaptureModel()
                state["resume_versions"] = [{"version_id": "synthetic-existing"}]
                message = HumanMessage(content="提交经历清单", id="intake-current", additional_kwargs={"intake": {
                    "kind": "experiences", "items": [{"name": "项目乙", "type": "项目", "role": "仅整理反馈",
                                                        "summary": "整理反馈清单，没有上线。"}]}})
                state["messages"][-1] = message
                before = copy.deepcopy(state)
                with budget_boundary(boundary):
                    result = await graph._intake_form_turn(state, model, message)
                saved = next(item for item in result["collected_info"]["projects"] if item["name"] == "项目乙")
                self.assertEqual(saved["role"], "仅整理反馈")
                self.assertIn("没有上线", json.dumps(saved, ensure_ascii=False))
                self.assertIn("项目乙", json.dumps(result["resume_data"], ensure_ascii=False))
                self.assertIn("后续回复因上下文容量不足暂停", result["messages"][0].content)
                self.assertEqual(model.calls, [])
                self.assertEqual(state, before)


class WordingContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_wording_and_retry_keep_earlier_unstructured_limits(self):
        state, model = long_state(current="怎么写更好"), CaptureModel(fail_advice=True)
        before = copy.deepcopy(state)
        await advice.wording_advice(state, "怎么写更好", model)
        calls = [messages for kind, messages in model.calls if kind == "WordingAdvice"]
        self.assertEqual(len(calls), 2)
        for messages in calls:
            payload = json.loads(messages[-1].content)
            self.assertIn(BOUNDARY, json.dumps(payload["candidate_memory"], ensure_ascii=False))
            self.assertEqual(payload["message"], "怎么写更好")
            self.assertNotIn("话" * 1500, flattened(messages))
        self.assertEqual(state, before)

    async def test_wording_overflow_is_not_swallowed_by_model_fallback(self):
        state, model = long_state(), CaptureModel()
        state["messages"][0].content = "synthetic protected original " * 8000 + BOUNDARY
        with self.assertRaises(ChatTurnError) as raised:
            await advice.wording_advice(state, "怎么写更好", model)
        self.assertEqual(raised.exception.code, "E-CONTEXT-LIMIT")
        self.assertEqual(model.calls, [])

    async def test_retry_budget_includes_refill_and_schema_and_stops_before_second_call(self):
        state, model = long_state(), CaptureModel(fail_advice=True)
        checks = []

        def check(messages, **kwargs):
            checks.append((copy.deepcopy(messages), kwargs))
            if len(checks) == 2:
                # The same real checker rejects this fuller retry payload.
                return ensure_context_budget(messages, **kwargs, max_input_tokens=1024)
            return ensure_context_budget(messages, **kwargs)

        with patch.object(advice, "ensure_context_budget", side_effect=check):
            with self.assertRaises(ChatTurnError) as raised:
                await advice.wording_advice(state, "怎么写更好", model)
        self.assertEqual(raised.exception.code, "E-CONTEXT-LIMIT")
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(len(checks), 2)
        self.assertIn('"requested_styles"', flattened(checks[1][0]))
        self.assertEqual(checks[1][1]["schemas"][0]["title"], "WordingAdvice")


if __name__ == "__main__":
    unittest.main()
