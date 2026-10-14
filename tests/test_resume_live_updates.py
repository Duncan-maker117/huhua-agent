"""Conversation facts must appear in the workspace as they are collected."""

import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents.resume_graph import (  # noqa: E402
    _apply_explicit_project_removals,
    _extract_info_from_message,
    _init_state,
    _run_decoder_and_build_reply,
    _serialize_to_resume_data,
    build_graph,
    collecting_node,
    evaluating_node,
    export_node,
    jd_input_node,
)
from app.agents.triage_chain import TriageAction, TriageDecision  # noqa: E402
from app.services.canonical_resume import editor_facts  # noqa: E402
from app.services.candidate_material import parse_existing_resume  # noqa: E402
from app.services.resume_facts import active_facts_for_writer, normalize_fact_store  # noqa: E402


SOURCE_RESUME = """林同学｜AI 产品
这是我之前的简历草稿，只保留真实资料；个人职责仍待核对。
教育背景
示例大学 · 计算机科学（本科） · 预计 2027 年 6 月毕业
项目经历
Huhua Agent｜对话式简历原型 · 2026.05
提供对话收集和导出功能，已完成本地演示，用户效果未验证。
CodeWiz｜开源贡献 · 2026.06
完成 Skill 接口实现；个人职责待核对。
"""

RENDER_UNAVAILABLE = {"status": "render_error", "pages": None, "within_page_limit": None,
                      "page_limit": 1, "error_type": "TestRendererUnavailable"}


