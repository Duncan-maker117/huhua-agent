"""Replay failures reproduced with fictional candidates and scripted models."""

import asyncio
import copy
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from docx import Document
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents import resume_graph as rg
from app.agents.fact_extractor import apply_fact_patch, extract_facts_patch
from app.agents.profile_archivist import ArchiveBatch, make_archivist
from app.agents.resume_writer import _seed_item
from app.agents.triage_chain import TRIAGE_SYSTEM, TriageAction, TriageDecision
from app.agents.wording_advice import _distinct, _edit_distance_ratio, wording_advice
from app.services.candidate_material import parse_existing_resume
from app.services.profile_service import context_to_collected_info
from app.services.renderer import list_templates, render_resume
from app.services.resume_facts import active_facts_for_writer, new_fact, normalize_fact_store
from app.services.resume_review import resume_to_text
from app.tools.resume_data_docx import resume_data_to_docx


PERSONAL = """姓名林小舟，人在深圳，求职意向是 AI 产品经理实习（Agent 方向）。
电话 13900000000，邮箱 fictional@candidate.test，GitHub 是 example-user，个人主页 example.test。
可实习时间：每周 6 天，6 个月起
教育：示例甲大学，计算机科学与技术本科，2023.09–2027.06，获得过校级三等奖学金。"""
BASIC = {"name": "林小舟", "phone": "13900000000", "email": "fictional@candidate.test", "location": "深圳"}


class ExtractModel:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=json.dumps(self.response, ensure_ascii=False))


def intake_state(text=PERSONAL, kind=None):
    state = rg._init_state()
    state.update(stage="COLLECTING", candidate_history_reconciled=True,
                 jd_text="岗位职责：需求分析。", jd_info={"job_title": "AI 产品实习", "required_skills": ["需求分析"]},
                 non_candidate_message_ids=["prior-jd"],
                 messages=[AIMessage(content="请补充基本信息和教育。"),
                           HumanMessage(content=text, id="personal-turn",
                                        additional_kwargs={"career_material_type": kind} if kind else {})])
    return state


