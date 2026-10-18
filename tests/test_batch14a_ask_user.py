import shutil
"""第十四批 a：工具流、永久关闭、历史恢复及实际写作参数，全部用桩。"""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.agents import resume_graph as graph  # noqa: E402
from app.agents.interviewer import question_candidates, open_questions  # noqa: E402
from app.agents.public_reply import stream_public_reply  # noqa: E402
from app.agents.triage_chain import TriageAction, TriageDecision  # noqa: E402
from app.services.ask_user import (  # noqa: E402
    Answers, AskUser, close_answers, is_closed, pending_card,
                                   question_context, validate_card)
from app.services.resume_workspace import build_workspace  # noqa: E402
import test_conversations as history_fixture  # noqa: E402
import test_structure_plan as plan_fixture  # noqa: E402
import test_writing_upgrade as style_fixture  # noqa: E402


QUESTION = {'id': 'adoption', 'prompt': '多少人在用？', 'kind': 'single', 'options': ['仅自己', '有人使用'], 'allow_other': True}
STATUS = {'id': 'status', 'prompt': '现在什么状态？', 'kind': 'single', 'options': ['原型能跑', '已上线']}


def project_state():
    return {**graph._init_state(), 'stage': 'COLLECTING', 'candidate_history_reconciled': True,
            'intake_stage': 'ready', 'resume_versions': [{'id': 'existing-draft'}],
            'jd_info': {'job_title': 'AI 产品经理', 'role_profile': {'role_family': 'ai-pm'}},
            'collected_info': {'projects': [{'item_id': 'p1', 'name': 'AI 简历项目', 'facts': [
                {'id': 'f1', 'kind': 'action', 'text': '独立开发 AI 简历项目，已上线',
                 'source_quote': '独立开发 AI 简历项目，已上线', 'status': 'active', 'source': 'chat'}]}]}}


def with_card(questions=None):
    state = project_state()
    card = validate_card({'subject': 'AI 简历项目', 'questions': questions or [QUESTION]}, state, 'ask-turn')
    state['messages'] = [HumanMessage(content='个人开发的 AI 简历项目，已经上线。'),
                         AIMessage(content='补充几项信息即可。', additional_kwargs={'ask_user': card})]
    return state


class ToolModel:
    def __init__(self, questions=None, *, gate=False, body='补充一点。', raw=None):
        self.questions = questions if questions is not None else [QUESTION, STATUS]
        self.body = body
        self.raw = raw
        self.release = asyncio.Event()
        if not gate:
            self.release.set()
        self.finished = False
        self.tools = []
        self.messages = []

    def bind_tools(self, tools, **kwargs):
        self.tools = tools
        assert kwargs == {'tool_choice': 'auto'}
        return self

    async def astream(self, messages):
        self.messages = messages
        yield AIMessageChunk(content=self.body[:2])
        await self.release.wait()
        yield AIMessageChunk(content=self.body[2:])
        if self.questions is not False:
            args = self.raw if self.raw is not None else json.dumps({'subject': 'AI 简历项目', 'questions': self.questions}, ensure_ascii=False)
            for index, offset in enumerate(range(0, len(args), 7)):
                yield AIMessageChunk(content='', tool_call_chunks=[{'index': 0, 'id': 'tool-1' if index == 0 else None,
                    'name': 'ask_user' if index == 0 else None, 'args': args[offset:offset + 7]}])
        self.finished = True


