"""Speed switches (B0-B3): off keeps old behaviour, on takes effect. Local doubles only."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from langchain_openai import ChatOpenAI  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.agents import resume_writer as writer  # noqa: E402
from app.agents.decoder_chain import _decoder_model  # noqa: E402
from app.agents.fact_extractor import extract_facts_patch  # noqa: E402
from app.schemas.writer import MatchPlan, OnePassOutput, WriterDraft  # noqa: E402
from app.services.llm_compat import without_thinking  # noqa: E402
from test_resume_writer import FakeModel, ROLE, draft, item, plan, run, source  # noqa: E402

WRITER = "app.agents.resume_writer.get_settings"


def settings(**flags):
    return SimpleNamespace(**flags)


def valid(**bullet_extra):
    bullet = {"text": "整理用户反馈并分类", "fact_ids": ["f3"], **bullet_extra}
    return {"match_plan": plan({"p2": "lead"}),
            "writer": draft([{**item("p2", "projects", []), "bullets": [bullet]}])}


class SchemaSpy:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.schemas = []
        self.calls = 0

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        return self.responses.pop(0)


def call(model, schema, state):
    return asyncio.run(writer._call(model, schema, {"evidence": "x"}, "contract", "other", retry_state=state))


class IgnoreExtraBulletFieldsTest(unittest.TestCase):
    def test_off_rejects_extra_and_records_field_names(self):
        bad = valid(**{"bad-name!": 1, "x" * 60: 2})
        model = SchemaSpy(bad, bad)
        state = {"schema_retry_count": 0}
        with patch(WRITER, return_value=settings(LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS=False)):
            with self.assertRaises(ValidationError):
                call(model, OnePassOutput, state)
        self.assertIs(model.schemas[0], OnePassOutput)
        self.assertEqual(model.calls, 2)
        self.assertEqual(state["extra_field_names"], ["badname", "x" * 40])
        self.assertNotIn("ignored_extra_fields", state)

    def test_on_drops_bullet_item_title_extras_in_one_call(self):
        response = valid(rationale="why", score=3)
        response["writer"]["items"][0]["note"] = "n"
        response["writer"]["items"][0]["title"] = {"name": "a", "tone": "b"}
        model = SchemaSpy(response)
        state = {"schema_retry_count": 0}
        with patch(WRITER, return_value=settings(LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS=True)):
            result = call(model, OnePassOutput, state)
        self.assertEqual(model.calls, 1)
        self.assertEqual(state["schema_retry_count"], 0)
        self.assertEqual(sorted(state["ignored_extra_fields"]), ["note", "rationale", "score", "tone"])
        self.assertEqual(result.writer.items[0].bullets[0].text, "整理用户反馈并分类")
        self.assertNotIn("rationale", json.dumps(result.model_dump()))
        # Tool definition is identical: same name, same JSON schema.
        sent = model.schemas[0]
        self.assertEqual(sent.__name__, "OnePassOutput")
        self.assertEqual(sent.model_json_schema(), OnePassOutput.model_json_schema())
        self.assertEqual(sent.model_json_schema()["$defs"]["WrittenBullet"]["additionalProperties"], False)
        self.assertEqual(WriterDraft.model_json_schema(), model.schemas[0].model_fields["writer"].annotation.model_json_schema())

    def test_on_upper_levels_also_lenient(self):
        top = valid()
        top["writer"]["stray"] = 1
        top["stray_top"] = 1
        plan_extra = valid()
        plan_extra["match_plan"]["capacity_note"] = 1
        for response, expected in ((top, ["stray", "stray_top"]), (plan_extra, ["capacity_note"])):
            model = SchemaSpy(response)
            state = {"schema_retry_count": 0}
            with patch(WRITER, return_value=settings(LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS=True)):
                result = call(model, OnePassOutput, state)
            self.assertEqual(model.calls, 1)
            self.assertEqual(sorted(state["ignored_extra_fields"]), expected)
            for name in expected:
                self.assertNotIn(name, json.dumps(result.model_dump()))
        model = SchemaSpy({**plan(), "questions_note": 1})
        state = {"schema_retry_count": 0}
        with patch(WRITER, return_value=settings(LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS=True)):
            call(model, MatchPlan, state)
        self.assertEqual(model.schemas[0].__name__, "MatchPlan")
        self.assertEqual(model.calls, 1)
        self.assertEqual(state["ignored_extra_fields"], ["questions_note"])

    def test_on_match_plan_array_elements_lenient(self):
        response = valid()
        mp = response["match_plan"]
        mp["experience_plan"][0]["target_bullets_note"] = "n"
        mp["requirements"] = [{"req_id": "r1", "status": "gap", "why-not": 1}]
        mp["questions"] = [{"q": "?", "improves": {"item_id": "p2", "zz": 1}, "extra_q": 1}]
        model = SchemaSpy(response)
        state = {"schema_retry_count": 0}
        with patch(WRITER, return_value=settings(LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS=True)):
            result = call(model, OnePassOutput, state)
        self.assertEqual(model.calls, 1)
        self.assertEqual(sorted(state["ignored_extra_fields"]),
                         ["extra_q", "target_bullets_note", "whynot", "zz"])
        self.assertNotIn("target_bullets_note", json.dumps(result.model_dump()))
        from app.schemas.writer import LENIENT_SCHEMAS
        for strict in (MatchPlan, OnePassOutput):
            self.assertEqual(LENIENT_SCHEMAS[strict].model_json_schema(), strict.model_json_schema())

    def test_on_standalone_match_plan_lenient(self):
        data = plan({"p2": "lead"})
        data["experience_plan"][0]["note"] = "n"
        model = SchemaSpy(data)
        with patch(WRITER, return_value=settings(LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS=True)):
            result = call(model, MatchPlan, {"schema_retry_count": 0})
        self.assertEqual(model.schemas[0].__name__, "MatchPlan")
        self.assertEqual(model.schemas[0].model_json_schema(), MatchPlan.model_json_schema())
        self.assertEqual(len(result.experience_plan), 1)

    def test_on_writer_draft_schema_also_lenient(self):
        model = SchemaSpy(valid(extra=1)["writer"])
        with patch(WRITER, return_value=settings(LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS=True)):
            result = call(model, WriterDraft, {"schema_retry_count": 0})
        self.assertEqual(model.schemas[0].__name__, "WriterDraft")
        self.assertEqual(model.schemas[0].model_json_schema(), WriterDraft.model_json_schema())
        self.assertEqual(len(result.items), 1)


def deepseek(model="deepseek-flash", base="https://api.deepseek.com"):
    return ChatOpenAI(model=model, api_key="unit-test", base_url=base, extra_body={"keep": 1})


class WithoutThinkingTest(unittest.TestCase):
    def test_deepseek_copy_disables_thinking_original_untouched(self):
        llm = deepseek()
        copy = without_thinking(llm)
        self.assertIsNot(copy, llm)
        self.assertEqual(copy.extra_body, {"keep": 1, "thinking": {"type": "disabled"}})
        self.assertEqual(llm.extra_body, {"keep": 1})

    def test_dashscope_uses_enable_thinking(self):
        llm = deepseek("deepseek-v4.1-flash", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(without_thinking(llm).extra_body, {"keep": 1, "enable_thinking": False})

    def test_non_deepseek_and_doubles_unchanged(self):
        other = deepseek("gpt-4o", "https://api.openai.com/v1")
        self.assertIs(without_thinking(other), other)
        double = object()
        self.assertIs(without_thinking(double), double)


class ExtractorThinkingTest(unittest.IsolatedAsyncioTestCase):
    async def run_extract(self, flag):
        seen = {}

        def spy(model, name):
            seen["model"], seen["name"] = model, name
            return SimpleNamespace(ainvoke=lambda messages: _reply())

        async def _reply():
            return SimpleNamespace(content=json.dumps({"items": []}))

        llm = deepseek()
        with patch("app.agents.fact_extractor.label_run", spy), \
                patch("app.config.get_settings", return_value=settings(LLM_EXTRACTOR_THINKING=flag)):
            await extract_facts_patch("我做了一个项目", {}, llm)
        return llm, seen

    async def test_default_true_keeps_model(self):
        llm, seen = await self.run_extract(True)
        self.assertIs(seen["model"], llm)
        self.assertEqual(seen["name"], "fact_extractor")

    async def test_false_disables_thinking_on_copy(self):
        llm, seen = await self.run_extract(False)
        self.assertEqual(seen["model"].extra_body["thinking"], {"type": "disabled"})
        self.assertNotIn("thinking", llm.extra_body)


class DecoderThinkingTest(unittest.TestCase):
    def test_label_and_switch(self):
        llm = deepseek()
        for flag, disabled in ((True, False), (False, True)):
            seen = {}
            with patch("app.agents.decoder_chain.label_run",
                       lambda model, name: seen.update(model=model, name=name) or model), \
                    patch("app.config.get_settings", return_value=settings(LLM_JD_DECODER_THINKING=flag)):
                _decoder_model(llm)
            self.assertEqual(seen["name"], "jd_decoder")
            self.assertEqual("thinking" in (seen["model"].extra_body or {}), disabled)
            self.assertNotIn("thinking", llm.extra_body)


class EditReusePlanTest(unittest.TestCase):
    PREVIOUS = plan({"p2": "lead"})
    CURRENT = {"projects": [{"item_id": "p2", "name": "数据项目", "polished_bullets": ["整理用户反馈并分类"]}]}

    def go(self, flag, *, current=None, meta=None, previous=None, first="WriterDraft"):
        response = draft([item("p2", "projects", [("整理用户反馈并分类", ["f3"])])])
        if first == "OnePassOutput":
            response = {"match_plan": self.PREVIOUS, "writer": response}
        model = FakeModel([(first, response)])
        with patch(WRITER, return_value=settings(LLM_WRITER_EDIT_REUSE_PLAN=flag)):
            result = run(source(), ROLE, model, current_data=current, resume_meta=meta or {},
                         previous_plan=previous)
        return model, result

    def test_reuses_plan_from_meta_and_only_asks_for_writer_draft(self):
        model, result = self.go(True, current=deepcopy(self.CURRENT), meta={"match_plan": self.PREVIOUS})
        self.assertEqual([name for name, _ in model.calls], ["WriterDraft", "RepairOutput"])
        sent = json.dumps([m.content for m in model.calls[0][1]], ensure_ascii=False)
        self.assertIn('\\"match_plan\\"', sent)
        self.assertEqual(result["writer_diagnostic"]["status"], "model_completed")
        self.assertTrue(result["writer_diagnostic"]["plan_reused"])
        self.assertEqual({row["item_id"]: row["treatment"] for row in result["match_plan"]["experience_plan"]}["p2"], "lead")

    def test_explicit_previous_plan_param(self):
        model, _ = self.go(True, current=deepcopy(self.CURRENT), previous=self.PREVIOUS)
        self.assertEqual([name for name, _ in model.calls], ["WriterDraft", "RepairOutput"])

    def test_off_keeps_one_pass(self):
        model, result = self.go(False, current=deepcopy(self.CURRENT), meta={"match_plan": self.PREVIOUS},
                                first="OnePassOutput")
        self.assertEqual([name for name, _ in model.calls], ["OnePassOutput", "RepairOutput"])
        self.assertNotIn("plan_reused", result["writer_diagnostic"])

    def test_without_previous_plan_falls_back_to_one_pass(self):
        for meta in ({}, {"match_plan": {}}):
            model, _ = self.go(True, current=deepcopy(self.CURRENT), meta=meta, first="OnePassOutput")
            self.assertEqual([name for name, _ in model.calls], ["OnePassOutput", "RepairOutput"])

    def test_invalid_previous_plan_falls_back_to_one_pass(self):
        model, _ = self.go(True, current=deepcopy(self.CURRENT), meta={"match_plan": {"requirements": "bad"}},
                           first="OnePassOutput")
        self.assertEqual([name for name, _ in model.calls], ["OnePassOutput", "RepairOutput"])

    def test_first_draft_without_body_always_one_pass(self):
        for current in (None, {"projects": [{"item_id": "p2", "polished_bullets": []}]}):
            model, _ = self.go(True, current=current, meta={"match_plan": self.PREVIOUS}, first="OnePassOutput")
            self.assertEqual([name for name, _ in model.calls], ["OnePassOutput", "RepairOutput"])

    def test_two_pass_mode_unaffected(self):
        planner = FakeModel([("MatchPlan", self.PREVIOUS)])
        wr = FakeModel([("WriterDraft", draft([item("p2", "projects", [("整理用户反馈并分类", ["f3"])])]))])
        with patch(WRITER, return_value=settings(LLM_WRITER_EDIT_REUSE_PLAN=True)):
            run(source(), ROLE, wr, structured_llm=planner, mode="two_pass", current_data=deepcopy(self.CURRENT),
                resume_meta={"match_plan": self.PREVIOUS})
        self.assertEqual([n for n, _ in planner.calls], ["MatchPlan"])


class SettingsDefaultsTest(unittest.TestCase):
    def test_defaults_keep_current_behaviour(self):
        from app.config import Settings
        s = Settings(_env_file=None)
        self.assertTrue(s.LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS)
        self.assertFalse(s.LLM_EXTRACTOR_THINKING)
        self.assertFalse(s.LLM_WRITER_EDIT_REUSE_PLAN)
        self.assertFalse(s.LLM_JD_DECODER_THINKING)


if __name__ == "__main__":
    unittest.main()
