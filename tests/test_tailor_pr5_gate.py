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
    uncovered_edit_clauses, writing_constraints, detail_gap_rows,
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
        # 句尾「先给我出一版看看」是指令不是事实，不得进入事实原文
        self.assertEqual(role[0]["source_quote"], "途记基本是我一个人做的，产品方案和代码都是我。")
        self.assertNotIn("先给我", role[0]["text"])
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

    def test_unrequested_field_edit_stays_off_the_receipt(self):
        before = {"education": [{"item_id": "e1", "school": "江商大", "major": "计算机", "degree": ""}]}
        after = {"education": [{"item_id": "e1", "school": "江北商业大学", "major": "计算机科学与技术", "degree": "本科"}]}
        lines = render_operation_report([
            {"op": "set_field", "target": "p1", "status": "needs_confirmation",
             "reason": "该页眉值还没有对应的 active fact"},
            {"op": "set_field", "target": "e1", "field": "school", "status": "cannot",
             "reason": "仅能设置已确认的经历页眉字段"},
            {"op": "set_field", "target": "e1", "field": "major", "status": "done", "changed": True},
            {"op": "set_field", "target": "e1", "field": "degree", "status": "done", "changed": True},
            {"op": "set_field", "target": "e1", "status": "cannot", "reason": "仅能设置已确认的经历页眉字段"},
        ], before, after)
        self.assertEqual(lines, ["✅ 修改学校", "✅ 修改专业", "✅ 修改学历"])
        plan = choose_edit_plan(
            "途记基本是我一个人做的，产品方案和代码都是我。先给我出一版看看。",
            {"projects": [{"item_id": "p1", "name": "途记"}]},
            [{"op": "set_field", "target": "p1", "args": {"field": "role", "value": "独立完成"}}],
        )
        self.assertFalse(any(row["op"] == "set_field" for row in plan))

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


ROUND5 = "途记更突出 Agent 设计；工坊集写详细一点；简历里保留抖音推广和 Claude Code；不要编造用户量。"
INTERNAL_NAMES = ("understand", "whole", "set_field", "set_constraint", "refocus", "rewrite",
                  "honor", "hide_item", "clean_format", "needs_confirmation")


def _receipt(message, model_plan, before, after):
    """Mirror the graph: executed ops + writing rules + uncovered clauses, then the receipt."""
    from app.services.edit_plan import execute_edit_plan
    plan = choose_edit_plan(message, before, model_plan)
    executed = execute_edit_plan(before, {}, plan, collected_info={}, instruction=message)
    rows = list(executed["operation_results"]) + writing_constraints(message) + uncovered_edit_clauses(
        message, [*executed["operation_results"], *plan], before)
    return plan, render_operation_report(rows, before, after)


