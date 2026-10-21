"""Flow loading, SDK protocol, prompts and scoped deletion; no live providers."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from langchain_core.messages import HumanMessage
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]
from app.agents import orchestrator as loop, orchestrator_tools as tools  # noqa: E402
from app.agents.flow_skills import FLOW_SKILLS, load_flow_skills, skill_catalog  # noqa: E402
from app.agents.career_prompt import load_skill  # noqa: E402
from app.agents.orchestrator_context import project_tool_result  # noqa: E402
from app.services.model_privacy import ContactRedactor  # noqa: E402
from app.services.resume_versions import text_hash, valid_bullet_metadata  # noqa: E402
from app.services.tech_stack import apply_stack_edit, parse_stack_edit, remove_stack_mentions  # noqa: E402
from test_orchestrator import state  # noqa: E402
from test_orchestrator_tools import measured  # noqa: E402
from test_batch18b import WriterStub, collected, document  # noqa: E402
from test_batch18b_fixes import replay_state  # noqa: E402
from test_batch18b_round2 import second_turn  # noqa: E402


class FlowCatalogTests(unittest.TestCase):
    def parse(self, contents):
        with TemporaryDirectory() as directory:
            for filename, content in contents.items():
                (Path(directory) / filename).write_text(content)
            return load_flow_skills(Path(directory))

    def test_frontmatter_yaml_and_sort_by_name_not_filename(self):
        result = self.parse({'a.md': '---\nname: z\ntitle: "标题: Z"\nwhen: >-\n  场景一\n  场景二\n---\n正文 Z',
                             'z.md': '---\nname: a\ntitle: A\nwhen: 场景\n---\n正文 A'})
        self.assertEqual(list(result), ['a', 'z'])
        self.assertEqual(result['z'].title, '标题: Z')
        self.assertEqual(result['z'].when, '场景一 场景二')
        self.assertEqual(skill_catalog(result).splitlines()[1:3], ['a：A——场景', 'z：标题: Z——场景一 场景二'])

    def test_missing_each_required_field_fails_with_filename_and_field(self):
        fields = {'name': 'flow', 'title': '标题', 'when': '场景'}
        for missing in fields:
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, f'bad.md:.*{missing}'):
                self.parse({'bad.md': '---\n' + '\n'.join(f'{k}: {v}' for k, v in fields.items() if k != missing) + '\n---\n正文'})

    def test_invalid_frontmatter_and_empty_body_fail(self):
        for text in ('正文', '---\nname: x', '---\n[broken\n---\n正文',
                     '---\nname: x\ntitle: false\nwhen: 条件\n---\n正文',
                     '---\nname: x\ntitle: X\nwhen: 条件\n---\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'bad.md:'):
                self.parse({'bad.md': text})

    def test_duplicate_name_fails(self):
        text = '---\nname: x\ntitle: X\nwhen: 条件\n---\n正文'
        with self.assertRaisesRegex(ValueError, 'duplicate skill name'):
            self.parse({'a.md': text, 'b.md': text})

    def test_empty_directory_fails(self):
        with self.assertRaisesRegex(ValueError, 'no flow skills'):
            self.parse({})

    def test_catalog_is_generated_and_schema_matches(self):
        self.assertTrue(loop.SYSTEM_PROMPT.endswith(skill_catalog(FLOW_SKILLS)))
        self.assertEqual(tools.SkillArgs.model_json_schema()['properties']['name']['enum'], list(FLOW_SKILLS))
        self.assertEqual(len(FLOW_SKILLS), 5)
        self.assertIn('本轮第一步与第一个工具同时调用 use_skill(name)', loop.SYSTEM_PROMPT)


class SkillToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_body_without_frontmatter_or_data_sanitization(self):
        for name, skill in FLOW_SKILLS.items():
            outcome = await tools.use_skill({}, {'name': name}, tools.ToolContext())
            self.assertEqual(outcome.result['body'], skill.body)
            self.assertNotIn('---\nname:', outcome.result['body'])
            self.assertEqual(outcome.update, {})
            self.assertIn('正在查看做法', outcome.events[0]['message'])

    async def test_unknown_and_path_names_are_rejected(self):
        for name in ('unknown', '../resume-write/SKILL', '/tmp/flow'):
            ctx = tools.ToolContext()
            outcome = await tools.execute_tool('use_skill', {}, {'name': name}, ctx)
            self.assertEqual(outcome.result['code'], 'invalid_arguments')
            self.assertEqual(ctx.loaded_skills, [])

    async def test_duplicate_load_is_short_and_next_turn_is_fresh(self):
        ctx = tools.ToolContext()
        await tools.use_skill({}, {'name': 'tech-stack'}, ctx)
        again = await tools.use_skill({}, {'name': 'tech-stack'}, ctx)
        self.assertEqual(again.result, {'status': 'ok', 'name': 'tech-stack', 'message': '已加载'})
        self.assertEqual(ctx.loaded_skills, ['tech-stack'])
        fresh = await tools.use_skill({}, {'name': 'tech-stack'}, tools.ToolContext())
        self.assertIn('body', fresh.result)


class SDKFlowTests(unittest.IsolatedAsyncioTestCase):
    async def run_script(self, script, *, registry=None, value=None):
        requests, events = [], []
        def transport(request):
            body = json.loads(request.content)
            index = len(requests)
            requests.append(body)
            entry = script[index]
            calls = entry if isinstance(entry, list) else []
            delta = {'reasoning_content': '离线推理', 'content': '' if calls else entry}
            if calls:
                delta['tool_calls'] = [{'index': i, 'id': f'c{index}-{i}', 'type': 'function',
                    'function': {'name': name, 'arguments': json.dumps(args)}} for i, (name, args) in enumerate(calls)]
            frames = [{'choices': [{'index': 0, 'delta': delta}]}, {'choices': [{'index': 0, 'delta': {},
                'finish_reason': 'tool_calls' if calls else 'stop'}]}]
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=''.join(
                f'data: {json.dumps(frame)}\n\n' for frame in frames) + 'data: [DONE]\n\n')
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            async with AsyncOpenAI(api_key='offline', base_url='https://model.invalid/v1', http_client=http, max_retries=0) as client:
                registry = registry or tools.TOOLS
                model = loop.OrchestratorModel(client, model='fixture', schemas=loop._schemas(registry))
                with self.assertLogs(loop.logger, level='INFO') as logs:
                    result = await loop.run_orchestrator(value or state(), model, registry=registry, emit=events.append)
        metrics = result['messages'][-1].additional_kwargs['orchestrator']
        logged = json.loads(next(row.split('orchestrator_turn ', 1)[1] for row in logs.output if 'orchestrator_turn ' in row))
        self.assertEqual(logged['skills'], metrics['skills'])
        self.assertEqual(len(requests), metrics['model_calls'])
        return result, requests, events, metrics

    async def test_skill_and_record_same_request_return_both_without_extra_call(self):
        async def record(value, args, ctx):
            self.assertEqual(ctx.loaded_skills, ['add-experience'])
            return tools.ToolOutcome({'status': 'ok'}, {'collected_info': {'projects': []}})
        registry = {**tools.TOOLS, 'record_facts': replace(tools.TOOLS['record_facts'], handler=record)}
        _, requests, events, metrics = await self.run_script([
            [('record_facts', {'source_id': 'current'}), ('use_skill', {'name': 'add-experience'})], '已记录。'], registry=registry)
        self.assertTrue(requests[0]['parallel_tool_calls'])
        results = {m['tool_call_id']: json.loads(m['content']) for m in requests[1]['messages'] if m['role'] == 'tool'}
        self.assertEqual(set(results), {'c0-0', 'c0-1'})
        self.assertEqual(results['c0-1']['body'], FLOW_SKILLS['add-experience'].body)
        self.assertNotIn('untrusted_data', results['c0-1'])
        self.assertEqual(results['c0-0']['untrusted_data']['status'], 'ok')
        self.assertEqual((metrics['model_calls'], metrics['tool_steps']), (2, 1))
        self.assertEqual([row['name'] for row in metrics['tools']], ['record_facts'])
        self.assertTrue(any(e.get('tool') == 'use_skill' and e.get('message') == '正在查看做法…' for e in events))

    async def test_four_real_tools_plus_skill_keep_budget_and_final_call(self):
        check = AsyncMock(return_value=tools.ToolOutcome({'status': 'ok'}))
        registry = {**tools.TOOLS, 'check_layout': replace(tools.TOOLS['check_layout'], handler=check)}
        _, requests, _, metrics = await self.run_script([
            [('check_layout', {}), ('use_skill', {'name': 'one-page'})],
            *[[('check_layout', {})] for _ in range(3)], '已核对。'], registry=registry)
        self.assertEqual((metrics['model_calls'], metrics['tool_steps']), (5, 4))
        self.assertEqual(check.await_count, 4)
        self.assertEqual(requests[-1]['tool_choice'], 'none')

    async def test_skill_only_calls_use_model_budget_and_duplicate_body_once(self):
        _, requests, _, metrics = await self.run_script([
            *[[('use_skill', {'name': 'tech-stack'})] for _ in range(4)], '已查看。'])
        self.assertEqual((metrics['model_calls'], metrics['tool_steps']), (5, 0))
        self.assertEqual(metrics['tools'], [])
        self.assertEqual(metrics['skills'], ['tech-stack'])
        results = [json.loads(m['content']) for m in requests[-1]['messages'] if m['role'] == 'tool']
        self.assertEqual(sum('body' in row for row in results), 1)
        self.assertEqual(results[-1]['message'], '已加载')

    async def test_next_turn_does_not_reuse_tools_or_skills_from_history(self):
        first, _, _, _ = await self.run_script([[('use_skill', {'name': 'tech-stack'})], '已查看。'])
        value = state()
        value['messages'] += first['messages'] + [HumanMessage(content='继续修改', id='next')]
        _, requests, _, metrics = await self.run_script([[('use_skill', {'name': 'tech-stack'})], '已查看。'], value=value)
        self.assertFalse(any(m['role'] == 'tool' for m in requests[0]['messages']))
        self.assertIn('body', json.loads(requests[1]['messages'][-1]['content']))
        self.assertEqual(metrics['skills'], ['tech-stack'])

    async def test_unknown_skill_does_not_consume_tools_or_appear_in_metrics(self):
        _, requests, _, metrics = await self.run_script([[('use_skill', {'name': 'missing'})], '未加载。'])
        self.assertEqual(json.loads(requests[1]['messages'][-1]['content'])['code'], 'invalid_arguments')
        self.assertEqual((metrics['tool_steps'], metrics['skills']), (0, []))


class HintAndDeletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch('app.services.resume_capacity.measure_rendered_pages', side_effect=measured))
        self.enterContext(patch('app.agents.tailor_pipeline.measure_rendered_pages', side_effect=measured))

    async def test_new_experience_hint_only_when_skill_not_loaded(self):
        for loaded in (False, True):
            value, ctx = second_turn(), tools.ToolContext()
            if loaded:
                await tools.use_skill(value, {'name': 'add-experience'}, ctx)
            outcome = await tools.edit_resume(value, {'instruction': value['messages'][-1].content}, ctx)
            self.assertEqual(outcome.result['code'], 'new_experience_requires_write_draft')
            self.assertEqual('hint' in outcome.result, not loaded)
            self.assertEqual(outcome.update, {})

    async def test_stack_hint_success_error_and_loaded(self):
        for instruction in ('给那个项目的技术栈去掉记忆。', '给那个项目的技术栈去掉 Rust。'):
            for loaded in (False, True):
                value, ctx = replay_state(instruction), tools.ToolContext()
                if loaded:
                    await tools.use_skill(value, {'name': 'tech-stack'}, ctx)
                outcome = await tools.edit_resume(value, {'instruction': instruction}, ctx)
                self.assertEqual('hint' in outcome.result, not loaded)
                if not loaded:
                    self.assertEqual(project_tool_result('edit_resume', outcome.result, ContactRedactor())['hint'],
                                     "先 use_skill('tech-stack')")

    async def test_unrelated_edit_has_no_hint(self):
        value = replay_state('润色整个简历')
        with patch.object(tools, '_write', new=AsyncMock(return_value=tools.ToolOutcome({'status': 'unchanged'}))):
            outcome = await tools.edit_resume(value, {'instruction': '润色整个简历'}, tools.ToolContext())
        self.assertNotIn('hint', outcome.result)

    async def test_exact_live_removal_syncs_bullets_hashes_and_is_idempotent(self):
        value = replay_state('给那个项目的技术栈去掉记忆。')
        before = deepcopy(value)
        first = await tools.edit_resume(value, {'instruction': value['messages'][-1].content}, tools.ToolContext())
        item = first.update['resume_data']['projects'][0]
        self.assertNotIn('记忆', ''.join(item['polished_bullets']))
        self.assertEqual(item['polished_bullets'][0], before['resume_data']['projects'][0]['polished_bullets'][0].replace('MCP、记忆与', 'MCP 与'))
        self.assertEqual(item['polished_bullets'][1:], before['resume_data']['projects'][0]['polished_bullets'][1:])
        meta = first.update['resume_meta']
        self.assertEqual(meta['bullets'][item['item_id']][0]['text_hash'], text_hash(item['polished_bullets'][0]))
        self.assertEqual(valid_bullet_metadata(first.update['resume_data'], meta)['bullets'], meta['bullets'])
        self.assertEqual(first.result['tech_stack_body_receipt'][0]['removed'], ['记忆'])
        current = {**value, **first.update}
        again = await tools.edit_resume(current, {'instruction': value['messages'][-1].content}, tools.ToolContext())
        self.assertEqual(again.result['status'], 'unchanged', again.result)
        self.assertEqual(again.update['resume_data'], first.update['resume_data'])
        self.assertEqual(again.update['resume_versions'], first.update['resume_versions'])
        self.assertEqual(again.update['version_id'], first.update['version_id'])
        self.assertEqual(value, before)

    async def test_sole_technology_is_retained_with_receipt(self):
        value = replay_state('给那个项目的技术栈去掉记忆。')
        item = value['resume_data']['projects'][0]
        item['polished_bullets'] = ['基于记忆搭建问答服务']
        outcome = await tools.edit_resume(value, {'instruction': '去掉记忆'}, tools.ToolContext())
        self.assertEqual(outcome.update['resume_data']['projects'][0]['polished_bullets'], item['polished_bullets'])
        self.assertEqual(outcome.result['tech_stack_body_receipt'][0]['retained'], ['记忆'])
        self.assertIn('唯一技术', outcome.result['tech_stack_body_receipt'][0]['message'])

    def test_list_member_positions_aliases_and_multiple_removals(self):
        cases = [
            ('基于 MCP、记忆与 Tool Calling 搭建问答服务', ['MCP', '记忆', 'Tool Calling'], {'记忆'}, '基于 MCP 与 Tool Calling 搭建问答服务'),
            ('用 Java、MySQL、Redis 开发服务', ['Java', 'MySQL', 'Redis'], {'java'}, '用 MySQL、Redis 开发服务'),
            ('使用 Java、MySQL、Redis 开发服务', ['Java', 'MySQL', 'Redis'], {'redis'}, '使用 Java、MySQL 开发服务'),
            ('基于 MCP、记忆与 Tool Calling 搭建服务', ['MCP', '记忆', 'Tool Calling'], {'mcp', '记忆'}, '基于 Tool Calling 搭建服务'),
            ('使用 longchain 与 MCP 接入模型', ['LangChain', 'MCP'], {'langchain'}, '使用 MCP 接入模型'),
        ]
        for text, stack, removed, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(remove_stack_mentions(text, stack, removed), expected)
                self.assertEqual(remove_stack_mentions(expected, stack, removed), expected)

    def test_unsafe_or_non_list_mentions_stay_verbatim(self):
        for text in ('基于记忆搭建服务', '负责记忆模块开发', '帮助用户记忆单词',
                     '对比 MCP 与记忆的差异', '基于 MCP 与记忆之间的依赖实现协作',
                     '基于长期记忆与 MCP 搭建服务'):
            self.assertEqual(remove_stack_mentions(text, ['记忆', 'MCP', '长期记忆'], {'记忆'}), text)
        self.assertEqual(remove_stack_mentions('使用 MCP 与记忆开发服务', ['MCP', '记忆'], {'mcp', '记忆'}), '使用 MCP 与记忆开发服务')

    def test_work_bullets_and_citations_drop_removed_only_fact_not_actions(self):
        value = replay_state()
        line = '基于 MCP、记忆与 Tool Calling 搭建接口'
        item = {'item_id': 'work', 'company': '公司', 'tech_stack': ['MCP', '记忆', 'Tool Calling'], 'bullets': [line]}
        facts = [{'id': 'only', 'text': '记忆'}, {'id': 'action', 'text': line}]
        data = {'work_experience': [item]}
        meta = {'bullets': {'work': [{'text_hash': text_hash(line), 'fact_ids': ['only', 'action'], 'coverage_fact_ids': ['only', 'action']}]}}
        edit = parse_stack_edit(data, '给公司的技术栈去掉记忆')
        output, updated = apply_stack_edit(data, meta, {'work_experience': [{'item_id': 'work', 'facts': facts}]}, edit)
        self.assertEqual(output['work_experience'][0]['bullets'], ['基于 MCP 与 Tool Calling 搭建接口'])
        self.assertEqual(updated['bullets']['work'][0]['fact_ids'], ['action'])
        self.assertEqual(updated['bullets']['work'][0]['coverage_fact_ids'], [])
        self.assertEqual(value['resume_data'], replay_state()['resume_data'])

    def test_stale_hash_is_not_rebound_to_new_text(self):
        value = replay_state()
        item = value['resume_data']['projects'][0]
        value['resume_meta']['bullets'][item['item_id']][0]['text_hash'] = 'stale'
        edit = parse_stack_edit(value['resume_data'], '给那个项目的技术栈去掉记忆')
        _, meta = apply_stack_edit(value['resume_data'], value['resume_meta'], value['collected_info'], edit)
        self.assertEqual(meta['bullets'][item['item_id']][0], {})


class WriterPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_loop_writing_tools_receive_resume_write_rules(self):
        prompts = []
        class CaptureWriter(WriterStub):
            def with_structured_output(self, schema):
                wrapped = super().with_structured_output(schema)
                async def invoke(messages):
                    if schema.__name__ in {'OnePassOutput', 'WriterDraft'}:
                        prompts.append(messages[0].content)
                    return await wrapped.ainvoke(messages)
                return SimpleNamespace(ainvoke=invoke)
        with patch('app.services.resume_capacity.measure_rendered_pages', side_effect=measured), \
                patch('app.agents.tailor_pipeline.measure_rendered_pages', side_effect=measured):
            for tool in ('write_draft', 'edit_resume'):
                prompts.clear()
                value = state('润色整个简历', collected_info=collected(), resume_data=document())
                outcome = await tools.execute_tool(tool, value, {'instruction': '润色整个简历'} if tool == 'edit_resume' else {},
                                                   tools.ToolContext(llm=CaptureWriter()))
                self.assertIn(outcome.result['status'], ('ok', 'partial', 'unchanged'), outcome.result)
                self.assertTrue(prompts, tool)
                for prompt in prompts:
                    self.assertIn(load_skill('resume-write'), prompt)
                    for rule in ('技术栈单独成行', '不加空话尾巴', '重写不丢已写内容'):
                        self.assertIn(rule, prompt)


class StackSuffixListingTests(unittest.TestCase):
    def test_listing_ending_with_stack_word_is_removed_only_when_covered(self):
        from app.services.tech_stack import clean_stack_prose
        stack = ['MCP', '记忆', 'Tool Calling', 'LangChain']
        for text in ('项目采用 MCP、记忆、Tool Calling、LangChain 技术栈', '项目采用 MCP、记忆、Tool Calling、LangChain 等技术栈'):
            self.assertEqual(clean_stack_prose(text, stack), '')
        self.assertEqual(clean_stack_prose('项目采用 MCP、Rust 技术栈', stack), '项目采用 MCP、Rust 技术栈')
