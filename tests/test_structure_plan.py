"""P3 confirmation flow: synthetic facts, local models and mocked PDF checks only."""
import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
from contextvars import ContextVar
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.agents import resume_graph as graph  # noqa: E402
from app.agents.resume_writer import run_resume_writer  # noqa: E402
from app.config import get_settings, Settings  # noqa: E402
from app.schemas.writer import StructurePlan  # noqa: E402
from app.services.fact_guard import guard_bullets  # noqa: E402
from app.services.resume_workspace import build_workspace  # noqa: E402
from app.services.structure_plan import (edit_plan, plan_action, select_plan, plan_guidance)  # noqa: E402
from test_resume_writer import FakeModel  # noqa: E402


def fact(fid, text):
    return {'id': fid, 'text': text, 'source_quote': text, 'kind': 'action', 'status': 'active', 'source': 'chat'}


def source():
    return {'basic_info': {'name': '合成候选人'}, 'education': [], 'work_experience': [], 'skills': [],
            'projects': [{'item_id': 'p1', 'name': '纸舟计划', 'facts': [fact('f1', '整理用户反馈并分类')]}],
            'open_source': [{'item_id': 'o1', 'name': 'EchoKit', 'facts': [fact('f2', '修复跨语言记忆污染')]}],
            'awards': [{'item_id': 'a1', 'name': '合成竞赛', 'facts': [fact('f3', '获得校级竞赛二等奖')]}]}


def card():
    return {'recommended': {'label': '主线叙事型', 'positioning': '修复跨语言记忆污染',
                'thesis': '通过修复跨语言记忆污染展示记忆处理实践',
                'requirements': [{'req_id': 'r1', 'status': 'direct', 'fact_ids': ['f2']}],
                'section_order': ['open_source', 'projects', 'education', 'awards', 'skills', 'work_experience', 'certificates'],
                'experience_plan': [
                    {'item_id': 'o1', 'treatment': 'lead', 'target_bullets': 3,
                     'reason': 'EchoKit 修复跨语言记忆污染，直接对应 JD 的记忆处理。'},
                    {'item_id': 'p1', 'treatment': 'brief', 'target_bullets': 1,
                     'reason': '纸舟计划整理用户反馈，可补充问题发现过程，和记忆处理关联较弱。'}]},
            'alternatives': [{'label': '问题发现型', 'positioning': '整理用户反馈并分类', 'thesis': '整理用户反馈并分类',
                'section_order': ['projects', 'open_source', 'education', 'awards', 'skills', 'work_experience', 'certificates'],
                'experience_plan': [{'item_id': 'p1', 'treatment': 'lead', 'target_bullets': 3,
                                     'reason': '纸舟计划的反馈分类可从用户问题切入记忆处理。'}]}]}


def writer_draft():
    return {'items': [{'item_id': iid, 'section': section, 'bullets': [{'text': text, 'fact_ids': [fid]}]}
                     for iid, section, text, fid in [('o1', 'open_source', '修复跨语言记忆污染', 'f2'),
                                                    ('p1', 'projects', '整理用户反馈并分类', 'f1')]]}


def state(text='生成简历'):
    return {**graph._init_state(), 'messages': [HumanMessage(content=text)], 'stage': 'BUILDING',
            'collected_info': source(), 'jd_info': {'job_title': '记忆应用实习生', 'role_profile': {
                'role_family': 'other', 'requirements': [{'id': 'r1', 'text': '记忆处理'}]}}}


async def lexical_guard(rows, facts, **kwargs):
    kwargs.pop('llm', None)
    return await guard_bullets(rows, facts, **kwargs)


class StructurePlanFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = []
        for context in (patch.object(get_settings(), 'LLM_PLAN_CONFIRM', True),
                        patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={
                            'status': 'rendered', 'pages': 1, 'page_limit': 1, 'within_page_limit': True}),
                        patch('app.agents.resume_writer.guard_bullets', side_effect=lexical_guard)):
            self.stack.append(context)
            context.start()
            self.addCleanup(context.stop)
        context = patch('app.services.fact_guard.verify_semantics', AsyncMock(side_effect=lambda pairs, *args, **kwargs:
            {row['id']: {'verdict': 'pass'} for row in pairs}))
        context.start()
        self.addCleanup(context.stop)

    async def planned(self):
        model = FakeModel([('StructurePlan', card())])
        initial = state()
        result = await graph.building_node(initial, model)
        return {**initial, **result}, model

    async def test_first_draft_returns_card_only_no_version_or_page_measurement(self):
        with patch('app.agents.tailor_pipeline.run_tailor_pipeline', AsyncMock()) as pipeline:
            current, model = await self.planned()
        self.assertFalse(current['resume_data'])
        self.assertFalse(current['resume_versions'])
        self.assertFalse(current['version_id'])
        self.assertEqual(current['stage'], 'BUILDING')
        self.assertTrue(current['pending_plan'])
        self.assertFalse(current['confirmed_plan'])
        pipeline.assert_not_awaited()
        self.assertEqual([name for name, _ in model.calls], ['StructurePlan'])
        guidance = build_workspace(current)['guidance']
        self.assertEqual(guidance['kind'], 'structure_plan')
        self.assertEqual(guidance['structure_plan']['recommended']['experience_plan'][0]['name'], 'EchoKit')
        self.assertEqual(guidance['options'][0]['value'], '按推荐写')
        self.assertEqual(build_workspace(current)['tailor']['questions'], [])

    async def test_recommended_confirmation_writes_and_persists_summary(self):
        current, _ = await self.planned()
        current['messages'] = [HumanMessage(content='按推荐写')]
        writer = FakeModel([('WriterDraft', writer_draft())])
        result = await graph.structure_plan_node(current, writer)
        self.assertFalse(result['pending_plan'])
        self.assertFalse(result['plan_required'])
        self.assertEqual(result['confirmed_plan']['label'], '主线叙事型')
        self.assertEqual(result['resume_meta']['confirmed_plan'], result['confirmed_plan'])
        self.assertTrue(result['version_id'])
        self.assertEqual(result['resume_data']['summary'], '修复跨语言记忆污染')
        self.assertEqual(result['resume_data']['sections'][0]['kind'], 'open_source')
        reply = result['messages'][0].content
        self.assertIn('这版的思路', reply)
        self.assertIn(card()['recommended']['thesis'], reply)
        self.assertIn('EchoKit（修复跨语言记忆污染）', reply)
        self.assertNotIn('方案摘要', reply)
        self.assertNotIn('正文写到', reply)
        self.assertEqual([name for name, _ in writer.calls], ['WriterDraft'])

    async def test_alternative_and_natural_text_confirmation_merge_diffs(self):
        for command in ('用备选：问题发现型', '用第二个方案', '用备选1'):
            with self.subTest(command=command):
                current, _ = await self.planned()
                current['messages'] = [HumanMessage(content=command)]
                result = await graph.structure_plan_node(current, FakeModel([('WriterDraft', writer_draft())]))
                self.assertEqual(result['confirmed_plan']['label'], '问题发现型')
                treatments = {row['item_id']: row['treatment'] for row in result['confirmed_plan']['experience_plan']}
                self.assertEqual(treatments, {'o1': 'lead', 'p1': 'lead'})
                self.assertEqual(result['resume_data']['sections'][0]['kind'], 'projects')

    async def test_colloquial_confirmation_is_deterministic(self):
        current, _ = await self.planned()
        current['messages'] = [HumanMessage(content='就按这个')]
        self.assertEqual(graph.route_by_stage(current), 'structure_plan')
        result = await graph.structure_plan_node(current, FakeModel([('WriterDraft', writer_draft())]))
        self.assertTrue(result['confirmed_plan'])

    async def test_invalid_alternative_keeps_card_without_writer_call(self):
        current, _ = await self.planned()
        current['messages'] = [HumanMessage(content='用第三个方案')]
        model = FakeModel([])
        result = await graph.structure_plan_node(current, model)
        self.assertEqual(model.calls, [])
        self.assertTrue(result['pending_plan'])
        self.assertNotIn('version_id', result)

    async def test_text_order_and_omission_edit_refreshes_all_options_without_model(self):
        current, _ = await self.planned()
        current['messages'] = [HumanMessage(content='把开源贡献放前面，纸舟计划不写')]
        model = FakeModel([])
        result = await graph.structure_plan_node(current, model)
        self.assertEqual(model.calls, [])
        self.assertNotIn('resume_data', result)
        for i in range(2):
            selected = select_plan(result['pending_plan'], i)
            self.assertEqual(selected['section_order'][0], 'open_source')
            self.assertEqual(next(row for row in selected['experience_plan'] if row['item_id'] == 'p1')['treatment'], 'backup')
        written = await graph.structure_plan_node({**current, **result, 'messages': [HumanMessage(content='按推荐写')]},
                                                 FakeModel([('WriterDraft', writer_draft())]))
        self.assertTrue(written['resume_data']['projects'][0]['hidden'])
        self.assertEqual(written['confirmed_plan']['experience_plan'][-1]['treatment'], 'backup')

    async def test_thesis_change_calls_only_plan_and_clears_old_confirmation(self):
        current, _ = await self.planned()
        current.update(confirmed_plan=select_plan(current['pending_plan']), pending_plan={},
                       messages=[HumanMessage(content='主线换成记忆处理')])
        model = FakeModel([('StructurePlan', card())])
        result = await graph.structure_plan_node(current, model)
        self.assertTrue(result['pending_plan'])
        self.assertFalse(result['confirmed_plan'])
        self.assertNotIn('version_id', result)
        self.assertEqual([name for name, _ in model.calls], ['StructurePlan'])

    async def test_direct_write_runs_plan_then_writer_and_attaches_summary(self):
        for command in ('直接写', '先出一版', '不用确认'):
            with self.subTest(command=command):
                model = FakeModel([('StructurePlan', card()), ('WriterDraft', writer_draft())])
                result = await graph.building_node(state(command), model)
                self.assertEqual([name for name, _ in model.calls], ['StructurePlan', 'WriterDraft'])
                self.assertTrue(result['confirmed_plan'])
                self.assertEqual(result['messages'][0].content.count('**这版的思路**'), 1)
                self.assertNotIn('方案摘要', result['messages'][0].content)

    async def test_confirmed_plan_is_reused_even_when_edit_reuse_switch_off(self):
        current = state('改写一下正文')
        current.update(confirmed_plan=select_plan(card()), plan_required=False)
        with patch.object(get_settings(), 'LLM_WRITER_EDIT_REUSE_PLAN', False):
            model = FakeModel([('WriterDraft', writer_draft())])
            result = await graph.building_node(current, model)
        self.assertEqual([name for name, _ in model.calls], ['WriterDraft'])
        self.assertTrue(result['writer_diagnostic']['plan_reused'])
        self.assertEqual(result['confirmed_plan']['section_order'], current['confirmed_plan']['section_order'])
        payload = json.loads(model.calls[0][1][-1].content)
        self.assertEqual(payload['match_plan']['thesis'], current['confirmed_plan']['thesis'])

    async def test_confirmed_structural_edit_updates_draft_and_plan_without_model(self):
        current = state('按推荐写')
        current.update(confirmed_plan=select_plan(card()), plan_required=False)
        written = await graph.building_node(current, FakeModel([('WriterDraft', writer_draft())]))
        current = {**current, **written, 'messages': [HumanMessage(content='纸舟计划不写，把项目经历放前面')]}
        model = FakeModel([])
        result = await graph.structure_plan_node(current, model)
        self.assertTrue(result['resume_data']['projects'][0]['hidden'])
        self.assertEqual(result['resume_data']['sections'][0]['kind'], 'projects')
        self.assertEqual(result['confirmed_plan']['section_order'][0], 'projects')
        self.assertEqual(result['resume_meta']['confirmed_plan'], result['confirmed_plan'])
        self.assertEqual(model.calls, [])

    async def test_new_jd_clears_confirmation_then_shows_new_card(self):
        current = state('新岗位职责：记忆处理，任职要求：具备实践记录。')
        current.update(confirmed_plan=select_plan(card()), plan_required=False,
                       resume_data={'projects': [{'item_id': 'p1', 'name': '纸舟计划', 'polished_bullets': ['整理用户反馈并分类']}]},
                       resume_meta={'confirmed_plan': select_plan(card())}, requested_task='decode_jd')
        model = FakeModel([('StructurePlan', card())])
        with patch('app.agents.resume_graph._run_decoder_and_build_reply', AsyncMock(return_value=(state()['jd_info'], '已读岗位'))):
            result = await graph.skill_task_node(current, model)
        self.assertFalse(result['confirmed_plan'])
        self.assertNotIn('confirmed_plan', result['resume_meta'])
        self.assertTrue(result['pending_plan'])
        self.assertEqual([name for name, _ in model.calls], ['StructurePlan'])

    async def test_new_jd_without_draft_clears_both_plans_before_generation(self):
        current = state('岗位职责：记忆处理。')
        current.update(pending_plan=card(), confirmed_plan=select_plan(card()), requested_task='decode_jd')
        with patch('app.agents.resume_graph._run_decoder_and_build_reply', AsyncMock(return_value=(state()['jd_info'], '已读岗位'))):
            result = await graph.skill_task_node(current, FakeModel([]))
        self.assertFalse(result['pending_plan'])
        self.assertFalse(result['confirmed_plan'])
        self.assertTrue(result['plan_required'])

    async def test_switch_false_retains_single_one_pass_generation(self):
        model = FakeModel([('OnePassOutput', {'match_plan': {}, 'writer': writer_draft()})])
        with patch.object(get_settings(), 'LLM_PLAN_CONFIRM', False):
            result = await graph.building_node(state(), model)
        self.assertTrue(result['version_id'])
        self.assertNotIn('pending_plan', result)
        self.assertEqual([name for name, _ in model.calls], ['OnePassOutput'])

    async def test_legacy_visible_draft_without_confirmed_plan_does_not_show_card(self):
        current = state()
        current.pop('plan_required')
        current['resume_data'] = {'projects': [{'item_id': 'p1', 'name': '纸舟计划', 'polished_bullets': ['整理用户反馈并分类']}]}
        model = FakeModel([('OnePassOutput', {'match_plan': {}, 'writer': writer_draft()})])
        result = await graph.building_node(current, model)
        self.assertNotIn('pending_plan', result)
        self.assertEqual([name for name, _ in model.calls], ['OnePassOutput'])

    async def test_plan_lexical_guard_removes_unsupported_claims_and_stale_refs(self):
        raw = card()
        raw['recommended'].update(positioning='主导1000用户增长', thesis='使用 Kubernetes 部署到线上')
        raw['recommended']['requirements'][0]['fact_ids'] = ['deleted-fact']
        raw['recommended']['experience_plan'].append({'item_id': 'invented', 'treatment': 'lead'})
        raw['alternatives'][0]['positioning'] = '拥有300用户'
        model = FakeModel([('StructurePlan', raw)])
        result = await run_resume_writer(source(), state()['jd_info']['role_profile'], model, phase='plan', mode='two_pass')
        recommended = result['structure_plan']['recommended']
        self.assertEqual(recommended['positioning'], '')
        self.assertEqual(recommended['thesis'], '')
        self.assertEqual(recommended['requirements'][0]['status'], 'gap')
        self.assertNotIn('invented', {row['item_id'] for row in recommended['experience_plan']})
        self.assertEqual(result['structure_plan']['alternatives'][0]['positioning'], '')
        self.assertEqual(len(model.calls), 1)

    async def test_model_failure_returns_conservative_card_without_writing(self):
        result = await graph.building_node(state(), FakeModel([('StructurePlan', RuntimeError('offline'))]))
        self.assertTrue(result['pending_plan']['alternatives'])
        self.assertNotIn('resume_data', result)
        self.assertEqual(result['pending_plan']['recommended']['positioning'], '')
        self.assertTrue(all(row['reason'] for row in result['pending_plan']['recommended']['experience_plan']))

    async def test_writer_failure_preserves_confirmed_omission(self):
        selected = select_plan(card())
        selected, _ = edit_plan(selected, '纸舟计划不写', source())
        result = await run_resume_writer(source(), state()['jd_info']['role_profile'],
            FakeModel([('WriterDraft', RuntimeError('offline'))]), previous_plan=selected, phase='write')
        self.assertTrue(result['resume_data']['projects'][0]['hidden'])
        self.assertEqual(next(row for row in result['match_plan']['experience_plan'] if row['item_id'] == 'p1')['treatment'], 'backup')

    async def test_pdf_compression_cannot_silently_hide_confirmed_experience(self):
        current = state()
        current.update(confirmed_plan=select_plan(card()), plan_required=False)
        with patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={'status': 'rendered', 'pages': 2,
                'page_limit': 1, 'within_page_limit': False}), patch('app.agents.tailor_pipeline.plan_compression', return_value=[
                    {'op': 'hide_item', 'item_id': 'p1', 'target': '/projects/0', 'writer_required': False}]):
            result = await graph.building_node(current, FakeModel([('WriterDraft', writer_draft())]))
        self.assertFalse(result['resume_data']['projects'][0].get('hidden'))
        self.assertFalse(result['page_check']['within_page_limit'])

    async def test_graph_checkpoint_keeps_card_and_confirmation_across_turns(self):
        model = FakeModel([('StructurePlan', card()), ('WriterDraft', writer_draft())])
        compiled = graph.build_graph(model)
        config = {'configurable': {'thread_id': 'synthetic-p3'}}
        first = await compiled.ainvoke(state(), config)
        self.assertTrue(first['pending_plan'])
        second = await compiled.ainvoke({'messages': [HumanMessage(content='按推荐写')]}, config)
        self.assertTrue(second['confirmed_plan'])
        self.assertFalse(second['pending_plan'])
        self.assertTrue(second['version_id'])
        self.assertEqual([name for name, _ in model.calls], ['StructurePlan', 'WriterDraft'])

    async def test_stream_card_does_not_serialize_a_draft_and_confirm_reply_is_public(self):
        model = FakeModel([('StructurePlan', card()), ('WriterDraft', writer_draft())])
        compiled = graph.build_graph(model)
        config = {'configurable': {'thread_id': 'synthetic-stream'}}
        initial = state()
        initial['messages'] = []
        await compiled.aupdate_state(config, initial)
        saved = []
        def save(**kwargs):
            saved.append(deepcopy(kwargs))
            return kwargs
        with patch('app.agents.resume_graph.get_graph', return_value=compiled), \
                patch('app.services.session_store.save_resume_session', side_effect=save), \
                patch('app.services.profile_bridge.archive_event_for_message', return_value=None):
            first = ''.join([text async for text in graph.stream_agent([{'role': 'user', 'content': '生成简历'}], 'synthetic-stream', model)])
            self.assertIn('先定', first)
            self.assertEqual(saved[-1]['resume_data'], {})
            self.assertFalse(saved[-1]['resume_versions'])
            second = ''.join([text async for text in graph.stream_agent([{'role': 'user', 'content': '按推荐写'}], 'synthetic-stream', model)])
            self.assertIn('这版的思路', second)
            self.assertTrue(saved[-1]['resume_meta']['confirmed_plan'])

    async def test_runner_full_fake_replay_records_auto_confirm_and_latency(self):
        here = ROOT / 'evaluation' / 'tailor-bench'
        sys.path.insert(0, str(here))
        spec = importlib.util.spec_from_file_location('p3_full_runner', here / 'run_bench.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        model = FakeModel([('StructurePlan', card()), ('WriterDraft', writer_draft())])
        compiled = graph.build_graph(model)
        initial = state()
        initial['messages'] = []
        await compiled.aupdate_state({'configurable': {'thread_id': 'synthetic-bench'}}, initial)
        stored = {}
        def save(**kwargs):
            stored.update(deepcopy(kwargs))
            return deepcopy(stored)
        case = {'id': 'synthetic-plan', 'truth_facts': ['整理用户反馈并分类', '修复跨语言记忆污染'],
                'jd_text': '', 'opening_turns': ['生成简历'], 'opening_fact_indices': [[0, 1]],
                'edit_instructions': [], 'truth_review_status': 'synthetic'}
        args = SimpleNamespace(turn_timeout=5, max_followups=0, judge_timeout=5, selector_timeout=5)
        with tempfile.TemporaryDirectory() as folder, \
                patch('app.agents.resume_graph.get_graph', return_value=compiled), \
                patch('app.services.conversation_store.create_conversation', return_value={'session_id': 'synthetic-bench'}), \
                patch('app.services.session_store.save_resume_session', side_effect=save), \
                patch('app.services.session_store.load_resume_session', side_effect=lambda sid: deepcopy(stored)), \
                patch('app.services.profile_bridge.archive_event_for_message', return_value=None), \
                patch('judge.judge_version', AsyncMock(return_value={'status': 'completed'})), \
                patch.object(runner, 'measure_rendered_resume', return_value={'status': 'rendered', 'pages': 1}):
            result = await runner.run_case(case, model, None, lambda: SimpleNamespace(calls=[]),
                ContextVar('synthetic-counter'), args, Path(folder))
            turns = json.loads((Path(folder) / case['id'] / 'turns.json').read_text())
            self.assertEqual([row['phase'] for row in turns], ['opening', 'auto_confirm'])
            self.assertEqual(result['auto_confirm_count'], 1)
            self.assertEqual(result['turn_count'], 2)
            self.assertEqual(result['auto_confirm_latency_seconds'], turns[1]['elapsed_seconds'])
            self.assertEqual(turns[0]['new_versions'], [])
            self.assertTrue(turns[1]['new_versions'])
            self.assertEqual(result['first_draft_turn'], 2)
            self.assertEqual(result['status'], 'completed')


class PlanCommandTest(unittest.TestCase):
    def test_frontend_renderer_discloses_diff_and_sends_exact_deduplicated_choice(self):
        result = subprocess.run(['node', str(ROOT / 'tests' / 'structure_plan.dom.js'),
                                 str(ROOT / 'web' / 'resume-workspace.js')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DOM checks passed', result.stdout)

    def test_order_move_and_item_order_are_deterministic(self):
        selected = select_plan(card())
        modified, changed = edit_plan(selected, '把开源贡献放到项目经历后面', source())
        self.assertTrue(changed)
        self.assertGreater(modified['section_order'].index('open_source'), modified['section_order'].index('projects'))
        modified, _ = edit_plan(selected, '纸舟计划放到EchoKit前面', source())
        self.assertEqual(modified['experience_plan'][0]['item_id'], 'p1')
        self.assertEqual(selected, select_plan(card()))
        modified, _ = edit_plan(selected, '栏目顺序：项目经历、开源贡献、教育经历', source())
        self.assertEqual(modified['section_order'][:3], ['projects', 'open_source', 'education'])

    def test_ordinal_omission_only_hides_the_selected_item(self):
        collected = source()
        collected['projects'].append({'item_id': 'p2', 'name': '项目乙', 'facts': [fact('f4', '核对重复记录')]})
        selected = select_plan(card())
        selected['experience_plan'].append({'item_id': 'p2', 'treatment': 'keep', 'reason': '核对重复记录', 'target_bullets': 2})
        edited, changed = edit_plan(selected, '删除第二个项目', collected)
        self.assertTrue(changed)
        treatments = {row['item_id']: row['treatment'] for row in edited['experience_plan']}
        self.assertEqual(treatments, {'o1': 'lead', 'p1': 'brief', 'p2': 'backup'})
        unknown, changed = edit_plan(selected, '删除第三个项目', collected)
        self.assertFalse(changed)
        self.assertEqual(unknown, selected)

    def test_schema_accepts_long_positioning_and_limits_alternative_count(self):
        self.assertEqual(StructurePlan.model_validate({'recommended': {'positioning': '字' * 41}}).recommended.positioning,
                         '字' * 41)
        with self.assertRaises(ValueError):
            StructurePlan.model_validate({'recommended': {}, 'alternatives': card()['alternatives'] * 3})

    def test_configuration_default_is_true_without_environment(self):
        with patch.dict('os.environ', {'LLM_PLAN_CONFIRM': 'true'}):
            self.assertTrue(Settings(_env_file=None).LLM_PLAN_CONFIRM)
        self.assertTrue(Settings.model_fields['LLM_PLAN_CONFIRM'].default)

    def test_every_button_text_has_deterministic_selection(self):
        guidance = plan_guidance(card(), source())
        self.assertEqual([plan_action(row['value'], card()) for row in guidance['options']], [('confirm', 0), ('confirm', 1)])

    def test_runner_auto_confirm_metered_turn_and_explicit_responses(self):
        here = ROOT / 'evaluation' / 'tailor-bench'
        sys.path.insert(0, str(here))
        spec = importlib.util.spec_from_file_location('p3_runner', here / 'run_bench.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        for text in ('整理措辞', ''):
            turn = AsyncMock()
            self.assertTrue(asyncio.run(runner.auto_confirm_plan({'pending_plan': card()}, text, turn)))
            turn.assert_awaited_once_with('按推荐写', 'auto_confirm')
        for text in ('按推荐写', '用第二个方案', '纸舟计划不写', '主线换成记忆处理', '直接写'):
            turn = AsyncMock()
            self.assertFalse(asyncio.run(runner.auto_confirm_plan({'pending_plan': card()}, text, turn)))
            turn.assert_not_awaited()
        turn = AsyncMock()
        self.assertFalse(asyncio.run(runner.auto_confirm_plan({}, '整理措辞', turn)))
        turn.assert_not_awaited()
        snapshot = runner.snapshot_context({'pending_plan': card(), 'confirmed_plan': {}})
        self.assertEqual(snapshot['pending_plan'], card())
        turn = AsyncMock()
        self.assertTrue(asyncio.run(runner.auto_confirm_plan({'pending_plan': card()}, '压缩成一页', turn, collected_info=source())))
        turn.assert_awaited_once_with('按推荐写', 'auto_confirm')
