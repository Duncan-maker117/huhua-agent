"""Complete source intake, truthful receipts, and the next step after building."""
import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.agents.resume_graph import (  # noqa: E402
    _explicit_generate_requested, _init_state, build_graph, building_node,
    evaluating_node,
    stream_agent,
)
from app.services.resume_workspace import build_workspace  # noqa: E402

SOURCE = """以下是本人已确认的信息，暂无具体 JD，不虚构成果。
姓名：林同学
求职方向：AI 产品｜Agent 应用方向
教育背景：示例大学，计算机科学，本科，预计2027年6月毕业。

ResumeLab｜简历工作台　2025.09
个人项目｜产品设计与原型实现
- 实现对话资料收集、草稿和文件导出。
- 仅完成本地演示，尚未上线。

CodeLab｜代码 Agent　2026.05
训练营项目｜负责Agent设计
- 实现代码索引与工具调用，保留人工确认。

RouteLab｜旅行规划原型　2026.05—2026.07
黑客松项目｜产品方案与原型实现
- 完成地图和行程交互，支持加站与删站。

产品与技术能力：
开发实践：Python、FastAPI、LangGraph。
竞赛与活动：
校程序设计竞赛三等奖。
训练营结营证书。

请现在生成完整简历。
"""

RENDER_UNAVAILABLE = {'status': 'render_error', 'pages': None, 'within_page_limit': None,
                      'page_limit': 1, 'error_type': 'TestRendererUnavailable'}