class Q3ReceiptTests(unittest.TestCase):
    """评审 Q3：回执不自相矛盾、不泄露内部名、以执行前后文稿为准。"""

    before = {"projects": [{"item_id": "p1", "name": "途记", "polished_bullets": ["a"]},
                           {"item_id": "p2", "name": "工坊集", "polished_bullets": ["b"]}],
              "education": [{"item_id": "e1", "school": "江商大", "major": "计算机", "degree": ""}]}

    def after(self, **changes):
        document = deepcopy(self.before)
        if changes.get("p1"):
            document["projects"][0]["polished_bullets"] = ["a2"]
        if changes.get("p2"):
            document["projects"][1]["polished_bullets"] = ["b2"]
        return document

    def test_covered_clause_never_also_reports_not_understood(self):
        model_plan = [{"op": "refocus", "target": "途记", "args": {"focus": ["Agent 设计"]}},
                      {"op": "rewrite", "target": "工坊集", "args": {}},
                      {"op": "set_constraint", "target": "whole", "args": {}}]
        plan, lines = _receipt(ROUND5, model_plan, self.before, self.after(p1=True, p2=True))
        self.assertFalse(any(row["op"] == "set_constraint" for row in plan))
        self.assertFalse(any("没理解" in line for line in lines), lines)
        self.assertIn("✅ 调整重点 途记", lines)
        self.assertIn("✅ 改写 工坊集", lines)
        # 同一子句即使模型只给了动词、目标写成别名，也不得再出现没理解
        self.assertEqual(uncovered_edit_clauses("工坊集写详细一点", [{"op": "rewrite", "target": "p2"}], self.before), [])
        self.assertEqual(uncovered_edit_clauses("途记更突出 Agent 设计", [{"op": "refocus", "target": "途记"}], self.before), [])

    def test_receipt_text_never_contains_internal_op_names(self):
        model_plan = [{"op": "refocus", "target": "途记", "args": {}},
                      {"op": "set_constraint", "target": "whole", "args": {}},
                      {"op": "set_field", "target": "p1", "args": {"field": "role", "value": "独立"}}]
        for after in (self.after(p1=True), self.after()):
            _, lines = _receipt(ROUND5, model_plan, self.before, after)
            text = "\n".join(lines)
            for name in INTERNAL_NAMES:
                self.assertNotIn(name, text)
        lines = render_operation_report(
            [{"op": "understand", "target": "x", "status": "needs_confirmation", "reason": "这项我没理解：『x』"},
             {"op": "set_constraint", "target": "whole", "status": "cannot", "reason": "没有可设置的约束"},
             {"op": "set_field", "target": "e1", "field": "school", "status": "done", "changed": True}],
            self.before, self.after())
        for line in lines:
            for name in INTERNAL_NAMES:
                self.assertNotIn(name, line)

    def test_do_not_fabricate_is_a_writing_rule_not_a_constraint(self):
        plan = choose_edit_plan(ROUND5, self.before, [{"op": "set_constraint", "target": "whole", "args": {"x": 1}}])
        self.assertFalse(any(row["op"] == "set_constraint" for row in plan))
        rows = writing_constraints("不要编造用户量")
        self.assertEqual([row["target"] for row in rows], ["用户量"])
        _, lines = _receipt(ROUND5, [], self.before, self.after(p1=True, p2=True))
        self.assertIn("✅ 已遵守：未写用户量", lines)
        self.assertFalse(any("篇幅" in line or "约束" in line for line in lines), lines)
        # 真正的页数要求仍是约束
        page = choose_edit_plan("压成一页，不要编造用户量", self.before,
                                [{"op": "set_constraint", "target": "whole", "args": {"page_limit": 1}}])
        self.assertTrue(any(row["op"] == "set_constraint" for row in page))

    def test_education_receipt_follows_the_actual_before_after_diff(self):
        message = "学校改成江北商业大学，计算机科学与技术专业，本科大三。"
        after = deepcopy(self.before)
        after["education"][0].update(school="江北商业大学", major="计算机科学与技术", degree="本科")
        failed = [{"op": "set_field", "target": "e1", "field": "school", "status": "cannot",
                   "reason": "仅能设置已确认的经历页眉字段"},
                  {"op": "set_field", "target": "e1", "field": "degree", "status": "cannot",
                   "reason": "仅能设置已确认的经历页眉字段"}]
        lines = render_operation_report(failed, self.before, after)
        self.assertTrue(lines and all(line.startswith("✅") for line in lines), lines)
        self.assertFalse(any("❌" in line for line in lines))
        # 文稿没变时，不能谎报成功
        lines = render_operation_report(
            [{"op": "set_field", "target": "e1", "field": "school", "status": "done", "changed": True}],
            self.before, self.before)
        self.assertFalse(any(line.startswith("✅") for line in lines), lines)

    def test_unrequested_ops_do_not_reach_the_receipt(self):
        answer = "途记基本是我一个人做的，产品方案和代码都是我。先给我出一版看看。"
        plan, lines = _receipt(answer, [{"op": "set_field", "target": "p1", "args": {"field": "role", "value": "独立完成"}}],
                               self.before, self.after(p1=True))
        self.assertFalse(any(row["op"] == "set_field" for row in plan))
        self.assertFalse(any("页眉" in line or "active fact" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()


class Q4Tests(unittest.IsolatedAsyncioTestCase):
    async def test_q4_2_answer_without_new_facts_closes_question_without_rewrite(self):
        state = _init_state()
        state["stage"] = "EVALUATING"
        state["resume_data"] = {"basic_info": {"name": "江同学"}, "projects": [
            {"item_id": "p1", "name": "途记", "polished_bullets": ["做了行程推荐原型"]}]}
        state["messages"] = [HumanMessage(content="这方面我没有更多可以确认的信息，请只使用我已经提供的内容。")]
        with patch("app.agents.resume_graph._write_resume_update", new=AsyncMock(
                side_effect=AssertionError("无新事实的回答不得触发重写"))):
            result = await evaluating_node(state, object())
        self.assertFalse({"resume_data", "resume_versions", "change_summary", "collected_info"} & set(result))
        self.assertNotIn("调整了", result["messages"][0].content)

    async def test_q4_3_tool_named_only_in_an_experience_reaches_the_skill_area(self):
        from app.agents.resume_writer import run_resume_writer
        quote = "用 Claude Code 写技能"
        source = {"projects": [{"item_id": "p2", "name": "工坊集", "facts": [
            {"id": "f1", "kind": "method_tool", "text": quote, "source_quote": quote, "status": "active"}]}]}

        class Model:
            def with_structured_output(self, schema):
                return self

            async def ainvoke(self, messages):
                return {"match_plan": {"requirements": [], "experience_plan": [{"item_id": "p2", "treatment": "keep"}]},
                        "writer": {"items": [{"item_id": "p2", "section": "projects",
                                              "bullets": [{"text": "用 Claude Code 编写技能", "fact_ids": ["f1"]}]}],
                                   "skill_groups": {}}}

        result = await run_resume_writer(source, {}, Model())
        data = result["resume_data"]
        names = [skill for values in (data.get("skill_groups") or {}).values() for skill in values] + list(data.get("skills") or [])
        self.assertIn("Claude Code", names)

    def test_q4_4_reasoning_is_explained_once_and_transferable_is_specific(self):
        facts = {"projects": [{"item_id": "p1", "name": "工坊集", "facts": [
            {"id": "f1", "kind": "action", "text": "公开仓库", "source_quote": "仓库是公开的", "status": "active"}]}]}
        plan = {"requirements": [{"req_id": "r1", "status": "transferable", "fact_ids": ["f1"]}],
                "experience_plan": [{"item_id": "p1", "treatment": "lead", "req_ids": ["r1"]}]}
        profile = {"requirements": [{"id": "r1", "text": "开源协作"}]}
        base = {"collected_info": facts, "resume_data": {"projects": [{"item_id": "p1", "name": "工坊集"}]},
                "resume_versions": [{}], "resume_meta": {}}
        first = compose_interviewer_reply(base, match_plan=plan, role_profile=profile)["text"]
        self.assertIn("这版的思路", first)
        self.assertIn("「开源协作」由工坊集", first)
        self.assertNotIn("部分岗位要求由相邻经历支持", first)
        later = {**base, "resume_versions": [{}, {}], "resume_meta": {"match_plan": plan}}
        again = compose_interviewer_reply(later, match_plan=plan, role_profile=profile)["text"]
        self.assertNotIn("这版的思路", again)
        self.assertNotIn("可迁移表述", again)


class HandsOnLiveFindingsTests(unittest.IsolatedAsyncioTestCase):
    """handson-01 实测发现：用户原话「我一个人做的」应能支持「独立完成」，阶段词不单独成 bullet。"""

    def test_one_person_statement_supports_independent_and_responsible(self):
        from app.services.fact_guard import lexical_fact_errors
        source = "途记基本是我一个人做的，产品方案和代码都是我。"
        for text in ("独立完成途记的产品方案与代码实现", "负责途记的产品方案与代码"):
            self.assertEqual(lexical_fact_errors(text, source), [], text)
        # 没有这句话时仍然拦截
        self.assertTrue(lexical_fact_errors("独立完成途记的代码实现", "我参与了途记的代码实现"))
        self.assertTrue(lexical_fact_errors("负责途记的代码实现", "我参与了途记的代码实现"))

    def test_bare_stage_word_is_not_a_fallback_bullet(self):
        from app.agents.resume_writer import _fallback_bullet
        facts = {"f1": {"id": "f1", "item_id": "p1", "kind": "status_limit", "text": "课程原型"},
                 "f2": {"id": "f2", "item_id": "p1", "kind": "action", "text": "做了行程推荐原型；没有用户量"}}
        text, refs = _fallback_bullet("p1", ["f1", "f2"], facts)
        self.assertEqual((text, refs), ("做了行程推荐原型", ["f2"]))
        self.assertEqual(_fallback_bullet("p1", ["f1"], {"f1": facts["f1"]}), ("", []))


class DeterministicOnlyTests(unittest.IsolatedAsyncioTestCase):
    """R1：只改教育字段时不调用 writer，项目/经历正文逐字不变。"""

    async def run_turn(self, message):
        from app.services.resume_facts import normalize_fact_store
        state = _init_state()
        state["stage"] = "EVALUATING"
        state["candidate_history_reconciled"] = True
        state["collected_info"] = normalize_fact_store({
            "projects": [{"item_id": "p1", "name": "途记", "description": "做行程推荐原型。"}],
            "education": [{"item_id": "e1", "school": "江商大", "major": "计算机", "degree": ""}]})
        pid = state["collected_info"]["projects"][0]["item_id"]
        state["resume_data"] = {"basic_info": {"name": "江同学"},
                                "education": [{"item_id": "e1", "school": "江商大", "major": "计算机", "degree": ""}],
                                "projects": [{"item_id": pid, "name": "途记", "hidden": False,
                                              "polished_bullets": ["设计行程推荐 Agent 方案：先检索候选地点，再由模型编排行程。"]}]}
        state["messages"] = [HumanMessage(content=message)]
        writer = AsyncMock(side_effect=AssertionError("字段类修改不得调用 writer"))
        with patch("app.agents.tailor_pipeline.run_resume_writer", new=writer), \
                patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value={
                    "status": "rendered", "pages": 1, "page_limit": 1, "within_page_limit": True}), \
                patch("app.agents.resume_graph._recover_candidate_history",
                      new=AsyncMock(side_effect=lambda current, model: current["collected_info"])):
            result = await evaluating_node(state, object())
        return state, result, writer

    async def test_education_only_edit_keeps_project_prose_verbatim(self):
        state, result, writer = await self.run_turn("学校改成江北商业大学，计算机科学与技术专业，本科大三。")
        writer.assert_not_awaited()
        before, after = state["resume_data"], result["resume_data"]
        self.assertEqual(after["projects"], before["projects"])
        self.assertEqual(after.get("work_experience"), before.get("work_experience"))
        education = after["education"][0]
        self.assertEqual((education["school"], education["major"], education["degree"]),
                         ("江北商业大学", "计算机科学与技术", "本科"))
        reply = result["messages"][0].content
        self.assertIn("✅ 修改学校", reply)
        self.assertNotIn("❌", reply)

    def test_deterministic_only_requires_no_writing_op(self):
        from app.agents.turn_actions import deterministic_only
        edu = {"education": [1]}
        self.assertTrue(deterministic_only("学校改成X", [{"op": "set_field"}], [], {}, edu))
        self.assertFalse(deterministic_only("学校改成X，途记写详细点", [{"op": "set_field"}, {"op": "rewrite"}], [], {}, edu))
        self.assertFalse(deterministic_only("学校改成X", [{"op": "set_field"}], [{"scope": "item"}], {}, edu))
        self.assertFalse(deterministic_only("学校改成X", [], [], {}, {"education": [1], "projects": [2]}))


class RepeatedFactTests(unittest.TestCase):
    """R2：同一事实不重复成多条；回退不拼接、不带标题行已有的阶段词。"""

    def rows(self, *specs):
        return [{"id": f"b{i}", "text": text, "fact_ids": ids} for i, (text, ids) in enumerate(specs)]

    def test_equal_or_subset_fact_sets_keep_the_richer_bullet(self):
        from app.agents.resume_writer import _without_repeated_fact_rows
        rows = self.rows(("先查候选再让模型选", ["f3"]),
                         ("针对模型推荐不存在的店，改为先查候选再让模型选", ["f2", "f3"]),
                         ("做行程推荐", ["f1"]))
        kept = _without_repeated_fact_rows(rows)
        self.assertEqual([row["id"] for row in kept], ["b1", "b2"])
        same = _without_repeated_fact_rows(self.rows(("短句", ["f1"]), ("更长的一句表述", ["f1"])))
        self.assertEqual([row["text"] for row in same], ["更长的一句表述"])

    def test_bullet_count_never_exceeds_distinct_fact_groups(self):
        from app.agents.resume_writer import _without_repeated_fact_rows
        facts = [{"id": "f1", "field": None, "text": "做行程推荐"},
                 {"id": "f2", "field": None, "text": "课程原型"},
                 {"id": "f3", "field": None, "text": "没有用户量"}]
        rows = self.rows(("a", ["f1"]), ("b", ["f2"]), ("c", ["f3"]))
        self.assertEqual(len(_without_repeated_fact_rows(rows, facts)), 1)

    def test_prompts_state_the_one_bullet_per_fact_group_rule(self):
        from app.agents import resume_writer
        for contract in (resume_writer._WRITE_CONTRACT, resume_writer._ONE_PASS_CONTRACT):
            self.assertIn("事实组", contract)

    def test_fallback_is_one_fact_without_stage_statement_or_joining(self):
        from app.agents.resume_writer import _fallback_bullet
        facts = {"f1": {"id": "f1", "item_id": "p1", "kind": "action", "text": "做了行程推荐"},
                 "f2": {"id": "f2", "item_id": "p1", "kind": "status_limit", "text": "途记基本是课程原型"},
                 "f3": {"id": "f3", "item_id": "p1", "kind": "action", "text": "改成先查候选再让模型选"}}
        text, refs = _fallback_bullet("p1", ["f1", "f2", "f3"], facts, "途记")
        self.assertEqual((text, refs), ("改成先查候选再让模型选", ["f3"]))
        self.assertNotIn("；", text)
        self.assertEqual(_fallback_bullet("p1", ["f2"], {"f2": facts["f2"]}, "途记"), ("", []))


class DetailRequestReceiptTests(unittest.TestCase):
    """R3：要求「写详细」但没有未使用的已披露事实时，回执不能是 ✅。"""

    collected = {"projects": [{"item_id": "p2", "name": "工坊集", "facts": [
        {"id": "f1", "kind": "method_tool", "text": "用 Claude Code 写技能", "source_quote": "用 Claude Code 写技能", "status": "active"},
        {"id": "f2", "kind": "action", "text": "做过抖音推广", "source_quote": "做过抖音推广", "status": "active"},
        {"id": "f3", "kind": "status_limit", "text": "没有星数", "source_quote": "没有星数", "status": "active"}]}]}
    before = {"projects": [{"item_id": "p2", "name": "工坊集", "polished_bullets": ["a"]}]}
    profile = {"role_family": "ai_pm", "core_signals": [{"id": "s1", "signal": "开源协作"}, {"id": "s2", "signal": "内容推广"}]}
    row = {"op": "rewrite", "target": "工坊集", "status": "done", "reason": "等待 writer 改写",
           "changed": False, "affected_item_ids": ["p2"]}

    def lines(self, cited):
        meta = {"bullets": {"p2": [{"fact_ids": cited}]}}
        rows = detail_gap_rows("工坊集写详细一点", [self.row], self.before, meta, self.collected, self.profile)
        after = {"projects": [{"item_id": "p2", "name": "工坊集", "polished_bullets": ["a2"]}]}
        return render_operation_report(rows, self.before, after)

    def test_all_facts_already_used_becomes_a_warning_with_one_signal_question(self):
        lines = self.lines(["f1", "f2"])
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("⚠ 工坊集：现有资料都已写进去了，想写得更详细需要你补充，比如："), lines)
        # W3：问句来自岗位手册「高价值追问」，不把信号名套进模板
        from app.agents.career_prompt import playbook_followups
        self.assertTrue(any(question in lines[0] for question in playbook_followups("ai_pm")), lines)
        self.assertNotIn("相关的部分", lines[0])
        self.assertNotIn("开源协作", lines[0])
        self.assertNotIn("✅", lines[0])

    def test_unused_disclosed_fact_keeps_the_normal_receipt(self):
        self.assertEqual(self.lines(["f1"]), ["✅ 改写 工坊集"])

    def test_other_requests_are_not_affected(self):
        rows = detail_gap_rows("工坊集精简一点", [self.row], self.before, {"bullets": {}}, self.collected, self.profile)
        self.assertEqual(rows, [self.row])


