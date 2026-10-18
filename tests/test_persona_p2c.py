"""P2c evaluator contracts, with in-memory transports and fixed answer sources."""
import asyncio
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from importlib import import_module
import io
import json
import logging
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from persona_support import runner, report, golden_run
from app.services.resume_versions import text_hash

aipm = runner.aipm
real = runner.aipm_real
returning = runner.returning
loop = runner.loop_checks
server = import_module('evaluation.persona-ux.serve')
compare = import_module('scripts.compare_persona_runs')


def draft(reply='已完成。', guidance=None):
    bullet = '决策：依据已确认事实整理项目。'
    return {'status': 'ok', 'sse_done': True, 'reply': reply, 'stage': 'EVALUATING',
            'revision': 'r1', 'has_data': True, 'resume_data': {'projects': [{
                'item_id': 'p', 'name': aipm.INTAKE['items'][0]['name'], 'polished_bullets': [bullet]}]},
            'workspace': {'guidance': guidance or {}, 'tailor': {'resume_meta': {
                'writer_diagnostic': {'status': 'model_completed'},
                'bullets': {'p': [{'fact_ids': ['f'], 'text_hash': text_hash(bullet)}]}}}}}


def card(question, turn_id='actual-card'):
    return {'kind': 'ask_user', 'turn_id': turn_id, 'subject': aipm.INTAKE['items'][0]['name'],
            'questions': [question]}


class ScriptedClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.sent = []
        self.cookies = SimpleNamespace(clear=lambda: None)

    def start(self):
        pass

    def json(self, path):
        return {'schema_version': 1, 'agent_mode': 'loop', 'model_call_scope': loop.CALL_SCOPE}

    def turn(self, action, text, **payload):
        self.sent.append((action, text, payload))
        return {**deepcopy(next(self.responses)), 'action': action, 'input': text, **payload}


class P2cRunnerTests(unittest.TestCase):
    def test_loop_keeps_answering_card_after_first_draft_and_off_stays_unchanged(self):
        q = {'id': 'eval-now', 'prompt': '如何评测生成结果？', 'kind': 'text'}
        responses = [draft(guidance=card(q)), draft()]
        client = ScriptedClient(responses)
        turns = list(aipm.replay(client, agent_mode='loop'))
        self.assertEqual(len(turns), 2)
        self.assertEqual(client.sent[1][2]['answers'], {'turn_id': 'actual-card', 'items': [aipm._answer(q)]})
        self.assertIn(aipm.VALUES['evaluation'][1], client.sent[1][1])
        self.assertEqual(len(list(aipm.replay(ScriptedClient(responses), agent_mode='off'))), 1)

    def test_no_card_uses_existing_free_answer_bank_instead_of_ending(self):
        client = ScriptedClient([draft('你用什么技术栈做的？'), draft()])
        turns = list(aipm.replay(client, agent_mode='loop'))
        self.assertEqual(len(turns), 2)
        self.assertEqual(client.sent[1], ('free_answer', aipm.free_text_answer('你用什么技术栈做的？', aipm.VALUES), {}))
        self.assertNotEqual(client.sent[1][1], '不知道')

    def test_real_preserves_raw_four_turns_then_answers_same_bank_after_draft(self):
        q = {'id': 'usage', 'prompt': '有多少人在用？', 'kind': 'single',
             'options': ['10 人付费使用', '100 人'], 'allow_other': True}
        responses = [draft() for _ in range(3)] + [draft(guidance=card(q)), draft()]
        client = ScriptedClient(responses)
        turns = list(real.replay(client, agent_mode='loop'))
        self.assertEqual([text for _, text, _ in client.sent[:4]], real.FIRST_TURNS)
        self.assertTrue(all(not extra for _, _, extra in client.sent[:4]))
        self.assertEqual(turns[-1]['answers']['items'], [real.answer(q)])
        self.assertEqual(real.answer(q)['value'], real.VALUES['adoption'])
        self.assertNotIn('付费', client.sent[-1][1])

    def test_header_card_answers_only_existing_intake_facts_never_contacts(self):
        for module, answer in ((aipm, aipm._answer), (real, real.answer)):
            for prompt, key in (('这个项目叫什么名字？', 'name'), ('项目开始时间是哪年哪月？', 'start'),
                                ('项目结束时间？', 'end'), ('在项目中是什么角色？', 'role')):
                q = {'id': 'runtime-id', 'prompt': prompt, 'kind': 'text'}
                self.assertEqual(answer(q)['value'], module.INTAKE['items'][0][key])
            for prompt in ('姓名、手机和邮箱？', '学校和专业？'):
                q = {'id': 'header_info', 'prompt': prompt, 'kind': 'text'}
                self.assertTrue(answer(q)['unknown'])
            q = {'id': 'project_name', 'prompt': '这个项目叫什么名字？', 'kind': 'single',
                 'options': ['没有做过项目'], 'allow_other': False}
            self.assertTrue(answer(q)['unknown'])

    def test_unknown_questions_and_depth_limit_remain_visible_failures(self):
        q = {'id': 'unknown', 'prompt': '尚未记录的字段是什么？', 'kind': 'text'}
        client = ScriptedClient([draft(guidance=card(q)) for _ in range(aipm.MAX_ROUNDS + 2)])
        turns = list(aipm.replay(client, agent_mode='loop'))
        self.assertEqual(len(turns), aipm.MAX_ROUNDS + 2)
        self.assertTrue(turns[1]['answers']['items'][0]['unknown'])
        self.assertTrue(turns[-1]['depth_limit_exceeded'])
        result = {c['id']: c['status'] for c in aipm.evaluate_persona('aipm', turns)}
        self.assertEqual(result['aipm.depth_within_limit'], 'fail')
        self.assertEqual(result['aipm.answers_used'], 'fail')

    def test_runner_passes_mode_and_saves_actual_answer_payload(self):
        q = {'id': 'evaluation', 'prompt': '如何评测？', 'kind': 'text'}
        client = ScriptedClient([draft(guidance=card(q)), draft()])
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, 'GuestClient', return_value=client):
            run = runner.run_replay('http://127.0.0.1:9', Path(directory) / 'run', ['aipm'], agent_mode='loop')
            turns = run['personas']['aipm']['turns']
            saved = json.loads((Path(directory) / 'run/aipm/02-answers_1.json').read_text())
            self.assertEqual(saved['answers'], turns[-1]['answers'])
            self.assertEqual(len(turns), 2)


