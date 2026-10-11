"""2026-10-10 端到端试用 P1：可迁移 gap、思路句、手册追问。"""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.agents.interviewer import compose_interviewer_reply  # noqa: E402
from app.agents.resume_writer import _validate_plan  # noqa: E402
from app.schemas.writer import MatchPlan  # noqa: E402


class LaunchRequirementGapTest(unittest.TestCase):
    def plan(self, fact_id):
        return MatchPlan.model_validate({"requirements": [
            {"req_id": "r1", "status": "transferable", "fact_ids": [fact_id], "angle": "开源作品"},
            {"req_id": "r2", "status": "transferable", "fact_ids": [fact_id], "angle": "迁移"}]})

    def run_plan(self, fact):
        profile = {"requirements": [{"id": "r1", "text": "有上线产品或真实用户数据（加分）"},
                                    {"id": "r2", "text": "熟悉 Agent 开发"}]}
        items = {"p1": {"item_id": "p1"}}
        return {row["req_id"]: row for row in _validate_plan(
            self.plan(fact["id"]), {"projects": [{"item_id": "p1"}]}, profile, items, {fact["id"]: fact})["requirements"]}

    def test_open_source_stars_are_not_a_launched_product(self):
        rows = self.run_plan({"id": "f1", "text": "GitHub 有 70 多个 star", "source_quote": "github有70多个star"})
        self.assertEqual(rows["r1"]["status"], "gap")
        self.assertEqual(rows["r1"]["fact_ids"], [])
        self.assertEqual(rows["r2"]["status"], "transferable")  # 不相关的要求不受影响

    def test_real_launch_fact_keeps_transferable(self):
        rows = self.run_plan({"id": "f1", "text": "上线后有 30 位同学试用", "source_quote": "上线后有30位同学试用"})
        self.assertEqual(rows["r1"]["status"], "transferable")

    def test_unreleased_does_not_count_as_launched(self):
        rows = self.run_plan({"id": "f1", "text": "课程原型，还没上线", "source_quote": "课程原型，还没上线"})
        self.assertEqual(rows["r1"]["status"], "gap")


def reply_state():
    return {"jd_info": {"job_title": "AI 产品实习生", "role_profile": {"role_family": "ai_pm", "requirements": [
                {"id": "r1", "text": "熟悉大模型应用（RAG、Agent、Function Calling）"}]}},
            "collected_info": {"projects": [{"item_id": "p1", "name": "mtagent", "facts": [
                {"id": "f1", "text": "多个 Agent 分工", "source_quote": "有好几个agent分工", "status": "active", "kind": "method_tool"},
                {"id": "f2", "text": "FastAPI 开发", "source_quote": "用fastapi写的", "status": "active", "kind": "method_tool"}]}]},
            "resume_data": {"basic_info": {"name": "C"}, "projects": [
                {"item_id": "p1", "name": "mtagent", "polished_bullets": ["使用 FastAPI 开发多 Agent 分工的路线规划应用"]}]},
            "resume_meta": {"bullets": {"p1": [{"fact_ids": ["f1", "f2"]}]}},
            "match_plan": {"requirements": [{"req_id": "r1", "status": "direct", "fact_ids": ["f1"]}],
                           "experience_plan": [{"item_id": "p1", "treatment": "lead"}], "questions": []}}


class InterviewerP1Test(unittest.TestCase):
    def test_rationale_uses_confirmed_plan_instead_of_truncated_draft(self):
        state = reply_state()
        state['confirmed_plan'] = {'thesis': '多个 Agent 分工', 'experience_plan': [
            {'item_id': 'p1', 'treatment': 'lead', 'reason': 'mtagent 的分工对应岗位的 Agent 应用要求。'}]}
        text = compose_interviewer_reply(state, version_number=1)["text"]
        self.assertIn('mtagent（分工对应岗位的 Agent 应用要求）', text)
        self.assertNotIn('正文写到', text)
        self.assertNotIn("证明", text)

    def test_rationale_not_claimed_when_fact_not_in_draft(self):
        state = reply_state()
        state["resume_meta"] = {"bullets": {"p1": [{"fact_ids": ["f2"]}]}}  # f1（对应该要求的事实）没进稿
        text = compose_interviewer_reply(state, version_number=1)["text"]
        self.assertNotIn("对应岗位要求", text)
        self.assertNotIn("RAG", text)

    def test_playbook_questions_fill_when_planner_gives_none(self):
        state = reply_state()
        before = deepcopy(state)
        result = compose_interviewer_reply(state, version_number=1)
        self.assertEqual(state, before)
        self.assertTrue(1 <= len(result["questions"]) <= 3)
        self.assertTrue(all(row["q"].startswith("mtagent：") for row in result["questions"]))
        self.assertIn("想让它更强", result["text"])
        self.assertEqual(result["guidance"]["question"], result["questions"][0]["q"])
        again = compose_interviewer_reply({**state, "asked_questions": result["asked_questions"]}, version_number=2)
        asked = {row["question_id"] for row in result["questions"]}
        self.assertFalse(asked & {row["question_id"] for row in again["questions"]})  # 不重复追问