class RejectedTextRecordingTests(unittest.IsolatedAsyncioTestCase):
    """R4：被拒原文仅在 benchmark 开关下记录；默认只有 hash 和错误码。"""

    async def fallback_rows(self, enabled):
        import os
        from app.agents.resume_writer import run_resume_writer
        quote = "我参与了途记的代码实现"
        source = {"projects": [{"item_id": "p1", "name": "途记", "facts": [
            {"id": "f1", "kind": "action", "text": quote, "source_quote": quote, "status": "active"}]}]}

        class Model:
            def with_structured_output(self, schema):
                self.schema = schema
                return self

            async def ainvoke(self, messages):
                if self.schema.__name__ == "RepairOutput":
                    return {"bullets": []}
                return {"match_plan": {"requirements": [], "experience_plan": [{"item_id": "p1", "treatment": "keep"}]},
                        "writer": {"items": [{"item_id": "p1", "section": "projects", "bullets": [
                            {"text": "独立负责途记的代码实现", "fact_ids": ["f1"]}]}]}}

        env = {"HUHUA_RECORD_REJECTED_TEXT": "1"} if enabled else {}
        with patch.dict(os.environ, env, clear=False):
            if not enabled:
                os.environ.pop("HUHUA_RECORD_REJECTED_TEXT", None)
            return (await run_resume_writer(source, {}, Model()))["guard_fallbacks"]

    async def test_default_records_only_hash_and_codes(self):
        rows = await self.fallback_rows(False)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("rejected_text", rows[0])
        self.assertIn("unsupported_responsibility_or_status:独立", rows[0]["error_codes"])
        self.assertTrue(rows[0]["rejected_text_hash"])

    async def test_benchmark_switch_records_rejected_text(self):
        rows = await self.fallback_rows(True)
        self.assertEqual(rows[0]["rejected_text"], "独立负责途记的代码实现")
        self.assertEqual(rows[0]["fallback_text"], "我参与了途记的代码实现")


