"""Authorized real inputs; offline scripted extractor/writer, graph and replay."""
import asyncio
from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
from langchain_core.messages import AIMessageChunk  # noqa: E402
from app.agents import resume_graph as graph  # noqa: E402
from app.agents.fact_extractor import apply_fact_patch, extract_facts_patch  # noqa: E402
from app.agents.resume_writer import run_resume_writer  # noqa: E402
from app.agents.triage_chain import TriageAction, TriageDecision  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.schemas.writer import LABELED_SEMANTICS, LABELED_SELECTION, LENIENT_SCHEMAS, WriterDraft  # noqa: E402
from app.services.resume_versions import text_hash  # noqa: E402
from app.services.resume_workspace import build_workspace  # noqa: E402
from app.services.writing_style import format_rows  # noqa: E402
from test_batch14b_intake import FlowModel, PAGES  # noqa: E402
from test_campus_and_naming import ExtractorStub, raw  # noqa: E402
from test_fact_guard import decision  # noqa: E402
from test_resume_writer import fact  # noqa: E402
import test_persona_runner as http_stub  # noqa: E402

REAL = import_module('evaluation.persona-ux.aipm_real')
RUNNER = import_module('evaluation.persona-ux.run_persona')
REPORT = import_module('evaluation.persona-ux.report')
QUESTIONS = [
    {'id': 'usage', 'prompt': '这个工具现在有多少人在用？', 'kind': 'single',
     'options': ['没有人用', '100 人以上'], 'allow_other': True},
    {'id': 'eval', 'prompt': '如何验证输出？', 'kind': 'text'},
    {'id': 'badcase', 'prompt': '效果不好时怎么改？', 'kind': 'text'},
    {'id': 'tech_stack', 'prompt': '用了什么技术栈？', 'kind': 'text'},
]
GOOD = [
    '问题：简历填表繁琐；AI 优化后的经历仍需复制粘贴。',
    '决策：接入 MCP，支持用户用自己的 AI 操作简历工具。',
    '现状：流程已贯通并上线可用；使用人数为 10 人，生成简历与使用体验仍在优化。',
]


def final_turn(bullets=None):
    bullets = list(GOOD if bullets is None else bullets)
    return {'action': 'plan_confirm', 'input': '按推荐写', 'status': 'ok', 'sse_done': True,
            'stage': 'EVALUATING', 'revision': 'draft',
            'resume_data': {'projects': [{'item_id': 'p', 'name': '胡话简历', 'start_date': '2025-09',
                'end_date': '至今', 'positioning': '简历制作工具', 'project_type': '个人项目', 'polished_bullets': bullets}]},
            'workspace': {'tailor': {'resume_meta': {'writer_diagnostic': {'status': 'model_completed'},
                'bullets': {'p': [{'fact_ids': ['fact'], 'text_hash': text_hash(b)} for b in bullets]}}}}}


def scripted_turns():
    card = {'kind': 'ask_user', 'turn_id': 'actual-card', 'subject': 'p', 'questions': QUESTIONS}
    result = [{'action': f'initial_{i}', 'input': text, 'status': 'ok', 'sse_done': True, 'workspace': {}}
              for i, text in enumerate(REAL.FIRST_TURNS, 1)]
    result[-1]['workspace'] = {'guidance': card}
    _, text, payload = REAL.submission({'guidance': card})
    result.append({'action': 'answers_1', 'input': text, **payload, 'status': 'ok', 'sse_done': True,
        'workspace': {'guidance': {'kind': 'structure_plan', 'options': [{'label': '按推荐写', 'value': '按推荐写'}]}}})
    result.append(final_turn())
    return result


def checks(turns):
    return {r['id'].removeprefix('aipm_real.'): r['status'] for r in REAL.evaluate_persona('aipm_real', turns)}


