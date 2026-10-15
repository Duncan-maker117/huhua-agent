"""Explicit stop vs transport disconnect, with real graph/checkpoint and SQLite."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.agents import resume_graph as graph
from app.api import chat
from app.database import Base
from app.services import session_store, conversation_store
from app.services.chat_turns import ChatTurn, active_turns, current_turn, TurnCancelled


class ChatCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.enterContext(patch.object(session_store, 'SessionLocal', self.factory))
        self.enterContext(patch.object(conversation_store, 'SessionLocal', self.factory))
        self.enterContext(patch('app.services.account_service.resolve_owner', side_effect=lambda request, **kw: request.headers.get('x-owner', 'guest:one')))
        self.enterContext(patch('app.services.resume_capacity.revalidate_committed_page_check', side_effect=lambda data, meta, *a, **kw: meta))
        self.session = conversation_store.create_conversation('guest:one')['session_id']
        self.old = {'basic_info': {'name': '合成人物'}, 'work_experience': [{'item_id': 'work', 'company': '测试店', 'bullets': ['此前已保存']}]}
        self.old_facts = {'basic_info': {'name': '合成人物'}}
        session_store.save_resume_session(self.session, self.old, stage='EVALUATING', collected_info=self.old_facts,
                                          resume_meta={'version_id': 'old'}, resume_versions=[{'label': '旧版'}])
        self.entered, self.release, self.closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.calls = []
        async def collecting(state):
            facts = {**self.old_facts, 'skills': [{'name': 'Excel', 'source_quote': '会Excel'}]}
            update = await graph._persist_intake(state, facts)
            return update
        async def building(state):
            self.calls.append('writer')
            self.entered.set()
            try:
                await self.release.wait()
            finally:
                self.closed.set()
            self.calls.append('later_llm')
            new = deepcopy(self.old)
            new['work_experience'][0]['bullets'] = ['本轮新措辞']
            return {'resume_data': new, 'resume_meta': {'version_id': 'new'}, 'resume_versions': [{'label': '本轮'}],
                    'messages': [AIMessage(content='已修改', id='reply')], 'stage': 'EVALUATING'}
        builder = StateGraph(graph.ResumeState)
        builder.add_node('collecting', collecting)
        builder.add_node('building', building)
        builder.add_edge(START, 'collecting')
        builder.add_edge('collecting', 'building')
        builder.add_edge('building', END)
        self.compiled = builder.compile(checkpointer=MemorySaver())
        self.config = {'configurable': {'thread_id': self.session}}
        await self.compiled.aupdate_state(self.config, {**graph._init_state(), 'stage': 'EVALUATING',
            'resume_data': deepcopy(self.old), 'collected_info': deepcopy(self.old_facts),
            'resume_meta': {'version_id': 'old'}, 'resume_versions': [{'label': '旧版'}]}, as_node='building')
        self.enterContext(patch.object(graph, 'get_graph', return_value=self.compiled))
        app = FastAPI()
        app.include_router(chat.router, prefix='/api/chat')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver')

    async def asyncTearDown(self):
        self.release.set()
        for turn in list(active_turns.values()):
            turn.cancel()
        if chat._active_streams:
            await asyncio.gather(*list(chat._active_streams), return_exceptions=True)
        await self.client.aclose()
        self.engine.dispose()

    async def start_turn(self, turn_id='turn-one'):
        turn = ChatTurn(self.session, turn_id, 'guest:one')
        active_turns[(self.session, turn_id)] = turn
        async def source():
            async with session_store.session_lock(self.session):
                yield 'started'
                async for chunk in graph.stream_agent([{'content': '补充：会Excel，请生成'}], self.session, object()):
                    yield chunk
        stream = chat._complete_on_disconnect(source(), turn)
        self.assertEqual(await anext(stream), 'started')
        await asyncio.wait_for(self.entered.wait(), 3)
        return turn, stream

    async def cancel(self, turn, owner='guest:one', session=None):
        return await self.client.post(f'/api/chat/session/{session or self.session}/cancel',
                                      params={'turn_id': turn.turn_id}, headers={'x-owner': owner})

    async def test_cancel_stops_later_calls_keeps_committed_intake_and_next_turn_works(self):
        turn, stream = await self.start_turn()
        self.assertTrue(session_store.load_resume_session(self.session)['collected_info']['skills'])
        response = await asyncio.wait_for(self.cancel(turn), 3)
        self.assertTrue(response.json()['cancelled'])
        await stream.aclose()
        self.assertTrue(self.closed.is_set())
        self.assertEqual(self.calls, ['writer'])
        saved = session_store.load_resume_session(self.session)
        self.assertEqual(saved['resume_data'], self.old)
        self.assertEqual(saved['resume_meta']['version_id'], 'old')
        self.assertEqual(saved['resume_versions'], [{'label': '旧版'}])
        self.assertTrue(saved['collected_info']['skills'])
        values = (await self.compiled.aget_state(self.config)).values
        self.assertEqual(values['resume_data'], self.old)
        self.assertEqual(values['collected_info'], saved['collected_info'])
        self.assertFalse(session_store.session_lock(self.session).locked())
        self.assertNotIn((self.session, turn.turn_id), active_turns)
        self.release.set()
        next_turn, stream = await self.start_turn('turn-two')
        _ = [chunk async for chunk in stream]
        self.assertTrue(next_turn.committed)
        self.assertEqual(session_store.load_resume_session(self.session)['resume_data']['work_experience'][0]['bullets'], ['本轮新措辞'])

    async def test_stream_endpoint_registers_client_turn_id_for_authenticated_cancel(self):
        payload = {'session_id': self.session, 'turn_id': 'client-id', 'messages': [{'role': 'user', 'content': '补充会Excel'}]}
        async def receive():
            return {'type': 'http.request', 'body': json.dumps(payload).encode(), 'more_body': False}
        request = Request({'type': 'http', 'method': 'POST', 'path': '/api/chat/stream', 'headers': []}, receive)
        with patch.object(chat, '_get_llm', return_value=object()), patch.object(chat, 'get_graph', return_value=self.compiled), patch.object(chat, 'resolve_owner', return_value='guest:one'), patch.object(chat, 'reserve_turn'), patch.object(chat, 'prepare_graph_context', return_value=None):
            response = await chat.chat_stream(request)
            self.assertEqual(response.headers['x-chat-turn-id'], 'client-id')
            pending = asyncio.create_task(anext(response.body_iterator))
            await asyncio.wait_for(self.entered.wait(), 3)
            turn = active_turns[(self.session, 'client-id')]
            result = await asyncio.wait_for(self.cancel(turn), 3)
            self.assertTrue(result.json()['cancelled'])
            self.assertIn('cancelled', await pending)
            _ = [chunk async for chunk in response.body_iterator]
        self.assertEqual(session_store.load_resume_session(self.session)['resume_data'], self.old)
        self.assertEqual(self.calls, ['writer'])

    async def test_disconnect_without_cancel_still_commits_and_holds_lock(self):
        turn, stream = await self.start_turn()
        await stream.aclose()
        self.assertFalse(turn.cancelled)
        self.assertTrue(session_store.session_lock(self.session).locked())
        self.release.set()
        await asyncio.wait_for(turn.done.wait(), 3)
        self.assertTrue(turn.committed)
        self.assertEqual(self.calls, ['writer', 'later_llm'])
        self.assertEqual(session_store.load_resume_session(self.session)['resume_data']['work_experience'][0]['bullets'], ['本轮新措辞'])

    async def test_cancel_authorization_and_turn_identity_do_not_cross_sessions(self):
        turn, stream = await self.start_turn()
        other = conversation_store.create_conversation('guest:two')['session_id']
        account_session = conversation_store.create_conversation('account:one')['session_id']
        for owner in ('guest:two', 'account:two'):
            response = await self.cancel(turn, owner)
            self.assertEqual(response.status_code, 404)
            self.assertFalse(turn.cancelled)
        response = await self.cancel(turn, 'account:two', account_session)
        self.assertEqual(response.status_code, 404)
        response = await self.cancel(turn, 'guest:two', other)
        self.assertFalse(response.json()['cancelled'])
        response = await self.client.post(f'/api/chat/session/{self.session}/cancel', params={'turn_id': 'old-turn'})
        self.assertFalse(response.json()['cancelled'])
        self.assertFalse(turn.cancelled)
        self.assertTrue((await self.cancel(turn)).json()['cancelled'])
        await stream.aclose()

    async def test_cancel_during_save_rolls_back_and_repairs_ahead_checkpoint(self):
        entered, release = threading.Event(), threading.Event()
        def delayed_measure(data, meta, *args, **kwargs):
            entered.set()
            release.wait(5)
            return meta
        self.release.set()
        try:
            with patch('app.services.resume_capacity.revalidate_committed_page_check', side_effect=delayed_measure):
                turn, stream = await self.start_turn()
                self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                pending = asyncio.create_task(self.cancel(turn))
                # Cancel endpoint needs a scheduling turn before the worker resumes.
                for _ in range(50):
                    if turn.cancelled:
                        break
                    await asyncio.sleep(.001)
                self.assertTrue(turn.cancelled)
                release.set()
                self.assertTrue((await asyncio.wait_for(pending, 3)).json()['cancelled'])
                await stream.aclose()
            self.assertEqual(session_store.load_resume_session(self.session)['resume_data'], self.old)
            self.assertEqual((await self.compiled.aget_state(self.config)).values['resume_data'], self.old)
            self.assertFalse(turn.committed)
        finally:
            release.set()

    async def test_committed_turn_cannot_report_a_successful_cancellation(self):
        turn = ChatTurn(self.session, 'finished', 'guest:one')
        token = current_turn.set(turn)
        try:
            await asyncio.to_thread(session_store.save_resume_session, self.session, self.old, stage='EVALUATING')
        finally:
            current_turn.reset(token)
        self.assertTrue(turn.committed)
        self.assertFalse(turn.cancel())
        self.assertFalse(turn.cancelled)

    async def test_cancelled_turn_cannot_commit_an_unfinished_intake_transaction(self):
        turn = ChatTurn(self.session, 'intake', 'guest:one')
        turn.cancel()
        token = current_turn.set(turn)
        try:
            with self.assertRaises(TurnCancelled):
                await asyncio.to_thread(session_store.save_candidate_intake, self.session, {'skills': ['Redis']}, {}, 'COLLECTING')
        finally:
            current_turn.reset(token)
        self.assertEqual(session_store.load_resume_session(self.session)['collected_info'], self.old_facts)

    async def test_cancel_before_producer_start_never_enters_upstream(self):
        turn = ChatTurn(self.session, 'early', 'guest:one')
        self.assertTrue(turn.cancel())
        async def source():
            self.fail('cancelled turn must not start another LLM call')
            yield ''
        events = [event async for event in chat._complete_on_disconnect(source(), turn)]
        self.assertIn('cancelled', ''.join(events))
        self.assertTrue(turn.done.is_set())


if __name__ == '__main__':
    unittest.main()
