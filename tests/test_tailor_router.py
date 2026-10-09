"""Router tests use fictional materials and no external model calls."""

import asyncio
from pathlib import Path
import sys
import unittest

from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.router import route_intents  # noqa: E402


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


def state(with_draft=True):
    return {"resume_data": {"basic_info": {"name": "Candidate" if with_draft else "",
                                            "objective": ""},
                            "projects": [{"item_id": "p1", "name": "项目甲", "raw_notes": ["不送模型"],
                                          "polished_bullets": ["这是一个超过二十个字的虚构项目说明，用来验证摘要截断"]}]
                            if with_draft else []},
            "messages": [AIMessage(content="上一轮已经给出草稿。")],
            "jd_info": {"job_title": "产品实习生"}}


class TailorRouterTest(unittest.TestCase):
    def test_compound_new_fact_and_edit_are_both_preserved(self):
        model = FakeModel({"intents": ["experience"],
                           "edit": {"scope": "item", "targets": ["p1"], "instruction": "模型自造指令"},
                           "edit_plan": [{"op": "rewrite", "target": "p1", "args": {}}],
                           "reason": ""})
        message = "我还做过用户访谈，加进去并优化项目甲"
        result = asyncio.run(route_intents(message, state(), model))
        self.assertEqual(result["intents"], ["experience", "edit"])
        self.assertEqual(result["edit"]["instruction"], message)
        self.assertEqual(result["edit_plan"][0]["target"], "p1")
        payload = model.calls[0][1][-1].content
        self.assertIn("项目甲", payload)
        self.assertNotIn("不送模型", payload)
        self.assertNotIn("超过二十个字的虚构项目说明，用来验证", payload)

    def test_edit_verb_overrides_misclassified_chat_and_keeps_named_scope(self):
        model = FakeModel({"intents": ["chat"], "edit": {}, "edit_plan": [], "reason": ""})
        result = asyncio.run(route_intents("把项目甲精简一点", state(), model))
        self.assertIn("edit", result["intents"])
        self.assertEqual(result["edit"], {"scope": "item", "targets": ["p1"],
                                          "instruction": "把项目甲精简一点"})
        self.assertEqual(result["edit_plan"], [{"op": "rewrite", "target": "p1", "args": {}}])

    def test_unresolved_ordinal_is_not_expanded_to_whole_document(self):
        model = FakeModel({"intents": ["edit"], "edit": {}, "edit_plan": [], "reason": ""})
        result = asyncio.run(route_intents("把第九个项目改短", state(), model))
        self.assertEqual(result["edit"]["scope"], "item")
        self.assertEqual(result["edit"]["targets"], [])
        self.assertEqual(result["edit_plan"][0]["target"], "第九个项目")

    def test_failed_model_fallback_depends_on_draft_presence(self):
        with_draft = asyncio.run(route_intents("优化", state(), FakeModel(RuntimeError("offline"))))
        self.assertEqual(with_draft["intents"], ["edit"])
        self.assertEqual(with_draft["edit"]["scope"], "whole")
        self.assertEqual(with_draft["fallback_reason"], "router_unavailable")
        no_draft = asyncio.run(route_intents("我做过一个项目", state(False), FakeModel(RuntimeError("offline"))))
        self.assertEqual(no_draft["intents"], ["experience"])
        self.assertEqual(no_draft["edit_plan"], [])


if __name__ == "__main__":
    unittest.main()
