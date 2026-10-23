"""Read-only checklist, bounded orchestration and slow writing. Fictional data only."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]
from langchain_core.messages import HumanMessage
from app.agents import orchestrator as loop, orchestrator_tools as tools
from app.agents.orchestrator_context import project_tool_result
from app.config import Settings
from app.services.model_privacy import ContactRedactor
from app.services.resume_capacity import resume_data_hash
from app.services.resume_preflight import check_resume, precheck_for_state, preflight_resume
from app.services.resume_versions import text_hash
from app.services.resume_workspace import build_workspace
from test_orchestrator import Model, call, registry, state
from test_orchestrator_tools import Writer, measured, state_with_draft


def noisy_state():
    data = {'basic_info': {'name': '虚构候选人乙', 'email': 'fictional@example.invalid', 'links': [
        {'text': '个人主页', 'url': 'https://github.com/fictional-18e'},
        {'text': 'GitHub', 'url': 'http://github.com/fictional-18e/'}]},
        'projects': [{'item_id': 'fictional-a', 'name': '虚构资料项目', 'role': '功能说明' * 20,
                      'start_date': '2025年1月', 'tech_stack': ['Python', '我们来提供素材'],
                      'polished_bullets': ['问题：本人发现记录重复', '决策：记录重复',
                          '迭代：https://github.com/example-org/fictional-18e/pull/12 已合入']},
                     {'item_id': 'fictional-b', 'name': '虚构资料项目', 'polished_bullets': ['增加导出校验']}]}
    return state('检查重复和格式', resume_data=data, jd_text='岗位要求：Docker',
                 jd_info={'required_skills': ['Docker']})


class Quality18EChecklistTests(unittest.IsolatedAsyncioTestCase):
    async def test_contract_all_categories_stable_ids_and_no_state_mutation(self):
        value = noisy_state()
        before = deepcopy(value)
        outcome = await tools.execute_tool('check_resume', value, {}, tools.ToolContext())
        report = outcome.result
        self.assertEqual(set(report), {'status', 'issues', 'counts'})
        self.assertEqual(report['status'], 'ok')
        self.assertEqual({row['category'] for row in report['issues']}, {
            'duplicate_experience', 'duplicate_contact', 'contact_label', 'date_format',
            'tech_stack_noise', 'title_overflow', 'long_link', 'oral_phrase', 'repeated_point', 'jd_gap'})
        for issue in report['issues']:
            self.assertEqual(set(issue), {'id', 'category', 'severity', 'section', 'item_id', 'field',
                                          'message', 'suggestion', 'auto_fixable'})
            self.assertIn(issue['severity'], {'error', 'warning', 'info'})
            self.assertIs(type(issue['auto_fixable']), bool)
            self.assertTrue(issue['message'] and issue['suggestion'])
        self.assertEqual(len({r['id'] for r in report['issues']}), len(report['issues']))
        self.assertEqual(sum(report['counts'].values()), len(report['issues']))
        self.assertEqual(outcome.update, {})
        self.assertEqual(value, before)
        again = await tools.check_resume(value, {}, tools.ToolContext())
        self.assertEqual(report, again.result)
        self.assertEqual(outcome.events[0]['message'], '正在检查简历…')
        self.assertEqual(project_tool_result('check_resume', report, ContactRedactor()), report)

    async def test_empty_resume_and_strict_no_arguments(self):
        result = await tools.check_resume({}, {}, tools.ToolContext())
        self.assertEqual(result.result, {'status': 'ok', 'issues': [], 'counts': {'error': 0, 'warning': 0, 'info': 0}})
        invalid = await tools.check_resume({}, {'instruction': '改稿'}, tools.ToolContext())
        self.assertEqual(invalid.result['code'], 'invalid_arguments')
        self.assertFalse(invalid.update)

    def test_delivery_cleanup_removes_already_fixed_issues(self):
        value = noisy_state()
        cleaned, meta, _ = preflight_resume(value['resume_data'])
        report = precheck_for_state({**value, 'resume_data': cleaned, 'resume_meta': meta})
        categories = {r['category'] for r in report['issues']}
        self.assertFalse({'duplicate_contact', 'date_format', 'long_link', 'duplicate_experience',
                          'tech_stack_noise', 'contact_label', 'repeated_point'} & categories)
        self.assertTrue({'jd_gap', 'title_overflow'} <= categories)

    def test_invalid_date_is_manual_error_and_year_only_not_guessed(self):
        value = {'education': [{'item_id': 'fictional-school', 'start_date': '2023', 'end_date': '2027.13'}]}
        report = check_resume(value)
        self.assertEqual(len(report['issues']), 1)
        self.assertEqual(report['counts']['error'], 1)
        self.assertEqual(report['issues'][0]['field'], 'end_date')
        self.assertFalse(report['issues'][0]['auto_fixable'])

    def test_hidden_items_and_distinct_dates_not_flagged(self):
        data = {'projects': [{'item_id': 'a', 'name': '虚构课程项目', 'start_date': '2024.01', 'end_date': '2024.02'},
                             {'item_id': 'b', 'name': '虚构课程项目', 'start_date': '2025.01', 'end_date': '2025.02'},
                             {'item_id': 'c', 'name': '虚构课程项目', 'hidden': True,
                              'start_date': '2025年1月', 'polished_bullets': ['我写过接口']}]}
        self.assertEqual(check_resume(data)['issues'], [])

    def test_collected_source_identity_supports_duplicate_detection(self):
        data = {'projects': [{'item_id': 'a', 'name': '虚构甲项目'}, {'item_id': 'b', 'name': '虚构乙项目'}]}
        facts = {'projects': [{'item_id': iid, 'profile_refs': [{'item_id': 'same-fictional-source'}]} for iid in ('a', 'b')]}
        self.assertEqual(check_resume(data)['issues'], [])
        self.assertEqual(check_resume(data, facts)['issues'][0]['category'], 'duplicate_experience')

    def test_duplicates_without_ids_have_correct_section_and_distinct_issue_ids(self):
        data = {'education': [{'school': '虚构学院'}], 'projects': [
            {'name': '虚构甲项目'}, {'name': '虚构甲项目'}, {'name': '虚构乙项目'}, {'name': '虚构乙项目'}]}
        issues = check_resume(data)['issues']
        self.assertEqual(len(issues), 2)
        self.assertEqual({row['section'] for row in issues}, {'projects'})
        self.assertTrue(all(row['item_id'] is None for row in issues))
        self.assertEqual(len({row['id'] for row in issues}), 2)

    def test_jd_gaps_need_real_jd_visible_positive_evidence_and_valid_citations(self):
        data = {'projects': [{'item_id': 'a', 'name': '虚构核对项目', 'polished_bullets': ['实现服务封装', '尚未使用 Docker']}]}
        facts = {'projects': [{'item_id': 'a', 'facts': [{'id': 'f1', 'text': '实现服务封装', 'status': 'active'}]}]}
        jd = {'required_skills': ['Docker'], 'role_profile': {'source': 'jd', 'requirements': [
            {'id': 'r1', 'source': 'jd', 'text': '具备 API 开发经历', 'jd_quote': '具备 API 开发经历'}]}}
        meta = {'bullets': {'a': [{'text_hash': text_hash('实现服务封装'), 'fact_ids': ['f1'], 'req_ids': ['r1']}]}}
        report = check_resume(data, facts, jd_info=jd, has_jd=True, meta=meta)
        self.assertEqual(len(report['issues']), 1)
        self.assertIn('Docker', report['issues'][0]['message'])
        self.assertEqual(check_resume(data, facts, jd_info=jd, meta=meta)['issues'], [])
        self.assertEqual(check_resume(data, facts, jd_info={'role_profile': {'source': 'direction',
                         'requirements': jd['role_profile']['requirements']}}, has_jd=True)['issues'], [])
        for change in ('hidden', 'rewritten', 'withdrawn'):
            draft, collected = deepcopy(data), deepcopy(facts)
            if change == 'hidden':
                draft['projects'][0]['hidden'] = True
            elif change == 'rewritten':
                draft['projects'][0]['polished_bullets'][0] = '整理页面素材'
            else:
                collected['projects'][0]['facts'][0]['status'] = 'withdrawn'
            report = check_resume(draft, collected, jd_info=jd, has_jd=True, meta=meta)
            self.assertTrue(any('API' in row['message'] for row in report['issues']))

    async def test_write_and_deterministic_edit_refresh_report_after_cleanup(self):
        self.enterContext(patch('app.agents.tailor_pipeline.measure_rendered_pages', side_effect=measured))
        self.enterContext(patch('app.services.resume_capacity.measure_rendered_pages', side_effect=measured))
        value = state_with_draft()
        written = await tools.write_draft(value, {}, tools.ToolContext(llm=Writer()))
        self.assertIn(written.result['status'], {'ok', 'partial', 'unchanged'})
        self.assert_report(value, written)
        value = noisy_state()
        value['messages'] = [HumanMessage(content='合并重复项目，统一格式', id='fictional-edit')]
        edited = await tools.edit_resume(value, {'instruction': '合并重复项目，统一格式'}, tools.ToolContext())
        self.assertEqual(edited.result['status'], 'ok', edited.result)
        self.assert_report(value, edited)
        self.assertEqual(len(edited.update['resume_data']['projects']), 1)
        again = await tools.edit_resume({**value, **edited.update}, {'instruction': '合并重复项目，统一格式'}, tools.ToolContext())
        self.assertEqual(again.result['status'], 'unchanged')
        self.assert_report({**value, **edited.update}, again)

    def assert_report(self, value, outcome):
        current = {**value, **outcome.update}
        report = outcome.update['resume_meta']['precheck']
        self.assertEqual(report, precheck_for_state(current))
        self.assertEqual(report['data_hash'], resume_data_hash(current['resume_data']))
        self.assertEqual(report['counts'], outcome.result['counts'])
        self.assertEqual(build_workspace(current, current['resume_data'])['tailor']['resume_meta']['precheck'], report)

    async def test_partial_write_checks_delivered_fallback_and_failed_write_does_not_publish(self):
        value = state_with_draft()
        partial = tools.ToolOutcome({'status': 'partial'}, {'resume_data': value['resume_data']})
        with patch.object(tools, '_write', return_value=partial):
            outcome = await tools.write_draft(value, {}, tools.ToolContext())
        self.assert_report(value, outcome)
        failed = await tools.write_draft({}, {}, tools.ToolContext())
        self.assertNotIn('counts', failed.result)
        self.assertNotIn('resume_meta', failed.update)

    def test_workspace_invalidates_on_document_jd_or_fact_change_without_mutation(self):
        original = noisy_state()
        original['resume_meta']['precheck'] = precheck_for_state(original)
        for changed in ('document', 'jd', 'facts'):
            value = deepcopy(original)
            if changed == 'document':
                value['resume_data']['projects'][0]['name'] = '虚构新标题'
            elif changed == 'jd':
                value['jd_info']['required_skills'] = ['Rust']
            else:
                value['collected_info']['verification_notes'] = ['已撤回旧材料']
            before = deepcopy(value)
            report = build_workspace(value, value['resume_data'])['tailor']['resume_meta']['precheck']
            self.assertEqual(report['status'], 'stale')
            self.assertEqual(report['issues'], [])
            self.assertEqual(sum(report['counts'].values()), 0)
            self.assertEqual(value, before)

    async def test_session_meta_existing_interface_exposes_checklist(self):
        from app.api import chat
        value = noisy_state()
        value['resume_meta']['precheck'] = precheck_for_state(value)
        stored = {**value, 'has_authoritative_state': True}
        graph = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(values=value)))
        with patch.object(chat, 'session_can_read_checkpoint', return_value=True), \
                patch.object(chat, 'get_graph', return_value=graph), \
                patch.object(chat, 'load_resume_session', return_value=stored), \
                patch.object(chat, 'protect_state', side_effect=lambda owner, data: data), \
                patch.object(chat, 'protect_data', side_effect=lambda owner, data: data), \
                patch('app.services.conversation_store.session_owner', return_value='guest:fictional'), \
                patch('app.services.job_intel.background.refresh_expired', return_value=value):
            payload = await chat._session_meta('fictional-session', object())
        self.assertEqual(payload['workspace']['tailor']['resume_meta']['precheck'], value['resume_meta']['precheck'])
        self.assertEqual(payload['resume_meta']['precheck'], value['resume_meta']['precheck'])


class Quality18ELoopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = Settings(_env_file=None, AGENT_MODE='loop')
        self.enterContext(patch('app.config.get_settings', return_value=self.settings))

    async def test_repeated_insufficient_read_does_not_block_import_and_draft(self):
        read = AsyncMock(return_value=tools.ToolOutcome({'status': 'insufficient', 'missing': ['岗位正文']}))
        specs = registry(read_jd=read)
        # Five tools in one turn, with two identical reads; MAX_MODEL_CALLS is
        # independent of the number of calls in a provider message.
        model = Model([{'calls': [*call('read_jd', source_id='current')['calls'],
                                  *call('read_jd', source_id='current')['calls'],
                                  *call('read_profile')['calls']]},
                       call('use_profile_items', item_ids=['fictional-profile']), call('write_draft'),
                       {'content': '已按选用经历生成稿件。'}])
        result = await loop.run_orchestrator(state(), model, registry=specs)
        specs['write_draft'].handler.assert_awaited_once()
        read.assert_awaited_once()
        metrics = result['messages'][-1].additional_kwargs['orchestrator']
        self.assertEqual(metrics['tool_steps'], 2)
        self.assertLessEqual(metrics['tool_steps'], loop.MAX_TOOL_STEPS)
        self.assertTrue(metrics['tools'][1]['cached'])
        receipts = [json.loads(m['content']) for m in model.requests[-1]['messages'] if m['role'] == 'tool']
        self.assertEqual(receipts[0], receipts[1])

    async def test_different_arguments_run_after_insufficient_and_old_patch_not_replayed(self):
        read = AsyncMock(side_effect=[tools.ToolOutcome({'status': 'insufficient'}, {'jd_text': '旧岗位'}),
                                    tools.ToolOutcome({'status': 'ok'}, {'jd_text': '新岗位'})])
        value = state()
        value['messages'].insert(0, HumanMessage(content='虚构历史岗位', id='old-jd'))
        model = Model([{'calls': [*call('read_jd', source_id='old-jd')['calls'],
                                  *call('read_jd', source_id='current')['calls'],
                                  *call('read_jd', source_id='old-jd')['calls']]}, {'content': '已核对。'}])
        result = await loop.run_orchestrator(value, model, registry=registry(read_jd=read))
        self.assertEqual(read.await_count, 2)
        self.assertEqual(result['jd_text'], '新岗位')
        self.assertEqual(result['messages'][-1].additional_kwargs['orchestrator']['tool_steps'], 0)

    async def test_all_read_only_tools_cached_and_free_including_company_and_skill(self):
        cases = [('read_jd', {'source_id': 'current'}), ('read_profile', {}), ('check_layout', {}),
                 ('check_resume', {}), ('search_company', {'name': '虚构企业'}), ('use_skill', {'name': 'tech-stack'})]
        calls = [entry for name, args in cases for _ in range(2) for entry in call(name, **args)['calls']]
        specs = registry()
        result = await loop.run_orchestrator(state(), Model([{'calls': calls}, {'content': '已检查。'}]), registry=specs)
        for name, _ in cases:
            specs[name].handler.assert_awaited_once()
        self.assertEqual(result['messages'][-1].additional_kwargs['orchestrator']['tool_steps'], 0)

    async def test_auto_precheck_refreshes_read_receipt_after_edit_without_reexecuting_tool(self):
        before = {'status': 'ok', 'issues': [{'message': '存在重复'}], 'counts': {'error': 0, 'warning': 1, 'info': 0}}
        after = {'status': 'ok', 'issues': [], 'counts': {'error': 0, 'warning': 0, 'info': 0}}
        check = AsyncMock(return_value=tools.ToolOutcome(before))
        edit = AsyncMock(return_value=tools.ToolOutcome({'status': 'ok', 'counts': after['counts']},
                         {'resume_meta': {'precheck': {**after, 'data_hash': 'fictional-hash'}}}))
        model = Model([call('check_resume'), call('edit_resume', instruction='合并重复'), call('check_resume'), {'content': '重复已合并。'}])
        await loop.run_orchestrator(state(), model, registry=registry(check_resume=check, edit_resume=edit))
        check.assert_awaited_once()
        receipts = [json.loads(m['content'])['untrusted_data'] for m in model.requests[-1]['messages'] if m['role'] == 'tool']
        self.assertEqual(receipts[-1], after)

    async def test_infinite_read_calls_stop_at_hard_model_limit_even_if_final_ignores_tool_choice(self):
        specs = registry()
        model = Model([call('read_profile') for _ in range(loop.MAX_MODEL_CALLS + 1)])
        result = await loop.run_orchestrator(state(), model, registry=specs)
        self.assertEqual(len(model.requests), loop.MAX_MODEL_CALLS)
        self.assertFalse(model.requests[-1]['allow_tools'])
        self.assertTrue(result['messages'][-1].content.strip())
        specs['read_profile'].handler.assert_awaited_once()
        self.assertEqual(result['messages'][-1].additional_kwargs['orchestrator']['tool_steps'], 0)

    async def test_writer_separate_timeout_and_ordinary_timeout_cancellation(self):
        events = []
        async def slow(*args):
            try:
                await asyncio.sleep(.04)
                return tools.ToolOutcome({'status': 'ok'})
            finally:
                events.append('closed')
        specs = registry(write_draft=slow, check_layout=slow)
        model = Model([call('write_draft'), call('check_layout'), {'content': '写稿完成，排版检查超时。'}])
        self.settings.WRITE_DRAFT_TIMEOUT_SECONDS = .2
        result = await loop.run_orchestrator(state(), model, registry=specs, timeout=.01)
        metrics = result['messages'][-1].additional_kwargs['orchestrator']
        self.assertEqual([r['status'] for r in metrics['tools']], ['ok', 'error'])
        self.assertEqual(events, ['closed', 'closed'])
        self.assertIn('TimeoutError', model.requests[-1]['messages'][-1]['content'])

    async def test_writer_timeout_cancels_handler_and_has_final_reply(self):
        closed = asyncio.Event()
        async def slow(*args):
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
        model = Model([call('write_draft'), {'content': '写稿超时，尚未完成。'}])
        result = await loop.run_orchestrator(state(), model, registry=registry(write_draft=slow), write_draft_timeout=.01)
        self.assertTrue(closed.is_set())
        self.assertIn('TimeoutError', model.requests[-1]['messages'][-1]['content'])
        self.assertTrue(result['messages'][-1].content)

    async def test_slow_warning_once_while_running_without_private_content(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(*args):
            entered.set()
            await release.wait()
            return tools.ToolOutcome({'status': 'ok'})
        spec = replace(tools.TOOLS['write_draft'], handler=slow)
        value = state(collected_info={'projects': [{'raw_notes': '虚构私密正文'}, {}], 'work_experience': [{}]})
        with patch.object(loop, 'WRITE_DRAFT_SLOW_SECONDS', .01), self.assertLogs(loop.logger, 'WARNING') as captured:
            task = asyncio.create_task(loop._run_tool(spec, 'write_draft', value, tools.WriteArgs(), tools.ToolContext(), 1))
            await entered.wait()
            await asyncio.sleep(.03)
            self.assertFalse(task.done())
            release.set()
            await task
        self.assertEqual(len(captured.output), 1)
        self.assertIn('elapsed_seconds=', captured.output[0])
        self.assertIn('experience_count=3', captured.output[0])
        self.assertNotIn('虚构私密正文', captured.output[0])

    def test_default_timeouts_and_legacy_loop_environment_gets_headroom(self):
        self.assertEqual(self.settings.WRITE_DRAFT_TIMEOUT_SECONDS, 150)
        self.assertEqual(self.settings.CHAT_TIMEOUT_SECONDS, 360)
        self.assertEqual(self.settings.chat_turn_timeout_seconds, 360)
        self.settings.CHAT_TIMEOUT_SECONDS = 150
        self.assertEqual(self.settings.chat_turn_timeout_seconds, 330)
        self.settings.WRITE_DRAFT_TIMEOUT_SECONDS = 240
        self.assertEqual(self.settings.chat_turn_timeout_seconds, 420)
        self.settings.AGENT_MODE = 'off'
        self.assertEqual(self.settings.chat_turn_timeout_seconds, 150)

    async def test_heartbeat_keeps_slow_producer_alive_and_disconnect_does_not_cancel_it(self):
        from app.api import chat
        release, finished = asyncio.Event(), asyncio.Event()
        async def source():
            await release.wait()
            yield 'data: {"content":"合成结果"}\n\n'
            finished.set()
        self.assertEqual(chat.SSE_HEARTBEAT_SECONDS, 15)
        with patch.object(chat, 'SSE_HEARTBEAT_SECONDS', .01):
            stream = chat._complete_on_disconnect(source())
            self.assertEqual(await anext(stream), ': heartbeat\n\n')
            self.assertEqual(await anext(stream), ': heartbeat\n\n')
            self.assertFalse(finished.is_set())
            await stream.aclose()
            release.set()
            await asyncio.wait_for(finished.wait(), 1)
            await asyncio.gather(*list(chat._active_streams))

    @unittest.skipUnless(shutil.which('node'), 'Node required for DOM regression')
    def test_frontend_waits_through_150_seconds_then_accepts_final_stream(self):
        result = subprocess.run(['node', 'tests/quality_18e.dom.js'], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
