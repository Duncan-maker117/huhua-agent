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
    def test_f3_edit_prompt_accepts_stage_in_title_and_never_requires_printed_absence(self):
        prompt = judge._EDIT_PROMPT
        for phrase in ("标题行", "任一 bullet", "没有”类事实不要求印出", "不能因“状态限制未出现在 after 的 bullet 里”判为不遵循", "说反"):
            self.assertIn(phrase, prompt)

    def test_negative_absence_printed_is_a_quality_check(self):
        case = {"id": "t", "opening_turns": ["x"], "truth_facts": ["x"], "requirements": []}
        for text, flagged in (("仓库公开；没有星数", True), ("先查候选店铺再编排行程，还没上线", True),
                              ("使用 FastAPI 实现接口并联调", False)):
            _, issues = judge._field_audits(case, resume(text), [], set())
            kinds = [row["kind"] for row in issues]
            self.assertEqual("negative_absence_printed" in kinds, flagged, text)

    def setUp(self):
        self.case = {"id": "test", "jd_text": "岗位需要服务100万用户并上线生产环境。",
                     "opening_turns": ["我整理反馈，做了原型但未上线。"],
                     "truth_facts": ["我整理反馈，做了原型但未上线。", "团队3人，测试30个例子。"],
                     "forbidden": {"numbers": [], "claims": ["上线", "主导", "Java"]},
                     "must_cover": ["r1 整理反馈"],
                     "requirements": [{"id": "r1", "text": "整理反馈", "expected_status": "direct", "evidence_fact_indices": [0]}]}

    def answer(self):
        return {"audits": [{"unit_id": "u001", "verdict": "supported",
                             "observed_quotes": ["我整理反馈"], "truth_quotes": ["我整理反馈"],
                             "unsupported_spans": [], "reason": "对应本人动作。"}],
                "quality": {key: 3 for key in judge.QUALITY_DIMENSIONS},
                "coverage": [{"requirement_id": "r1", "covered": True,
                              "evidence": [{"unit_id": "u001", "quote": "整理反馈", "fact_indices": [0]}]}]}

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

    def test_indefinite_one_quantifiers_are_excluded_but_award_rank_is_checked(self):
        case = {"truth_facts": [], "opening_turns": []}
        for classifier in "个次些种项份名位段条":
            self.assertFalse(judge.deterministic_score(case, resume(f"整理一{classifier}材料。"))["flags"])
        out = judge.deterministic_score(case, resume("获得一等奖。"))
        self.assertEqual(out["flags"][0]["span"], "一")
        self.assertEqual(out["flags"][0]["kind"], "number_not_in_truth")

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
                self.assertIsNone(out["coverage"]["covered"])
                self.assertEqual(out["coverage"]["coverage_of_truth"]["status"], "not_run")

    async def test_truth_only_remains_suspicion_and_is_not_coverage(self):
        answer = self.answer()
        answer["audits"][0].update(verdict="truth_only", observed_quotes=[],
                                  truth_quotes=["团队3人"], reason="仅完整truth出现，尚未披露。")
        answer["coverage"][0]["evidence"][0].update(quote="团队3人", fact_indices=[1])
        self.case["requirements"][0]["evidence_fact_indices"] = [1]
        out = await judge.judge_version(self.case, resume("团队3人。"), FakeLLM(answer))
        self.assertEqual(out["status"], "completed")
        self.assertIsNone(out["coverage"]["ratio"])
        self.assertEqual(out["coverage"]["coverage_of_truth"]["ratio"], 1)
        self.assertEqual(out["factuality"]["suspicions"][0]["quote"], "团队3人。")
        self.assertEqual(out["factuality"]["suspicions"][0]["verdict"], "truth_only")

    async def test_generic_title_routes_to_quality_without_llm_factual_suspicion(self):
        answer = self.answer()
        answer["audits"][0]["unit_id"] = "u002"
        answer["coverage"][0]["evidence"][0]["unit_id"] = "u002"
        data = resume("整理反馈。")
        data["projects"][0]["name"] = "对话中描述的经历"
        model = FakeLLM(answer)
        out = await judge.judge_version(self.case, data, model)
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["quality"], answer["quality"])
        self.assertEqual(out["coverage"]["ratio"], 1)
        self.assertFalse(out["factuality"]["suspicions"])
        self.assertEqual(out["factuality"]["unverifiable_units"][0]["quote"], "对话中描述的经历")
        payload = json.loads(model.calls[0][0][1].content)
        self.assertEqual(payload["assertion_unit_ids"], ["u002"])
        self.assertEqual(len(out["factuality"]["audits"]), 2)
        self.assertIsNone(out["factuality"]["safe"])

    async def test_uncertain_assertion_is_unverifiable_not_suspicion(self):
        answer = self.answer()
        answer["audits"][0].update(verdict="uncertain", observed_quotes=[], unsupported_spans=[])
        answer["coverage"][0].update(covered=False, evidence=[])
        out = await judge.judge_version(self.case, resume("整理反馈。"), FakeLLM(answer))
        self.assertEqual(out["status"], "completed")
        self.assertFalse(out["factuality"]["suspicions"])
        unit = out["factuality"]["unverifiable_units"][0]
        self.assertEqual(unit["verdict"], "uncertain")
        self.assertEqual(unit["unsupported_spans"], ["整理反馈。"])
        self.assertEqual(unit["location_fallback"], "whole_unit_for_uncertain")

    async def test_disclosed_and_truth_coverage_have_distinct_requirements_and_fact_denominators(self):
        case = copy.deepcopy(self.case)
        case["requirements"] = [
            {"id": "r1", "text": "整理反馈", "expected_status": "direct", "evidence_fact_indices": [0, 1]},
            {"id": "r2", "text": "团队测试", "expected_status": "direct", "evidence_fact_indices": [1]},
            {"id": "r3", "text": "生产上线", "expected_status": "gap", "evidence_fact_indices": []},
        ]
        answer = self.answer()
        answer["coverage"] += [{"requirement_id": "r2", "covered": False, "evidence": []},
                               {"requirement_id": "r3", "covered": False, "evidence": []}]
        out = await judge.judge_version(case, resume("整理反馈。"), FakeLLM(answer), disclosed_fact_indices=[0])
        self.assertEqual(out["status"], "completed")
        disclosed = out["coverage"]["coverage_of_disclosed"]
        truth = out["coverage"]["coverage_of_truth"]
        self.assertEqual((disclosed["covered"], disclosed["total"], disclosed["fact_covered"], disclosed["fact_total"]), (1, 1, 1, 1))
        self.assertEqual((truth["covered"], truth["total"], truth["fact_covered"], truth["fact_total"]), (1, 2, 1, 3))
        self.assertIsNone(out["coverage"]["requirements"][1]["disclosed_covered"])
        self.assertFalse(out["coverage"]["gap_requirements"][0]["leaked_into_resume"])

    async def test_wrong_requirement_fact_cannot_receive_coverage(self):
        answer = self.answer()
        # A numerically valid truth index is still invalid for this requirement.
        answer["coverage"][0]["evidence"][0]["fact_indices"] = [1]
        out = await judge.judge_version(self.case, resume("整理反馈。"), FakeLLM(answer), disclosed_fact_indices=[0, 1])
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["validation_error"], "evidence facts outside requirement pool")
        self.assertIsNone(out["coverage"]["covered"])

    async def test_partial_fact_without_allowed_index_cannot_receive_coverage(self):
        answer = self.answer()
        answer["coverage"][0]["evidence"][0]["fact_indices"] = []
        out = await judge.judge_version(self.case, resume("整理反馈。"), FakeLLM(answer), disclosed_fact_indices=[0])
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["validation_error"], "coverage missing allowed fact evidence")
        self.assertEqual(out["unvalidated_result"]["coverage"][0]["evidence"][0]["fact_indices"], [])
        self.assertIsNone(out["coverage"]["covered"])
        # The safe model response for an incomplete fact preserves a quality
        # score but gives no requirement/fact coverage.
        answer["coverage"][0].update(covered=False, evidence=[])
        out = await judge.judge_version(self.case, resume("整理反馈。"), FakeLLM(answer), disclosed_fact_indices=[0])
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["coverage"]["covered"], 0)

    async def test_skill_only_draft_receives_quality_but_no_experience_coverage(self):
        answer = self.answer()
        answer["audits"] = []
        answer["coverage"][0].update(covered=False, evidence=[])
        model = FakeLLM(answer)
        out = await judge.judge_version(self.case, {"skills": ["SQL"]}, model, ["我使用过 SQL。"], [0])
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["quality"], answer["quality"])
        self.assertEqual(out["coverage"]["coverage_of_truth"]["covered"], 0)
        self.assertEqual(json.loads(model.calls[0][0][1].content)["assertion_unit_ids"], [])
        answer["coverage"][0].update(covered=True, evidence=[{"unit_id": "u001", "quote": "SQL", "fact_indices": [0]}])
        bad = await judge.judge_version(self.case, {"skills": ["SQL"]}, FakeLLM(answer), ["我使用过 SQL。"], [0])
        self.assertEqual(bad["status"], "error")
        self.assertEqual(bad["validation_error"], "coverage requires assertion unit")

    async def test_gap_claim_is_separate_and_not_positive_coverage(self):
        case = copy.deepcopy(self.case)
        case["requirements"] = [{"id": "r3", "text": "上线", "expected_status": "gap", "evidence_fact_indices": []}]
        answer = self.answer()
        answer["audits"][0].update(verdict="unsupported", observed_quotes=[], truth_quotes=[], unsupported_spans=["已经上线"], reason="原始事实未上线。")
        answer["coverage"] = [{"requirement_id": "r3", "covered": True,
                                "evidence": [{"unit_id": "u001", "quote": "已经上线", "fact_indices": []}]}]
        out = await judge.judge_version(case, resume("已经上线。"), FakeLLM(answer), disclosed_fact_indices=[0])
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["coverage"]["coverage_of_truth"]["total"], 0)
        self.assertTrue(out["coverage"]["gap_requirements"][0]["leaked_into_resume"])
        self.assertEqual(len(out["factuality"]["suspicions"]), 1)

    async def test_no_draft_has_zero_coverage_and_not_run_keeps_unknown_numerator(self):
        empty = await judge.judge_version(self.case, {}, None, disclosed_fact_indices=[0])
        pending = await judge.judge_version(self.case, resume("整理反馈。"), None, disclosed_fact_indices=[0])
        self.assertEqual(empty["coverage"]["coverage_of_disclosed"]["ratio"], 0)
        self.assertEqual(empty["coverage"]["coverage_of_truth"]["ratio"], 0)
        self.assertIsNone(pending["coverage"]["coverage_of_disclosed"]["covered"])
        self.assertEqual(pending["coverage"]["coverage_of_disclosed"]["total"], 1)

    async def test_project_titles_and_duplicates_are_quality_checks(self):
        case = {"truth_facts": ["我做过项目“借物箱”。"], "expected_project_names": ["借物箱"], "requirements": []}
        observed = ["我做过项目“借物箱”。"]
        data = {"projects": [{"name": "课程", "description": "实现借物箱页面。"},
                             {"name": "的", "description": "补了加载提示。"}]}
        out = await judge.judge_version(case, data, None, observed, [0])
        kinds = [row["kind"] for row in out["quality_checks"]]
        self.assertEqual(kinds.count("project_title_mismatch"), 2)
        self.assertEqual(kinds.count("duplicate_project"), 1)
        self.assertFalse(out["deterministic"]["flags"])
        valid = await judge.judge_version(case, {"projects": [{"name": "借物箱", "description": "补了加载提示。"}]}, None, observed, [0])
        self.assertFalse(valid["quality_checks"])

    async def test_skill_fields_use_disclosed_text_with_ascii_boundaries(self):
        data = {"skills": ["SQLite", "SQL", "Java"]}
        out = await judge.judge_version({"requirements": []}, data, None, ["我使用 SQLite、SQL 和 JavaScript。"], [])
        issues = out["quality_checks"]
        self.assertEqual([row["quote"] for row in issues], ["Java"])
        self.assertEqual(out["factuality"]["statement_unit_count"], 0)
        self.assertFalse(out["factuality"]["suspicions"])

    async def test_objective_must_come_from_direction_or_jd_title_not_jd_skills(self):
        case = {"role_direction": "数据分析实习", "jd_text": "岗位：数据分析实习生\n技能：SQL；职责：数据报表和业务分析。", "requirements": []}
        out = await judge.judge_version(case, {"basic_info": {"objective": "数据分析, SQL, 数据报表, 业务分析"}}, None, ["我想找数据分析实习。"], [])
        issue = next(row for row in out["quality_checks"] if row["kind"] == "objective_unsupported")
        self.assertEqual(issue["unsupported_terms"], ["SQL", "数据报表", "业务分析"])
        self.assertFalse(out["deterministic"]["flags"])

    async def test_only_disclosed_education_is_required_in_visible_education(self):
        case = {"truth_facts": ["我是计算机专业本科在读。"], "requirements": [],
                "disclosed_education": [{"fact_index": 0, "fields": {"major": "计算机", "degree": "本科", "status": "在读"}, "opening_turn_indices": [0]}]}
        undisclosed = await judge.judge_version(case, {}, None, [], [])
        missing = await judge.judge_version(case, {}, None, [case["truth_facts"][0]], [0])
        self.assertFalse(undisclosed["quality_checks"])
        self.assertEqual(missing["quality_checks"][0]["kind"], "education_missing")
        partial = await judge.judge_version(case, {"education": [{"major": "计算机", "degree": "本科"}]}, None, [case["truth_facts"][0]], [0])
        issue = next(row for row in partial["quality_checks"] if row["kind"] == "education_field_missing")
        self.assertEqual(issue["missing_fields"], {"status": "在读"})
        complete = await judge.judge_version(case, {"education": [{"major": "计算机", "degree": "本科在读"}]}, None, [case["truth_facts"][0]], [0])
        self.assertFalse(complete["quality_checks"])

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

    async def test_edit_payload_uses_only_disclosed_material_not_hidden_truth(self):
        case = copy.deepcopy(self.case)
        hidden = "HIDDEN_ONLY_TEAM_CHARTS_731：队友制作可视化图表，本人不负责图表。"
        case["truth_facts"].append(hidden)
        case["jd_text"] = "DISCLOSED_JD_947：数据分析实习，使用 SQL，关注数据质量。"
        case["requirements"] = [{"hidden_pool": "HIDDEN_REQUIREMENT_583"}]
        before = resume("用 SQL 汇总采购流水。核对疑似重复并标记，未删除原始数据。")
        after = resume("用 SQL 汇总采购流水并核对标记疑似重复，未删除原始数据。")
        instruction = "精简成一条，保留已有材料中的本人工作、团队分工和状态限制。"
        observed = ["我用 SQL 汇总采购流水，核对疑似重复并标记，没有删除原始数据。"]
        for supplied in (observed, None):
            with self.subTest(explicit_observed=supplied is not None):
                model = FakeLLM({"followed": True, "reason": "合并了已披露的本人工作和限制。",
                                 "evidence": [{"before_quote": before["projects"][0]["polished_bullets"][0],
                                               "after_quote": after["projects"][0]["polished_bullets"][0]}]})
                out = await judge.judge_edit(case, before, after, instruction, model, supplied)
                self.assertTrue(out["executed"])
                messages = model.calls[0][0]
                payload = json.loads(messages[1].content)
                self.assertEqual(set(payload), {"instruction", "before", "after", "job_context", "observed_facts"})
                self.assertEqual(payload["instruction"], instruction)
                self.assertEqual(payload["job_context"], case["jd_text"])
                self.assertNotIn(case["jd_text"], payload["observed_facts"])
                self.assertEqual(payload["before"], judge._public_units(before))
                self.assertEqual(payload["after"], judge._public_units(after))
                self.assertEqual(payload["observed_facts"], observed if supplied is not None else case["opening_turns"])
                transmitted = "\n".join(message.content for message in messages)
                for marker in (hidden, "HIDDEN_REQUIREMENT_583"):
                    self.assertNotIn(marker, transmitted)

    async def test_edit_direction_context_stays_separate_from_candidate_facts(self):
        for key in ("role_direction", "direction"):
            with self.subTest(direction_key=key):
                case = {key: "数据分析实习", "truth_facts": ["未披露的九千人增长指标"]}
                observed = ["我用 SQL 整理采购数据。"]
                model = FakeLLM({"followed": None, "reason": "只有 SQL 使用，尚不能确定更具体的职责。", "evidence": []})
                await judge.judge_edit(case, resume("整理采购数据。"), resume("用 SQL 整理采购数据。"),
                                      "按已给定方向突出本人工作", model, observed)
                payload = json.loads(model.calls[0][0][1].content)
                self.assertEqual(payload["job_context"], "数据分析实习")
                self.assertEqual(payload["observed_facts"], observed)
                self.assertNotIn("未披露的九千人增长指标", json.dumps(payload, ensure_ascii=False))

    async def test_edit_missing_necessary_evidence_remains_unknown(self):
        model = FakeLLM({"followed": None, "reason": "未披露责任边界，无法确定本轮是否保留完整分工。", "evidence": []})
        out = await judge.judge_edit(self.case, resume("整理反馈并做原型。"),
                                     resume("整理反馈，制作原型。"), "突出完整分工", model, ["我整理反馈。"])
        self.assertEqual(out["status"], "completed")
        self.assertTrue(out["substantive_diff"])
        self.assertIsNone(out["followed"])
        self.assertIsNone(out["executed"])

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
        self.assertEqual(out["winner"], "相当")
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
