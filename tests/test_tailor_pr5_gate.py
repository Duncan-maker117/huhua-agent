"""PR5 gates from the 2026-10-09 handson: edits, answers, generation, education.

Materials are fictional. Storage-boundary cases stay in test_fact_draft_storage.
"""

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.interviewer import compose_interviewer_reply, first_draft_ready  # noqa: E402
from app.agents.resume_graph import _init_state, evaluating_node  # noqa: E402
from app.agents.resume_writer import _without_near_duplicate_rows  # noqa: E402
from app.agents.turn_actions import (  # noqa: E402
    absorb_education, bind_role_followup, choose_edit_plan, deterministic_compound_plan,
    education_confirmation, name_matches, parse_education_fields, render_operation_report,
    uncovered_edit_clauses,
)
from app.services.fact_guard import ngram_overlap  # noqa: E402
from app.services.resume_facts import new_fact  # noqa: E402
from app.services.resume_review import review_resume  # noqa: E402
from app.services.resume_workspace import build_workspace  # noqa: E402


INTRO = "我是江商大计算机大三的。途记基本是我一个人做的，做了行程推荐原型，还没上线。工坊集用 Claude Code 写技能，也做过抖音推广。"
ROLE = "途记基本是我一个人做的，产品方案和代码都是我。先给我出一版看看。"
COMPOUND = "途记更突出 Agent 设计；工坊集写详细一点；补上抖音推广；学校用全称；补上专业。"
CORRECTION = "学校改成江北商业大学，计算机科学与技术专业，本科大三。"