class ResumeLiveUpdatesTest(unittest.IsolatedAsyncioTestCase):
    def test_short_role_answer_does_not_create_another_generic_experience(self):
        from app.agents.resume_graph import _keep_unextracted_experience
        facts = _init_state()["collected_info"]
        facts["projects"] = [{"name": "已有项目", "description": "本地原型", "role": ""}]
        for answer in ("我独立完成的", "这个是我独立开发的。"):
            with self.subTest(answer=answer):
                result = _keep_unextracted_experience(facts, copy.deepcopy(facts), HumanMessage(content=answer))
                self.assertEqual(result, facts)

    def model(self):
        return SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="请补充你本人做的一个动作。")))

    async def test_first_turn_resume_imports_before_asking_for_jd(self):
        state = {**_init_state(), "messages": [HumanMessage(content=SOURCE_RESUME)]}
        with patch("app.agents.resume_graph.run_triage", side_effect=AssertionError("No triage required")):
            result = await jd_input_node(state, object())
        self.assertEqual(result["stage"], "COLLECTING")
        self.assertEqual(result["resume_data"]["basic_info"]["name"], "林同学")
        self.assertEqual(len(result["resume_data"]["projects"]), 2)
        self.assertEqual(len(result["resume_data"]["education"]), 1)
        self.assertIn("Huhua Agent", result["resume_draft"])

    def test_markdown_resume_sections_are_imported(self):
        markdown = SOURCE_RESUME.replace("教育背景", "## 教育背景").replace("项目经历", "**项目经历**")
        parsed = parse_existing_resume(markdown)
        self.assertEqual(len(parsed["projects"]), 2)
        self.assertEqual(parsed["education"][0]["school"], "示例大学")

    def test_project_removal_requires_an_affirmative_instruction(self):
        facts = {"projects": [{"name": "CodeWiz", "description": "完成 Skill 接口实现"}]}
        for text in ("不要删除 CodeWiz", "是否去掉 CodeWiz？", "要不要 CodeWiz"):
            with self.subTest(text=text):
                self.assertEqual(_apply_explicit_project_removals(facts, text), facts)
        hidden = _apply_explicit_project_removals(facts, "算了不要 CodeWiz 了")["projects"]
        self.assertEqual(len(hidden), 1)
        self.assertTrue(hidden[0]["hidden"])
        self.assertEqual(hidden[0]["description"], "完成 Skill 接口实现")

    async def test_collecting_updates_canonical_before_generate(self):
        model = self.model()
        state = {**_init_state(), "stage": "COLLECTING", "messages": [HumanMessage(content="我在课程项目实现了检索接口。") ]}
        decision = TriageDecision(action=TriageAction.WRAP_EXPERIENCE, reason="事实", experience_snippet=state["messages"][0].content)
        with (
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=model),
            patch("app.agents.resume_graph.run_triage", AsyncMock(return_value=decision)),
            patch("app.agents.resume_graph._extract_info_from_message", AsyncMock(side_effect=lambda text, current, model: current)),
        ):
            result = await collecting_node(state, model)
        self.assertNotIn("stage", result)
        self.assertEqual(result["resume_data"]["projects"][0]["description"], "我在课程项目实现了检索接口。")
        self.assertIn("检索接口", result["resume_draft"])
        self.assertNotIn("请补充", result["resume_draft"])

    async def test_basic_and_education_facts_alone_update_live_resume(self):
        state = {**_init_state(), "stage": "COLLECTING", "messages": [HumanMessage(content="我叫林同学，在示例大学读本科。") ]}
        updated = copy.deepcopy(state["collected_info"])
        updated["basic_info"]["name"] = "林同学"
        updated["education"] = [{"school": "示例大学", "degree": "本科"}]
        model = self.model()
        with (
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=model),
            patch("app.agents.resume_graph.run_triage", AsyncMock(return_value=TriageDecision(action=TriageAction.ASK_EXPERIENCE, reason="追问项目"))),
            patch("app.agents.resume_graph._extract_info_from_message", AsyncMock(return_value=updated)),
        ):
            result = await collecting_node(state, model)
        self.assertEqual(result["resume_data"]["basic_info"]["name"], "林同学")
        self.assertEqual(result["resume_data"]["education"][0]["degree"], "本科")

    async def test_legacy_history_restores_old_resume_and_keeps_latest_removal(self):
        state = _init_state()
        state.update(stage="EVALUATING", messages=[
            HumanMessage(content=SOURCE_RESUME, id="source"),
            AIMessage(content="建议写成主导千万用户增长。"),
            HumanMessage(content="算了那不要 CodeWiz 了"),
            HumanMessage(content="我做过生活工具，完成 PDF 合并功能。"),
            HumanMessage(content="给我做简历"),
        ])
        state["collected_info"]["projects"] = [{"name": "生活工具", "description": "我做过生活工具，完成 PDF 合并功能。"}]
        state["resume_data"] = _serialize_to_resume_data(state)
        extracted_sources = []

        async def extract(text, current, model):
            extracted_sources.append(text)
            return current

        with (
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=object()),
            patch("app.agents.resume_graph._extract_info_from_message", side_effect=extract),
            patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value=RENDER_UNAVAILABLE),
        ):
            result = await evaluating_node(state, object())
        names = [item["name"] for item in result["resume_data"]["projects"]]
        self.assertIn("Huhua Agent", names)
        self.assertIn("生活工具", names)
        self.assertIn("CodeWiz", names)
        self.assertTrue(next(item for item in result["collected_info"]["projects"] if item["name"] == "CodeWiz")["hidden"])
        self.assertEqual(result["resume_data"]["basic_info"]["name"], "林同学")
        self.assertNotIn("千万", "".join(extracted_sources))
        self.assertNotIn("千万", result["resume_draft"])
        self.assertTrue(result["candidate_history_reconciled"])
        from app.services.fact_coverage import coverage_notice
        notice = coverage_notice(result['resume_meta'].get('fact_coverage') or {})
        self.assertLess(len(result["messages"][0].content.replace(notice, '').strip()), 160)

    async def test_legacy_recovery_excludes_review_reference_and_jd_sources(self):
        state = _init_state()
        sources = [HumanMessage(content=SOURCE_RESUME, additional_kwargs={"career_material_type": kind}) for kind in ("review", "reference", "jd")]
        state.update(stage="EVALUATING", non_candidate_message_ids=["auto-jd"], messages=[
            *sources,
            HumanMessage(content=SOURCE_RESUME, id="auto-jd"),
            AIMessage(content=SOURCE_RESUME),
            HumanMessage(content="？"),
        ])
        with patch("app.agents.resume_graph._extract_info_from_message") as extract:
            result = await evaluating_node(state, object())
        extract.assert_not_called()
        self.assertEqual(result["resume_data"]["projects"], [])
        self.assertNotIn("林同学", str(result))

    async def test_manual_editor_snapshot_blocks_history_resurrection(self):
        state = _init_state()
        saved = {"basic_info": {"name": "手动修改的姓名", "objective": ""}, "projects": [], "sections": [], "skills": [], "verification_notes": []}
        state.update(stage="EVALUATING", resume_data=saved, collected_info=editor_facts(saved), messages=[HumanMessage(content=SOURCE_RESUME), HumanMessage(content="上面")])
        with patch("app.agents.resume_graph._extract_info_from_message") as extract:
            result = await evaluating_node(state, object())
        extract.assert_not_called()
        data = result.get("resume_data", saved)
        self.assertEqual(data["projects"], [])
        self.assertEqual(data["basic_info"]["name"], "手动修改的姓名")
        self.assertEqual(data["sections"], [])

    async def test_export_stage_accepts_incremental_fact_and_preserves_sections(self):
        state = _init_state()
        saved = {"basic_info": {"name": "林同学"}, "projects": [{"name": "Huhua Agent", "description": "完成本地演示。"}], "skills": ["Python"], "skill_groups": {"工具": ["Python"]}, "sections": [{"id": "projects", "kind": "projects", "title": "代表作品", "content": ""}, {"id": "links", "kind": "custom", "title": "链接", "content": "https://example.test"}]}
        state.update(stage="EXPORT", resume_data=saved, collected_info=editor_facts(saved), messages=[HumanMessage(content="补充：我在 Huhua Agent 编写了 12 条接口测试。")])
        with (
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=object()),
            patch("app.agents.resume_graph._extract_info_from_message", AsyncMock(side_effect=lambda text, current, model: current)),
            patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value=RENDER_UNAVAILABLE),
        ):
            result = await export_node(state, object())
        self.assertEqual(result["stage"], "EVALUATING")
        self.assertEqual(result["resume_data"]["sections"], saved["sections"])
        self.assertEqual(result["resume_data"]["skill_groups"], saved["skill_groups"])
        self.assertEqual(len(result["resume_data"]["projects"]), 1)
        self.assertIn("12 条接口测试", result["resume_draft"])
        self.assertNotIn("12 条接口测试", result["messages"][0].content)

    async def test_short_pointers_do_not_repeat_no_new_facts_error(self):
        for phrase in ("上面", "？", "?"):
            with self.subTest(phrase=phrase):
                state = {**_init_state(), "stage": "EVALUATING", "messages": [HumanMessage(content=phrase)]}
                with (patch("app.agents.resume_graph._extract_info_from_message") as extract,
                      patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value=RENDER_UNAVAILABLE)):
                    result = await evaluating_node(state, object())
                extract.assert_not_called()
                self.assertIn("请补充教育或项目/工作经历", result["messages"][0].content)
                self.assertNotIn("新事实", result["messages"][0].content)

    async def test_jd_analysis_is_kept_in_card_data_and_chat_is_short(self):
        decoded = [{"keyword": "用户研究", "real_meaning": "访谈与分析"}]
        output = {"jd_info": {"job_title": "AI 产品实习生", "required_skills": ["Python"]}, "decoded_items": decoded, "summary": "这是一段详细岗位分析。"}
        with (
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=object()),
            patch("app.agents.resume_graph.run_decoder_chain", AsyncMock(return_value=output)),
        ):
            info, reply = await _run_decoder_and_build_reply("JD 原文", object())
        self.assertEqual(info["decoded_items"], decoded)
        self.assertEqual(info["summary"], output["summary"])
        self.assertIn("右侧「读岗位」", reply)
        self.assertNotIn("访谈与分析", reply)

    async def test_followup_live_updates_persist_in_graph_without_build_request(self):
        model = self.model()
        graph = build_graph(model)
        config = {"configurable": {"thread_id": "live-facts"}}

        async def extract(text, current, model):
            updated = copy.deepcopy(current)
            updated["projects"][0]["description"] += "\n我在 Huhua Agent 编写了 8 条测试。"
            return updated

        with (
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=model),
            patch("app.agents.resume_graph.run_triage", AsyncMock(return_value=TriageDecision(action=TriageAction.WRAP_EXPERIENCE, reason="补充"))),
            patch("app.agents.resume_graph._extract_info_from_message", side_effect=extract),
        ):
            initial = await graph.ainvoke({**_init_state(), "messages": [HumanMessage(content=SOURCE_RESUME)]}, config)
            result = await graph.ainvoke({"messages": [HumanMessage(content="我在 Huhua Agent 编写了 8 条测试。") ]}, config)
        self.assertEqual(initial["stage"], "COLLECTING")
        self.assertEqual(result["stage"], "COLLECTING")
        self.assertEqual(len(result["resume_data"]["projects"]), 2)
        self.assertIn("8 条测试", result["resume_data"]["projects"][0]["description"])
        self.assertIn("8 条测试", result["resume_draft"])

    def paper_facts(self):
        current = _init_state()["collected_info"]
        current["projects"] = [
            {"name": "纸页工具", "description": "使用 AI 编程工具实现页面拆分，目前为本地 Demo，未上线。"},
            {"name": "访谈整理器", "description": "整理访谈笔记，交付 4 个页面。"},
        ]
        current["skills"] = ["Python"]
        return current

    async def test_real_smoke_actions_reach_canonical_when_extraction_fails(self):
        source = "补充纸页工具：我给一位同学演示了页面拆分，收集到 2 条反馈，并修改了文件选择提示。没有上线，没有用户增长数据。"
        state = {**_init_state(), "stage": "COLLECTING", "collected_info": self.paper_facts(), "messages": [HumanMessage(content=source)]}
        state["resume_data"] = _serialize_to_resume_data(state)
        observed = []

        async def public(messages):
            context = json.loads(messages[1].content.split("\n", 1)[1])
            observed.append(context)
            return AIMessage(content="已更新右侧经历和简历草稿。")

        model = SimpleNamespace(ainvoke=AsyncMock(side_effect=public))
        with (
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=model),
            patch("app.agents.resume_graph.run_triage", AsyncMock(return_value=TriageDecision(action=TriageAction.WRAP_EXPERIENCE, reason="补充", experience_snippet="我给一位同学演示了页面拆分，收集到 2 条反馈，并修改了文件选择提示。"))),
            patch("app.agents.resume_graph._extract_info_from_message", AsyncMock(side_effect=lambda text, current, model: current)),
        ):
            result = await collecting_node(state, model)
        self.assertNotEqual(result["resume_data"], state["resume_data"])
        self.assertEqual(len(result["resume_data"]["projects"]), 2)
        description = result["resume_data"]["projects"][0]["description"]
        for fact in ("2 条反馈", "修改了文件选择提示"):
            self.assertIn(fact, description)
        for limit in ("没有上线", "没有用户增长数据"):  # 限制只留在事实母版，不印进展示文本
            self.assertNotIn(limit, description)
            self.assertIn(limit, json.dumps(result["collected_info"]["projects"], ensure_ascii=False))
        self.assertEqual(observed[0]["candidate_facts"]["projects"][0]["facts"][-1]["source_quote"], source)
        self.assertTrue(observed[0]["resume_updated"])

    async def test_sparse_patch_keeps_other_projects_and_previous_actions(self):
        current = normalize_fact_store(self.paper_facts())
        item_id = current["projects"][0]["item_id"]
        old_other = copy.deepcopy(current["projects"][1])
        message = "补充纸页工具：收集到 2 条反馈。"
        output = {"items": [{"section": "projects", "item_id": item_id, "name": "纸页工具", "facts": [
            {"kind": "result_metric", "text": "收集到 2 条反馈", "source_quote": "收集到 2 条反馈"}]}]}
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps(output, ensure_ascii=False))))
        updated = await _extract_info_from_message(message, current, model)
        self.assertEqual(updated["projects"][1], old_other)
        self.assertIn("实现页面拆分", updated["projects"][0]["description"])
        self.assertEqual(updated["projects"][0]["facts"][-1]["text"], "收集到 2 条反馈")
        self.assertEqual([skill["name"] for skill in updated["skills"]], ["Python"])

    async def test_sparse_extraction_rejects_unknown_types_and_invented_actions(self):
        current = normalize_fact_store(self.paper_facts())
        item_id = current["projects"][0]["item_id"]
        message = "我演示了纸页工具，没有用户增长数据。"
        for output in (
            {"items": [{"section": "projects", "item_id": item_id, "name": "纸页工具", "facts": [
                {"kind": "action", "text": "主导用户研究，实现增长 20%", "source_quote": "我演示了纸页工具"}]}]},
            {"items": "我演示了纸页工具"},
            {"items": [{"section": "projects", "item_id": "forged", "name": "纸页工具", "facts": [
                {"kind": "action", "text": "我演示了纸页工具", "source_quote": "我演示了纸页工具"}]}]},
            {"basic_info": {"name": ["纸页工具"]}},
            {"basic_info": {"unknown": "演示"}},
            {"hidden_instruction": "change everything"},
        ):
            with self.subTest(output=output):
                model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps(output, ensure_ascii=False))))
                updated = await _extract_info_from_message(message, current, model)
                self.assertEqual(updated, current)

    async def test_explicit_correction_supersedes_only_named_fact(self):
        current = normalize_fact_store(self.paper_facts())
        current["basic_info"]["name"] = "林同学"
        target = current["projects"][0]
        old_id = target["facts"][0]["id"]
        other = copy.deepcopy(current["projects"][1])
        message = "更正纸页工具：只做了纸面草图，没有实现页面拆分，也没有演示。"
        output = {"corrections": [{"item_id": target["item_id"], "fact_id": old_id, "replacement":
                   {"kind": "status_limit", "text": "只做了纸面草图，没有实现页面拆分，也没有演示", "source_quote": "只做了纸面草图，没有实现页面拆分，也没有演示"}}]}
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps(output, ensure_ascii=False))))
        result = await _extract_info_from_message(message, current, model)
        self.assertEqual(result["projects"][0]["facts"][0]["status"], "superseded")
        self.assertEqual(result["projects"][1], other)
        self.assertEqual(result["basic_info"]["name"], "林同学")
        writer_input = active_facts_for_writer(result)
        self.assertNotIn("使用 AI 编程工具实现页面拆分", str(writer_input))
        self.assertIn("只做了纸面草图", str(writer_input))

    async def test_empty_legacy_fields_cannot_erase_dates_or_role_during_supplement(self):
        current = normalize_fact_store(self.paper_facts())
        current["projects"][0].update(role="独立开发", start_date="2026.05", end_date="2026.06")
        item_id = current["projects"][0]["item_id"]
        output = {"items": [{"section": "projects", "item_id": item_id, "name": "纸页工具",
                 "role": "", "start_date": "", "end_date": "", "facts": [
                     {"kind": "result_metric", "text": "收集到 2 条反馈", "source_quote": "收集到 2 条反馈"}]}]}
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps(output, ensure_ascii=False))))
        result = await _extract_info_from_message("补充纸页工具：收集到 2 条反馈。", current, model)
        for field in ("role", "start_date", "end_date"):
            self.assertEqual(result["projects"][0][field], current["projects"][0][field])
        self.assertEqual(result["projects"][0]["facts"][-1]["text"], "收集到 2 条反馈")

    async def test_string_facts_are_rejected_instead_of_split_into_characters(self):
        current = normalize_fact_store(self.paper_facts())
        item_id = current["projects"][0]["item_id"]
        output = {"items": [{"section": "projects", "item_id": item_id, "name": "纸页工具", "facts": "补充测试"}]}
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps(output, ensure_ascii=False))))
        result = await _extract_info_from_message("纸页工具补充测试", current, model)
        self.assertEqual(result, current)

    async def test_negated_and_planned_demonstrations_do_not_create_completed_actions(self):
        for source in (
            "纸页工具：我没有演示页面，也没有收集反馈。",
            "纸页工具：我计划给同学演示页面并收集反馈。",
            "纸页工具：我并未修改文件提示，也未收集反馈。",
        ):
            with self.subTest(source=source):
                state = {**_init_state(), "stage": "COLLECTING", "collected_info": self.paper_facts(), "messages": [HumanMessage(content=source)]}
                state["resume_data"] = _serialize_to_resume_data(state)
                model = self.model()
                with (
                    patch("app.agents.resume_graph._make_non_streaming_llm", return_value=model),
                    patch("app.agents.resume_graph.run_triage", AsyncMock(return_value=TriageDecision(action=TriageAction.WRAP_EXPERIENCE, reason="核实"))),
                    patch("app.agents.resume_graph._extract_info_from_message", AsyncMock(side_effect=lambda text, current, model: current)),
                ):
                    result = await collecting_node(state, model)
                self.assertEqual(result["collected_info"], state["collected_info"])
                self.assertNotIn("resume_data", result)


if __name__ == "__main__":
    unittest.main()