class P2cCheckTests(unittest.TestCase):
    def test_one_post_draft_request_is_one_and_repeated_requests_still_fail(self):
        turn = draft('首稿已完成，请一次补齐姓名、手机、邮箱。',
                     card({'id': 'contacts', 'prompt': '手机和邮箱', 'kind': 'text'}))
        self.assertEqual(loop.observations([turn])['contact_request_turns'], [1])
        rows = {c['id']: c['status'] for c in loop.evaluate_loop('career', [turn, deepcopy(turn)])}
        self.assertEqual(rows['career.loop.contacts_once'], 'fail')

    def test_acknowledgment_cannot_hide_another_missing_contact_request(self):
        self.assertTrue(loop.contact_request({'reply': '邮箱已经记下，但手机号还缺，请补充手机号。'}))
        self.assertTrue(loop.contact_request({'reply': '姓名和邮箱已经记下，头部还差手机号，方便的话请发给我。'}))
        self.assertFalse(loop.contact_request({'reply': '手机和邮箱已记录，不用再提供。'}))
        self.assertFalse(loop.contact_request({'workspace': {'guidance': {
            'kind': 'intake_basics', 'missing_fields': ['school', 'major']}}}))

    def test_receipt_requires_completed_action_both_names_and_visible_evidence(self):
        names = '、'.join(returning.PROJECTS)
        turn = {'reply': f'已从档案选用了两段并写入简历：{names}。',
                'resume_data': {'projects': [{'name': n} for n in returning.PROJECTS]}}
        self.assertTrue(returning.import_receipt(turn))
        for reply in (f'我把两段经历选进了稿子：{names}。', f'已从档案导入：{names}。'):
            self.assertTrue(returning.import_receipt({**turn, 'reply': reply}))
        for reply in (f'下轮我会导入{names}。', f'没有导入{names}。', f'是否导入{names}？',
                      f'已导入{names}，但导入失败。', f'档案中有{names}。', f'已导入{returning.PROJECTS[0]}。'):
            self.assertFalse(returning.import_receipt({**turn, 'reply': reply}), reply)
        self.assertFalse(returning.import_receipt({**turn, 'resume_data': {}}))
        turn['resume_data']['projects'][0]['hidden'] = True
        self.assertFalse(returning.import_receipt(turn))


def orchestration():
    return {'model_calls': 2, 'tool_steps': 1, 'seconds': 3,
            'usage': {'prompt_tokens': 6000, 'completion_tokens': 600, 'reasoning_tokens': 400,
                      'prompt_cache_hit_tokens': 2000},
            'turns': [{'mode': 'thinking', 'seconds': 1, 'usage': {'prompt_tokens': 2000,
                       'completion_tokens': 300, 'reasoning_tokens': 200, 'prompt_cache_hit_tokens': 1000}},
                      {'mode': 'off', 'seconds': .5, 'usage': {'prompt_tokens': 4000,
                       'completion_tokens': 300, 'reasoning_tokens': 200, 'prompt_cache_hit_tokens': 1000}}]}


