"""Review must inspect the same visible content as editor/export."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.services.resume_review import resume_to_text, review_resume
from app.services.session_store import resume_data_has_content


class CanonicalReviewTextTests(unittest.TestCase):
    def test_visibility_order_titles_and_custom_content(self):
        data = {
            'basic_info': {'name': '测试'},
            'projects': [{'name': '被隐藏项目', 'description': '不应被检查为当前正文'}],
            'education': [{'school': '测试大学', 'major': '计算机', 'degree': '本科', 'start_date': '2023.09', 'end_date': '2027.06', 'highlights': '课程设计'}],
            'certificates': ['待核对证书'],
            'sections': [
                {'id': 'custom-1', 'kind': 'custom', 'title': '我的作品', 'content': '演示记录'},
                {'id': 'education', 'kind': 'education', 'title': '学习经历'},
                {'id': 'certificates', 'kind': 'certificates', 'title': '证书'},
            ],
            'verification_notes': ['毕业时间来自旧稿，需本人核对'],
        }
        text = resume_to_text(data)
        self.assertNotIn('被隐藏项目', text)
        self.assertLess(text.index('我的作品'), text.index('学习经历'))
        for value in ('演示记录', '计算机', '2023.09', '2027.06', '课程设计', '待核对证书'):
            self.assertIn(value, text)
        self.assertNotIn('毕业时间来自旧稿', text)
        self.assertIn('待核对：毕业时间来自旧稿，需本人核对', review_resume(data))

    def test_explicit_empty_sections_hide_all_body_and_grouped_skills_survive(self):
        self.assertNotIn('Python', resume_to_text({'skills': ['Python'], 'sections': []}))
        text = resume_to_text({'skill_groups': {'技术': ['Python']}})
        self.assertIn('技术：Python', text)

    def test_jd_alone_is_not_personal_data_but_editor_custom_draft_is(self):
        self.assertFalse(resume_data_has_content({'basic_info': {'objective': 'AI 产品实习'}}))
        self.assertTrue(resume_data_has_content({'basic_info': {'objective': 'AI 产品实习'}, 'sections': []}))
        self.assertTrue(resume_data_has_content({'sections': [{'kind': 'custom', 'content': '本人提供的作品说明'}]}))
        self.assertTrue(resume_data_has_content({'skill_groups': {'工具': ['Figma']}}))


if __name__ == '__main__':
    unittest.main()