class UnrequestedWritingOpTests(unittest.TestCase):
    def test_answer_without_edit_intent_creates_no_rewrite_ops(self):
        answer = "途记基本是我一个人做的，产品方案和代码都是我。先给我出一版看看。"
        data = {"projects": [{"item_id": "p1", "name": "途记"}]}
        plan = choose_edit_plan(answer, data, [{"op": "refocus", "target": "途记", "args": {}},
                                               {"op": "rewrite", "target": "途记", "args": {}}])
        self.assertEqual(plan, [])
        kept = choose_edit_plan("途记写详细一点", data, [{"op": "rewrite", "target": "途记", "args": {}}])
        self.assertEqual([row["op"] for row in kept], ["rewrite"])


class StoryBulletTests(unittest.IsolatedAsyncioTestCase):
    """W1/W2：问题不单独成条、凑数条被丢弃（途记三条事实）。"""

    facts = [("f1", "action", "做了行程推荐"),
             ("f2", "context", "模型会推荐不存在的店"),
             ("f3", "method_tool", "改成先查候选再让模型选")]

    def source(self):
        return {"projects": [{"item_id": "p1", "name": "途记", "facts": [
            {"id": fid, "kind": kind, "text": text, "source_quote": text, "status": "active"}
            for fid, kind, text in self.facts]}]}

    async def write(self, bullets):
        from app.agents.resume_writer import run_resume_writer

        class Model:
            def with_structured_output(self, schema):
                self.schema = schema.__name__
                return self

            async def ainvoke(self, messages):
                if self.schema == "SemanticBatch":
                    return {"decisions": [{"id": f"b{i}", "subject_ok": True, "actions_supported": True,
                                           "objects_supported": True, "results_supported": True, "limits_kept": True,
                                           "unsupported_spans": [], "verdict": "pass"} for i in range(8)]}
                return {"match_plan": {"requirements": [], "experience_plan": [{"item_id": "p1", "treatment": "lead", "target_bullets": 3}]},
                        "writer": {"items": [{"item_id": "p1", "section": "projects", "bullets": bullets}]}}

        return (await run_resume_writer(self.source(), {}, Model()))["resume_data"]["projects"][0]["polished_bullets"]

    async def test_w1_problem_is_merged_into_the_action_bullet(self):
        out = await self.write([
            {"text": "模型会推荐不存在的店", "fact_ids": ["f2"]},
            {"text": "改成先查候选再让模型选", "fact_ids": ["f3"]},
            {"text": "做了行程推荐", "fact_ids": ["f1"]}])
        self.assertEqual(len(out), 2, out)
        self.assertIn("不存在的店", out[0])
        self.assertIn("先查候选", out[0])

    async def test_w2_filler_bullet_is_dropped(self):
        out = await self.write([
            {"text": "做行程推荐，模型会推荐不存在的店，改成先查候选再让模型选", "fact_ids": ["f1", "f2", "f3"]},
            {"text": "以课程原型形式完成行程推荐流程", "fact_ids": ["f1"]}])
        self.assertEqual(len(out), 1, out)

    def test_w2_filler_rule_is_deterministic(self):
        from app.agents.resume_writer import _without_filler_rows
        rows = [{"id": "a", "text": "负责途记行程推荐模块，先查候选再选"},
                {"id": "b", "text": "以课程原型形式完成行程推荐流程"},
                {"id": "c", "text": "完成途记项目"}]
        self.assertEqual([row["id"] for row in _without_filler_rows(rows, "途记")], ["a"])
        self.assertEqual(len(_without_filler_rows(rows[2:], "途记")), 1)  # 唯一一条不清空条目