class P2cMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_installed_openai_sdk_transport_is_counted_and_contacts_blocked(self):
        from openai import AsyncOpenAI, DefaultAsyncHttpxClient, APIConnectionError
        transport_module = import_module(DefaultAsyncHttpxClient.__mro__[1].__module__.split('.')[0])
        sent = []
        def respond(request):
            sent.append(request)
            return transport_module.Response(200, json={'id': 'offline', 'object': 'chat.completion',
                'created': 0, 'model': 'offline', 'choices': [{'index': 0,
                'message': {'role': 'assistant', 'content': 'ok'}, 'finish_reason': 'stop'}]})
        ledger = {'model_calls': 0, 'privacy_blocks': 0}
        token = server.COUNTS.set(ledger)
        try:
            with server.model_meter():
                async with AsyncOpenAI(api_key='offline-test', base_url='https://model.invalid/v1', max_retries=0,
                        http_client=DefaultAsyncHttpxClient(transport=transport_module.MockTransport(respond))) as client:
                    await client.chat.completions.create(model='offline', messages=[{'role': 'user', 'content': 'safe'}])
                    self.assertEqual(ledger['model_calls'], 1)
                    for contact in ('13900001234', 'person@example.invalid'):
                        with self.assertRaises((ValueError, APIConnectionError)):
                            await client.chat.completions.create(model='offline', messages=[{'role': 'user', 'content': contact}])
            self.assertEqual(len(sent), 1)
            self.assertEqual(ledger, {'model_calls': 1, 'privacy_blocks': 2})
        finally:
            server.COUNTS.reset(token)

    def test_guest_turn_and_saved_artifact_keep_projected_orchestrator_metrics(self):
        event = {'type': 'evaluation_metrics', 'agent_mode': 'loop', 'model_calls': 2,
                 'privacy_blocks': 0, 'server_seconds': 4, 'model_call_scope': loop.CALL_SCOPE,
                 'metrics_version': 2, 'orchestrator': orchestration()}
        raw = ('data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n').encode()
        client = runner.GuestClient('http://127.0.0.1:9')
        with patch.object(client, 'open', return_value=io.BytesIO(raw)), patch.object(client, 'json', return_value={}):
            turn = client.turn('initial', 'safe')
        with tempfile.TemporaryDirectory() as directory:
            runner.save_turn(Path(directory), 1, turn)
            saved = json.loads((Path(directory) / '01-initial.json').read_text())
        self.assertEqual(saved['orchestrator'], orchestration())
        self.assertEqual(saved['metrics_version'], 2)

    async def test_parallel_orchestrator_logs_are_numeric_only_and_reach_saved_turn(self):
        log = logging.getLogger('app.agents.orchestrator')
        original_level = log.level
        async def app(scope, receive, send):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
                for _ in range(2):
                    await client.post('https://model.invalid/chat/completions', json={'messages': []})
            data = orchestration()
            data['seconds'] = scope['test_seconds']
            data.update(content='DO_NOT_SAVE', reasoning_content='13900001234', email='secret@example.invalid')
            data['turns'][0]['usage']['secret'] = 'DO_NOT_SAVE'
            log.info('orchestrator_turn %s', json.dumps(data))
            await asyncio.sleep(0)
            await send({'type': 'http.response.start', 'headers': [(b'content-type', b'text/event-stream')], 'status': 200})
            await send({'type': 'http.response.body', 'body': b'data: [DONE]\n\n'})

        async def request(seconds):
            chunks = []
            async def send(message):
                chunks.append(message.get('body', b''))
            await server.ReplayApp(app, 'loop')({'type': 'http', 'method': 'POST',
                'path': '/api/chat/stream', 'test_seconds': seconds}, None, send)
            raw = b''.join(chunks)
            self.assertNotIn(b'DO_NOT_SAVE', raw)
            self.assertNotIn(b'13900001234', raw)
            self.assertNotIn(b'secret@example.invalid', raw)
            return runner.read_sse(io.BytesIO(raw))['metrics']
        with server.model_meter():
            first, second = await asyncio.gather(request(3), request(7))
        self.assertEqual([r['orchestrator']['seconds'] for r in (first, second)], [3, 7])
        self.assertEqual(first['orchestrator']['usage']['prompt_cache_hit_tokens'], 2000)
        self.assertEqual(first['model_calls'], 2)
        self.assertEqual(first['metrics_version'], 2)
        self.assertEqual(log.level, original_level)
        self.assertIsNone(server.COUNTS.get())

    async def test_missing_http_observation_is_unknown_not_zero_or_orchestrator_estimate(self):
        async def app(scope, receive, send):
            logging.getLogger('app.agents.orchestrator').info('orchestrator_turn %s', json.dumps(orchestration()))
            await send({'type': 'http.response.start', 'headers': [(b'content-type', b'text/event-stream')]})
            await send({'type': 'http.response.body', 'body': b'data: [DONE]\n\n'})
        chunks = []
        async def send(message):
            chunks.append(message.get('body', b''))
        with server.model_meter():
            await server.ReplayApp(app, 'loop')({'type': 'http', 'method': 'POST', 'path': '/api/chat/stream'}, None, send)
        result = runner.read_sse(io.BytesIO(b''.join(chunks)))['metrics']
        self.assertIsNone(result['model_calls'])
        self.assertIsNone(result['privacy_blocks'])
        self.assertEqual(result['orchestrator']['model_calls'], 2)

    def test_missing_or_invalid_usage_is_not_zero_and_unknown_fields_are_dropped(self):
        data = orchestration()
        data['usage'] = {'prompt_tokens': True, 'completion_tokens': -1, 'reasoning_tokens': float('nan')}
        data['turns'][0]['usage']['prompt_cache_hit_tokens'] = '100'
        projected = runner.metrics.orchestrator(data)
        self.assertTrue(all(v is None for v in projected['usage'].values()))
        self.assertIsNone(projected['turns'][0]['usage']['prompt_cache_hit_tokens'])

    def test_v2_loop_metrics_require_orchestrator_evidence_except_structured_actions(self):
        turn = {**draft(), 'metrics_version': 2, 'metrics_agent_mode': 'loop',
                'model_call_scope': loop.CALL_SCOPE, 'model_calls': 2, 'privacy_blocks': 0,
                'server_seconds': 3, 'stream_seconds': 3, 'elapsed_seconds': 3}
        def status(value):
            return next(r['status'] for r in loop.evaluate_loop('aipm', [value]) if r['id'].endswith('.metrics'))
        self.assertEqual(status(turn), 'fail')
        self.assertEqual(status({**turn, 'orchestrator': orchestration()}), 'pass')
        self.assertEqual(status({**turn, 'answers': {'turn_id': 'card', 'items': []}}), 'pass')
        self.assertEqual(status({**turn, 'kind': 'confirmation'}), 'pass')


