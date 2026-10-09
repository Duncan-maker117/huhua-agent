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
        self.assertEqual(case["first_draft_turn"], 2)
        self.assertEqual(case["diagnostic_stage_first_draft_turn"], 5)
        self.assertEqual(case["formal_first_quality"]["jd_relevance"], 3)
        self.assertEqual(case["first_quality"]["jd_relevance"], 3)
        self.assertEqual(result["totals"]["first_visible_experience"]["within_two_turns"], 1)
        self.assertEqual(result["totals"]["first_draft"]["within_two_turns"], 1)

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

    def test_hidden_backup_does_not_create_first_draft_or_coverage(self):
        self.manifest()
        hidden = version("v001", 1)
        hidden["resume_data"] = {"projects": [{"item_id": "hidden", "name": "备份项目",
                                                "description": "上线 999 次。", "hidden": True}]}
        self.fixture(versions=[hidden], version_scores=[{"version_id": "v001", "score": {"status": "no_draft"}}],
                     meta={"first_draft_turn": None, "first_draft_version": None})
        result = report.build_report(self.output)
        case = result["cases"][0]
        self.assertIsNone(case["first_draft_turn"])
        self.assertFalse(case["versions"][0]["has_displayed_content"])
        self.assertEqual(case["final_coverage"]["covered"], 0)
        self.assertEqual(result["totals"]["first_draft"]["drafted_cases"], 0)

    def test_pr4_report_preserves_per_version_page_guard_and_visible_flags(self):
        self.manifest()
        manifest = json.loads((self.output / "manifest.json").read_text())
        manifest["phase"] = "PR4"
        dump(self.output / "manifest.json", manifest)
        row = version()
        row["resume_data"]["projects"][0]["item_id"] = "visible"
        row["resume_data"]["projects"].append({"item_id": "backup", "hidden": True,
                                                   "description": "隐藏备份。"})
        row["acceptance_context"] = {
            "resume_meta": {"bullets": {"visible": [{"flags": ["transferable"]}],
                                        "backup": [{"flags": ["unsupported"]}]},
                            "writer_diagnostic": {"status": "model_fallback", "mode": "one_pass",
                                                  "stage": "one_pass", "error_type": "ValidationError"},
                            "compression_writer_diagnostics": [
                                {"status": "model_completed", "mode": "one_pass"},
                                {"status": "model_fallback", "mode": "two_pass",
                                 "stage": "write", "error_type": "TimeoutError"}]},
            "guard_fallbacks": [{"bullet_id": "b1", "reason": "compression_preserved_status_limit"}],
            "session_constraints": {"page_limit": 1}}
        row["render"] = {"status": "rendered", "pages": 2, "within_page_limit": False}
        self.fixture(versions=[row])
        result = report.build_report(self.output)
        self.assertEqual(result["totals"]["pages"]["over_limit"], 1)
        self.assertEqual(result["totals"]["guard"]["fallbacks"], 1)
        self.assertEqual(result["totals"]["guard"]["reasons"], {"compression_preserved_status_limit": 1})
        self.assertEqual(result["totals"]["writer"]["model_fallback"], 1)
        self.assertEqual(result["totals"]["writer"]["compression_model_fallback"], 1)
        self.assertEqual(result["totals"]["writer"]["compression_model_completed"], 1)
        self.assertEqual(result["totals"]["writer"]["model_completed"], 0)
        self.assertEqual(result["totals"]["writer_flags"], {"transferable": 1})
        self.assertEqual(result["cases"][0]["versions"][0]["pages"], 2)
        self.assertEqual(result["cases"][0]["versions"][0]["writer_diagnostics"]["main"]["error_type"], "ValidationError")
        summary = (self.output / "detailed-summary.md").read_text()
        self.assertIn("Writer 模型回退 | 2", summary)
        self.assertIn("事实限制保护回退 | 1", summary)
        title = summary.splitlines()[0]
        self.assertEqual(title, "# Tailor PR4 · 逐版本评估")

    def test_frozen_baseline_without_phase_keeps_legacy_report_contract(self):
        self.manifest()
        self.fixture()
        result = report.build_report(self.output)
        self.assertEqual(result["totals"]["pages"]["unknown"], 1)
        self.assertIsNone(result["totals"]["guard"]["fallbacks"])
        self.assertEqual(result["totals"]["writer"]["status"], "not_observed")
        self.assertEqual(result["totals"]["writer"]["not_observed_versions"], 1)
        self.assertIn("Writer 模型回退 | 未观测", (self.output / "detailed-summary.md").read_text())
        self.assertEqual((self.output / "detailed-summary.md").read_text().splitlines()[0],
                         "# Tailor PR0 · 旧链路逐版本基线")

    def test_writer_diagnostic_does_not_publish_exception_message(self):
        self.manifest()
        row = version()
        row["acceptance_context"] = {"resume_meta": {
            "writer_diagnostic": {"status": "model_fallback", "stage": "write",
                                  "error_type": "provider rejected private@example.com"},
            "compression_writer_diagnostics": []}}
        self.fixture(versions=[row])
        result = report.build_report(self.output)
        diagnostic = result["cases"][0]["versions"][0]["writer_diagnostics"]["main"]
        self.assertEqual(diagnostic, {"status": "model_fallback", "stage": "write"})
        self.assertEqual(result["totals"]["writer"]["model_fallback"], 1)
        self.assertNotIn("private@example.com", (self.output / "aggregate.json").read_text())

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

    def test_facts_only_middle_version_stays_completed_without_quality(self):
        self.manifest()
        versions = [version("v001", 2), version("v002", 3), version("v003", 4)]
        middle = score()
        middle["quality"] = None
        middle["quality_scope"] = "facts_only"
        self.fixture(versions=versions, version_scores=[
            {"version_id": "v001", "score": score()},
            {"version_id": "v002", "score": middle},
            {"version_id": "v003", "score": score()},
        ])
        result = report.build_report(self.output)
        self.assertEqual([row["score_status"] for row in result["cases"][0]["versions"]],
                         ["completed", "completed", "completed"])

    def test_final_version_still_needs_quality_when_marked_facts_only(self):
        self.manifest()
        invalid = score()
        invalid["quality"] = None
        invalid["quality_scope"] = "facts_only"
        self.fixture(version_scores=[{"version_id": "v001", "score": invalid}])
        result = report.build_report(self.output)
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

    def dual_coverage_fixture(self, *, pending=False):
        self.manifest()
        self.fixture()
        folder = self.output / "case-01"
        case = json.loads((folder / "case.json").read_text())
        case.update(truth_review_status="approved_by_claude", requirements=[
            {"id": "r1", "text": "要求1", "expected_status": "direct", "evidence_fact_indices": [0, 1]},
            {"id": "r2", "text": "要求2", "expected_status": "transferable", "evidence_fact_indices": [2]},
            {"id": "r3", "text": "上线", "expected_status": "gap", "evidence_fact_indices": []},
        ])
        dump(folder / "case.json", case)
        meta = json.loads((folder / "meta.json").read_text())
        meta.update(truth_review_status="approved_by_claude", stage_first_draft_turn=None, stage_first_draft_version=None)
        dump(folder / "meta.json", meta)
        versions = json.loads((folder / "versions.json").read_text())
        versions[0]["disclosed_fact_indices"] = [0]
        dump(folder / "versions.json", versions)
        value = score()
        for row in value["coverage"]["requirements"]:
            row["expected_status"] = "direct"
        value["coverage"]["requirements"].append({"requirement": "r3 上线", "expected_status": "gap"})
        value["coverage"].update(
            coverage_of_disclosed={"total": 1, "covered": None if pending else 1, "fact_total": 1, "fact_covered": None if pending else 1},
            coverage_of_truth={"total": 2, "covered": None if pending else 1, "fact_total": 3, "fact_covered": None if pending else 1},
            gap_requirements=[{"requirement": "r3 上线", "leaked_into_resume": False}],
        )
        if pending:
            value["status"] = "not_run"
        scores = json.loads((folder / "scores.json").read_text())
        scores["versions"][0]["score"] = value
        dump(folder / "scores.json", scores)

    def test_gap_is_excluded_and_unrevealed_requirement_is_na_only_for_disclosed(self):
        self.dual_coverage_fixture()
        result = report.build_report(self.output)
        truth = result["totals"]["coverage_of_truth"]
        disclosed = result["totals"]["coverage_of_disclosed"]
        self.assertEqual((truth["covered"], truth["total"], truth["fact_total"]), (1, 2, 3))
        self.assertEqual((disclosed["covered"], disclosed["total"], disclosed["not_applicable"]), (1, 1, 1))
        self.assertEqual(disclosed["fact_total"], 1)
        self.assertEqual(result["totals"]["gap_requirements"], 1)
        self.assertIsNone(result["cases"][0]["diagnostic_stage_first_draft_turn"])
        self.assertEqual(result["cases"][0]["first_draft_turn"], 2)
        queue = json.loads((self.output / "review-queue.json").read_text())["items"]
        self.assertNotIn("truth_review", {row["kind"] for row in queue})
        self.assertEqual(result["truth_review_status"], "approved_by_claude")

    def test_dual_coverage_plans_survive_pending_reviews_without_becoming_zero_scores(self):
        self.dual_coverage_fixture(pending=True)
        result = report.build_report(self.output)
        self.assertEqual(result["totals"]["coverage_of_truth"]["unknown"], 2)
        self.assertEqual(result["totals"]["coverage_of_disclosed"]["unknown"], 1)
        self.assertEqual(result["totals"]["coverage_of_disclosed"]["not_applicable"], 1)
        self.assertEqual(result["totals"]["coverage_of_truth"]["fact_unknown"], 3)
        self.assertEqual(result["status"], "incomplete")

    def test_incomplete_v2_coverage_cannot_fall_back_to_legacy_completed_score(self):
        self.dual_coverage_fixture()
        path = self.output / "case-01/scores.json"
        scores = json.loads(path.read_text())
        scores["versions"][0]["score"]["coverage"].pop("coverage_of_truth")
        dump(path, scores)
        result = report.build_report(self.output)
        self.assertEqual(result["cases"][0]["versions"][0]["score_status"], "invalid_completed_score")
        self.assertEqual(result["totals"]["coverage_of_truth"]["unknown"], 2)
        self.assertEqual(result["status"], "incomplete")

    def test_self_evaluation_fact_coverage_does_not_count_as_experience_first_draft(self):
        self.dual_coverage_fixture()
        path = self.output / "case-01/versions.json"
        versions = json.loads(path.read_text())
        versions[0]["resume_data"] = {"self_evaluation": "我核对记录，没有删除原数据。"}
        versions[0]["observed_facts"] = ["我核对记录，没有删除原数据。"]
        dump(path, versions)
        result = report.build_report(self.output)
        case = result["cases"][0]
        self.assertIsNone(case["first_draft_turn"])
        self.assertIsNone(case["first_quality"])
        self.assertEqual(result["totals"]["first_draft"]["drafted_cases"], 0)
        self.assertEqual(case["final_coverage_of_truth"]["covered"], 1)
        self.assertEqual(case["final_coverage_of_disclosed"]["covered"], 1)
        self.assertTrue(case["product_observations"]["self_evaluation_assertions"])
        text = (self.output / "summary.md").read_text()
        self.assertIn("覆盖不限经历栏，不能替代首稿指标", text)
        self.assertIn("case-01 的已披露行动事实被放入 self_evaluation（自评栏）", text)
        self.assertIn("终稿已有事实覆盖 1/2，但首稿仍为无稿", text)

    def test_historical_zero_is_not_transferred_and_quality_findings_use_current_artifacts(self):
        self.manifest()
        self.fixture()
        folder = self.output / "case-01"
        versions = json.loads((folder / "versions.json").read_text())
        versions[0]["observed_facts"] = ["我核对记录，没有删除原数据。"]
        dump(folder / "versions.json", versions)
        scores = json.loads((folder / "scores.json").read_text())
        scores["versions"][0]["score"]["quality_checks"] = [{"kind": "project_title_mismatch", "path": "projects[0].name", "quote": "课程"}]
        scores["versions"][0]["score"]["factuality"]["unverifiable_units"] = [{"unit_id": "u001", "verdict": "uncertain"}]
        dump(folder / "scores.json", scores)
        result = report.build_report(self.output)
        self.assertEqual(result["historical_review"]["confirmed_new_experience_facts"], 0)
        self.assertIsNone(result["totals"]["facts"]["confirmed_new_facts"])
        self.assertEqual(result["totals"]["facts"]["semantic_suspicions"], 0)
        self.assertEqual(result["totals"]["facts"]["unverifiable_units"], 1)
        findings = result["totals"]["product_findings"]
        self.assertEqual(findings["title_error_cases"], ["case-01"])
        self.assertEqual(findings["verbatim_body_cases"], ["case-01"])
        self.assertEqual(findings["first_person_cases"], ["case-01"])
        text = (self.output / "detailed-summary.md").read_text()
        for code in ("E1", "E2", "E3", "E4", "E5"):
            self.assertIn(code, text)
        self.assertIn("这个 0 只属于 v1", text)
        self.assertNotIn("首稿 ≤ 2 个用户轮（进入成稿 stage）", text)

    def test_simulator_usage_is_separate_and_included_in_total_cost(self):
        self.manifest()
        def usage(tokens, cost):
            return {"input_tokens": tokens, "output_tokens": 0, "total_tokens": tokens,
                    "reported_token_cost_usd": {"lower_bound": cost, "upper_bound": cost,
                                                "priced_calls": 1, "unpriced_calls": 0}}
        self.fixture(meta={"graph_usage": usage(10, 0.01), "judge_usage": usage(20, 0.02), "simulator_usage": usage(5, 0.005)})
        result = report.build_report(self.output)
        values = result["totals"]["usage"]
        self.assertEqual(values["graph"]["total_tokens"], 10)
        self.assertEqual(values["simulator"]["total_tokens"], 5)
        self.assertEqual(values["all_models"]["total_tokens"], 35)
        self.assertEqual(values["all_models"]["reported_token_cost_usd"]["lower_bound"], 0.035)

    def test_r1_case_annotations_are_approved_and_keep_gap_out_of_positive_pool(self):
        cases = {p.stem: json.loads(p.read_text()) for p in (ROOT / "evaluation/tailor-bench/cases").glob("*.json")}
        handson = cases.pop("handson-01")
        self.assertEqual(handson["truth_review_status"], "pending_claude")
        self.assertIn("抖音", " ".join(handson["must_cover"]))
        self.assertIn("Claude Code", " ".join(handson["must_cover"]))
        self.assertEqual(len(cases), 12)
        self.assertEqual(sum(len(x["must_cover"]) for x in cases.values()), 24)
        self.assertEqual(sum(len(x["requirements"]) for x in cases.values()), 35)
        self.assertEqual(cases["ai-pm-01"]["requirements"][1]["evidence_fact_indices"], [3])
        self.assertEqual(cases["direction-01"]["requirements"][1]["evidence_fact_indices"], [4, 5])
        self.assertEqual(cases["direction-01"]["opening_fact_indices"][1], [1, 2, 3])
        self.assertEqual(cases["frontend-01"]["opening_fact_indices"][0], [0, 2])
        self.assertEqual(cases["career-switch-01"]["requirements"][0]["expected_status"], "transferable")
        for case in cases.values():
            self.assertEqual(case["truth_review_status"], "approved_by_claude")
            self.assertTrue(case["expected_project_names"])
            for row in case["requirements"]:
                if row["expected_status"] == "gap":
                    self.assertFalse(row["evidence_fact_indices"])
                    self.assertNotIn(row["id"] + " " + row["text"], case["must_cover"])
            for education in case["disclosed_education"]:
                self.assertTrue(all(value in case["truth_facts"][education["fact_index"]] for value in education["fields"].values()))


if __name__ == "__main__":
    unittest.main()