class PlaybookFollowupTests(unittest.TestCase):
    def test_questions_come_from_the_playbook_section(self):
        from app.agents.career_prompt import pick_followup, playbook_followups
        self.assertEqual(playbook_followups("backend")[0], "你自己写的是哪几个模块/接口？")
        self.assertIn("这部分是你自己做的还是团队一起？你具体负责哪块？", playbook_followups("ai_pm"))
        self.assertEqual(len(playbook_followups("other")), 3)

    def test_first_uncovered_signal_is_chosen_and_generic_fallback_exists(self):
        from app.agents.career_prompt import pick_followup
        covered = "我一个人做的，负责全部代码，同学试用后给了反馈"
        self.assertEqual(pick_followup("ai_pm", ""), "效果不好的时候你是怎么发现的、怎么改的？")
        # 个人贡献/反馈已覆盖时，跳过对应问句
        picked = pick_followup("ai_pm", covered)
        self.assertNotIn("自己做的还是团队", picked)
        self.assertNotIn("有多少人用过", picked)
        self.assertTrue(pick_followup("no_such_family", ""))

    def test_interviewer_drops_signal_template_questions(self):
        facts = {"projects": [{"item_id": "p1", "name": "工坊集", "facts": [
            {"id": "f1", "kind": "action", "text": "写技能", "source_quote": "写技能", "status": "active"}]}]}
        bad = "工坊集里和「开源协作」相关的部分，你具体做了什么？"
        plan = {"requirements": [], "experience_plan": [{"item_id": "p1", "treatment": "lead"}],
                "questions": [{"q": bad, "improves": {"item_id": "p1", "req_id": ""}, "value": 5}]}
        state = {"collected_info": facts, "resume_data": {"projects": [{"item_id": "p1", "name": "工坊集", "polished_bullets": ["a"]}]},
                 "resume_versions": [{}]}
        text = compose_interviewer_reply(state, match_plan=plan, role_profile={})["text"]
        self.assertNotIn("相关的部分", text)
