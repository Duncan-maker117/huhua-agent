"""Model formatting must not hide source facts from the draft or editor save."""

import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents.editor_chain import (  # noqa: E402
    EditorOutput,
    _source_supported_bullets,
    run_editor,
)
from app.services.canonical_resume import editor_facts  # noqa: E402
from app.services.resume_review import resume_to_text  # noqa: E402


class EditorSourceCoverageTest(unittest.IsolatedAsyncioTestCase):
    def source(self):
        return {
            "projects": [{
                "name": "纸页工具",
                "description": "实现页面拆分。向一位同学演示，收集到2条反馈。尚未上线。",
            }],
            "education": [{"school": "示例大学"}],
            "skills": ["Python"],
        }

    async def polish(self, source, bullets):
        response = EditorOutput(project_polishes=[{
            "name": "纸页工具", "polished_bullets": bullets,
        }])
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=response))
        with patch("app.agents.editor_chain.with_structured_output", return_value=model):
            return await run_editor(source, object())

    async def test_partial_polish_keeps_feedback_and_limitations_visible_and_saved(self):
        source = self.source()
        before = copy.deepcopy(source)
        for bullets in (
            ["实现页面拆分"],
            ["实现页面拆分", "向一位同学演示，收集到2条反馈"],
            ["实现页面拆分", "尚未上线"],
        ):
            with self.subTest(bullets=bullets):
                result = await self.polish(source, bullets)
                self.assertEqual(result, before)
                self.assertEqual(source, before)
                draft = resume_to_text(result)
                saved_facts = editor_facts(result)
                for fact in ("实现页面拆分", "收集到2条反馈", "尚未上线"):
                    self.assertIn(fact, draft)
                    self.assertIn(fact, saved_facts["projects"][0]["description"])

    async def test_complete_reordering_retains_all_facts_and_other_sections(self):
        source = self.source()
        before = copy.deepcopy(source)
        bullets = ["尚未上线。", "实现页面拆分。", "向一位同学演示，收集到2条反馈。"]
        result = await self.polish(source, bullets)
        self.assertEqual(result["projects"][0]["polished_bullets"], bullets)
        self.assertEqual(result["education"], source["education"])
        self.assertEqual(result["skills"], source["skills"])
        self.assertEqual(source, before)
        for fact in bullets:
            self.assertIn(fact, resume_to_text(result))
            self.assertIn(fact, editor_facts(result)["projects"][0]["description"])

    def test_repeated_bullet_cannot_replace_a_missing_sentence(self):
        self.assertFalse(_source_supported_bullets(
            "参与调研。效果未验证。", ["参与调研", "参与调研"],
        ))

    def test_omitting_a_repeated_source_sentence_is_not_lossless(self):
        self.assertFalse(_source_supported_bullets(
            "完成演示。完成演示。", ["完成演示"],
        ))

    def test_whitespace_and_source_sentence_separators_allow_reordering(self):
        self.assertTrue(_source_supported_bullets(
            "- 参与调研；整理 2 份笔记。\n• 尚未上线。",
            ["尚未上线", "整理2份笔记", "参与调研"],
        ))

    def test_rewording_or_adding_claims_is_rejected(self):
        for bullets in (["主导调研", "尚未上线"], ["参与调研", "尚未上线", "用户增长50%"]):
            with self.subTest(bullets=bullets):
                self.assertFalse(_source_supported_bullets("参与调研。尚未上线。", bullets))


if __name__ == "__main__":
    unittest.main()
