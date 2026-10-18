"""Loop writing parity and behavior; production adapters with offline models only."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests")]
from app.agents import orchestrator_tools as tools  # noqa: E402
from app.agents import resume_graph as graph  # noqa: E402
from app.agents.fact_extractor import extract_facts_patch, apply_fact_patch  # noqa: E402
from app.services.resume_versions import text_hash  # noqa: E402
from test_orchestrator_tools import PHONE, EMAIL, Writer, collected, measured, state_with_draft  # noqa: E402
from test_batch14c5_labeled import FIXTURE, WrongModel, collected as labeled_facts  # noqa: E402
from test_campus_and_naming import ExtractorStub  # noqa: E402
from test_persona_regressions import correction_state  # noqa: E402
from test_structure_plan import card, state as plan_state  # noqa: E402


class OrchestratorWritingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=measured))
        self.enterContext(patch("app.services.resume_capacity.measure_rendered_pages", side_effect=measured))

    async def test_plan_and_labeled_writer_use_existing_persona_evidence(self):
        for persona in ("aipm", "aipm_real"):
            with self.subTest(persona=persona):
                facts = labeled_facts(persona)
                if persona == "aipm_real":
                    extracted = await extract_facts_patch(FIXTURE[persona]["inputs"][3], facts,
                        ExtractorStub({"items": []}), turn_id="p2-pains")
                    facts = apply_fact_patch(facts, extracted)
                facts["basic_info"] = {"name": "离线候选人", "phone": PHONE, "email": EMAIL}
                state = {**graph._init_state(), "collected_info": facts,
                         "jd_info": {"role_profile": {"role_family": "ai_pm"}},
                         "messages": [HumanMessage(content="按已有材料直接生成", id="draft")]}
                model = WrongModel(invalid_classification=True, hallucinate=True)
                before = deepcopy(state)
                outcome = await tools.write_draft(state, {}, tools.ToolContext(llm=model))
                self.assertEqual(outcome.result["status"], "ok", outcome.result)
                calls = [name for name, _ in model.calls]
                self.assertLess(calls.index("StructurePlan"), calls.index("WriterDraft"))
                self.assertIn("FactSlots", calls)
                self.assertNotIn("OnePassOutput", calls)
                result = outcome.update
                self.assertEqual(result["confirmed_plan"]["bullet_style"], "labeled")
                self.assertEqual(result["resume_meta"]["confirmed_plan"], result["confirmed_plan"])
                self.assertFalse(result["pending_plan"])
                self.assertFalse(result["plan_required"])
                self.assertFalse(any(e.get("type") == "guidance" for e in outcome.events))
                project = result["resume_data"]["projects"][0]
                body = project["polished_bullets"]
                self.assertTrue(body)
                self.assertTrue(all(line.startswith(("问题：", "决策：", "迭代：", "技术：", "现状：")) for line in body), body)
                for key in ("name", "role", "start_date", "end_date"):
                    self.assertEqual(project[key], FIXTURE[persona]["project"][key])
                self.assertTrue(project.get("positioning"))
                if persona == "aipm_real":
                    pain = next(line for line in body if line.startswith("问题："))
                    for term in ("填空", "复制粘贴", "无法编辑", "结构"):
                        self.assertIn(term, pain)
                    self.assertTrue(any("MCP" in line for line in body))
                self.assertNotIn("1000", str(body))
                for line, record in zip(body, result["resume_meta"]["bullets"][project["item_id"]]):
                    self.assertEqual(record["text_hash"], text_hash(line))
                    self.assertTrue(record["fact_ids"])
                self.assertEqual(result["resume_data"]["basic_info"]["phone"], PHONE)
                self.assertEqual(result["resume_data"]["basic_info"]["email"], EMAIL)
                for value in (model.calls, outcome.result):
                    self.assertNotIn(PHONE, json.dumps(value, ensure_ascii=False))
                    self.assertNotIn(EMAIL, json.dumps(value, ensure_ascii=False))
                self.assertEqual(state, before)

    async def test_user_plain_choice_is_reused_from_checkpoint_metadata(self):
        facts = labeled_facts("aipm")
        selected = {"label": "自选", "bullet_style": "plain", "bullet_style_source": "user",
                    "experience_plan": [{"item_id": facts["projects"][0]["item_id"],
                                         "treatment": "lead", "target_bullets": 3}], "section_order": ["projects"]}
        state = {**graph._init_state(), "collected_info": facts, "resume_meta": {"confirmed_plan": selected},
                 "jd_info": {"role_profile": {"role_family": "ai_pm"}}}
        model = WrongModel()
        outcome = await tools.write_draft(state, {}, tools.ToolContext(llm=model))
        self.assertEqual(outcome.result["status"], "ok", outcome.result)
        names = [name for name, _ in model.calls]
        self.assertIn("WriterDraft", names)
        self.assertNotIn("StructurePlan", names)
        self.assertNotIn("FactSlots", names)
        self.assertEqual(outcome.update["confirmed_plan"]["bullet_style"], "plain")
        self.assertEqual(outcome.update["confirmed_plan"]["bullet_style_source"], "user")

    async def test_pending_alternative_is_selected_without_replanning(self):
        state = {**plan_state("用备选方案1"), "pending_plan": card()}
        seen = []
        async def pipeline(working, base, *args, **kwargs):
            seen.append(deepcopy(working))
            return {"resume_data": base, "changed": True, "confirmed_plan": working["confirmed_plan"]}
        with patch.object(tools, "_structure_card", side_effect=AssertionError("must reuse pending plan")), \
                patch("app.agents.tailor_pipeline.run_tailor_pipeline", side_effect=pipeline):
            result = await tools.write_draft(state, {}, tools.ToolContext(llm=object()))
        self.assertEqual(result.result["status"], "ok")
        self.assertEqual(seen[0]["confirmed_plan"]["label"], "问题发现型")
        self.assertEqual(seen[0]["confirmed_plan"]["section_order"][0], "projects")

    async def test_literal_corrections_share_legacy_transaction_and_never_rewrite(self):
        for persona in ("tech", "career"):
            with self.subTest(persona=persona):
                state = correction_state(persona)
                before = deepcopy(state)
                expected = await graph.evaluating_node(state, object())
                saved = []
                async def save(values):
                    saved.append(deepcopy(values))
                token = graph._intake_saver.set(save)
                ctx = tools.ToolContext()
                try:
                    with patch.object(tools, "_write", side_effect=AssertionError("corrections must not call writer")), \
                            patch("app.agents.fact_extractor.extract_facts_patch", side_effect=AssertionError("no model extraction")):
                        outcome = await tools.record_facts(state, {"source_id": "current"}, ctx)
                        repeated = await tools.edit_resume({**state, **outcome.update},
                            {"instruction": "只更新刚才那个数字"}, ctx)
                finally:
                    graph._intake_saver.reset(token)
                self.assertEqual(outcome.result["status"], "ok", outcome.result)
                self.assertTrue(outcome.result["correction_applied"])
                self.assertTrue(outcome.stop)
                self.assertEqual(outcome.update["resume_data"], expected["resume_data"])
                self.assertEqual(saved[0]["collected_info"], outcome.update["collected_info"])
                self.assertEqual(len(saved), 1)
                self.assertTrue(outcome.update["resume_versions"])
                self.assertEqual(outcome.update["resume_data"]["projects"], state["resume_data"]["projects"])
                for line, record in zip(outcome.update["resume_data"]["work_experience"][0]["bullets"],
                                        outcome.update["resume_meta"]["bullets"]["work"]):
                    self.assertEqual(record["text_hash"], text_hash(line))
                    self.assertTrue(record["fact_ids"])
                self.assertEqual(repeated.result, {"status": "unchanged", "correction_applied": True})
                self.assertFalse(repeated.update)
                self.assertEqual(state, before)

    async def test_direct_edit_uses_user_correction_not_model_argument(self):
        state = correction_state("tech")
        with patch.object(tools, "_write", side_effect=AssertionError("no writer")):
            result = await tools.edit_resume(state, {"instruction": "把170ms改成1ms"}, tools.ToolContext())
        body = str(result.update["resume_data"])
        self.assertTrue(result.result["correction_applied"])
        self.assertIn("190ms", body)
        self.assertNotIn("170ms", body)
        self.assertNotIn("1ms", body)

    async def test_failed_or_ambiguous_correction_preserves_document_and_facts(self):
        for variant in ("missing_body", "ambiguous", "save_failure", "reference"):
            with self.subTest(variant=variant):
                state = correction_state("tech")
                if variant == "missing_body":
                    state["resume_data"]["work_experience"][0]["bullets"] = ["没有该数字的旧稿"]
                if variant == "ambiguous":
                    state["collected_info"]["work_experience"].append({
                        **deepcopy(state["collected_info"]["work_experience"][0]), "item_id": "other", "company": "另一家公司"})
                if variant == "reference":
                    state["messages"][0].additional_kwargs["career_material_type"] = "reference"
                before, ctx = deepcopy(state), tools.ToolContext()
                saver = AsyncMock(side_effect=RuntimeError("storage offline"))
                token = graph._intake_saver.set(saver if variant == "save_failure" else None)
                try:
                    with patch.object(tools, "_write", side_effect=AssertionError("no writer")):
                        result = await tools.edit_resume(state, {"instruction": "更正数字"}, ctx)
                finally:
                    graph._intake_saver.reset(token)
                self.assertNotEqual(result.result["status"], "ok")
                self.assertEqual(result.update, {})
                self.assertFalse(ctx.recorded_sources)
                self.assertFalse(ctx.corrected_sources)
                self.assertEqual(state, before)

    async def test_contacts_asked_once_across_turns_and_export_can_ask_again(self):
        state = {**graph._init_state(), "collected_info": collected()}
        state["collected_info"]["basic_info"] = {"name": "离线候选人"}
        first = await tools.write_draft(state, {}, tools.ToolContext(llm=Writer()))
        self.assertEqual(first.result["contacts_missing"], ["phone", "email"])
        self.assertTrue(first.update["session_constraints"]["contacts_requested"])
        current = {**state, **first.update, "messages": [HumanMessage(content="不知道")]}
        for instruction in ("直接写", "把第二个项目改短", "就这样"):
            current["messages"] = [HumanMessage(content=instruction)]
            result = await (tools.edit_resume(current, {"instruction": instruction}, tools.ToolContext(llm=Writer()))
                            if "改短" in instruction else tools.write_draft(current, {}, tools.ToolContext(llm=Writer())))
            self.assertIn(result.result["status"], {"ok", "unchanged", "partial"})
            self.assertNotIn("contacts_missing", result.result)
            current.update(result.update)
            self.assertTrue(current["session_constraints"]["contacts_requested"])
        current["messages"] = [HumanMessage(content="导出PDF")]
        export = await tools.write_draft(current, {}, tools.ToolContext(llm=Writer()))
        self.assertEqual(export.result["contacts_missing"], ["phone", "email"])
        current["collected_info"]["basic_info"].update(phone=PHONE, email=EMAIL)
        completed = await tools.write_draft(current, {}, tools.ToolContext(llm=Writer()))
        self.assertNotIn("contacts_missing", completed.result)

    async def test_failed_draft_does_not_mark_contacts_requested(self):
        state = {"collected_info": collected()}
        state["collected_info"]["basic_info"] = {}
        with patch.object(tools, "_write", AsyncMock(return_value=tools.ToolOutcome({"status": "error"}))):
            result = await tools.write_draft(state, {}, tools.ToolContext())
        self.assertNotIn("contacts_missing", result.result)
        self.assertFalse(result.update)

    async def test_contact_question_card_respects_draft_and_request_state(self):
        state = state_with_draft()
        state["collected_info"]["basic_info"] = {}
        state["resume_data"]["basic_info"] = {}
        args = {"card": {"subject": "补齐信息", "questions": [
            {"id": "header", "prompt": "请提供手机和邮箱", "kind": "text"},
            {"id": "method", "prompt": "你采用了什么做法？", "kind": "text"}]}}
        first = await tools.ask_user(state, args, tools.ToolContext())
        self.assertTrue(first.update["session_constraints"]["contacts_requested"])
        second = await tools.ask_user({**state, **first.update}, args, tools.ToolContext())
        questions = second.events[-1]["guidance"]["questions"]
        self.assertEqual([q["id"] for q in questions], ["method"])
        before_draft = await tools.ask_user({**state, "resume_data": {}}, args, tools.ToolContext())
        self.assertEqual([q["id"] for q in before_draft.events[-1]["guidance"]["questions"]], ["method"])

    async def test_internal_identifiers_removed_from_result_but_kept_in_state(self):
        state = state_with_draft()
        state["jd_info"] = {"role_profile": {"core_signals": [{"id": "s1", "signal": "核对能力"}]}}
        raw = {"status": "ok", "resume_data": state["resume_data"], "fact_ids": ["f1"],
               "slot_id": "slot-internal", "message": "s1 对应 p1，引用 f1；slot-internal检查fact_ids和item_id",
               "writer_diagnostic": {"slot_lines": {"p1:问题": {"fact_ids": ["f1"]}}}}
        outcome = tools.ToolOutcome(raw, {"resume_data": state["resume_data"]})
        with patch.object(tools, "_write", AsyncMock(return_value=outcome)):
            result = await tools.write_draft(state, {}, tools.ToolContext())
        visible = json.dumps(result.result, ensure_ascii=False)
        for internal in ("s1", "p1", "f1", "slot-internal", "fact_ids", "item_id", "slot_lines"):
            self.assertNotIn(internal, visible)
        self.assertIn("核对能力", visible)
        self.assertIn("资料核对项目", visible)
        self.assertEqual(result.update["resume_data"], state["resume_data"])

    async def test_profile_selection_ids_still_work_and_receipt_names_imported_items(self):
        state = state_with_draft()
        ctx = tools.ToolContext()
        result = {"status": "ok", "items": [{"id": "profile-item", "name": "核对项目", "fact_ids": ["secret-fact"]}]}
        with patch("app.services.profile_tools.execute_profile_tool", AsyncMock(return_value=(result, {}))):
            read = await tools.read_profile(state, {}, ctx)
        self.assertEqual(read.result["items"][0]["id"], "profile-item")
        self.assertNotIn("secret-fact", str(read.result))
        with patch("app.services.profile_tools.execute_profile_tool", AsyncMock(return_value=(
                {"status": "ok", "imported": ["核对项目"], "facts": [{"id": "secret-fact", "text": "核对材料"}]}, {}))):
            adopted = await tools.use_profile_items(state, {"item_ids": ["profile-item"]}, ctx)
        self.assertEqual(adopted.result["message"], "已从档案导入：核对项目。")
        self.assertNotIn("secret-fact", str(adopted.result))