class CompleteResumeTaskTest(unittest.IsolatedAsyncioTestCase):
    def test_generation_request_at_end_and_negation(self):
        for text in (SOURCE, '请直接为我制作一份中文一页简历。', '按已有资料开始生成待核对简历草稿',
                     '请按已有真实资料整理当前简历草稿，缺失信息保留待核对提示。'):
            self.assertTrue(_explicit_generate_requested(text), text)
        for text in ('先不要生成简历', '是否现在生成简历？', '项目提供生成简历功能。', '我设计直接生成简历按钮。',
                     '“请生成简历”是按钮示例。', '不要生成简历，先核对日期。'):
            self.assertFalse(_explicit_generate_requested(text), text)

    async def invoke(self, stage, source=SOURCE):
        graph = build_graph(object())
        state = {**_init_state(), 'stage': stage, 'messages': [HumanMessage(content=source)]}
        if stage == 'EVALUATING':
            state['candidate_history_reconciled'] = True
            state['collected_info']['projects'] = [{'name': '已有项目', 'description': '保留原有测试工作。'}]
        with (
            patch('app.agents.resume_graph._make_non_streaming_llm', return_value=object()),
            patch('app.agents.resume_graph.run_triage', AsyncMock(side_effect=AssertionError('完整资料不应再采访'))),
            patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value=RENDER_UNAVAILABLE),
        ):
            return await graph.ainvoke(state, {'configurable': {'thread_id': 'complete-' + stage}})

    async def test_complete_source_builds_from_first_turn_without_interview(self):
        result = await self.invoke('JD_INPUT')
        self.assertEqual(result['stage'], 'EVALUATING')
        data = result['resume_data']
        self.assertEqual([p['name'] for p in data['projects']], ['ResumeLab', 'CodeLab', 'RouteLab'])
        self.assertEqual(data['basic_info']['name'], '林同学')
        self.assertEqual(len(data['education']), 1)
        self.assertTrue(data['skills'])
        self.assertEqual(len(data['certificates']), 2)
        self.assertIn('尚未上线', data['projects'][0]['description'])
        self.assertIn('3 段项目', result['messages'][-1].content)
        self.assertIn('已按已有事实更新', result['messages'][-1].content)
        self.assertNotIn('先从哪一段', result['messages'][-1].content)
        view = build_workspace(result, data)
        self.assertEqual(view['focus'], 'resume')
        self.assertEqual(view['guidance']['title'], '草稿已就绪')
        self.assertNotIn('先生成草稿', str(view['guidance']))

    async def test_new_material_is_ingested_when_rebuilding_existing_draft(self):
        result = await self.invoke('EVALUATING')
        self.assertEqual(len(result['resume_data']['projects']), 4)
        self.assertIn('ResumeLab', result['resume_draft'])
        self.assertIn('已有项目', result['resume_draft'])

    async def test_generate_command_with_supplement_extracts_new_facts(self):
        from app.services.resume_facts import new_fact, normalize_fact_store
        for supplement in ("补充：我在纸页工具编写了12条接口测试。", "我给一位同学演示了纸页工具，收集到2条反馈，并修改了文件选择提示。", "补充纸页工具：新增2条反馈。"):
            with self.subTest(supplement=supplement):
                state = {**_init_state(), 'stage': 'EVALUATING', 'candidate_history_reconciled': True,
                         'messages': [HumanMessage(content=supplement + '请生成简历。')]}
                state['collected_info']['projects'] = [{'name': '纸页工具', 'description': '实现页面拆分。'}]
                state['collected_info'] = normalize_fact_store(state['collected_info'])
                updated = copy.deepcopy(state['collected_info'])
                updated['projects'][0]['facts'].append(new_fact(supplement))
                with (
                    patch('app.agents.resume_graph._make_non_streaming_llm', return_value=object()),
                    patch('app.agents.resume_graph._extract_info_from_message', AsyncMock(return_value=updated)) as extract,
                    patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value=RENDER_UNAVAILABLE),
                ):
                    result = await evaluating_node(state, object())
                extract.assert_awaited_once()
                self.assertIn(supplement, result['resume_draft'])
                self.assertEqual(result['collected_info']['projects'][0]['facts'][-1]['text'], supplement)

    async def test_repeated_build_does_not_claim_a_change(self):
        data = {'basic_info': {'name': '林同学'}, 'projects': [{'name': 'ResumeLab', 'description': '本地原型。'}]}
        with patch('app.agents.resume_graph._write_resume_update', AsyncMock(return_value={
            'resume_data': copy.deepcopy(data), 'resume_meta': {}, 'resume_versions': [],
            'session_constraints': {'page_limit': 1}, 'match_plan': {},
            'page_check': {'status': 'not_rendered', 'pages': None},
            'guard_fallbacks': [], 'changed': False, 'change_summary': [],
        })):
            result = await building_node({'resume_data': data}, object())
        self.assertIn('没有形成可保存的正文修改', result['messages'][0].content)
        self.assertNotIn('已更新', result['messages'][0].content)

    async def test_basic_only_build_names_its_limitation(self):
        data = {'basic_info': {'name': '林同学'}, 'projects': []}
        with patch('app.agents.resume_graph._write_resume_update', AsyncMock(return_value={
            'resume_data': data, 'resume_meta': {}, 'resume_versions': [],
            'session_constraints': {'page_limit': 1}, 'match_plan': {},
            'page_check': {'status': 'not_rendered', 'pages': None},
            'guard_fallbacks': [], 'changed': True, 'change_summary': [],
        })):
            result = await building_node(_init_state(), object())
        self.assertIn('只整理到基本信息', result['messages'][0].content)
        self.assertNotIn('已更新', result['messages'][0].content)

    async def test_no_success_receipt_before_a_failed_canonical_save(self):
        class Graph:
            async def astream(self, *args, **kwargs):
                yield 'updates', {'building': {'messages': [AIMessage(content='已更新右侧草稿。')]}}
            async def aget_state(self, config):
                return SimpleNamespace(values={'resume_data': {'projects': [{'name': 'ResumeLab'}]}})
        chunks = []
        with (
            patch('app.agents.resume_graph.get_graph', return_value=Graph()),
            patch('app.services.session_store.save_resume_session', side_effect=RuntimeError('storage unavailable')),
        ):
            with self.assertRaises(RuntimeError):
                async for chunk in stream_agent([{'content': '请生成简历'}], 'save-failure', object()):
                    chunks.append(chunk)
        self.assertEqual(chunks, [])

    async def test_failed_save_is_not_replayed_as_success_from_checkpoint(self):
        graph = build_graph(object())
        sid = 'failed-build-checkpoint'
        with (
            patch('app.agents.resume_graph.get_graph', return_value=graph),
            patch('app.agents.resume_graph._make_non_streaming_llm', return_value=object()),
            patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value=RENDER_UNAVAILABLE),
            patch('app.services.session_store.save_resume_session', side_effect=RuntimeError('storage unavailable')),
        ):
            with self.assertRaises(RuntimeError):
                _ = [chunk async for chunk in stream_agent([{'content': SOURCE}], sid, object())]
        snapshot = await graph.aget_state({'configurable': {'thread_id': sid}})
        reply = snapshot.values['messages'][-1]
        self.assertTrue(reply.additional_kwargs['resume_save_failed'])
        self.assertIn('未保存', reply.content)
        self.assertNotIn('已更新', reply.content)

    async def test_success_receipt_follows_canonical_save(self):
        events = []
        class Graph:
            async def astream(self, *args, **kwargs):
                yield 'updates', {'building': {'messages': [AIMessage(content='已更新右侧草稿。')]}}
            async def aget_state(self, config):
                return SimpleNamespace(values={'resume_data': {'projects': [{'name': 'ResumeLab'}]}})
        with (
            patch('app.agents.resume_graph.get_graph', return_value=Graph()),
            patch('app.services.session_store.save_resume_session', side_effect=lambda **kw: events.append('saved')),
        ):
            async for chunk in stream_agent([{'content': '请生成简历'}], 'save-success', object()):
                events.append(chunk)
        self.assertEqual(events, ['saved', '已更新右侧草稿。'])


if __name__ == '__main__':
    unittest.main()