class DecodeFallbackTests(unittest.IsolatedAsyncioTestCase):
    def assert_personal_retained(self, result):
        basic = result["collected_info"]["basic_info"]
        for key, value in BASIC.items():
            self.assertEqual(basic[key], value)
        self.assertEqual(basic["availability"], "每周 6 天，6 个月起")
        self.assertEqual([link["url"] for link in basic["links"]], ["example-user", "example.test"])
        education = result["collected_info"]["education"][0]
        self.assertEqual(education["school"], "示例甲大学")
        self.assertEqual(education["major"], "计算机科学与技术")
        self.assertEqual(education["degree"], "本科")
        self.assertEqual((education["start_date"], education["end_date"]), ("2023.09", "2027.06"))
        self.assertIn("校级三等奖学金", education["highlights"])
        self.assertNotIn("personal-turn", result.get("non_candidate_message_ids", []))
        self.assertNotIn("这段材料还没有解析出", result["messages"][0].content)
        self.assertEqual(result["resume_data"]["basic_info"]["email"], BASIC["email"])

    async def test_collecting_blocks_personal_decode_reuses_completed_extraction_and_postprocessing(self):
        from app.agents.turn_actions import absorb_education, bind_role_followup
        state = intake_state()
        before = copy.deepcopy(state)
        completed = asyncio.Event()
        model = ExtractModel({"basic_info": BASIC})  # Education omitted deliberately.
        original = rg._extract_info_from_message

        async def extract(*args):
            result = await original(*args)
            completed.set()
            return result

        async def triage(**kwargs):
            await asyncio.wait_for(completed.wait(), 1)
            return TriageDecision(action=TriageAction.DECODE_JD, reason="fake misclassification")

        self.assertIsNone(parse_existing_resume(PERSONAL))
        with (
            patch.object(rg, "_make_non_streaming_llm", return_value=model),
            patch.object(rg, "run_triage", AsyncMock(side_effect=triage)),
            patch.object(rg, "_extract_info_from_message", AsyncMock(side_effect=extract)) as extraction,
            patch.object(rg, "_run_decoder_and_build_reply", AsyncMock(return_value=({}, "这段材料还没有解析出岗位。"))) as decode,
            patch.object(rg, "stream_public_reply", AsyncMock(return_value=AIMessage(content="已整理本人资料。"))),
            patch("app.agents.interviewer.first_draft_ready", return_value=False),
            patch("app.agents.turn_actions.absorb_education", wraps=absorb_education) as education,
            patch("app.agents.turn_actions.bind_role_followup", wraps=bind_role_followup) as role,
        ):
            result = await rg.collecting_node(state, model)
        extraction.assert_awaited_once()
        decode.assert_not_awaited()
        education.assert_called_once()
        role.assert_called_once()
        self.assertEqual(role.call_args.args[-1], "personal-turn")
        self.assert_personal_retained(result)
        self.assertNotIn("jd_info", result)
        self.assertNotIn("jd_text", result)
        self.assertEqual(state, before)

    async def test_jd_input_failed_decode_collects_once_without_second_triage(self):
        state = {**intake_state(), "stage": "JD_INPUT"}
        model = ExtractModel({"basic_info": BASIC})
        with (
            patch.object(rg, "_make_non_streaming_llm", return_value=model),
            patch.object(rg, "run_triage", AsyncMock(return_value=TriageDecision(action=TriageAction.DECODE_JD, reason="fake"))) as triage,
            patch.object(rg, "_run_decoder_and_build_reply", AsyncMock(return_value=({}, "这段材料还没有解析出岗位。"))),
            patch.object(rg, "stream_public_reply", AsyncMock(return_value=AIMessage(content="已整理本人资料。"))),
            patch("app.agents.interviewer.first_draft_ready", return_value=False),
        ):
            result = await rg.jd_input_node(state, model)
        triage.assert_awaited_once()
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(result["stage"], "COLLECTING")
        self.assertNotIn("requested_task", result)
        self.assert_personal_retained(result)

    async def test_explicit_external_material_stays_excluded_when_decode_fails(self):
        for node in (rg.jd_input_node, rg.collecting_node):
            for kind in ("jd", "reference", "review"):
                with self.subTest(node=node.__name__, kind=kind):
                    state = intake_state(kind=kind)
                    with (
                        patch.object(rg, "_make_non_streaming_llm", return_value=object()),
                        patch.object(rg, "run_triage", AsyncMock(return_value=TriageDecision(action=TriageAction.DECODE_JD, reason="fake"))),
                        patch.object(rg, "_extract_info_from_message", AsyncMock(side_effect=AssertionError("external extraction"))) as extract,
                        patch.object(rg, "_run_decoder_and_build_reply", AsyncMock(return_value=({}, "补充招聘方要求。"))),
                    ):
                        result = await node(state, object())
                    extract.assert_not_awaited()
                    self.assertIn("personal-turn", result["non_candidate_message_ids"])
                    self.assertFalse(any(((result.get("collected_info") or {}).get("basic_info") or {}).values()))

    async def test_successful_decode_discards_candidate_result_and_excludes_source(self):
        completed = asyncio.Event()

        async def extract(*args):
            completed.set()
            return {"basic_info": BASIC}

        async def triage(**kwargs):
            await asyncio.wait_for(completed.wait(), 1)
            return TriageDecision(action=TriageAction.DECODE_JD, reason="fake JD")

        with (
            patch.object(rg, "_make_non_streaming_llm", return_value=object()),
            patch.object(rg, "run_triage", AsyncMock(side_effect=triage)),
            patch.object(rg, "_extract_info_from_message", AsyncMock(side_effect=extract)),
            patch.object(rg, "_run_decoder_and_build_reply", AsyncMock(return_value=({"job_title": "需求分析实习"}, "岗位已解析。"))) as decoder,
        ):
            current = intake_state("招聘产品实习生，负责需求分析与跨团队合作。")
            current.update(jd_info={}, jd_text='')  # Without a current JD, triage may recognize a prose JD.
            result = await rg.collecting_node(current, object())
        decoder.assert_awaited_once()
        self.assertFalse(any(result["collected_info"]["basic_info"].values()))
        self.assertEqual(result["jd_info"]["job_title"], "需求分析实习")
        self.assertIn("personal-turn", result["non_candidate_message_ids"])

    async def test_fake_graph_saves_candidate_info_and_keeps_message_as_archive_source(self):
        model = ExtractModel({"basic_info": BASIC})
        graph = rg.build_graph(model)
        thread = "fictional-decode-fallback-checkpoint"
        config = {"configurable": {"thread_id": thread}}
        seed = intake_state()
        seed["messages"] = [HumanMessage(content=seed["jd_text"], id="prior-jd",
                                        additional_kwargs={"career_material_type": "jd"})]
        await graph.aupdate_state(config, seed)
        with (
            patch.object(rg, "get_graph", return_value=graph),
            patch.object(rg, "_make_non_streaming_llm", return_value=model),
            patch.object(rg, "run_triage", AsyncMock(return_value=TriageDecision(action=TriageAction.DECODE_JD, reason="fake"))),
            patch.object(rg, "_run_decoder_and_build_reply", AsyncMock(return_value=({}, "这段材料还没有解析出岗位。"))),
            patch.object(rg, "stream_public_reply", AsyncMock(return_value=AIMessage(content="已整理本人资料。"))),
            patch("app.agents.interviewer.first_draft_ready", return_value=False),
            patch("app.services.session_store.save_candidate_intake"),
            patch("app.services.session_store.save_resume_session") as save,
        ):
            chunks = [chunk async for chunk in rg.stream_agent([{"content": PERSONAL}], thread, model)]
        self.assertIn("已整理本人资料", "".join(chunks))
        save.assert_called_once()
        self.assertEqual(save.call_args.kwargs["collected_info"]["basic_info"]["name"], BASIC["name"])
        self.assertEqual(save.call_args.kwargs["resume_data"]["education"][0]["school"], "示例甲大学")
        checkpoint = await graph.aget_state(config)
        latest = next(m for m in reversed(checkpoint.values["messages"]) if isinstance(m, HumanMessage))
        self.assertNotIn(latest.id, checkpoint.values["non_candidate_message_ids"])
        self.assertIn("prior-jd", checkpoint.values["non_candidate_message_ids"])

    def test_triage_contract_explicitly_separates_personal_data_and_objective_from_jd(self):
        self.assertIn("含姓名/电话/邮箱/教育等个人资料、只是顺带提到求职意向的消息不是 JD", TRIAGE_SYSTEM)


