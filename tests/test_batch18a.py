"""Batch 18a: isolated accounts, fake provider streams, and Node DOM checks."""
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI
from langgraph.checkpoint.memory import MemorySaver
from openai import AsyncOpenAI

import test_orchestrator as orchestration
import test_product_security_flow as security
from app.agents import orchestrator as loop, resume_graph as graph
from app.agents.next_hint import HINTS, HintStream, filter_next_hint
from app.agents.orchestrator_tools import ToolOutcome
from app.api import chat, conversations
from app.config import Settings
from app.services.access_control import OTHER_ACCOUNT_MESSAGE
from app.services.session_store import delete_resume_session


class HintFilterTests(unittest.TestCase):
    def test_allowed_intent_and_whitespace(self):
        for hint in HINTS:
            self.assertLessEqual(len(hint), 30)
            self.assertEqual(filter_next_hint(' ' + hint + ' '), hint)

    def test_numbers_are_discarded(self):
        for value in ('我提升了30%的效率', '联系13800139000', '补充２项成果', '增加٣项'):
            self.assertIsNone(filter_next_hint(value))

    def test_links_and_email_are_discarded(self):
        for value in ('访问http://example.test', '访问HTTPS://example.test', '联系a@example.test', '访问www.example.test'):
            self.assertIsNone(filter_next_hint(value))

    def test_empty_and_nonstring_are_discarded(self):
        for value in ('', '  ', None, {}, 1):
            self.assertIsNone(filter_next_hint(value))

    def test_long_and_unverified_facts_are_discarded(self):
        for value in ('补' * 31, '我在虚构公司负责增长', '我毕业于虚构大学', '我曾独立完成系统研发', '我让收入翻倍'):
            self.assertIsNone(filter_next_hint(value))

    def test_card_suppresses_valid_hint(self):
        self.assertIsNone(filter_next_hint(HINTS[0], has_card=True))

    def test_stream_split_at_every_boundary_and_malformed_suffix(self):
        text = '公开回复。<next_hint>' + HINTS[0] + '</next_hint>'
        for split in range(len(text) + 1):
            stream = HintStream()
            self.assertEqual(stream.feed(text[:split]) + stream.feed(text[split:]), '公开回复。')
            self.assertEqual(stream.hint(), HINTS[0])
        for suffix in ('<next_hint>不完整', '<next_hint>' + HINTS[0] + '</next_hint>额外正文', '<next_hi'):
            stream = HintStream()
            self.assertEqual(''.join(stream.feed(c) for c in '正文。' + suffix), '正文。')
            self.assertIsNone(stream.hint())


