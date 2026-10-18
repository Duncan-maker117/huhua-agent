"""Offline loop/protocol checks; prescribed tools do not measure model judgment."""
import argparse
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
from contextlib import redirect_stdout
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.agents.orchestrator_spike import (  # noqa: E402
    FakeTools, ModelReply, OpenAIStreamModel, ScriptedModel, SYSTEM_PROMPT,
    real_adapters, run_loop, thinking_body, validate_history, SpikeProtocolError,
)
from run_agent_spike import assess, evaluate, DEFAULT_CASES  # noqa: E402


def call(name, **arguments):
    return {"calls": [{"name": name, "arguments": arguments}]}


class OrchestratorSpikeTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_cases_both_modes_and_no_test_content_in_system(self):
        cases = json.loads(DEFAULT_CASES.read_text())["cases"]
        self.assertEqual(len(cases), 10)
        for mode in ("off", "thinking"):
            for case in cases:
                with self.subTest(mode=mode, case=case["id"]):
                    model = ScriptedModel(case["stub_script"])
                    result = await run_loop(model, FakeTools(case["user_message"], state=case["state"]),
                                            user_message=case["user_message"], history_summary=case["history_summary"], mode=mode)
                    self.assertTrue(assess(case, result)["matches_expectation"], result)
                    self.assertLessEqual(result["steps"], 4)
                    self.assertNotIn(case["user_message"], SYSTEM_PROMPT)
                    for request in model.requests:
                        validate_history(request["messages"], mode)

    async def test_budget_allows_four_tools_and_one_final_request(self):
        model = ScriptedModel([call("read_profile") for _ in range(4)] + [{"content": "完成模拟查看"}])
        result = await run_loop(model, FakeTools("查看"), user_message="查看", mode="thinking")
        self.assertEqual(result["steps"], 4)
        self.assertEqual(result["model_calls"], 5)
        self.assertFalse(model.requests[-1]["allow_tools"])
        self.assertEqual(result["status"], "completed")

    async def test_model_cannot_execute_fifth_tool(self):
        handler = AsyncMock(return_value={"status": "ok"})
        model = ScriptedModel([call("read_profile") for _ in range(5)])
        result = await run_loop(model, FakeTools("查看", handlers={"read_profile": handler}), user_message="查看")
        self.assertEqual(handler.await_count, 4)
        self.assertEqual(result["steps"], 4)
        self.assertEqual(result["status"], "budget_exceeded")
        self.assertEqual(len(result["requested_tool_sequence"]), 5)

    async def test_parallel_tool_batch_cannot_bypass_budget_and_ids_all_answered(self):
        model = ScriptedModel([{"calls": [{"name": "read_profile"} for _ in range(6)]}, {"content": "预算已满"}])
        result = await run_loop(model, FakeTools("查看"), user_message="查看", mode="thinking")
        self.assertEqual(result["steps"], 4)
        self.assertEqual(result["status"], "budget_exceeded")
        tool_results = [message for message in model.requests[-1]["messages"] if message["role"] == "tool"]
        self.assertEqual(len(tool_results), 6)
        self.assertEqual(json.loads(tool_results[-1]["content"])["untrusted_data"]["code"], "tool_budget_exceeded")

    async def test_tool_exception_is_returned_with_original_id_without_exception_body(self):
        async def broken(arguments, tools):
            raise RuntimeError("private@example.invalid secret-provider-payload")
        model = ScriptedModel([call("search_company", query="上下文公司"), {"content": "查询失败，不能核实"}])
        result = await run_loop(model, FakeTools("查询", handlers={"search_company": broken}), user_message="查询", mode="thinking")
        message = model.requests[-1]["messages"][-1]
        self.assertEqual(message["tool_call_id"], "stub_0_0")
        self.assertEqual(json.loads(message["content"])["untrusted_data"], {
            "status": "error", "code": "tool_exception", "error_type": "RuntimeError"})
        self.assertNotIn("secret-provider-payload", json.dumps(result))

    async def test_invalid_arguments_unknown_tool_and_insufficient_information(self):
        tools = FakeTools("查看")
        self.assertEqual((await tools.execute("unknown", {}))["code"], "unknown_tool")
        for arguments in ({}, {"source_id": 1}, {"source_id": "current", "text": "编造"}):
            self.assertEqual((await tools.execute("record_facts", arguments))["code"], "invalid_arguments")
        self.assertEqual((await tools.execute("write_draft", {}))["status"], "insufficient_information")
        self.assertEqual((await tools.execute("use_profile_items", {"item_ids": ["invented"]}))["status"], "error")

    async def test_malformed_json_returns_error_then_continues(self):
        model = AsyncMock()
        model.complete.side_effect = [ModelReply({"role": "assistant", "content": "", "tool_calls": [{
            "id": "bad-json", "type": "function", "function": {"name": "read_profile", "arguments": "{"},
        }]}), ModelReply({"role": "assistant", "content": "参数有误"})]
        result = await run_loop(model, FakeTools("查看"), user_message="查看")
        self.assertEqual(result["tools"][0]["result"]["code"], "invalid_arguments_or_result")
        self.assertEqual(result["model_calls"], 2)

    async def test_missing_reasoning_or_duplicate_ids_fail_closed(self):
        for message, expected in [
            ({"role": "assistant", "content": "done"}, "missing_reasoning_content"),
            ({"role": "assistant", "content": "", "reasoning_content": "synthetic", "tool_calls": [
                {"id": "duplicate", "function": {"name": "read_profile", "arguments": "{}"}},
                {"id": "duplicate", "function": {"name": "read_profile", "arguments": "{}"}},
            ]}, "invalid_tool_call_id"),
        ]:
            model = AsyncMock()
            model.complete.return_value = ModelReply(message)
            result = await run_loop(model, FakeTools("查看"), user_message="查看", mode="thinking")
            self.assertEqual(result["error"], expected)
            self.assertEqual(result["steps"], 0)

    async def test_contacts_redacted_in_history_state_tools_and_assistant_arguments(self):
        phone, email = "13800138000", "offline@example.invalid"
        state = {"facts": [f"电话：{phone}"], "draft": email}
        before = deepcopy(state)
        model = ScriptedModel([
            call("read_profile"), call("ask_user", question=f"邮箱 {email} 电话 {phone}"), {"content": "完成"},
        ])
        tools = FakeTools(f"电话 {phone}", state=state, results={"read_profile": {
            "status": "ok", "type": "image", "text": f"{email} {phone}", "nested": {"phone": "0755-12345678"},
        }})
        await run_loop(model, tools, user_message=f"电话 {phone}", history_summary=email, mode="thinking")
        for request in model.requests:
            text = json.dumps(request, ensure_ascii=False)
            for contact in (phone, email, "0755-12345678"):
                self.assertNotIn(contact, text)
        self.assertEqual(state, before)

    async def test_reasoning_contacts_never_sent_back_and_reasoning_not_logged(self):
        model = ScriptedModel([{**call("read_profile"), "reasoning_content": "电话13800138000"}, {"content": "不应执行"}])
        result = await run_loop(model, FakeTools("查看"), user_message="查看", mode="thinking")
        self.assertEqual(len(model.requests), 1)
        self.assertEqual(result["error"], "contacts_in_reasoning")
        self.assertNotIn("13800138000", json.dumps(result))
        self.assertNotIn("reasoning_content", result)

    async def test_injection_stays_data_and_external_material_cannot_be_recorded(self):
        case = json.loads(DEFAULT_CASES.read_text())["cases"][-1]
        text = case["user_message"]
        model = ScriptedModel([call("read_jd", source_id="current"), call("record_facts", source_id="current"), {"content": "不能写入"}])
        tools = FakeTools(text)
        result = await run_loop(model, tools, user_message=text, mode="thinking")
        for request in model.requests:
            system = [message for message in request["messages"] if message["role"] == "system"]
            self.assertEqual(system, [{"role": "system", "content": SYSTEM_PROMPT}])
            self.assertIn(text, json.loads(request["messages"][1]["content"])["user_message"])
        response = json.loads(model.requests[1]["messages"][-1]["content"])
        self.assertEqual(response["untrusted_data"]["text"], text)
        self.assertEqual(result["tools"][-1]["result"]["code"], "not_candidate_material")
        self.assertFalse(tools.state.get("facts"))
        # Also blocked before a read_jd call by the existing candidate-evidence filter.
        self.assertEqual((await FakeTools(text).execute("record_facts", {"source_id": "current"}))["status"], "error")

    async def test_real_adapters_delegate_to_existing_functions_without_persistence(self):
        decoder = AsyncMock(return_value={"jd_info": {"job_title": "岗位"}})
        extractor = AsyncMock(return_value={"items": [], "basic_info": {"objective": "实习"}})
        with patch("app.agents.decoder_chain.run_decoder_chain", decoder), patch("app.agents.fact_extractor.extract_facts_patch", extractor):
            llm = object()
            handlers = real_adapters(llm)
            tools = FakeTools("我的求职方向是实习", handlers=handlers)
            output = await tools.execute("record_facts", {"source_id": "current"})
            self.assertEqual(output["persistence"], "memory_only")
            self.assertEqual(tools.state["collected_info"]["basic_info"]["objective"], "实习")
            extractor.assert_awaited_once()
            await tools.execute("read_jd", {"source_id": "current"})
            decoder.assert_awaited_once_with("我的求职方向是实习", llm)

    async def test_stub_runner_reports_without_reading_config_or_creating_client(self):
        with tempfile.TemporaryDirectory(prefix="agent-spike-report-") as directory:
            args = argparse.Namespace(cases=DEFAULT_CASES, name="offline", output_root=Path(directory),
                                      mode="thinking", real=False, stub=True, timeout=2.0)
            with patch("run_agent_spike.real_config", side_effect=AssertionError("config read")), \
                    patch("openai.AsyncOpenAI", side_effect=AssertionError("network client")), redirect_stdout(io.StringIO()):
                code = await evaluate(args)
            report = json.loads((Path(directory) / "offline" / "report.json").read_text())
            markdown = (Path(directory) / "offline" / "report.md").read_text()
            self.assertEqual(code, 0)
            self.assertEqual(report["summary"]["matched"], 10)
            self.assertEqual(report["metadata"]["token_source"], "scripted_fixture")
            self.assertNotIn("13800138000", json.dumps(report))
            self.assertNotIn("reasoning_content", json.dumps(report))
            self.assertIn("不能评价模型", markdown)

    async def test_model_errors_are_recorded_and_missing_tokens_are_not_zero(self):
        model = AsyncMock()
        model.complete.side_effect = RuntimeError("provider secret")
        result = await run_loop(model, FakeTools("查看"), user_message="查看")
        self.assertEqual(result["status"], "model_error")
        self.assertEqual(result["error"], "RuntimeError")
        self.assertIsNone(result["usage"]["reasoning_tokens"])
        self.assertNotIn("provider secret", json.dumps(result))

    def test_history_checker_rejects_mismatched_ids(self):
        with self.assertRaises(SpikeProtocolError):
            validate_history([{"role": "tool", "content": "{}", "tool_call_id": "orphan"}], "off")

    def test_switch_matches_existing_endpoint_conventions(self):
        self.assertEqual(thinking_body("off", "https://api.deepseek.com"), {"thinking": {"type": "disabled"}})
        self.assertEqual(thinking_body("thinking", "https://api.deepseek.com"), {"thinking": {"type": "enabled"}})
        self.assertEqual(thinking_body("thinking", "https://dashscope.aliyuncs.com/compatible-mode/v1"), {"enable_thinking": True})

    async def test_actual_sdk_stream_serialization_both_modes_multistep(self):
        for mode in ("off", "thinking"):
            bodies = []

            def handle(request):
                body = json.loads(request.content)
                bodies.append(body)
                index = len(bodies) - 1
                frames = []

                def delta(value, finish=None):
                    frames.append({"id": "offline", "object": "chat.completion.chunk", "created": 1,
                                   "model": "deepseek-flash", "choices": [{"index": 0, "delta": value, "finish_reason": finish}]})

                if mode == "thinking":
                    delta({"reasoning_content": f"reason-{index}-"})
                    delta({"reasoning_content": "tail"})
                if index < 2:
                    name = "read_profile" if index == 0 else "use_profile_items"
                    arguments = "{}" if index == 0 else '{"item_ids":["p"]}'
                    delta({"tool_calls": [{"index": 0, "id": f"call-{index}", "type": "function", "function": {"name": name[:5], "arguments": arguments[:1]}}]})
                    delta({"tool_calls": [{"index": 0, "function": {"name": name[5:], "arguments": arguments[1:]}}]})
                    delta({}, "tool_calls")
                else:
                    delta({"content": "模拟结果"}, "stop")
                frames.append({"id": "offline", "object": "chat.completion.chunk", "created": 1,
                               "model": "deepseek-flash", "choices": [], "usage": {
                                   "prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18,
                                   "completion_tokens_details": {"reasoning_tokens": 3 if mode == "thinking" else 0},
                               }})
                data = "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames) + "data: [DONE]\n\n"
                return httpx.Response(200, content=data.encode(), headers={"Content-Type": "text/event-stream"})

            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
                async with AsyncOpenAI(api_key="offline-key", base_url="https://api.deepseek.com", http_client=transport, max_retries=0) as client:
                    result = await run_loop(OpenAIStreamModel(client, model="deepseek-flash"),
                                            FakeTools("查看", state={"profile_items": [{"id": "p", "facts": ["真实原文"]}]}),
                                            user_message="查看", mode=mode)
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(result["tool_sequence"], ["read_profile", "use_profile_items"])
            self.assertEqual(result["usage"], {"prompt_tokens": 33, "completion_tokens": 21, "reasoning_tokens": 9 if mode == "thinking" else 0})
            for body in bodies:
                self.assertEqual(body["thinking"]["type"], "enabled" if mode == "thinking" else "disabled")
                validate_history(body["messages"], mode)
            assistants = [message for message in bodies[-1]["messages"] if message["role"] == "assistant"]
            self.assertEqual([message["tool_calls"][0]["id"] for message in assistants], ["call-0", "call-1"])
            if mode == "thinking":
                self.assertEqual([message["reasoning_content"] for message in assistants], ["reason-0-tail", "reason-1-tail"])
            else:
                self.assertTrue(all("reasoning_content" not in message for message in assistants))


if __name__ == "__main__":
    unittest.main()
