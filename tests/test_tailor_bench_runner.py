"""Regression checks for benchmark evidence, not for the legacy writing policy."""
import importlib.util
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1] / "evaluation" / "tailor-bench"
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("tailor_bench_runner", HERE / "run_bench.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from simulate_user import answer_question, validate_case  # noqa: E402


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
            self.assertEqual(case["truth_review_status"], "draft_pending_claude")


if __name__ == "__main__":
    unittest.main()