def provider_client(text, requests):
    def transport(request):
        requests.append(json.loads(request.content))
        chunks = [{'choices': [{'index': 0, 'delta': {'reasoning_content': '内部推理'}}]}]
        chunks += [{'choices': [{'index': 0, 'delta': {'content': char}}]} for char in text]
        chunks.append({'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              text=''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks) + 'data: [DONE]\n\n')
    return AsyncOpenAI(api_key='offline', base_url='https://provider.invalid', max_retries=0,
                       http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))


class HintLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_model_call_produces_hint_in_decision_and_forced_final(self):
        for allow_tools in (True, False):
            with self.subTest(allow_tools=allow_tools):
                requests, deltas = [], []
                async with provider_client('公开回复。<next_hint>' + HINTS[0] + '</next_hint>', requests) as client:
                    model = loop.OrchestratorModel(client, model='offline', schemas=[])
                    reply = await model.complete([{'role': 'user', 'content': '测试'}], mode='off',
                                                 allow_tools=allow_tools, on_delta=deltas.append)
                self.assertEqual(len(requests), 1)
                self.assertEqual(reply.message['content'], '公开回复。')
                self.assertEqual(reply.message['next_hint'], HINTS[0])
                self.assertEqual(''.join(deltas), '' if allow_tools else '公开回复。')

    async def test_loop_stores_hint_without_extra_call_and_card_suppresses_it(self):
        settings = Settings(_env_file=None, AGENT_MODE='loop')
        for card_present in (False, True):
            requests = []
            card = {'kind': 'ask_user', 'turn_id': 'card', 'questions': [
                {'id': 'work', 'prompt': '具体做了什么？', 'kind': 'text'}]}
            tools = orchestration.registry(ask_user=AsyncMock(return_value=ToolOutcome(
                {'status': 'ok'}, {}, [{'type': 'guidance', 'guidance': card}], stop=True)))
            async with provider_client('已整理。<next_hint>' + HINTS[0] + '</next_hint>', requests) as client:
                model = loop.OrchestratorModel(client, model='offline', schemas=loop._schemas(tools))
                if card_present:
                    real_complete = model.complete
                    first = orchestration.Model([orchestration.call('ask_user', card={'questions': card['questions']})])
                    async def complete(messages, **kwargs):
                        if not first.requests:
                            return await first.complete(messages, **kwargs)
                        return await real_complete(messages, **kwargs)
                    model.complete = complete
                with patch('app.config.get_settings', return_value=settings):
                    result = await loop.run_orchestrator(orchestration.state(), model, registry=tools)
            final = result['messages'][-1]
            self.assertEqual(len(requests), 1)
            self.assertEqual(final.additional_kwargs['orchestrator']['model_calls'], 2 if card_present else 1)
            self.assertEqual(final.additional_kwargs.get('next_hint'), None if card_present else HINTS[0])
            self.assertNotIn('next_hint', final.content)
            self.assertNotIn('next_hint', json.dumps(conversations._public_messages(result)))


class HintSSETests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = orchestration.OrchestratorGraphTests.asyncSetUp
    asyncTearDown = orchestration.OrchestratorGraphTests.asyncTearDown

    async def test_real_graph_and_sse_forward_hint_after_save(self):
        requests = []
        async with provider_client('已整理。<next_hint>' + HINTS[0] + '</next_hint>', requests) as client:
            model = loop.OrchestratorModel(client, model='offline', schemas=[])
            async def node(value, llm):
                from langgraph.config import get_stream_writer
                return await loop.run_orchestrator(value, model, registry={}, emit=get_stream_writer())
            with patch.object(loop, 'orchestrator_node', node):
                compiled = graph.build_graph(SimpleNamespace(model_name='offline'), MemorySaver())
            app = FastAPI()
            app.include_router(chat.router, prefix='/api/chat')
            with (patch.object(graph, 'get_graph', return_value=compiled),
                  patch.object(chat, 'get_graph', return_value=compiled),
                  patch.object(chat, '_get_llm', return_value=SimpleNamespace(model_name='offline')),
                  patch.object(chat, 'resolve_owner', return_value='guest:orchestrator'),
                  patch.object(chat, 'prepare_graph_context', new_callable=AsyncMock),
                  patch.object(chat, '_session_meta', new_callable=AsyncMock, return_value={'type': 'meta'}),
                  patch('app.services.account_service.resolve_owner', return_value='guest:orchestrator')):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as web:
                    response = await web.post('/api/chat/stream', json={
                        'session_id': self.session, 'messages': [{'role': 'user', 'content': '你好'}]})
        self.assertEqual(response.status_code, 200, response.text)
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: {')]
        self.assertIn({'type': 'next_hint', 'next_hint': HINTS[0]}, frames)
        self.assertTrue(response.text.endswith('data: [DONE]\n\n'))
        self.assertEqual(len(requests), 1)
        snapshot = await compiled.aget_state({'configurable': {'thread_id': self.session}})
        self.assertEqual(conversations._public_messages(snapshot.values)[-1], {'role': 'assistant', 'content': '已整理。'})
        self.assertIsNotNone(self.store.load_resume_session(self.session))


class EditLinkAccountTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = security.ProductSecurityFlow.asyncSetUp
    cleanup = security.ProductSecurityFlow.cleanup
    login = security.ProductSecurityFlow.login
    fixture = security.ProductSecurityFlow.fixture

    def paths(self, sid):
        return (f'/api/chat/conversations/{sid}?from=mcp', f'/api/resume/current?session_id={sid}&from=mcp')

    async def test_other_account_returns_only_fixed_error_and_owner_still_reads(self):
        sid, _ = await self.fixture()
        for path in self.paths(sid):
            result = await self.b.get(path)
            self.assertEqual(result.status_code, 403, result.text)
            self.assertEqual(result.json(), {'detail': {'code': 'conversation_other_account', 'message': OTHER_ACCOUNT_MESSAGE}})
            self.assertEqual(result.headers['cache-control'], 'no-store')
            for secret in ('PRIVATE_CANARY', '课程工具', '后端参与者', 'a@example.test', self.account_a, sid):
                self.assertNotIn(secret, result.text)
            self.assertEqual((await self.a.get(path)).status_code, 200)

    async def test_normal_and_unknown_source_reads_keep_original_404(self):
        sid, _ = await self.fixture()
        for path in self.paths(sid):
            for marker in ('', 'from=web'):
                result = await self.b.get(path.replace('from=mcp', marker).rstrip('?&'))
                self.assertEqual(result.status_code, 404, result.text)
                self.assertNotIn('conversation_other_account', result.text)

    async def test_missing_and_deleted_sessions_keep_original_404(self):
        sid, _ = await self.fixture()
        delete_resume_session(sid)
        for session in (sid, str(uuid4())):
            for path in self.paths(session):
                result = await self.b.get(path)
                self.assertEqual(result.status_code, 404, result.text)
                self.assertNotIn('conversation_other_account', result.text)

    async def test_logged_out_does_not_disclose_existence(self):
        sid, _ = await self.fixture()
        await self.b.post('/api/account/logout')
        for path in self.paths(sid):
            result = await self.b.get(path)
            missing = await self.b.get(path.replace(sid, str(uuid4())))
            self.assertEqual(result.status_code, missing.status_code)
            self.assertEqual(result.json(), missing.json())
            self.assertNotIn('conversation_other_account', result.text)

    async def test_marker_does_not_change_write_authorization(self):
        sid, _ = await self.fixture()
        result = await self.b.delete(f'/api/chat/session/{sid}?from=mcp')
        self.assertEqual(result.status_code, 404)
        self.assertNotIn('conversation_other_account', result.text)


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class Batch18aDOMTests(unittest.TestCase):
    def check_dom(self, scenario):
        import subprocess
        result = subprocess.run(['node', str(Path(__file__).with_name('batch18a.dom.js')), scenario],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_hint_placeholder_tab_typing_sending_and_mobile(self):
        self.check_dom('hint')

    def test_editor_other_account_and_logout_return_link(self):
        self.check_dom('editor')

    def test_chat_other_account_switch_and_login_return(self):
        self.check_dom('chat')

    def test_shared_logout_clears_cache_preserves_url_and_handles_failure(self):
        self.check_dom('logout')