class AskValidationTest(unittest.TestCase):
    def test_schema_and_per_question_strict_validation(self):
        self.assertEqual(AskUser.model_json_schema()['properties']['questions']['maxItems'], 4)
        bad = [
            {**QUESTION, 'prompt': '长' * 41}, {**QUESTION, 'kind': 'select'},
            {**QUESTION, 'id': 'with spaces'}, {**QUESTION, 'options': ['唯一']},
            {**QUESTION, 'options': ['同样', '同样']}, {**QUESTION, 'options': ['项' + str(i) for i in range(7)]},
            {**QUESTION, 'allow_other': 'true'}, {**QUESTION, 'extra': 1},
        ]
        for question in bad:
            with self.subTest(question=question):
                card = validate_card({'questions': [question, STATUS]}, {}, 'turn')
                self.assertEqual([row['id'] for row in card['questions']], ['status'])
        for args in ({'questions': []}, {'questions': [QUESTION] * 5}, {'questions': [QUESTION], 'subject': 123}, 'invalid'):
            self.assertEqual(validate_card(args, {}, 'turn'), {})

    def test_unknown_skipped_and_answered_close_id_and_dimension(self):
        for flag in ('unknown', 'skipped', 'answered'):
            state = with_card()
            item = {'id': 'adoption', 'value': '仅自己' if flag == 'answered' else ''}
            if flag != 'answered':
                item[flag] = True
            state['closed_questions'] = close_answers(state, '可读消息', {'turn_id': 'ask-turn', 'items': [item]})
            self.assertEqual(state['closed_questions'][0]['reason'], flag)
            self.assertFalse(pending_card(state))
            for question in (QUESTION, {**QUESTION, 'id': 'users', 'prompt': '使用人数有多少？'},
                             {**QUESTION, 'id': 'users_two', 'prompt': '用户数是多少？'}):
                self.assertFalse(validate_card({'subject': 'AI 简历项目', 'questions': [question]}, state, 'next'))
            self.assertTrue(validate_card({'subject': '另一个项目', 'questions': [QUESTION]}, state, 'next'))
            self.assertIn('closed_questions', question_context(state))

    def test_free_text_unknown_single_question_and_ambiguous_multi(self):
        for text in ('不知道', '不清楚', '跳过', '没数字'):
            self.assertEqual(len(close_answers(with_card(), text)), 1)
        self.assertEqual(close_answers(with_card([QUESTION, STATUS]), '不知道'), [])
        state = project_state()
        state['messages'] = [AIMessage(content='「AI 简历项目」多少人在用？')]
        closed = close_answers(state, '不知道')
        self.assertEqual(closed[0]['dimension'], 'adoption')
        self.assertEqual(closed[0]['subject'], 'p1')
        state['messages'] = [AIMessage(content='多少人在用？现在什么状态？')]
        self.assertEqual(close_answers(state, '不知道'), [])

    def test_stale_turn_and_unrelated_ids_cannot_close_other_dimensions(self):
        state = with_card()
        self.assertEqual(close_answers(state, '不知道', {'turn_id': 'stale', 'items': [{'id': 'adoption', 'unknown': True}]}), [])
        closed = close_answers(state, '回答', {'turn_id': 'ask-turn', 'items': [{'id': 'invented', 'value': 'x'}]})
        self.assertEqual([row['id'] for row in closed], ['adoption'])
        self.assertEqual(closed[0]['reason'], 'skipped')
        with self.assertRaises(ValidationError):
            Answers.model_validate({'turn_id': 'turn', 'items': [{'id': 'adoption', 'unknown': 'true'}]})

    def test_interviewer_and_missing_fields_respect_closed_dimensions(self):
        state = with_card()
        state['closed_questions'] = close_answers(state, '不知道')
        state['resume_data'] = {'projects': [{'item_id': 'p1', 'name': 'AI 简历项目', 'polished_bullets': ['独立开发，已上线']} ]}
        state['match_plan'] = {'questions': [{'q': '用户数是多少？', 'improves': {'item_id': 'p1'}, 'value': 5}]}
        self.assertNotIn('用户数', str(question_candidates(state)))
        self.assertEqual(open_questions(state), [])
        state['closed_questions'].append({'subject': 'p1', 'id': 'my_work', 'dimension': 'my_work'})
        view = build_workspace(state, state['resume_data'])
        self.assertNotIn('你的职责与分工', view['experiences']['items'][0]['missing'])
        self.assertNotIn('用户数', str(view['guidance']))
        self.assertEqual(view['tailor']['questions'], [])

    def test_pending_plan_wins_over_tool_card(self):
        state = with_card()
        state['pending_plan'] = plan_fixture.card()
        self.assertFalse(validate_card({'questions': [QUESTION]}, state, 'next'))
        self.assertEqual(build_workspace(state)['guidance']['kind'], 'structure_plan')

    def test_plain_question_never_creates_card(self):
        state = project_state()
        state['messages'] = [HumanMessage(content='继续'), AIMessage(content='多少人在用？')]
        self.assertIsNone(build_workspace(state)['guidance'])

    @unittest.skipUnless(shutil.which('node'), 'node is not installed')

    def test_frontend_dom_behaviors(self):
        result = subprocess.run(['node', str(ROOT / 'tests/ask_user.dom.js')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class ToolStreamTest(unittest.IsolatedAsyncioTestCase):
    async def test_stream_chunk_parser_keeps_text_and_valid_questions(self):
        model = ToolModel([QUESTION, {**STATUS, 'prompt': '长' * 41}])
        response = await stream_public_reply(model, [], ask_state=project_state())
        self.assertEqual(response.content, model.body)
        self.assertEqual([q['id'] for q in response.additional_kwargs['ask_user']['questions']], ['adoption'])
        self.assertEqual(model.tools[0]['function']['name'], 'ask_user')
        self.assertIn('不复述题干', model.messages[-1].content)

    async def test_all_invalid_or_invalid_json_never_fail_turn(self):
        for raw in ('{"questions":[{"id":"invalid"}]}', '{"questions":', '{"questions":[]}'):
            model = ToolModel(raw=raw, body='')
            reply = await stream_public_reply(model, [], ask_state={})
            self.assertNotIn('ask_user', reply.additional_kwargs)
            self.assertEqual(reply.content, '')

    async def test_does_not_rewrite_duplicate_questions_in_prose(self):
        text = '多少人在用？现在什么状态？'
        reply = await stream_public_reply(ToolModel(body=text), [], ask_state={})
        self.assertEqual(reply.content, text)
        self.assertTrue(reply.additional_kwargs['ask_user'])

    async def test_non_streaming_tool_adapter_and_pending_plan(self):
        class Model:
            def bind_tools(self, *args, **kwargs):
                return self

            async def ainvoke(self, messages):
                return AIMessage(content='补充一点。', tool_calls=[{'name': 'ask_user', 'args': {'questions': [QUESTION]}, 'id': 'call'}])
        self.assertTrue((await stream_public_reply(Model(), [], ask_state={})).additional_kwargs['ask_user'])
        self.assertNotIn('ask_user', (await stream_public_reply(Model(), [], ask_state={'pending_plan': {'x': 1}})).additional_kwargs)

    async def test_first_token_before_tool_completion_in_actual_graph(self):
        model = ToolModel(gate=True)
        compiled = graph.build_graph(model)
        config = {'configurable': {'thread_id': 'b14-stream'}}
        await compiled.aupdate_state(config, project_state(), as_node='collecting')
        with patch.object(graph, 'get_graph', return_value=compiled), \
             patch.object(graph, '_make_non_streaming_llm', side_effect=lambda model, **kwargs: model), \
             patch.object(graph, '_extract_info_from_message', AsyncMock(return_value=project_state()['collected_info'])), \
             patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(action=TriageAction.ASK_EXPERIENCE, reason='桩'))), \
             patch('app.agents.interviewer.first_draft_ready', return_value=False), \
             patch('app.services.session_store.save_candidate_intake'), patch('app.services.session_store.save_resume_session'):
            stream = graph.stream_agent([{'content': '个人开发的 AI 简历项目，已上线。'}], 'b14-stream', model)
            first = await asyncio.wait_for(anext(stream), 2)
            self.assertEqual(first, '补充')
            self.assertFalse(model.finished)
            model.release.set()
            text = first + ''.join([part async for part in stream])
            current = (await compiled.aget_state(config)).values
        self.assertEqual(text, '补充一点。')
        self.assertEqual(build_workspace(current)['guidance']['kind'], 'ask_user')

    async def test_post_writer_candidates_go_to_model_without_duplicate_card(self):
        state = project_state()
        result = {'resume_data': {'projects': [{'item_id': 'p1', 'name': 'AI 简历项目'}]},
                  'match_plan': {'questions': [{'q': '多少人在用？', 'improves': {'item_id': 'p1'}, 'value': 5}]}}
        reply = await graph._model_followup(state, result, ToolModel())
        self.assertTrue(reply.additional_kwargs['ask_user'])
        self.assertNotIn('多少人', reply.content)
        view = build_workspace({**state, **result, 'messages': [reply]})
        self.assertEqual(view['tailor']['questions'], [])
        self.assertEqual(view['guidance']['kind'], 'ask_user')

    async def test_tool_and_open_question_keep_answer_ownership_without_rewriting(self):
        state = project_state()
        for question in (True, False):
            model = ToolModel([QUESTION] if question else False, body='「AI 简历项目」怎么实现的？')
            reply = await stream_public_reply(model, [], ask_state=state)
            finished = graph._finish_followup_turn(state, {'messages': [reply]})
            self.assertEqual(finished['messages'][0].content, reply.content)
            self.assertEqual(finished['collected_info']['followup_target']['item_id'], 'p1')
            context = graph._latest_previous_assistant(finished['messages'])
            if question:
                self.assertIn('多少人在用？', context)

    async def test_labeled_confirmation_reaches_real_writer_payload(self):
        current = {**plan_fixture.state('按推荐写，写法：问题-决策-结果'),
                   'pending_plan': plan_fixture.card(), 'plan_choice': {'option': '按推荐写', 'bullet_style': 'labeled'}}
        model = plan_fixture.FakeModel([('WriterDraft', plan_fixture.writer_draft())])
        with patch.object(plan_fixture.get_settings(), 'LLM_PLAN_CONFIRM', True), \
             patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={'status': 'rendered', 'pages': 1, 'page_limit': 1, 'within_page_limit': True}), \
             patch('app.agents.resume_writer.guard_bullets', side_effect=plan_fixture.lexical_guard), \
             patch('app.services.fact_guard.verify_semantics', AsyncMock(side_effect=lambda pairs, *args, **kwargs: {row['id']: {'verdict': 'pass'} for row in pairs})):
            self.assertEqual(graph.route_by_stage(current), 'structure_plan')
            result = await graph.structure_plan_node(current, model)
        messages = next(messages for name, messages in model.calls if name == 'WriterDraft')
        self.assertIn('"bullet_style": "labeled"', messages[-1].content)
        self.assertEqual(result['confirmed_plan']['bullet_style'], 'labeled')
        self.assertEqual(result['match_plan']['bullet_style'], 'labeled')
        self.assertFalse(result['pending_plan'])
        self.assertNotEqual((build_workspace({**current, **result})['guidance'] or {}).get('kind'), 'structure_plan')

    async def test_labeled_confirmation_formats_project_body(self):
        current = {**graph._init_state(), 'stage': 'BUILDING', 'collected_info': style_fixture.evidence(),
                   'pending_plan': style_fixture.plan_card(), 'jd_info': {'role_profile': {'role_family': 'ai_pm'}},
                   'messages': [HumanMessage(content='按推荐写，写法：问题-决策-结果')],
                   'plan_choice': {'option': '按推荐写', 'bullet_style': 'labeled'}}
        with patch.object(plan_fixture.get_settings(), 'LLM_PLAN_CONFIRM', True), \
             patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={'status': 'rendered', 'pages': 1, 'page_limit': 1, 'within_page_limit': True}):
            result = await graph.structure_plan_node(current, style_fixture.PlanModel([('WriterDraft', style_fixture.draft())]))
        bullets = result['resume_data']['projects'][0]['polished_bullets']
        self.assertEqual([line.split('：')[0] for line in bullets], ['问题', '决策', '现状'])
        self.assertEqual(result['resume_meta']['confirmed_plan']['bullet_style'], 'labeled')
        self.assertFalse(result['pending_plan'])

    async def test_advisor_does_not_repeat_closed_missing_dimension(self):
        from app.agents import advisor
        state = with_card()
        state['closed_questions'] = close_answers(state, '不知道')
        state['resume_data'] = {'projects': [{'item_id': 'p1', 'name': 'AI 简历项目', 'polished_bullets': ['独立开发，已上线']} ]}
        response = advisor.AdvisorOutput(issues=[advisor.AdviceIssue(location='/projects/0', issue='缺少用户数',
            action='补充使用人数', action_kind='ask')])
        model = type('AdvisorStub', (), {'ainvoke': AsyncMock(return_value=response)})()
        with patch.object(advisor, 'with_structured_output', return_value=model):
            result = await advisor.review_with_advisor(state, object())
        self.assertEqual(result['issues'], [])
        self.assertNotIn('用户数', result['text'])
        prompt = str(model.ainvoke.call_args.args[0])
        self.assertIn('closed_questions', prompt)
        self.assertIn('adoption', prompt)


