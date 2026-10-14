"""Acceptance checks must pass faithful drafts and reject known online failures.

Old data below is manually reconstructed from explicit preview_texts indices;
capture files contain multiple iframe versions, so never guess the latest index.
These tests do not assert the current backend still has those defects.
"""
from copy import deepcopy
import json
import unittest

from persona_support import checks, golden_data, golden_turns, MATERIALS


def captured(filename, index):
    return json.loads((MATERIALS / filename).read_text(encoding="utf-8"))["preview_texts"][index]


class PersonaChecksTests(unittest.TestCase):
    def assert_failure(self, persona, turns, *suffixes):
        by_id = {c["id"]: c for c in checks.evaluate_persona(persona, turns)}
        for suffix in suffixes:
            with self.subTest(assertion=suffix):
                row = by_id[f"{persona}.{suffix}"]
                self.assertEqual(row["status"], "fail", row)
                self.assertTrue(row["evidence"])
        return by_id

    def test_faithful_examples_pass_every_assertion_with_and_without_recovery(self):
        for recovery in (False, True):
            for persona in checks.PERSONAS:
                with self.subTest(persona=persona, recovery=recovery):
                    before = golden_turns(persona, recovery)
                    frozen = deepcopy(before)
                    results = checks.evaluate_persona(persona, before, with_recovery=recovery)
                    self.assertTrue(all(c["status"] == "pass" for c in results), [c for c in results if c["status"] != "pass"])
                    self.assertEqual(before, frozen)
                    self.assertEqual(len({c["id"] for c in results}), len(results))

    def test_missing_turns_never_pass_the_complete_gate(self):
        for persona in checks.PERSONAS:
            with self.subTest(persona=persona):
                self.assert_failure(persona, [], "common.rounds_complete", "common.first_draft")
                self.assert_failure(persona, golden_turns(persona)[:-1], "common.rounds_complete")
        with self.assertRaises(ValueError):
            checks.evaluate_persona("unknown", [])

    def test_initial_plan_card_uses_only_its_own_confirmed_draft(self):
        for persona in ('service', 'design', 'ops'):
            turns = golden_turns(persona)
            confirmed = deepcopy(turns[0])
            confirmed.update(action='initial_confirm', trigger_action='initial', kind='confirmation', input='按推荐写')
            turns[0].update(resume_data={}, reply='先确认方案。')
            turns.insert(1, confirmed)
            results = checks.evaluate_persona(persona, turns)
            self.assertTrue(all(row['status'] == 'pass' for row in results), [r for r in results if r['status'] == 'fail'])
            # Later polish/paste cannot rescue a missing confirmation draft.
            confirmed['resume_data'] = {}
            self.assert_failure(persona, turns, 'common.first_draft')

    def test_confirmation_cannot_hide_a_lost_direct_draft_or_later_regression(self):
        turns = golden_turns('service')
        confirmed = deepcopy(turns[0])
        confirmed.update(action='initial_confirm', trigger_action='initial', kind='confirmation', input='按推荐写')
        turns[0].update(input='材料已给全，请直接生成简历', resume_data={})
        turns.insert(1, confirmed)
        self.assert_failure('service', turns, 'common.direct_first_draft')
        turns[-1]['resume_data']['education'] = []
        self.assert_failure('service', turns, 'single_education', 'school_clean')

    def test_old_tech_major_and_uncorrected_170_are_rejected(self):
        turns = golden_turns("tech")
        polish = captured("tech-capture-014735.json", 1)
        corrected = captured("tech-capture-014907.json", 0)
        self.assertIn("请把实习经历润色得更", polish)
        self.assertIn("170ms", corrected)
        self.assertNotIn("190ms", corrected)
        turns[1]["resume_data"]["education"][0]["major"] = "请把实习经历润色得更"
        turns[2]["resume_data"]["education"] = deepcopy(turns[1]["resume_data"]["education"])
        turns[2]["resume_data"]["work_experience"][0]["bullets"] = [line for line in corrected.splitlines() if "接口" in line or "420ms" in line]
        self.assert_failure("tech", turns, "polish_identity", "correction_190")

    def test_old_tech_split_project_and_missing_skills(self):
        text = captured("tech-capture-014735.json", 0)
        self.assertIn("[待补]", text)
        self.assertNotIn("Java", text.split("技能证书", 1)[1])
        turns = golden_turns("tech")
        for turn in turns:
            turn["resume_data"]["projects"].insert(0, {"name": "[待补]", "description": "课程作业"})
            turn["resume_data"]["skills"] = ["Spring Boot", "MySQL"]
        self.assert_failure("tech", turns, "single_project", "skills")

    def test_recovery_cannot_hide_initial_omission_or_empty_confirmation_gate(self):
        turns = golden_turns("tech", True)
        turns[0]["resume_data"] = {"education": deepcopy(turns[0]["resume_data"]["education"])}
        results = checks.evaluate_persona("tech", turns, with_recovery=True)
        self.assertEqual(next(c["status"] for c in results if c["id"] == "tech.initial_internship"), "fail")
        self.assertEqual(next(c["status"] for c in results if c["id"] == "tech.common.direct_first_draft"), "fail")
        confirmed = deepcopy(turns[1]); confirmed.update(action="initial_confirm", trigger_action="initial", kind="confirmation")
        turns.insert(1, confirmed)
        results = {c["id"]: c for c in checks.evaluate_persona("tech", turns, with_recovery=True)}
        self.assertEqual(results["tech.initial_internship"]["status"], "pass")
        self.assertEqual(results["tech.common.direct_first_draft"]["status"], "fail")

    def test_old_ops_wrong_ownership_duplicates_and_missing_dates(self):
        text = captured("ops-capture-014735.json", 0)
        self.assertIn("写过推文\n帮店长做海报\n[待补]\n完成 4 张促销海报", text)
        turns = golden_turns("ops")
        for turn in turns[1:]:
            data = turn["resume_data"]
            data["campus"] = [{"name": "校园读书协会", "bullets": ["完成8篇文章排版，其中3篇初稿由本人撰写。", "写过推文", "帮店长做海报"]},
                              {"name": "[待补]", "bullets": ["完成4张促销海报设计。"]}]
            data["work_experience"][0]["bullets"] = ["拍摄6条素材，其中2条被店长发布。", "拍过店里的短视频"]
        self.assert_failure("ops", turns, "posters_ownership", "no_placeholder_campus", "no_raw_duplicates", "association_dates")
        for start, end in (("2024年9月", "2025年6月"), ("2024.9", "2025-06")):
            turns = golden_turns("ops")
            for turn in turns[1:]:
                turn["resume_data"]["campus"][0].update(start_date=start, end_date=end)
            self.assertEqual(next(c["status"] for c in checks.evaluate_persona("ops", turns) if c["id"] == "ops.association_dates"), "pass")

    def test_old_career_input_dump_and_training_correction(self):
        raw = captured("career-capture-014706.json", 0)
        after = captured("career-capture-015028.json", 1)
        self.assertIn("对话中描述的经历", raw)
        self.assertIn("6 场", after)
        turns = golden_turns("career")
        turns[0]["resume_data"] = {"projects": [{"name": "对话中描述的经历", "description": raw}]}
        for turn in turns[1:]:
            turn["resume_data"]["work_experience"][0]["bullets"] = [line for line in after.splitlines() if "报销" in line or "培训" in line or "访客" in line]
        self.assert_failure("career", turns, "no_instruction_body", "correction_four", "retained_duties")

    def test_old_service_duplicate_prefixed_school_and_corrupted_major(self):
        initial = captured("service-capture-015139.json", 0)
        polish = captured("service-capture-015251.json", 0)
        self.assertEqual(initial.count("在新城职业学院"), 2)
        self.assertIn("写得更", polish)
        turns = golden_turns("service")
        for turn in turns:
            turn["resume_data"]["education"][0]["school"] = "在新城职业学院"
            turn["resume_data"]["education"].append(deepcopy(turn["resume_data"]["education"][0]))
        turns[1]["resume_data"]["education"][0]["major"] = "写得更"
        self.assert_failure("service", turns, "single_education", "school_clean", "polish_identity", "polish_education", "no_instruction_major")

    def test_old_design_missing_course_major_negative_skills(self):
        text = captured("design-capture-015028.json", 0)
        self.assertNotIn("借物", text)
        self.assertIn("开发：没有前端", text)
        turns = golden_turns("design")
        for turn in turns:
            turn["resume_data"]["projects"] = []
            turn["resume_data"]["education"][0]["major"] = ""
            turn["resume_data"]["skills"].append("没有前端")
        turns[0]["workspace"] = {"jd": {"raw_text": "许禾的借物 App，12个页面和18个组件"}}
        self.assert_failure("design", turns, "initial_project", "initial_education_major", "attachment_not_jd", "no_negative_skills", "single_course_project")

    def test_hidden_or_removed_section_cannot_prove_delivered_experience(self):
        turns = golden_turns("design")
        turns[0]["resume_data"]["projects"][0]["hidden"] = True
        self.assert_failure("design", turns, "initial_project", "attachment_not_jd")
        turns[0]["resume_data"]["projects"][0].pop("hidden")
        turns[0]["resume_data"]["sections"] = [{"kind": "education"}, {"kind": "campus"}]
        self.assert_failure("design", turns, "initial_project")

    def test_stale_description_and_workspace_are_not_current_body(self):
        turns = golden_turns("tech")
        turns[2]["resume_data"]["work_experience"][0]["bullets"][2] = "尚未记录性能数字。"
        turns[2]["workspace"] = {"experiences": {"items": [{"bullets": ["190ms"]}]}}
        self.assert_failure("tech", turns, "correction_190")
        turns = golden_turns("design")
        project = turns[0]["resume_data"]["projects"][0]
        project["description"] = "借物 App，12个页面和18个组件。"
        project["polished_bullets"] = ["只有概念草图。"]
        self.assert_failure("design", turns, "initial_project")

    def test_numeric_change_detects_other_number_loss_even_if_190_exists(self):
        turns = golden_turns("tech")
        turns[2]["resume_data"]["work_experience"][0]["bullets"][3] = "编写11条接口测试用例。"
        self.assert_failure("tech", turns, "correction_other_numbers")
        turns = golden_turns("career")
        turns[2]["resume_data"]["work_experience"][0]["bullets"][1] = "维护121人员工通讯录。"
        self.assert_failure("career", turns, "correction_other_numbers")

    def test_tech_lost_limits_or_unrelated_polish_are_failures(self):
        for suffix, old, new in (("mentor", "导师指导", "同事帮助"), ("test_environment", "测试环境", "生产环境"),
                                 ("no_online_load", "没做线上压测", "完成线上压测"), ("team_scope", "登录模块由同学实现", "独立完成登录模块")):
            with self.subTest(suffix=suffix):
                turns = golden_turns("tech")
                turns[1]["resume_data"] = json.loads(json.dumps(turns[1]["resume_data"], ensure_ascii=False).replace(old, new))
                self.assert_failure("tech", turns, suffix)
        turns = golden_turns("tech")
        turns[1]["resume_data"]["projects"][0]["polished_bullets"].append("无关改稿。")
        self.assert_failure("tech", turns, "polish_scope")

    def test_kubernetes_and_upgraded_redis_do_not_pass_skills(self):
        for skills in (["Java", "Git", "熟练Redis"], ["Java", "Git", "Redis（了解）", "不会Kubernetes"]):
            turns = golden_turns("tech")
            turns[1]["resume_data"]["skills"] = skills
            self.assert_failure("tech", turns, "skills")
        turns = golden_turns("tech")
        turns[1]["resume_data"]["skills"] = ["会用Java", "使用Git", "了解Redis"]
        self.assertEqual(next(c["status"] for c in checks.evaluate_persona("tech", turns) if c["id"] == "tech.skills"), "pass")

    def test_no_readership_question_in_public_or_guidance(self):
        turns = golden_turns("ops")
        turns[1]["reply"] = "没有阅读量数据，所以不填写阅读量。"
        self.assertEqual(next(c["status"] for c in checks.evaluate_persona("ops", turns) if c["id"] == "ops.no_readership_followup"), "pass")
        for target in ("reply", "guidance"):
            with self.subTest(target=target):
                turns = golden_turns("ops")
                if target == "reply":
                    turns[1]["reply"] = "需要你补充：能否找一下阅读量？"
                else:
                    turns[1]["workspace"] = {"guidance": {"question": "能否补充阅读量？"}}
                self.assert_failure("ops", turns, "no_readership_followup")

    def test_backup_requires_explicit_same_version_review_omission(self):
        turns = golden_turns("career")
        turns[1]["resume_data"]["work_experience"][0]["bullets"].pop(1)
        turns[1]["workspace"] = {"experiences": {"items": [{"bullets": ["维护120人员工通讯录。"]}]}}
        self.assert_failure("career", turns, "retained_duties")
        turns[1]["workspace"]["tailor"] = {"resume_meta": {"fact_coverage": {"facts": [
            {"status": "omitted", "reason": "篇幅取舍，保留备用", "text": "维护120人员工通讯录。"}]}}}
        result = {c["id"]: c for c in checks.evaluate_persona("career", turns)}
        self.assertEqual(result["career.retained_duties"]["status"], "pass")

    def test_service_limit_and_volume_removal_are_failures(self):
        for suffix, old, new in (("approval_limit", "退款提交主管审批", "独立决定退款"),
                                 ("complaint_limit", "复杂投诉转交主管跟进", "独立解决复杂投诉"),
                                 ("volume_800", "800次咨询", "700次咨询")):
            turns = golden_turns("service")
            turns[1]["resume_data"] = json.loads(json.dumps(turns[1]["resume_data"], ensure_ascii=False).replace(old, new))
            self.assert_failure("service", turns, suffix)

    def test_common_language_question_error_and_order_gates(self):
        for suffix, patch in (("common.one_question", {"reply": "需要你补充A。需要你补充B。"}),
                              ("common.public_language", {"reply": "internship project 当前排版为 0 档"}),
                              ("common.rounds_complete", {"status": "error", "error": "HTTP 500"}),
                              ("common.rounds_complete", {"sse_done": False})):
            turns = golden_turns("service")
            turns[1].update(patch)
            self.assert_failure("service", turns, suffix)
        self.assert_failure("service", list(reversed(golden_turns("service"))), "common.rounds_complete")

    def test_one_supplement_heading_cannot_hide_multiple_questions(self):
        for reply in ("需要你补充：\n- 学校名称？\n- 毕业日期？", "需要你补充：学校是什么？毕业是什么时候？"):
            turns = golden_turns("service")
            turns[1]["reply"] = reply
            self.assert_failure("service", turns, "common.one_question")
        self.assertEqual(checks.supplement_questions("**需要你补充**\n公司名称？\n**已写入**\n- 咨询\n- 物流"), 1)

    def test_headers_only_are_not_an_experience_draft(self):
        turns = golden_turns("tech")
        turns[0]["resume_data"] = {"education": turns[0]["resume_data"]["education"], "projects": [{"name": "校园二手交易系统"}]}
        self.assert_failure("tech", turns, "common.first_draft", "common.direct_first_draft")

    def test_positive_fabrications_are_rejected(self):
        for persona, suffix, claim in (("ops", "no_invented_operations", "独立运营账号，粉丝增长100%。"),
                                       ("career", "no_invented_customer_outcomes", "负责客户续费，熟练使用CRM。"),
                                       ("design", "no_invented_design_results", "产品成功上线，验证转化率。")):
            turns = golden_turns(persona)
            key = "projects" if persona == "design" else "work_experience"
            field = "polished_bullets" if persona == "design" else "bullets"
            turns[-1]["resume_data"][key][0][field].append(claim)
            self.assert_failure(persona, turns, suffix)

    def test_negative_limits_are_not_mistaken_for_positive_fabrications(self):
        for persona, suffix, claim in (("ops", "no_invented_operations", "没有独立运营，没有粉丝增长。"),
                                       ("career", "no_invented_customer_outcomes", "没有使用过CRM，未负责客户续费。"),
                                       ("design", "no_invented_design_results", "没有验证转化率，未正式上线。")):
            turns = golden_turns(persona)
            key = "projects" if persona == "design" else "work_experience"
            field = "polished_bullets" if persona == "design" else "bullets"
            turns[-1]["resume_data"][key][0][field].append(claim)
            results = {c["id"]: c for c in checks.evaluate_persona(persona, turns)}
            self.assertEqual(results[f"{persona}.{suffix}"]["status"], "pass")

    def test_company_material_in_wrong_section_cannot_pass_first_draft(self):
        for persona, suffix in (("tech", "initial_internship"), ("career", "initial_named_work")):
            turns = golden_turns(persona)
            company = turns[0]["resume_data"]["work_experience"].pop()
            turns[0]["resume_data"]["projects"].append({"name": company["company"], "description": "\n".join(company["bullets"])})
            self.assert_failure(persona, turns, suffix)

    def test_role_evidence_missing_and_other_scope_changes(self):
        turns = golden_turns("career")
        for turn in turns:
            turn["reply"] = "已更新。"
        self.assert_failure("career", turns, "transition_evidence_gaps")
        for persona in ("ops", "career", "service", "design"):
            turns = golden_turns(persona)
            next(t for t in turns if t["action"] == "polish")["resume_data"]["basic_info"]["name"] = "错误姓名"
            self.assert_failure(persona, turns, "polish_scope")
