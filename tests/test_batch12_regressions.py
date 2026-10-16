"""Primary outages are retryable; only generated drafts deduplicate metrics/actions."""
# ruff: noqa: E402 -- application imports require the repository backend path.
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
import openai
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.agents import resume_graph as graph
from app.agents.resume_writer import run_resume_writer
from app.services.fact_coverage import ensure_fact_coverage, text_covered
from app.services.resume_dedup import deduplicate_resume
from app.services.resume_facts import new_fact
from app.services.resume_review import resume_to_text
from app.services.resume_versions import text_hash
from app.services.error_codes import ChatTurnError, require_model_response
from test_batch11_comparison_case import fixture, P1, P2, P3, extraction_output
from test_campus_and_naming import EchoWriter, semantic_stub
from test_persona_regressions import FIXTURES, fixture_patch
import test_product_security_flow as harness
from app.api import chat
from app.services.session_store import load_resume_session

METRICS = [
    '在120道自拟问题上对答案做人工判定，正确数由基础版本的71道提高到82道',
    '在120道自拟问题上，答案人工判定正确数由基础版本的71道提高到82道',
]
ACTION = '绘制简历素材录入与修改流程原型'
ACTIONS = ['访谈12名同学并整理需求，' + ACTION,
           ACTION + '，参与8名同学可用性测试']
REQUEST = httpx.Request('POST', 'https://model.invalid')


def failure(kind):
    if kind == 'connection':
        raise openai.APIConnectionError(request=REQUEST)
    if kind == 'timeout':
        raise openai.APITimeoutError(request=REQUEST)
    return AIMessage(content='')


class RecoveryModel:
    def __init__(self):
        self.failed_stage = ''
        self.kind = ''
        self.output = fixture_patch('tech')
        self.extract_calls = []
        self.write_calls = []

    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        self.extract_calls.append(payload['message'])
        if self.failed_stage == 'extract':
            return failure(self.kind)
        return AIMessage(content=json.dumps(self.output, ensure_ascii=False))

    def with_structured_output(self, schema):
        async def invoke(messages):
            if schema.__name__ not in ('OnePassOutput', 'WriterDraft', 'RepairOutput'):
                raise ValueError('offline routing fallback')
            self.write_calls.append(schema.__name__)
            if self.failed_stage == 'write':
                return failure(self.kind)
            if schema.__name__ == 'RepairOutput':
                return {'bullets': []}
            result = await EchoWriter().ainvoke(messages)
            return result['writer'] if schema.__name__ == 'WriterDraft' else result
        return SimpleNamespace(ainvoke=invoke)