class AskHistoryTest(unittest.IsolatedAsyncioTestCase):
    # 复用已有隔离 SQL/checkpoint/ASGI fixture，不继承其测试，避免重复计数。
    asyncSetUp = history_fixture.ConversationPersistenceTest.asyncSetUp
    open_checkpointer = history_fixture.ConversationPersistenceTest.open_checkpointer
    cleanup = history_fixture.ConversationPersistenceTest.cleanup
    create = history_fixture.ConversationPersistenceTest.create
    checkpoint = history_fixture.ConversationPersistenceTest.checkpoint

    async def test_real_sse_unknown_then_synonym_filtered_and_sqlite_refresh(self):
        model = ToolModel([QUESTION])
        self.graph = graph.build_graph(model, checkpointer=self.saver)
        sid = await self.create()
        await self.checkpoint(sid, **project_state())
        with patch('app.api.chat._get_llm', return_value=model), patch.object(graph, 'get_graph', return_value=self.graph), \
             patch('app.api.chat.get_graph', return_value=self.graph), \
             patch.object(graph, '_make_non_streaming_llm', side_effect=lambda model, **kwargs: model), \
             patch.object(graph, '_extract_info_from_message', AsyncMock(return_value=project_state()['collected_info'])), \
             patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(action=TriageAction.ASK_EXPERIENCE, reason='桩'))), \
             patch('app.agents.interviewer.first_draft_ready', return_value=False):
            first = await self.client.post('/api/chat/stream', json={'session_id': sid, 'messages': [{'role': 'user', 'content': '我个人开发的 AI 简历项目已上线。'}]})
            events = [json.loads(line[6:]) for line in first.text.splitlines() if line.startswith('data: {')]
            self.assertFalse(any('error' in event for event in events), first.text)
            self.assertEqual(''.join(row.get('content', '') for row in events), '补充一点。')
            card = next(row['workspace']['guidance'] for row in events if row.get('type') == 'meta')
            detail = (await self.client.get('/api/chat/conversations/' + sid)).json()
            self.assertEqual(detail['workspace']['guidance'], card)
            model.questions = [{**QUESTION, 'id': 'user_count', 'prompt': '使用人数有多少？'}, STATUS]
            second = await self.client.post('/api/chat/stream', json={'session_id': sid,
                'messages': [{'role': 'user', 'content': '多少人在用：不知道'}],
                'answers': {'turn_id': card['turn_id'], 'items': [{'id': 'adoption', 'value': '', 'unknown': True}]}})
            self.assertNotIn('"error"', second.text)
        # 关闭并重新打开持久 checkpoint，模拟页面刷新与进程重建。
        await self.saver_context.__aexit__(None, None, None)
        await self.open_checkpointer()
        detail = (await self.client.get('/api/chat/conversations/' + sid)).json()
        self.assertEqual([q['id'] for q in detail['workspace']['guidance']['questions']], ['status'])
        values = (await self.graph.aget_state({'configurable': {'thread_id': sid}})).values
        self.assertTrue(is_closed(values, 'AI 简历项目', 'any', '用户数是多少？'))
        self.assertIn('unknown', str(values['closed_questions']))
        self.assertIn('多少人在用：不知道', str(detail['messages']))

    async def test_submitted_card_never_reappears_without_new_tool_call(self):
        sid = await self.create()
        values = with_card()
        await self.checkpoint(sid, **values)
        before = (await self.client.get('/api/chat/conversations/' + sid)).json()
        self.assertEqual(before['workspace']['guidance']['kind'], 'ask_user')
        closed = close_answers(values, '跳过', {'turn_id': 'ask-turn', 'items': [{'id': 'adoption', 'skipped': True}]})
        await self.graph.aupdate_state({'configurable': {'thread_id': sid}}, {'closed_questions': closed,
            'messages': [HumanMessage(content='跳过'), AIMessage(content='按现有信息继续。')]}, as_node='collecting')
        after = (await self.client.get('/api/chat/conversations/' + sid)).json()
        self.assertIsNone(after['workspace']['guidance'])
