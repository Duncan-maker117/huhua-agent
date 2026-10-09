"""Advisor only returns bounded suggestions backed by the current draft."""

import asyncio
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.advisor import review_with_advisor  # noqa: E402


class FakeModel:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        self.calls.append((self.schema.__name__, messages))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def state():
    return {"resume_data": {"basic_info": {"name": "Candidate", "email": "candidate@example.org"},
                            "projects": [{"item_id": "p1", "name": "反馈项目",
                                          "polished_bullets": ["整理反馈并按问题分类"]}]},
            "collected_info": {"projects": [{"item_id": "p1", "name": "反馈项目",
                                             "raw_notes": ["已经删除的旧说法"], "facts": [
                {"id": "f1", "text": "整理反馈并按问题分类", "source_quote": "整理反馈并按问题分类",
                 "status": "active", "kind": "action"},
                {"id": "f-old", "text": "旧成果1000用户", "source_quote": "旧成果1000用户",
                 "status": "deleted", "kind": "result_metric"}]}],
                               "skills": [{"name": "Python", "status": "active"}]},
            "jd_info": {"role_profile": {"requirements": [{"id": "r1", "text": "用户研究"}]},
                        "required_skills": ["Python", "Docker"]}}


def issue(**overrides):
    return {"location": "/projects/0/polished_bullets/0",
            "evidence_quote": "整理反馈并按问题分类",
            "issue": "没有说明分类结果如何被使用。",
            "action": "询问本人分类表是否支持后续讨论；没有则保留现有描述。",
            "action_kind": "ask", "fact_ids": ["f1"], "req_ids": ["r1"], "priority": 4,
            **overrides}


class TailorAdvisorTest(unittest.TestCase):
    def test_valid_issue_is_read_only_and_button_requires_later_edit(self):
        current = state()
        current["resume_data"]["projects"][0]["raw_notes"] = ["不应作为当前稿送审的旧备注"]
        before = deepcopy(current)
        model = FakeModel({"issues": [issue()], "checked_scope": "已验证PDF排版"})
        result = asyncio.run(review_with_advisor(current, model))
        self.assertEqual(current, before)
        self.assertEqual(len(result["issues"]), 1)
        self.assertFalse(result["changed"])
        self.assertEqual(result["quick_reply"]["intent"], "edit")
        self.assertIn("要我直接按这些改吗", result["text"])
        self.assertIn("建议尚未写入简历", result["text"])
        self.assertEqual(result["checked_scope"], "current_resume_and_available_jd")
        payload = model.calls[0][1][-1].content
        self.assertNotIn("已经删除的旧说法", payload)
        self.assertNotIn("旧成果1000用户", payload)
        self.assertNotIn("不应作为当前稿送审的旧备注", payload)

    def test_fabricated_quotes_inactive_facts_numbers_and_tools_are_dropped(self):
        model = FakeModel({"issues": [
            issue(evidence_quote="模型编造的原句"),
            issue(fact_ids=["f-old"]),
            issue(action_kind="edit", action="加入1000名真实用户结果"),
            issue(action_kind="edit", action="添加跨部门项目经验"),
            issue(issue="已经通过 ATS 筛选。"),
        ]})
        result = asyncio.run(review_with_advisor(state(), model))
        self.assertEqual(result["issues"], [])
        self.assertIsNone(result["quick_reply"])
        self.assertNotIn("1000名", result["text"])
        tool = asyncio.run(review_with_advisor(state(), FakeModel({"issues": [
            issue(action_kind="edit", action="将当前技能改写为 Docker 项目能力")]})))
        self.assertEqual(tool["issues"], [])

    def test_model_failure_uses_basic_checks_without_claiming_export_validation(self):
        current = state()
        current["resume_data"]["basic_info"] = {"name": "", "email": "", "phone": ""}
        result = asyncio.run(review_with_advisor(current, FakeModel(RuntimeError("offline"))))
        self.assertEqual(result["checked_scope"], "deterministic_checks_only")
        self.assertGreaterEqual(len(result["issues"]), 2)
        self.assertLessEqual(len(result["issues"]), 5)
        self.assertIn("未验证导出文件排版", result["text"])
        self.assertFalse(result["changed"])

    def test_no_draft_does_not_call_model(self):
        model = FakeModel(RuntimeError("should not run"))
        result = asyncio.run(review_with_advisor({"resume_data": {}}, model))
        self.assertEqual(model.calls, [])
        self.assertEqual(result["issues"], [])
        self.assertIsNone(result["quick_reply"])


if __name__ == "__main__":
    unittest.main()
