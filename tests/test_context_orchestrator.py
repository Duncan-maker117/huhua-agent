"""Context fidelity at the actual orchestration boundary, with offline models."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests")]
from app.agents import orchestrator as loop  # noqa: E402
from app.agents.orchestrator_context import input_context  # noqa: E402
from app.agents.orchestrator_tools import ToolOutcome, TOOLS, _source  # noqa: E402
from app.agents.orchestrator_spike import validate_history  # noqa: E402
from app.services.model_privacy import ContactRedactor  # noqa: E402
from app.services.resume_facts import new_fact  # noqa: E402
from test_orchestrator import Model, call, registry, state  # noqa: E402


def memory(request):
    return json.loads(request["messages"][1]["content"])["untrusted_data"]["candidate_memory"]


class ContextLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_fact_and_late_negative_are_visible_at_model_boundary(self):
        items = []
        for i in range(14):
            facts = [new_fact(f"项目{i}整理了第{j}份材料", turn_id=f"old-{i}") for j in range(4)]
            facts += [new_fact(f"项目{i}没有企业实习经历，也没有做过线上压测。", kind="status_limit", turn_id=f"old-{i}")]
            items.append({"item_id": f"p{i}", "name": f"项目{i}", "facts": facts})
        value = state("看看我的经历", collected_info={"projects": items})
        original = deepcopy(value)
        model = Model([{"content": "可以按现有经历整理。"}])
        await loop.run_orchestrator(value, model, registry=registry())
        sent = json.dumps(memory(model.requests[0]), ensure_ascii=False)
        for item in items:
            for fact in item["facts"]:
                self.assertIn(fact["text"], sent)
                self.assertIn(fact["id"], sent)
        self.assertEqual(value, original)

    async def test_next_decision_refreshes_corrected_facts_without_breaking_tool_pairs(self):
        old = new_fact("平均耗时170ms", turn_id="old-source")
        new = new_fact("平均耗时190ms", turn_id="user-source")
        value = state("实际为190ms", collected_info={"projects": [{"item_id": "p", "name": "课程项目", "facts": [old]}]})
        value["messages"].insert(0, HumanMessage(content=old["text"], id="old-source"))
        changed = {"projects": [{"item_id": "p", "name": "课程项目", "facts": [{**old, "status": "superseded"}, {**new, "replaces": old["id"]}]}]}
        record = AsyncMock(return_value=ToolOutcome({"status": "ok"}, {"collected_info": changed}))
        model = Model([call("record_facts", source_id="current"), {"content": "已更正。"}])
        await loop.run_orchestrator(value, model, registry=registry(record_facts=record))
        before, after = memory(model.requests[0]), memory(model.requests[1])
        self.assertIn("平均耗时170ms", json.dumps(before, ensure_ascii=False))
        self.assertNotIn("平均耗时170ms", json.dumps(after, ensure_ascii=False))
        self.assertIn("平均耗时190ms", json.dumps(after, ensure_ascii=False))
        for request in model.requests:
            validate_history(request["messages"], request["mode"])
        self.assertEqual(len([m for m in model.requests[1]["messages"] if m["role"] == "tool"]), 1)

    async def test_context_overflow_prevents_model_and_tools_without_mutating_state(self):
        value = state("不能为了继续就删除我的事实。")
        original = deepcopy(value)
        model, tools = Model([]), registry()
        with patch.dict(os.environ, {"CONTEXT_MAX_INPUT_TOKENS": "1024"}):
            result = await loop.run_orchestrator(value, model, registry=tools)
        self.assertFalse(model.requests)
        for spec in tools.values():
            spec.handler.assert_not_awaited()
        self.assertEqual(value, original)
        metrics = result["messages"][-1].additional_kwargs["orchestrator"]
        self.assertEqual(metrics["status"], "context_limit")
        self.assertEqual(metrics["model_calls"], 0)
        self.assertNotIn("不能为了继续就删除我的事实", result["messages"][-1].content)

    async def test_overflow_after_tool_keeps_validated_updates(self):
        value = state("记录材料")
        changed = {"projects": [{"item_id": "p", "name": "长材料", "facts": [new_fact("未做过线上压测。" * 5000)]}]}
        record = AsyncMock(return_value=ToolOutcome({"status": "ok"}, {"collected_info": changed}))
        model = Model([call("record_facts", source_id="current")])
        result = await loop.run_orchestrator(value, model, registry=registry(record_facts=record))
        self.assertEqual(len(model.requests), 1)
        self.assertEqual(result["collected_info"], changed)
        self.assertEqual(result["messages"][-1].additional_kwargs["orchestrator"]["status"], "context_limit")

    async def test_mixed_source_stays_recordable_after_jd_read(self):
        value = state("我的经历：\n我做过课程项目，没做过线上压测。\nJD：\n岗位职责：维护系统")
        read = AsyncMock(return_value=ToolOutcome({"status": "ok", "source_kind": "jd"}, {"jd_info": {"job_title": "开发"}}))
        record = AsyncMock(return_value=ToolOutcome({"status": "ok"}))
        model = Model([call("read_jd", source_id="current"), call("record_facts", source_id="current"), {"content": "已记录。"}])
        await loop.run_orchestrator(value, model, registry=registry(read_jd=read, record_facts=record))
        record.assert_awaited_once()

    async def test_pure_jd_is_excluded_after_tool_updates_source_classification(self):
        value = state("岗位职责：维护系统")
        read = AsyncMock(return_value=ToolOutcome({"status": "ok"}, {"non_candidate_message_ids": ["user-source"]}))
        record = AsyncMock(return_value=ToolOutcome({"status": "ok"}))
        model = Model([call("read_jd", source_id="current"), call("record_facts", source_id="current"), {"content": "已读取岗位。"}])
        await loop.run_orchestrator(value, model, registry=registry(read_jd=read, record_facts=record))
        record.assert_not_awaited()
        self.assertNotIn("岗位职责：维护系统", json.dumps(memory(model.requests[1]), ensure_ascii=False))

    def test_old_unextracted_source_remains_discoverable_and_latest_tail_is_complete(self):
        value = state()
        value["messages"] = [HumanMessage(content="我没做过模型训练，但独立整理过评测记录。", id="early")]
        for i in range(20):
            value["messages"] += [AIMessage(content="解释" * 1000), HumanMessage(content=f"讨论第{i}轮", id=f"u{i}")]
        latest = "背景" * 1800 + "没有做过支付接口，也不是项目负责人。"
        value["messages"].append(HumanMessage(content=latest, id="latest"))
        data = input_context(value, loop._sources(value), ContactRedactor())
        self.assertIn("early", data["sources"])
        self.assertIn("我没做过模型训练", json.dumps(data["candidate_memory"], ensure_ascii=False))
        self.assertEqual(data["history"][-1]["content"], latest)

    def test_deleted_fact_is_not_revived_by_navigation_summary(self):
        fact = {**new_fact("负责了生产支付系统", turn_id="early"), "status": "deleted"}
        value = state("继续", collected_info={"projects": [{"item_id": "p", "name": "课程项目", "description": fact["text"], "facts": [fact]}]})
        value["messages"].insert(0, HumanMessage(content=fact["text"], id="early"))
        data = input_context(value, loop._sources(value), ContactRedactor())
        self.assertNotIn(fact["text"], json.dumps(data, ensure_ascii=False))

    async def test_actual_record_tool_blocks_reimport_even_when_pending_is_empty(self):
        old = {**new_fact("我实现了生产支付接口", turn_id="old"), "status": "deleted"}
        value = state("整理当前资料", collected_info={"projects": [{"item_id": "p", "name": "课程项目", "facts": [old]}]})
        value["messages"].insert(0, HumanMessage(content=old["text"], id="old"))
        model = Model([call("record_facts", source_id="old"), {"content": "请提供当前确认的信息。"}])
        result = await loop.run_orchestrator(value, model, registry=registry(record_facts=TOOLS["record_facts"].handler))
        response = next(m for m in model.requests[-1]["messages"] if m["role"] == "tool")
        self.assertEqual(json.loads(response["content"])["untrusted_data"]["code"], "requires_current_confirmation")
        self.assertNotIn("collected_info", result)

    def test_old_idless_source_index_is_resolvable_by_tool(self):
        value = {"messages": [AIMessage(content="请介绍经历"), HumanMessage(content="我没做过部署")]}
        identifier = next(key for key in loop._sources(value) if key != "current")
        self.assertIs(_source(value, identifier), value["messages"][1])

    def test_navigation_keeps_stop_and_verification_fields(self):
        from app.agents.orchestrator_context import _facts
        projected = _facts({"no_more_questions": True, "verification_notes": ["没有测过线上性能"]})
        self.assertTrue(projected["no_more_questions"])
        self.assertEqual(projected["verification_notes"], ["没有测过线上性能"])

    async def test_public_profile_continuation_overflow_retains_import_update(self):
        from app.agents.public_reply import stream_public_reply

        class ProfileModel:
            def __init__(self):
                self.calls = 0

            def bind_tools(self, _tools, **kwargs):
                return self

            async def ainvoke(self, messages):
                self.calls += 1
                return AIMessage(content="", tool_calls=[{"id": "import-call", "name": "use_profile_items", "args": {"item_ids": ["p"]}}])

        model = ProfileModel()
        imported = {"projects": [{"item_id": "p", "name": "课程项目", "facts": [new_fact("没做过线上压测。" * 6000)]}]}
        outcome = ({"status": "ok", "imported": ["课程项目"]}, {"collected_info": imported})
        with patch("app.services.profile_tools.tools_enabled", return_value=True), \
             patch("app.services.profile_tools.execute_profile_tool", AsyncMock(return_value=outcome)):
            reply = await stream_public_reply(model, [HumanMessage(content='{"candidate_memory":{}}',
                additional_kwargs={"candidate_memory": True}), HumanMessage(content="使用档案")], ask_state=state("使用档案"))
        self.assertEqual(model.calls, 1)
        self.assertEqual(reply.additional_kwargs["profile_update"]["collected_info"], imported)
        self.assertTrue(reply.additional_kwargs["public_reply_interrupted"])
        self.assertIn("上下文", reply.content)


if __name__ == "__main__":
    unittest.main()
