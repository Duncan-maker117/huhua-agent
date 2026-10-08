"""Regression checks for benchmark evidence, not for the legacy writing policy."""
import importlib.util
import json
from types import SimpleNamespace
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import AsyncMock, patch

HERE = Path(__file__).resolve().parents[1] / "evaluation" / "tailor-bench"
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("tailor_bench_runner", HERE / "run_bench.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from simulate_user import answer_question, select_answer, render_fact, validate_case  # noqa: E402


class VersionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.recorder = runner.VersionRecorder()
        self.data = {"projects": [{"name": "合成项目", "description": "仅完成 Demo。"}]}

    def record(self, data, turn=1, kind="internal"):
        return self.recorder.record(data, turn=turn, stage="EVALUATING", kind=kind,
                                    observed=["仅完成 Demo。"])

    def test_checkpoint_becomes_visible_only_on_matching_commit(self):
        record = self.record(self.data)
        self.assertFalse(record["user_visible"])
        self.assertIs(record, self.record(self.data, kind="committed"))
        self.assertEqual(len(self.recorder.versions), 1)
        self.assertTrue(record["user_visible"])

    def test_failed_internal_change_is_not_visible(self):
        self.record(self.data)
        self.record({}, kind="committed")
        self.assertFalse(self.recorder.versions[0]["user_visible"])

    def test_later_reversion_is_a_version_not_global_deduplication(self):
        self.record(self.data, kind="committed")
        self.record({"projects": []}, turn=2, kind="committed")
        self.record(self.data, turn=3, kind="committed")
        self.assertEqual(len(self.recorder.versions), 3)
        self.assertEqual(self.recorder.versions[0]["hash"], self.recorder.versions[2]["hash"])

    def test_input_mutation_does_not_change_previous_version(self):
        self.record(self.data)
        self.data["projects"][0]["description"] = "changed"
        self.assertEqual(self.recorder.versions[0]["resume_data"]["projects"][0]["description"], "仅完成 Demo。")

    def test_same_text_stage_transition_still_records_draft_event(self):
        for turn, stage in [(1, "COLLECTING"), (2, "EVALUATING")]:
            self.recorder.record(self.data, turn=turn, stage=stage, kind="committed", observed=[])
        self.assertEqual(len(self.recorder.versions), 1)
        self.assertEqual(self.recorder.commits[-1]["stage"], "EVALUATING")
        self.assertEqual(self.recorder.commits[-1]["turn"], 2)

    def test_missing_usage_not_zero_cost_or_no_calls(self):
        totals = runner.usage_total([{"status": "error"}, {"usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}}])
        self.assertEqual(totals["logical_model_calls"], 2)
        self.assertEqual(totals["calls_without_usage"], 1)
        self.assertIsNone(totals["cost"])
        self.assertIsNone(totals["sdk_http_attempts"])

    def test_completed_review_call_recovered_after_score_only_commit(self):
        call = {"run_id": "saved-score-run", "usage": {"total_tokens": 17}}
        scores = {"versions": [{"review_calls": [call]}], "edits": []}
        self.assertEqual(runner.review_call_ledger({}, scores), [call])
        self.assertEqual(runner.review_call_ledger({"judge_calls": [call]}, scores), [call])

    def test_version_freezes_disclosed_indices(self):
        indices = [0, 2]
        record = self.recorder.record(self.data, turn=1, stage="COLLECTING", kind="committed",
                                      observed=[], disclosed_fact_indices=indices)
        indices.append(3)
        self.assertEqual(record["disclosed_fact_indices"], [0, 2])

    def test_first_draft_requires_visible_body_regardless_of_stage(self):
        versions = [
            {"version_id": "internal", "user_visible": False, "resume_data": self.data},
            {"version_id": "title-only", "user_visible": True, "resume_data": {"projects": [{"name": "名称"}]}},
            {"version_id": "draft", "user_visible": True, "stage": "COLLECTING", "resume_data": self.data},
        ]
        self.assertEqual(runner.first_draft_version(versions)["version_id"], "draft")

    def test_hidden_body_does_not_count_as_first_draft(self):
        resume = {"projects": [{"name": "项目", "description": "有文字", "hidden": True}]}
        self.assertFalse(runner.has_experience_body(resume))


class SimulatorEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.case = {"truth_facts": ["我参与了手动测试。", "没有效果数字。", "没有上线。"],
                     "simulator_topics": [{"keywords": ["效果"], "fact_indices": [1]},
                                          {"keywords": ["测试"], "fact_indices": [0]}]}

    def test_only_selected_verbatim_truth_is_sent(self):
        result = answer_question(self.case, "效果如何？", set())
        self.assertEqual(result["text"], "没有效果数字。")
        self.assertEqual(result["fact_indices"], [1])

    def test_unknown_question_does_not_disclose_unrelated_truth(self):
        result = answer_question(self.case, "使用了什么数据库？", set())
        self.assertEqual(result["fact_indices"], [])
        self.assertNotIn("上线", result["text"])

    def test_no_question_stops_followup(self):
        self.assertIsNone(answer_question(self.case, "已整理好右侧草稿。", set()))

    def test_no_unprompted_generate_to_improve_first_draft_metric(self):
        result = answer_question(self.case, "测试中遇到什么问题？", set())
        self.assertNotIn("生成", result["text"])

    def test_generation_offer_has_fact_free_control_response(self):
        result = answer_question(self.case, "要不要现在生成简历？", set())
        self.assertEqual(result["reason"], "explicit_generation_offer")
        self.assertEqual(result["fact_indices"], [])

    def test_negated_generation_is_not_an_offer(self):
        result = answer_question(self.case, "现在不能生成，你能补充项目细节吗？", set())
        self.assertNotEqual(result["reason"], "explicit_generation_offer")

    def test_all_authored_cases_are_valid_and_trap_covered(self):
        import json
        cases = [json.loads(path.read_text()) for path in (HERE / "cases").glob("*.json")]
        self.assertEqual(len(cases), 12)
        for case in cases:
            validate_case(case)
            self.assertGreaterEqual(len(set(case["traps"])), 2)
            self.assertEqual(case["truth_review_status"], "approved_by_claude")


class RejudgeEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejudge_preserves_prior_score_calls_and_frozen_dialogue(self):
        import judge
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "case"
            folder.mkdir()
            case = {"id": "case"}
            frozen = [{"version_id": "v001", "turn": 1, "resume_data": {},
                       "observed_facts": ["已披露"], "disclosed_fact_indices": [2]}]
            first_call = {"run_id": "first"}
            runner.write_json(folder / "versions.json", frozen)
            runner.write_json(folder / "edit-inputs.json", [])
            runner.write_json(folder / "scores.json", {"versions": [{"version_id": "v001", "score": {
                "status": "completed", "marker": "first"}, "review_calls": [first_call]}], "edits": []})
            runner.write_json(folder / "meta.json", {"graph_status": "completed", "judge_calls": [first_call]})
            transcript = folder / "transcript.md"
            transcript.write_text("frozen conversation")

            class Counter:
                def __init__(self):
                    self.calls = [{"run_id": "second"}]

            context = runner.ContextVar("test_counter", default=None)
            args = SimpleNamespace(rejudge_versions=True, judge_timeout=1)
            fake = AsyncMock(return_value={"status": "completed", "marker": "second"})
            with patch.object(judge, "judge_version", fake):
                meta = await runner.rescore_case(case, object(), Counter, context, args, root)
            score = json.loads((folder / "scores.json").read_text())["versions"][0]
            self.assertEqual(score["score"]["marker"], "second")
            self.assertEqual(score["previous_attempts"][0]["marker"], "first")
            self.assertEqual({call["run_id"] for call in meta["judge_calls"]}, {"first", "second"})
            self.assertEqual(fake.call_args.kwargs["disclosed_fact_indices"], [2])
            self.assertEqual(len(score["score"]["judge_code_sha256"]), 64)
            self.assertEqual(json.loads((folder / "versions.json").read_text()), frozen)
            self.assertEqual(transcript.read_text(), "frozen conversation")


class SelectorTests(unittest.IsolatedAsyncioTestCase):
    class FakeSelector:
        def __init__(self, payload):
            self.payload = payload
            self.messages = None

        async def ainvoke(self, messages, **kwargs):
            self.messages = messages
            return SimpleNamespace(content=json.dumps(self.payload, ensure_ascii=False))

    def load_case(self, name):
        return json.loads((HERE / "cases" / f"{name}.json").read_text())

    async def test_direction_original_question_selects_personal_responsibility(self):
        case = self.load_case("direction-01")
        model = self.FakeSelector({"fact_indices": [6]})
        result = await select_answer(case, "这个小组作业里你具体负责哪一部分？", {0, 1, 2, 3}, model)
        self.assertEqual(result["fact_indices"], [6])
        self.assertEqual(result["text"], render_fact(case["truth_facts"][6]))
        self.assertNotIn('在“晚餐账本”中', result["text"])
        supplied = json.loads(model.messages[1]["content"])["undisclosed_facts"]
        self.assertNotIn("2", supplied)

    async def test_ai_pm_original_question_selects_retest(self):
        case = self.load_case("ai-pm-01")
        model = self.FakeSelector({"fact_indices": [4]})
        result = await select_answer(case, "改完提示词后，你重新跑过那批问题吗？", {0, 1, 2, 3}, model)
        self.assertEqual(result["fact_indices"], [4])
        self.assertIn("重测", result["text"])
        self.assertIn("没有保存准确率或改善比例", result["text"])

    async def test_empty_selection_uses_relevant_negative_even_if_disclosed(self):
        case = self.load_case("import-01")
        model = self.FakeSelector({"fact_indices": []})
        result = await select_answer(case, "有没有留下排查记录？", set(case["opening_fact_indices"][0]), model)
        self.assertEqual(result["fact_indices"], [6])
        self.assertEqual(result["text"], render_fact(case["truth_facts"][6]))
        self.assertNotIn("没有排查记录", result["text"])

    async def test_generated_prose_is_rejected_and_never_sent(self):
        case = self.load_case("ai-pm-01")
        model = self.FakeSelector({"fact_indices": [4], "text": "用户增长100%"})
        result = await select_answer(case, "效果如何？", {0, 1, 2, 3}, model)
        self.assertEqual(result["selector_status"], "fallback")
        self.assertNotIn("用户增长100%", result["text"])

    async def test_out_of_range_and_disclosed_indices_fail_closed(self):
        case = {"truth_facts": ["已披露", "未披露"], "simulator_topics": []}
        for indices in ([99], [-1], [0], [True], [1, 1]):
            result = await select_answer(case, "怎么做的？", {0}, self.FakeSelector({"fact_indices": indices}))
            self.assertEqual(result["selector_status"], "fallback")
            self.assertEqual(result["fact_indices"], [])

    async def test_empty_unrelated_selection_does_not_dump_hidden_truth(self):
        case = self.load_case("ai-pm-01")
        result = await select_answer(case, "你在哪里住？", {0}, self.FakeSelector({"fact_indices": []}))
        self.assertEqual(result["fact_indices"], [])

    def test_render_removes_only_wrapper_keeps_negation_and_every_clause(self):
        fact = '在“项目”中，我重测了问题，但没有保存比例；队友做页面。'
        self.assertEqual(render_fact(fact), "我重测了问题，但没有保存比例；队友做页面。")
        self.assertEqual(render_fact('“项目”没有上线。'), '“项目”没有上线。')


if __name__ == "__main__":
    unittest.main()