class DedupTest(unittest.TestCase):
    def test_empty_model_envelopes_are_errors_but_empty_fact_patch_is_valid(self):
        for value in (None, '', '  ', [], AIMessage(content=''), AIMessage(content=[{'type': 'text', 'text': ''}])):
            with self.subTest(value=value), self.assertRaises(ChatTurnError):
                require_model_response(value)
        require_model_response({'items': []})

    def clean(self, bullets):
        source = {'projects': [{'item_id': 'p', 'name': '测试项目', 'facts': [new_fact(t) for t in bullets]}]}
        data = {'projects': [{'item_id': 'p', 'name': '测试项目', 'polished_bullets': list(bullets)}]}
        meta = {'bullets': {'p': [{'fact_ids': [f['id']], 'text_hash': text_hash(t)}
                                for f, t in zip(source['projects'][0]['facts'], bullets)]}}
        deduplicate_resume(data, meta)
        return data, meta, source

    def test_metric_variants_keep_fuller_one_with_citations(self):
        for values in (METRICS, list(reversed(METRICS))):
            data, meta, source = self.clean(values)
            self.assertEqual(data['projects'][0]['polished_bullets'], [METRICS[0]])
            self.assertEqual(len(meta['bullets']['p'][0]['fact_ids']), 2)
            self.assertEqual(meta['bullets']['p'][0]['text_hash'], text_hash(METRICS[0]))
            for _ in range(3):
                report = ensure_fact_coverage(data, meta, source, repair_ids=['p'], repairs={
                    f['id']: {'text': f['text']} for f in source['projects'][0]['facts']})
                self.assertEqual(report['covered'], 2, report)
                self.assertEqual(report['restored'], 0)
                self.assertFalse(deduplicate_resume(data, meta))

    def test_same_length_metrics_keep_earlier(self):
        values = ['用120道自拟问题测试，正确数从71道提高到82道', '以120道自拟问题测试，正确数从71道提高到82道']
        data, _, _ = self.clean(values)
        self.assertEqual(data['projects'][0]['polished_bullets'], [values[0]])

    def test_repeated_action_removed_but_unique_counts_retained(self):
        data, meta, source = self.clean(ACTIONS)
        self.assertEqual(data['projects'][0]['polished_bullets'], [ACTIONS[0], '参与8名同学可用性测试'])
        self.assertEqual(ensure_fact_coverage(data, meta, source)['covered'], 2)
        self.assertFalse(deduplicate_resume(data, meta))

    def test_grammar_equivalent_clause_is_removed(self):
        data, _, _ = self.clean([ACTIONS[0], '绘制了简历素材录入与修改流程原型，参与8名同学可用性测试'])
        self.assertEqual(data['projects'][0]['polished_bullets'][1], '参与8名同学可用性测试')

    def test_unique_number_or_contribution_limit_never_disappears(self):
        for unique in (ACTION + '并访谈9名同学', '仅' + ACTION, ACTION + '由其他成员实现',
                       ACTION + '，未上线', ACTION + '，只在课堂演示'):
            data, _, _ = self.clean([ACTIONS[0], unique])
            self.assertIn(unique.split('，')[-1], '，'.join(data['projects'][0]['polished_bullets']))

    def test_unique_metric_qualifier_wins_and_no_cross_item_cleanup(self):
        data, meta, _ = self.clean([METRICS[0], '在本地测试中，' + METRICS[0]])
        self.assertEqual(data['projects'][0]['polished_bullets'], ['在本地测试中，' + METRICS[0]])
        data['projects'].append({'item_id': 'other', 'polished_bullets': [METRICS[0]]})
        before = deepcopy(data)
        self.assertFalse(deduplicate_resume(data, meta))
        self.assertEqual(data, before)

    def test_single_number_and_short_clause_are_not_dedup_keys(self):
        values = ['访谈12名同学收集反馈', '邀请12名同学体验原型']
        data, _, _ = self.clean(values)
        self.assertEqual(data['projects'][0]['polished_bullets'], values)
        data, _, _ = self.clean(['整理需求，负责原型设计', '整理需求，参与用户测试'])
        self.assertEqual(len(data['projects'][0]['polished_bullets']), 2)

    def test_raw_fallback_refuses_full_fixture_instructions_and_multi_experience(self):
        for text in (FIXTURES['tech']['initial'], '我做A项目时整理反馈。再告诉我哪些地方值得补充。',
                     '我做A项目时整理反馈，也不要编造数据。',
                     '我做A项目时整理反馈。我做B项目时编写接口。',
                     '我做A项目时整理反馈，我做B项目时编写接口。'):
            self.assertEqual(graph._harvest_projects_from_messages([HumanMessage(content=text)]), [])
            result = graph._keep_unextracted_experience({}, {}, HumanMessage(content=text))
            self.assertFalse(result.get('projects'))
        self.assertEqual(graph._harvest_projects_from_messages([
            HumanMessage(content='我做A项目时整理反馈')])[0]['description'], '我做A项目时整理反馈')


