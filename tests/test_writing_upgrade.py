"""Writing upgrade: fictional evidence, scripted models and isolated local output."""
from copy import deepcopy
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from docx import Document
from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.agents import resume_graph as graph
from app.agents.interviewer import compose_interviewer_reply
from app.agents.resume_writer import run_resume_writer
from app.agents.turn_actions import bind_role_followup
from app.config import get_settings
from app.services.fact_guard import guard_bullets
from app.services.renderer import list_templates, render_resume
from app.services.structure_plan import plan_action, select_plan
from app.tools.resume_data_docx import resume_data_to_docx
from test_replay_plan_intake_regressions import PlanModel


def fact(fid, text, kind='action', status='active'):
    return {'id': fid, 'text': text, 'source_quote': text, 'kind': kind, 'status': status, 'source': 'chat'}


def evidence():
    return {'basic_info': {'name': '合成同学'}, 'projects': [{'item_id': 'p1', 'name': '纸舟', 'facts': [
        fact('f1', '用户把外部调研当作个人经历', 'context'),
        fact('f2', '选择将个人事实与外部调研分开存储'),
        fact('f3', '避免把外部调研当成个人经历', 'context'),
        fact('f4', '完成本地闭环原型，演示版使用本地数据与模拟模型', 'status_limit'),
    ]}], 'skills': []}


STATEMENT = '实现个人事实存储。关注个人事实与外部调研。'


def plan_card(statement=STATEMENT):
    plan = {'label': '事实与边界', 'profile_statement': statement, 'positioning': '',
            'thesis': '从事实存储展示边界意识', 'section_order': ['projects'],
            'experience_plan': [{'item_id': 'p1', 'treatment': 'lead', 'target_bullets': 3}]}
    return {'recommended': plan, 'alternatives': [{**deepcopy(plan), 'label': '原型实践'}]}


def draft():
    return {'items': [{'item_id': 'p1', 'section': 'projects', 'bullets': [
        {'text': '现状：完成本地闭环原型，演示版使用本地数据与模拟模型', 'fact_ids': ['f4']},
        {'text': '关键决策：选择将个人事实与外部调研分开存储，避免把外部调研当成个人经历', 'fact_ids': ['f2', 'f3']},
        {'text': '问题：用户把外部调研当作个人经历', 'fact_ids': ['f1']},
    ]}]}


class WritingUpgradeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for context in (patch.object(get_settings(), 'LLM_PLAN_CONFIRM', True),
                        patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={
                            'status': 'rendered', 'pages': 1, 'page_limit': 1, 'within_page_limit': True})):
            context.start()
            self.addCleanup(context.stop)

    async def planned(self, statement=STATEMENT, collected=None, family='ai_pm'):
        return await run_resume_writer(collected or evidence(), {'role_family': family},
            PlanModel([('StructurePlan', plan_card(statement))]), phase='plan')

    async def test_profile_supported_stance_and_alternative(self):
        result = await self.planned()
        for row in [result['structure_plan']['recommended'], *result['structure_plan']['alternatives']]:
            self.assertEqual(row['profile_statement'], STATEMENT)
            self.assertEqual(row['positioning'], '')

    async def test_profile_rejects_missing_stance_noun_and_single_active_support(self):
        cases = [(STATEMENT.replace('外部调研', '用户增长'), evidence())]
        one = evidence()
        for row in one['projects'][0]['facts']:
            if row['id'] != 'f2':
                row['status'] = 'deleted'
        cases.append((STATEMENT, one))
        for statement, collected in cases:
            with self.subTest(statement=statement, active=sum(f['status'] == 'active' for f in collected['projects'][0]['facts'])):
                result = await self.planned(statement, collected)
                self.assertEqual(result['structure_plan']['recommended']['profile_statement'], '')

    async def test_profile_rejects_new_identity_number_tool_outcome_and_bad_shape(self):
        for statement in ['担任产品经理。关注个人事实与外部调研。',
                          '完成100个项目。关注个人事实与外部调研。',
                          '使用Kubernetes。关注个人事实与外部调研。',
                          '已上线。关注个人事实与外部调研。',
                          '候选人实现个人事实存储。关注个人事实与外部调研。',
                          '关注个人事实与外部调研。', '实' * 89 + '。完成。']:
            with self.subTest(statement=statement):
                result = await self.planned(statement)
                self.assertEqual(result['structure_plan']['recommended']['profile_statement'], '')

    async def test_profile_semantic_result_failure_rejected(self):
        result = await run_resume_writer(evidence(), {'role_family': 'ai_pm'},
            PlanModel([('StructurePlan', plan_card('实现用户增长。关注个人事实与外部调研。'))],
                      fail_ids=['plan_positioning_0', 'plan_positioning_1']), phase='plan')
        self.assertFalse(result['structure_plan']['recommended']['profile_statement'])

    async def test_confirm_writes_exact_profile_and_all_templates_and_word_heading(self):
        state = {**graph._init_state(), 'stage': 'BUILDING', 'collected_info': evidence(),
                 'jd_info': {'role_profile': {'role_family': 'ai_pm'}},
                 'messages': [HumanMessage(content='生成简历')]}
        planned = await graph.building_node(state, PlanModel([('StructurePlan', plan_card())]))
        self.assertFalse(planned.get('resume_data'))
        model = PlanModel([('WriterDraft', draft())], fail_ids=['plan_positioning_0'])
        result = await graph.structure_plan_node({**state, **planned, 'messages': [HumanMessage(content='按推荐写')]}, model)
        data = result['resume_data']
        self.assertEqual(data['summary'], STATEMENT)
        self.assertNotIn('StructurePlan', model.calls)
        self.assertFalse(any(row['id'] == 'plan_positioning_0' for batch in model.batches for row in batch))
        for template in list_templates():
            html = render_resume(template['id'], data)
            self.assertEqual(html.count('>个人定位<'), 1, template['id'])
            self.assertEqual(html.count(STATEMENT), 1)
        doc = Document(io.BytesIO(resume_data_to_docx(data)))
        texts = [p.text for p in doc.paragraphs]
        self.assertEqual(texts.count('个人定位'), 1)
        self.assertEqual(texts[texts.index('个人定位') + 1], STATEMENT)

    async def test_profile_user_edit_pending_and_confirmed_is_exact_no_model(self):
        planned = (await self.planned())['structure_plan']
        text = '关注真实问题。习惯先验证，再迭代。'
        command = '个人定位改成' + text
        state = {**graph._init_state(), 'collected_info': evidence(), 'pending_plan': planned,
                 'messages': [HumanMessage(content=command)]}
        model = PlanModel()
        self.assertEqual(plan_action(command)[0], 'edit')
        edited = await graph.structure_plan_node(state, model)
        self.assertEqual(edited['pending_plan']['recommended']['profile_statement'], text)
        result = await run_resume_writer(evidence(), {'role_family': 'ai_pm'}, PlanModel([('WriterDraft', draft())]),
            phase='write', previous_plan=select_plan(edited['pending_plan']))
        self.assertEqual(result['resume_data']['summary'], text)
        final = await graph.structure_plan_node({**state, **result, 'pending_plan': {},
            'messages': [HumanMessage(content='个人定位改成原话中的 r1 也原样保留。继续学习。')]}, model)
        self.assertEqual(final['resume_data']['summary'], '原话中的 r1 也原样保留。继续学习。')
        self.assertEqual(model.calls, [])

    async def test_role_default_and_explicit_style_toggle_never_plans(self):
        for family, expected in [('ai_pm', 'labeled'), ('pm', 'labeled'), ('backend', 'plain')]:
            result = await self.planned(family=family)
            self.assertEqual(result['structure_plan']['recommended']['bullet_style'], expected)
        state = {**graph._init_state(), 'collected_info': evidence(),
                 'pending_plan': (await self.planned())['structure_plan'],
                 'messages': [HumanMessage(content='写法：普通')]}
        model = PlanModel()
        edited = await graph.structure_plan_node(state, model)
        self.assertEqual(edited['pending_plan']['recommended']['bullet_style'], 'plain')
        self.assertTrue(all(row['bullet_style'] == 'plain' for row in edited['pending_plan']['alternatives']))
        written = await run_resume_writer(evidence(), {'role_family': 'ai_pm'}, PlanModel([('WriterDraft', draft())]),
            phase='write', previous_plan=select_plan(state['pending_plan']))
        edited = await graph.structure_plan_node({**state, **written, 'pending_plan': {}}, model)
        self.assertFalse(any('：' in b for b in edited['resume_data']['projects'][0]['polished_bullets']))
        restored = await graph.structure_plan_node({**state, **edited, 'pending_plan': {},
            'messages': [HumanMessage(content='写法：问题-决策-结果')]}, model)
        self.assertEqual([b.split('：')[0] for b in restored['resume_data']['projects'][0]['polished_bullets']],
                         ['问题', '关键决策', '现状'])
        self.assertEqual(model.calls, [])

    async def test_labeled_order_reason_and_positive_status_survive_writer(self):
        result = await run_resume_writer(evidence(), {'role_family': 'ai_pm'},
            PlanModel([('WriterDraft', draft())]), phase='write', previous_plan=select_plan((await self.planned())['structure_plan']))
        bullets = result['resume_data']['projects'][0]['polished_bullets']
        self.assertEqual([b.split('：')[0] for b in bullets], ['问题', '关键决策', '现状'])
        self.assertIn('，避免把外部调研当成个人经历', bullets[1])
        self.assertIn('演示版使用本地数据与模拟模型', bullets[2])
        self.assertEqual(result['resume_meta']['bullets']['p1'][1]['fact_ids'], ['f2', 'f3'])

    async def test_labeled_does_not_pad_missing_facts_or_trust_model_label(self):
        collected = evidence()
        collected['projects'][0]['facts'] = [collected['projects'][0]['facts'][1]]
        output = {'items': [{'item_id': 'p1', 'section': 'projects', 'bullets': [
            {'text': '结果：选择将个人事实与外部调研分开存储', 'fact_ids': ['f2']}]}]}
        result = await run_resume_writer(collected, {'role_family': 'ai_pm'},
            PlanModel([('OnePassOutput', {'match_plan': {}, 'writer': output})]), mode='one_pass')
        self.assertEqual(result['resume_data']['projects'][0]['polished_bullets'],
                         ['关键决策：选择将个人事实与外部调研分开存储'])
        from app.services.writing_style import row_label
        self.assertEqual(row_label({'text': '课程项目', 'fact_ids': ['c']},
                                   {'c': fact('c', '课程项目', 'context')}), '')

    async def test_reason_priority_and_exact_answer_is_context_and_not_reasked(self):
        collected = evidence()
        collected['projects'][0]['facts'] = [collected['projects'][0]['facts'][1]]
        state = {'collected_info': collected, 'resume_data': {'projects': [
            {'item_id': 'p1', 'name': '纸舟', 'polished_bullets': ['选择分开存储']} ]},
            'match_plan': {'questions': [{'q': '有多少用户？', 'value': 5, 'improves': {'item_id': 'p1'}}]}}
        result = compose_interviewer_reply(state)
        self.assertIn('这样做是为了解决什么', result['questions'][0]['q'])
        answer = '避免把外部调研当成个人经历'
        updated = bind_role_followup(collected, result['text'], answer, 'fictional-turn')
        reason = next(f for f in updated['projects'][0]['facts'] if f['kind'] == 'context')
        self.assertEqual(reason['source_quote'], answer)
        self.assertEqual(reason['turn_id'], 'fictional-turn')
        combined = '选择将个人事实与外部调研分开存储，' + answer
        writer = PlanModel([('OnePassOutput', {'match_plan': {}, 'writer': {'items': [
            {'item_id': 'p1', 'section': 'projects', 'bullets': [
                {'text': combined, 'fact_ids': ['f2', reason['id']]}]}]}})])
        written = await run_resume_writer(updated, {'role_family': 'ai_pm'}, writer)
        self.assertEqual(written['resume_data']['projects'][0]['polished_bullets'], ['关键决策：' + combined])
        self.assertIn(reason['id'], written['resume_meta']['bullets']['p1'][0]['fact_ids'])
        again = compose_interviewer_reply({**state, 'collected_info': updated})
        self.assertFalse(any('这样做是为了解决什么' in q['q'] for q in again['questions']))
        self.assertEqual(bind_role_followup(collected, result['text'], '不知道 / 没有'), collected)
        self.assertEqual(bind_role_followup(collected, result['text'], '10个用户'), collected)

    async def test_plain_writer_and_edit_legacy_resume_without_plan_are_deterministic(self):
        collected = evidence()
        plan = select_plan((await self.planned())['structure_plan'])
        plan['bullet_style'] = 'plain'
        written = await run_resume_writer(collected, {'role_family': 'ai_pm'},
            PlanModel([('WriterDraft', draft())]), phase='write', previous_plan=plan)
        self.assertFalse(any('：' in b for b in written['resume_data']['projects'][0]['polished_bullets']))
        state = {**graph._init_state(), 'resume_data': written['resume_data'], 'collected_info': collected,
                 'messages': [HumanMessage(content='个人定位改成保持学习。持续验证。')]}
        self.assertEqual(graph.route_by_stage(state), 'structure_plan')
        model = PlanModel()
        result = await graph.structure_plan_node(state, model)
        self.assertEqual(result['resume_data']['summary'], '保持学习。持续验证。')
        self.assertEqual(model.calls, [])

    async def test_status_positive_allowed_and_absence_blocked(self):
        for text, rejected in [('现状：完成本地闭环原型', False),
                               ('演示版使用本地数据与模拟模型', False), ('没有用户量', True), ('未跑通', True)]:
            rows = await guard_bullets([{'id': 'b', 'text': text, 'fact_ids': ['f']}],
                [fact('f', text, 'status_limit')], lexical_only=True)
            self.assertEqual('negative_absence_printed' in rows[0]['lexical_errors'], rejected)
