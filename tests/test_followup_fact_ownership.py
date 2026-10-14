"""A current extraction's raw note can resolve an otherwise unnamed follow-up."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents import resume_graph as graph  # noqa: E402
from app.agents.triage_chain import TriageAction, TriageDecision  # noqa: E402
from app.services.resume_facts import new_fact  # noqa: E402


FOLLOWUP = "我为物品名称为空的情况添加了提示，不让空名称直接提交。"


def store(section="projects"):
    return {section: [{
        "item_id": "existing-item", "name": "借物箱", "company": "练习公司",
        "facts": [new_fact("我做过一个小程序，叫“借物箱”。")],
        "raw_notes": ["我做过一个小程序，叫“借物箱”。"],
    }]}


def note_patch(previous, text=FOLLOWUP, section="projects"):
    collected = copy.deepcopy(previous)
    collected[section][0]["raw_notes"].append(text)
    return collected


class FollowupFactOwnershipTest(unittest.TestCase):
    def test_unique_new_exact_note_adds_fact_to_existing_item_for_all_sections(self):
        for section in ("projects", "work_experience", "internship"):
            with self.subTest(section=section):
                previous = store(section)
                collected = note_patch(previous, section=section)
                saved_previous, saved_collected = copy.deepcopy(previous), copy.deepcopy(collected)
                result = graph._keep_unextracted_experience(
                    collected, previous, HumanMessage(content=FOLLOWUP, id="followup-turn"))
                self.assertEqual(len(result[section]), 1)
                self.assertEqual(len(result.get("projects", [])), 1 if section == "projects" else 0)
                self.assertEqual(result[section][0]["item_id"], "existing-item")
                fact = result[section][0]["facts"][-1]
                self.assertEqual(fact["text"], FOLLOWUP)
                self.assertEqual(fact["source_quote"], FOLLOWUP)
                self.assertEqual(fact["turn_id"], "followup-turn")
                self.assertEqual(fact["source"], "chat")
                self.assertEqual(fact["status"], "active")
                self.assertEqual(result[section][0]["raw_notes"].count(FOLLOWUP), 1)
                self.assertEqual(previous, saved_previous)
                self.assertEqual(collected, saved_collected)

    def test_unique_current_note_among_several_existing_items_resolves_owner(self):
        previous = store()
        other = {"item_id": "another-item", "name": "校园论坛", "facts": [], "raw_notes": []}
        previous["projects"].append(other)
        collected = note_patch(previous)
        result = graph._keep_unextracted_experience(collected, previous, HumanMessage(content=FOLLOWUP))
        self.assertEqual(len(result["projects"]), 2)
        self.assertEqual(result["projects"][0]["facts"][-1]["source_quote"], FOLLOWUP)
        self.assertEqual(result["projects"][1], other)

    def test_explicit_existing_name_wins_over_wrong_note_attachment(self):
        previous = store()
        previous["projects"].append({"item_id": "another-item", "name": "校园论坛", "facts": [], "raw_notes": []})
        text = "我在校园论坛项目编写了评论表单。"
        collected = note_patch(previous, text)
        result = graph._keep_unextracted_experience(collected, previous, HumanMessage(content=text))
        self.assertEqual(len(result["projects"]), 2)
        self.assertEqual(result["projects"][0], collected["projects"][0])
        self.assertEqual(result["projects"][1]["facts"][-1]["source_quote"], text)

    def test_multiple_explicit_existing_names_are_not_resolved_by_wrong_note(self):
        previous = store()
        previous["projects"].append({"item_id": "another-item", "name": "校园论坛", "facts": [], "raw_notes": []})
        text = "我为借物箱和校园论坛整理了反馈记录。"
        collected = note_patch(previous, text)
        result = graph._keep_unextracted_experience(collected, previous, HumanMessage(content=text))
        self.assertEqual(result["projects"][:2], collected["projects"])

    def test_explicit_new_experience_cannot_use_note_wrongly_attached_to_old_item(self):
        previous = store()
        for subject in ("另一个项目", "另外一个项目", "新的项目", "新项目", "别的项目", "其他项目", "另一次活动"):
            with self.subTest(subject=subject):
                text = f"我在{subject}做了表单，添加了提示。"
                collected = note_patch(previous, text)
                result = graph._keep_unextracted_experience(collected, previous, HumanMessage(content=text))
                self.assertEqual(result["projects"][0], collected["projects"][0])
                self.assertEqual(len(result["projects"]), 1)
                self.assertIn(text, result["raw_notes"])

    def test_explicit_new_name_cannot_use_note_wrongly_attached_to_old_item(self):
        previous = store()
        for text in (
            "我开发了“星河”项目的表单。",
            "我在星河项目做了表单。",
            "我开发了一个项目，叫“星河”，实现了表单。",
            "我做了一个项目名为星河，实现了表单。",
            "我做了一个小程序，叫星河，实现了表单。",
        ):
            with self.subTest(text=text):
                collected = note_patch(previous, text)
                result = graph._keep_unextracted_experience(collected, previous, HumanMessage(content=text))
                self.assertEqual(result["projects"][0], collected["projects"][0])

    def test_quoted_feature_still_uses_unique_followup_note(self):
        previous = store()
        text = "我实现了“报名提醒”功能。"
        collected = note_patch(previous, text)
        result = graph._keep_unextracted_experience(collected, previous, HumanMessage(content=text))
        self.assertEqual(len(result["projects"]), 1)
        self.assertEqual(result["projects"][0]["facts"][-1]["source_quote"], text)

    def test_only_one_project_without_a_new_note_does_not_imply_ownership(self):
        previous = store()
        result = graph._keep_unextracted_experience(copy.deepcopy(previous), previous, HumanMessage(content=FOLLOWUP))
        self.assertEqual(result["projects"][0], previous["projects"][0])
        self.assertEqual(len(result["projects"]), 1)
        self.assertIn(FOLLOWUP, result["raw_notes"])

    def test_unchanged_old_note_does_not_imply_current_ownership(self):
        previous = note_patch(store())
        result = graph._keep_unextracted_experience(copy.deepcopy(previous), previous, HumanMessage(content=FOLLOWUP))
        self.assertEqual(result["projects"][0], previous["projects"][0])
        self.assertEqual(len(result["projects"]), 1)
        self.assertIn(FOLLOWUP, result["raw_notes"])

    def test_same_new_note_on_two_items_does_not_merge_into_either(self):
        previous = store()
        previous["projects"].append({"item_id": "another-item", "name": "校园论坛", "facts": [], "raw_notes": []})
        collected = note_patch(previous)
        collected["projects"][1]["raw_notes"].append(FOLLOWUP)
        result = graph._keep_unextracted_experience(collected, previous, HumanMessage(content=FOLLOWUP))
        self.assertEqual(result["projects"][:2], collected["projects"])
        self.assertEqual(len(result["projects"]), 2)
        self.assertIn(FOLLOWUP, result["raw_notes"])

    def test_same_new_note_on_existing_and_new_item_is_ambiguous(self):
        previous = store()
        collected = note_patch(previous)
        collected["projects"].append({"item_id": "new-item", "name": "另外一段", "facts": [], "raw_notes": [FOLLOWUP]})
        self.assertIsNone(graph._new_raw_note_owner(collected, previous, FOLLOWUP))
        result = graph._keep_unextracted_experience(collected, previous, HumanMessage(content=FOLLOWUP))
        self.assertEqual(result["projects"][:2], collected["projects"])

    def test_note_on_new_unnamed_item_does_not_bind_to_existing_project(self):
        previous = store()
        collected = copy.deepcopy(previous)
        collected["projects"].append({"item_id": "new-item", "name": "", "facts": [], "raw_notes": [FOLLOWUP]})
        self.assertIsNone(graph._new_raw_note_owner(collected, previous, FOLLOWUP))
        result = graph._keep_unextracted_experience(collected, previous, HumanMessage(content=FOLLOWUP))
        self.assertEqual(result["projects"][0], previous["projects"][0])

    def test_note_without_stable_existing_identity_does_not_bind(self):
        previous = store()
        previous["projects"][0].pop("item_id")
        collected = note_patch(previous)
        self.assertIsNone(graph._new_raw_note_owner(collected, previous, FOLLOWUP))

    def test_reworded_or_partial_note_does_not_bind(self):
        previous = store()
        for note in ("为物品名称为空的情况添加了提示。", FOLLOWUP[:-1], "助手建议：" + FOLLOWUP):
            with self.subTest(note=note):
                result = graph._keep_unextracted_experience(note_patch(previous, note), previous, HumanMessage(content=FOLLOWUP))
                self.assertEqual(result["projects"][0]["facts"], previous["projects"][0]["facts"])

    def test_non_candidate_and_assistant_notes_cannot_become_facts(self):
        previous = store()
        collected = note_patch(previous)
        messages = [AIMessage(content=FOLLOWUP)] + [
            HumanMessage(content=FOLLOWUP, additional_kwargs={"career_material_type": kind})
            for kind in ("review", "jd", "reference")
        ]
        for message in messages:
            with self.subTest(message=message.type, metadata=message.additional_kwargs):
                self.assertEqual(graph._keep_unextracted_experience(collected, previous, message), collected)

    def test_non_fact_and_planned_work_notes_do_not_create_facts(self):
        previous = store()
        for text in ("好的，就是这个。", "我计划编写登录功能。", "我没有做后端开发。"):
            with self.subTest(text=text):
                collected = note_patch(previous, text)
                self.assertEqual(graph._keep_unextracted_experience(collected, previous, HumanMessage(content=text)), collected)

    def test_extracted_current_fact_does_not_gain_duplicate_fallback(self):
        previous = store()
        collected = note_patch(previous)
        collected["projects"][0]["facts"].append(new_fact(FOLLOWUP))
        self.assertEqual(graph._keep_unextracted_experience(collected, previous, HumanMessage(content=FOLLOWUP)), collected)


class FollowupWrapBranchTest(unittest.IsolatedAsyncioTestCase):
    async def test_wrap_retains_extractor_note_ownership_without_generic_project(self):
        previous = store()
        extracted = note_patch(previous)
        state = graph._init_state()
        state.update(stage="COLLECTING", collected_info=previous,
                     messages=[HumanMessage(content=FOLLOWUP, id="followup-turn")])
        decision = TriageDecision(action=TriageAction.WRAP_EXPERIENCE,
                                  reason="follow-up action", experience_snippet=FOLLOWUP)
        with (
            patch.object(graph, "_make_non_streaming_llm", return_value=object()),
            patch.object(graph, "run_triage", AsyncMock(return_value=decision)),
            patch.object(graph, "_extract_info_from_message", AsyncMock(return_value=extracted)),
            patch.object(graph, "_live_resume_update", return_value={}),
            patch.object(graph, "stream_public_reply", AsyncMock(return_value=AIMessage(content="收到这条原始补充。"))),
        ):
            result = await graph._collecting_turn_node(state, object())
        self.assertEqual(len(result["collected_info"]["projects"]), 1)
        facts = result["collected_info"]["projects"][0]["facts"]
        self.assertEqual(facts[-1]["source_quote"], FOLLOWUP)
        self.assertEqual(facts[-1]["turn_id"], "followup-turn")


class FallbackProjectNameTest(unittest.TestCase):
    def test_explicit_quoted_activity_or_project_name_precedes_grammar_fallback(self):
        for opener, closer in (("“", "”"), ("‘", "’"), ('"', '"'), ("'", "'")):
            for suffix in ("活动", "项目"):
                with self.subTest(opener=opener, suffix=suffix):
                    text = f"我在校园社团参加过{opener}拾光集{closer}{suffix}运营，负责整理反馈；报名和主持是别的同学做的。"
                    self.assertEqual(graph._guess_project_name(text), "拾光集")
                    self.assertEqual(graph._harvest_projects_from_messages([HumanMessage(content=text)])[0]["name"], "拾光集")

    def test_unlabelled_quoted_features_are_not_project_names(self):
        for text in ("我负责‘报名提醒’功能。", "我实现了“搜索”按钮，报名是同学做的。"):
            with self.subTest(text=text):
                self.assertEqual(graph._guess_project_name(text), "")

    def test_grammar_particles_alone_cannot_be_fallback_names(self):
        for particle in ("的", "了", "过", "着"):
            with self.subTest(particle=particle):
                self.assertEqual(graph._guess_project_name(f"这不是我做{particle}。"), "")
        projects = graph._harvest_projects_from_messages([
            HumanMessage(content="我整理访谈笔记，主持是同学做的。")])
        self.assertEqual(projects, [])

    def test_legitimate_single_character_and_letter_project_names_remain(self):
        for name in ("A", "海"):
            with self.subTest(name=name):
                self.assertEqual(graph._guess_project_name(f"我做{name}项目时整理反馈。"), name)
                self.assertEqual(graph._guess_project_name(f"我参与“{name}”项目。"), name)
        self.assertFalse(graph._snippet_matches_experience("我用 FastAPI 编写接口。", {"name": "A"}))

    def test_rejected_particle_does_not_hide_later_explicit_name(self):
        self.assertEqual(graph._guess_project_name("这是同学做的，我做海项目时整理了笔记。"), "海")


if __name__ == "__main__":
    unittest.main()
