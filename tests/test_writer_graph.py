"""Graph-level PR4 flow with local writer/page doubles and real version handling."""

import asyncio
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.resume_graph import (  # noqa: E402
    _write_resume_update, _writer_reply, building_node, evaluating_node, collecting_node, route_by_stage,
)


def collected():
    def fact(identifier, text):
        return {"id": identifier, "text": text, "source_quote": text,
                "kind": "action", "status": "active", "source": "chat"}

    return {"basic_info": {"name": "Candidate", "objective": ""},
            "projects": [
                {"item_id": "p1", "name": "项目甲", "description": "原材料甲",
                 "facts": [fact("f1", "整理用户反馈并分类")]},
                {"item_id": "p2", "name": "项目乙", "description": "原材料乙",
                 "facts": [fact("f2", "核对重复记录")]},
            ],
            "work_experience": [], "internship": [], "education": [], "skills": []}


class WriterGraphTest(unittest.TestCase):
    def test_failed_edit_receipt_does_not_claim_raw_fallback_or_compression(self):
        reply = _writer_reply({
            'resume_data': {'projects': [{'name': '旧项目', 'polished_bullets': ['上版正文']}]},
            'changed': False,
            'writer_diagnostic': {'status': 'model_fallback', 'fallback_action': 'preserved_existing_draft'},
            'page_check': {'status': 'rendered', 'pages': 2, 'page_limit': 1, 'within_page_limit': False},
        })
        self.assertIn('保留上一版仍有效的正文', reply)
        self.assertIn('尚未完成压缩', reply)
        self.assertIn('实际为 2 页', reply)
        self.assertNotIn('事实原文', reply)
        self.assertNotIn('压缩后仍超页', reply)

    def test_visible_collecting_draft_edit_routes_to_writer_without_triage(self):
        for stage in ('COLLECTING', 'JD_INPUT', 'EVALUATING'):
            with self.subTest(stage=stage):
                state = {'stage': stage, 'messages': [HumanMessage(content='项目甲按 JD 改写，不补新经历')],
                         'resume_data': {'projects': [{'item_id': 'p1', 'name': '项目甲',
                                                       'polished_bullets': ['整理用户反馈并分类']}]},
                         'collected_info': collected()}
                self.assertEqual(route_by_stage(state), 'evaluating')
                result = {'stage': 'EVALUATING', 'resume_data': state['resume_data'],
                          'messages': [HumanMessage(content='writer result')]}
                with patch('app.agents.resume_graph.evaluating_node', AsyncMock(return_value=result)) as writer, \
                        patch('app.agents.resume_graph.run_triage', AsyncMock(side_effect=AssertionError('edit reached triage'))):
                    actual = asyncio.run(collecting_node(state, object()))
                self.assertEqual(actual, result)
                self.assertEqual(writer.await_count, 1)

    def test_edit_shortcut_requires_visible_body_and_preserves_explicit_tasks(self):
        state = {'stage': 'COLLECTING', 'messages': [HumanMessage(content='修改项目甲')],
                 'resume_data': {'projects': [{'item_id': 'p1', 'name': '项目甲'}]}}
        self.assertEqual(route_by_stage(state), 'collecting')
        state['resume_data']['projects'][0].update(polished_bullets=['正文'], hidden=True)
        self.assertEqual(route_by_stage(state), 'collecting')
        state['resume_data']['projects'][0]['hidden'] = False
        state['requested_task'] = 'research_job'
        self.assertEqual(route_by_stage(state), 'skill_task')
        state['requested_task'] = 'auto'
        state['messages'] = [HumanMessage(content='岗位职责：优化接口与实现数据处理。')]
        self.assertEqual(route_by_stage(state), 'collecting')
        state['messages'] = [HumanMessage(content='项目甲：我并未修改文件提示，也未收集反馈。')]
        self.assertEqual(route_by_stage(state), 'collecting')

    def test_graph_passes_distinct_writer_and_structured_models_to_pipeline(self):
        class FakeChatInput:
            pass

        writer = object()
        structured = object()
        pipeline = AsyncMock(return_value={"resume_data": {}, "resume_meta": {}})
        state = {"collected_info": collected(), "messages": [HumanMessage(content="定制简历")],
                 "resume_data": {}, "resume_strategy": {}}
        with patch("app.agents.resume_graph.ChatOpenAI", FakeChatInput), \
                patch("app.agents.resume_graph._make_writer_llm", return_value=writer), \
                patch("app.agents.resume_graph._make_non_streaming_llm", return_value=structured), \
                patch("app.agents.tailor_pipeline.run_tailor_pipeline", pipeline):
            asyncio.run(_write_resume_update(state, FakeChatInput()))
        self.assertIs(pipeline.await_args.args[2], writer)
        self.assertIs(pipeline.await_args.kwargs["structured_llm"], structured)
        self.assertEqual(pipeline.await_args.kwargs["instruction"], "定制简历")

    def test_jd_first_draft_targeted_edit_then_undo_keeps_fact_master(self):
        facts = collected()
        initial = {"messages": [HumanMessage(content="生成面向产品实习生的简历")],
                   "stage": "BUILDING", "collected_info": deepcopy(facts),
                   "jd_info": {"job_title": "产品实习生", "role_profile": {
                       "role_family": "pm", "seniority": "intern", "requirements": []}},
                   "resume_data": {}, "resume_meta": {}, "resume_versions": [],
                   "session_constraints": {"page_limit": 1, "language": "zh-CN",
                                           "template_id": "t001-jianyue"}}
        calls = []

        async def fake_writer(collected_info, role_profile, llm, **kwargs):
            calls.append({"scope": kwargs["scope"], "targets": list(kwargs["targets"]),
                          "instruction": kwargs["instruction"], "target_role": role_profile.get("target_role")})
            data = deepcopy(kwargs["current_data"])
            first = next(item for item in data["projects"] if item["item_id"] == "p1")
            second = next(item for item in data["projects"] if item["item_id"] == "p2")
            if kwargs["scope"] == "whole":
                first["polished_bullets"] = ["首稿：整理用户反馈并分类"]
                second["polished_bullets"] = ["首稿：核对重复记录"]
            elif kwargs["scope"] == "item":
                first["polished_bullets"] = ["整理用户反馈并分类"]
            return {"resume_data": data, "resume_meta": deepcopy(kwargs["resume_meta"]),
                    "match_plan": {"experience_plan": []}, "omitted": [],
                    "guard_fallbacks": [], "change_summary": ["调整项目表述"],
                    "changed_items": [{"section": "projects", "item_id": "p1"}]}

        def one_page(data, constraints):
            return {"status": "rendered", "pages": 1, "page_limit": constraints["page_limit"],
                    "within_page_limit": True}

        async def recover(state, llm):
            return deepcopy(state["collected_info"])

        with patch("app.agents.tailor_pipeline.run_resume_writer", side_effect=fake_writer), \
                patch("app.agents.tailor_pipeline.measure_rendered_pages", side_effect=one_page), \
                patch("app.agents.resume_graph._recover_candidate_history", side_effect=recover), \
                patch("app.agents.resume_graph.parse_existing_resume", return_value=None):
            first = asyncio.run(building_node(initial, object()))
            self.assertEqual(first["stage"], "EVALUATING")
            self.assertTrue(first["changed"])
            self.assertEqual(first["resume_data"]["projects"][0]["polished_bullets"],
                             ["首稿：整理用户反馈并分类"])
            self.assertEqual(first["page_check"]["pages"], 1)
            self.assertEqual(first["session_constraints"]["page_limit"], 1)
            self.assertEqual(first["resume_meta"]["match_plan"], first["match_plan"])
            self.assertEqual(calls[0]["target_role"], "产品实习生")
            first_facts = deepcopy(first["collected_info"])

            edit_state = {**initial, **first, "messages": [HumanMessage(content="项目甲再精简一点")]}
            edited = asyncio.run(evaluating_node(edit_state, object()))
            self.assertEqual(calls[1]["scope"], "item")
            self.assertEqual(calls[1]["targets"], ["p1"])
            self.assertEqual(edited["resume_data"]["projects"][0]["polished_bullets"],
                             ["整理用户反馈并分类"])
            self.assertEqual(edited["resume_data"]["projects"][1],
                             first["resume_data"]["projects"][1])
            self.assertEqual(len(edited["resume_versions"]), 1)
            self.assertEqual(edited["resume_versions"][0]["resume_data"], first["resume_data"])
            self.assertEqual(edited["collected_info"], first_facts)

            undo_state = {**edit_state, **edited, "messages": [HumanMessage(content="撤销")]}
            restored = asyncio.run(evaluating_node(undo_state, object()))
            self.assertEqual(restored["resume_data"]["projects"][0]["polished_bullets"],
                             first["resume_data"]["projects"][0]["polished_bullets"])
            self.assertEqual(restored["resume_data"]["projects"][1],
                             first["resume_data"]["projects"][1])
            self.assertEqual(len(calls), 2)
            self.assertEqual(undo_state["collected_info"], first_facts)
            self.assertIn("已恢复上一版文稿", restored["messages"][0].content)


if __name__ == "__main__":
    unittest.main()
