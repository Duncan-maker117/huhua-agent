"""Heading-first followups and contact fallback regressions; no live providers."""
from copy import deepcopy
from importlib import import_module
import unittest
from unittest.mock import AsyncMock, patch

from test_orchestrator import Model, call, registry
from test_orchestrator_p2h import draft_outcome, followup_state
from app.agents import orchestrator as loop, orchestrator_tools as tools
from app.config import Settings
from app.services.ask_user import pending_card

DESIGN_CONTACTS = "邮箱已记下；电话还没有，所以头部暂时空着，需要的话补一个即可。"


def missing_heading():
    value = followup_state()
    for store in (value["collected_info"], value["resume_data"]):
        store["projects"][0].update(name="项目（待补名称）", start_date="", end_date="", role="")
    return value


class P2jTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch("app.config.get_settings", return_value=Settings(_env_file=None, AGENT_MODE="loop")))

    def test_missing_heading_precedes_depth_and_only_missing_fields_are_asked(self):
        value = missing_heading()
        with patch("app.agents.interviewer.question_candidates") as candidates:
            card = tools._draft_followup(value, tools.ToolContext())
            self.assertEqual([q["id"] for q in card["questions"]], ["name", "dates", "role"])
            candidates.assert_not_called()
        for store in (value["collected_info"], value["resume_data"]):
            store["projects"][0].update(name="资料核对项目", end_date="至今", role="参与者")
        self.assertEqual([q["id"] for q in tools._draft_followup(value, tools.ToolContext())["questions"]], ["dates"])
        value["resume_data"]["projects"][0]["start_date"] = "2025-03"
        self.assertEqual(tools._draft_followup(value, tools.ToolContext())["questions"][0]["id"], "evaluation")

    def test_main_written_experience_uses_plan_and_excludes_hidden_empty_backup(self):
        for excluded in ("hidden", "empty", "backup", "zero", "section"):
            with self.subTest(excluded=excluded):
                value = missing_heading()
                first, main = value["resume_data"]["projects"]
                main.update(name="主项目（真实名称）", start_date="", end_date="至今", role="参与者")
                value["collected_info"]["projects"][1].update(name=main["name"])
                plan = [{"item_id": first["item_id"], "treatment": "lead", "target_bullets": 3},
                        {"item_id": main["item_id"], "treatment": "support", "target_bullets": 2}]
                if excluded == "hidden":
                    first["hidden"] = True
                elif excluded == "empty":
                    first["polished_bullets"] = []
                elif excluded == "backup":
                    plan[0]["treatment"] = "backup"
                elif excluded == "zero":
                    plan[0]["target_bullets"] = 0
                else:
                    value["resume_data"]["campus"] = [first]
                    value["resume_data"]["projects"] = [main]
                    value["resume_data"]["sections"] = [{"id": "projects", "kind": "projects", "title": "项目经历"}]
                value["confirmed_plan"] = {"experience_plan": plan}
                card = tools._draft_followup(value, tools.ToolContext())
                self.assertEqual(card["subject"], main["name"])
                self.assertEqual([q["id"] for q in card["questions"]], ["dates"])
        value = missing_heading()
        value["confirmed_plan"] = {"experience_plan": [
            {"item_id": "p1", "treatment": "brief"}, {"item_id": "p2", "treatment": "lead"}]}
        value["resume_data"]["projects"][1]["start_date"] = ""
        self.assertEqual(tools._draft_followup(value, tools.ToolContext())["subject"], "页面原型项目")

    def test_identity_binding_closed_dimensions_and_budget_are_preserved(self):
        value = missing_heading()
        for store in (value["collected_info"], value["resume_data"]):
            store["projects"][1]["name"] = "项目（待补名称）"
        value["closed_questions"] = [{"subject": "p1", "id": "name", "dimension": "name", "reason": "unknown"}]
        card = tools._draft_followup(value, tools.ToolContext())
        self.assertEqual(card["subject"], "p1")
        self.assertEqual([q["id"] for q in card["questions"]], ["dates", "role"])
        for patch_state in ({"pending_plan": {"kind": "structure_plan"}},
                            {"session_constraints": {"questions_finished": True}},
                            {"collected_info": {**value["collected_info"], "no_more_questions": True}}):
            self.assertFalse(tools._draft_followup({**value, **patch_state}, tools.ToolContext()))
        self.assertFalse(tools._draft_followup(value, tools.ToolContext(ask_used=True)))

    async def test_model_cannot_replace_heading_card_and_budget_fallback_keeps_all_fields(self):
        for script in (
            [call("write_draft"), call("ask_user", card={"subject": "另一段经历", "questions": [
                {"id": "evaluation", "prompt": "怎么评测？", "kind": "text"}]}), {"content": "稿件已生成。"}],
            [call("check_layout"), call("check_layout"), call("check_layout"), call("write_draft"), RuntimeError("offline")],
        ):
            value = missing_heading()
            specs = registry()
            specs.update({key: tools.TOOLS[key] for key in ("write_draft", "ask_user")})
            events = []
            with patch.object(tools, "_write", AsyncMock(return_value=draft_outcome(value))):
                result = await loop.run_orchestrator(value, Model(script), registry=specs, emit=events.append)
            card = pending_card({**value, **result})
            self.assertEqual(card["subject"], "项目（待补名称）")
            self.assertEqual([q["id"] for q in card["questions"]], ["name", "dates", "role"])
            self.assertEqual(len([e for e in events if e["type"] == "guidance"]), 1)

    def test_contact_fallback_understands_optional_synonyms_without_false_acknowledgments(self):
        self.assertEqual(loop._unrequested_contacts(DESIGN_CONTACTS, ["phone"]), [])
        for field, text in (("phone", "电话没有，需要的话补一个即可。"),
                            ("phone", "手机号可以补一下。"), ("phone", "请提供 phone。"),
                            ("email", "邮件地址可留一个。"), ("email", "email 方便的话发给我。"),
                            ("name", "姓名可以补上。"), ("name", "名字方便的话告诉我。")):
            self.assertEqual(loop._unrequested_contacts(text, [field]), [], text)
        for text in ("邮箱已记下。", "手机号不用现在补。", "手机拍摄素材、文案由店长提供。", "稿子已生成。"):
            self.assertEqual(loop._unrequested_contacts(text, ["phone"]), ["手机"], text)
        self.assertEqual(loop._unrequested_contacts("邮箱已记下，但电话需要补一个。", ["phone", "email"]), ["邮箱"])

    async def test_design_original_is_not_followed_by_a_duplicate_and_omission_gets_one(self):
        for prose in (DESIGN_CONTACTS, "稿子已生成。", "请提供手机。"):
            value = followup_state()
            for store in (value["collected_info"], value["resume_data"]):
                store["basic_info"].pop("phone", None)
            specs = registry()
            specs.update({key: tools.TOOLS[key] for key in ("write_draft", "ask_user")})
            events = []
            with patch.object(tools, "_write", AsyncMock(return_value=draft_outcome(value))):
                result = await loop.run_orchestrator(value, Model([call("write_draft"),
                    {"content": prose, "deltas": list(prose)}]), registry=specs, emit=events.append)
            text = result["messages"][-1].content
            self.assertEqual(text, "".join(e["content"] for e in events if e["type"] == loop.PUBLIC_REPLY_EVENT))
            if prose == DESIGN_CONTACTS:
                self.assertEqual(text, DESIGN_CONTACTS)
                self.assertNotIn("请补充手机", text)
            else:
                self.assertEqual(text.count("请补充手机，用于简历头部。"), 1)
            self.assertTrue(result["session_constraints"]["contacts_requested"])

    def test_material_timing_never_passes_missing_material_or_unsaved_or_late_draft(self):
        checks = import_module("evaluation.persona-ux.loop_checks")
        from test_persona_loop import new_turns
        draft = new_turns("upload")[0]
        turns = [{"action": f"initial_{i}", "resume_data": {}} for i in range(1, 5)]
        turns[-1].update({k: v for k, v in draft.items() if k != "action"})
        stats = checks.observations(turns, "aipm_real")
        self.assertEqual((stats["first_draft_turn"], stats["first_material_turn"], stats["turns_from_material"]), (4, 4, 1))
        def passed(rows):
            return next(c["status"] for c in checks.evaluate_loop("aipm_real", rows) if c["id"].endswith("first_draft_by_turn3"))
        self.assertEqual(passed(turns), "pass")
        for mutate in (lambda rows: rows[-1].update(action="other"),
                       lambda rows: rows[-1].update(revision=None),
                       lambda rows: rows[-1].update(resume_data={}),
                       lambda rows: rows[0].update({k: v for k, v in draft.items() if k != "action"})):
            changed = deepcopy(turns)
            mutate(changed)
            self.assertEqual(passed(changed), "fail")
        self.assertEqual(passed([]), "fail")
        turns[-1] = {"action": "initial_4", "resume_data": {}}
        turns += [{"action": "confirm"}, {"action": "contacts"}, draft]
        self.assertEqual(passed(turns), "fail")
        self.assertEqual(checks.observations(turns, "aipm_real")["turns_from_material"], 4)


if __name__ == "__main__":
    unittest.main()
