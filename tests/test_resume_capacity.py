"""Page budget estimates stay separate from production PDF page evidence."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.renderer import list_templates  # noqa: E402
from app.services.resume_capacity import (  # noqa: E402
    MAX_COMPRESSION_ROUNDS, apply_deterministic_compression, load_template_capacity,
    measure_rendered_pages, normalize_session_constraints, plan_compression,
    writer_capacity_budget,
)


class ResumeCapacityTest(unittest.TestCase):
    def test_session_constraints_persist_and_validate(self):
        initial = normalize_session_constraints(seniority="intern")
        self.assertEqual(initial, {"page_limit": 1, "language": "zh-CN", "template_id": "t001-jianyue"})
        updated = normalize_session_constraints(initial, overrides={"page_limit": 2, "template_id": "t1001"})
        self.assertEqual(normalize_session_constraints(updated, overrides={"language": "en-US"}),
                         {"page_limit": 2, "language": "en-US", "template_id": "t1001"})
        self.assertEqual(normalize_session_constraints(seniority="experienced")["page_limit"], 2)
        for changes in ({"page_limit": 0}, {"page_limit": True}, {"page_limit": 3},
                        {"language": ""}, {"template_id": "not-a-template"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize_session_constraints(overrides=changes)

    def test_six_template_budgets_are_heuristics_with_bullet_caps(self):
        names = [row["id"] for row in list_templates()]
        self.assertEqual(len(names), 6)
        for name in names:
            with self.subTest(template=name):
                capacity = load_template_capacity(name)
                self.assertEqual(sum(capacity["section_lines"].values()), capacity["one_page_body_lines"])
                budget = writer_capacity_budget({"template_id": name, "page_limit": 1})
                self.assertEqual(budget["status"], "heuristic_not_rendered")
                self.assertEqual(budget["body_lines"], capacity["one_page_body_lines"])
                self.assertEqual(budget["max_bullet_lines"], 2)
                self.assertEqual(budget["bullet_caps"], {"lead": 3, "keep": 2, "brief": 1})
                self.assertEqual(budget["max_compression_rounds"], 2)

    def test_ranked_compression_preserves_original_and_skips_removed_bullets(self):
        resume = {
            "work_experience": [
                {"item_id": "brief-1", "bullets": ["B" * 120]},
                {"item_id": "keep-1", "bullets": ["K" * 80, "trim this second bullet"]},
            ],
            "projects": [{"item_id": "lead-1", "polished_bullets": ["L" * 40]}],
            "self_evaluation": "Generic summary",
        }
        unchanged = deepcopy(resume)
        match_plan = {"experience_plan": [
            {"item_id": "brief-1", "treatment": "brief"},
            {"item_id": "keep-1", "treatment": "keep"},
            {"item_id": "lead-1", "treatment": "lead"},
        ]}
        actions = plan_compression(resume, match_plan)
        self.assertEqual([row["op"] for row in actions],
                         ["hide_item", "merge_bullets", "shorten_bullet", "clear_self_evaluation"])
        self.assertTrue(actions[1]["writer_required"])
        self.assertEqual(actions[2]["target"], "/work_experience/1/bullets/0")
        self.assertTrue(actions[2]["writer_required"])
        compressed = apply_deterministic_compression(resume, actions)
        self.assertTrue(compressed["work_experience"][0]["hidden"])
        self.assertEqual(compressed["work_experience"][1]["bullets"], ["K" * 80, "trim this second bullet"])
        self.assertEqual(compressed["self_evaluation"], "Generic summary")
        self.assertEqual(apply_deterministic_compression(compressed, actions[3:])["self_evaluation"], "")
        self.assertEqual(resume, unchanged)
        self.assertEqual(MAX_COMPRESSION_ROUNDS, 2)
        with self.assertRaises(ValueError):
            plan_compression(resume, match_plan, round_number=3)
        with self.assertRaises(ValueError):
            apply_deterministic_compression(resume, [{**actions[0], "item_id": "wrong"}])

    def test_renderer_failure_never_claims_page_fit(self):
        with patch("app.services.resume_pdf.count_resume_pdf_pages", side_effect=RuntimeError("render unavailable")):
            result = measure_rendered_pages({}, {"page_limit": 1})
        self.assertEqual(result["status"], "render_error")
        self.assertIsNone(result["pages"])
        self.assertIsNone(result["within_page_limit"])
        self.assertEqual(result["error_type"], "RuntimeError")

    def test_real_pdf_page_count_not_character_estimate(self):
        short = {"basic_info": {"name": "Test Person"},
                 "projects": [{"name": "Short", "polished_bullets": ["One short factual line."]}]}
        long = {"basic_info": {"name": "Test Person"},
                "projects": [{"name": "Long", "polished_bullets": [f"Factual bullet {i}: " + "context " * 30
                                                                     for i in range(45)]}]}
        first = measure_rendered_pages(short, {"page_limit": 1})
        second = measure_rendered_pages(long, {"page_limit": 1})
        self.assertEqual(first["status"], "rendered")
        self.assertEqual(first["pages"], 1)
        self.assertTrue(first["within_page_limit"])
        self.assertEqual(second["status"], "rendered")
        self.assertGreater(second["pages"], 1)
        self.assertFalse(second["within_page_limit"])
        # The layout count must equal the pages of the exported PDF itself.
        import io
        import pdfplumber
        from app.services.resume_pdf import render_resume_pdf
        with pdfplumber.open(io.BytesIO(render_resume_pdf(second["template_id"], long))) as pdf:
            self.assertEqual(len(pdf.pages), second["pages"])


if __name__ == "__main__":
    unittest.main()