class RealChecksTests(unittest.TestCase):
    def test_good_draft_passes_all_new_checks(self):
        self.assertEqual(set(checks(scripted_turns()).values()), {'pass'})
        self.assertEqual(len(checks(scripted_turns())), 11)

    def test_old_copied_draft_fails_and_preview_cannot_pass_quality(self):
        turns = scripted_turns()
        turns[-1] = final_turn(['解决了普通简历工具一个一个填空非常繁琐',
                               '甚至要用户自己用ai工具复制粘体优化过的经历'])
        turns[-1]['resume_data']['projects'][0]['name'] = '项目（待补名称）'
        result = checks(turns)
        for key in ('common.rounds_complete', 'heading', 'labels', 'real_pains', 'mcp_decision', 'no_placeholder', 'rewritten'):
            self.assertEqual(result[key], 'fail', key)
        # A named draft copying the full original paragraph also fails LCS,
        # independently of the missing name / delivery gate.
        turns[-1] = final_turn([REAL.FIRST_TURNS[-1], *GOOD[1:]])
        self.assertEqual(checks(turns)['rewritten'], 'fail')
        turns[-1] = final_turn()
        turns[-1]['workspace']['tailor']['resume_meta'].pop('bullets')
        for key in ('heading', 'real_pains', 'mcp_decision', 'rewritten'):
            self.assertEqual(checks(turns)[key], 'fail')

    def test_digits_chinese_metrics_and_wrong_owner_are_rejected(self):
        for text in ('现状：10 次调用。', '现状：使用人数为 10。', '现状：10 人团队开发工具。',
                     '现状：10 人付费使用。', '现状：使用人数为 100 人。', '迭代：回放五个求职者对话。',
                     '现状：使用人数为 10 人，准确率 10%。'):
            with self.subTest(text=text):
                turns = scripted_turns()
                turns[-1] = final_turn([*GOOD[:2], text])
                result = checks(turns)
                self.assertTrue(result['adoption_unit_and_owner'] == 'fail' or result['no_invented_metrics'] == 'fail')
        turns = scripted_turns()
        turns[-2]['answers']['items'][0]['unknown'] = True
        self.assertEqual(checks(turns)['no_invented_metrics'], 'fail')
        turns[-1]['resume_data']['projects'][0]['positioning'] = '100 人使用的工具'
        self.assertEqual(checks(turns)['no_invented_metrics'], 'fail')
        turns = scripted_turns()
        turns[-1]['resume_data']['work_experience'] = [{'bullets': ['完成71条断言检查']}]
        self.assertEqual(checks(turns)['no_invented_metrics'], 'fail')

    def test_unknown_is_closed_across_id_and_subject_aliases(self):
        turns = scripted_turns()
        turns[-2]['workspace'] = {'guidance': {'kind': 'ask_user', 'subject': '胡话简历',
            'questions': [{'id': 'new-evaluation', 'prompt': '如何评估？', 'kind': 'text'}]}}
        self.assertEqual(checks(turns)['unknown_not_reasked'], 'fail')

    def test_answer_bank_never_borrows_synthetic_facts(self):
        for dimension in ('eval', 'iteration', 'badcase', 'tech_stack', 'links', 'revenue'):
            self.assertEqual(REAL.answer({'id': dimension, 'prompt': '', 'kind': 'text'}),
                             {'id': dimension, 'value': '', 'unknown': True})
        for dimension, value in REAL.VALUES.items():
            self.assertFalse(REAL.answer({'id': dimension, 'prompt': '', 'kind': 'text'})['unknown'])
        q = QUESTIONS[0]
        self.assertEqual(REAL.answer(q)['value'], '10 人')
        for option in ('1–10 人', '10-50 人', '10 人'):
            self.assertEqual(REAL.answer({**q, 'options': [option]})['value'], option)
        for option in ('10 人付费使用', '日活 10 人', '11-50 人', '10 人团队', '10 次调用'):
            self.assertEqual(REAL.answer({**q, 'options': [option]})['value'], '10 人')
        self.assertTrue(REAL.answer({**q, 'allow_other': False})['unknown'])
        chosen = REAL.answer({'id': 'status', 'prompt': '', 'kind': 'multi',
            'options': ['整个流程已经打通了', '已经上线了可以正常使用', '公网可访问'], 'allow_other': True})
        self.assertNotIn('公网可访问', chosen['value'])

    def test_replay_preserves_four_raw_rounds_and_binds_actual_cards(self):
        requests = []
        responses = [{'workspace': {}} for _ in range(3)] + [
            {'workspace': {'guidance': {'kind': 'intake_experiences', 'items': [{'name': '项目（待补名称）', 'item_id': 'p'}]}}},
            {'workspace': {'guidance': {'kind': 'ask_user', 'turn_id': 'dynamic', 'questions': QUESTIONS}}},
            {'workspace': {'guidance': {'kind': 'intake_basics'}}},
            {'workspace': {'guidance': {'kind': 'structure_plan', 'options': [{'label': '按推荐写', 'value': '推荐确认值'}]}}}, final_turn()]
        class Client:
            def turn(self, action, text, **payload):
                response = responses[len(requests)]
                requests.append((text, payload))
                return {'status': 'ok', 'sse_done': True, **response, 'action': action, 'input': text, **payload}
        turns = list(REAL.replay(Client()))
        self.assertEqual([r[0] for r in requests[:4]], REAL.FIRST_TURNS)
        self.assertTrue(all(not r[1] for r in requests[:4]))
        self.assertEqual(requests[4][1]['intake']['items'][0]['item_id'], 'p')
        self.assertEqual(requests[5][1]['answers']['turn_id'], 'dynamic')
        self.assertTrue(requests[6][1]['intake']['skipped'])
        self.assertEqual(requests[7][0], '推荐确认值')
        self.assertTrue(all(r['status'] == 'pass' for r in REAL.evaluate_persona('aipm_real', turns)))

    def test_runner_registers_real_persona_and_report_keeps_independent_checks(self):
        expected = [{'resume_data': {}, 'reply': '', **t} for t in scripted_turns()]
        # Existing socketpair transport exercises urllib/JSON/cookies/SSE;
        # HTTPConnection.connect is replaced, so no TCP listener is contacted.
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(http_stub, 'golden_turns', return_value=expected), \
                http_stub.stub_server(('aipm_real',), plans=False) as (_, state):
            run = RUNNER.run_replay('http://127.0.0.1:9', Path(directory) / 'run', ['aipm_real'])
            self.assertEqual(run['status'], 'pass')
            self.assertIn('aipm_real_fixture_sha256', run)
            self.assertEqual(len(REPORT.result_index(run)), 11)
            self.assertIn('aipm_real.mcp_decision', REPORT.render_report([run]))
            payloads = [r['payload'] for r in state['requests']]
            self.assertEqual([p['messages'][0]['content'] for p in payloads[:4]], REAL.FIRST_TURNS)
            self.assertEqual(payloads[4]['answers']['items'][0]['value'], '10 人')