class ModelRecoveryTest(harness.ProductSecurityFlow):
    async def setup_model(self, model):
        self.settings.REQUIRE_ACCOUNT = False
        self.a.cookies.clear()  # The reported replay is a guest conversation.
        compiled = graph.build_graph(model, checkpointer=self.saver)
        for module in (graph, chat):
            self.enterContext(patch.object(module, 'get_graph', return_value=compiled))
        self.enterContext(patch.object(chat, '_get_llm', return_value=model))
        self.enterContext(patch.object(chat, 'reserve_turn'))
        self.enterContext(patch.object(chat, 'prepare_graph_context', AsyncMock()))
        self.enterContext(patch.object(graph, '_make_non_streaming_llm', return_value=model))
        self.enterContext(patch.object(graph, '_run_decoder_and_build_reply', AsyncMock(return_value=({'target_role': 'Java后端开发'}, '已解析'))))
        self.enterContext(patch('app.services.fact_guard.verify_semantics', side_effect=semantic_stub))
        for module in ('app.agents.tailor_pipeline', 'app.services.resume_capacity'):
            self.enterContext(patch(module + '.measure_rendered_pages', return_value={
                'status': 'rendered', 'pages': 1, 'within_page_limit': True}))
        self.settings.LLM_PLAN_CONFIRM = False
        return compiled

    async def send(self, sid, text):
        response = await self.a.post('/api/chat/stream', json={
            'session_id': sid, 'messages': [{'role': 'user', 'content': text}]})
        self.assertEqual(response.status_code, 200, response.text)
        return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: {')]

    async def exercise(self, stage, existing):
        model = RecoveryModel()
        compiled = await self.setup_model(model)
        for kind, code in (('connection', 'E-MODEL-NETWORK'), ('timeout', 'E-MODEL-TIMEOUT'), ('empty', 'E-MODEL-UPSTREAM')):
            with self.subTest(stage=stage, existing=existing, kind=kind):
                created = await self.a.post('/api/chat/conversations')
                sid = created.json()['session_id']
                config = {'configurable': {'thread_id': sid}}
                model.failed_stage = ''
                model.output = fixture_patch('tech')
                if existing:
                    events = await self.send(sid, FIXTURES['tech']['initial'])
                    self.assertFalse([e for e in events if e.get('error')], events)
                    self.assertTrue(load_resume_session(sid)['resume_data'].get('projects'))
                before = deepcopy(load_resume_session(sid)['resume_data'])
                if existing and stage == 'extract':
                    prompt = '校园二手交易系统项目补充：我编写了9条商品搜索测试用例，请把这条经历更新到简历。'
                    model.output = {'items': [{'section': 'projects', 'name': '校园二手交易系统', 'facts': [{
                        'text': '我编写了9条商品搜索测试用例', 'source_quote': '我编写了9条商品搜索测试用例', 'kind': 'action'}]}]}
                else:
                    prompt = '请润色校园二手交易系统项目这段经历，保持原有事实。' if existing else FIXTURES['tech']['initial']
                calls_before = len(model.write_calls)
                model.failed_stage, model.kind = stage, kind
                events = await self.send(sid, prompt)
                errors = [e for e in events if e.get('error')]
                self.assertEqual([e['code'] for e in errors], [code], events)
                if stage == 'write':
                    self.assertEqual(len(model.write_calls) - calls_before, 2)
                self.assertIn('模型服务暂时没有响应', errors[0]['error'])
                self.assertIn('重试', errors[0]['error'])
                self.assertFalse([e for e in events if e.get('type') == 'meta'])
                self.assertEqual(load_resume_session(sid)['resume_data'], before)
                snapshot = (await compiled.aget_state(config)).values
                self.assertEqual(snapshot['resume_data'], before)
                self.assertNotEqual(snapshot['stage'], 'BUILDING')
                self.assertTrue(any(isinstance(m, HumanMessage) and m.content == prompt for m in snapshot['messages']))
                self.assertEqual(snapshot['messages'][-1].additional_kwargs['turn_error'], {'code': code, 'retryable': True})
                if not existing and stage == 'extract':
                    self.assertFalse(snapshot.get('candidate_history_reconciled'))
                    self.assertFalse(snapshot['collected_info'].get('projects'))
                calls = len(model.extract_calls)
                model.failed_stage = ''
                events = await self.send(sid, prompt)
                self.assertFalse([e for e in events if e.get('error')], events)
                stored = load_resume_session(sid)
                self.assertTrue(stored['resume_data']['projects'])
                self.assertEqual(stored['stage'], 'EVALUATING')
                body = resume_to_text(stored['resume_data'])
                self.assertIn('林泽', body)
                self.assertNotIn('再告诉我', body)
                self.assertNotIn('也不要编造', body)
                if stage == 'extract':
                    self.assertGreater(len(model.extract_calls), calls)
                if existing and stage == 'extract':
                    self.assertIn('9条商品搜索测试用例', body)

    async def test_initial_extraction_failure_then_same_message_retry(self):
        await self.exercise('extract', False)

    async def test_existing_draft_extraction_failure_then_same_message_retry(self):
        await self.exercise('extract', True)

    async def test_initial_writer_failure_then_same_message_retry(self):
        await self.exercise('write', False)

    async def test_existing_draft_writer_failure_then_same_message_retry(self):
        await self.exercise('write', True)

    async def test_comparison_three_turns_and_persistence_remove_repeats(self):
        model = RecoveryModel()
        model.output = extraction_output(P1)
        await self.setup_model(model)
        original_writer = model.with_structured_output
        def duplicate_writer(schema):
            runnable = original_writer(schema)
            async def invoke(messages):
                result = await runnable.ainvoke(messages)
                rows = result.get('writer', result).get('items', [])
                payload = json.loads(messages[-1].content)
                sources = {item['item_id']: item for item in payload.get('evidence', {}).get('projects', [])}
                for row in rows:
                    source = sources.get(row['item_id'], {})
                    if 'RAG' in source.get('name', ''):
                        ids = [f['id'] for f in source['facts'] if '120' in f['text']]
                        row['bullets'] = [{'text': t, 'fact_ids': ids} for t in METRICS]
                return result
            return SimpleNamespace(ainvoke=invoke)
        model.with_structured_output = duplicate_writer
        sid = (await self.a.post('/api/chat/conversations')).json()['session_id']
        for prompt in (P1, P2, P3):
            events = await self.send(sid, prompt)
            self.assertFalse([e for e in events if e.get('error')], events)
            stored = load_resume_session(sid)
            for project in stored['resume_data'].get('projects', []):
                body = '，'.join(project['polished_bullets'])
                if 'RAG' in project['name']:
                    self.assertEqual(body.count('71'), 1, body)
                    self.assertEqual(body.count('82'), 1, body)
                self.assertLessEqual(body.count(ACTION), 1, body)
        # Generic saves preserve authored repeats; generation owns cleanup.
        from app.services.session_store import save_resume_session
        source, data = fixture()
        data['projects'][0]['polished_bullets'] = ACTIONS
        data['projects'][1]['polished_bullets'] = METRICS
        result = save_resume_session(sid, data, stage='EVALUATING', collected_info=source)
        self.assertEqual(result['resume_data']['projects'][0]['polished_bullets'], ACTIONS)
        self.assertEqual(result['resume_data']['projects'][1]['polished_bullets'], METRICS)
        from app.services.canonical_resume import save_canonical_resume, resume_revision
        compiled = graph.get_graph(model)
        await compiled.aupdate_state({'configurable': {'thread_id': sid}}, result, as_node='building')
        saved = await save_canonical_resume(sid, resume_revision(result['resume_data']), data,
                                            compiled, graph._serialize_to_resume_data, source='editor')
        self.assertEqual(saved['data'], result['resume_data'])

    async def test_editor_api_and_read_only_chat_preserve_authored_repeats(self):
        from app.api import resume as resume_api
        from app.services.session_store import save_resume_session
        model = RecoveryModel()
        compiled = await self.setup_model(model)
        self.enterContext(patch.object(resume_api, 'get_graph', return_value=compiled))
        sid = (await self.a.post('/api/chat/conversations')).json()['session_id']
        source, data = fixture()
        from uuid import uuid4
        for section in ('projects', 'campus'):
            for source_item, item in zip(source.get(section, []), data.get(section, [])):
                source_item['item_id'] = item['item_id'] = str(uuid4())
        initial = {**graph._init_state(), 'collected_info': source, 'resume_data': data, 'stage': 'EVALUATING'}
        await compiled.aupdate_state({'configurable': {'thread_id': sid}}, initial, as_node='building')
        save_resume_session(sid, data, stage='EVALUATING', collected_info=source)
        current = (await self.a.get(f'/api/resume/current?session_id={sid}')).json()
        authored = deepcopy(current['data'])
        authored['projects'][0]['polished_bullets'] = ACTIONS
        authored['projects'][1]['polished_bullets'] = METRICS
        saved = await self.a.put('/api/resume/current', json={
            'session_id': sid, 'expected_revision': current['revision'], 'resume_data': authored})
        self.assertEqual(saved.status_code, 200, saved.text)
        committed = saved.json()['data']
        self.assertEqual(committed['projects'][0]['polished_bullets'], ACTIONS)
        self.assertEqual(committed['projects'][1]['polished_bullets'], METRICS)
        self.assertEqual(load_resume_session(sid)['resume_data'], committed)
        snapshot = await compiled.aget_state({'configurable': {'thread_id': sid}})
        self.assertEqual(snapshot.values['resume_data'], committed)
        events = await self.send(sid, '你好')
        self.assertFalse([event for event in events if event.get('error')], events)
        self.assertEqual(load_resume_session(sid)['resume_data'], committed)


for _name in vars(harness.ProductSecurityFlow):
    if _name.startswith('test_') and _name not in vars(ModelRecoveryTest):
        setattr(ModelRecoveryTest, _name, None)


class WriterDedupTest(unittest.IsolatedAsyncioTestCase):
    async def test_edit_plan_cleanup_precedes_version_and_preserves_undo_data(self):
        from app.agents.tailor_pipeline import apply_deterministic_update
        from app.services.edit_plan import execute_edit_plan
        from app.services.resume_versions import restore_payload
        source, data = fixture()
        data['projects'][0]['polished_bullets'] = ACTIONS
        data['projects'][1]['polished_bullets'] = METRICS
        data['projects'][0]['polished_bullets'] = [*ACTIONS, '待删除的末条']
        data['projects'][1]['polished_bullets'] = [*METRICS, '待删除的末条']
        before = deepcopy(data)
        executed = execute_edit_plan(data, {}, [{'op': 'cap_bullets', 'target': 'projects', 'args': {'count': 2}}], collected_info=source, instruction='每个项目最多保留2条')
        state = {'resume_data': executed['data'], 'previous_resume_data': before, 'collected_info': source}
        with patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={'pages': 1}):
            result = await apply_deterministic_update(state, executed['data'], dedupe=True)
        self.assertEqual(result['resume_data']['projects'][0]['polished_bullets'],
                         [ACTIONS[0], '参与8名同学可用性测试'])
        self.assertEqual(len(result['resume_data']['projects'][1]['polished_bullets']), 1)
        self.assertEqual(restore_payload(result)['resume_data'], before)

    async def test_literal_correction_cleanup_is_part_of_generated_result(self):
        source, data = fixture()
        data['projects'][1]['polished_bullets'] = METRICS
        before = deepcopy(data)
        state = {**graph._init_state(), 'stage': 'EVALUATING', 'resume_data': data, 'collected_info': source,
                 'messages': [HumanMessage(content='校园问答RAG演示的正确数记错了，把“82道”改成“83道”。')]}
        with patch.object(graph, '_write_resume_update', AsyncMock(side_effect=AssertionError('no main write'))), \
                patch('app.services.resume_capacity.measure_rendered_pages', return_value={'pages': 1}):
            result = await graph._evaluating_turn_node(state, RecoveryModel())
        bullets = result['resume_data']['projects'][1]['polished_bullets']
        self.assertEqual(len(bullets), 1)
        self.assertIn('83道', bullets[0])
        self.assertNotIn('82道', bullets[0])
        self.assertEqual(data, before)

    async def test_secondary_semantic_outage_rejects_unverified_facts_without_turn_error(self):
        from app.services.fact_guard import verify_semantics
        from app.agents.fact_extractor import extract_facts_patch
        from test_campus_and_naming import ExtractorStub
        for kind in ('connection', 'timeout', 'empty'):
            class Verifier:
                def with_structured_output(self, schema):
                    return self

                async def ainvoke(self, messages):
                    return failure(kind)
            with self.subTest(kind=kind):
                verdicts = await verify_semantics([{'id': 'f', 'text': '整理反馈', 'source_quotes': ['整理反馈记录']}], Verifier())
                self.assertEqual(verdicts['f']['verdict'], 'fail')
                self.assertEqual(verdicts['f']['unsupported_spans'], ['semantic_verification_failed'])
            async def check(pairs):
                return await verify_semantics(pairs, Verifier())
            with self.subTest(extractor=kind):
                result = await extract_facts_patch('我做A项目时整理反馈记录', {}, ExtractorStub({'items': [{
                    'section': 'projects', 'name': 'A', 'facts': [{'text': '整理反馈', 'source_quote': '整理反馈记录', 'kind': 'action'}]}]}),
                    semantic_check=check)
                self.assertTrue(any(row['reason'] == 'semantic_verification_failed' for row in result['rejected']))

    async def test_written_comparison_facts_remain_covered_after_cleanup(self):
        source, current = fixture()
        source['projects'][0]['facts'] = [new_fact(t) for t in ACTIONS]
        source['projects'][1]['facts'] = [new_fact(t) for t in METRICS]
        with patch('app.services.fact_guard.verify_semantics', side_effect=semantic_stub):
            result = await run_resume_writer(source, {}, EchoWriter(), current_data=current)
        body = result['resume_data']['projects']
        self.assertEqual('，'.join(body[0]['polished_bullets']).count(ACTION), 1)
        self.assertEqual('，'.join(body[1]['polished_bullets']).count('71'), 1)
        for fact in source['projects'][0]['facts']:
            self.assertTrue(text_covered(fact['text'], body[0]['polished_bullets']))
