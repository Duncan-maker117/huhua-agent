"""Evidence master boundaries; all fixtures are synthetic."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.resume_facts import active_facts_for_writer, append_editor_facts, normalize_fact_store, new_fact


class ResumeFactsTest(unittest.TestCase):
    def test_legacy_raw_description_migrates_once_with_profile_refs(self):
        source = {"projects": [{"name": "PaperTool", "item_id": "stable", "description": "画了原型，未上线。",
                                "polished_bullets": ["上线后服务百万用户"],
                                "profile_refs": [{"fact_id": "p1", "revision": 2}]}]}
        once = normalize_fact_store(source)
        twice = normalize_fact_store(once)
        self.assertEqual(once, twice)
        fact = once["projects"][0]["facts"][0]
        self.assertEqual(fact["source_quote"], "画了原型，未上线。")
        self.assertEqual(fact["profile_refs"], source["projects"][0]["profile_refs"])
        self.assertNotIn("百万", str(once["projects"][0]["facts"]))

    def test_editor_adds_only_manual_changes_and_preserves_deleted_fact(self):
        collected = {"projects": [{"item_id": "p1", "name": "PaperTool", "facts": [new_fact("画了原型", quote="画了原型")],
                                   "raw_notes": ["画了原型"]}], "basic_info": {"name": "旧名"}}
        old = {"projects": [{"item_id": "p1", "name": "PaperTool", "polished_bullets": ["润色稿"]}]}
        new = {"basic_info": {"name": "新名"}, "skills": ["Python"], "projects": [{"item_id": "p1", "name": "PaperTool",
              "polished_bullets": ["手动新增一条"], "role": "参与设计"}]}
        result = append_editor_facts(collected, old, new, "turn-1")
        self.assertEqual(result["basic_info"]["name"], "新名")
        facts = result["projects"][0]["facts"]
        self.assertEqual([f["text"] for f in facts], ["画了原型", "手动新增一条", "参与设计"])
        self.assertTrue(all(f["source"] == "editor" and f["source_quote"] == f["text"] for f in facts[1:]))
        self.assertEqual(result["skills"][0]["source"], "editor")
        again = append_editor_facts(result, new, new, "turn-2")
        self.assertEqual(again["projects"][0]["facts"], facts)

    def test_reorder_legacy_items_keeps_identity_and_does_not_duplicate(self):
        collected = {"projects": [{"name": "A", "description": "做了 A。"}, {"name": "B", "description": "做了 B。"}]}
        old = {"projects": [{"name": "A", "polished_bullets": ["A"]}, {"name": "B", "polished_bullets": ["B"]}]}
        new = {"projects": [{"name": "B", "polished_bullets": ["B"]}, {"name": "A", "polished_bullets": ["A"]}]}
        result = append_editor_facts(collected, old, new, "turn")
        self.assertEqual(len(result["projects"]), 2)
        self.assertEqual(new["projects"][0]["item_id"], result["projects"][1]["item_id"])
        self.assertEqual(new["projects"][1]["item_id"], result["projects"][0]["item_id"])

    def test_writer_input_excludes_superseded_and_raw_notes(self):
        old = new_fact("我负责旧功能", quote="我负责旧功能")
        old["status"] = "superseded"
        current = new_fact("我只参与新功能", quote="我只参与新功能")
        collected = {"skills": [{"name": "Rust", "source_quote": "Rust", "status": "deleted"}],
                     "projects": [{"item_id": "x", "name": "Test", "role": "负责人",
                                   "description": "我负责旧功能", "raw_notes": ["我负责旧功能"],
                                   "facts": [old, current]}]}
        visible = active_facts_for_writer(copy.deepcopy(collected))
        self.assertEqual([f["text"] for f in visible["projects"][0]["facts"]], ["我只参与新功能"])
        self.assertNotIn("我负责旧功能", str(visible))
        self.assertNotIn("负责人", str(visible))
        self.assertEqual(visible["skills"], [])

    def test_explicitly_empty_facts_do_not_resurrect_source_text(self):
        collected = {"projects": [{"item_id": "x", "name": "Forgotten", "description": "不应恢复的旧事实",
                                   "facts": []}]}
        self.assertEqual(normalize_fact_store(collected)["projects"][0]["raw_notes"], [])
        visible = active_facts_for_writer(collected)
        self.assertEqual(visible["projects"], [])
        self.assertNotIn("不应恢复", str(visible))

    def test_writer_facts_are_bound_to_their_own_item(self):
        collected = {"projects": [{"item_id": "a", "name": "A", "facts": [new_fact("核对名单")]},
                                  {"item_id": "b", "name": "B", "facts": [new_fact("核对名单")]}]}
        visible = active_facts_for_writer(collected)
        self.assertEqual([item["facts"][0]["item_id"] for item in visible["projects"]], ["a", "b"])

    def test_import_conflicting_header_does_not_enter_active_writer_facts(self):
        from app.agents.resume_graph import _merge_imported_candidate
        own = new_fact("参与开发", kind="role")
        own["field"] = "role"
        incoming = new_fact("主导开发", kind="role", source="import")
        incoming["field"] = "role"
        collected = {"projects": [{"item_id": "p1", "name": "PaperTool", "role": "参与开发", "facts": [own], "raw_notes": []}]}
        imported = {"projects": [{"item_id": "p2", "name": "PaperTool", "role": "主导开发", "facts": [incoming], "raw_notes": []}]}
        merged = _merge_imported_candidate(collected, imported)
        self.assertEqual(merged["projects"][0]["role"], "参与开发")
        self.assertEqual(merged["projects"][0]["facts"][-1]["status"], "superseded")
        self.assertEqual([f["text"] for f in active_facts_for_writer(merged)["projects"][0]["facts"]], ["参与开发"])
        self.assertEqual(merged["field_conflicts"][0]["selected"], "参与开发")

    def test_education_values_never_become_skills(self):
        from app.services.resume_facts import normalize_fact_store
        store = normalize_fact_store({
            "education": [{"item_id": "e1", "school": "哈尔滨商业大学", "major": "计算机科学与技术"}],
            "skills": [{"name": "计算机科学与技术"}, {"name": "哈尔滨商业大学"}, {"name": "FastAPI"}]})
        self.assertEqual([skill["name"] for skill in store["skills"]], ["FastAPI"])


if __name__ == "__main__":
    unittest.main()
