"""第十四批 c：合成结构化输入走真实图；所有模型/语义返回均为本地桩。"""
from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
from langchain_core.messages import AIMessageChunk, HumanMessage  # noqa: E402
from app.agents import resume_graph as graph  # noqa: E402
from app.agents.resume_writer import run_resume_writer  # noqa: E402
from app.agents.triage_chain import TriageAction, TriageDecision  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.services.answer_facts import apply_answers  # noqa: E402
from app.services.candidate_language import resume_bullet  # noqa: E402
from app.services.fact_coverage import cite_entailed_facts  # noqa: E402
from app.services.fact_guard import guard_bullets  # noqa: E402
from app.services.intake import apply_submission  # noqa: E402
from app.services.renderer import render_resume  # noqa: E402
from app.services.resume_facts import new_fact  # noqa: E402
from app.services.resume_versions import text_hash  # noqa: E402
from app.services.resume_workspace import build_workspace  # noqa: E402
from test_batch14b_intake import FlowModel, extract_stub, PAGES, state_with_experiences  # noqa: E402
from test_fact_guard import decision  # noqa: E402
from test_resume_writer import FakeModel, fact, item  # noqa: E402

AIPM = import_module('evaluation.persona-ux.aipm')
TECH = {'id': 'tech_stack', 'prompt': '产品是用什么搭出来的？', 'kind': 'multi',
        'options': ['Cursor / Claude Code 等 AI 编程工具', '直接调用大模型 API'], 'allow_other': True}
MORE = [
    {'id': 'evaluation', 'prompt': '怎么判断效果好不好？', 'kind': 'multi',
     'options': ['对比过不同提示词或方案', '没有比较过'], 'allow_other': True},
    {'id': 'iteration', 'prompt': '开发中效果不好时怎么改？', 'kind': 'single',
     'options': ['换模型或调参数', '没有改过'], 'allow_other': True},
    {'id': 'status', 'prompt': '上线的具体形态是什么？', 'kind': 'single',
     'options': ['公网可访问的链接', '只在本地'], 'allow_other': True},
]


class AipmModel(FlowModel):
    def __init__(self, invented=False):
        super().__init__()
        self.invented = invented
        self.writer_inputs = []

    async def astream(self, messages):
        self.public_messages.append(messages)
        last = messages[-1].content
        context = json.loads(last.split('分阶段规则优先于旧候选：\n')[1]) if '分阶段规则优先于旧候选：\n' in last else {}
        yield AIMessageChunk(content='继续整理这段经历。')
        if context.get('subject'):
            asked = context.get('current_progress', {}).get('asked_dimensions', [])
            questions = MORE if 'tech_stack' in asked else [TECH]
            yield AIMessageChunk(content='', tool_call_chunks=[{'index': 0, 'id': 'synthetic', 'name': 'ask_user',
                'args': json.dumps({'subject': context['subject'], 'questions': questions}, ensure_ascii=False)}])

    def with_structured_output(self, schema):
        async def invoke(messages):
            self.calls.append(schema.__name__)
            data = json.loads(messages[-1].content)
            if schema.__name__ == 'SemanticBatch':
                return {'decisions': [decision(row['id']) for row in data]}
            if schema.__name__ == 'RepairOutput':
                return {'bullets': []}
            if schema.__name__ == 'StructurePlan':
                return {'recommended': {'label': '产品实践', 'bullet_style': 'plain', 'section_order': ['projects'],
                    'experience_plan': [{'item_id': p['item_id'], 'treatment': 'lead', 'target_bullets': 3} for p in data['evidence']['projects']]}}
            if schema.__name__ in {'WriterDraft', 'OnePassOutput'}:
                self.writer_inputs.append(data)
                project = data['evidence']['projects'][0]
                facts = project['facts']
                def refs(*needles):
                    return [f['id'] for f in facts if any(x in f['text'] for x in needles)]
                output = {'items': [{'item_id': project['item_id'], 'section': 'projects',
                    'title': {'positioning': '面向学生的对话式简历助手', 'fact_ids': refs('通过对话')},
                    'bullets': [
                        {'text': '决策：借助 Cursor / Claude Code 开发；直接调用大模型 API。',
                         'fact_ids': refs('Cursor', 'API', '独立开发者')},
                        {'text': '迭代：比较方案与提示词；以 71 条断言核查成稿，回放 5 个虚拟求职者对话；更换模型或调参。',
                         'fact_ids': refs('对比过', '五个', '换模型')},
                        {'text': '现状：已上线；通过链接可在公网访问。' + ('用户数达到1000。' if self.invented else ''),
                         'fact_ids': refs('上线', '公网')},
                    ]}]}
                return output if schema.__name__ == 'WriterDraft' else {'match_plan': {}, 'writer': output}
            raise AssertionError(schema.__name__)
        return SimpleNamespace(ainvoke=invoke)


