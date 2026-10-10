"""有 skill_groups 时，平铺 skills 由分组展开；Word 与 PDF 都用分组。"""
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.skill_groups import sync_flat_skills  # noqa: E402
from app.services.renderer import render_resume  # noqa: E402

OLD_SENTENCES = ["产品能力：需求拆解 / 竞品分析", "技术理解：Python 开发经验"]


def data():
    return {"basic_info": {"name": "测试人"}, "education": [], "work_experience": [], "projects": [],
            "skills": list(OLD_SENTENCES),
            "skill_groups": {"产品方法": ["需求拆解", "竞品分析"], "开发": ["Python", "python", "SQL"], "空组": []},
            "certificates": []}


class SkillSyncTests(unittest.TestCase):
    def test_flat_skills_are_expanded_from_groups(self):
        d = data()
        self.assertTrue(sync_flat_skills(d))
        self.assertEqual(d["skills"], ["需求拆解", "竞品分析", "Python", "SQL"])
        self.assertFalse(sync_flat_skills(d))

    def test_without_groups_flat_skills_are_kept(self):
        d = data()
        d["skill_groups"] = {}
        self.assertFalse(sync_flat_skills(d))
        self.assertEqual(d["skills"], OLD_SENTENCES)

    def test_html_uses_one_row_per_group_and_not_old_sentences(self):
        d = data()
        sync_flat_skills(d)
        html = render_resume("t001-jianyue", d)
        self.assertEqual(html.count('class="skill-row"'), 2)
        self.assertIn("需求拆解</span> / <span", html)
        self.assertNotIn("技术理解", html)

    def test_docx_uses_groups(self):
        from docx import Document
        from app.tools.resume_data_docx import resume_data_to_docx
        d = data()
        sync_flat_skills(d)
        raw = resume_data_to_docx(d)
        text = "\n".join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
        self.assertIn("产品方法：需求拆解 / 竞品分析", text)
        self.assertNotIn("技术理解", text)

    def test_hidden_items_not_rendered(self):
        d = data()
        d["projects"] = [{"name": "隐藏项目甲", "hidden": True, "polished_bullets": ["x"]},
                         {"name": "可见项目乙", "role": "负责人", "start_date": "2026.1", "end_date": "2026.3",
                          "polished_bullets": ["y"]}]
        html = render_resume("t001-jianyue", d)
        self.assertNotIn("隐藏项目甲", html)
        self.assertIn("可见项目乙</span> ｜ <span", html)


if __name__ == "__main__":
    unittest.main()
