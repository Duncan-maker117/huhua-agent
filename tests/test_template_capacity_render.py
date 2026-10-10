"""capacity.json 与真实 PDF 渲染一致（全部使用虚构内容）。"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.renderer import list_templates  # noqa: E402
from app.services.resume_capacity import load_template_capacity, writer_capacity_budget  # noqa: E402

spec = importlib.util.spec_from_file_location("probe", ROOT / "scripts" / "measure_template_capacity.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class TemplateCapacityRenderTests(unittest.TestCase):
    def test_every_template_is_registered_and_flags_one_page(self):
        data = json.loads((ROOT / "data/jianlimoban/capacity.json").read_text(encoding="utf-8"))
        for template in list_templates():
            self.assertIn(template["id"], data["templates"])
            self.assertIsInstance(template["fits_one_page"], bool)

    def test_chars_per_line_and_filled_page_match_real_render(self):
        for template in list_templates():
            tid = template["id"]
            with self.subTest(template=tid):
                row = load_template_capacity(tid)
                cpl = row["chars_per_line"]
                for n, expected in ((cpl, 1), (cpl + 3, 2)):
                    data = probe._resume(0, 20)
                    data["work_experience"][0]["bullets"] = ["测" * n]
                    _, lines = probe._pdf_lines(data, tid)
                    self.assertEqual(len([x for x in lines if "测" in x]), expected)
                whole = (row["section_lines"]["projects"] - 1) // 5
                pages, _ = probe._pdf_lines(probe._resume(whole, cpl), tid)
                self.assertEqual(pages, 1)

    def test_writer_budget_reads_measured_capacity(self):
        budget = writer_capacity_budget({"template_id": "t001-jianyue", "page_limit": 1})
        row = load_template_capacity("t001-jianyue")
        self.assertEqual(budget["chars_per_line"], row["chars_per_line"])
        self.assertLessEqual(budget["max_bullet_chars_estimate"], 60)


if __name__ == "__main__":
    unittest.main()