class StructuredAnswerTests(unittest.TestCase):
    def submitted(self, questions, answers, subject='胡话简历'):
        state = state_with_experiences()
        card = {'turn_id': 'ask-1', 'questions': questions, 'subject': subject}
        message = HumanMessage(content='结构化回答', id='human-answer', additional_kwargs={
            'answers': {'turn_id': 'ask-1', 'items': answers}, 'answer_card': card})
        result = apply_answers(state['collected_info'], message)
        return state, message, result

    def test_multi_option_other_are_separate_with_message_question_and_subject(self):
        _, message, result = self.submitted([TECH], [{'id': 'tech_stack', 'value': [*TECH['options'], '用自写脚本处理输入']}])
        added = [f for f in result['projects'][0]['facts'] if f.get('turn_id') == message.id]
        self.assertEqual(len(added), 3)
        self.assertEqual({f['text'] for f in added}, {*TECH['options'], '用自写脚本处理输入'})
        for f in added:
            self.assertEqual(f['question_id'], 'tech_stack')
            self.assertEqual(f['item_id'], 'p0')
            self.assertEqual(f['source_quote'], f['answer_value'])
            self.assertEqual(f['sources'][0]['turn_id'], 'human-answer')
            self.assertEqual(f['sources'][0]['question_prompt'], TECH['prompt'])
        self.assertEqual(apply_answers(result, message), result)

    def test_skipped_unknown_missing_stale_or_wrong_subject_produce_no_facts(self):
        for flags in ({'skipped': True}, {'unknown': True}, {'value': '不知道'}, {}):
            state, _, result = self.submitted([TECH], [{'id': 'tech_stack', **flags}])
            self.assertEqual(result, state['collected_info'])
        state, message, result = self.submitted([TECH], [{'id': 'tech_stack', 'value': TECH['options']}], '另一个项目')
        self.assertEqual(result, state['collected_info'])
        message.additional_kwargs['answer_card']['subject'] = '胡话简历'
        message.additional_kwargs['answers']['turn_id'] = 'stale'
        self.assertEqual(apply_answers(result, message), result)

    def test_unknown_question_and_unselected_options_not_evidence(self):
        question = {**MORE[2], 'allow_other': False}
        state, _, result = self.submitted([question], [{'id': 'missing', 'value': '新增用户999'}, {'id': 'status', 'value': '另外的选项'}])
        self.assertEqual(result, state['collected_info'])

    def test_form_summary_is_direct_fact_and_retry_keeps_provenance(self):
        message = HumanMessage(content='提交表单', id='form-1', additional_kwargs={'intake': AIPM.INTAKE})
        result = apply_submission({}, AIPM.INTAKE, message)
        retried = apply_submission(result, AIPM.INTAKE, message)
        self.assertEqual(result, retried)
        facts = result['collected_info']['projects'][0]['facts']
        self.assertTrue(all(f['turn_id'] == 'form-1' and f.get('question_id') for f in facts))
        summary = next(f for f in facts if f['question_id'] == 'summary')
        self.assertEqual(summary['text'], '现在已经上线了')
        self.assertFalse(summary.get('field'))
        self.assertEqual(next(f for f in facts if f.get('field') == 'start_date')['text'], '2026-08')

    def test_free_text_and_duplicate_subject_need_explicit_binding(self):
        question = {'id': 'decision', 'prompt': '关键决策是什么？', 'kind': 'text'}
        state, message, result = self.submitted([question], [{'id':'decision', 'value':'先体验后登录'}])
        self.assertTrue(any(f['text'] == '先体验后登录' for f in result['projects'][0]['facts']))
        duplicate = deepcopy(state['collected_info'])
        duplicate['projects'].append({**deepcopy(duplicate['projects'][0]), 'item_id':'another'})
        self.assertEqual(apply_answers(duplicate, message), duplicate)
        message.additional_kwargs['answer_card']['subject'] = 'another'
        bound = apply_answers(duplicate, message)
        self.assertFalse(any(f['text'] == '先体验后登录' for f in bound['projects'][0]['facts']))
        self.assertTrue(any(f['text'] == '先体验后登录' for f in bound['projects'][1]['facts']))

    def test_intake_skip_has_no_facts(self):
        result = apply_submission({}, {'kind': 'experiences', 'skipped': True, 'items': AIPM.INTAKE['items']}, HumanMessage(content='跳过'))
        self.assertFalse(result['collected_info'].get('projects'))


class GuardAndCoverageTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_comparison_cannot_upgrade_to_evaluation_system(self):
        f = {**new_fact('对比过不同提示词或方案'), 'item_id': 'p'}
        row = {'id': 'b', 'text': '建立评测体系', 'item_id': 'p', 'fact_ids': [f['id']]}
        result = await guard_bullets([row], [f], llm=AipmModel())
        self.assertEqual(result[0]['verdict'], 'fail')
        self.assertIn('unsupported_evaluation_system', result[0]['lexical_errors'])
        row['text'] = '比较不同方案和提示词'
        self.assertEqual((await guard_bullets([row], [f], llm=AipmModel()))[0]['verdict'], 'pass')

    async def test_new_number_is_rejected_even_when_semantic_stub_approves(self):
        f = {**new_fact('用71条断言自动检查成稿'), 'item_id': 'p'}
        row = {'id': 'b', 'text': '使用71条断言检查成稿，准确率99%', 'item_id': 'p', 'fact_ids': [f['id']]}
        result = await guard_bullets([row], [f], llm=AipmModel())
        self.assertEqual(result[0]['verdict'], 'fail')
        self.assertTrue(any(e.startswith('unsupported_numbers:') for e in result[0]['lexical_errors']))

    async def test_different_wording_multi_fact_coverage_reaches_semantic_checker(self):
        source = {'projects': [{'item_id': 'p', 'name': '项目', 'facts': [new_fact('使用不同提示词做过方案对比'), new_fact('更换模型或调参数')]}]}
        facts = source['projects'][0]['facts']
        text = '比较方案与提示词；更换模型或调参'
        data = {'projects': [{'item_id': 'p', 'polished_bullets': [text]}]}
        meta = {'bullets': {'p': [{'text_hash': text_hash(text), 'fact_ids': [f['id'] for f in facts]}]}}
        seen = []
        async def verify(rows, *args, **kwargs):
            seen.extend(rows)
            return {r['id']: {'verdict': 'pass'} for r in rows}
        with patch('app.services.fact_guard.verify_semantics', verify):
            await cite_entailed_facts(data, meta, source, object(), item_ids=['p'])
        self.assertTrue(seen)
        self.assertEqual(set(meta['bullets']['p'][0]['coverage_fact_ids']), {f['id'] for f in facts})

    async def test_overcitation_still_requires_each_action_not_just_ids(self):
        source = {'projects': [{'item_id': 'p', 'name': '项目', 'facts': [new_fact('比较方案'), new_fact('修复接口')]}]}
        text = '对比方案'
        facts = source['projects'][0]['facts']
        meta = {'bullets': {'p': [{'text_hash': text_hash(text), 'fact_ids': [f['id'] for f in facts]}]}}
        async def verify(rows, *args, **kwargs):
            return {r['id']: {'verdict': 'fail' if '修复' in r['text'] else 'pass'} for r in rows}
        with patch('app.services.fact_guard.verify_semantics', verify):
            await cite_entailed_facts({'projects': [{'item_id': 'p', 'polished_bullets': [text]}]}, meta, source, object(), item_ids=['p'])
        self.assertNotIn(facts[1]['id'], meta['bullets']['p'][0]['coverage_fact_ids'])


class AipmFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.model = AipmModel()
        self.compiled = graph.build_graph(self.model)
        for context in (
            patch.object(graph, 'get_graph', return_value=self.compiled),
            patch.object(graph, '_make_non_streaming_llm', side_effect=lambda model, **kwargs: model),
            patch.object(graph, '_extract_info_from_message', side_effect=extract_stub),
            patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(action=TriageAction.READY_TO_BUILD, reason='桩'))),
            patch('app.services.session_store.save_candidate_intake'), patch('app.services.session_store.save_resume_session'),
            patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value=PAGES),
            patch.object(get_settings(), 'LLM_PLAN_CONFIRM', True),
        ):
            self.enterContext(context)
        self.turns = []

    async def turn(self, action, text, **payload):
        events = [event async for event in graph.stream_agent([{'role':'user', 'content':text}], 'aipm-c', self.model, **payload)]
        self.assertNotIn('"error"', str(events))
        state = (await self.compiled.aget_state({'configurable': {'thread_id':'aipm-c'}})).values
        self.turns.append({'action':action, 'input':text, **payload, 'status':'ok', 'sse_done':True,
                          'revision':text_hash(json.dumps(state.get('resume_data') or {}, ensure_ascii=False)),
                          'resume_data':deepcopy(state.get('resume_data') or {}),
                          'workspace':build_workspace(state, state.get('resume_data') or {}), 'stage':state['stage']})
        return state

    async def flow(self, style=None):
        state = {}
        for action, step in AIPM.FIXTURE.items():
            if action == 'role':
                continue
            submitted = AIPM.submission(step, build_workspace(state) if state else {})
            if submitted is None:
                continue
            text, payload = submitted
            state = await self.turn(action, text, **payload)
        plan = state['pending_plan']['recommended']
        self.assertEqual(plan['bullet_style'], 'labeled')
        state = await self.turn('confirm', '按推荐写', **({'plan_choice':{'option':'按推荐写', 'bullet_style':style}} if style else {}))
        return state

    async def test_synthetic_two_answer_rounds_to_recommended_draft(self):
        state = await self.flow()
        checks = AIPM.evaluate_persona('aipm', self.turns)
        self.assertTrue(all(c['status'] == 'pass' for c in checks), checks)
        self.assertEqual(len([t for t in self.turns if t.get('answers')]), 2)
        for message in state['messages']:
            if not isinstance(message, HumanMessage) or not message.additional_kwargs.get('answers'):
                continue
            linked = [f for f in state['collected_info']['projects'][0]['facts'] if f['turn_id'] == message.id]
            self.assertTrue(linked)
            self.assertTrue(all(f.get('question_id') and f.get('sources') for f in linked))
        project = state['resume_data']['projects'][0]
        self.assertEqual(project['project_type'], '个人项目')
        html = render_resume('t001-jianyue', state['resume_data'])
        self.assertIn('面向学生的对话式简历助手', html)
        self.assertIn('个人项目', html)
        self.assertFalse(state['resume_meta'].get('guard_fallbacks'))
        Path('/private/tmp/huhua-b14c-aipm-stub.json').write_text(json.dumps({'synthetic':True, 'turns':self.turns, 'checks':checks}, ensure_ascii=False, indent=2))
        Path('/private/tmp/huhua-b14c-aipm-preview.html').write_text(html)

    async def test_user_plain_choice_is_respected(self):
        state = await self.flow('plain')
        self.assertEqual(state['match_plan']['bullet_style'], 'plain')
        self.assertTrue(all(not b.startswith(('决策：','迭代：','现状：')) for b in state['resume_data']['projects'][0]['polished_bullets']))

    async def test_writer_new_number_cannot_enter_draft(self):
        self.model.invented = True
        state = await self.flow()
        self.assertNotIn('1000', '\n'.join(state['resume_data']['projects'][0]['polished_bullets']))


class CompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def test_style_merge_retains_all_sources_and_limits_three_clauses(self):
        from app.services.writing_style import restyle_resume
        texts = ['比较两种提示词；调整输出结构', '回放虚拟求职对话；检查成稿', '根据回放调整提示词']
        facts = {f'f{i}': {'id':f'f{i}', 'item_id':'p', 'text':text, 'kind':'action'} for i,text in enumerate(texts)}
        data = {'projects':[{'item_id':'p', 'polished_bullets':texts}]}
        meta = {'bullets':{'p':[{'text_hash':text_hash(text), 'fact_ids':[f'f{i}'], 'coverage_fact_ids':[f'f{i}']} for i,text in enumerate(texts)]}}
        result, records = restyle_resume(data, meta, facts, 'labeled', role_family='ai_pm')
        body = result['projects'][0]['polished_bullets']
        self.assertEqual(body, ['迭代：比较两种提示词；调整输出结构；根据回放调整提示词', '迭代：回放虚拟求职对话；检查成稿'])
        self.assertEqual(records['bullets']['p'][0]['fact_ids'], ['f0','f2'])
        self.assertEqual(records['bullets']['p'][0]['coverage_fact_ids'], ['f0','f2'])
        self.assertEqual(records['bullets']['p'][0]['text_hash'], text_hash(body[0]))
        plain, plain_meta = restyle_resume(result, records, facts, 'plain', role_family='ai_pm')
        self.assertFalse(plain['projects'][0]['polished_bullets'][0].startswith('迭代：'))
        self.assertEqual(plain_meta['bullets']['p'][0]['fact_ids'], ['f0','f2'])
        from app.services.writing_style import format_rows
        old_rows = [{'text':'现状：已上线', 'fact_ids':['status']}, {'text':'结果：获得2项反馈', 'fact_ids':['result']}]
        old_facts = {'status': {'text':'已上线', 'kind':'status_limit'}, 'result': {'text':'获得2项反馈', 'kind':'result_metric'}}
        self.assertEqual(format_rows(old_rows, old_facts, 'labeled', role_family='other'), old_rows)

    async def test_service_fixture_stays_plain(self):
        from test_persona_regressions import facts_for, FIXTURES
        from test_campus_and_naming import EchoWriter, semantic_stub
        source = await facts_for('service')
        with patch('app.services.fact_guard.verify_semantics', semantic_stub):
            result = await run_resume_writer(source, {'role_family':'other'}, EchoWriter(), instruction=FIXTURES['service']['polish'])
        self.assertEqual(result['match_plan']['bullet_style'], 'plain')
        body = result['resume_data']['work_experience'][0]['bullets']
        self.assertTrue(body)
        self.assertFalse(any(b.startswith(('问题：','决策：','迭代：','现状：','技术：')) for b in body))
        self.assertIn('千牛', str(result['resume_data']))

    async def test_answers_persist_before_reply_failure(self):
        state = state_with_experiences()
        message = HumanMessage(content='回答', id='before-error', additional_kwargs={
            'answers':{'turn_id':'ask', 'items':[{'id':'tech_stack','value':TECH['options']}]},
            'answer_card':{'turn_id':'ask','subject':'胡话简历','questions':[TECH]}})
        state['messages'] = [message]
        saver = AsyncMock()
        token = graph._intake_saver.set(saver)
        try:
            with patch.object(graph, '_collection_reply', side_effect=RuntimeError('公开回复桩失败')):
                with self.assertRaises(RuntimeError):
                    await graph._intake_form_turn(state, object(), message)
            stored = saver.call_args.args[0]['collected_info']['projects'][0]['facts']
            self.assertEqual(len([f for f in stored if f.get('turn_id') == 'before-error']), 2)
        finally:
            graph._intake_saver.reset(token)

    async def test_heading_rejects_invented_position_and_roundtrips_schema(self):
        from app.schemas.writer import WrittenItem
        from app.schemas.editor import ResumeData
        from app.services.project_heading import apply_project_headings
        f = {**new_fact('用对话帮助学生整理简历'), 'item_id':'p'}
        source = {'item_id':'p', 'name':'胡话简历', 'facts':[f]}
        item = {'name':'胡话简历'}
        written = WrittenItem(item_id='p', section='projects', title={'positioning':'服务1000用户的简历平台','fact_ids':[f['id']]})
        await apply_project_headings({'p':written}, {'p':('projects',item)}, {'p':('projects',source)}, {f['id']:f}, {}, AipmModel())
        self.assertNotIn('positioning', item)
        data = ResumeData.model_validate({'projects':[{'name':'胡话简历','role':'独立开发者','positioning':'对话式简历助手','project_type':'个人项目'}]}).model_dump()
        self.assertEqual(data['projects'][0]['positioning'], '对话式简历助手')
        self.assertEqual(data['projects'][0]['project_type'], '个人项目')
        from app.services.renderer import list_templates
        for template in list_templates():
            html = render_resume(template['id'], data)
            self.assertIn('对话式简历助手', html)
            self.assertIn('个人项目', html)
            self.assertNotIn('>独立开发者<', html)


