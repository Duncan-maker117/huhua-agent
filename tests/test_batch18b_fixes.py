"""Offline replay of the three live-model failures; never loads the live databases."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]
from langchain_core.messages import HumanMessage  # noqa: E402
from app.agents import orchestrator_tools as tools, resume_graph as graph  # noqa: E402
from app.agents.orchestrator_context import project_tool_result  # noqa: E402
from app.services.fact_guard import guard_bullets  # noqa: E402
from app.services.fact_coverage import ensure_fact_coverage  # noqa: E402
from app.services.model_privacy import ContactRedactor  # noqa: E402
from app.services.profile_bridge import sanitize_fact_history  # noqa: E402
from app.services.resume_versions import restore_payload, text_hash, valid_bullet_metadata  # noqa: E402
from app.services.tech_stack import (  # noqa: E402
    apply_stack_edit, clean_stack_prose, normalize_prose, parse_stack_edit, project_item_stack,
)
from test_orchestrator_tools import measured  # noqa: E402
from test_batch18b import WriterStub, collected, document  # noqa: E402

FIXTURE = json.loads((ROOT / 'tests/fixtures/batch18b_tech_edit.json').read_text())
INSTRUCTION = FIXTURE['instruction']
EXPECTED = ['MCP', 'Tool Calling', 'LangChain', 'FastAPI']


def replay_state(instruction=INSTRUCTION):
    return {**graph._init_state(), **deepcopy(FIXTURE['state']),
            'messages': [HumanMessage(content=instruction, id='offline-tech-edit')]}


def stable(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class StackEditReplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.measure = patch('app.services.resume_capacity.measure_rendered_pages', side_effect=measured)
        self.measure.start()
        self.addCleanup(self.measure.stop)

    async def test_real_state_record_edit_save_and_undo_preserve_body(self):
        state = replay_state()
        before = deepcopy(state)
        project = state['resume_data']['projects'][0]
        self.assertEqual(project['tech_stack'], ['MCP', '记忆', 'Tool Calling', 'LangChain'])
        self.assertEqual(len(project['polished_bullets']), 3)
        ctx = tools.ToolContext()
        with patch('app.agents.fact_extractor.extract_facts_patch', new=AsyncMock(side_effect=AssertionError('model called'))):
            recorded = await tools.record_facts(state, {'source_id': 'current'}, ctx)
            self.assertEqual(recorded.result['status'], 'ok', recorded.result)
            self.assertNotIn('resume_data', recorded.update)
            working = {**state, **recorded.update}
            outcome = await tools.edit_resume(working, {'instruction': INSTRUCTION}, ctx)
        self.assertEqual(outcome.result['status'], 'ok', outcome.result)
        current = {**working, **outcome.update}
        actual = deepcopy(current['resume_data'])
        self.assertEqual(actual['projects'][0]['tech_stack'], EXPECTED)
        actual['projects'][0]['tech_stack'] = project['tech_stack']
        self.assertEqual(stable(actual), stable(before['resume_data']))
        self.assertEqual(state, before)
        old_facts = before['collected_info']['projects'][0]['facts']
        new_facts = current['collected_info']['projects'][0]['facts']
        self.assertEqual(new_facts[:len(old_facts)], old_facts)
        self.assertEqual(new_facts[-1]['text'], 'FastAPI')
        self.assertEqual(new_facts[-1]['source_quote'], INSTRUCTION)
        self.assertEqual(sanitize_fact_history(current)['resume_data'], current['resume_data'])
        self.assertEqual(restore_payload(current)['resume_data'], before['resume_data'])
        iid = project['item_id']
        self.assertEqual(current['resume_meta']['bullets'][iid], before['resume_meta']['bullets'][iid])
        self.assertEqual([row['text_hash'] for row in current['resume_meta']['tech_stack'][iid]],
                         [text_hash(name) for name in EXPECTED])
        # Exercise the canonical save sanitizer too, in the runner's temporary DB.
        from app.database import Base, engine
        from app.services.session_store import save_resume_session, load_resume_session
        Base.metadata.create_all(bind=engine)
        sid = str(uuid4())
        payload = {key: current[key] for key in ('resume_data', 'resume_draft', 'stage', 'collected_info',
                                                'resume_meta', 'resume_versions', 'session_constraints')}
        saved = save_resume_session(sid, **payload)
        self.assertEqual(stable(saved['resume_data']), stable(current['resume_data']))
        self.assertEqual(stable(load_resume_session(sid)['resume_data']), stable(current['resume_data']))

    async def test_ambiguous_record_and_repeated_insufficient_leave_exact_draft(self):
        state = replay_state('给那个项目的技术栈加上 FastAPI，去掉记忆。')
        second = deepcopy(state['resume_data']['projects'][0])
        second.update(item_id=str(uuid4()), name='另一个项目')
        state['resume_data']['projects'].append(second)
        before = deepcopy(state)
        ctx = tools.ToolContext()
        with patch('app.agents.fact_extractor.extract_facts_patch', new=AsyncMock()) as extraction, \
                patch.object(graph, '_persist_intake', new=AsyncMock()) as persist:
            recorded = await tools.record_facts(state, {'source_id': 'current'}, ctx)
            self.assertEqual(recorded.result['status'], 'insufficient')
            self.assertEqual(recorded.update, {})
            for _ in range(2):
                outcome = await tools.edit_resume(state, {'instruction': INSTRUCTION}, ctx)
                self.assertEqual(outcome.result['status'], 'insufficient')
                self.assertEqual(outcome.update, {})
            extraction.assert_not_called()
            persist.assert_not_called()
        self.assertEqual(state, before)
        self.assertEqual(stable(sanitize_fact_history(state)['resume_data']), stable(before['resume_data']))

    async def test_direct_edit_uses_literal_mixed_instruction_not_model_paraphrase(self):
        state = replay_state()
        outcome = await tools.edit_resume(state, {'instruction': '删除所有技术栈'}, tools.ToolContext())
        self.assertEqual(outcome.result['status'], 'ok', outcome.result)
        self.assertEqual(outcome.update['resume_data']['projects'][0]['tech_stack'], EXPECTED)

    async def test_remove_then_add_is_the_same_atomic_edit(self):
        instruction = '给简历 agent 那个项目的技术栈去掉记忆，再加上 FastAPI。'
        state = replay_state(instruction)
        outcome = await tools.edit_resume(state, {'instruction': instruction}, tools.ToolContext())
        self.assertEqual(outcome.result['status'], 'ok', outcome.result)
        self.assertEqual(outcome.update['resume_data']['projects'][0]['tech_stack'], EXPECTED)
        self.assertEqual(outcome.update['resume_data']['projects'][0]['polished_bullets'],
                         state['resume_data']['projects'][0]['polished_bullets'])

    async def test_removal_record_facts_never_deletes_compound_fact(self):
        state = replay_state('给那个项目的技术栈去掉记忆。')
        before = deepcopy(state)
        ctx = tools.ToolContext()
        recorded = await tools.record_facts(state, {'source_id': 'current'}, ctx)
        self.assertEqual(recorded.update, {})
        edited = await tools.edit_resume(state, {'instruction': '去掉记忆'}, ctx)
        self.assertEqual(edited.result['status'], 'ok', edited.result)
        current = {**state, **edited.update}
        self.assertEqual(current['collected_info'], before['collected_info'])
        self.assertEqual(sanitize_fact_history(current)['resume_data']['projects'][0]['polished_bullets'],
                         before['resume_data']['projects'][0]['polished_bullets'])
        self.assertEqual(current['resume_data']['projects'][0]['tech_stack'], ['MCP', 'Tool Calling', 'LangChain'])

    async def test_stack_limit_failure_keeps_all_existing_fields(self):
        state = replay_state('给那个项目的技术栈加上 FastAPI。')
        state['resume_data']['projects'][0]['tech_stack'] += ['A', 'B', 'C', 'D']
        before = deepcopy(state)
        outcome = await tools.edit_resume(state, {'instruction': '加 FastAPI'}, tools.ToolContext())
        self.assertEqual(outcome.result['status'], 'insufficient', outcome.result)
        self.assertEqual(outcome.result['code'], 'tech_stack_limit')
        self.assertEqual(outcome.update, {})
        self.assertEqual(state, before)

    async def test_failed_edit_outcome_cannot_publish_draft_or_metadata(self):
        state = replay_state('润色整个简历')
        failed = tools.ToolOutcome({'status': 'insufficient'}, {'resume_data': {}, 'resume_meta': {}, 'collected_info': {}})
        with patch.object(tools, '_write', new=AsyncMock(return_value=failed)):
            outcome = await tools.edit_resume(state, {'instruction': '润色整个简历'}, tools.ToolContext())
        self.assertEqual(outcome.result['status'], 'insufficient')
        self.assertEqual(outcome.update, {})

    async def test_legacy_mixed_edit_shares_transaction(self):
        state = replay_state()
        outcome = await graph._evaluating_turn_node(state, WriterStub())
        self.assertEqual(outcome['resume_data']['projects'][0]['tech_stack'], EXPECTED)
        self.assertEqual(outcome['resume_data']['projects'][0]['polished_bullets'],
                         state['resume_data']['projects'][0]['polished_bullets'])


class StackTargetAndDeltaTests(unittest.TestCase):
    def test_unique_project_ignores_unrelated_work_item(self):
        state = replay_state()
        for subject in ('那个项目', '简历 agent 那个项目'):
            edit = parse_stack_edit(state['resume_data'], f'给{subject}的技术栈加上 FastAPI，去掉记忆。')
            self.assertEqual(edit['section'], 'projects')
            self.assertEqual(edit['op'], 'update')
            self.assertEqual(edit['names'], ['FastAPI'])
            self.assertEqual(edit['remove_names'], ['记忆'])

    def test_multiple_projects_substring_keywords_and_ambiguity(self):
        data = replay_state()['resume_data']
        data['projects'].append({'item_id': 'other', 'name': '电商后台', 'polished_bullets': ['实现订单查询']})
        for subject in ('简历 agent 那个项目', '帮学生写简历那个项目', '学生简历项目'):
            if subject == '学生简历项目':
                # Semantic terms can come from concrete body text as well.
                data['projects'][0]['description'] = '学生简历项目'
            edit = parse_stack_edit(data, f'给{subject}的技术栈加上 FastAPI')
            self.assertEqual(edit.get('item_id'), data['projects'][0]['item_id'], edit)
        self.assertIn('error', parse_stack_edit(data, '给那个项目的技术栈加上 FastAPI'))
        data['projects'].append({'item_id': 'third', 'name': '简历 agent 另一版'})
        self.assertIn('error', parse_stack_edit(data, INSTRUCTION))

    def test_unknown_removal_does_not_clear_stack(self):
        data = replay_state()['resume_data']
        self.assertIn('error', parse_stack_edit(data, '给那个项目的技术栈去掉 Rust。'))
        self.assertIsNone(parse_stack_edit(data, '删除项目的第二条要点'))
        self.assertEqual(parse_stack_edit(data, '把那个项目的技术栈全部删除')['op'], 'remove')

    def test_delta_keeps_unrelated_names_and_bullet_metadata(self):
        state = replay_state()
        project = state['resume_data']['projects'][0]
        project['tech_stack'].append('Legacy SDK')  # Historic row without fresh source IDs.
        edit = parse_stack_edit(state['resume_data'], '给那个项目的技术栈加上 longchain，去掉记忆。')
        data, meta = apply_stack_edit(state['resume_data'], state['resume_meta'], state['collected_info'], edit)
        self.assertEqual(data['projects'][0]['tech_stack'], ['MCP', 'Tool Calling', 'LangChain', 'Legacy SDK'])
        self.assertEqual(data['projects'][0]['polished_bullets'], project['polished_bullets'])
        self.assertEqual(meta['bullets'], state['resume_meta']['bullets'])

    def test_invalid_addition_does_not_partially_apply_removal(self):
        edit = parse_stack_edit(replay_state()['resume_data'], '给那个项目的技术栈加上一个还没确定的框架，去掉记忆。')
        self.assertIn('error', edit)

    def test_removing_longer_capability_name_keeps_shorter_distinct_name(self):
        data = replay_state()['resume_data']
        data['projects'][0]['tech_stack'].append('长期记忆')
        edit = parse_stack_edit(data, '给那个项目的技术栈去掉长期记忆。')
        self.assertEqual(edit['names'], ['长期记忆'])

    def test_new_experience_prose_still_reaches_normal_fact_intake(self):
        data = replay_state()['resume_data']
        for text in ('另外一个订单项目使用了 Java 和 MySQL 写接口', '新项目使用了 MCP、LangChain'):
            self.assertIsNone(parse_stack_edit(data, text))


class StackProseFixTests(unittest.TestCase):
    def test_live_body_cleanup_preserves_actions_and_is_idempotent(self):
        state = replay_state()
        item, meta = state['resume_data']['projects'][0], state['resume_meta']
        facts = state['collected_info']['projects'][0]['facts']
        project_item_stack(item, facts, meta)
        self.assertEqual(item['polished_bullets'], [
            '负责后端与工具编排，实现根据用户口述直接产出简历初稿',
            '通过 MCP 接入 Claude 使用', '完成一个帮学生写简历的 agent'])
        self.assertEqual(item['tech_stack'], ['MCP', '记忆', 'Tool Calling', 'LangChain'])
        records = meta['bullets'][item['item_id']]
        self.assertEqual([row['text_hash'] for row in records], [text_hash(line) for line in item['polished_bullets']])
        self.assertEqual(valid_bullet_metadata(state['resume_data'], meta)['bullets'][item['item_id']], records)
        coverage = ensure_fact_coverage(state['resume_data'], meta, state['collected_info'])
        list_fact = next(f for f in facts if 'toolcalling' in f['text'])
        self.assertEqual(next(row['status'] for row in coverage['facts'] if row['fact_id'] == list_fact['id']), 'covered')
        self.assertTrue(all(list_fact['id'] not in row['fact_ids'] for row in records))
        before = stable((item, meta))
        project_item_stack(item, facts, meta)
        ensure_fact_coverage(state['resume_data'], meta, state['collected_info'])
        self.assertEqual(stable((item, meta)), before)

    def test_normalization_is_alias_only_and_respects_token_boundaries(self):
        self.assertEqual(normalize_prose('通过 longchain 调用 MCP；toolcalling 编排，NebulaDB 和 longchainX、foo.longchain 保持'),
                         '通过 LangChain 调用 MCP；Tool Calling 编排，NebulaDB 和 longchainX、foo.longchain 保持')
        self.assertEqual(clean_stack_prose('通过 longchain 调用模型', ['LangChain']), '通过 LangChain 调用模型')

    def test_lists_remove_only_when_wholly_covered_and_actions_stay(self):
        for line in ('项目采用 MCP、记忆与 Tool Calling 方案', '项目使用 longchain', '技术栈：mcp, longchain', 'MCP、LangChain'):
            self.assertEqual(clean_stack_prose(line, ['MCP', '记忆', 'Tool Calling', 'LangChain']), '', line)
        for line in ('项目使用 MCP、Rust', '项目使用 MCP, Rust', '项目使用 MCP 实现工具调用',
                     '没有使用 MCP', '计划使用 MCP', '使用 MCP 接入 Claude', '负责记忆模块开发'):
            self.assertEqual(clean_stack_prose(line, ['MCP']), line)
        self.assertEqual(clean_stack_prose('项目使用 longchain，并通过 MCP 接入 Claude。', ['LangChain', 'MCP']),
                         '通过 MCP 接入 Claude。')
        self.assertEqual(clean_stack_prose('项目使用 longchain', []), '项目使用 LangChain')

    def test_whole_list_bullet_removes_corresponding_metadata_and_coverage(self):
        item = {'item_id': 'p', 'polished_bullets': ['项目使用 longchain', '通过 longchain 接入工具'],
                'description': '技术栈：longchain\n通过 longchain 接入工具'}
        facts = [{'id': 'list', 'text': '项目使用 longchain', 'source_quote': '项目使用 longchain', 'status': 'active'},
                 {'id': 'action', 'text': '通过 longchain 接入工具', 'source_quote': '通过 longchain 接入工具', 'status': 'active'}]
        meta = {'bullets': {'p': [{'text_hash': text_hash(line), 'fact_ids': [fid], 'coverage_fact_ids': [fid]}
                                for line, fid in zip(item['polished_bullets'], ('list', 'action'))]}}
        project_item_stack(item, facts, meta)
        self.assertEqual(item['polished_bullets'], ['通过 LangChain 接入工具'])
        self.assertEqual(item['description'], '通过 LangChain 接入工具')
        self.assertEqual(meta['bullets']['p'][0]['coverage_fact_ids'], ['action'])
        self.assertEqual(meta['bullets']['p'][0]['fact_ids'], ['action'])

    def test_work_prose_uses_same_cleanup(self):
        item = {'item_id': 'w', 'bullets': ['项目采用 java、mysql，开发订单查询接口']}
        facts = [{'id': 'f', 'text': '技术栈：Java、MySQL', 'source_quote': '技术栈：Java、MySQL'}]
        project_item_stack(item, facts, {})
        self.assertEqual(item['bullets'], ['开发订单查询接口'])
        self.assertEqual(item['tech_stack'], ['Java', 'MySQL'])

    def test_compound_fact_coverage_requires_both_stack_and_cited_action(self):
        line = '项目使用 longchain，开发订单接口'
        facts = [{'id': 'compound', 'text': line, 'source_quote': line, 'status': 'active', 'kind': 'action'}]
        item = {'item_id': 'p', 'name': '接口项目', 'polished_bullets': [line]}
        meta = {'bullets': {'p': [{'text_hash': text_hash(line), 'fact_ids': ['compound'],
                                  'coverage_fact_ids': ['compound']}]}}
        project_item_stack(item, facts, meta)
        data, collected = {'projects': [item]}, {'projects': [{'item_id': 'p', 'name': '接口项目', 'facts': facts}]}
        self.assertEqual(item['polished_bullets'], ['开发订单接口'])
        self.assertEqual(meta['bullets']['p'][0]['coverage_fact_ids'], [])
        report = ensure_fact_coverage(data, meta, collected)
        self.assertEqual(report['facts'][0]['status'], 'covered')
        item['polished_bullets'] = []
        report = ensure_fact_coverage(data, meta, collected)
        self.assertEqual(report['facts'][0]['status'], 'omitted')


class StackToolTruthTests(unittest.IsolatedAsyncioTestCase):
    async def test_bullet_rewrite_cleans_only_requested_line(self):
        from app.agents.resume_writer import run_resume_writer
        state, data = collected(), document()
        item = data['projects'][0]
        item['tech_stack'] = ['LangChain']
        item['polished_bullets'] = ['待改写', '项目使用 longchain，保留这一条原文']
        state['projects'][0]['facts'][0].update(text='使用 longchain，并实现工具编排',
                                              source_quote='使用 longchain，并实现工具编排')
        result = await run_resume_writer(state, {'role_family': 'backend'}, WriterStub(),
            current_data=data, scope='bullet', targets=['/projects/0/polished_bullets/0'])
        written = result['resume_data']['projects'][0]
        self.assertEqual(written['polished_bullets'][0], '实现工具编排')
        self.assertEqual(written['polished_bullets'][1], item['polished_bullets'][1])
        self.assertEqual(written['tech_stack'], ['LangChain'])

    async def test_canonical_alias_not_reported_as_unsupported_tool(self):
        facts = [{'id': 'f', 'item_id': 'p', 'text': '使用 longchain 编排工具',
                  'source_quote': '使用 longchain 编排工具', 'status': 'active'}]
        result = await guard_bullets([{'id': 'b', 'item_id': 'p', 'text': '使用 LangChain 编排工具', 'fact_ids': ['f']}],
                                    facts, lexical_only=True)
        self.assertEqual(result[0]['verdict'], 'pass', result)
        for quote in ('没用 longchain', '计划使用 longchain', '使用 longchainX'):
            facts[0]['source_quote'] = quote
            checked = await guard_bullets([{'id': 'b', 'item_id': 'p', 'text': '使用 LangChain 编排工具', 'fact_ids': ['f']}],
                                         facts, lexical_only=True)
            self.assertIn('unsupported_tool:LangChain', checked[0]['lexical_errors'])

    async def test_receipt_and_compact_model_context_include_actual_stack(self):
        state = replay_state()
        outcome = tools._document_outcome({**state, 'changed': True})
        projected = project_tool_result('write_draft', outcome.result, ContactRedactor())
        self.assertIn('LangChain', projected['tech_stack_receipt'][0]['tech_stack'])
        self.assertIn('写入技术栈', projected['tech_stack_receipt'][0]['message'])
        item = projected['resume_data']['items'][0]
        self.assertEqual(item['tech_stack'], ['MCP', '记忆', 'Tool Calling', 'LangChain'])
        self.assertEqual(item['point_count'], 3)
