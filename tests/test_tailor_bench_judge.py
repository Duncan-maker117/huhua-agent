"""Offline evaluation invariants; no application imports, stores or providers."""

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tailor_bench_judge", ROOT / "evaluation/tailor-bench/judge.py")
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)


def resume(text):
    return {"projects": [{"polished_bullets": [text]}]}


class FakeLLM:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    async def ainvoke(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if isinstance(self.answer, Exception):
            raise self.answer
        result = self.answer(messages) if callable(self.answer) else self.answer
        return SimpleNamespace(content=json.dumps(result, ensure_ascii=False),
                               usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})


class JudgeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.case = {"id": "test", "jd_text": "岗位需要服务100万用户并上线生产环境。",
                     "opening_turns": ["我整理反馈，做了原型但未上线。"],
                     "truth_facts": ["我整理反馈，做了原型但未上线。", "团队3人，测试30个例子。"],
                     "forbidden": {"numbers": [], "claims": ["上线", "主导", "Java"]},
                     "must_cover": ["r1 整理反馈"]}

    def answer(self):
        return {"audits": [{"unit_id": "u001", "verdict": "supported",
                             "observed_quotes": ["我整理反馈"], "truth_quotes": ["我整理反馈"],
                             "unsupported_spans": [], "reason": "对应本人动作。"}],
                "quality": {key: 3 for key in judge.QUALITY_DIMENSIONS},
                "coverage": [{"requirement": "r1 整理反馈", "covered": True,
                              "evidence": [{"unit_id": "u001", "quote": "整理反馈"}]}]}

    def test_negated_and_planned_claims_are_not_affirmative_matches(self):
        for text in ("做了原型但未上线。", "我没有主导，项目尚未正式上线。", "计划上线，用户量未知。"):
            with self.subTest(text=text):
                out = judge.deterministic_score(self.case, resume(text))
                self.assertFalse(out["flags"])
        out = judge.deterministic_score(self.case, resume("项目上线，我主导开发。"))
        self.assertEqual({row["span"] for row in out["flags"]}, {"上线", "主导"})

    def test_ascii_forbidden_boundaries(self):
        self.assertFalse(judge.deterministic_score(self.case, resume("使用JavaScript整理反馈。"))["flags"])
        self.assertTrue(judge.deterministic_score(self.case, resume("使用Java整理反馈。"))["flags"])

    def test_only_displayed_candidate_content_is_scanned(self):
        data = resume("整理反馈。")
        data.update({"resume_strategy": {"requirements": ["上线999999次"]},
                     "metadata": {"id": 9909}, "version_id": "2026-v4"})
        data["projects"][0].update({"item_id": "project9999", "description": "隐藏原材料有99人。"})
        data["projects"].append({"hidden": True, "description": "上线8888次。"})
        out = judge.deterministic_score(self.case, data)
        self.assertEqual(out["candidate_unit_count"], 1)
        self.assertFalse(out["flags"])
        self.assertEqual(judge.candidate_units({"sections": [], "projects": data["projects"]}), [])

    def test_jd_numeric_claim_does_not_become_candidate_evidence(self):
        out = judge.deterministic_score(self.case, resume("服务100万用户。"))
        self.assertIn("number_not_in_truth", {row["kind"] for row in out["flags"]})
        self.assertTrue(all(row["review_status"] == "pending" for row in out["flags"]))
        self.assertIsNone(out["confirmed_fabrications"])

    def test_chinese_and_decimal_percent_equivalence(self):
        facts = ["整理了一万五千条记录，完成百分之一百五十。"]
        case = {"truth_facts": facts, "opening_turns": facts}
        out = judge.deterministic_score(case, resume("整理15000条记录，完成150%。"))
        self.assertFalse(out["flags"])
        self.assertEqual(judge._normal_number("1.5"), judge._normal_number("150%"))
        self.assertEqual(judge._normal_number("一百零五"), judge._normal_number("105"))
        self.assertEqual(judge._normal_number("三点五"), judge._normal_number("3.5"))

    def test_matching_number_in_wrong_context_is_suspicious(self):
        out = judge.deterministic_score(self.case, resume("团队30人。"), self.case["truth_facts"])
        self.assertEqual([row["kind"] for row in out["flags"]], ["number_context_mismatch"])
        out = judge.deterministic_score(self.case, resume("性能提升30%。"), self.case["truth_facts"])
        self.assertIn("number_not_in_truth", {row["kind"] for row in out["flags"]})

    def test_dates_tool_versions_and_undisclosed_numbers_remain_review_candidates(self):
        out = judge.deterministic_score(self.case, resume("2026年使用Vue3。"))
        self.assertIn("number_not_in_truth", {row["kind"] for row in out["flags"]})
        self.assertIn("number_not_disclosed", {row["kind"] for row in out["flags"]})
        self.assertIsNone(out["safe"])
        self.assertIsNone(out["confirmed_fabrications"])
        disclosed = judge.deterministic_score(self.case, resume("使用Vue3。"), self.case["truth_facts"])
        self.assertEqual([row["kind"] for row in disclosed["flags"]], ["number_context_mismatch"])

    async def test_no_draft_or_no_model_never_counts_safe(self):
        empty = await judge.judge_version(self.case, {}, FakeLLM(self.answer()))
        missing = await judge.judge_version(self.case, resume("整理反馈。"), None)
        self.assertEqual(empty["status"], "no_draft")
        self.assertEqual(missing["status"], "not_run")
        for result in (empty, missing):
            self.assertIsNone(result["factuality"]["safe"])
            self.assertIsNone(result["quality"])

    async def test_valid_judgment_has_verifiable_coverage_and_blind_payload(self):
        model = FakeLLM(self.answer())
        data = resume("整理反馈。")
        data.update({"version_label": "baseline-first", "change_summary": ["因为这个写法最好"]})
        out = await judge.judge_version(self.case, data, model)
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["coverage"]["ratio"], 1)
        self.assertIsNone(out["factuality"]["safe"])
        payload = json.loads(model.calls[0][0][1].content)
        self.assertNotIn("baseline-first", json.dumps(payload))
        self.assertNotIn("change_summary", json.dumps(payload))
        self.assertEqual(payload["observed_facts"], self.case["opening_turns"])
        self.assertEqual(model.calls[0][1]["response_format"], {"type": "json_object"})

    async def test_invented_evidence_or_incomplete_schema_fails_closed(self):
        variants = []
        ungrounded = self.answer()
        ungrounded["audits"][0]["observed_quotes"] = ["我完成生产上线"]
        variants.append(ungrounded)
        coverage = self.answer()
        coverage["coverage"][0]["evidence"][0]["quote"] = "并不存在的正文"
        variants.append(coverage)
        incomplete = self.answer()
        incomplete["audits"] = []
        variants.append(incomplete)
        unlocated_unsupported = self.answer()
        unlocated_unsupported["audits"][0]["verdict"] = "unsupported"
        variants.append(unlocated_unsupported)
        score = self.answer()
        score["quality"]["jd_relevance"] = True
        variants.append(score)
        for value in variants:
            with self.subTest(value=value):
                out = await judge.judge_version(self.case, resume("整理反馈。"), FakeLLM(value))
                self.assertEqual(out["status"], "error")
                self.assertEqual(out["error_type"], "JudgeSchemaError")
                self.assertTrue(out["validation_error"])
                self.assertEqual(out["unvalidated_result"], value)
                self.assertIsNone(out["factuality"]["safe"])
                self.assertIsNone(out["coverage"])

    async def test_truth_only_remains_suspicion_and_is_not_coverage(self):
        answer = self.answer()
        answer["audits"][0].update(verdict="truth_only", observed_quotes=[],
                                  truth_quotes=["团队3人"], reason="仅完整truth出现，尚未披露。")
        answer["coverage"][0]["evidence"][0]["quote"] = "团队3人"
        out = await judge.judge_version(self.case, resume("团队3人。"), FakeLLM(answer))
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["coverage"]["ratio"], 0)
        self.assertEqual(out["factuality"]["suspicions"][0]["quote"], "团队3人。")
        self.assertEqual(out["factuality"]["suspicions"][0]["verdict"], "truth_only")

    async def test_uncertain_generic_title_uses_known_unit_as_location_without_passing_safety(self):
        answer = self.answer()
        answer["audits"].insert(0, {"unit_id": "u000", "verdict": "uncertain",
                                    "observed_quotes": [], "truth_quotes": [], "unsupported_spans": [],
                                    "reason": "泛标题缺少具体事实，需人工核对。"})
        answer["audits"][0]["unit_id"] = "u001"
        answer["audits"][1]["unit_id"] = "u002"
        answer["coverage"][0]["evidence"][0]["unit_id"] = "u002"
        data = resume("整理反馈。")
        data["projects"][0]["name"] = "对话中描述的经历"
        out = await judge.judge_version(self.case, data, FakeLLM(answer))
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["quality"], answer["quality"])
        self.assertEqual(out["coverage"]["ratio"], 1)
        suspicion = out["factuality"]["suspicions"][0]
        self.assertEqual(suspicion["verdict"], "uncertain")
        self.assertEqual(suspicion["unsupported_spans"], ["对话中描述的经历"])
        self.assertEqual(suspicion["location_fallback"], "whole_unit_for_uncertain")
        self.assertIsNone(out["factuality"]["safe"])
        self.assertIsNone(out["factuality"]["confirmed_fabrications"])

    async def test_provider_error_text_is_never_persisted(self):
        out = await judge.judge_version(self.case, resume("整理反馈。"), FakeLLM(RuntimeError("Authorization Bearer secret-value")))
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error_type"], "RuntimeError")
        self.assertNotIn("secret-value", json.dumps(out))
        self.assertNotIn("validation_error", out)
        self.assertNotIn("unvalidated_result", out)

    async def test_unparsed_response_excludes_raw_response_and_error_text(self):
        class MalformedLLM:
            async def ainvoke(self, messages, **kwargs):
                return SimpleNamespace(content="provider diagnostic secret-value", usage_metadata={})
        out = await judge.judge_version(self.case, resume("整理反馈。"), MalformedLLM())
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error_type"], "JudgeSchemaError")
        self.assertNotIn("secret-value", json.dumps(out))
        self.assertNotIn("validation_error", out)
        self.assertNotIn("unvalidated_result", out)

    async def test_edit_checks_visible_diff_and_grounded_instruction_evidence(self):
        before = resume("整理反馈。")
        after = copy.deepcopy(before)
        after["metadata"] = {"revision": "new"}
        out = await judge.judge_edit(self.case, before, after, "改进表述", None)
        self.assertFalse(out["executed"])
        self.assertFalse(out["substantive_diff"])
        model = FakeLLM({"followed": True, "reason": "压缩句子。",
                         "evidence": [{"before_quote": "整理反馈。", "after_quote": "反馈整理。"}]})
        out = await judge.judge_edit(self.case, before, resume("反馈整理。"), "改进表述", model)
        self.assertTrue(out["executed"])
        model.answer["evidence"][0]["after_quote"] = "虚构证据"
        out = await judge.judge_edit(self.case, before, resume("反馈整理。"), "改进表述", model)
        self.assertEqual(out["status"], "error")
        self.assertIsNone(out["executed"])
        self.assertEqual(out["validation_error"], "ungrounded evidence quote")
        self.assertEqual(out["unvalidated_result"], model.answer)

    async def test_whitespace_or_punctuation_edit_is_not_substantive(self):
        out = await judge.judge_edit(self.case, resume("整理反馈。"), resume("整理 反馈！"), "更突出经验", None)
        self.assertFalse(out["substantive_diff"])
        self.assertFalse(out["executed"])

    async def test_pairwise_randomized_swap_maps_back_to_original_draft(self):
        def pick_good(messages):
            payload = json.loads(messages[1].content)
            return {"winner": "A" if payload["A"][0]["text"] == "好稿" else "B", "reason": "真实证据更清楚。"}
        model = FakeLLM(pick_good)
        out = await judge.pairwise(self.case, resume("好稿"), resume("另一稿"), model, seed=8)
        self.assertEqual(out["winner"], "a")
        self.assertTrue(out["consistent"])
        self.assertEqual(out["rounds"][0]["order"], list(reversed(out["rounds"][1]["order"])))
        first = json.loads(model.calls[0][0][1].content)
        second = json.loads(model.calls[1][0][1].content)
        self.assertEqual(first["A"], second["B"])
        self.assertEqual(first["B"], second["A"])
        self.assertNotIn("baseline", json.dumps(first))

    async def test_pairwise_position_bias_is_inconclusive(self):
        out = await judge.pairwise(self.case, resume("a"), resume("b"), FakeLLM({"winner": "A", "reason": "只选左边。"}))
        self.assertEqual(out["winner"], "inconclusive")
        self.assertFalse(out["consistent"])

    async def test_pairwise_schema_failure_retains_only_unvalidated_score_object(self):
        answer = {"winner": "first", "reason": "测试不符合枚举的响应"}
        out = await judge.pairwise(self.case, resume("a"), resume("b"), FakeLLM(answer))
        self.assertEqual(out["status"], "error")
        self.assertIsNone(out["winner"])
        for row in out["rounds"]:
            self.assertEqual(row["validation_error"], "invalid pairwise winner")
            self.assertEqual(row["unvalidated_result"], answer)


if __name__ == "__main__":
    unittest.main()
