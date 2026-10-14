"""Synthetic persona feedback regressions; no provider or real user data."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.agents import resume_graph as graph
from app.agents.fact_extractor import apply_fact_patch, extract_facts_patch
from app.agents.tailor_pipeline import infer_edit_scope
from app.agents.triage_chain import TriageAction, TriageDecision
from app.agents.turn_actions import choose_edit_plan, parse_education_fields
from app.config import get_settings
from app.services.candidate_material import parse_existing_resume, split_mixed_material
from app.services.fact_corrections import apply_literal_corrections, correction_pairs
from app.services.resume_facts import new_fact, normalize_fact_store
from app.services.resume_versions import text_hash
from app.services.skill_groups import normalize_skill_groups
from test_campus_and_naming import EchoWriter, ExtractorStub, raw, semantic_stub


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / 'evaluation/persona-ux-2026-10-15/fixtures.json').read_text())
ATTACHMENT = (ROOT / 'evaluation/persona-ux-2026-10-15/design-material.txt').read_text()
PAGES = {'within_page_limit': True, 'page_count': 1}


def fixture_patch(persona):
    text = FIXTURES[persona]['initial']
    education = parse_education_fields(text)
    if persona == 'ops':
        return {'basic_info': {'name': '陈夏'}, 'items': [
            {'section': 'education', 'name': '江城学院', 'facts': [raw(v, kind='context', field=k) for k, v in education.items()]},
            {'section': 'campus', 'name': '校园读书协会', 'facts': [raw('大三在校园读书协会帮忙做过公众号排版'), raw('也写过推文')]},
            {'section': 'work_experience', 'name': '', 'facts': [raw('还在一家咖啡店做过两个月兼职'), raw('拍过店里的短视频'), raw('也帮店长做海报')]}],
            'skills': ['剪映', 'Canva', 'Excel', 'PS']}
    if persona == 'tech':
        work = text[text.index('2025.07'):text.index('课程项目叫')]
        project = text[text.index('课程项目叫'):text.index('会用 Java')]
        name, school, company, title = '林泽', '海城理工大学', '云舟科技', '后端开发实习生'
    elif persona == 'service':
        work = text[text.index('2024.07'):text.index('会 Excel')]
        project = ''
        name, school, company, title = '赵悦', '在新城职业学院', '禾木家居', '电商客服'
    else:
        work = text[text.index('2024.07'):text.index('现在想转')]
        project = ''
        name, school, company, title = '周宁', '南川大学', '启明商贸', '行政助理'
    rows = [{'section': 'education', 'name': school, 'facts': [raw(value, kind='context', field=field)
             for field, value in education.items()]},
            {'section': 'internship' if persona == 'tech' else 'work_experience', 'name': company,
             'facts': [raw(title, field='title', kind='role'), *[raw(clause.strip()) for clause in re.split(r'[；。]', work) if clause.strip()]]}]
    if project:
        rows += [{'section': 'projects', 'name': '项目（待补名称）', 'facts': [raw(project.split('，')[0])]},
                 {'section': 'projects', 'name': '校园二手交易系统', 'facts': [raw(clause.strip()) for clause in re.split(r'[；。]', project) if clause.strip()]}]
    return {'basic_info': {'name': name}, 'items': rows,
            'skills': ['Java', 'Git', '了解 Redis', 'Kubernetes'] if persona == 'tech' else ['Excel', '千牛']}


class PersonaModel(EchoWriter):
    """Extraction includes a duplicate course and a denied skill; writing is literal."""
    def __init__(self, persona):
        super().__init__()
        self.persona = persona
        self.inputs = []

    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        if 'existing' in payload:
            self.inputs.append(payload['message'])
            return AIMessage(content=json.dumps(fixture_patch(self.persona), ensure_ascii=False))
        return await super().ainvoke(messages)


class PolishingWriter(EchoWriter):
    async def ainvoke(self, messages):
        output = await super().ainvoke(messages)
        for item in output['writer']['items']:
            for bullet in item['bullets']:
                bullet['text'] = bullet['text'].replace('回复售前咨询', '承接售前咨询').replace('查物流', '查询物流')
        return output


async def facts_for(persona):
    text, _ = split_mixed_material(FIXTURES[persona]['initial'])
    return apply_fact_patch({}, await extract_facts_patch(text, {}, ExtractorStub(fixture_patch(persona))))


def correction_state(persona):
    text = FIXTURES[persona]['initial']
    if persona == 'tech':
        metric = text[text.index('在测试环境'):text.index('；编写了')]
        other = text[text.index('编写了'):text.index('。课程项目')]
    else:
        metric = text[text.index('协助组织'):text.index('；接待访客')]
        other = text[text.index('负责每月'):text.index('；协助组织')]
    fact = new_fact(metric, kind='result_metric')
    spare = new_fact(other)
    facts = normalize_fact_store({'work_experience': [{'item_id': 'work', 'company': '云舟科技' if persona == 'tech' else '启明商贸',
                                  'facts': [fact, spare]}]})
    data = {'basic_info': {'name': '林泽' if persona == 'tech' else '周宁', 'objective': FIXTURES[persona]['role']},
            'education': [{'school': '合成大学', 'major': '计算机科学与技术'}],
            'work_experience': [{'item_id': 'work', 'company': facts['work_experience'][0]['company'],
                                 'bullets': [metric, '成果记录：' + metric, other]}],
            'projects': [{'item_id': 'untouched', 'name': '其他经历', 'polished_bullets': ['保留原文']}], 'skills': ['Java']}
    meta = {'bullets': {'work': [{'fact_ids': [f['id']], 'text_hash': text_hash(body)}
            for f, body in zip([fact, fact, spare], data['work_experience'][0]['bullets'])]}}
    return {**graph._init_state(), 'stage': 'EVALUATING', 'collected_info': facts, 'candidate_history_reconciled': True,
            'resume_data': data, 'resume_meta': meta, 'messages': [HumanMessage(content=FIXTURES[persona]['correction'], id='correct')]}


class PersonaRegressions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value=PAGES))
        self.enterContext(patch('app.services.resume_capacity.measure_rendered_pages', return_value=PAGES))
        self.enterContext(patch('app.services.fact_guard.verify_semantics', semantic_stub))
        self.enterContext(patch.object(get_settings(), 'LLM_PLAN_CONFIRM', False))
        self.enterContext(patch.object(get_settings(), 'LLM_WRITER_MODE', 'one_pass'))

    async def test_professional_adjectives_reject_both_extractor_and_router_fields(self):
        for persona, bad in [('tech', '请把实习经历润色得更'), ('service', '写得更')]:
            text = FIXTURES[persona]['polish']
            facts = await facts_for(persona)
            school = facts['education'][0]
            model = ExtractorStub({'items': [{'section': 'education', 'item_id': school['item_id'],
                                             'facts': [raw(bad, field='major', kind='context')]}]})
            result = apply_fact_patch(facts, await extract_facts_patch(text, facts, model))
            active = [f['text'] for f in result['education'][0]['facts'] if f.get('status') == 'active']
            self.assertNotIn(bad, active)
            self.assertEqual(parse_education_fields(text), {})
            plan = choose_edit_plan(text, {}, [{'op': 'set_field', 'target': school['item_id'],
                                     'args': {'field': 'major', 'value': bad}}], facts)
            self.assertFalse(any(row['op'] == 'set_field' for row in plan))
        for text in ('专业一点', '专业化', '用专业的表达'):
            self.assertEqual(parse_education_fields(text), {})

    def test_explicit_majors_remain_supported(self):
        for text in ('专业改成软件工程', '专业是软件工程', '我的专业是软件工程', '把专业写成软件工程',
                     '教育：海城理工大学，软件工程专业，本科'):
            self.assertEqual(parse_education_fields(text).get('major'), '软件工程', text)
        self.assertNotIn('major', parse_education_fields('把经历写成很有价值的专业表达'))
        self.assertNotIn('major', parse_education_fields('教育：海城理工大学，本科。课程项目：校园系统设计。'))

    async def test_polish_changes_only_selected_experience_prose(self):
        for persona in ('tech', 'service'):
            facts = await facts_for(persona)
            data = graph._serialize_to_resume_data({'collected_info': facts})
            data['basic_info']['objective'] = '用户手动写的目标'
            data['education'][0]['highlights'] = '用户保留的教育备注'
            data['summary'] = '用户保留的自述'
            data.setdefault('projects', []).append({'item_id': 'other', 'name': '其他项目', 'polished_bullets': ['不要修改这一条']})
            instruction = FIXTURES[persona]['polish']
            scope, targets = infer_edit_scope(data, instruction)
            self.assertEqual(scope, 'item')
            self.assertEqual(set(targets), {row['item_id'] for row in data['work_experience']})
            state = {**graph._init_state(), 'collected_info': facts, 'resume_data': data,
                     'candidate_history_reconciled': True, 'messages': [HumanMessage(content=instruction)]}
            with patch.object(graph, '_extract_info_from_message', AsyncMock(side_effect=AssertionError('wording is not new facts'))):
                result = await graph.evaluating_node(state, PolishingWriter())
            after = result['resume_data']
            for field in data:
                if field != 'work_experience':
                    self.assertEqual(after.get(field), data[field], (persona, field))
            self.assertEqual(result['collected_info'], facts)
            self.assertNotIn('修改专业', ''.join(m.content for m in result['messages']))
            self.assertNotEqual(after['work_experience'], data['work_experience'])
            if persona == 'tech':
                for limit in ('导师指导', '测试环境', '线上压测'):
                    self.assertIn(limit, str(after['work_experience']))

    def test_category_scope_excludes_other_work_and_projects(self):
        data = {'work_experience': [{'item_id': 'intern', 'title': '后端实习生', 'employment_type': 'internship'},
                                    {'item_id': 'job', 'title': '后端工程师', 'employment_type': 'full_time'}],
                'projects': [{'item_id': 'course', 'name': '校园借物', 'subtitle': '课程作品'},
                             {'item_id': 'personal', 'name': '个人网站'}]}
        self.assertEqual(infer_edit_scope(data, FIXTURES['tech']['polish']), ('item', ['intern']))
        self.assertEqual(infer_edit_scope(data, FIXTURES['design']['polish']), ('item', ['course']))

    async def test_literal_corrections_replace_all_bullets_without_writer(self):
        for persona, old, new in [('tech', '170ms', '190ms'), ('career', '6 场', '4 场')]:
            state = correction_state(persona)
            before = deepcopy(state)
            # A writer that only changes the fact master and reuses old prose
            # must never be responsible for this transaction.
            stale = AsyncMock(return_value={'collected_info': state['collected_info'], 'resume_data': state['resume_data']})
            with patch.object(graph, '_write_resume_update', stale):
                result = await graph.evaluating_node(state, object())
            stale.assert_not_awaited()
            expected = deepcopy(state['resume_data'])
            expected['work_experience'][0]['bullets'] = [b.replace(old, new) for b in expected['work_experience'][0]['bullets']]
            self.assertEqual(result['resume_data'], expected)
            self.assertEqual(state, before)
            self.assertIn('已更新正文', result['messages'][0].content)
            active = [f['text'] for f in result['collected_info']['work_experience'][0]['facts'] if f['status'] == 'active']
            self.assertNotIn(old, '\n'.join(active))
            self.assertIn(new, '\n'.join(active))
            for bullet, meta in zip(expected['work_experience'][0]['bullets'], result['resume_meta']['bullets']['work']):
                self.assertEqual(meta['text_hash'], text_hash(bullet))

    async def test_correction_failure_never_claims_updated_or_changes_facts(self):
        state = correction_state('tech')
        state['resume_data']['work_experience'][0]['bullets'] = ['没有该数字的旧稿']
        before = deepcopy(state)
        result = await graph.evaluating_node(state, object())
        self.assertNotIn('resume_data', result)
        self.assertNotIn('collected_info', result)
        self.assertNotIn('已更新', result['messages'][0].content)
        self.assertIn('未保存更正', result['messages'][0].content)
        self.assertEqual(state, before)

    def test_correction_short_form_and_ambiguous_owner(self):
        state = correction_state('career')
        pairs = correction_pairs('6 场改 4 场')
        result = apply_literal_corrections(state['collected_info'], state['resume_data'], state['resume_meta'], pairs)
        self.assertNotIn('error', result)
        facts = deepcopy(state['collected_info'])
        other = deepcopy(facts['work_experience'][0])
        other['item_id'] = 'different'
        facts['work_experience'].append(other)
        self.assertIn('error', apply_literal_corrections(facts, state['resume_data'], state['resume_meta'], pairs))
        self.assertEqual(correction_pairs('不要把6 场改 4 场'), [])

    def test_same_number_in_other_fact_and_numeric_substring_stay_unchanged(self):
        state = correction_state('career')
        other = new_fact('参加6 场会议，登记16 场活动')
        state['collected_info']['work_experience'][0]['facts'].append(other)
        state['resume_data']['work_experience'][0]['bullets'].append(other['text'])
        result = apply_literal_corrections(state['collected_info'], state['resume_data'], state['resume_meta'],
                                          correction_pairs(FIXTURES['career']['correction']))
        self.assertNotIn('error', result)
        self.assertEqual(result['resume_data']['work_experience'][0]['bullets'][-1], other['text'])

    async def test_corrected_draft_is_saved_before_success_receipt(self):
        state = correction_state('tech')
        state['messages'] = []
        compiled = graph.build_graph(object())
        config = {'configurable': {'thread_id': 'synthetic-persona-correction'}}
        await compiled.aupdate_state(config, state)
        events, saved = [], []
        def save(**kwargs):
            saved.append(deepcopy(kwargs))
            events.append('saved')
        with patch.object(graph, 'get_graph', return_value=compiled), patch('app.services.session_store.save_resume_session', side_effect=save):
            async for chunk in graph.stream_agent([{'content': FIXTURES['tech']['correction']}],
                                                   'synthetic-persona-correction', object()):
                events.append(chunk)
        self.assertEqual(events[0], 'saved')
        self.assertIn('190ms', str(saved[-1]['resume_data']))
        self.assertNotIn('170ms', str(saved[-1]['resume_data']))

    async def test_mixed_tech_first_draft_keeps_jd_and_all_candidate_sections(self):
        model = PersonaModel('tech')
        decoded = AsyncMock(return_value=({'job_title': 'Java 后端开发', 'role_direction': 'Java 后端开发'}, '岗位已解析'))
        state = {**graph._init_state(), 'messages': [HumanMessage(content=FIXTURES['tech']['initial'], id='first')]}
        with patch.object(graph, '_run_decoder_and_build_reply', decoded), patch.object(graph, '_make_non_streaming_llm', return_value=model):
            result = await graph.jd_input_node(state, model)
        self.assertEqual(decoded.await_count, 1)
        self.assertNotIn('420ms', decoded.await_args.args[0])
        self.assertIn('要求 Java', result['jd_text'])
        self.assertTrue(model.inputs)
        self.assertNotIn('目标岗位 JD', model.inputs[0])
        self.assertIn('420ms', model.inputs[0])
        data = result['resume_data']
        self.assertEqual(len(data['education']), 1)
        self.assertEqual(len(data['work_experience']), 1)
        self.assertEqual([row['name'] for row in data['projects']], ['校园二手交易系统'])
        self.assertTrue(data['work_experience'][0]['bullets'])
        self.assertTrue(data['projects'][0]['polished_bullets'])
        self.assertNotIn('Kubernetes', str(data.get('skills')) + str(data.get('skill_groups')))

    async def test_complete_tech_material_direct_generation_skips_plan_confirmation(self):
        model = PersonaModel('tech')
        with patch.object(get_settings(), 'LLM_PLAN_CONFIRM', True), patch.object(graph, '_run_decoder_and_build_reply',
                AsyncMock(return_value=({'job_title': 'Java 后端开发'}, '岗位已解析'))), patch.object(graph, '_make_non_streaming_llm', return_value=model):
            result = await graph.jd_input_node({**graph._init_state(), 'plan_required': True,
                    'messages': [HumanMessage(content=FIXTURES['tech']['initial'], id='first')]}, model)
        self.assertEqual(result['stage'], 'EVALUATING')
        self.assertFalse(result.get('pending_plan'))
        self.assertTrue(result['resume_data']['projects'][0]['polished_bullets'])
        self.assertTrue(result['resume_data']['work_experience'][0]['bullets'])

    async def test_design_attachment_overrides_wrong_jd_classification_and_recovers(self):
        attachment = '[文件: design-material.txt]\n' + ATTACHMENT
        text = attachment + '\n\n---\n\n' + FIXTURES['design']['initial']
        wrong = TriageDecision(action=TriageAction.DECODE_JD, reason='model misclassified attachment')
        state = {**graph._init_state(), 'messages': [HumanMessage(content=text, id='upload', additional_kwargs={'career_material_type': 'jd'})]}
        with patch.object(graph, 'run_triage', AsyncMock(return_value=wrong)), patch.object(graph, '_run_decoder_and_build_reply', AsyncMock(side_effect=AssertionError('personal material is not JD'))):
            result = await graph.jd_input_node(state, EchoWriter())
        self.assert_design(result)
        recovery = {**graph._init_state(), 'stage': 'COLLECTING', 'jd_text': attachment,
                    'jd_info': {'job_title': '12个页面18个组件'}, 'non_candidate_message_ids': ['upload'],
                    'messages': [state['messages'][0], HumanMessage(content=FIXTURES['design']['recovery'], id='recovery')]}
        recovered = await graph.collecting_node(recovery, EchoWriter())
        if recovered.get('stage') == 'BUILDING':
            recovered = {**recovered, **(await graph.building_node({**recovery, **recovered}, EchoWriter()))}
        self.assert_design(recovered)
        self.assertEqual(recovered.get('jd_info'), {})
        self.assertEqual(recovered.get('jd_text'), '')

    def assert_design(self, result):
        data = result['resume_data']
        self.assertEqual(data['basic_info']['name'], '许禾')
        self.assertEqual(data['education'][0]['major'], '视觉传达设计')
        self.assertEqual([item['name'] for item in data['projects']], ['校园借物 App 概念设计'])
        self.assertEqual(len(data['campus']), 1)
        body = ' '.join(data['projects'][0]['polished_bullets'])
        for number in ('12', '18', '5'):
            self.assertIn(number, body)
        self.assertNotIn('没有前端', str(data.get('skills')) + str(data.get('skill_groups')))
        self.assertNotIn('虚构测试', str(data.get('skills')))
        self.assertNotIn('请读', str(data.get('skills')))

    def test_design_paste_and_denied_skill_display(self):
        parsed = parse_existing_resume(FIXTURES['design']['paste'])
        self.assertEqual(len(parsed['projects']), 1)
        self.assertEqual(len(parsed['campus']), 1)
        self.assertEqual(parsed['education'][0]['major'], '视觉传达设计')
        groups = normalize_skill_groups({'开发': ['不会 Kubernetes', '没有前端开发经验'], '工具': ['Figma']})
        self.assertEqual(groups, {'工具': ['Figma']})

    async def test_service_school_prefix_does_not_duplicate_education(self):
        facts = await facts_for('service')
        self.assertEqual([row['school'] for row in facts['education']], ['新城职业学院'])
        result = await graph.building_node({**graph._init_state(), 'collected_info': facts,
            'messages': [HumanMessage(content=FIXTURES['service']['initial'])]}, EchoWriter())
        self.assertEqual([row['school'] for row in result['resume_data']['education']], ['新城职业学院'])


class PersonaRemainingRegressions(unittest.IsolatedAsyncioTestCase):
    setUp = PersonaRegressions.setUp

    async def test_initial_direction_and_experience_are_extracted_together(self):
        for persona in ('ops', 'service', 'career', 'tech'):
            model = PersonaModel(persona)
            state = {**graph._init_state(), 'messages': [HumanMessage(content=FIXTURES[persona]['initial'])]}
            decision = TriageDecision(action=TriageAction.READY_TO_BUILD, reason='synthetic', jd_keywords=[FIXTURES[persona]['role']])
            with patch.object(graph, 'run_triage', AsyncMock(return_value=decision)), patch.object(graph, '_make_non_streaming_llm', side_effect=lambda model, **kw: model):
                result = await graph.jd_input_node(state, model)
            self.assertTrue(model.inputs, persona)
            self.assertIn('我叫' if persona != 'tech' else '姓名林泽', model.inputs[0])
            self.assertTrue(result['collected_info']['work_experience'] or result['collected_info']['internship'], persona)
            self.assertTrue(result.get('resume_data'), persona)
            self.assertNotIn('可以一次把所有经历', str(result['messages']))

    async def test_facts_commit_before_reply_exception_and_survive_next_turn(self):
        model = PersonaModel('ops')
        compiled = graph.build_graph(model)
        saved = []
        def save(**values):
            saved.append(deepcopy(values))
        async def fail_reply(*args, **kwargs):
            self.assertTrue(saved)
            self.assertTrue(saved[-1]['collected_info']['campus'])
            raise RuntimeError('synthetic reply failure')
        with patch.object(graph, 'get_graph', return_value=compiled), patch.object(graph, '_make_non_streaming_llm', side_effect=lambda model, **kw: model), patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(action=TriageAction.ASK_EXPERIENCE, reason='synthetic'))), patch('app.agents.interviewer.first_draft_ready', return_value=False), patch.object(graph, '_collection_reply', side_effect=fail_reply), patch('app.services.session_store.save_candidate_intake', side_effect=save):
            with self.assertRaises(Exception):
                _ = [chunk async for chunk in graph.stream_agent([{'content': FIXTURES['ops']['initial']}], 'persona-error', model)]
        snapshot = await compiled.aget_state({'configurable': {'thread_id': 'persona-error'}})
        self.assertEqual(snapshot.values['collected_info'], saved[-1]['collected_info'])
        self.assertTrue(snapshot.values['collected_info']['campus'])

    async def test_failed_reply_intake_can_be_loaded_from_sql(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.database import Base
        from app.services import session_store
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        model = PersonaModel('ops')
        compiled = graph.build_graph(model)
        try:
            with patch.object(session_store, 'SessionLocal', sessionmaker(bind=engine)), patch.object(graph, 'get_graph', return_value=compiled), patch.object(graph, '_make_non_streaming_llm', side_effect=lambda model, **kw: model), patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(action=TriageAction.ASK_EXPERIENCE, reason='synthetic'))), patch('app.agents.interviewer.first_draft_ready', return_value=False), patch.object(graph, '_collection_reply', AsyncMock(side_effect=RuntimeError('synthetic reply failure'))):
                with self.assertRaises(Exception):
                    _ = [chunk async for chunk in graph.stream_agent([{'content': FIXTURES['ops']['initial']}], 'persona-sql', model)]
                stored = session_store.load_resume_session('persona-sql')
                self.assertTrue(stored['collected_info']['campus'])
                self.assertEqual(stored['collected_info']['basic_info']['name'], '陈夏')
                self.assertEqual(stored['resume_data'], {})
                snapshot = await compiled.aget_state({'configurable': {'thread_id': 'persona-sql'}})
                self.assertEqual(snapshot.values['collected_info'], stored['collected_info'])
        finally:
            engine.dispose()

    async def test_client_disconnect_continues_extraction_and_holds_session_lock(self):
        from app.api.chat import _complete_on_disconnect
        from app.services.session_store import session_lock
        entered, release, done = asyncio.Event(), asyncio.Event(), asyncio.Event()
        saved = []
        model = PersonaModel('ops')
        compiled = graph.build_graph(model)
        original = model.ainvoke
        async def delayed(messages):
            if 'existing' in json.loads(messages[-1].content):
                entered.set()
                await release.wait()
            return await original(messages)
        model.ainvoke = delayed
        async def source():
            async with session_lock('persona-disconnect'):
                yield 'started'
                async for chunk in graph.stream_agent([{'content': FIXTURES['ops']['initial']}], 'persona-disconnect', model):
                    yield chunk
                done.set()
        with patch.object(graph, 'get_graph', return_value=compiled), patch.object(graph, '_make_non_streaming_llm', side_effect=lambda model, **kw: model), patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(action=TriageAction.READY_TO_BUILD, reason='synthetic'))), patch('app.services.session_store.save_candidate_intake', side_effect=lambda **kw: saved.append(deepcopy(kw))), patch('app.services.session_store.save_resume_session', side_effect=lambda **kw: saved.append(deepcopy(kw))):
            stream = _complete_on_disconnect(source())
            self.assertEqual(await anext(stream), 'started')
            await asyncio.wait_for(entered.wait(), 2)
            await stream.aclose()
            self.assertTrue(session_lock('persona-disconnect').locked())
            release.set()
            await asyncio.wait_for(done.wait(), 5)
        self.assertTrue(saved[-1]['collected_info']['campus'])
        self.assertTrue(saved[-1]['resume_data'])
        self.assertFalse(session_lock('persona-disconnect').locked())

    async def test_career_whole_message_and_instructions_never_become_a_project(self):
        text = FIXTURES['career']['initial']
        patch_data = {'items': [{'section': 'projects', 'name': '对话中描述的经历', 'facts': [raw(text)]}]}
        result = await extract_facts_patch(text, {}, ExtractorStub(patch_data))
        body = '\n'.join(f['text'] for item in result['items'] if item['section'] != 'education' for f in item['facts'])
        for unwanted in ('周宁', '南川大学', '请先做', '不要把行政', '不能增加'):
            self.assertNotIn(unwanted, body)
        self.assertNotIn('对话中描述的经历', str(result['items']))
        for text in (FIXTURES['career']['initial'], FIXTURES['career']['polish']):
            self.assertFalse(graph._harvest_projects_from_messages([HumanMessage(content=text)]))
        from app.agents.tailor_pipeline import constraints_for_turn
        self.assertIn('不能增加', str(constraints_for_turn({}, FIXTURES['career']['polish'])['writing_rules']))

    def test_unsuffixed_company_and_position_and_negative_places(self):
        from app.services.candidate_language import literal_employment, literal_item_name
        for company, title in (('云舟科技', '后端开发实习生'), ('启明商贸', '全职行政助理')):
            for verb in ('做', '当', '任'):
                self.assertEqual(literal_employment(f'在{company}{verb}{title}'), (company, title))
                self.assertEqual(literal_item_name(f'在{company}{verb}{title}', 'work_experience'), company)
        for place in ('大学', '学校', '家', '某大学', '一家', '学习中心', '负责系统'):
            self.assertEqual(literal_item_name(f'在{place}做后端开发实习生', 'internship'), '')

    async def test_extractor_recovers_employment_header_from_unnamed_model_item(self):
        for persona, company, title in (('tech', '云舟科技', '后端开发实习生'), ('career', '启明商贸', '全职行政助理')):
            source = FIXTURES[persona]['initial']
            section = 'internship' if persona == 'tech' else 'work_experience'
            clause = re.search(r'在' + company + r'[^，。；]+', source)[0]
            result = await extract_facts_patch(source, {}, ExtractorStub({'items': [
                {'section': section, 'name': '', 'facts': [raw(clause)]}]}))
            employment = next(item for item in result['items'] if item['section'] == section)
            self.assertEqual(employment['name'], company)
            self.assertTrue(any(f.get('field') == 'title' and f['text'] == title for f in employment['facts']))

    async def test_all_numbers_survive_overcitation_and_one_bullet_budget(self):
        from app.agents.resume_writer import run_resume_writer
        from test_resume_writer import FakeModel, ROLE, draft, item, plan, fact
        texts = ['编写12条接口测试用例', '整理8份接口文档', '修复4个接口错误']
        source = {'projects': [{'item_id': 'p1', 'name': '接口工具',
                  'facts': [fact('n' + str(i), text, kind='action') for i, text in enumerate(texts)]}]}
        model = FakeModel([('OnePassOutput', {'match_plan': {**plan({'p1': 'keep'}), 'experience_plan': [
            {'item_id': 'p1', 'treatment': 'keep', 'target_bullets': 1}]},
            'writer': draft([item('p1', 'projects', [('编写接口测试用例', ['n0', 'n1', 'n2'])])])})])
        result = await run_resume_writer(source, ROLE, model, instruction='只写一条')
        bullets = result['resume_data']['projects'][0]['polished_bullets']
        self.assertEqual(len(bullets), 1)
        for text in texts:
            self.assertIn(text, bullets[0])

    async def test_required_limits_and_numeric_action_survive_a_writer_that_omits_them(self):
        from app.agents.resume_writer import run_resume_writer
        from app.agents.tailor_pipeline import constraints_for_turn
        facts = await facts_for('tech')
        class OmittingWriter(EchoWriter):
            async def ainvoke(self, messages):
                response = await super().ainvoke(messages)
                for item in response['writer']['items']:
                    item['bullets'] = [b for b in item['bullets'] if '12 条' not in b['text'] and '登录' not in b['text']]
                    for bullet in item['bullets']:
                        bullet['text'] = bullet['text'].replace('，没做线上压测', '').replace('，没有真实用户', '')
                return response
        result = await run_resume_writer(facts, {}, OmittingWriter(), constraints=constraints_for_turn({}, FIXTURES['tech']['initial']))
        data = result['resume_data']
        work = ' '.join(b for i in data['work_experience'] for b in i['bullets'])
        project = ' '.join(b for i in data['projects'] for b in i['polished_bullets'])
        for word in ('12', '接口测试', '测试环境', '线上压测', '导师指导'):
            self.assertIn(word, work)
        for word in ('登录', '同学', '没有真实用户', '演示'):
            self.assertIn(word, project)
        self.assertTrue(any('170' in b and '线上压测' in b for i in data['work_experience'] for b in i['bullets']))

    async def test_career_correction_routes_from_legacy_collecting_without_writer(self):
        for message in (FIXTURES['career']['correction'], '内部培训次数改成 4 场，通讯录仍是120人'):
            state = correction_state('career')
            state.update(stage='COLLECTING', messages=[HumanMessage(content=message)])
            with patch.object(graph, '_write_resume_update', AsyncMock(side_effect=AssertionError('no writer'))), patch.object(graph, '_extract_info_from_message', AsyncMock(side_effect=AssertionError('no extraction'))):
                result = await graph.collecting_node(state, object())
            body = str(result['resume_data']['work_experience'])
            self.assertIn('4 场', body)
            self.assertNotIn('6 场', body)
            self.assertIn('120', body)
            self.assertIn('已更新正文', result['messages'][0].content)

    def test_public_receipt_only_explains_overflow(self):
        data = correction_state('tech')['resume_data']
        for pages in (1, 2):
            reply = graph._writer_reply({'resume_data': data, 'changed': True, 'page_check': {
                'status': 'rendered', 'pages': pages, 'page_limit': 1, 'within_page_limit': pages == 1}})
            self.assertNotIn('当前排版', reply)
            self.assertNotIn('档', reply)
            if pages == 1:
                self.assertNotIn('页', reply)
            else:
                self.assertIn('第 2 页', reply)
                self.assertIn('压缩', reply)



if __name__ == '__main__':
    unittest.main()