class Batch12RegressionTests(unittest.IsolatedAsyncioTestCase):
    # 仅内嵌原合成记录的最小片段；不依赖私有绝对路径或历史 runs。
    async def test_date_only_bullet_is_removed_without_losing_header_dates(self):
        source = {'projects': [{'item_id':'p', 'name':'校园问答RAG演示', 'start_date':'2026.03', 'end_date':'2026.05',
            'facts':[{**fact('start','2026.03'), 'field':'start_date'}, {**fact('end','2026.05'), 'field':'end_date'}, fact('date','时间为2026.03—2026.05',kind='scope_scale'), fact('work','用Python和Streamlit在本地搭建演示',kind='method_tool')]}]}
        model = FakeModel([('OnePassOutput', {'match_plan':{}, 'writer':{'items':[item('p','projects', [('2026.03—2026.05',['date']), ('用Python和Streamlit在本地搭建演示',['work'])])]}})])
        result = await run_resume_writer(source, {}, model)
        project = result['resume_data']['projects'][0]
        self.assertEqual(project['start_date'], '2026.03')
        self.assertEqual(project['end_date'], '2026.05')
        self.assertFalse(any('2026' in b for b in project['polished_bullets']))
        self.assertTrue(any('Streamlit' in b for b in project['polished_bullets']))

    async def test_missing_python_streamlit_action_is_restored_next_to_metric(self):
        method = '用Python和Streamlit在本地搭建演示'
        metric = '在120道自拟问题上，答案人工判定正确数由基础版本的71道提高到82道'
        source = {'projects':[{'item_id':'p','name':'校园问答RAG演示','facts':[
            fact('date','时间为2026.03—2026.05',kind='scope_scale'), fact('work',method,kind='method_tool'),
            fact('table','整理问答材料并维护评测表'), fact('metric',metric,kind='result_metric')]}]}
        model = FakeModel([('OnePassOutput', {'match_plan':{'experience_plan':[{'item_id':'p','treatment':'lead','target_bullets':3}]},
             'writer':{'items':[item('p','projects', [('2026.03—2026.05',['date']), (metric,['metric'])])]}})])
        result = await run_resume_writer(source, {}, model)
        body = '\n'.join(result['resume_data']['projects'][0]['polished_bullets'])
        self.assertIn('Python和Streamlit在本地搭建', body)
        self.assertIn('120', body)
        self.assertNotIn('2026.03', body)

    async def test_third_round_delivery_repairs_existing_artifacts_without_writer(self):
        method = '用Python和Streamlit在本地搭建演示'
        metric = '在120道自拟问题上，答案人工判定正确数由基础版本的71道提高到82道'
        tail = '参与8名同学的可用性测试，依据反馈改版原型，时间为2026.06—2026.09'
        source = {'projects':[
            {'item_id':'rag','name':'校园问答RAG演示','facts':[fact('date','时间为2026.03—2026.05',kind='context'),
                fact('method',method,kind='method_tool'), fact('metric',metric,kind='result_metric')]},
            {'item_id':'resume','name':'拾光简历助手','facts':[fact('tail',tail)]}],
            'campus':[{'item_id':'removed','name':'已删活动','facts':[fact('campus','协助2次分享会')]}]}
        data = {'projects':[
            {'item_id':'rag','name':'校园问答RAG演示','start_date':'2026.03','end_date':'2026.05', 'polished_bullets':[metric,'2026.03—2026.05']},
            {'item_id':'resume','name':'拾光简历助手','start_date':'2026.06','end_date':'2026.09','polished_bullets':[tail]}], 'campus':[]}
        meta = {'bullets':{'rag':[{'fact_ids':['metric'],'text_hash':text_hash(metric)}, {'fact_ids':['date'],'text_hash':text_hash('2026.03—2026.05')}],
                            'resume':[{'fact_ids':['tail'],'text_hash':text_hash(tail)}]},
                'fact_coverage':{'facts':[{'fact_id':'method','item_id':'rag','status':'omitted','reason':'本版条数上限，未覆盖的职责保留为备用'}]}}
        plan = {'bullet_style':'plain','experience_plan':[{'item_id':'rag','treatment':'lead','target_bullets':3}],
                'requirements':[{'fact_ids':['method']}]}
        state = {**graph._init_state(),'stage':'EVALUATING','intake_stage':'ready','resume_data':data,'resume_meta':meta,
                 'collected_info':source,'match_plan':plan,'messages':[HumanMessage(content='请以第二轮确认的事实与删改要求为准，交付最终投递版中文简历。直接给出完整成果，不再反问、不添加新信息、不恢复已删除内容；检查职责归属、技能边界和离线评测口径是否准确。')]}
        with patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value=PAGES), patch('app.agents.resume_writer.run_resume_writer', side_effect=AssertionError('不应调用 writer')):
            result = await graph._evaluating_turn_node(state, object())
        self.assertEqual(result['resume_data']['projects'][0]['polished_bullets'], [metric, method])
        self.assertEqual(result['resume_data']['projects'][1]['polished_bullets'], ['参与8名同学的可用性测试，依据反馈改版原型'])
        self.assertEqual(result['resume_data']['projects'][0]['start_date'], '2026.03')
        self.assertEqual(result['resume_data']['campus'], [])
        self.assertEqual(result['writer_diagnostic']['status'], 'not_called')

    async def test_delivery_date_repair_does_not_restore_explicit_backup_or_touch_unbound_text(self):
        from app.services.delivery_date_repair import repair_delivery_dates
        body = ['2026.03—2026.05']
        source = {'projects':[{'item_id':'p','name':'项目','facts':[fact('date',body[0]),fact('work','用Python搭建演示')]}]}
        data = {'projects':[{'item_id':'p','name':'项目','start_date':'2026.03','end_date':'2026.05','polished_bullets':body}]}
        before = deepcopy(data)
        self.assertFalse(await repair_delivery_dates(data, {}, source, {}))
        self.assertEqual(data, before)
        meta = {'bullets':{'p':[{'fact_ids':['date'],'text_hash':text_hash(body[0])}]}}
        plan = {'experience_plan':[{'item_id':'p','treatment':'backup','target_bullets':0}]}
        self.assertFalse(await repair_delivery_dates(data, meta, source, plan))
        self.assertEqual(data, before)

    def test_date_tail_removed_but_action_and_quantities_retained(self):
        text = '参与8名同学的可用性测试，依据反馈改版原型，时间为2026.06—2026.09'
        self.assertEqual(resume_bullet(text), '参与8名同学的可用性测试，依据反馈改版原型')
        self.assertEqual(resume_bullet('2026年搭建原型；耗时3个月'), '2026年搭建原型；耗时3个月')


