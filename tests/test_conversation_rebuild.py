"""Saved editor choices must survive the next conversation-driven rebuild."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.resume_graph import (  # noqa: E402
    _write_resume_update,
    _init_state,
    _serialize_to_resume_data,
)
from app.schemas.editor import ResumeData  # noqa: E402
from app.services.canonical_resume import editor_facts  # noqa: E402


def saved_resume(**overrides):
    return ResumeData.model_validate({
        "basic_info": {"name": "虚构候选人"},
        "projects": [{"name": "课程项目", "description": "完成五个静态界面，未上线"}],
        **overrides,
    }).model_dump()


class ConversationRebuildTest(unittest.IsolatedAsyncioTestCase):
    async def rebuild(self, saved, facts, *, model=None, **state_updates):
        model = model or object()
        state = {
            **_init_state(),
            "resume_data": saved,
            "collected_info": facts,
            **state_updates,
        }

        with (
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=model),
            patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value={
                "status": "render_error", "pages": None, "within_page_limit": None,
                "page_limit": 1, "error_type": "TestRendererUnavailable"}),
        ):
            result = await _write_resume_update(state, model)
        return result["resume_data"]

    async def test_saved_basic_fields_and_explicit_blanks_survive_new_fact(self):
        saved = saved_resume(basic_info={
            "name": "虚构候选人", "birthday": "2004.05", "hometown": "深圳",
            "gender": "女", "age": "", "height": "", "political": "",
            "ethnicity": "", "objective": "",
        })
        facts = editor_facts(saved)
        facts["skills"].append("Excel")
        result = await self.rebuild(
            saved, facts, jd_keywords=["AI产品经理"],
            messages=[HumanMessage(content="我今年22岁，身高175cm，共青团员，汉族")],
        )
        self.assertEqual(result["basic_info"], saved["basic_info"])
        self.assertEqual(result["skills"], ["Excel"])

    async def test_latest_explicit_basic_correction_replaces_saved_value(self):
        saved = saved_resume(basic_info={"name": "旧姓名", "age": "22岁", "photo": "old-photo"})
        facts = editor_facts(saved)
        facts["basic_info"].update(name="新姓名", age="23岁", photo="")
        result = await self.rebuild(saved, facts)
        self.assertEqual(result["basic_info"]["name"], "新姓名")
        self.assertEqual(result["basic_info"]["age"], "23岁")
        self.assertEqual(result["basic_info"]["photo"], "")

    def test_first_draft_still_uses_jd_and_message_fallbacks(self):
        result = _serialize_to_resume_data({
            **_init_state(), "jd_keywords": ["AI产品经理"],
            "messages": [HumanMessage(content="我今年22岁，身高175cm")],
        })
        self.assertEqual(result["basic_info"]["objective"], "AI产品经理")
        self.assertEqual(result["basic_info"]["age"], "22岁")
        self.assertEqual(result["basic_info"]["height"], "175cm")

    async def test_visible_groups_replace_stale_flat_skills_on_rebuild(self):
        saved = saved_resume(skills=["Python", "Java"], skill_groups={"自定义工具": ["Excel"]})
        facts = editor_facts(saved)
        self.assertEqual(facts["skills"], ["Excel"])
        facts["certificates"].append("虚构证书")
        from test_resume_writer import FakeModel
        from app.services.resume_facts import normalize_fact_store
        from app.services.fact_guard import strip_absence
        facts = normalize_fact_store(facts)
        project = facts['projects'][0]
        model = FakeModel([('OnePassOutput', {'match_plan': {}, 'writer': {
            'items': [{'item_id': project['item_id'], 'section': 'projects',
                       'bullets': [{'text': strip_absence(fact['text']), 'fact_ids': [fact['id']]}
                                   for fact in project['facts'] if strip_absence(fact['text'])]}],
            'skill_groups': {'自定义工具': ['Excel']}}})])
        result = await self.rebuild(saved, facts, model=model)
        self.assertEqual([schema for schema, _ in model.calls], ['OnePassOutput'])
        self.assertEqual(result["skills"], ["Excel"])
        # Custom headings have no authenticated provenance in an old draft;
        # retain the active skill while using a neutral display heading.
        self.assertEqual(result["skill_groups"], {"办公软件": ["Excel"]})  # 固定类别，自定义分组名不显示
        self.assertEqual(result["certificates"], ["虚构证书"])

    async def test_group_only_edits_survive_and_new_chat_skill_is_added(self):
        saved = saved_resume(skills=[], skill_groups={"工具": ["Excel"]})
        facts = editor_facts(saved)
        facts["skills"].append("Python")
        result = await self.rebuild(saved, facts)
        self.assertEqual(result["skills"], ["Excel", "Python"])
        self.assertEqual(result["skill_groups"], {"工具": ["Excel"], "其他": ["Python"]})

    async def test_empty_visible_group_does_not_revive_legacy_skills(self):
        saved = saved_resume(skills=["Python"], skill_groups={"工具": []})
        result = await self.rebuild(saved, editor_facts(saved))
        self.assertEqual(result["skills"], [])
        self.assertEqual(result["skill_groups"], {})

    async def test_chat_removing_grouped_skill_does_not_revive_it(self):
        saved = saved_resume(skills=["Python"], skill_groups={"工具": ["Python"]})
        facts = editor_facts(saved)
        facts["skills"] = []
        result = await self.rebuild(saved, facts)
        self.assertEqual(result["skills"], [])
        self.assertEqual(result["skill_groups"], {})

    async def test_explicit_ungrouped_choice_and_blank_title_survive_rebuild(self):
        saved = saved_resume(skills=["Excel"], skill_groups={}, experience_section_title="")
        result = await self.rebuild(saved, editor_facts(saved))
        self.assertEqual(result["skill_groups"], {})
        self.assertEqual(result["experience_section_title"], "")

    async def test_contact_and_skill_changes_work_without_experience(self):
        saved = saved_resume(projects=[], basic_info={"name": "虚构候选人", "email": "old@example.test"}, skills=["Excel"])
        facts = editor_facts(saved)
        facts["basic_info"]["email"] = "new@example.test"
        facts["skills"].append("Python")
        facts["education"] = [{"school": "示例大学"}]
        result = await self.rebuild(saved, facts)
        self.assertEqual(result["basic_info"]["email"], "new@example.test")
        self.assertEqual(result["skills"], ["Python", "Excel"])  # Source skills now join the fixed display categories.
        self.assertEqual(result["education"][0]["school"], "示例大学")

    async def test_deleting_last_experience_does_not_restore_old_draft(self):
        saved = saved_resume()
        facts = editor_facts(saved)
        facts["projects"] = []
        result = await self.rebuild(saved, facts, messages=[HumanMessage(content="我做过旧项目，完成五个静态界面")])
        self.assertEqual(result["projects"], [])
        self.assertEqual(result["basic_info"]["name"], "虚构候选人")

    async def test_missing_fact_master_does_not_promote_old_draft_to_source(self):
        saved = saved_resume()
        result = await self.rebuild(saved, None)
        self.assertEqual(result["projects"], [])
        self.assertEqual(result["basic_info"]["name"], "")
        self.assertNotIn("完成五个静态界面", str(result))


if __name__ == "__main__":
    unittest.main()
