"""Reports preserve incomplete evidence and full denominators; no live providers."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tailor_bench_report", ROOT / "evaluation/tailor-bench/report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def version(vid="v001", turn=2, visible=True, name_only=False):
    data = {"projects": [{"name": "合成项目"}]} if name_only else {"projects": [{"description": "我核对记录，没有删除原数据。"}]}
    return {"version_id": vid, "turn": turn, "user_visible": visible,
            "stage": "COLLECTING", "kind": "internal", "resume_data": data}


def score(quality=3, covered=1, semantic_suspicion=False):
    audit = {"unit_id": "u001", "verdict": "uncertain" if semantic_suspicion else "supported"}
    return {
        "status": "completed", "quality": {key: quality for key in report.QUALITY_DIMENSIONS},
        "deterministic": {"status": "completed", "flags": []},
        "coverage": {"total": 2, "covered": covered,
                     "requirements": [{"requirement": f"r{i} 要求{i}", "covered": i <= covered,
                                       "evidence_supported": i <= covered} for i in (1, 2)]},
        "factuality": {"status": "pending_human_review", "audits": [audit],
                       "suspicions": [{**audit, "quote": "核对记录", "reason": "需人工复核"}] if semantic_suspicion else []},
    }


def edit(instruction, turn, *, category="no_diff"):
    item = {"turn": turn, "instruction": instruction, "turn_status": "completed"}
    if category == "error":
        item["score"] = {"status": "error", "error_type": "TimeoutError"}
    elif category == "executed":
        item["score"] = {"status": "completed", "substantive_diff": True, "followed": True, "executed": True}
    else:
        item["score"] = {"status": "completed", "substantive_diff": False, "followed": False, "executed": False}
    return item


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)

    def manifest(self, ids=("case-01",)):
        dump(self.output / "manifest.json", {"case_hashes": {cid: "sha256" for cid in ids},
                                            "started_at": "2026-10-08T18:00:00+08:00", "git_commit": "snapshot",
                                            "writer_model": "writer", "judge_model": "judge"})

    def fixture(self, cid="case-01", *, versions=None, version_scores=None, edits=None, meta=None, turns=None):
        if versions is None:
            versions = [version()]
        if version_scores is None:
            version_scores = [{"version_id": row["version_id"], "score": score()} for row in versions]
        if edits is None:
            edits = [edit("按岗位改", 3), edit("精简成一条", 4)]
        if turns is None:
            turns = [{"turn": 2, "phase": "opening", "status": "completed", "elapsed_seconds": 5},
                     {"turn": 3, "phase": "edit", "status": "completed", "elapsed_seconds": 10},
                     {"turn": 4, "phase": "edit", "status": "completed", "elapsed_seconds": 15}]
        case = {"id": cid, "role_family": "data", "truth_review_status": "draft_pending_claude",
                "must_cover": ["r1 要求1", "r2 要求2"], "edit_instructions": ["按岗位改", "精简成一条"]}
        values = {"graph_status": "completed", "evaluation_status": "completed",
                  "truth_review_status": "draft_pending_claude", "first_draft_turn": 2,
                  "first_draft_version": "v001", "final_version": versions[-1]["version_id"] if versions else None}
        values.update(meta or {})
        folder = self.output / cid
        for name, data in (("case", case), ("meta", values), ("versions", versions), ("turns", turns),
                           ("scores", {"versions": version_scores, "edits": edits})):
            dump(folder / f"{name}.json", data)

    def test_failed_reviews_keep_unknown_and_do_not_promote_unvalidated_output(self):
        self.manifest()
        failed = {"status": "error", "error_type": "JudgeSchemaError",
                  "deterministic": {"status": "completed", "flags": [{"kind": "forbidden_claim", "span": "上线"}]},
                  "unvalidated_result": {"quality": {key: 5 for key in report.QUALITY_DIMENSIONS},
                                         "audits": [{"verdict": "unsupported"}]}}
        self.fixture(version_scores=[{"version_id": "v001", "score": failed}],
                     edits=[edit("按岗位改", 3, category="error"), edit("精简成一条", 4, category="error")],
                     meta={"evaluation_status": "incomplete"})
        result = report.build_report(self.output)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["totals"]["coverage"]["unknown"], 2)
        self.assertEqual(result["totals"]["coverage"]["observed_lower_bound"], 0)
        self.assertEqual(result["totals"]["coverage"]["possible_upper_bound"], 1)
        self.assertEqual(result["totals"]["edits"]["error"], 2)
        self.assertIsNone(result["cases"][0]["first_quality"])
        self.assertEqual(result["totals"]["facts"]["lexical_flags"], 1)
        self.assertEqual(result["totals"]["facts"]["semantic_suspicions"], 0)
        self.assertIsNone(result["totals"]["facts"]["confirmed_new_facts"])
        queue = json.loads((self.output / "review-queue.json").read_text())
        self.assertIn("lexical", {row["kind"] for row in queue["items"]})
        self.assertIn("evaluation_incomplete", {row["kind"] for row in queue["items"]})
        self.assertNotIn("semantic", {row["kind"] for row in queue["items"]})

    def test_no_versions_means_zero_coverage_but_missing_edits_still_have_denominator(self):
        self.manifest()
        self.fixture(versions=[], edits=[], turns=[{"turn": 1, "phase": "opening", "status": "completed"}],
                     meta={"first_draft_turn": None, "first_draft_version": None})
        result = report.build_report(self.output)
        coverage = result["totals"]["coverage"]
        self.assertEqual((coverage["covered"], coverage["known_uncovered"], coverage["unknown"]), (0, 2, 0))
        self.assertEqual(result["totals"]["edits"]["expected"], 2)
        self.assertEqual(result["totals"]["edits"]["not_run"], 2)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("no_visible_draft", result["cases"][0]["failures"])

    def test_no_diff_never_earns_execution_and_ai_scores_never_confirm_safety(self):
        self.manifest()
        self.fixture()
        result = report.build_report(self.output)
        self.assertEqual(result["totals"]["edits"]["no_diff"], 2)
        self.assertEqual(result["totals"]["edits"]["executed"], 0)
        self.assertEqual(result["totals"]["coverage"]["covered"], 1)
        self.assertEqual(result["status"], "evaluated_pending_claude")
        self.assertIsNone(result["totals"]["facts"]["safe"])
        self.assertIsNone(result["totals"]["coverage"]["human_confirmed_covered"])
        self.assertIn("edit_not_executed", result["cases"][0]["failures"])
        self.assertEqual(result["cases"][0]["truth_review_status"], "draft_pending_claude")

    def test_formal_first_draft_can_reference_old_collecting_version(self):
        self.manifest()
        self.fixture(meta={"first_draft_turn": 5, "first_draft_version": "v001"})
        result = report.build_report(self.output)
        case = result["cases"][0]
        self.assertEqual(case["first_visible_experience_turn"], 2)
        self.assertEqual(case["first_draft_turn"], 5)
        self.assertEqual(case["formal_first_quality"]["jd_relevance"], 3)
        self.assertEqual(case["first_quality"]["jd_relevance"], 3)
        self.assertEqual(result["totals"]["first_visible_experience"]["within_two_turns"], 1)
        self.assertEqual(result["totals"]["first_draft"]["within_two_turns"], 0)

    def test_visible_quality_ignores_name_only_and_invisible_body_versions(self):
        self.manifest()
        versions = [version("v001", 1, name_only=True), version("v002", 2, visible=False), version("v003", 4)]
        self.fixture(versions=versions,
                     version_scores=[{"version_id": row["version_id"], "score": score(quality=n)} for n, row in enumerate(versions, 2)])
        result = report.build_report(self.output)
        case = result["cases"][0]
        self.assertEqual(case["first_visible_experience_version"], "v003")
        self.assertEqual(case["first_visible_experience_turn"], 4)
        self.assertEqual(case["first_quality"]["jd_relevance"], 4)
        self.assertEqual(case["formal_first_quality"]["jd_relevance"], 2)
        self.assertEqual((case["visible_version_count"], case["internal_only_version_count"]), (2, 1))

    def test_manifest_missing_cases_remain_in_twenty_four_denominators(self):
        ids = [f"case-{index:02}" for index in range(1, 13)]
        self.manifest(ids)
        self.fixture()
        result = report.build_report(self.output)
        self.assertEqual(result["totals"]["cases"], 12)
        self.assertEqual(result["totals"]["coverage"]["total"], 24)
        self.assertEqual(result["totals"]["coverage"]["unknown"], 22)
        self.assertEqual(result["totals"]["edits"]["expected"], 24)
        self.assertEqual(result["totals"]["edits"]["not_run"], 22)
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(all(not row["source"].startswith("/") for row in result["failures"]))

    def test_graph_error_overrides_successful_edit_score(self):
        self.manifest()
        edits = [edit("按岗位改", 3, category="executed"), edit("精简成一条", 4)]
        edits[0]["turn_status"] = "error"
        self.fixture(edits=edits, meta={"graph_status": "error", "status": "graph_error"})
        result = report.build_report(self.output)
        self.assertEqual(result["totals"]["edits"]["executed"], 0)
        self.assertEqual(result["totals"]["edits"]["error"], 1)
        self.assertIn("graph_failed", result["cases"][0]["failures"])

    def test_semantic_and_lexical_queue_entries_remain_separate_with_relative_links(self):
        self.manifest()
        value = score(semantic_suspicion=True)
        value["deterministic"]["flags"] = [{"kind": "forbidden_claim", "quote": "核对记录"}]
        self.fixture(version_scores=[{"version_id": "v001", "score": value}])
        result = report.build_report(self.output)
        self.assertEqual(result["totals"]["facts"]["visible_lexical_flags"], 1)
        self.assertEqual(result["totals"]["facts"]["visible_semantic_suspicions"], 1)
        queue = json.loads((self.output / "review-queue.json").read_text())["items"]
        self.assertTrue(all(row["review_status"] == "pending_claude" for row in queue))
        self.assertTrue(all(not Path(row["source"]).is_absolute() for row in queue))
        text = (self.output / "detailed-summary.md").read_text()
        self.assertIn("[review-queue.json](review-queue.json)", text)
        self.assertIn("N/A", text)
        self.assertNotIn(str(self.output), text)

    def test_usage_totals_are_partial_and_cost_range_is_not_an_invoice(self):
        self.manifest(("case-01", "case-02"))
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                 "logical_model_calls": 1, "calls_with_usage": 1, "calls_without_usage": 0,
                 "reported_token_cost_usd": {"lower_bound": 0.01, "upper_bound": 0.02,
                                             "priced_calls": 1, "unpriced_calls": 0, "source": "verified-rate-table"}}
        self.fixture(meta={"graph_usage": usage})
        result = report.build_report(self.output)
        total = result["totals"]["usage"]["graph"]
        self.assertEqual(total["total_tokens"], 15)
        self.assertFalse(total["total_tokens_complete"])
        self.assertEqual(total["cases_missing_usage"], 1)
        self.assertEqual(total["reported_token_cost_usd"]["cases_without_range"], 1)
        self.assertIsNone(total["actual_cost_usd"])
        self.assertIsNone(result["totals"]["usage"]["judge"]["total_tokens"])

    def test_claiming_completed_with_missing_quality_is_not_usable(self):
        self.manifest()
        invalid = score()
        invalid["quality"] = None
        self.fixture(version_scores=[{"version_id": "v001", "score": invalid}])
        result = report.build_report(self.output)
        self.assertEqual(result["totals"]["coverage"]["unknown"], 2)
        self.assertEqual(result["cases"][0]["evaluation_status"], "incomplete")
        self.assertEqual(result["cases"][0]["versions"][0]["score_status"], "invalid_completed_score")

    def test_completed_requires_both_lexical_and_semantic_review(self):
        self.manifest()
        for missing in ("deterministic", "factuality"):
            with self.subTest(missing=missing):
                invalid = score()
                invalid.pop(missing)
                self.fixture(version_scores=[{"version_id": "v001", "score": invalid}])
                result = report.build_report(self.output)
                self.assertEqual(result["totals"]["coverage"]["unknown"], 2)
                self.assertEqual(result["cases"][0]["evaluation_status"], "incomplete")

    def test_no_draft_score_cannot_hide_existing_visible_content(self):
        self.manifest()
        self.fixture(version_scores=[{"version_id": "v001", "score": {"status": "no_draft"}}])
        result = report.build_report(self.output)
        self.assertEqual(result["totals"]["coverage"]["unknown"], 2)
        self.assertEqual(result["cases"][0]["versions"][0]["score_status"], "invalid_no_draft")


if __name__ == "__main__":
    unittest.main()