def word_text(data):
    return "\n".join(p.text for p in Document(io.BytesIO(resume_data_to_docx(data))).paragraphs)


class RoleAndAwardTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_extractor_cannot_label_project_status_as_role(self):
        for status in ("原型", "未上线", "已上线", "Demo", "原型 / 未上线"):
            for kind, field in (("role", "role"), ("role", None), ("context", "role")):
                with self.subTest(status=status, kind=kind, field=field):
                    raw = {"kind": kind, "text": status, "source_quote": status}
                    if field:
                        raw["field"] = field
                    model = ExtractModel({"items": [{"section": "projects", "name": "星舟", "facts": [raw]}]})
                    patch_data = await extract_facts_patch("星舟的项目状态：" + status, {}, model)
                    fact = patch_data["items"][0]["facts"][0]
                    self.assertEqual(fact["kind"], "status_limit")
                    self.assertNotEqual(fact.get("field"), "role")
                    self.assertEqual(fact["source_quote"], status)
                    canonical = rg._serialize_to_resume_data({"collected_info": apply_fact_patch({}, patch_data)})
                    self.assertFalse(canonical["projects"][0]["role"])

    def test_document_project_metadata_retains_phase_without_setting_role(self):
        for status in ("原型", "未上线", "已上线"):
            text = "姓名：林小舟\n项目经历：\n星舟 | 2025.01\n个人项目 | " + status + "\n- 设计确认流程。"
            data = parse_existing_resume(text)
            self.assertEqual(len(data["projects"]), 1)
            self.assertFalse(data["projects"][0]["role"])
            self.assertIn(status, data["projects"][0]["description"])

    def test_profile_status_mislabeled_role_becomes_description_and_keeps_source(self):
        context = {"facts": [{"id": "profile-f1", "revision": 1, "category": "project",
                              "subject": "星舟", "field": "role", "value": "原型"}]}
        bindings = []
        data = context_to_collected_info(context, projection_bindings=bindings)
        self.assertFalse(data["projects"][0].get("role"))
        self.assertIn("原型", data["projects"][0]["description"])
        self.assertEqual(bindings[0]["field"], "description")
        self.assertEqual(data["projects"][0]["facts"][0]["profile_refs"][0]["fact_id"], "profile-f1")

    async def test_fake_archivist_cannot_write_status_into_project_role(self):
        class ArchivistModel:
            def with_structured_output(self, schema):
                return self

            async def ainvoke(self, messages):
                return ArchiveBatch.model_validate({"proposals": [{"category": "project", "subject": "星舟",
                    "field": "role", "value": "原型", "evidence_quote": "原型"}]})

        batch = await make_archivist(ArchivistModel())({"source_kind": "self", "human_text": "星舟是原型"}, {})
        self.assertEqual(batch.proposals[0].field, "status")
        self.assertEqual(batch.proposals[0].value, "原型")
        self.assertEqual(batch.proposals[0].evidence_quote, "原型")

    def test_existing_role_is_kept_when_profile_also_contains_a_status(self):
        current = {"projects": [{"name": "星舟", "role": "原型设计负责人"}]}
        context = {"facts": [{"id": "profile-f1", "revision": 1, "category": "project",
                              "subject": "星舟", "field": "role", "value": "未上线"}]}
        data = context_to_collected_info(context, current)
        self.assertEqual(data["projects"][0]["role"], "原型设计负责人")
        self.assertIn("未上线", data["projects"][0]["description"])

    def test_legacy_and_new_patch_status_roles_are_preserved_as_status_facts(self):
        legacy = {"projects": [{"name": "星舟", "role": "原型", "description": "设计确认流程"}]}
        normalized = normalize_fact_store(legacy)
        self.assertFalse(normalized["projects"][0].get("role"))
        fact = next(f for f in normalized["projects"][0]["facts"] if f["text"] == "原型")
        self.assertEqual(fact["kind"], "status_limit")
        self.assertNotIn("field", fact)
        self.assertEqual(legacy["projects"][0]["role"], "原型")
        source = active_facts_for_writer(normalized)["projects"][0]
        row = _seed_item("projects", source, {"name": "星舟", "role": "已上线"})
        self.assertFalse(row["role"])

    def test_pure_legacy_status_role_is_hidden_in_all_templates_and_word(self):
        for status in ("原型", "未上线", "已上线", "Demo / 原型"):
            data = {"projects": [{"name": "星舟", "role": status, "description": "完成需求梳理"}]}
            before = copy.deepcopy(data)
            for template in list_templates():
                html = render_resume(template["id"], data, interactive=True)
                self.assertNotIn('data-field-path="/projects/0/role"', html, template["id"])
            self.assertNotIn(status, word_text(data))
            self.assertNotIn(status, resume_to_text(data))
            self.assertEqual(data, before)

    def test_real_roles_containing_status_words_remain_visible(self):
        for role in ("原型设计负责人", "独立开发者", "负责原型设计与上线"):
            data = {"projects": [{"name": "星舟", "role": role}]}
            self.assertIn(role, render_resume("t001-jianyue", data))
            self.assertIn(role, word_text(data))

    async def test_actual_role_is_kept_by_fake_extractor_and_canonical_mapper(self):
        role = "原型设计负责人"
        model = ExtractModel({"items": [{"section": "projects", "name": "星舟", "facts": [
            {"kind": "role", "field": "role", "text": role, "source_quote": role}]}]})
        collected = apply_fact_patch({}, await extract_facts_patch("星舟本人角色：" + role, {}, model))
        data = rg._serialize_to_resume_data({"collected_info": collected})
        self.assertEqual(data["projects"][0]["role"], role)

    async def test_award_name_punctuation_is_removed_through_extraction_and_canonical(self):
        text = "竞赛荣誉：示例 AI 训练营结营。"
        patch_data = await extract_facts_patch(text, {}, ExtractModel({}))
        collected = apply_fact_patch({}, patch_data)
        data = rg._serialize_to_resume_data({"collected_info": collected})
        self.assertEqual(data["awards"][0]["name"], "示例 AI 训练营结营")
        self.assertIn("示例 AI 训练营结营。", collected["awards"][0]["raw_notes"])
        self.assertEqual(word_text(data).count("示例 AI 训练营结营"), 1)

    async def test_model_supplied_award_name_with_punctuation_is_cleaned(self):
        text = "获得了示例训练营结营。"
        model = ExtractModel({"items": [{"section": "awards", "name": "示例训练营结营。", "facts": [
            {"kind": "context", "field": "name", "text": "示例训练营结营。", "source_quote": "示例训练营结营。"}]}]})
        collected = apply_fact_patch({}, await extract_facts_patch(text, {}, model))
        self.assertEqual(collected["awards"][0]["name"], "示例训练营结营")
        self.assertEqual(collected["awards"][0]["facts"][0]["source_quote"], "示例训练营结营。")

    def test_award_header_echoes_hide_without_shifting_preview_bullet_paths(self):
        data = {"awards": [{"name": "，星舟挑战赛。", "level": "三等奖", "bullets": [
            "星舟挑战赛 ｜ 三等奖。", "三等奖。", "完成三轮答辩。"]}]}
        before = copy.deepcopy(data)
        for template in list_templates():
            html = render_resume(template["id"], data, interactive=True)
            self.assertEqual(html.count("星舟挑战赛"), 1)
            self.assertEqual(html.count("三等奖"), 1)
            self.assertIn('data-field-path="/awards/0/bullets/2"', html)
            self.assertNotIn('data-field-path="/awards/0/bullets/0"', html)
        for text in (word_text(data), resume_to_text(data)):
            self.assertEqual(text.count("星舟挑战赛"), 1)
            self.assertEqual(text.count("三等奖"), 1)
            self.assertIn("完成三轮答辩。", text)
        self.assertEqual(data, before)

    def test_award_supplement_with_additional_information_is_kept(self):
        data = {"awards": [{"name": "星舟挑战赛", "level": "三等奖", "bullets": [
            "星舟挑战赛三等奖，完成现场答辩。"]}]}
        for text in (render_resume("t001-jianyue", data), word_text(data), resume_to_text(data)):
            self.assertIn("完成现场答辩", text)


