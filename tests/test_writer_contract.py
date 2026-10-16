"""Writer schema and fail-closed diagnostics use only local model doubles."""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from langchain_core.messages import AIMessage
from langchain_core.output_parsers.openai_tools import PydanticToolsParser
from langchain_core.outputs import ChatGeneration
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_ROOT = ROOT if (ROOT / "backend/app/schemas/writer.py").exists() else Path.cwd()
sys.path.insert(0, str(DEPENDENCY_ROOT / "backend"))

from app.schemas.writer import OnePassOutput  # noqa: E402
from app.services.error_codes import ChatTurnError  # noqa: E402

SPEC = importlib.util.spec_from_file_location("resume_writer_schema_retry", ROOT / "backend/app/agents/resume_writer.py")
assert SPEC and SPEC.loader
writer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(writer)
_call = writer._call
_ONE_PASS_CONTRACT = writer._ONE_PASS_CONTRACT
run_resume_writer = writer.run_resume_writer


class ParserThenValidModel:
    """Exercise the installed LangChain parser without any provider call."""

    def __init__(self, kind: str, *, always_bad: bool = False):
        self.kind = kind
        self.always_bad = always_bad
        self.calls = []
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if len(self.calls) > 1 and not self.always_bad:
            return {"match_plan": PLAN, "writer": DRAFT}
        if self.kind == "args_list":
            message = AIMessage.model_construct(content="", additional_kwargs={}, tool_calls=[
                {"name": self.schema.__name__, "args": [], "id": "call-1", "type": "tool_call"}])
        else:
            message = AIMessage.model_construct(content="", tool_calls=[], additional_kwargs={
                "tool_calls": [{"id": "call-1", "type": "function", "function": {
                    "name": self.schema.__name__, "arguments": '"PRIVATE_STRING_ARGS"'}}]})
        parser = PydanticToolsParser(tools=[self.schema], first_tool_only=True)
        return parser.parse_result([ChatGeneration(message=message)])


SOURCE_TEXT = "制作了页面拆分本地原型，尚未上线。"
TEXT = PRINTED = "制作了页面拆分本地原型"  # 「尚未上线」只是限制，不入稿
SOURCE = {"projects": [{"item_id": "synthetic-paper", "name": "纸页工具",
                        "facts": [{"id": "synthetic-fact-1", "kind": "status_limit",
                                   "text": SOURCE_TEXT, "source_quote": SOURCE_TEXT, "status": "active",
                                   "source": "chat"}]}]}
PLAN = {"requirements": [], "experience_plan": [{"item_id": "synthetic-paper",
                                                "treatment": "keep"}]}
DRAFT = {"items": [{"item_id": "synthetic-paper", "section": "projects",
                    "bullets": [{"text": TEXT, "fact_ids": ["synthetic-fact-1"]}]}]}


class FakeModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        self.calls.append((self.schema.__name__, messages))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class WriterContractTest(unittest.TestCase):
    def test_one_pass_contract_names_one_top_level_schema(self):
        self.assertIn("OnePassOutput", _ONE_PASS_CONTRACT)
        self.assertIn('"match_plan"', _ONE_PASS_CONTRACT)
        self.assertIn('"writer"', _ONE_PASS_CONTRACT)
        model = FakeModel({"match_plan": PLAN, "writer": DRAFT})
        parsed = asyncio.run(_call(model, OnePassOutput, {}, _ONE_PASS_CONTRACT, "other"))
        self.assertEqual(parsed.writer.items[0].bullets[0].text, TEXT)
        self.assertEqual(model.calls[0][0], "OnePassOutput")
        self.assertIn("不要只输出 MatchPlan 或 WriterDraft", model.calls[0][1][0].content)

    def test_missing_nested_writer_is_schema_failure_not_success(self):
        model = FakeModel({"match_plan": PLAN})
        with self.assertRaises(ValidationError):
            asyncio.run(_call(model, OnePassOutput, {}, _ONE_PASS_CONTRACT, "other"))
        model = FakeModel({"match_plan": PLAN}, {"match_plan": PLAN})
        with self.assertRaises(ChatTurnError) as caught:
            asyncio.run(run_resume_writer(SOURCE, {}, model))
        self.assertEqual(caught.exception.code, 'E-MODEL-UPSTREAM')
        self.assertEqual(caught.exception.error_type, 'ValidationError')
        self.assertEqual(len(model.calls), 2)

    def test_secondary_validation_paths_never_expose_unexpected_keys_or_values(self):
        invalid = {"match_plan": PLAN, "writer": {"items": [{
            "item_id": "synthetic-paper", "section": "projects", "bullets": [{
                "fact_ids": ["synthetic-fact-1"], "PRIVATE_KEY_SECRET": "PRIVATE_VALUE_SECRET"}]}]}}
        model = FakeModel(invalid, invalid)
        with mock.patch.object(writer, "get_settings",
                        return_value=SimpleNamespace(LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS=False)):
            result = asyncio.run(run_resume_writer(SOURCE, {}, model, primary_call=False))
        diagnostic = result["writer_diagnostic"]
        self.assertEqual(diagnostic["status"], "model_fallback")
        self.assertEqual(diagnostic["error_type"], "ValidationError")
        self.assertIn({"loc": ["writer", "items", 0, "bullets", 0, "text"], "type": "missing"},
                      diagnostic["validation_errors"])
        self.assertIn({"loc": ["writer", "items", 0, "bullets", 0, "<extra>"],
                       "type": "extra_forbidden"}, diagnostic["validation_errors"])
        # Only the (sanitized) key name is diagnostic; values and paths stay hidden.
        self.assertEqual(diagnostic["extra_field_names"], ["PRIVATE_KEY_SECRET"])
        self.assertNotIn("PRIVATE_VALUE_SECRET", json.dumps(diagnostic))
        self.assertNotIn("SECRET", json.dumps(diagnostic["validation_errors"]))
        self.assertEqual(diagnostic["schema_retry_count"], 1)
        self.assertNotIn("PRIVATE_KEY_SECRET", str(model.calls[1][1]))
        self.assertNotIn("PRIVATE_VALUE_SECRET", str(model.calls[1][1]))

    def test_provider_error_message_cannot_enter_public_error(self):
        model = FakeModel(*[RuntimeError("SECRET_PROVIDER_TEXT and original prompt")] * 2)
        with self.assertRaises(ChatTurnError) as caught:
            asyncio.run(run_resume_writer(SOURCE, {}, model))
        self.assertEqual(caught.exception.code, 'E-MODEL-UPSTREAM')
        self.assertEqual(caught.exception.error_type, 'RuntimeError')
        self.assertEqual(len(model.calls), 2)
        self.assertNotIn('SECRET_PROVIDER_TEXT', str(caught.exception))
        self.assertNotIn('original prompt', str(caught.exception))

    def test_value_error_retries_without_schema_feedback(self):
        model = FakeModel(*[ValueError("SECRET_INVALID_PROVIDER_RESPONSE")] * 2)
        with self.assertRaises(ChatTurnError) as caught:
            asyncio.run(run_resume_writer(SOURCE, {}, model))
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(caught.exception.error_type, 'ValueError')
        self.assertEqual(model.calls[0][1], model.calls[1][1])
        self.assertNotIn('SECRET', str(caught.exception))

    def test_actual_langchain_parser_non_object_args_get_one_safe_retry(self):
        for kind in ("args_list", "json_string"):
            with self.subTest(kind=kind):
                model = ParserThenValidModel(kind)
                result = asyncio.run(run_resume_writer(SOURCE, {}, model))
                diagnostic = result["writer_diagnostic"]
                self.assertEqual(diagnostic["status"], "model_completed")
                self.assertEqual(diagnostic["schema_retry_count"], 1)
                self.assertEqual(diagnostic["schema_retry_reason_code"], "tool_arguments_not_object")
                self.assertEqual(len(model.calls), 2)
                self.assertIn('"reason_code": "tool_arguments_not_object"', model.calls[1][-1].content)
                self.assertNotIn("PRIVATE_STRING_ARGS", model.calls[1][-1].content)
                self.assertNotIn("PRIVATE_STRING_ARGS", json.dumps(diagnostic))

    def test_spoofed_parser_message_is_not_schema_feedback(self):
        model = FakeModel(*[ValueError("Tool arguments must be specified as a dict, received: PRIVATE_ARGS")] * 2)
        with self.assertRaises(ChatTurnError) as caught:
            asyncio.run(run_resume_writer(SOURCE, {}, model))
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(caught.exception.error_type, 'ValueError')
        self.assertEqual(model.calls[0][1], model.calls[1][1])
        self.assertNotIn('PRIVATE_ARGS', str(caught.exception))

    def test_second_parser_shape_error_is_retryable_turn_error(self):
        model = ParserThenValidModel("json_string", always_bad=True)
        with self.assertRaises(ChatTurnError) as caught:
            asyncio.run(run_resume_writer(SOURCE, {}, model))
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(caught.exception.code, 'E-MODEL-UPSTREAM')
        self.assertEqual(caught.exception.error_type, 'ValueError')
        self.assertIn('"reason_code": "tool_arguments_not_object"', model.calls[1][-1].content)
        self.assertNotIn('PRIVATE_STRING_ARGS', str(caught.exception))

    def test_missing_output_object_retries_once_with_fixed_reason(self):
        model = FakeModel(None, {"match_plan": PLAN, "writer": DRAFT})
        result = asyncio.run(run_resume_writer(SOURCE, {}, model))
        diagnostic = result["writer_diagnostic"]
        self.assertEqual(diagnostic["status"], "model_completed")
        self.assertEqual(diagnostic["schema_retry_count"], 1)
        self.assertEqual(diagnostic["schema_retry_reason_code"], "object_missing")
        self.assertEqual(len(model.calls), 2)
        self.assertIn('"reason_code": "object_missing"', model.calls[1][1][-1].content)

    def test_bad_local_json_retries_without_echoing_response(self):
        model = FakeModel(SimpleNamespace(content="{INVALID_JSON_PRIVATE_VALUE"),
                          {"match_plan": PLAN, "writer": DRAFT})
        result = asyncio.run(run_resume_writer(SOURCE, {}, model))
        diagnostic = result["writer_diagnostic"]
        self.assertEqual(diagnostic["status"], "model_completed")
        self.assertEqual(diagnostic["schema_retry_count"], 1)
        self.assertEqual(diagnostic["schema_retry_reason_code"], "invalid_json")
        self.assertNotIn("PRIVATE_VALUE", json.dumps(diagnostic))
        self.assertNotIn("PRIVATE_VALUE", str(model.calls[1][1]))

    def test_second_empty_or_non_object_output_is_retryable_error(self):
        from copy import deepcopy
        for value in (None, ["non-object response"], AIMessage(content='')):
            with self.subTest(value=value):
                model = FakeModel(value, value)
                previous = {'projects': [{'item_id': 'synthetic-paper', 'polished_bullets': ['用户保存的旧稿']}]}
                before = deepcopy(previous)
                with self.assertRaises(ChatTurnError) as caught:
                    asyncio.run(run_resume_writer(SOURCE, {}, model, current_data=previous))
                self.assertEqual(caught.exception.code, 'E-MODEL-UPSTREAM')
                self.assertIn('重试', str(caught.exception))
                self.assertEqual(len(model.calls), 2)
                self.assertEqual(previous, before)

    def test_schema_valid_empty_writer_is_still_an_observable_fallback(self):
        result = asyncio.run(run_resume_writer(SOURCE, {}, FakeModel({
            "match_plan": PLAN, "writer": {"items": []}})))
        self.assertEqual(result["writer_diagnostic"], {
            "status": "model_fallback", "mode": "one_pass",
            "schema_retry_count": 0,
            "stage": "write", "error_type": "EmptyWriterDraft"})
        self.assertEqual(result["resume_data"]["projects"][0]["polished_bullets"], [PRINTED])

    def test_two_pass_failure_is_retryable_and_never_publishes_fallback(self):
        for planner, main, stage in (
            (FakeModel(*[RuntimeError("plan secret")] * 2), FakeModel(), "plan"),
            (FakeModel(PLAN), FakeModel(*[RuntimeError("writer secret")] * 2), "write"),
        ):
            with self.subTest(stage=stage), self.assertRaises(ChatTurnError) as caught:
                asyncio.run(run_resume_writer(SOURCE, {}, main, structured_llm=planner, mode="two_pass"))
            self.assertEqual(caught.exception.code, 'E-MODEL-UPSTREAM')
            self.assertEqual(caught.exception.error_type, 'RuntimeError')
            self.assertEqual(len(planner.calls), 2 if stage == 'plan' else 1)
            self.assertEqual(len(main.calls), 0 if stage == 'plan' else 2)

    def test_valid_one_pass_is_distinct_from_fallback(self):
        result = asyncio.run(run_resume_writer(SOURCE, {},
                                               FakeModel({"match_plan": PLAN, "writer": DRAFT})))
        self.assertEqual(result["writer_diagnostic"], {"status": "model_completed", "mode": "one_pass",
                                                       "schema_retry_count": 0})
        self.assertEqual(result["resume_data"]["projects"][0]["polished_bullets"], [PRINTED])

    def test_validation_retry_succeeds_with_same_evidence_and_safe_feedback(self):
        model = FakeModel({"match_plan": PLAN}, {"match_plan": PLAN, "writer": DRAFT})
        result = asyncio.run(run_resume_writer(SOURCE, {}, model))
        diagnostic = result["writer_diagnostic"]
        self.assertEqual(diagnostic["status"], "model_completed")
        self.assertEqual(diagnostic["schema_retry_count"], 1)
        self.assertEqual(len(model.calls), 2)
        first, second = model.calls[0][1], model.calls[1][1]
        self.assertEqual(first, second[:len(first)])
        self.assertIn('"loc": ["writer"]', second[-1].content)
        self.assertIn('"type": "missing"', second[-1].content)
        self.assertNotIn(TEXT, second[-1].content)

    def test_two_pass_primary_write_gets_its_own_single_retry(self):
        planner = FakeModel({"experience_plan": "bad"}, PLAN)
        draft_model = FakeModel({"items": "bad"}, DRAFT)
        result = asyncio.run(run_resume_writer(SOURCE, {}, draft_model,
                                               structured_llm=planner, mode="two_pass"))
        self.assertEqual(result['writer_diagnostic']['status'], 'model_completed')
        self.assertEqual(len(planner.calls), 2)
        self.assertEqual(len(draft_model.calls), 2)

    def test_validation_retry_shares_one_timeout(self):
        class SlowModel(FakeModel):
            async def ainvoke(self, messages):
                await asyncio.sleep(0.035)
                return await super().ainvoke(messages)

        model = SlowModel({"match_plan": PLAN}, {"match_plan": PLAN, "writer": DRAFT})
        state = {"schema_retry_count": 0}
        started = time.monotonic()
        with mock.patch.object(writer, "WRITER_TIMEOUT_SECONDS", 0.055):
            with self.assertRaises(TimeoutError):
                asyncio.run(_call(model, OnePassOutput, {}, _ONE_PASS_CONTRACT, "other",
                                  retry_state=state))
        self.assertLess(time.monotonic() - started, 0.085)
        self.assertEqual(state["schema_retry_count"], 1)


if __name__ == "__main__":
    unittest.main()
