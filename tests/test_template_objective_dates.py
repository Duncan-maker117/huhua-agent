"""Active HTML templates must show sourced objectives and honest date ranges."""

import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.editor import ResumeData  # noqa: E402
from app.services.renderer import list_templates, render_resume  # noqa: E402


class _VisibleText(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.hidden = False
        self.parts: list[str] = []
        self.feed(html)

    def handle_starttag(self, tag: str, attrs):
        if tag in ("style", "script"):
            self.hidden = True

    def handle_endtag(self, tag: str):
        if tag in ("style", "script"):
            self.hidden = False

    def handle_data(self, text: str):
        if not self.hidden:
            self.parts.append(text)


def _resume(start_dates: bool, end_dates: bool, objective: str = "") -> dict:
    values = (
        ("education", "school", "某大学", "2020.1", "2024.6"),
        ("work_experience", "company", "某公司", "2024.7", "2024.9"),
        ("projects", "name", "项目甲", "2025.1", "2025.6"),
    )
    data = {"basic_info": {"name": "测试者", "objective": objective}}
    for section, label, name, start, end in values:
        data[section] = [
            {
                label: name,
                "start_date": start if start_dates else "",
                "end_date": end if end_dates else "",
            }
        ]
    return ResumeData.model_validate(data).model_dump()


class TemplateObjectiveDatesTest(unittest.TestCase):
    def test_all_active_templates_map_objective_only_when_present(self):
        objective = "AI 产品（Agent 应用方向）"
        for template in list_templates():
            template_id = template["id"]
            with self.subTest(template=template_id):
                html = render_resume(template_id, _resume(False, False, objective))
                self.assertEqual(
                    html.count(
                        f'data-field-path="/basic_info/objective">{objective}</span>'
                    ),
                    1,
                )
                empty_html = render_resume(template_id, _resume(False, False))
                self.assertNotIn('data-field-path="/basic_info/objective"', empty_html)
                self.assertNotIn("求职意向", _VisibleText(empty_html).parts)

    def test_all_active_templates_render_only_available_date_endpoints(self):
        dates = (
            ("education", "2020.1", "2024.6"),
            ("work_experience", "2024.7", "2024.9"),
            ("projects", "2025.1", "2025.6"),
        )
        for template in list_templates():
            template_id = template["id"]
            for has_start, has_end in (
                (True, False),
                (False, True),
                (False, False),
                (True, True),
            ):
                with self.subTest(template=template_id, start=has_start, end=has_end):
                    html = render_resume(template_id, _resume(has_start, has_end))
                    paths = set(re.findall(r'data-field-path="([^"]+)"', html))
                    text = re.sub(r"\s+", "", "".join(_VisibleText(html).parts))
                    for section, start, end in dates:
                        self.assertEqual(f"/{section}/0/start_date" in paths, has_start)
                        self.assertEqual(f"/{section}/0/end_date" in paths, has_end)
                        if has_start and has_end:
                            self.assertIn(f"{start}—{end}", text)
                        elif has_start:
                            self.assertIn(start, text)
                        elif has_end:
                            self.assertIn(end, text)
                    self.assertEqual(text.count("—"), 3 if has_start and has_end else 0)
                    if not has_start and not has_end:
                        self.assertNotIn("实习时间：", text)


if __name__ == "__main__":
    unittest.main()
