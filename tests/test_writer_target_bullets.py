"""A validated match-plan count is an actual draft limit, not a suggestion."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from test_resume_writer import FakeModel, fact, item, run  # noqa: E402


TEXTS = ["整理用户反馈", "核对接口记录", "编写检查清单"]


def source(section="projects"):
    return {section: [{"item_id": "a", "name": "甲", "company": "甲单位",
                       "facts": [fact(f"f{i}", text) for i, text in enumerate(TEXTS)]}],
            "skills": []}


def model(section, treatment, count, *, include_item=True):
    rows = [item("a", section, [(text, [f"f{i}"]) for i, text in enumerate(TEXTS)])] if include_item else []
    return FakeModel([("OnePassOutput", {
        "match_plan": {"experience_plan": [{"item_id": "a", "treatment": treatment, "target_bullets": count}]},
        "writer": {"items": rows},
    })])


class WriterTargetBulletsTest(unittest.TestCase):
    def test_requested_counts_and_treatment_maximum_both_apply(self):
        for section in ("projects", "work_experience"):
            for treatment, maximum in (("lead", 3), ("keep", 2), ("brief", 1), ("backup", 0)):
                for count in range(4):
                    with self.subTest(section=section, treatment=treatment, count=count):
                        result = run(source(section), {}, model(section, treatment, count))
                        row = result["resume_data"][section][0]
                        field = "polished_bullets" if section == "projects" else "bullets"
                        if treatment == "backup":
                            self.assertTrue(row["hidden"])
                        else:
                            self.assertEqual(row[field], TEXTS[:min(count, maximum)])
                            self.assertEqual(len(result["resume_meta"]["bullets"]["a"]), min(count, maximum))
                        self.assertEqual(result["match_plan"]["experience_plan"][0]["target_bullets"], min(count, maximum))

    def test_explicit_zero_without_writer_row_is_not_reported_as_failure(self):
        for scope, targets in (("whole", []), ("item", ["a"]), ("section", ["projects"])):
            with self.subTest(scope=scope):
                current = {"projects": [{"item_id": "a", "name": "甲", "description": "旧正文说明",
                                         "polished_bullets": list(TEXTS)}]}
                result = run(source(), {}, model("projects", "lead", 0, include_item=False),
                             current_data=current, scope=scope, targets=targets)
                self.assertEqual(result["resume_data"]["projects"][0]["polished_bullets"], [])
                self.assertEqual(result["resume_data"]["projects"][0]["description"], "")
                self.assertEqual(result["writer_diagnostic"]["status"], "model_completed")
                self.assertEqual(current["projects"][0]["polished_bullets"], TEXTS)

    def test_missing_writer_item_fallback_respects_accepted_plan(self):
        collected = source()
        collected["projects"].append({"item_id": "b", "name": "乙", "facts": [fact("fb", "检查重复记录")]})
        writer = FakeModel([("OnePassOutput", {
            "match_plan": {"experience_plan": [{"item_id": "a", "treatment": "lead", "target_bullets": 1}]},
            "writer": {"items": [item("b", "projects", [("检查重复记录", ["fb"])])]},
        })])
        result = run(collected, {}, writer)
        a = next(row for row in result["resume_data"]["projects"] if row["item_id"] == "a")
        self.assertEqual(a["polished_bullets"], TEXTS[:1])

    def test_item_zero_preserves_unselected_sibling_bytes(self):
        collected = source()
        collected["projects"].append({"item_id": "b", "name": "乙", "facts": [fact("fb", "检查重复记录")]})
        sibling = {"item_id": "b", "name": "乙", "description": "保留说明", "polished_bullets": ["检查重复记录"]}
        current = {"projects": [{"item_id": "a", "name": "甲", "polished_bullets": list(TEXTS)}, deepcopy(sibling)]}
        result = run(collected, {}, model("projects", "lead", 0, include_item=False),
                     current_data=current, scope="item", targets=["a"])
        self.assertEqual(result["resume_data"]["projects"][1], sibling)

    def test_bullet_edit_ignores_document_plan_count_for_siblings(self):
        for treatment, count in (("lead", 0), ("lead", 1), ("brief", 0), ("backup", 0)):
            with self.subTest(treatment=treatment, count=count):
                current = {"projects": [{"item_id": "a", "name": "甲", "polished_bullets": list(TEXTS)}]}
                writer = FakeModel([("OnePassOutput", {
                    "match_plan": {"experience_plan": [{"item_id": "a", "treatment": treatment, "target_bullets": count}]},
                    "writer": {"items": [item("a", "projects", [(TEXTS[0], ["f0"])])]},
                })])
                result = run(source(), {}, writer, current_data=current,
                             scope="bullet", targets=["/projects/0/polished_bullets/2"])
                self.assertEqual(result["resume_data"]["projects"][0]["polished_bullets"], [TEXTS[0], TEXTS[1], TEXTS[0]])
                self.assertFalse(result["resume_data"]["projects"][0].get("hidden", False))

    def test_capped_output_keeps_active_limit_visible_without_extra_bullet(self):
        collected = source()
        collected["projects"][0]["facts"].append(fact("limit", "没有上线", kind="status_limit"))
        result = run(collected, {}, model("projects", "lead", 1))
        bullets = result["resume_data"]["projects"][0]["polished_bullets"]
        self.assertEqual(len(bullets), 1)
        self.assertIn("没有上线", bullets[0])


if __name__ == "__main__":
    unittest.main()
