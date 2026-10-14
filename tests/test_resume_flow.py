import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.resume_writer import run_resume_writer  # noqa: E402
from app.agents.resume_graph import (  # noqa: E402
    _empty_collected_info,
    _extract_info_from_message,
    _harvest_projects_from_messages,
    _init_state,
    _serialize_to_resume_data,
    collecting_node,
    evaluating_node,
    export_node,
    stream_agent,
)
from app.agents.triage_chain import TriageAction, TriageDecision  # noqa: E402


class _StructuredLLM:
    def __init__(self, output):
        self.output = list(output) if isinstance(output, list) else [output]

    def with_structured_output(self, _schema):
        return self

    async def ainvoke(self, _messages):
        return self.output.pop(0)


RENDER_UNAVAILABLE = {"status": "render_error", "pages": None, "within_page_limit": None,
                      "page_limit": 1, "error_type": "TestRendererUnavailable"}


class ResumeFlowTest(unittest.IsolatedAsyncioTestCase):
    async def _wrap_with_extraction(self, message, snippet, extracted, current=None):
        state = _init_state()
        state["stage"] = "COLLECTING"
        state["messages"] = [HumanMessage(content=message)]
        if current is not None:
            state["collected_info"] = copy.deepcopy(current)
        extraction_response = (
            extracted
            if isinstance(extracted, Exception)
            else AIMessage(content=json.dumps(extracted, ensure_ascii=False))
        )
        llm = SimpleNamespace(
            ainvoke=AsyncMock(
                side_effect=[extraction_response, AIMessage(content="经历整理建议")]
            )
        )
        decision = TriageDecision(
            action=TriageAction.WRAP_EXPERIENCE,
            reason="user described an experience",
            experience_snippet=snippet,
        )
        with (
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=llm),
            patch(
                "app.agents.resume_graph.run_triage", AsyncMock(return_value=decision)
            ),
        ):
            return await collecting_node(state, llm)

    def _evaluating_state(self, text: str):
        from app.services.resume_facts import normalize_fact_store
        state = _init_state()
        state["stage"] = "EVALUATING"
        state["collected_info"]["projects"] = [
            {"name": "校招调研", "description": "参与用户调研"}
        ]
        state["collected_info"] = normalize_fact_store(state["collected_info"])
        state["resume_data"] = _serialize_to_resume_data(state)
        state["messages"] = [HumanMessage(content=text)]
        return state

    async def test_revision_rebuilds_resume_and_review_in_one_turn(self):
        state = self._evaluating_state(
            "不满意，请补充我整理过 12 份访谈笔记，还会 Python"
        )
        updated = copy.deepcopy(state["collected_info"])
        from app.services.resume_facts import new_fact
        updated["projects"][0]["facts"].append(new_fact("整理过 12 份访谈笔记"))
        updated["skills"] = ["Python"]

        extractor = AsyncMock(return_value=updated)
        with (
            patch("app.agents.resume_graph._extract_info_from_message", extractor),
            patch(
                "app.agents.resume_graph._make_non_streaming_llm", return_value=object()
            ),
            patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value=RENDER_UNAVAILABLE),
        ):
            from test_resume_writer import source_echo_model
            result = await evaluating_node(state, source_echo_model(updated))

        self.assertEqual(result["stage"], "EVALUATING")
        self.assertEqual(result["collected_info"]["projects"][0]["facts"], updated["projects"][0]["facts"])
        self.assertEqual(result["resume_data"]["skills"], ["Python"])
        self.assertIn("12 份访谈笔记", result["resume_draft"])
        self.assertIn("待核对草稿", result["messages"][0].content)
        self.assertIn("右侧待核对草稿", result["messages"][0].content)
        self.assertNotIn("12 份访谈笔记", result["messages"][0].content)
        self.assertEqual(result["page_check"]["status"], "render_error")
        extractor.assert_awaited_once()

    async def test_vague_optimization_asks_for_facts_without_rebuilding(self):
        state = self._evaluating_state("继续优化")
        with (patch("app.agents.resume_graph._extract_info_from_message") as extractor,
              patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value=RENDER_UNAVAILABLE)):
            result = await evaluating_node(state, object())
        self.assertEqual(result["stage"], "EVALUATING")
        self.assertNotIn("12 份访谈笔记", result["resume_draft"])
        self.assertNotIn("投递前核对", result["messages"][0].content)
        extractor.assert_not_called()

    async def test_standalone_export_does_not_extract(self):
        state = self._evaluating_state("可以导出 Word")
        with patch("app.agents.resume_graph._extract_info_from_message") as extractor:
            result = await evaluating_node(state, object())
        self.assertEqual(result["stage"], "EXPORT")
        extractor.assert_not_called()

    async def test_exported_conversation_accepts_later_corrections(self):
        state = self._evaluating_state("补充我整理了 12 份访谈笔记")
        state["stage"] = "EXPORT"
        state["jd_text"] = "产品岗位要求访谈分析"
        updated = copy.deepcopy(state["collected_info"])
        from app.services.resume_facts import new_fact
        updated["projects"][0]["facts"].append(new_fact("整理了 12 份访谈笔记"))
        with (
            patch("app.agents.resume_graph._extract_info_from_message", AsyncMock(return_value=updated)),
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=object()),
            patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value=RENDER_UNAVAILABLE),
        ):
            from test_resume_writer import source_echo_model
            result = await export_node(state, source_echo_model(updated))
        self.assertEqual(result["stage"], "EVALUATING")
        self.assertIn("12 份访谈笔记", result["resume_draft"])
        self.assertEqual(state["jd_text"], "产品岗位要求访谈分析")

    async def test_repeated_export_keeps_the_existing_draft(self):
        state = self._evaluating_state("导出 Word")
        state["stage"] = "EXPORT"
        with patch("app.agents.resume_graph.evaluating_node", AsyncMock()) as evaluate:
            result = await export_node(state, object())
        evaluate.assert_not_awaited()
        self.assertIn("右侧「写简历」", result["messages"][0].content)

    async def test_edit_before_export_is_not_treated_as_confirmation(self):
        state = self._evaluating_state("项目描述有问题，请先补充整理访谈笔记，再导出")
        updated = copy.deepcopy(state["collected_info"])
        from app.services.resume_facts import new_fact
        updated["projects"][0]["facts"].append(new_fact("整理访谈笔记"))
        extractor = AsyncMock(return_value=updated)
        with (
            patch("app.agents.resume_graph._extract_info_from_message", extractor),
            patch(
                "app.agents.resume_graph._make_non_streaming_llm", return_value=object()
            ),
            patch("app.agents.tailor_pipeline.measure_rendered_pages", return_value=RENDER_UNAVAILABLE),
        ):
            from test_resume_writer import source_echo_model
            result = await evaluating_node(state, source_echo_model(updated))
        self.assertEqual(result["stage"], "EVALUATING")
        self.assertIn("整理访谈笔记", result["resume_draft"])
        extractor.assert_awaited_once()

    async def test_writer_rejects_semantic_upgrade_and_invented_skills(self):
        from app.services.resume_facts import new_fact
        fact = {**new_fact("参与调研，整理访谈笔记"), "id": "f1"}
        source = {"projects": [{"item_id": "p1", "name": "A", "facts": [fact]}],
                  "skills": [{"name": "Excel", "status": "active", "source_quote": "Excel"}]}
        proposed = {"match_plan": {"requirements": [],
                                    "experience_plan": [{"item_id": "p1", "treatment": "keep"}]},
                    "writer": {"items": [{"item_id": "p1", "section": "projects", "title": {},
                                          "bullets": [{"text": "主导调研并推动上线", "fact_ids": ["f1"]}]}],
                               "skill_groups": {"技术栈": ["Python"]}}}
        result = await run_resume_writer(source, {}, _StructuredLLM([proposed]))
        data = result["resume_data"]
        self.assertNotIn("主导", str(data))
        self.assertNotIn("上线", str(data))
        self.assertNotIn("Python", str(data))
        self.assertIn("参与调研", data["projects"][0]["polished_bullets"][0])
        self.assertEqual(result["resume_meta"]["bullets"]["p1"][0]["fact_ids"], ["f1"])

    async def test_writer_rejects_invented_number_but_keeps_supported_action(self):
        from app.services.resume_facts import new_fact
        fact = {**new_fact("参与调研，整理访谈笔记"), "id": "f1"}
        source = {"projects": [{"item_id": "p1", "name": "A", "facts": [fact]}]}
        proposed = {"match_plan": {"requirements": [],
                                    "experience_plan": [{"item_id": "p1", "treatment": "keep"}]},
                    "writer": {"items": [{"item_id": "p1", "section": "projects", "title": {},
                                          "bullets": [{"text": "完成 80 次调研", "fact_ids": ["f1"]}]}]}}
        result = await run_resume_writer(source, {}, _StructuredLLM([proposed]))
        self.assertNotIn("80", str(result["resume_data"]))
        self.assertIn("参与调研", result["resume_data"]["projects"][0]["polished_bullets"][0])

    async def test_extractor_rejects_unsupported_ownership_upgrade(self):
        current = _empty_collected_info()
        message = "我在 A 项目参与调研"
        llm = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps({
            "items": [{"section": "projects", "name": "A", "facts": [
                {"kind": "role", "text": "主导调研", "source_quote": "参与调研"}]}]}
        ))))
        rejected = await _extract_info_from_message(message, current, llm)
        self.assertEqual(rejected["projects"], [])

        llm.ainvoke.return_value = AIMessage(content=json.dumps({
            "items": [{"section": "projects", "name": "A", "facts": [
                {"kind": "action", "text": "参与调研", "source_quote": "参与调研"}]}]}
        ))
        accepted = await _extract_info_from_message(message, current, llm)
        self.assertEqual([f["text"] for f in accepted["projects"][0]["facts"]], ["参与调研"])

    async def test_extractor_does_not_turn_a_negated_action_into_a_claim(self):
        current = _empty_collected_info()
        message = "我在 A 项目没有负责上线，只参与调研"
        llm = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps({
            "items": [{"section": "projects", "name": "A", "facts": [
                {"kind": "role", "text": "负责上线", "source_quote": "负责上线"}]}]}
        ))))
        rejected = await _extract_info_from_message(message, current, llm)
        self.assertEqual(rejected["projects"], [])

        llm.ainvoke.return_value = AIMessage(content=json.dumps({
            "items": [{"section": "projects", "name": "A", "facts": [
                {"kind": "action", "text": "参与调研", "source_quote": "参与调研"}]}]}
        ))
        accepted = await _extract_info_from_message(message, current, llm)
        self.assertEqual([f["text"] for f in accepted["projects"][0]["facts"]], ["参与调研"])

    async def test_fallback_uses_user_words_not_ai_bullet(self):
        messages = [
            HumanMessage(content="我在 A 项目参与调研"),
            AIMessage(content="🧷 **试着这么写**：主导调研并推动上线"),
        ]
        fallback = _harvest_projects_from_messages(messages)
        self.assertEqual(fallback[0]["description"], "我在 A 项目参与调研")
        self.assertNotIn("主导", fallback[0]["description"])
        self.assertEqual(_harvest_projects_from_messages(messages[1:]), [])

    async def test_wrap_saves_raw_user_experience_only(self):
        state = _init_state()
        state["stage"] = "COLLECTING"
        state["messages"] = [HumanMessage(content="我在 A 项目参与调研")]
        llm = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value=AIMessage(content="🧷 **试着这么写**：主导调研并推动上线")
            )
        )
        decision = TriageDecision(
            action=TriageAction.WRAP_EXPERIENCE,
            reason="user described an experience",
            experience_snippet="我在 A 项目参与调研",
        )
        with (
            patch("app.agents.resume_graph._make_non_streaming_llm", return_value=llm),
            patch(
                "app.agents.resume_graph._extract_info_from_message",
                AsyncMock(return_value=state["collected_info"]),
            ),
            patch(
                "app.agents.resume_graph.run_triage", AsyncMock(return_value=decision)
            ),
        ):
            result = await collecting_node(state, llm)
        self.assertEqual(
            result["collected_info"]["projects"][0]["description"],
            "我在 A 项目参与调研",
        )

    async def test_wrap_does_not_duplicate_an_extracted_chinese_project(self):
        message = "我在测试知识库实现文档检索接口，并编写10条接口测试。"
        patch = {"items": [{"section": "projects", "name": "测试知识库", "facts": [
            {"kind": "action", "text": "实现文档检索接口", "source_quote": "实现文档检索接口"},
            {"kind": "deliverable", "text": "编写10条接口测试", "source_quote": "编写10条接口测试"}]}]}
        result = await self._wrap_with_extraction(message, message, patch)
        projects = result["collected_info"]["projects"]
        self.assertEqual(len(projects), 1)
        self.assertEqual([f["text"] for f in projects[0]["facts"]], ["实现文档检索接口", "编写10条接口测试"])
        self.assertNotIn("技能：", str(projects[0]["facts"]))

    async def test_wrap_does_not_copy_extracted_work_or_internship_into_projects(self):
        snippet = "我在测试公司用 Python 实现文档检索接口，并编写了10条接口测试"
        for section in ("work_experience", "internship"):
            with self.subTest(section=section):
                patch = {"items": [{"section": section, "name": "测试公司", "facts": [
                    {"kind": "action", "text": "用 Python 实现文档检索接口", "source_quote": "用 Python 实现文档检索接口"}]}]}
                result = await self._wrap_with_extraction(snippet, snippet, patch)
                self.assertEqual(result["collected_info"]["projects"], [])
                self.assertEqual(result["collected_info"][section][0]["facts"][0]["source_quote"], "用 Python 实现文档检索接口")

    async def test_wrap_keeps_a_new_project_when_extraction_only_found_another(self):
        message = "我在 A 项目整理用户访谈。FastAPI，我实现了文档检索接口"
        snippet = "FastAPI，我实现了文档检索接口"
        patch = {"items": [{"section": "projects", "name": "A", "facts": [
            {"kind": "action", "text": "整理用户访谈", "source_quote": "整理用户访谈"}]}]}
        result = await self._wrap_with_extraction(message, snippet, patch)
        projects = result["collected_info"]["projects"]
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["facts"][0]["text"], "整理用户访谈")
        self.assertIn(snippet, result["collected_info"]["raw_notes"])

    async def test_wrap_keeps_raw_fallback_after_extraction_failure_or_rejection(self):
        current = _empty_collected_info()
        current["projects"] = [{"name": "旧项目", "description": "整理用户访谈"}]
        snippet = "我在新项目参与调研，并整理了12份访谈笔记"
        invented = {"items": [{"section": "projects", "name": "新项目", "facts": [
            {"kind": "role", "text": "主导调研推动上线", "source_quote": "参与调研"}]}]}
        for extracted in (RuntimeError("offline extraction failure"), invented):
            with self.subTest(extracted=type(extracted).__name__):
                result = await self._wrap_with_extraction(snippet, snippet, extracted, current=current)
                projects = result["collected_info"]["projects"]
                self.assertEqual(projects[0]["description"], current["projects"][0]["description"])
                self.assertNotIn('对话中描述的经历', str(projects))
                self.assertNotIn('主导', str(projects))
                self.assertTrue(snippet in str(result['collected_info']))

    async def test_wrap_uses_existing_chinese_name_for_new_raw_facts(self):
        current = _empty_collected_info()
        current["projects"] = [{"name": "测试知识库", "description": "实现文档检索接口"}]
        snippet = "测试知识库，并编写了10条接口测试"
        result = await self._wrap_with_extraction(snippet, snippet, RuntimeError("offline extraction failure"), current=current)
        projects = result["collected_info"]["projects"]
        self.assertEqual(len(projects), 1)
        self.assertIn("实现文档检索接口", projects[0]["description"])
        self.assertEqual(projects[0]["facts"][-1]["source_quote"], snippet)

    async def test_wrap_does_not_append_raw_text_to_an_updated_project(self):
        from app.services.resume_facts import normalize_fact_store
        current = _empty_collected_info()
        current["projects"] = [{"name": "测试知识库", "description": "实现文档检索接口"}]
        current = normalize_fact_store(current)
        snippet = "测试知识库，并编写了10条接口测试"
        patch = {"items": [{"section": "projects", "item_id": current["projects"][0]["item_id"], "name": "测试知识库", "facts": [
            {"kind": "deliverable", "text": "编写了10条接口测试", "source_quote": "编写了10条接口测试"}]}]}
        result = await self._wrap_with_extraction(snippet, snippet, patch, current)
        projects = result["collected_info"]["projects"]
        self.assertEqual(len(projects), 1)
        self.assertEqual([f["source_quote"] for f in projects[0]["facts"]].count("编写了10条接口测试"), 1)
        self.assertEqual(projects[0]["description"], "实现文档检索接口")

    async def test_stream_emits_only_public_node_messages(self):
        class FakeGraph:
            async def astream(self, *_args, **_kwargs):
                yield {"triage": {"messages": [AIMessage(content="INTERNAL_TRIAGE")]}}
                yield {
                    "collecting": {
                        "messages": [AIMessage(content="请讲讲你的项目经历")]
                    }
                }
                yield {"decoder": {"messages": [AIMessage(content="INTERNAL_DECODER")]}}

            async def aget_state(self, _config):
                return SimpleNamespace(
                    values={
                        "messages": [AIMessage(content="请讲讲你的项目经历")],
                        "resume_data": {"basic_info": {"name": "张三"}},
                        "resume_draft": "",
                        "stage": "COLLECTING",
                    }
                )

        with (
            patch("app.agents.resume_graph.get_graph", return_value=FakeGraph()),
            patch("app.services.session_store.save_resume_session") as save,
        ):
            chunks = [
                chunk
                async for chunk in stream_agent([{"content": "你好"}], "s1", object())
            ]
        self.assertEqual(chunks, ["请讲讲你的项目经历"])
        save.assert_called_once()

    async def test_stream_error_hides_internal_exception(self):
        class FailingGraph:
            async def astream(self, *_args, **_kwargs):
                raise RuntimeError("private model diagnostics")
                yield {}  # pragma: no cover

        with patch("app.agents.resume_graph.get_graph", return_value=FailingGraph()):
            with self.assertRaisesRegex(RuntimeError, "生成失败") as error:
                _ = [chunk async for chunk in stream_agent([{"content": "你好"}], "s1", object())]
        self.assertNotIn("private model diagnostics", str(error.exception))


if __name__ == "__main__":
    unittest.main()
