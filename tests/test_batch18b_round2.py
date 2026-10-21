"""Run2 synthetic SQL/checkpoint replay; all model responses are offline doubles."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]
from langchain_core.messages import HumanMessage  # noqa: E402
from app.agents import orchestrator_tools as tools  # noqa: E402
from app.agents.orchestrator_context import project_tool_result  # noqa: E402
from app.services.fact_coverage import ensure_fact_coverage  # noqa: E402
from app.services.model_privacy import ContactRedactor  # noqa: E402
from app.services.resume_versions import prepare_version, text_hash  # noqa: E402
from app.services.tech_stack import clean_stack_prose, project_item_stack  # noqa: E402
from test_fact_guard import decision  # noqa: E402

FIXTURE = json.loads((ROOT / 'tests/fixtures/batch18b_run2.json').read_text())
FEATURE = '能根据用户口述直接出简历初稿'
STACK = ['MCP', '记忆', 'Tool Calling', 'LangChain']


def second_turn():
    state = deepcopy(FIXTURE['first_draft'])
    state['collected_info'] = deepcopy(FIXTURE['second_turn']['collected_info'])
    state['messages'] = [HumanMessage(content=FIXTURE['second_turn']['instruction'])]
    return state


def measured(*args, **kwargs):
    return {'status': 'rendered', 'pages': 1, 'within_page_limit': True}


class Run2Writer:
    """Replay the observed first draft, including its overcitation and omission."""
    def __init__(self):
        self.calls = []

    def with_structured_output(self, schema):
        async def invoke(messages):
            payload = json.loads(messages[-1].content)
            self.calls.append(schema.__name__)
            if schema.__name__ in {'OnePassOutput', 'WriterDraft'}:
                state = FIXTURE['first_draft']
                project = state['resume_data']['projects'][0]
                records = state['resume_meta']['bullets'][project['item_id']]
                writer = {'items': [{'item_id': project['item_id'], 'section': 'projects',
                    'tech_stack': STACK, 'tech_stack_fact_ids': [f['id'] for f in state['collected_info']['projects'][0]['facts']],
                    'bullets': [{'text': line, 'fact_ids': row['fact_ids']}
                                for line, row in zip(project['polished_bullets'], records)]}]}
                return {'match_plan': state['confirmed_plan'], 'writer': writer} if schema.__name__ == 'OnePassOutput' else writer
            if schema.__name__ == 'SemanticBatch':
                # Do not turn a citation to the missing feature into proof of coverage.
                return {'decisions': [decision(row['id'], not ('口述' in row['text']
                    and not any('口述' in s for s in row['source_quotes']))) for row in payload]}
            if schema.__name__ == 'RepairOutput':
                return {'bullets': []}
            raise AssertionError(schema.__name__)
        return SimpleNamespace(ainvoke=invoke)


class Run2AdditionTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_new_internship_cannot_report_success_or_modify_old_draft(self):
        state = second_turn()
        before = deepcopy(state)
        with patch.object(tools, '_write', new=AsyncMock(side_effect=AssertionError('must redirect'))) as writer:
            result = await tools.edit_resume(state, {'instruction': FIXTURE['second_turn']['instruction']}, tools.ToolContext())
        self.assertEqual(result.result['status'], 'insufficient', result.result)
        self.assertEqual(result.result['next_tool'], 'write_draft')
        self.assertEqual(result.result['pending_experiences'], [{'section': '工作经历', 'name': '一家电商公司'}])
        self.assertEqual(result.update, {})
        self.assertEqual(state, before)
        writer.assert_not_awaited()

    async def test_existing_project_name_in_add_request_cannot_mask_new_internship(self):
        state = second_turn()
        result = await tools.edit_resume(state, {'instruction': '加入实习，保留帮学生写简历的 agent'}, tools.ToolContext())
        self.assertEqual(result.result['code'], 'new_experience_requires_write_draft')
        self.assertEqual(result.update, {})

    async def test_unrelated_old_backup_does_not_block_edit(self):
        state = second_turn()
        state['messages'] = [HumanMessage(content='润色帮学生写简历的 agent')]
        with patch.object(tools, '_write', new=AsyncMock(return_value=tools.ToolOutcome({'status': 'unchanged'}))) as writer:
            outcome = await tools.edit_resume(state, {'instruction': '润色帮学生写简历的 agent'}, tools.ToolContext())
        writer.assert_awaited_once()
        self.assertEqual(outcome.result['status'], 'unchanged')

    async def test_named_pending_entry_redirects_on_later_turn(self):
        state = second_turn()
        state['messages'] = [HumanMessage(content='把一家电商公司写进简历')]
        outcome = await tools.edit_resume(state, {'instruction': '把一家电商公司写进简历'}, tools.ToolContext())
        self.assertEqual(outcome.result['next_tool'], 'write_draft')

    async def test_success_with_no_actual_diff_is_unchanged(self):
        state = deepcopy(FIXTURE['first_draft'])
        state['messages'] = [HumanMessage(content='润色整个简历')]
        fake = tools.ToolOutcome({'status': 'ok', 'changed': True, 'change_summary': ['新增了实习']},
                                 {'resume_data': deepcopy(state['resume_data']), 'resume_meta': deepcopy(state['resume_meta'])})
        with patch.object(tools, '_write', new=AsyncMock(return_value=fake)):
            outcome = await tools.edit_resume(state, {'instruction': '润色整个简历'}, tools.ToolContext())
        self.assertEqual(outcome.result['status'], 'unchanged')
        self.assertFalse(outcome.result['changed'])
        self.assertEqual(outcome.result['document_changes'], [])
        self.assertEqual(outcome.result['change_summary'], [])

    def test_added_item_receipt_comes_from_actual_document(self):
        state = deepcopy(FIXTURE['first_draft'])
        after = deepcopy(state['resume_data'])
        after['work_experience'] = [{'item_id': 'new', 'company': '一家电商公司', 'bullets': ['开发订单查询接口']}]
        outcome = tools.ToolOutcome({'status': 'ok', 'change_summary': ['模型说改了项目']}, {'resume_data': after})
        tools._edit_diff_receipt(state, outcome)
        self.assertEqual(outcome.result['document_changes'], [{'action': '新增', 'section': '工作经历', 'name': '一家电商公司'}])
        self.assertEqual(outcome.result['change_summary'], ['新增工作经历「一家电商公司」'])

    async def test_real_stack_edit_retains_round1_no_data_loss(self):
        state = second_turn()
        state.update(deepcopy(FIXTURE['second_draft']))
        state['messages'] = [HumanMessage(content='给简历 agent 那个项目的技术栈加上 FastAPI，去掉记忆。')]
        with patch('app.services.resume_capacity.measure_rendered_pages', side_effect=measured):
            outcome = await tools.edit_resume(state, {'instruction': state['messages'][0].content}, tools.ToolContext())
        self.assertEqual(outcome.result['status'], 'ok', outcome.result)
        item = outcome.update['resume_data']['projects'][0]
        self.assertEqual(item['tech_stack'], ['MCP', 'Tool Calling', 'LangChain', 'FastAPI'])
        self.assertEqual(item['polished_bullets'], state['resume_data']['projects'][0]['polished_bullets'])
        self.assertEqual(outcome.result['document_changes'][0]['action'], '修改')


class Run2ProseTests(unittest.TestCase):
    def test_first_draft_exact_live_strings_and_coverage(self):
        state = deepcopy(FIXTURE['first_draft'])
        item = state['resume_data']['projects'][0]
        project_item_stack(item, state['collected_info']['projects'][0]['facts'], state['resume_meta'])
        self.assertEqual(item['polished_bullets'], ['负责帮学生写简历 agent 的后端与工具编排', '通过 MCP 接入 Claude 使用'])
        report = ensure_fact_coverage(state['resume_data'], state['resume_meta'], state['collected_info'])
        self.assertEqual(next(f for f in report['facts'] if f['text'] == FEATURE)['status'], 'omitted')
        rows = state['resume_meta']['bullets'][item['item_id']]
        self.assertEqual([r['text_hash'] for r in rows], [text_hash(s) for s in item['polished_bullets']])
        before = deepcopy(state)
        project_item_stack(item, state['collected_info']['projects'][0]['facts'], state['resume_meta'])
        self.assertEqual(state, before)

    def test_conjunctions_after_removed_list(self):
        for prefix in ('并', '并且', '且', '同时', '以及', '还', '，并', '，、并且', '，', '、'):
            with self.subTest(prefix=prefix):
                text = '项目使用 MCP、记忆、Tool Calling 与 LangChain' + prefix + '可通过 MCP 接入 Claude 使用'
                self.assertEqual(clean_stack_prose(text, STACK), '通过 MCP 接入 Claude 使用')

    def test_vague_agent_capability_is_list_but_specific_work_survives(self):
        self.assertEqual(clean_stack_prose('项目采用 MCP、记忆、Tool Calling 与 LangChain 搭建 agent 能力', STACK), '')
        for text in ('项目采用 MCP、记忆、Tool Calling 与 LangChain 搭建订单查询服务',
                     '使用 Java 和 MySQL 开发订单查询接口', '通过 MCP 接入 Claude 使用',
                     '并发处理订单请求', '还原用户会话', '同时性检查'):
            self.assertEqual(clean_stack_prose(text, STACK + ['Java', 'MySQL']), text)

    def test_incomplete_stack_does_not_erase_uncopied_technology(self):
        text = '项目使用 MCP、Rust，并可通过 MCP 接入 Claude 使用'
        self.assertEqual(clean_stack_prose(text, STACK), text)

    def test_live_second_draft_origin_cleaned_without_dangling_conjunction(self):
        original = FIXTURE['first_draft']['resume_data']['projects'][0]['polished_bullets'][1]
        self.assertEqual(clean_stack_prose(original, STACK), '通过 MCP 接入 Claude 使用')
        self.assertEqual(FIXTURE['second_draft']['resume_data']['projects'][0]['polished_bullets'][1],
                         '并可通过 MCP 接入 Claude 使用')


class Run2ToolPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_draft_real_pipeline_cleans_and_restores_missing_feature(self):
        state = deepcopy(FIXTURE['first_draft'])
        state.update(resume_data={}, resume_meta={}, resume_versions=[], stage='COLLECTING',
                     messages=[HumanMessage(content=FIXTURE['first_instruction'])])
        model = Run2Writer()
        with patch('app.agents.tailor_pipeline.measure_rendered_pages', side_effect=measured), \
             patch('app.services.resume_capacity.measure_rendered_pages', side_effect=measured):
            outcome = await tools.write_draft(state, {}, tools.ToolContext(llm=model))
        self.assertEqual(outcome.result['status'], 'ok', outcome.result)
        item = outcome.update['resume_data']['projects'][0]
        self.assertEqual(item['tech_stack'], STACK)
        self.assertFalse(any('项目使用' in s or '搭建 agent 能力' in s or s.startswith('并') for s in item['polished_bullets']), item)
        self.assertIn(FEATURE, item['polished_bullets'])
        coverage = outcome.update['resume_meta']['fact_coverage']
        self.assertEqual(next(f for f in coverage['facts'] if f['text'] == FEATURE)['status'], 'covered')
        self.assertIn('WriterDraft', model.calls)
        # Snapshot creation must retain the cleaned first draft.
        version = prepare_version(outcome.update['resume_data'], outcome.update['resume_meta'], [],
                                  {**outcome.update['resume_data'], 'summary': '后续修改'}, outcome.update['resume_meta'])
        self.assertEqual(version['resume_versions'][0]['resume_data']['projects'][0], item)

    def test_unrepaired_live_omission_is_visible_in_compact_tool_receipt(self):
        outcome = tools._document_outcome({**deepcopy(FIXTURE['first_draft']), 'changed': True})
        self.assertTrue(any(f['text'] == FEATURE for f in outcome.result['uncovered_facts']))
        projected = project_tool_result('write_draft', outcome.result, ContactRedactor())
        self.assertIn(FEATURE, json.dumps(projected, ensure_ascii=False))

    async def test_missing_layout_library_is_explicit_and_leaves_no_updates(self):
        with patch('app.services.resume_pdf.measure_resume_pdf_layout', side_effect=OSError('private path')):
            outcome = await tools.check_layout(FIXTURE['first_draft'], {}, tools.ToolContext())
        self.assertEqual(outcome.result['code'], 'layout_renderer_unavailable')
        self.assertEqual(outcome.update, {})
        self.assertNotIn('private path', json.dumps(outcome.result))

    async def test_layout_of_run2_with_installed_libraries(self):
        state = {**deepcopy(FIXTURE['first_draft']), **deepcopy(FIXTURE['final_draft'])}
        outcome = await tools.check_layout(state, {}, tools.ToolContext())
        self.assertEqual(outcome.result['status'], 'ok', outcome.result)
        self.assertGreaterEqual(outcome.result['page_check']['pages'], 1)
        self.assertNotIn('resume_data', outcome.update)