class P2cComparisonTests(unittest.TestCase):
    def test_comparison_rechecks_failures_and_reports_exact_timing_and_token_samples(self):
        old = golden_run(('tech',), run_id='off')
        new = deepcopy(old)
        new.update(run_id='loop', agent_mode='loop', agent_mode_verified=True)
        for i, turn in enumerate(new['personas']['tech']['turns']):
            turn.update(elapsed_seconds=i + 1, orchestrator=orchestration())
        new['personas']['tech']['turns'][-1]['resume_data']['work_experience'][0]['bullets'][2] = '420ms → 170ms'
        new['personas']['tech']['checks'] = [{'id': 'tech.correction_190', 'status': 'pass'}]
        markdown = report.render_comparison([old, new])
        self.assertIn('correction_190', markdown)
        self.assertIn('2.000 / 3.000 (3/3)', markdown)
        self.assertIn('18000 / 1800 / 1200 / 6000', markdown)
        self.assertIn('3000 / 4000 (6/6)', markdown)
        self.assertIn('N/A', markdown)
        self.assertIn('共同断言', markdown)
        self.assertIn('1/1 | thinking', report.render_report([new]))

    def test_missing_persona_and_partial_metrics_cannot_be_success_or_complete_cost(self):
        old, new = golden_run(('tech',)), golden_run(('service',))
        turns = new['personas']['service']['turns']
        turns[0]['orchestrator'] = orchestration()
        turns[0]['orchestrator']['usage']['reasoning_tokens'] = None
        turns[0]['elapsed_seconds'] = float('nan')
        text = report.render_comparison([old, new])
        self.assertIn('MISSING', text)
        self.assertIn('6000 / 600 / N/A / 2000', text)
        self.assertIn('(1/2)', text)
        self.assertNotIn('nan', text)

    def test_cli_reads_two_frozen_directories_and_writes_markdown_without_service(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('before', 'after'):
                (root / name).mkdir()
                (root / name / 'run.json').write_text(json.dumps(golden_run(('tech',), run_id=name)))
            output = root / 'evaluation/comparison.md'
            with patch.object(compare, 'ROOT', root):
                self.assertEqual(compare.main([str(root / 'before'), str(root / 'after'), '--output', str(output)]), 0)
                self.assertIn('tech', output.read_text())
                stream = io.StringIO()
                with redirect_stdout(stream):
                    self.assertEqual(compare.main([str(root / 'before'), str(root / 'after')]), 0)
                self.assertIn('before', stream.getvalue())
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    compare.main([str(root / 'before'), str(root / 'after'), '--output', str(root / 'outside.md')])