class RealModel(FlowModel):
    def __init__(self):
        super().__init__()
        self.writer_inputs = []

    async def astream(self, messages):
        last = messages[-1].content
        context = json.loads(last.split('分阶段规则优先于旧候选：\n')[1]) if '分阶段规则优先于旧候选：\n' in last else {}
        yield AIMessageChunk(content='继续整理这段经历。')
        if context.get('subject'):
            yield AIMessageChunk(content='', tool_call_chunks=[{'index': 0, 'id': 'real-input-stub', 'name': 'ask_user',
                'args': json.dumps({'subject': context['subject'], 'questions': QUESTIONS}, ensure_ascii=False)}])

    def with_structured_output(self, schema):
        async def invoke(messages):
            data = json.loads(messages[-1].content)
            if schema.__name__ == 'SemanticBatch':
                return {'decisions': [decision(r['id']) for r in data]}
            if schema.__name__ == 'RepairOutput':
                return {'bullets': []}
            if schema.__name__ == 'StructurePlan':
                return {'recommended': {'label': '产品实践', 'section_order': ['projects'],
                    'experience_plan': [{'item_id': p['item_id'], 'treatment': 'lead', 'target_bullets': 3} for p in data['evidence']['projects']]}}
            if schema.__name__ == 'WriterDraft':
                self.writer_inputs.append(data)
                project = data['evidence']['projects'][0]
                def refs(*needles):
                    return [f['id'] for f in project['facts'] if any(n.casefold() in f['text'].casefold() for n in needles)]
                return {'items': [{'item_id': project['item_id'], 'section': 'projects',
                    'title': {'positioning': '简历制作工具', 'fact_ids': refs('简历')},
                    'bullets': [{'text': b, 'fact_ids': refs(*needles)} for b, needles in zip(GOOD, [
                        ['填空', '复制'], ['mcp'], ['上线', '流程', '效果', '10 人']])]}]}
            raise AssertionError(schema.__name__)
        return SimpleNamespace(ainvoke=invoke)


async def extract_real_stub(message, current, llm):
    candidate = {'items': []}
    if message == REAL.FIRST_TURNS[-1]:
        candidate['items'] = [{'section': 'projects', 'name': '项目（待补名称）', 'facts': [
            raw('解决了普通简历工具一个一个填空非常繁琐', kind='context'),
            raw('甚至要用户自己用ai工具复制粘体优化过的经历', kind='context'),
            raw('ai工具生成的简历格式无法微调经常给你一个pdf用户无法编辑', kind='context'),
            raw('甚至ai工具总是不知道简历的结构应该怎么样才好', kind='context'),
            raw('提示词原型都是我，这是我的个人开发项目', kind='role'),
            raw('现在已经能跑了整个流程已经打通了', kind='deliverable'),
            raw('但是出的简历和使用过程中的效果可能差点意思', kind='status_limit'),
            raw('所以还在优化但是已经上线了可以正常使用', kind='status_limit'),
            raw('也接入了mcp可以使用用户自己的ai来使用这样的一个工具'),
        ], 'raw_notes': [message]}]
    return apply_fact_patch(current, await extract_facts_patch(message, current, ExtractorStub(candidate)))


class RealGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_inputs_through_graph_stream_cards_and_writer(self):
        model = RealModel()
        compiled = graph.build_graph(model)
        async def triage(user_message, **kwargs):
            if user_message == REAL.FIRST_TURNS[0]:
                return TriageDecision(action=TriageAction.ASK_EXPERIENCE, reason='从零聊经历')
            if user_message == REAL.FIRST_TURNS[1]:
                return TriageDecision(action=TriageAction.SKIP_JD_OK, jd_keywords=['AI产品'], reason='本人目标方向')
            return TriageDecision(action=TriageAction.READY_TO_BUILD, reason='阶段门槛负责推进')
        for context in (
            patch.object(graph, 'get_graph', return_value=compiled),
            patch.object(graph, '_make_non_streaming_llm', side_effect=lambda model, **kwargs: model),
            patch.object(graph, '_extract_info_from_message', side_effect=extract_real_stub),
            patch.object(graph, 'run_triage', side_effect=triage),
            patch('app.services.session_store.save_candidate_intake'), patch('app.services.session_store.save_resume_session'),
            patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value=PAGES),
            patch.object(get_settings(), 'LLM_PLAN_CONFIRM', True),
        ):
            self.enterContext(context)
        states = []
        async def turn(action, text, **payload):
            extra = {k: v for k, v in payload.items() if k in {'intake', 'answers'}}
            events = [e async for e in graph.stream_agent([{'role': 'user', 'content': text}], 'aipm-real-c3', model, **extra)]
            self.assertNotIn('"error"', str(events))
            state = (await compiled.aget_state({'configurable': {'thread_id': 'aipm-real-c3'}})).values
            states.append(state)
            return {'action': action, 'input': text, **payload, 'status': 'ok', 'sse_done': True,
                'revision': text_hash(json.dumps(state.get('resume_data') or {}, ensure_ascii=False)),
                'resume_data': deepcopy(state.get('resume_data') or {}),
                'workspace': build_workspace(state, state.get('resume_data') or {}), 'stage': state.get('stage', 'JD_INPUT')}
        loop = asyncio.get_running_loop()
        class Client:
            def turn(self, *args, **kwargs):
                return asyncio.run_coroutine_threadsafe(turn(*args, **kwargs), loop).result(timeout=30)
        turns = await asyncio.to_thread(lambda: list(REAL.replay(Client())))
        result = REAL.evaluate_persona('aipm_real', turns)
        Path('/private/tmp/huhua-b14c3-aipm-real-stub.json').write_text(json.dumps(
            {'source': 'authorized real inputs, offline model doubles', 'turns': turns, 'checks': result}, ensure_ascii=False, indent=2))
        self.assertTrue(all(r['status'] == 'pass' for r in result), result)
        self.assertEqual([t['input'] for t in turns[:4]], REAL.FIRST_TURNS)
        self.assertTrue(model.writer_inputs)
        self.assertEqual(len(states[-1]['collected_info']['projects']), 1)
        self.assertEqual(states[-1]['resume_data']['projects'][0]['project_type'], '个人项目')
        self.assertFalse(states[-1]['resume_meta'].get('guard_fallbacks'))
        facts = states[-1]['collected_info']['projects'][0]['facts']
        self.assertTrue(any(f.get('dimension') == 'adoption' and f['text'] == '10 人' for f in facts))
        self.assertFalse(any(f.get('dimension') in {'evaluation', 'iteration', 'tech_stack'} for f in facts))