class FixVerificationQuestionTest(unittest.TestCase):
    def state(self, extra=()):
        base = reply_state()
        facts = base["collected_info"]["projects"][0]["facts"]
        facts += [
            {"id": "f3", "text": "初期模型会推荐不存在的店铺", "source_quote": "一开始模型老推荐不存在的店", "status": "active", "kind": "context"},
            {"id": "f4", "text": "改为先用高德查询 POI，再让模型从结果中挑选", "source_quote": "后来我改成先用高德查poi再让模型从里面挑", "status": "active", "kind": "action"},
            *extra]
        return base

    def test_asks_whether_problem_recurs_after_the_fix(self):
        result = compose_interviewer_reply(self.state(), version_number=1)
        self.assertIn('这样做是为了解决什么', result['questions'][0]['q'])
        first = next(row['q'] for row in result['questions'] if '还会出现吗' in row['q'])
        self.assertIn("还会出现吗", first)
        self.assertIn("先用高德查询 POI", first)
        self.assertIn("模型会推荐不存在的店铺", first)
        self.assertFalse(any("效果不好的时候你是怎么发现的" in row["q"] and row["q"].startswith("mtagent") for row in result["questions"]))

    def test_problem_phrase_is_cut_before_the_fix_when_one_fact_holds_both(self):
        state = reply_state()
        state["collected_info"]["projects"][0]["facts"] += [
            {"id": "f3", "text": "模型会推荐不存在的店，我改成先查候选再让模型选", "source_quote": "x", "status": "active", "kind": "action"}]
        first = compose_interviewer_reply(state, version_number=1)["questions"][0]["q"]
        self.assertIn("「模型会推荐不存在的店」的情况还会出现吗", first)
        self.assertIn("改成「先查候选再让模型选」", first)

    def test_not_asked_when_verification_already_stated(self):
        extra = [{"id": "f5", "text": "拿 20 个例子测试过", "source_quote": "拿20个例子测试过", "status": "active", "kind": "action"}]
        result = compose_interviewer_reply(self.state(extra), version_number=1)
        self.assertFalse(any("还会出现吗" in row["q"] for row in result["questions"]))


class ReceiptDedupeTest(unittest.TestCase):
    def test_identical_lines_are_reported_once(self):
        from app.agents.turn_actions import render_operation_report
        same = {"op": "contract_gap", "target": "途记", "status": "needs_detail", "reason": "同一个原因", "changed": False}
        self.assertEqual(len(render_operation_report([same, dict(same)], {}, {})), 1)


class UndoEducationNoteTest(unittest.TestCase):
    def test_note_only_when_a_field_was_corrected(self):
        from app.services.resume_versions import education_correction_note
        plain = {"education": [{"facts": [{"status": "active", "field": "school", "text": "哈商大"}]}]}
        self.assertEqual(education_correction_note(plain), "")
        corrected = {"education": [{"facts": [{"status": "superseded", "field": "school", "text": "哈商大"},
                                              {"status": "active", "field": "school", "text": "哈尔滨商业大学"}]}]}
        note = education_correction_note(corrected)
        self.assertIn("撤销不会还原", note)
        self.assertEqual(education_correction_note({}), "")

    def test_graph_undo_reply_carries_the_note(self):
        import asyncio
        from unittest.mock import patch
        from langchain_core.messages import HumanMessage
        from app.agents.resume_graph import _evaluating_turn_node
        collected = {"education": [{"item_id": "e1", "school": "哈尔滨商业大学", "facts": [
            {"status": "superseded", "field": "school", "text": "哈商大"},
            {"status": "active", "field": "school", "text": "哈尔滨商业大学"}]}]}
        restored = {"resume_data": {"projects": []}}
        state = {"messages": [HumanMessage(content="撤销")], "resume_data": {"projects": [{"name": "x"}]},
                 "collected_info": collected}
        with patch("app.services.resume_versions.restore_payload", return_value=restored):
            result = asyncio.run(_evaluating_turn_node(state, object()))
        self.assertIn("撤销不会还原", result["messages"][0].content)


if __name__ == "__main__":
    unittest.main()