class HandsOnGateTests(unittest.TestCase):
    def test_p1_7_experience_card_reads_facts_not_polished_bullets(self):
        facts = {"projects": [{"item_id": "p1", "name": "工坊集", "facts": [
            {"id": "f1", "text": "做过抖音推广", "source_quote": "做过抖音推广",
             "kind": "action", "status": "active"},
            {"id": "f2", "text": "用 Claude Code 写技能", "source_quote": "用 Claude Code 写技能",
             "kind": "method_tool", "status": "active"}]}],
            "skills": [{"name": "Claude Code", "status": "active", "source_quote": "Claude Code"}]}
        draft = {"projects": [{"item_id": "p1", "name": "工坊集",
                               "polished_bullets": ["写过一个技能原型。"]}]}
        before = deepcopy(facts)
        view = build_workspace({"collected_info": facts, "jd_info": {
            "summary": "你现在只给了 JD，没有给我个人材料。岗位要求原型经验。"}}, draft)
        self.assertEqual(facts, before)
        self.assertEqual(view["experiences"]["items"][0]["bullets"], ["做过抖音推广", "用 Claude Code 写技能"])
        self.assertIn("Claude Code", view["experiences"]["skills"])
        self.assertNotIn("只给了", view["jd"]["info"]["summary"])
        self.assertIn("岗位要求原型经验", view["jd"]["info"]["summary"])

    def test_p1_6_near_duplicate_bullets_do_not_both_pass(self):
        left = "针对初期模型频繁推荐不存在店铺的问题，改为先调用高德查询 POI。"
        right = "针对初期模型经常推荐不存在店铺的问题，改为先用高德查询 POI。"
        self.assertGreaterEqual(ngram_overlap(left, right), 0.6)
        kept = _without_near_duplicate_rows([{"text": left}, {"text": right}, {"text": "另外整理了用户反馈。"}])
        self.assertEqual([row["text"] for row in kept], [left, "另外整理了用户反馈。"])

    def test_p1_8_parenthetical_skill_matches_a_token(self):
        skill = "大模型应用（RAG、Agent、Function Calling 等）"
        checks = review_resume(
            {"projects": [{"name": "途记", "polished_bullets": ["做了 Agent 行程原型。"]}]},
            {"required_skills": [skill]})
        self.assertFalse(any("JD 中这些技能" in check for check in checks))
        missing = review_resume({"skills": ["Excel"]}, {"required_skills": [skill]})
        self.assertTrue(any(skill in check for check in missing))

    def test_p0_4_education_stays_education_and_correction_overwrites(self):
        collected = absorb_education({"projects": [], "education": []}, {}, INTRO, "t1")
        self.assertEqual(collected["projects"], [])
        school = collected["education"][0]
        self.assertEqual(school["school"], "江商大")
        self.assertEqual(school["major"], "计算机")
        self.assertNotIn("江北商业大学", str(collected))
        corrected = absorb_education(collected, collected, CORRECTION, "t2")
        item = corrected["education"][0]
        active = {fact["field"]: fact["text"] for fact in item["facts"] if fact["status"] == "active"}
        self.assertEqual(active["school"], "江北商业大学")
        self.assertEqual(active["major"], "计算机科学与技术")
        self.assertEqual(active["degree"], "本科")
        self.assertEqual(active["grade"], "大三")
        self.assertEqual(sum(fact["field"] == "school" and fact["status"] == "superseded" for fact in item["facts"]), 1)
        self.assertEqual(parse_education_fields("我在大学做了项目"), {})

    def test_p0_2_role_answer_closes_the_same_question(self):
        collected = {"projects": [{"item_id": "p1", "name": "途记", "facts": [
            new_fact("做了行程推荐原型", kind="action"),
            new_fact("还没上线", kind="status_limit")]}]}
        bound = bind_role_followup(
            collected, "「途记」是你独立完成，还是团队协作？", ROLE, "t3")
        role = [fact for fact in bound["projects"][0]["facts"] if fact["kind"] == "role"]
        self.assertEqual(role[0]["source_quote"], ROLE)
        self.assertNotIn("独立", role[0]["text"])
        view = build_workspace({"collected_info": bound}, {"projects": [{
            "item_id": "p1", "name": "途记", "polished_bullets": ["做了行程推荐原型。"]}]})
        self.assertNotIn("你的职责与分工", view["experiences"]["items"][0]["missing"])
        state = {"collected_info": bound, "resume_data": {"projects": [{
            "item_id": "p1", "name": "途记", "polished_bullets": ["做了行程推荐原型。"]}]},
            "jd_info": {"job_title": "AI 产品实习生", "role_profile": {"requirements": [{"id": "r1", "text": "Agent"}]}},
            "match_plan": {"requirements": [{"req_id": "r1", "status": "direct", "fact_ids": ["f-role"]}],
                           "questions": [{"q": "途记是你独立完成还是团队协作？", "why": "分工", "value": 5,
                                          "improves": {"item_id": "p1", "req_id": "r1"}}]},
            "messages": [HumanMessage(content=ROLE)]}
        asked = compose_interviewer_reply(state)["questions"]
        self.assertFalse(any("独立" in row["q"] or "团队" in row["q"] for row in asked))

    def test_p0_3_colloquial_generation_is_ready_once_two_facts_exist(self):
        state = {"messages": [HumanMessage(content=ROLE)],
                 "jd_info": {"job_title": "AI 产品实习生"},
                 "collected_info": {"projects": [{"facts": [new_fact("原型"), new_fact("未上线")]}]}}
        self.assertTrue(first_draft_ready(state))
        self.assertFalse(first_draft_ready({"messages": [HumanMessage(content="先别出一版")],
                                             "jd_info": {},
                                             "collected_info": {"projects": [{"facts": [new_fact("原型")]}]}}))

    def test_p0_1_compound_plan_reports_each_op_from_the_diff(self):
        plan = deterministic_compound_plan(COMPOUND, {"projects": [
            {"name": "途记"}, {"name": "工坊集"}]})
        self.assertGreaterEqual(len(plan), 2)
        self.assertIn("refocus", [row["op"] for row in plan])
        before = {"projects": [{"item_id": "p1", "name": "途记", "polished_bullets": ["旧句"]}]}
        after = deepcopy(before)
        report = render_operation_report(
            [{"op": "refocus", "target": "途记", "status": "done", "reason": "等待 writer 改写",
              "changed": False, "affected_item_ids": ["p1"]},
             {"op": "rewrite", "target": "工坊集", "status": "needs_confirmation", "reason": "没有找到指定经历"}],
            before, after)
        self.assertTrue(any(line.startswith("❌") and "途记" in line for line in report))
        self.assertTrue(any(line.startswith("⚠") and "工坊集" in line for line in report))
        self.assertNotIn("调整了", "\n".join(report))


class ReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.data = {"projects": [
            {"item_id": "p1", "name": "mtagent", "polished_bullets": ["旧句"]},
            {"item_id": "p2", "name": "Forge Skill", "polished_bullets": ["旧句"], "hidden": True},
        ]}

    def test_b1_rules_do_not_replace_a_model_plan_and_unmatched_clauses_are_reported(self):
        message = "按JD再改改，mtagent突出一下agent设计和我解决幻觉那块，forge写详细点，抖音推广也写上。学校写全称哈尔滨商业大学，计算机科学与技术专业"
        model_plan = [{"op": "refocus", "target": "mtagent", "args": {}}]
        plan = choose_edit_plan(message, self.data, model_plan, router_failed=False)
        self.assertEqual(plan[0], model_plan[0])
        self.assertTrue(any(name_matches("forge", row.get("target", "")) for row in plan))
        self.assertFalse(name_matches("mt", "mtagent"))
        self.assertTrue(name_matches("forge", "Forge Skill"))
        gaps = uncovered_edit_clauses(message, plan, self.data)
        self.assertTrue(any("抖音推广" in row["reason"] for row in gaps))
        self.assertTrue(all(row["status"] == "needs_confirmation" for row in gaps))

    def test_b1_router_failure_keeps_ordinal_delete_and_page_limit(self):
        message = "第二个项目删了吧，然后整体压成一页"
        plan = choose_edit_plan(message, self.data, [{"op": "rewrite", "target": "whole", "args": {}}],
                                router_failed=True)
        self.assertTrue(any(row["op"] == "hide_item" and "第二" in row["target"] for row in plan))
        self.assertTrue(any(row["op"] == "set_constraint" and row["args"].get("page_limit") == 1 for row in plan))
        forge = choose_edit_plan("把forge那段补一句抖音推广的事", self.data, [], router_failed=True)
        self.assertEqual(forge[0]["op"], "rewrite")
        self.assertEqual(forge[0]["target"], "Forge Skill")

    def test_nested_model_args_do_not_crash_plan_merge(self):
        message = "途记更突出 Agent 设计；工坊集写详细一点"
        data = {"projects": [{"item_id": "p1", "name": "途记"}, {"item_id": "p2", "name": "工坊集"}]}
        plan = choose_edit_plan(message, data, [
            {"op": "refocus", "target": "途记", "args": {"focus": ["Agent 设计"]}},
        ])
        self.assertEqual(plan[0]["args"]["focus"], ["Agent 设计"])
        self.assertTrue(any(row["op"] == "rewrite" and row["target"] == "工坊集" for row in plan))

    def test_b2_school_values_are_continuous_source_spans(self):
        self.assertEqual(parse_education_fields("学校写全称哈尔滨商业大学")["school"], "哈尔滨商业大学")
        self.assertEqual(parse_education_fields("学校填哈尔滨商业大学吧")["school"], "哈尔滨商业大学")
        fields = parse_education_fields("我在哈工大读软工，大三")
        self.assertEqual(fields["school"], "哈工大")
        self.assertEqual(fields["major"], "软工")
        self.assertEqual(fields["grade"], "大三")
        self.assertIn("哈工大", education_confirmation(fields))
        self.assertNotIn("写全称", str(fields))


class EditReceiptGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_named_failure_is_not_described_as_a_successful_edit(self):
        from app.services.resume_facts import normalize_fact_store
        state = _init_state()
        state["stage"] = "EVALUATING"
        state["candidate_history_reconciled"] = True
        state["collected_info"] = normalize_fact_store({"projects": [
            {"item_id": "p1", "name": "途记", "description": "做了行程推荐原型，还没上线。"}]})
        state["resume_data"] = {"basic_info": {"name": "江同学"}, "projects": [{
            "item_id": state["collected_info"]["projects"][0]["item_id"], "name": "途记",
            "polished_bullets": ["做了行程推荐原型，还没上线。"]}]}
        state["messages"] = [HumanMessage(content="把途记改得更突出 Agent 设计，但不要编造成果。")]

        async def writer(collected_info, role_profile, llm, **kwargs):
            data = deepcopy(kwargs["current_data"])
            return {"resume_data": data, "resume_meta": deepcopy(kwargs["resume_meta"]),
                    "match_plan": {}, "omitted": [], "guard_fallbacks": [],
                    "change_summary": ["调整了 1 段经历的表述或顺序。"], "changed_items": []}

        with patch("app.agents.tailor_pipeline.run_resume_writer", side_effect=writer), \
                patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value={
                    "status": "rendered", "pages": 1, "page_limit": 1, "within_page_limit": True}), \
                patch("app.agents.resume_graph._recover_candidate_history",
                      new=AsyncMock(side_effect=lambda current, model: current["collected_info"])):
            result = await evaluating_node(state, object())
        reply = result["messages"][0].content
        self.assertNotIn("调整了 1 段经历", reply)
        self.assertIn("❌", reply)
        self.assertIn("途记", reply)


if __name__ == "__main__":
    unittest.main()