class LabeledWriterTests(unittest.IsolatedAsyncioTestCase):
    def test_source_classification_never_promotes_tools_or_ownership_to_decision(self):
        texts = ['独立完成从需求到开发的全流程', '直接调用大模型 API，借助 Cursor/Claude Code 开发',
                 '接入 MCP，让用户使用自己的 AI', '先体验后登录', '用71条断言自动检查成稿，回放5个虚拟求职者',
                 '已上线，公网可访问', '已有10人使用']
        facts = {str(i): fact(str(i), t, kind='method_tool' if i == 1 else 'action') for i, t in enumerate(texts)}
        for family in ('ai_pm', 'other'):
            rows = format_rows([{'text': t, 'fact_ids': [str(i)]} for i, t in enumerate(texts)], facts, 'labeled', role_family=family)
            decisions = [r['text'] for r in rows if r['text'].startswith(('决策：', '关键决策：'))]
            self.assertTrue(any('MCP' in t for t in decisions))
            self.assertTrue(any('先体验后登录' in t for t in decisions))
            self.assertFalse(any('独立完成' in t or 'API' in t for t in decisions))
            self.assertTrue(any(r['text'].startswith('技术：') and 'API' in r['text'] for r in rows))
            self.assertTrue(any(r['text'].startswith('迭代：') and '71' in r['text'] for r in rows))
            self.assertTrue(any(r['text'].startswith('现状：') and '10人' in r['text'] for r in rows))

    def test_wire_schema_and_writer_contract_share_semantics_and_priority(self):
        from app.agents.resume_writer import _WRITE_CONTRACT, _ONE_PASS_CONTRACT
        for contract in (_WRITE_CONTRACT, _ONE_PASS_CONTRACT):
            self.assertIn(LABELED_SEMANTICS, contract)
            self.assertIn(LABELED_SELECTION, contract)
        for schema in (WriterDraft, LENIENT_SCHEMAS[WriterDraft]):
            wire = json.dumps(schema.model_json_schema(), ensure_ascii=False)
            for text in ('独立完成', '不是决策', '可访问性', '舍弃信息量最低', '不能补出原因或结果'):
                self.assertIn(text, wire)

    async def test_c2_facts_use_product_decision_and_prioritize_eval_and_launch(self):
        synthetic = import_module('evaluation.persona-ux.aipm')
        rows = [('problem', synthetic.VALUES['problem'], 'context'), ('work', synthetic.VALUES['my_work'], 'role'),
                ('decision', synthetic.VALUES['decision'], 'action'), ('tool', '；'.join(synthetic.VALUES['tech_stack']), 'method_tool'),
                ('eval', '；'.join(synthetic.VALUES['evaluation']), 'action'), ('iteration', synthetic.VALUES['iteration'], 'action'),
                ('launch', '现在已经上线了；公网可访问的链接', 'status_limit')]
        source = {'projects': [{'item_id': 'p', 'name': '胡话简历', 'start_date': '2026-08', 'end_date': '至今',
            'role': '独立开发者', 'facts': [fact(fid, text, kind=kind) for fid, text, kind in rows]}]}
        old = ['问题：针对学生难以梳理自身经历的问题，设计以对话挖掘可写进简历事实的产品方案。',
               '决策：独立完成从需求到开发的全流程，产出AI简历助手；直接调用大模型 API，借助 Cursor/Claude Code 等 AI 编程工具开发。',
               '迭代：换模型或调参数，并对比不同提示词或方案']
        emitted = ['决策：先通过对话梳理学生经历，再依据确认的事实写简历。',
                   '迭代：以71条断言自动核查成稿，回放5个虚拟求职者对话；对比提示词与方案。',
                   '现状：已上线，提供公网访问链接。']
        captured = []
        class Model(RealModel):
            def with_structured_output(self, schema):
                if schema.__name__ != 'WriterDraft':
                    return super().with_structured_output(schema)
                async def invoke(messages):
                    # Scripted contract consumer: legacy instructions reproduce
                    # c2's weak selection. New source contracts must reach the
                    # actual writer invocation, not be applied after output.
                    contract = messages[0].content
                    data = json.loads(messages[-1].content)
                    captured.append((contract, data))
                    tightened = LABELED_SEMANTICS in contract and LABELED_SELECTION in contract
                    texts = emitted if tightened else old
                    refs = [['decision'], ['eval'], ['launch']] if tightened else [['problem'], ['work', 'tool'], ['iteration', 'eval']]
                    return {'items': [{'item_id': 'p', 'section': 'projects', 'bullets': [
                        {'text': t, 'fact_ids': f} for t, f in zip(texts, refs)]}]}
                return SimpleNamespace(ainvoke=invoke)
        result = await run_resume_writer(source, {'role_family': 'ai_pm'}, Model(), phase='write', previous_plan={
            'bullet_style': 'labeled', 'experience_plan': [{'item_id': 'p', 'treatment': 'lead', 'target_bullets': 3}]})
        self.assertTrue(captured)
        body = result['resume_data']['projects'][0]['polished_bullets']
        self.assertLessEqual(len(body), 3)
        decision_rows = [t for t in body if t.startswith('决策：')]
        self.assertTrue(decision_rows, body)
        self.assertFalse(any(t in str(decision_rows) for t in ('独立完成', 'Cursor', 'API')))
        for text in ('71', '5', '断言', '回放', '公网', '上线'):
            self.assertIn(text, str(body))
        self.assertTrue(any(t.startswith('迭代：') and '71' in t for t in body))
        self.assertFalse(any(t.endswith('换模型或调参数') for t in body))
        self.assertFalse(result.get('guard_fallbacks'))


if __name__ == '__main__':
    unittest.main()
