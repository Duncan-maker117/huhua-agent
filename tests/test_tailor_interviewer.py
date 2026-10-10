"""Follow-ups target concrete draft locations and never become facts by themselves."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.interviewer import (  # noqa: E402
    compose_interviewer_reply, first_draft_ready, open_questions, record_interview_answer,
)


def state():
    return {"messages": [HumanMessage(content="我想投产品实习")],
            "jd_info": {"job_title": "产品实习生", "role_profile": {
                "requirements": [{"id": "r1", "text": "用户研究"}, {"id": "r2", "text": "数据判断"}]}},
            "collected_info": {"projects": [{"item_id": "p1", "name": "反馈项目",
                                              "raw_notes": ["不作为提问事实的旧备注"], "facts": [
                {"id": "f1", "text": "整理反馈", "source_quote": "整理反馈", "status": "active", "kind": "action"},
                {"id": "f2", "text": "按问题分类", "source_quote": "按问题分类", "status": "active", "kind": "action"}]}]},
            "resume_data": {"basic_info": {"name": "Candidate"},
                            "projects": [{"item_id": "p1", "name": "反馈项目",
                                          "polished_bullets": ["整理反馈", "按问题分类"]}]},
            "resume_meta": {"bullets": {"p1": [{"fact_ids": ["f1"]}, {"fact_ids": ["f2"]}]}},
            "match_plan": {"requirements": [{"req_id": "r1", "status": "direct", "fact_ids": ["f1"]},
                                             {"req_id": "r2", "status": "direct", "fact_ids": ["f2"]}],
                           "experience_plan": [{"item_id": "p1", "treatment": "lead"}],
                           "questions": [
                               {"q": "分类结果后来怎么用？", "why": "能说明交付价值", "value": 5,
                                "improves": {"item_id": "p1", "req_id": "r2"}, "options": ["用于讨论"]},
                               {"q": "你是自己整理反馈的吗？", "why": "澄清本人贡献", "value": 4,
                                "improves": {"item_id": "p1", "req_id": "r1"}},
                               {"q": "有没有效果数字？", "why": "可选指标", "value": 2,
                                "improves": {"item_id": "p1", "req_id": "r2"}},
                               {"q": "还有什么？", "why": "低价值", "value": 1,
                                "improves": {"item_id": "p1", "req_id": "r1"}},
                               {"q": "无效经历问题", "value": 5,
                                "improves": {"item_id": "missing", "req_id": "r1"}},
                           ]}}


class TailorInterviewerTest(unittest.TestCase):
    def test_first_draft_gate_and_explicit_generation(self):
        ready = state()
        ready["resume_data"] = {}
        self.assertTrue(first_draft_ready(ready))
        self.assertEqual(compose_interviewer_reply(ready)["next_action"], "write")
        self.assertEqual(compose_interviewer_reply(ready)["questions"], [])
        ready["collected_info"]["projects"][0]["facts"] = ready["collected_info"]["projects"][0]["facts"][:1]
        self.assertFalse(first_draft_ready(ready))
        self.assertEqual(compose_interviewer_reply(ready)["next_action"], "ask")
        ready["messages"] = [HumanMessage(content="请按现有材料生成简历")]
        self.assertTrue(first_draft_ready(ready))

    def test_without_role_asks_one_gating_question_with_short_options(self):
        minimal = {"messages": [], "jd_info": {}, "collected_info": {}, "resume_data": {}}
        result = compose_interviewer_reply(minimal)
        self.assertFalse(result["ready_for_first_draft"])
        self.assertEqual(result["next_action"], "ask")
        self.assertEqual(len(result["questions"]), 1)
        self.assertEqual(len(result["guidance"]["options"]), 3)
        self.assertIn("岗位", result["guidance"]["question"])
        self.assertEqual(result["pre_draft_rounds"], 1)
        minimal["asked_questions"] = result["asked_questions"]
        repeated = compose_interviewer_reply(minimal)
        self.assertEqual(repeated["questions"], [])
        self.assertEqual(repeated["next_action"], "await_user_or_generate")
        self.assertEqual(repeated["pre_draft_rounds"], 1)

    def test_three_ranked_questions_have_item_req_and_exact_draft_location(self):
        current = state()
        before = deepcopy(current)
        result = compose_interviewer_reply(current)
        self.assertEqual(current, before)
        self.assertEqual(len(result["questions"]), 3)
        self.assertEqual([row["value"] for row in result["questions"]], [5, 4, 2])
        self.assertEqual(result["questions"][0]["improves"], {"item_id": "p1", "req_id": "r2"})
        self.assertEqual(result["questions"][0]["location_path"], "/projects/0/polished_bullets/1")
        self.assertIn("反馈项目 第 2 条", result["text"])
        self.assertIn("用户研究", result["text"])
        self.assertEqual(len(result["asked_questions"]), 3)
        self.assertEqual(result["guidance"]["question"], result["questions"][0]["q"])

    def test_no_answer_closes_question_without_reasking_or_updating_facts(self):
        current = state()
        first = compose_interviewer_reply(current)
        question = first["questions"][0]
        saved_facts = deepcopy(current["collected_info"])
        closed = record_interview_answer(first["asked_questions"], question["question_id"], "不知道 / 没有")
        self.assertEqual(closed["status"], "closed_without_fact")
        self.assertEqual(closed["candidate_turn"], "")
        self.assertFalse(closed["facts_added"])
        current["asked_questions"] = closed["asked_questions"]
        second = compose_interviewer_reply(current)
        self.assertNotIn(question["question_id"], [row["question_id"] for row in second["questions"]])
        self.assertEqual(current["collected_info"], saved_facts)
        substantive = record_interview_answer([], "q2", "我把分类表交给项目组讨论")
        self.assertEqual(substantive["status"], "answered_pending_extraction")
        self.assertFalse(substantive["facts_added"])
        self.assertEqual(substantive["candidate_turn"], "我把分类表交给项目组讨论")

    def test_open_questions_exclude_unasked_and_closed(self):
        current = state()
        self.assertEqual(open_questions(current), [])  # 还没问过，不是待答追问
        first = compose_interviewer_reply(current)
        current["asked_questions"] = first["asked_questions"]
        shown = open_questions(current)
        self.assertEqual([row["question_id"] for row in shown], [row["question_id"] for row in first["questions"]])
        self.assertTrue(all(row["options"][-1]["value"] == "不知道 / 没有" for row in shown))
        closed = record_interview_answer(current["asked_questions"], shown[0]["question_id"], "不知道 / 没有")
        current["asked_questions"] = closed["asked_questions"]
        remaining = [row["question_id"] for row in open_questions(current)]
        self.assertNotIn(shown[0]["question_id"], remaining)
        self.assertEqual(len(remaining), len(shown) - 1)

    def test_workspace_tailor_metadata_exposes_only_open_questions(self):
        from app.services.resume_workspace import tailor_metadata
        current = state()
        first = compose_interviewer_reply(current)
        values = {k: current[k] for k in ("jd_info", "collected_info", "match_plan")}
        values["asked_questions"] = first["asked_questions"]
        canonical = current["resume_data"]
        shown = tailor_metadata(values, canonical)["questions"]
        self.assertEqual(len(shown), 3)
        self.assertTrue(all(row["question_id"] and row["options"] for row in shown))
        values["asked_questions"] = record_interview_answer(
            first["asked_questions"], shown[0]["question_id"], "有，用于周会讨论")["asked_questions"]
        self.assertEqual(len(tailor_metadata(values, canonical)["questions"]), 2)


if __name__ == "__main__":
    unittest.main()
