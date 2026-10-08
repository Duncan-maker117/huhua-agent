"""Private-data boundaries and observable acceptance; no external model calls."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1] / "evaluation" / "tailor-bench"
sys.path.insert(0, str(HERE))
import private_case as private  # noqa: E402


def sample_case():
    opening, edit = "下面是本人材料：参与项目原型。", "删除自我评价。"
    return {"id": "private-example", "private": True, "replay_policy": "fixed_two_turns", "role_family": "ai-pm",
            "jd_text": "", "opening_turns": [opening], "edit_instructions": [edit],
            "truth_facts": ["参与项目原型。"], "forbidden": {}, "must_cover": ["r1 原型"],
            "replay_sha256": [hashlib.sha256(text.encode()).hexdigest() for text in (opening, edit)]}


def reference_resume():
    # Synthetic placeholders only; no candidate source prose or profile facts.
    return {"basic_info": {"location": "深圳", "objective": "AI 产品经理实习（Agent 应用方向）"},
            "projects": [
                {"name": "mtagent", "polished_bullets": ["测试条目甲甲甲甲甲。", "测试条目乙。"]},
                {"name": "CodeWiz", "polished_bullets": ["测试链接 PR #6、#8。", "测试条目丙。"]},
                {"name": "Forge Skill", "polished_bullets": ["测试条目丁。", "测试条目戊。"]},
                {"name": "Huhua Agent", "polished_bullets": ["测试条目己。"]}],
            "skills": ["工具甲", "工具乙", "工具丙"]}


class PrivateBoundaryTests(unittest.TestCase):
    def test_default_remains_twelve_public_cases(self):
        cases = private.load_cases()
        self.assertEqual(len(cases), 12)
        self.assertFalse(any(private.is_private(case) for case in cases))

    def test_private_needs_fixed_two_turns_and_hashes(self):
        case = sample_case()
        private.validate_benchmark_case(case)
        for update in ({"jd_text": "new JD"}, {"edit_instructions": ["a", "b"]},
                       {"opening_turns": ["rewritten"]}, {"replay_sha256": []},
                       {"simulator_topics": [{"keywords": ["foo"], "fact_indices": [0]}]}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                private.validate_benchmark_case({**case, **update})

    def test_no_simulator_turns_are_inserted(self):
        self.assertEqual(private.followup_limit(sample_case(), 4), 0)
        self.assertEqual(private.followup_limit({"id": "public"}, 4), 4)

    def test_private_output_defaults_to_ignored_root(self):
        self.assertEqual(private.safe_output([sample_case()], None, "example"), (HERE / "runs-private/example").resolve())

    def test_private_cannot_write_public_or_external_paths(self):
        for path in (HERE / "runs/accidental", HERE / "runs-private/../runs/escaped", Path("/tmp/personal-output")):
            with self.subTest(path=path), self.assertRaises(ValueError):
                private.safe_output([sample_case()], path, "example")

    def test_symlink_cannot_escape_private_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private"
            root.mkdir()
            (root / "escape").symlink_to(Path(temp), target_is_directory=True)
            with patch.object(private, "PRIVATE_RUNS", root), self.assertRaises(ValueError):
                private.safe_output([sample_case()], root / "escape/run", "example")

    def test_custom_directory_classified_private_even_if_marker_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            case = sample_case()
            del case["private"]
            (Path(temp) / "case.json").write_text(json.dumps(case))
            self.assertTrue(private.load_cases(cases_dir=Path(temp))[0]["private"])

    def test_private_flash_official_only_and_graph_only(self):
        settings = SimpleNamespace(LLM_MODEL="deepseek-flash", LLM_STRUCTURED_MODEL="deepseek-flash", LLM_BASE_URL="https://api.deepseek.com/v1")
        args = SimpleNamespace(graph_only=True)
        private.assert_private_model_policy([sample_case()], args, settings)
        with self.assertRaises(ValueError):
            private.assert_private_model_policy([sample_case()], SimpleNamespace(graph_only=False), settings)
        for name, value in (("LLM_MODEL", "deepseek-v4-pro"), ("LLM_STRUCTURED_MODEL", "other"),
                            ("LLM_BASE_URL", "https://other.example/v1"),
                            ("LLM_BASE_URL", "http://api.deepseek.com/v1")):
            with self.subTest(name=name), self.assertRaises(ValueError):
                private.assert_private_model_policy([sample_case()], args, SimpleNamespace(**{**vars(settings), name: value}))

    def test_report_refuses_private_frozen_input_in_public_run(self):
        import report
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private-example").mkdir()
            (root / "private-example/case.json").write_text(json.dumps(sample_case()))
            with self.assertRaises(ValueError):
                report.build_report(root)
            self.assertFalse((root / "summary.md").exists())

    @unittest.skipUnless((HERE / "cases-private/real-01.json").exists(), "local private source not distributed")
    def test_real_fixture_preserves_actual_two_inputs_and_hides_golden(self):
        case = json.loads((HERE / "cases-private/real-01.json").read_text())
        private.validate_benchmark_case(case)
        self.assertEqual(len(case["edit_instructions"][0]), 237)
        self.assertEqual(len(case["source_materials"]), 2)
        for material in case["source_materials"]:
            self.assertIn(material["text"], case["opening_turns"][0])
        self.assertNotIn("标准答案", case["opening_turns"][0])
        self.assertNotIn("golden-one-page", case["opening_turns"][0])

    @unittest.skipUnless((HERE / "cases-private/real-01.json").exists(), "local private source not distributed")
    def test_saved_run_import_keeps_rendered_pages_and_no_execution(self):
        case = json.loads((HERE / "cases-private/real-01.json").read_text())
        source = HERE.parents[1] / case["frozen_from"]
        if not source.exists():
            self.skipTest("local frozen UI run not available")
        (HERE / "runs-private").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=HERE / "runs-private") as temp:
            output = Path(temp) / "saved-import"
            result = private.import_saved_run(source.parent, output)
            acceptance = json.loads((output / "real-01/private-acceptance.json").read_text())
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(acceptance["final"]["render"]["pages"], 3)
            self.assertEqual(acceptance["edits"][0]["op_executed"], 0)
            self.assertEqual(json.loads((output / "manifest.json").read_text())["new_model_calls"], 0)


class ObservableAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.resume = reference_resume()
        self.render = {"status": "rendered", "pages": 1}
        self.context = {"session_constraints": {"page_limit": 1}}

    def evaluate(self, resume=None, **kwargs):
        return private.evaluate_real01(resume or self.resume, rendered=kwargs.get("rendered", self.render),
                                       context=kwargs.get("context", self.context))

    def test_eight_goals_fourteen_operations_and_reference_not_exact_prose(self):
        result = self.evaluate()
        self.assertEqual((result["goal_total"], result["op_total"]), (8, 14))
        self.assertEqual(result["goal_counts"], {"pass": 8})
        self.assertEqual(result["length"]["bullet_count"], 7)
        self.assertTrue(result["golden_comparison"]["order_matches_reference"])
        self.assertEqual(result["golden_comparison"]["semantic_limitations_status"], "pending_review")

    def test_no_render_cannot_claim_page_pass(self):
        result = self.evaluate(rendered=None)
        page = result["goals"][-1]
        self.assertEqual(page["status"], "unknown")
        self.assertIsNone(result["length"]["bullets"][0]["actual_lines"])

    def test_rendered_three_pages_fails_even_with_one_page_constraint(self):
        self.assertEqual(self.evaluate(rendered={"status": "rendered", "pages": 3})["goals"][-1]["status"], "fail")

    def test_missing_persistent_constraint_remains_unknown(self):
        self.assertEqual(self.evaluate(context={})["goals"][-1]["status"], "unknown")

    def test_unchanged_satisfied_operations_are_not_execution(self):
        result = private.evaluate_edit(self.resume, copy.deepcopy(self.resume), before_rendered=self.render, rendered=self.render,
                                       before_context=self.context, context=self.context)
        self.assertEqual(result["op_executed"], 0)
        self.assertEqual(result["goal_executed"], 0)
        self.assertEqual(result["op_counts"], {"already_satisfied": 14})

    def test_compound_edit_counts_actual_changed_operations(self):
        before = copy.deepcopy(self.resume)
        before["projects"].insert(0, {"name": "深圳", "polished_bullets": ["联系栏"]})
        before["basic_info"]["location"] = ""
        before["basic_info"]["objective"] = "错误方向"
        before["self_evaluation"] = "自我评价文字"
        result = private.evaluate_edit(before, self.resume, before_rendered={"status": "rendered", "pages": 3}, rendered=self.render,
                                       before_context=self.context, context=self.context)
        self.assertEqual(result["op_executed"], 5)
        self.assertEqual(result["goal_executed"], 4)
        self.assertEqual(result["op_execution_rate"], 5 / 14)

    def test_graph_error_never_earns_edit_credit(self):
        result = private.evaluate_edit({}, self.resume, rendered=self.render, context=self.context, turn_status="error")
        self.assertEqual(result["op_executed"], 0)
        self.assertEqual(result["op_counts"], {"error": 14})

    def test_missing_or_hidden_project_cannot_satisfy_caps(self):
        self.resume["projects"][0]["hidden"] = True
        self.assertEqual(self.evaluate()["goals"][1]["status"], "fail")

    def test_skill_tokens_clean_links_and_repeated_metadata(self):
        self.resume["skills"] = ["开发：Python、Figma", "Python"]
        self.resume["projects"][1]["role"] = "测试角色"
        self.resume["projects"][1]["polished_bullets"] = ["[PR #6](https://example.com/6) 与 PR #8", "测试角色 2030.05 - 至今"]
        goals = {row["id"]: row["status"] for row in self.evaluate()["goals"]}
        self.assertEqual(goals["skills_dedup"], "fail")
        self.assertEqual(goals["readable_links"], "fail")
        self.assertEqual(goals["metadata_dedup"], "fail")

    def test_normalized_ngram_repetition_threshold_is_point_six(self):
        self.resume["projects"][1]["polished_bullets"].append("测试条目，甲甲甲甲甲！")
        result = private.length_metrics(self.resume)
        self.assertEqual(result["duplicate_threshold"], 0.6)
        self.assertTrue(any(row["cross_project"] and row["overlap"] == 1 for row in result["duplicate_pairs"]))

    def test_no_pdf_tools_leaves_unknown_not_estimated_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "fake.pdf"
            pdf.write_bytes(b"%PDF-placeholder")
            with patch.object(private.subprocess, "run", side_effect=FileNotFoundError):
                result = private.measure_rendered_resume(self.resume, "t001-jianyue", existing_pdf=pdf)
            self.assertEqual(result["status"], "render_error")
            self.assertIsNone(result["pages"])
            self.assertIsNone(result["within_page_limit"])

    def test_saved_pdf_page_count_uses_actual_tool_output(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "fake.pdf"
            pdf.write_bytes(b"%PDF-placeholder")
            with patch.object(private.subprocess, "run", side_effect=[
                    subprocess.CompletedProcess([], 0, stdout=b"Pages: 3\n"), FileNotFoundError()]):
                result = private.measure_rendered_resume(self.resume, "t001-jianyue", existing_pdf=pdf)
            self.assertEqual(result["pages"], 3)
            self.assertFalse(result["within_page_limit"])
            self.assertEqual(result["actual_line_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