class AipmRunnerTests(unittest.TestCase):
    def test_guest_client_transmits_structured_payloads(self):
        import io
        runner = import_module('evaluation.persona-ux.run_persona')
        client = runner.GuestClient('http://127.0.0.1:8849', 1)
        client.session_id = 'synthetic'
        answers = {'turn_id':'ask', 'items':[{'id':'iteration','value':'换模型或调参数'}]}
        with patch.object(client, 'open', return_value=io.BytesIO(b'data: [DONE]\n\n')) as opened, \
             patch.object(client, 'json', return_value={'data':{},'workspace':{}}):
            row = client.turn('structured', '提交答案', answers=answers, intake=AIPM.INTAKE)
        payload = opened.call_args.args[1]
        self.assertEqual(payload['answers'], answers)
        self.assertEqual(payload['intake'], AIPM.INTAKE)
        self.assertEqual(row['answers'], answers)
        self.assertEqual(row['intake'], AIPM.INTAKE)
        self.assertTrue(row['sse_done'])

    def test_aipm_replay_binds_actual_cards_and_keeps_original_five_defaults(self):
        import tempfile
        runner = import_module('evaluation.persona-ux.run_persona')
        requests = []
        project = {'item_id':'p', 'name':'胡话简历', 'start_date':'2026-08', 'end_date':'至今',
                   'positioning':'面向学生的对话式简历助手', 'project_type':'个人项目',
                   'polished_bullets':['决策：借助 Cursor / Claude Code 开发；直接调用大模型 API。',
                       '迭代：比较方案与提示词；以 71 条断言核查成稿，回放 5 个虚拟求职者对话；更换模型或调参。',
                       '现状：已上线；通过链接可在公网访问。']}
        guides = [
            {'kind':'intake_experiences', 'items':[{'name':'胡话简历','item_id':'p'}]},
            {'kind':'ask_user','subject':'胡话简历','turn_id':'actual-1','questions':[TECH]},
            {'kind':'ask_user','subject':'胡话简历','turn_id':'actual-2','questions':MORE},
            {'kind':'intake_basics'},
            {'kind':'structure_plan', 'options':[{'label':'按推荐写','value':'按推荐写'}]},
            {},
        ]
        class Client:
            def __init__(self, *args):
                self.cookies = SimpleNamespace(clear=lambda:None)
            def start(self):
                pass
            def turn(self, action, text, **payload):
                guide = guides[len(requests)]
                requests.append(payload)
                final = action.endswith('_confirm')
                return {'action':action, 'input':text, 'status':'ok', 'sse_done':True, 'reply':'完成',
                        'revision':'stub-revision',
                        'workspace':{'guidance':guide, 'tailor':{'resume_meta': {
                            'writer_diagnostic':{'status':'model_completed'},
                            'bullets':{project['item_id']:[{'fact_ids':['source'], 'text_hash':text_hash(b)} for b in project['polished_bullets']]}
                        } if final else {}}}, 'stage':'EVALUATING' if final else 'COLLECTING',
                        'resume_data':{'projects':[project]} if final else {}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, 'GuestClient', Client):
            run = runner.run_replay('http://127.0.0.1:8849', Path(tmp)/'run', ['aipm'])
        self.assertEqual(run['status'], 'pass', run)
        self.assertTrue(run['aipm_synthetic_placeholder'])
        self.assertEqual(requests[1]['intake']['items'][0]['item_id'], 'p')
        self.assertEqual(requests[2]['answers']['turn_id'], 'actual-1')
        self.assertEqual(requests[3]['answers']['turn_id'], 'actual-2')
        self.assertEqual(len(run['personas']['aipm']['checks']), 9)
        self.assertEqual(runner.checks.PERSONAS, ('tech','ops','career','service','design'))

    def test_cli_accepts_aipm(self):
        from contextlib import redirect_stdout
        import io
        import tempfile
        runner = import_module('evaluation.persona-ux.run_persona')
        with tempfile.TemporaryDirectory() as tmp:
            here = Path(tmp)
            with patch.object(runner, 'HERE', here), patch.object(runner, 'run_replay', return_value={'status':'pass','stream_requests':6}) as replay, redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(['--persona','aipm','--base','http://127.0.0.1:8849','--output',str(here/'runs'/'synthetic')]), 0)
            self.assertEqual(replay.call_args.args[2], ['aipm'])


if __name__ == '__main__':
    unittest.main()