ADVICE_SOURCE = "我负责需求取舍，设计失败确认流程并交付状态图"
LONG_OPTION = "负责需求取舍，设计失败确认流程并交付状态图"
SHORT_OPTION = "设计失败确认流程"


def option(text, style="role", refs=None):
    return {"text": text, "style": style, "fact_ids": ["f1"] if refs is None else refs}


def advice_state():
    return {"collected_info": {"projects": [{"item_id": "p1", "name": "星舟", "facts": [
        {**new_fact(ADVICE_SOURCE), "id": "f1"}]}]}}


class AdviceModel:
    def __init__(self, responses, *, reject=False):
        self.responses = iter(responses)
        self.reject = reject
        self.calls = []

    def with_structured_output(self, schema):
        async def invoke(messages):
            self.calls.append((schema.__name__, messages))
            if schema.__name__ == "WordingAdvice":
                response = next(self.responses)
                if isinstance(response, Exception):
                    raise response
                return {"options": response}
            if schema.__name__ == "SemanticBatch":
                pairs = json.loads(messages[-1].content)
                return {"decisions": [{"id": row["id"], "subject_ok": True, "actions_supported": True,
                    "objects_supported": True, "results_supported": True, "limits_kept": True,
                    "unsupported_spans": [], "verdict": "fail" if self.reject else "pass"} for row in pairs]}
            raise AssertionError("unexpected model schema")
        return SimpleNamespace(ainvoke=invoke)


