"""The existing-resume path must create an editable draft without invented facts."""

import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.resume_graph import (  # noqa: E402
    _candidate_source_allowed,
    _init_state,
    _merge_imported_candidate,
    _serialize_to_resume_data,
    build_graph,
    building_node,
    collecting_node,
    evaluating_node,
)
from app.services.candidate_material import parse_existing_resume  # noqa: E402
from app.services.session_store import resume_data_has_content  # noqa: E402
from test_candidate_material_documents import PDF_TEXT, MARKDOWN_TEXT, documents  # noqa: E402


OLD_RESUME = """这是我以前的简历工作初稿。项目机制不等于本人贡献，不要编造职责或数据。

徐同学｜AI 产品（Agent 应用方向）

姓名、学校和毕业时间来自旧简历，当前信息待确认。正式版删除本说明。
联系方式：candidate@example.com，139xxxx1603

教育背景
哈尔滨商业大学 · 计算机科学与技术（本科） · 预计 2027 年 6 月毕业

项目经历
Huhua Agent｜对话式简历工作台 · [2025.9] · [个人项目 产品原型]
原型提供对话收集、事实核对和导出流程。
本地 API 已可演示；真实模型全流程和用户效果仍需验证。本人具体设计取舍待补。

CodeWiz｜代码 Agent 开源贡献· 2026.5 [训练营项目 负责agent设计]
以 GitHub 账号提交两项已合入贡献，涉及 Skill 抽象和代码索引。
两项 PR 内容存在重叠，不重复计算工作量；本人验证与方案选择待补。

mtagent｜路线优先的旅行规划原型 · [2026.5-2026.7] [黑客松项目]
产品支持局部加站、换站和删站。
本地演示首屏采用 Stub／确定性路径，交通时间为估算；本人设计取舍待补。

校园活动（待核实）
某训练营结营证书
程序设计竞赛三等奖

产品与技术能力（待本人核实）
候选范围：Python、FastAPI、LangGraph、Cursor。定稿只保留本人可解释的技能。

到馆后的定稿顺序（不进入投递版）
计划补齐个人职责，导出 PDF。不要让 AI 编造贡献。
"""

RENDER_UNAVAILABLE = {"status": "render_error", "pages": None, "within_page_limit": None,
                      "page_limit": 1, "error_type": "TestRendererUnavailable"}


class ResumeImportFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_two_attachments_reach_current_draft_with_all_sections(self):
        source = documents(("resume.pdf", PDF_TEXT), ("draft.md", MARKDOWN_TEXT))
        state = {**_init_state(), "stage": "COLLECTING", "messages": [HumanMessage(content=source)]}
        with patch("app.agents.resume_graph.run_triage", AsyncMock(side_effect=AssertionError("structured import must not call triage"))):
            result = await collecting_node(state, object())
        data = result["resume_data"]
        self.assertEqual([p["name"] for p in data["projects"]], ["Mirror Skill", "RouteFlow", "ResumeLab", "CodeLab"])
        self.assertEqual(data["basic_info"]["name"], "林同学")
        self.assertEqual(len(data["skills"]), 5)
        self.assertEqual(len(data["certificates"]), 2)
        self.assertEqual(data["projects"][0]["role"], "独立开发者")
        self.assertEqual(data["projects"][1]["end_date"], "2026.7")
        self.assertIn("draft.md：2026.7", "\n".join(data["verification_notes"]))
        self.assertNotIn("候选技能与奖项暂未写入", result["messages"][-1].content)
        self.assertEqual(len(result["collected_info"]["imported_documents"]), 2)

    def test_reimport_keeps_sections_idempotent_and_conflicts_visible(self):
        imported = parse_existing_resume(documents(("resume.pdf", PDF_TEXT), ("draft.md", MARKDOWN_TEXT)))
        once = _merge_imported_candidate(_init_state()["collected_info"], imported)
        twice = _merge_imported_candidate(once, imported)
        for field in ("projects", "education", "skills", "certificates", "field_conflicts", "imported_documents", "verification_notes"):
            self.assertEqual(twice[field], once[field], field)
        self.assertTrue(twice["field_conflicts"])

    async def test_import_question_does_not_inherit_author_project_claims(self):
        for name, description in (
            ("CodeWiz", "我参与课程代码阅读，目前只完成本地笔记整理，没有提交贡献。"),
            ("星河工具", "我用 Python 完成本地文件分类，尚未上线，也没有用户效果数据。"),
            ("校园读书活动", "我在读书活动中整理报名名单和场地安排，参与团队的一部分工作。"),
        ):
            with self.subTest(project=name):
                source = (
                    "这是我以前的简历，请按已有内容整理，缺失信息保留待核对。\n"
                    "林同学｜运营助理\n教育背景\n示例大学 · 文学（本科） · 2026 年毕业\n"
                    f"项目经历\n{name}｜课程实践 · 2026.5\n{description}\n"
                )
                state = {**_init_state(), "stage": "COLLECTING",
                         "messages": [HumanMessage(content=source)]}
                with (
                    patch("app.agents.resume_graph._make_non_streaming_llm", return_value=object()),
                    patch("app.agents.resume_graph.run_triage", AsyncMock(side_effect=AssertionError("import should not call model"))),
                ):
                    result = await collecting_node(state, object())
                reply = result["messages"][-1].content
                self.assertIn("1 段项目", reply)
                self.assertIn("生成", reply)
                for unsupported in ("两项", "已合入", "PR", "主导", "已上线"):
                    self.assertNotIn(unsupported, reply)
                self.assertIn(description, result["resume_data"]["projects"][0]["description"])

    def test_negative_fabrication_instruction_allows_real_resume(self):
        self.assertTrue(_candidate_source_allowed(HumanMessage(content=OLD_RESUME)))
        for kind in ("review", "jd", "reference"):
            with self.subTest(kind=kind):
                self.assertFalse(
                    _candidate_source_allowed(
                        HumanMessage(
                            content=OLD_RESUME,
                            additional_kwargs={"career_material_type": kind},
                        )
                    )
                )
        for material in (
            "示例简历：\n" + OLD_RESUME,
            "帮我编造一个项目经历，然后写进简历。",
            "岗位职责：负责 Agent 产品设计、工具调用。",
        ):
            self.assertFalse(_candidate_source_allowed(HumanMessage(content=material)))

    def test_parser_preserves_three_named_projects_and_uncertain_status(self):
        imported = parse_existing_resume(OLD_RESUME)
        self.assertIsNotNone(imported)
        self.assertEqual(
            [p["name"] for p in imported["projects"]],
            ["Huhua Agent", "CodeWiz", "mtagent"],
        )
        self.assertEqual(imported["projects"][0]["start_date"], "2025.9")
        self.assertEqual(imported["projects"][1]["start_date"], "2026.5")
        self.assertEqual(imported["projects"][2]["end_date"], "2026.7")
        self.assertEqual(imported["education"][0]["degree"], "本科")
        self.assertIn("原型", imported["projects"][0]["description"])
        self.assertIn("Stub", imported["projects"][2]["description"])
        self.assertIn("估算", imported["projects"][2]["description"])
        self.assertIn("已合入", imported["projects"][1]["description"])
        self.assertNotIn("负责agent设计", imported["projects"][1]["description"])
        self.assertEqual(imported["basic_info"]["name"], "徐同学")
        self.assertNotIn("email", imported["basic_info"])
        whole = "\n".join(p["description"] for p in imported["projects"])
        for forbidden in (
            "候选范围",
            "结营证书",
            "计划补齐",
            "定稿只保留",
            "本人设计取舍待补",
        ):
            self.assertNotIn(forbidden, whole)
        self.assertTrue(imported["verification_notes"])

    def test_parser_copies_source_objective_exactly(self):
        imported = parse_existing_resume(OLD_RESUME)
        self.assertEqual(
            imported["basic_info"]["objective"], "AI 产品（Agent 应用方向）"
        )

    def test_reimport_does_not_duplicate_projects_or_turn_document_into_one_project(
        self,
    ):
        imported = parse_existing_resume(OLD_RESUME)
        state = _init_state()
        state["messages"] = [HumanMessage(content=OLD_RESUME)]
        merged = _merge_imported_candidate(state["collected_info"], imported)
        merged_again = _merge_imported_candidate(merged, imported)
        self.assertEqual(len(merged_again["projects"]), 3)
        self.assertEqual(
            len(merged_again["verification_notes"]), len(merged["verification_notes"])
        )
        data = _serialize_to_resume_data({**state, "collected_info": merged_again})
        self.assertTrue(resume_data_has_content(data))
        self.assertEqual(len(data["projects"]), 3)
        self.assertFalse(data["skills"])
        self.assertFalse(data["certificates"])

    def test_deleted_editor_sections_do_not_resurrect_old_chat_experience(self):
        state = _init_state()
        state["messages"] = [HumanMessage(content="我在旧项目负责接口开发。")]
        state["resume_data"] = {
            "sections": [],
            "projects": [],
            "verification_notes": [],
            "basic_info": {},
        }
        rebuilt = _serialize_to_resume_data(state)
        self.assertEqual(rebuilt["projects"], [])
        self.assertEqual(rebuilt["sections"], [])
        self.assertEqual(rebuilt["verification_notes"], [])

    async def test_import_then_explicit_generate_reaches_preview_data(self):
        llm = SimpleNamespace()
        graph = build_graph(llm)
        config = {"configurable": {"thread_id": "import-then-generate"}}
        with (
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=llm),
            patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value=RENDER_UNAVAILABLE),
            patch(
                "app.agents.resume_graph.run_triage",
                AsyncMock(side_effect=AssertionError("triage should be bypassed")),
            ),
        ):
            imported = await graph.ainvoke(
                {
                    **_init_state(),
                    "stage": "COLLECTING",
                    "messages": [HumanMessage(content=OLD_RESUME)],
                },
                config,
            )
            self.assertEqual(imported["stage"], "COLLECTING")
            self.assertEqual(len(imported["collected_info"]["projects"]), 3)
            self.assertLess(len(imported["messages"][-1].content), 350)
            self.assertTrue(
                resume_data_has_content(_serialize_to_resume_data(imported))
            )

            generated = await graph.ainvoke(
                {
                    "messages": [
                        HumanMessage(content="按已有资料开始生成待核对简历草稿")
                    ]
                },
                config,
            )
        self.assertEqual(generated["stage"], "EVALUATING")
        self.assertEqual(len(generated["resume_data"]["projects"]), 3)
        self.assertTrue(resume_data_has_content(generated["resume_data"]))
        self.assertIn("Huhua Agent", generated["resume_draft"])
        self.assertIn("mtagent", generated["resume_draft"])
        self.assertTrue(generated["resume_data"]["verification_notes"])

    async def test_building_marks_public_draft_as_unverified(self):
        data = {
            "basic_info": {"name": "徐同学", "objective": "AI 产品（Agent 应用方向）"},
            "projects": [{"name": "Huhua Agent", "description": "对话式简历原型。"}],
            "verification_notes": [
                "姓名待核对。",
                "个人贡献待核对。",
                "项目时间待核对。",
                "联系方式待核对。",
            ],
        }
        with patch("app.agents.resume_graph._write_resume_update", AsyncMock(return_value={
            "resume_data": data, "resume_meta": {}, "resume_versions": [],
            "session_constraints": {"page_limit": 1}, "match_plan": {},
            "page_check": {"status": "not_rendered", "pages": None},
            "guard_fallbacks": [], "changed": True, "change_summary": [],
        })):
            result = await building_node(_init_state(), object())
        public_text = result["messages"][0].content
        self.assertTrue(public_text.startswith("已按已有事实更新右侧待核对草稿"))
        self.assertIn("4 项信息待核对", public_text)
        self.assertNotIn("- 个人贡献待核对。", public_text)
        self.assertNotIn("联系方式待核对。", public_text)
        self.assertNotIn("# 徐同学", public_text)
        self.assertTrue(result["resume_draft"].startswith("# 徐同学"))
        self.assertNotIn("个人贡献待核对。", result["resume_draft"])

    async def test_export_confirmation_provides_template_link_in_same_turn(self):
        saved = {
            "basic_info": {"name": "徐同学"},
            "projects": [{"name": "Huhua Agent", "description": "对话式简历原型。"}],
            "verification_notes": ["个人贡献待核对。"],
        }
        draft = "# 徐同学\nHuhua Agent"
        graph = build_graph(object())
        result = await graph.ainvoke(
            {
                **_init_state(),
                "stage": "EVALUATING",
                "resume_data": copy.deepcopy(saved),
                "resume_draft": draft,
                "messages": [HumanMessage(content="导出")],
            },
            {"configurable": {"thread_id": "export-in-same-turn"}},
        )
        self.assertEqual(result["stage"], "EXPORT")
        self.assertIn("[模板页](/resume)", result["messages"][-1].content)
        self.assertEqual(result["resume_data"], saved)
        self.assertEqual(result["resume_draft"], draft)

    async def test_saved_editor_metadata_survives_later_fact_revision(self):
        imported = parse_existing_resume(OLD_RESUME)
        collected = _merge_imported_candidate(_init_state()["collected_info"], imported)
        collected["skills"] = ["Python"]
        collected[
            "verification_notes"
        ] = []  # User cleared the imported notes in editor.
        collected["projects"][0]["description"] = "用户编辑后的原型说明。"
        state = _init_state()
        state.update(stage="EVALUATING", collected_info=collected)
        saved = _serialize_to_resume_data(state)
        saved["basic_info"]["photo"] = "data:image/png;base64,AAAA"
        saved["skill_groups"] = {"技术栈": ["Python"]}
        saved["experience_section_title"] = "代表项目"
        saved["sections"] = [
            {"id": "projects", "kind": "projects", "title": "代表项目", "content": ""},
            {
                "id": "portfolio",
                "kind": "custom",
                "title": "作品链接",
                "content": "https://example.test",
            },
        ]
        saved["verification_notes"] = []
        state["resume_data"] = saved
        state["messages"] = [
            HumanMessage(content="补充：我给 Huhua Agent 做了三次本地验收。")
        ]
        updated = copy.deepcopy(collected)
        from app.services.resume_facts import new_fact
        updated["projects"][0]["facts"].append(new_fact("我给 Huhua Agent 做了三次本地验收。"))
        with (
            patch(
                "app.agents.resume_graph._extract_info_from_message",
                AsyncMock(return_value=updated),
            ),
            patch(
                "app.agents.resume_graph._make_non_streaming_llm", return_value=object()
            ),
            patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value=RENDER_UNAVAILABLE),
        ):
            from test_resume_writer import source_echo_model
            result = await evaluating_node(state, source_echo_model(updated))
        new_data = result["resume_data"]
        self.assertEqual(new_data["sections"], saved["sections"])
        self.assertEqual(new_data["basic_info"]["photo"], saved["basic_info"]["photo"])
        self.assertEqual(new_data["skill_groups"], saved["skill_groups"])
        self.assertEqual(new_data["experience_section_title"], "代表项目")
        self.assertEqual(new_data["verification_notes"], [])
        self.assertIn("三次本地验收", new_data["projects"][0]["description"])
        self.assertEqual(len(new_data["projects"]), 3)


if __name__ == "__main__":
    unittest.main()
