"""Compound edit execution stays reversible and bounded to cited user values."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.edit_plan import execute_edit_plan  # noqa: E402


def document():
    return {"basic_info": {"name": "Candidate", "location": "", "objective": ""},
            "projects": [
                {"item_id": "bad", "name": "海港城", "polished_bullets": ["误识别项目"]},
                {"item_id": "p1", "name": "Project Delta", "role": "设计者",
                 "polished_bullets": ["**整理反馈**，见 [PR #2](https://example.org/pr/2)", "第二条", "第三条"]},
                {"item_id": "p2", "name": "Project Echo", "polished_bullets": ["A", "B", "C"]},
            ],
            "work_experience": [{"item_id": "w1", "company": "Example Ltd", "title": "实习生", "bullets": ["核对资料"]}],
            "education": [], "self_evaluation": "模板化自我评价"}


def facts():
    return {"projects": [{"item_id": "p1", "name": "Project Delta", "facts": [
        {"id": "f-role", "text": "产品设计实习生", "field": "role", "status": "active",
         "source_quote": "产品设计实习生", "source": "chat", "kind": "role"},
        {"id": "f-old", "text": "负责人", "field": "role", "status": "superseded",
         "source_quote": "负责人", "source": "chat", "kind": "role"},
    ]}]}


class EditPlanTest(unittest.TestCase):
    def test_eight_independent_operations_and_one_writer_batch(self):
        data, evidence = document(), facts()
        before_data, before_facts = deepcopy(data), deepcopy(evidence)
        instruction = ("海港城是所在地，不是项目，删除海港城这个误识别项目并保留所在地海港城；"
                       "项目各保留最多两条描述；删除自我评价；Project Delta 的 PR 链接去掉 Markdown 格式；"
                       "求职意向写产品实习生；压缩成一页；把 Project Echo 的表达精简。")
        plan = [
            {"op": "delete_item", "target": "海港城", "args": {}},
            {"op": "set_field", "target": "/basic_info/location", "args": {"value": "海港城"}},
            {"op": "cap_bullets", "target": "projects", "args": {"n": 2}},
            {"op": "remove_section", "target": "自我评价", "args": {}},
            {"op": "clean_format", "target": "Project Delta", "args": {}},
            {"op": "set_field", "target": "/basic_info/objective", "args": {"value": "产品实习生"}},
            {"op": "set_constraint", "target": "page_limit", "args": {"page_limit": 1}},
            {"op": "compress", "target": "Project Echo", "args": {"instruction": "模型自造内容"}},
        ]
        result = execute_edit_plan(data, {"page_limit": 2}, plan,
                                   collected_info=evidence, instruction=instruction)
        changed = result["data"]
        self.assertEqual(len(result["operation_results"]), 8)
        self.assertTrue(all(row["status"] == "done" for row in result["operation_results"]))
        self.assertTrue(changed["projects"][0]["hidden"])
        self.assertEqual(changed["basic_info"]["location"], "海港城")
        self.assertEqual(changed["basic_info"]["objective"], "产品实习生")
        self.assertEqual(len(changed["projects"][1]["polished_bullets"]), 2)
        self.assertEqual(len(changed["projects"][2]["polished_bullets"]), 2)
        self.assertNotIn("self_evaluation", [row["kind"] for row in changed["sections"]])
        self.assertEqual(changed["self_evaluation"], "模板化自我评价")
        self.assertEqual(changed["projects"][1]["polished_bullets"][0], "整理反馈，见 PR #2")
        self.assertEqual(changed["projects"][1]["links"],
                         [{"text": "PR #2", "url": "https://example.org/pr/2"}])
        self.assertEqual(result["constraints"]["page_limit"], 1)
        self.assertEqual(result["writer_requests"],
                         [{"scope": "item", "targets": ["p2"], "instruction": instruction}])
        self.assertEqual(data, before_data)
        self.assertEqual(evidence, before_facts)

    def test_unresolved_one_operation_does_not_block_other_operations(self):
        plan = [{"op": "delete_item", "target": "不存在的经历", "args": {}},
                {"op": "hide_item", "target": "第2个项目", "args": {}},
                {"op": "rewrite", "target": "第9个项目", "args": {}},
                {"op": "refocus", "target": "Project Echo", "args": {}}]
        result = execute_edit_plan(document(), {}, plan,
                                   instruction="删除不存在的经历，隐藏第二个项目，改第九个项目，突出 Project Echo")
        self.assertEqual([row["status"] for row in result["operation_results"]],
                         ["needs_confirmation", "done", "needs_confirmation", "done"])
        self.assertTrue(result["data"]["projects"][1]["hidden"])
        self.assertEqual(result["writer_requests"][0]["targets"], ["p2"])

    def test_set_field_requires_literal_basic_value_and_active_header_fact(self):
        plan = [
            {"op": "set_field", "target": "/basic_info/objective", "args": {"value": "虚构高级主管"}},
            {"op": "set_field", "target": "Project Delta", "args": {"field": "role", "value": "负责人"}},
            {"op": "set_field", "target": "Project Delta", "args": {"field": "role", "value": "产品设计实习生"}},
            {"op": "set_field", "target": "Project Delta", "args": {"field": "description", "value": "虚构成果"}},
        ]
        result = execute_edit_plan(document(), {}, plan, collected_info=facts(),
                                   instruction="把 Project Delta 的角色更正为产品设计实习生")
        self.assertEqual([row["status"] for row in result["operation_results"]],
                         ["cannot", "needs_confirmation", "done", "cannot"])
        self.assertEqual(result["data"]["projects"][1]["role"], "产品设计实习生")
        self.assertEqual(result["data"]["basic_info"]["objective"], "")

    def test_already_satisfied_is_reported_without_claiming_change(self):
        plan = [{"op": "hide_item", "target": "/projects/0", "args": {}},
                {"op": "hide_item", "target": "/projects/0", "args": {}}]
        result = execute_edit_plan(document(), {}, plan, instruction="隐藏第一个项目")
        self.assertTrue(result["operation_results"][0]["changed"])
        self.assertFalse(result["operation_results"][1]["changed"])
        self.assertEqual(result["operation_results"][1]["reason"], "already_satisfied")

    def test_model_cannot_expand_one_item_edit_to_entire_section(self):
        plan = [{"op": "hide_item", "target": "projects", "args": {}},
                {"op": "cap_bullets", "target": "projects", "args": {"n": 2}},
                {"op": "rewrite", "target": "projects", "args": {}}]
        result = execute_edit_plan(document(), {}, plan,
                                   instruction="只修改 Project Delta，最多两条，别动其他项目")
        self.assertEqual([row["status"] for row in result["operation_results"]],
                         ["needs_confirmation", "needs_confirmation", "needs_confirmation"])
        self.assertEqual(result["writer_requests"], [])
        self.assertFalse(any(item.get("hidden") for item in result["data"]["projects"]))

    def test_ordinal_targets_are_anchored_before_previous_hide(self):
        plan = [{"op": "hide_item", "target": "第一个项目", "args": {}},
                {"op": "hide_item", "target": "第二个项目", "args": {}}]
        result = execute_edit_plan(document(), {}, plan,
                                   instruction="删除第一个项目，隐藏第二个项目")
        self.assertEqual([row["status"] for row in result["operation_results"]], ["done", "done"])
        self.assertEqual([bool(item.get("hidden")) for item in result["data"]["projects"]],
                         [True, True, False])

    def test_deletion_word_in_another_clause_cannot_clear_field_or_section(self):
        plan = [{"op": "set_field", "target": "/basic_info/objective", "args": {"value": ""}},
                {"op": "remove_section", "target": "自我评价", "args": {}}]
        result = execute_edit_plan(document(), {}, plan,
                                   instruction="删除误识别项目，求职意向保持原样，保留自我评价")
        self.assertEqual([row["status"] for row in result["operation_results"]],
                         ["cannot", "needs_confirmation"])

    def test_set_field_cannot_redirect_a_json_pointer(self):
        plan = [{"op": "set_field", "target": "/basic_info/location",
                 "args": {"field": "objective", "value": "海港城"}},
                {"op": "set_field", "target": "/projects/1/role",
                 "args": {"field": "name", "value": "产品设计实习生"}}]
        result = execute_edit_plan(document(), {}, plan, collected_info=facts(),
                                   instruction="地点海港城，角色产品设计实习生")
        self.assertEqual([row["status"] for row in result["operation_results"]], ["cannot", "cannot"])
        self.assertEqual(result["data"]["basic_info"]["objective"], "")
        self.assertEqual(result["data"]["projects"][1]["name"], "Project Delta")

    def test_clean_format_deduplicates_visible_skills_and_flat_list_follows_groups(self):
        data = document()
        data["skills"] = ["Python", " python ", "SQL"]
        data["skill_groups"] = {"开发": ["Python", "SQL"], "数据": ["sql", "Excel"]}
        result = execute_edit_plan(data, {}, [{"op": "clean_format", "target": "技能", "args": {}}],
                                   instruction="精简重复技能")
        self.assertEqual(result["operation_results"][0]["status"], "done")
        self.assertEqual(result["data"]["skills"], ["Python", "SQL", "Excel"])
        self.assertEqual(result["data"]["skill_groups"],
                         {"开发": ["Python", "SQL"], "数据": ["Excel"]})
        self.assertEqual(data["skills"], ["Python", " python ", "SQL"])


if __name__ == "__main__":
    unittest.main()