class AdviceDiversityTests(unittest.IsolatedAsyncioTestCase):
    async def test_near_identical_options_are_deduplicated_and_refilled_in_another_style(self):
        model = AdviceModel([[option(LONG_OPTION), option(LONG_OPTION.replace("负责", "规划")),
                              option(LONG_OPTION + "。", "action")], [option(SHORT_OPTION, "concise")]])
        state = advice_state()
        before = copy.deepcopy(state)
        reply = await wording_advice(state, "星舟怎么写更好", model)
        self.assertIn("1.「" + LONG_OPTION + "」", reply)
        self.assertIn("2.「" + SHORT_OPTION + "」", reply)
        self.assertNotIn("规划需求取舍", reply)
        self.assertNotIn("3.「", reply)
        calls = [messages for schema, messages in model.calls if schema == "WordingAdvice"]
        self.assertEqual(len(calls), 2)
        payload = json.loads(calls[1][-1].content)
        self.assertEqual(payload["requested_styles"], ["concise", "action"])
        self.assertEqual([row["text"] for row in payload["existing_options"]], [LONG_OPTION])
        self.assertEqual(state, before)

    async def test_two_distinct_grounded_options_do_not_incur_a_refill(self):
        model = AdviceModel([[option(LONG_OPTION), option(SHORT_OPTION, "concise")]])
        reply = await wording_advice(advice_state(), "怎么写更好", model)
        self.assertIn("2.「", reply)
        self.assertEqual(sum(schema == "WordingAdvice" for schema, _ in model.calls), 1)

    async def test_refill_still_similar_returns_one_option_and_explains(self):
        model = AdviceModel([[option(LONG_OPTION), option(LONG_OPTION.replace("负责", "规划"))],
                             [option(LONG_OPTION + "。", "action")]])
        reply = await wording_advice(advice_state(), "怎么写更好", model)
        self.assertNotIn("2.「", reply)
        self.assertIn("暂时只给这一种", reply)
        self.assertEqual(sum(schema == "WordingAdvice" for schema, _ in model.calls), 2)

    async def test_refill_cannot_use_same_style_or_unsupported_facts(self):
        for refill in ([option(SHORT_OPTION, "role")], [option("提升转化100%", "action")],
                       [option(SHORT_OPTION, "concise", ["unknown"])], [option("使用Kubernetes上线", "action")]):
            with self.subTest(refill=refill):
                model = AdviceModel([[option(LONG_OPTION), option(LONG_OPTION + "。")], refill])
                reply = await wording_advice(advice_state(), "怎么写更好", model)
                self.assertIn("1.「" + LONG_OPTION + "」", reply)
                self.assertNotIn("2.「", reply)
                self.assertNotIn("100%", reply)
                self.assertNotIn("Kubernetes", reply)

    async def test_refill_is_semantically_checked_and_failure_keeps_single_grounded_literal(self):
        for responses, reject in (([[option(LONG_OPTION)], [option(SHORT_OPTION, "concise")]], True),
                                  ([RuntimeError("fake failure"), RuntimeError("fake failure")], False)):
            model = AdviceModel(responses, reject=reject)
            reply = await wording_advice(advice_state(), "怎么写更好", model)
            self.assertIn("1.「" + ADVICE_SOURCE + "」", reply)
            self.assertNotIn("2.「", reply)
            self.assertIn("暂时只给这一种", reply)

    def test_similarity_normalizes_punctuation_space_case_and_full_width_characters(self):
        self.assertEqual(_edit_distance_ratio("Ａｇｅｎｔ，需求。", "agent 需求"), 0)
        self.assertLess(_edit_distance_ratio(LONG_OPTION, LONG_OPTION.replace("负责", "规划")), .2)
        self.assertEqual(len(_distinct([option("abcdefghij"), option("abXXefghij")])), 2)
        self.assertEqual(len(_distinct([option("abcdefghij"), option("abcXefghij")])), 1)


if __name__ == "__main__":
    unittest.main()
