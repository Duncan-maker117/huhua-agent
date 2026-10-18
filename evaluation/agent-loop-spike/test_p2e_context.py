"""P2a offline regressions, kept separate from P2c's evaluation/test ownership."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from langchain_core.messages import AIMessage, HumanMessage
from openai import AsyncOpenAI
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests")]
from app.agents import orchestrator as loop, orchestrator_context as context  # noqa: E402
from app.agents.orchestrator_spike import ModelReply  # noqa: E402
from app.agents.orchestrator_tools import ToolOutcome  # noqa: E402
from app.services.model_privacy import ContactRedactor  # noqa: E402
from test_orchestrator import BadRequest, Model, call, registry, state  # noqa: E402


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def facts():
    return {"basic_info": {"name": "离线样例", "phone": "13912340000", "email": "context@example.invalid"},
            "projects": [{"name": "温室巡检", "role": "数据核对", "raw_notes": ["PRIVATE_SOURCE" * 2000],
                "facts": [{"text": f"核对第{i}组记录。这里是省略的后句。", "source_quote": "PRIVATE_QUOTE" * 500,
                           "sources": [{"source_quote": "PRIVATE_ORIGIN"}], "status": "active"} for i in range(80)] +
                         [{"text": "未连接生产设备", "kind": "status_limit", "status": "active"},
                          {"text": "SUPERSEDED_FACT", "status": "superseded"}]}]}


class ContextProjectionTests(unittest.TestCase):
    def test_fact_summary_omits_provenance_and_retains_counts_limits_and_contacts(self):
        source = facts()
        before = deepcopy(source)
        result = context.project_tool_result("record_facts", {"status": "partial", "changed": True,
            "collected_info": source, "uncovered": ["尚未识别的补充"], "rejected_count": 2}, ContactRedactor())
        item = result["collected_info"]["items"][0]
        self.assertEqual(item["name"], "温室巡检")
        self.assertEqual(item["point_count"], 81)
        self.assertEqual(item["first_sentences"][0], "核对第0组记录。")
        self.assertIn("未连接生产设备", item["scope_limits"])
        self.assertEqual(result["collected_info"]["contacts_present"], {"phone": True, "email": True})
        self.assertEqual(result["uncovered"], ["尚未识别的补充"])
        self.assertEqual(result["rejected_count"], 2)
        for forbidden in ("PRIVATE_", "SUPERSEDED_FACT", "13912340000", "context@example.invalid"):
            self.assertNotIn(forbidden, encoded(result))
        self.assertEqual(source, before)

    def test_document_summary_retains_version_page_missing_and_error(self):
        document = {"basic_info": facts()["basic_info"], "projects": [{"name": "温室巡检",
            "bullets": [f"第{i}条首句。后句正文" * 100 for i in range(60)]}]}
        raw = {"status": "partial", "code": "guard_fallback", "version_id": "version-two", "changed": True,
               "resume_data": document, "contacts_missing": ["email"],
               "page_check": {"pages": 2, "page_limit": 1, "within_page_limit": False, "data_hash": "SECRET_HASH"},
               "writer_diagnostic": {"status": "model_fallback", "reason": "unsupported_fact"}}
        result = context.project_tool_result("write_draft", raw, ContactRedactor())
        self.assertEqual(result["version_id"], "version-two")
        self.assertEqual(result["page_check"]["pages"], 2)
        self.assertFalse(result["page_check"]["within_page_limit"])
        self.assertEqual(result["contacts_missing"], ["email"])
        self.assertEqual(result["resume_data"]["items"][0]["point_count"], 60)
        self.assertEqual(result["writer_diagnostic"]["reason"], "unsupported_fact")
        self.assertNotIn("SECRET_HASH", encoded(result))
        self.assertLessEqual(len(encoded(result)), context.TOOL_RESULT_CHARS)

    def test_profile_selection_ids_and_import_receipt_survive(self):
        rows = [{"id": "profile-one", "name": "温室巡检", "category": "project", "summary": "核对记录",
                 "fact_ids": ["PRIVATE_FACT"], "raw_notes": "PRIVATE_NOTES"}]
        catalog = context.project_tool_result("read_profile", {"status": "ok", "items": rows}, ContactRedactor())
        self.assertEqual(catalog["items"][0]["id"], "profile-one")
        self.assertNotIn("PRIVATE", encoded(catalog))
        receipt = context.project_tool_result("use_profile_items", {"status": "ok", "imported": ["温室巡检"],
            "facts": [{"value": "PRIVATE_FACT"}] * 500}, ContactRedactor())
        self.assertEqual(receipt["imported"], ["温室巡检"])
        self.assertEqual(receipt["fact_count"], 500)
        self.assertNotIn("PRIVATE", encoded(receipt))

    def test_truncation_is_marked_bounded_and_redacted_before_slicing(self):
        for text in ('"\\\n' * 2000, '中' * 4000, 'a' * 330 + ' context@example.invalid'):
            raw = {"status": "error", "code": "upstream_error", "message": text,
                   "type": "image_url", "url": "data:context@example.invalid", "nested": [[text] * 10] * 4}
            result = context.project_tool_result("search_company", raw, ContactRedactor())
            self.assertEqual(result["code"], "upstream_error")
            self.assertLessEqual(len(encoded(result)), context.TOOL_RESULT_CHARS)
            self.assertNotIn("context@example", encoded(result))
            self.assertIn("截断", encoded(result))

    def test_history_keeps_recent_originals_and_deterministic_old_summary(self):
        messages = []
        for index in range(10):
            messages.extend([HumanMessage(content=f"原文材料{index}", id=f"source-{index}"),
                AIMessage(content=f"答复{index}", additional_kwargs={"ask_user": {"subject": "温室巡检",
                    "questions": [{"id": "problem", "prompt": "解决什么问题？"}]}})])
        messages.append(HumanMessage(content="这是本轮更正原文", id="latest"))
        value = state(messages=messages, collected_info=facts(), version_id="version-two",
            resume_data={"projects": [{"name": "温室巡检", "bullets": ["核对记录"]}]},
            jd_info={"role_direction": "数据处理"}, closed_questions=[{"subject": "温室巡检", "dimension": "evaluation"}])
        original = deepcopy(value)
        data = context.input_context(value, loop._sources(value), ContactRedactor())
        self.assertEqual(data["history"][-1]["content"], "这是本轮更正原文")
        self.assertEqual([r["source_id"] for r in data["history"] if r["role"] == "user"], ["source-8", "source-9", "latest"])
        summary = data["state"]["summary"]
        self.assertEqual(summary["omitted_messages"], 16)
        self.assertEqual(summary["direction"], "数据处理")
        self.assertEqual(summary["version_id"], "version-two")
        self.assertIn("温室巡检", summary["recorded_experiences"])
        self.assertEqual(summary["asked_dimensions"], [{"subject": "温室巡检", "dimension": "problem"}])
        self.assertEqual(summary["closed_questions"], value["closed_questions"])
        self.assertNotIn("text", data["sources"]["source-0"])
        self.assertEqual(loop._sources(value)["source-0"]["text"], "原文材料0")
        self.assertEqual(value, original)

    def test_large_history_and_state_are_bounded_without_modifying_sources(self):
        value = state(messages=[HumanMessage(content='"\\\n' * 20000, id=f"source-{i}") for i in range(30)],
            collected_info=facts(), resume_data={"projects": [{"name": "项目" * 100, "bullets": ["正文" * 5000]}] * 30})
        sources = loop._sources(value)
        data = context.input_context(value, sources, ContactRedactor())
        self.assertLess(len(encoded(data)), context.HISTORY_CHARS + context.STATE_CHARS + 2100)
        self.assertLessEqual(len(encoded(data["state"])), context.STATE_CHARS)
        self.assertIn("current", data["sources"])
        self.assertEqual(data["omitted_sources"], 18)
        self.assertEqual(len(sources["source-0"]["text"]), 60000)
        self.assertIn("截断", encoded(data))

    def test_prefix_and_schema_are_stable_across_contacts_and_registry_order(self):
        first = loop._input_messages(state("你好"), loop._sources(state("你好")), ContactRedactor())
        second_state = state("电话 13912340000 context@example.invalid", collected_info=facts())
        second = loop._input_messages(second_state, loop._sources(second_state), ContactRedactor())
        self.assertEqual(first[0], second[0])
        self.assertEqual(loop._schemas(registry()), loop._schemas(dict(reversed(list(registry().items())))))
        self.assertNotIn("context@example.invalid", encoded(second))
        self.assertEqual(second[0]["content"].count(loop.CONTACT_PRIVACY_NOTICE), 1)

    def test_final_mode_settings_default_override_and_validation(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(context.OrchestratorSettings(_env_file=None).AGENT_FINAL_MODE, "off")
        with patch.dict(os.environ, {"AGENT_FINAL_MODE": "off"}):
            self.assertEqual(context.OrchestratorSettings(_env_file=None).AGENT_FINAL_MODE, "off")
        with self.assertRaises(ValidationError):
            context.OrchestratorSettings(_env_file=None, AGENT_FINAL_MODE="invalid")


class ContextLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_projection_only_changes_outbound_not_handler_or_saved_state(self):
        source = facts()
        async def record(working, args, ctx):
            self.assertEqual(working["messages"][0].content, "完整来源" * 3000)
            return ToolOutcome({"status": "ok", "collected_info": source}, {"collected_info": source})
        async def draft(working, args, ctx):
            self.assertEqual(working["collected_info"], source)
            return ToolOutcome({"status": "ok"}, stop=True)
        value = state(messages=[HumanMessage(content="完整来源" * 3000, id="old"), HumanMessage(content="继续", id="now")])
        model = Model([call("record_facts", source_id="old"), call("write_draft"), {"content": "完成"}])
        result = await loop.run_orchestrator(value, model, registry=registry(record_facts=record, write_draft=draft))
        self.assertEqual(result["collected_info"], source)
        for request in model.requests:
            self.assertNotIn("PRIVATE_SOURCE", encoded(request))
            self.assertNotIn("13912340000", encoded(request))
            self.assertNotIn("context@example.invalid", encoded(request))

    async def test_final_off_preserves_decision_reasoning_and_tool_pairing(self):
        model = Model([call("read_profile"), call("check_layout"), {"content": "核对完成", "deltas": ["核对", "完成"]}])
        tools = registry(check_layout=AsyncMock(return_value=ToolOutcome({"status": "ok"}, stop=True)))
        result = await loop.run_orchestrator(state(), model, registry=tools, final_mode="off")
        self.assertEqual([r["mode"] for r in model.requests], ["thinking", "thinking", "off"])
        self.assertIn("reasoning_content", model.requests[1]["messages"][2])
        self.assertFalse(any("reasoning_content" in m for m in model.requests[-1]["messages"]))
        self.assertEqual(len([m for m in model.requests[-1]["messages"] if m["role"] == "tool"]), 2)
        self.assertEqual(result["messages"][-1].content, "核对完成")
        self.assertFalse(result["messages"][-1].additional_kwargs["orchestrator"]["fallback"])

    async def test_default_final_off_and_auto_text_remains_thinking(self):
        for final_mode in ("thinking", "off"):
            model = Model([{"content": "你好"}])
            await loop.run_orchestrator(state(), model, registry=registry(), final_mode=final_mode)
            self.assertEqual(model.requests[0]["mode"], "thinking")
        model = Model([call("check_layout"), {"content": "完成"}])
        await loop.run_orchestrator(state(), model, registry=registry(check_layout=AsyncMock(
            return_value=ToolOutcome({"status": "ok"}, stop=True))))
        self.assertEqual([r["mode"] for r in model.requests], ["thinking", "off"])

    async def test_final_off_after_budget_fallback_and_dsml_retry(self):
        scripts = [([call("check_layout")] * 4 + [{"content": "完成"}], ["thinking"] * 4 + ["off"]),
                   ([BadRequest("private"), call("check_layout"), {"content": "完成"}], ["thinking", "off", "off"]),
                   ([call("check_layout"), {"content": loop.DSML_MARKER + "invoke>"}, {"content": "完成"}],
                    ["thinking", "off", "off"])]
        for index, (script, modes) in enumerate(scripts):
            model = Model(script)
            tools = registry(check_layout=AsyncMock(return_value=ToolOutcome({"status": "ok"}, stop=index != 0)))
            result = await loop.run_orchestrator(state(), model, registry=tools, final_mode="off")
            self.assertEqual([r["mode"] for r in model.requests], modes)
            self.assertEqual(result["messages"][-1].content, "完成")
            self.assertNotIn(loop.DSML_MARKER, encoded(model.requests))

    async def test_failure_usage_unknown_and_metric_body_is_never_logged(self):
        model = AsyncMock()
        model.complete.side_effect = [ModelReply({"role": "assistant", "content": "", "reasoning_content": "思考",
            "tool_calls": [{"id": "one", "type": "function", "function": {"name": "check_layout", "arguments": "{}"}}]},
            {"prompt_tokens": 100, "completion_tokens": 20, "reasoning_tokens": 6, "prompt_cache_hit_tokens": 80,
             "prompt_cache_miss_tokens": 20, "unexpected_body": "PRIVATE_BODY"}), RuntimeError("PRIVATE_ERROR")]
        with self.assertLogs(loop.logger, level="INFO") as logs:
            result = await loop.run_orchestrator(state(), model, registry=registry())
        metrics = result["messages"][-1].additional_kwargs["orchestrator"]
        self.assertEqual(metrics["turns"][0]["usage"]["prompt_cache_hit_tokens"], 80)
        self.assertIsNone(metrics["usage"]["prompt_tokens"])
        self.assertIsNone(metrics["usage"]["prompt_cache_hit_tokens"])
        self.assertTrue(all(row["seconds"] >= 0 for row in metrics["turns"]))
        self.assertNotIn("PRIVATE_", str(logs.output))

    async def test_actual_sdk_stream_cache_usage_and_final_off_wire_request(self):
        requests = []
        def transport(request):
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 1:
                delta = {"reasoning_content": "保留完整思考", "tool_calls": [{"index": 0, "id": "sdk-call",
                    "type": "function", "function": {"name": "check_layout", "arguments": "{}"}}]}
                usage = {"prompt_tokens": 100, "completion_tokens": 20, "prompt_cache_hit_tokens": 80,
                         "prompt_cache_miss_tokens": 20, "completion_tokens_details": {"reasoning_tokens": 5}}
            else:
                delta = {"content": "已核对"}
                usage = {"prompt_tokens": 110, "completion_tokens": 10, "reasoning_tokens": 0,
                         "prompt_cache_hit_tokens": 90, "prompt_cache_miss_tokens": 20}
            frames = [{"choices": [{"index": 0, "delta": delta}]}, {"choices": [{"index": 0, "delta": {},
                "finish_reason": "tool_calls" if len(requests) == 1 else "stop"}]}, {"choices": [], "usage": usage}]
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                content="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames) + "data: [DONE]\n\n")
        tools = registry(check_layout=AsyncMock(return_value=ToolOutcome({"status": "ok"}, stop=True)))
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            async with AsyncOpenAI(api_key="offline", base_url="https://model.invalid/v1", http_client=http) as client:
                model = loop.OrchestratorModel(client, model="offline", schemas=loop._schemas(tools))
                result = await loop.run_orchestrator(state(), model, registry=tools, final_mode="off")
        self.assertEqual(requests[0]["thinking"], {"type": "enabled"})
        self.assertEqual(requests[1]["thinking"], {"type": "disabled"})
        self.assertEqual(requests[1]["tool_choice"], "none")
        self.assertEqual(requests[0]["tools"], requests[1]["tools"])
        self.assertEqual(requests[0]["messages"][0], requests[1]["messages"][0])
        metrics = result["messages"][-1].additional_kwargs["orchestrator"]
        self.assertEqual(metrics["usage"]["prompt_cache_hit_tokens"], 170)
        self.assertEqual(metrics["usage"]["prompt_cache_miss_tokens"], 40)
        self.assertEqual(metrics["usage"]["reasoning_tokens"], 5)
        self.assertEqual([row["phase"] for row in metrics["turns"]], ["decision", "final"])

    def test_usage_preserves_zero_and_unknown_and_openai_cache_shape(self):
        self.assertIsNone(loop._usage({})["prompt_cache_hit_tokens"])
        self.assertEqual(loop._usage({"prompt_cache_hit_tokens": 0})["prompt_cache_hit_tokens"], 0)
        self.assertEqual(loop._usage({"prompt_tokens_details": {"cached_tokens": 7}})["prompt_cache_hit_tokens"], 7)
        for value in (True, "PRIVATE_BODY", -1):
            self.assertIsNone(loop._usage({"prompt_tokens": value})["prompt_tokens"])


if __name__ == "__main__":
    unittest.main()
