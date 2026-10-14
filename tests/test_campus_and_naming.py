"""Fictional nontechnical intake, including imperfect model output and failed writing."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.agents import resume_graph as graph
from app.agents.fact_extractor import apply_fact_patch, extract_facts_patch
from app.agents.resume_writer import run_resume_writer, SECTIONS
from app.agents.turn_actions import bind_role_followup, parse_education_fields
from app.schemas.editor import ResumeData
from app.services.candidate_language import PLACEHOLDER_NAMES, literal_item_name, resume_bullet, safe_objective
from app.services.candidate_sections import parse_header_fields, parse_labelled_items
from app.services.canonical_resume import editor_facts
from app.services.fact_guard import lexical_fact_errors
from app.services.profile_service import context_to_collected_info
from app.services.renderer import TEMPLATES, render_resume
from app.services.resume_facts import new_fact
from app.services.resume_review import resume_to_text
from app.tools.resume_data_docx import resume_data_to_docx


INTRO = '我在青栖职业学院读艺术设计专科，毕业一年了。我不知道自己适合什么岗位，但是希望工作能融入AI。我想知道还有哪些岗位适合我'
CAMPUS = '大学的时候我参与了大学生观影协会，在协会的宣传部中担任副部长，我运用可画完成了约10张海报。个人认为能力尚浅，我认为可以接单'
WORK = '毕业后我做采购和行政，采购的是仪表连接件，工作内容为与客户对接信息、办公平台提报申请付款、网站报价。行政主要为办公区日常用品管理与采购、员工考勤管理记录、办公室卫生管理'
SCOPE = '对接2家客户，考勤和办公用品管理覆盖20余人'


def raw(text, **extra):
    return {'kind': 'action', 'text': text, 'source_quote': text, **extra}


class ExtractorStub:
    def __init__(self, output):
        self.output = output

    async def ainvoke(self, messages):
        return SimpleNamespace(content=json.dumps(self.output, ensure_ascii=False))


class EchoWriter:
    """Schema-correct writer that still repeats conversational source text."""
    def __init__(self, fail=False):
        self.schema = None
        self.payload = None
        self.fail = fail

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        if self.fail:
            raise RuntimeError('synthetic writer outage')
        self.payload = json.loads(messages[-1].content)
        # Read the supplied active facts, preserving every item and source ID.
        evidence = self.payload['evidence']
        rows = []
        for section in SECTIONS:
            for item in evidence.get(section, []):
                body = [fact for fact in item['facts'] if not fact.get('field')]
                rows.append({'section': section, 'item_id': item['item_id'], 'bullets': [
                    {'text': fact['text'], 'fact_ids': [fact['id']]} for fact in body]})
        return {'match_plan': {}, 'writer': {'items': rows}}


async def semantic_stub(rows, *args, **kwargs):
    return {row['id']: {'verdict': 'pass'} for row in rows}


async def fixture():
    """Each state is obtained from the preceding extraction, never a prebuilt owner."""
    current = {}
    outputs = [
        (INTRO, {'basic_info': {'objective': INTRO}, 'items': []}),
        (CAMPUS, {'items': [{'section': 'open_source', 'name': '了大学生观影协会',
                            'facts': [raw(CAMPUS)], 'raw_notes': [CAMPUS]}]}),
        (WORK, {'items': [{'section': 'work_experience', 'name': '采购及行政工作',
                          'facts': [raw(WORK)], 'raw_notes': [WORK]}]}),
    ]
    for text, output in outputs:
        current = apply_fact_patch(current, await extract_facts_patch(text, current, ExtractorStub(output)))
    return current


class CampusNamingTest(unittest.IsolatedAsyncioTestCase):
    async def test_new_work_survives_invented_label_then_short_answer_binds(self):
        current = await fixture()
        work = current['work_experience'][0]
        self.assertEqual(work['company'], PLACEHOLDER_NAMES['work_experience'])
        self.assertTrue(work['facts'])
        question = '需要你补充：采购对接几家客户？考勤和办公用品管理覆盖多少人？'
        bound = graph._finish_followup_turn({'collected_info': {}}, {
            'collected_info': current, 'messages': [AIMessage(content=question)]})
        current = bound['collected_info']
        previous = '\n\n'.join(m.content for m in bound['messages'])
        result = await graph._extract_with_previous_assistant(SCOPE, current, ExtractorStub({
            'items': [{'section': 'work_experience', 'name': '采购行政经历',
                       'facts': [raw(part, kind='scope_scale') for part in SCOPE.split('，')]}]}), previous)
        self.assertEqual(len(result['work_experience']), 1)
        self.assertEqual(result['work_experience'][0]['item_id'], work['item_id'])
        self.assertTrue(all(any(part == f['source_quote'] for f in result['work_experience'][0]['facts'])
                            for part in SCOPE.split('，')))
        self.assertFalse(result.get('unrecorded'))

    async def test_campus_routing_complete_name_major_and_objective(self):
        current = await fixture()
        self.assertEqual(current['campus'][0]['name'], '大学生观影协会')
        self.assertFalse(current.get('open_source'))
        self.assertEqual(parse_education_fields(CAMPUS), {})
        self.assertEqual(parse_education_fields(INTRO)['major'], '艺术设计')
        self.assertFalse(current.get('basic_info', {}).get('objective'))
        self.assertIn(INTRO, current['metadata_context'])
        data = graph._serialize_to_resume_data({'collected_info': current, 'jd_info': {'target_role': INTRO}})
        self.assertEqual(data['campus'][0]['role'], '副部长')
        self.assertEqual(data['basic_info']['objective'], '')

    async def test_name_asked_once_and_literal_answer_renames_without_id(self):
        current = await fixture()
        first = graph._finish_followup_turn({}, {'collected_info': current, 'messages': [AIMessage(content='已记下。')]})
        self.assertIn('的名称是什么', first['messages'][-1].content)
        previous = '\n\n'.join(m.content for m in first['messages'])
        answer = '公司名字是澄原设备公司'
        result = await graph._extract_with_previous_assistant(answer, first['collected_info'], ExtractorStub({}), previous)
        self.assertEqual(result['work_experience'][0]['company'], '澄原设备公司')
        self.assertEqual(len(result['work_experience']), 1)
        ignored = graph._finish_followup_turn(first, {'collected_info': first['collected_info'], 'messages': [AIMessage(content='可以继续补充。')]})
        self.assertEqual(len(ignored['messages']), 1)

    async def test_project_naming_answer_does_not_create_second_item(self):
        original = '我整理了社群通知'
        current = apply_fact_patch({}, await extract_facts_patch(original, {}, ExtractorStub({'items': [
            {'section': 'projects', 'name': '社群整理实践', 'facts': [raw(original)]}]})))
        first = graph._finish_followup_turn({}, {'collected_info': current, 'messages': [AIMessage(content='已记下。')]})
        for output in ({}, {'items': [{'section': 'projects', 'name': '栖木', 'facts': [raw('项目叫栖木')]}]}):
            with self.subTest(output=bool(output)):
                renamed = await graph._extract_with_previous_assistant(
                    '项目叫栖木', first['collected_info'], ExtractorStub(output), first['messages'][-1].content)
                self.assertEqual(len(renamed['projects']), 1)
                self.assertEqual(renamed['projects'][0]['name'], '栖木')
                self.assertEqual(renamed['projects'][0]['item_id'], current['projects'][0]['item_id'])

    async def test_new_campus_item_does_not_steal_technical_project(self):
        text = '我为观影协会开发了报名网站'
        current = apply_fact_patch({}, await extract_facts_patch(text, {}, ExtractorStub({'items': [
            {'section': 'projects', 'name': '报名网站', 'facts': [raw(text)]}]})))
        self.assertFalse(current.get('campus'))
        self.assertTrue(current['projects'][0]['facts'])

    async def test_model_major_cannot_be_taken_from_association(self):
        text = '我参与了大学生读书协会'
        result = await extract_facts_patch(text, {}, ExtractorStub({'items': [
            {'section': 'education', 'name': '大学', 'facts': [raw('读书协会', field='major')]}]}))
        self.assertFalse(any(f.get('field') == 'major' for item in result['items'] for f in item['facts']))

    async def test_role_header_is_extracted_from_quote_not_rewritten_claim(self):
        text = '在观影协会担任干事'
        result = await extract_facts_patch(text, {}, ExtractorStub({'items': [
            {'section': 'open_source', 'name': '宣传实践', 'facts': [
                {'text': '在观影协会担任部长，主导全部宣传工作', 'source_quote': text}]}]}),
                semantic_check=lambda pairs: {})
        self.assertFalse(any('部长' in f['text'] for item in result['items'] for f in item['facts']))

    async def test_all_sections_use_writer_and_failed_writer_cleans_prose(self):
        current = await fixture()
        for section in ('projects', 'internship', 'open_source', 'awards'):
            label = 'company' if section == 'internship' else 'name'
            current[section] = [{'item_id': section, label: section, 'facts': [new_fact('我整理了活动材料')]}]
        serialized = graph._serialize_to_resume_data({'collected_info': current})
        for failed in (False, True):
            with self.subTest(failed=failed), patch('app.services.fact_guard.verify_semantics', semantic_stub):
                writer = EchoWriter(failed)
                result = await run_resume_writer(current, {}, writer, current_data=serialized)
                data = result['resume_data']
                if not failed:
                    self.assertEqual(result['writer_diagnostic']['status'], 'model_completed')
                for section in SECTIONS:
                    self.assertTrue(data[section], section)
                    for item in data[section]:
                        bullets = item.get('polished_bullets' if section == 'projects' else 'bullets') or []
                        self.assertTrue(bullets, (section, item))
                        self.assertEqual(len(bullets), len(set(bullets)))
                        text = ' '.join(bullets)
                        for unwanted in ('我', '大学的时候', '个人认为', '可以接单', '哪些岗位', '担任副部长', '参与了大学生观影协会'):
                            self.assertNotIn(unwanted, text)
                campus_text = ' '.join(data['campus'][0]['bullets'])
                self.assertIn('可画', campus_text)
                self.assertIn('10', campus_text)
                self.assertNotIn('独立设计', campus_text)

    async def test_fabricated_number_and_responsibility_still_rejected(self):
        text = '运用可画完成海报'
        result = await extract_facts_patch(text, {}, ExtractorStub({'items': [{
            'section': 'campus', 'name': '宣传经历', 'facts': [
                {'text': '运用可画完成99张海报', 'source_quote': text},
                {'text': '独立设计海报', 'source_quote': text}]}]}))
        facts = [f['text'] for row in result['items'] for f in row['facts']]
        self.assertNotIn('运用可画完成99张海报', facts)
        self.assertNotIn('独立设计海报', facts)
        self.assertTrue(lexical_fact_errors('独立设计海报', text))

    async def test_writer_upgrade_falls_back_to_supported_tool_action(self):
        from test_resume_writer import FakeModel
        source = {'campus': [{'item_id': 'c1', 'name': '观影协会', 'facts': [new_fact('运用可画完成海报')]}]}
        fid = source['campus'][0]['facts'][0]['id']
        model = FakeModel([('OnePassOutput', {'match_plan': {}, 'writer': {'items': [
            {'item_id': 'c1', 'section': 'campus', 'bullets': [
                {'text': '独立设计99张海报', 'fact_ids': [fid]}]}]}}), ('RepairOutput', {'bullets': []})])
        result = await run_resume_writer(source, {}, model)
        self.assertEqual(result['resume_data']['campus'][0]['bullets'], ['运用可画完成海报'])
        self.assertTrue(result['guard_fallbacks'])

    async def test_independent_answer_does_not_create_team_question(self):
        current = await fixture()
        for answer in ('运用了可画，但是是我独立完成的', '我一个人做的'):
            result = bind_role_followup(current, '这部分是独立完成还是团队协作？', answer)
            self.assertFalse(result.get('pending_ownership'))
            self.assertNotIn('团队分工', graph.unrecorded_notice(result, answer))
        current['pending_ownership'] = [{'source_quote': '我一个人做的'}]
        self.assertNotIn('团队分工', graph.unrecorded_notice(current, '我一个人做的'))

    async def test_receipt_all_combinations_are_grammatical(self):
        text = '我完成了海报，还处理了报名'
        for recorded in (False, True):
            for prefix in ('已记下', '部分已记下'):
                current = {'unrecorded': {'source': graph._hash_text(text), 'clauses': ['还处理了报名']}}
                if recorded:
                    current['campus'] = [{'item_id': 'c', 'name': '观影协会', 'facts': [new_fact('我完成了海报')]}]
                async def stream(llm, messages, **kwargs):
                    return AIMessage(content=kwargs.get('transform', lambda x: x)(prefix + '，右侧草稿会同步更新。'))
                with patch.object(graph, 'stream_public_reply', stream):
                    reply = await graph._collection_reply(object(), [], current, text)
                self.assertNotIn('部分这轮', reply.content)
                self.assertNotIn('部分部分', reply.content)
                self.assertIn('部分已记下' if recorded else '这轮还有内容需要确认', reply.content)


class CampusPresentationTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_campus_editor_fields_and_legacy_defaults(self):
        result = subprocess.run(['node', str(Path(__file__).with_name('campus_editor.dom.js'))],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('campus editor DOM checks passed', result.stdout)

    def test_literal_names_and_objective_boundary(self):
        self.assertEqual(literal_item_name(CAMPUS, 'campus'), '大学生观影协会')
        self.assertEqual(graph._guess_project_name('做产品排版这些基础的工作在大学'), '')
        self.assertEqual(literal_item_name('我在澄原设备公司负责报价', 'work_experience'), '澄原设备公司')
        self.assertEqual(literal_item_name('我在宣传部担任干事', 'campus'), '宣传部')
        for value in ('视觉设计', '电商美工', 'AIGC 设计助理'):
            self.assertEqual(safe_objective(value), value)
        for value in (INTRO, '我想知道哪些岗位适合我', '我不知道做什么', '希望做设计', '工作能融入AI'):
            self.assertEqual(safe_objective(value), '')
            self.assertNotIn('objective', parse_header_fields('求职意向：' + value))
        self.assertEqual(resume_bullet('大学的时候我完成了海报，个人认为能力尚浅，我想知道有哪些岗位，我完成了海报'), '完成了海报')

    def test_placeholder_labels_never_leak_into_rendered_body(self):
        label = PLACEHOLDER_NAMES['projects']
        data = {'projects': [{'name': label, 'role': label, 'description': label,
                              'polished_bullets': [label, '整理海报素材']}],
                'campus': [{'name': PLACEHOLDER_NAMES['campus'], 'bullets': ['维护社团台账']}]}
        self.assertNotIn(label, resume_to_text(data))
        for template in TEMPLATES:
            html = render_resume(template['id'], data)
            self.assertNotIn(label, html)
            self.assertNotIn(PLACEHOLDER_NAMES['campus'], html)
            self.assertIn('[待补]', html)

    def test_schema_templates_docx_and_canonical_roundtrip(self):
        data = ResumeData.model_validate({'campus': [{'name': '观影协会', 'role': '宣传部副部长', 'bullets': ['运用可画完成约10张海报']}],
                                         'work_experience': [{'company': PLACEHOLDER_NAMES['work_experience'], 'bullets': ['核对付款申请']}]}).model_dump()
        self.assertEqual(editor_facts(data)['campus'][0]['name'], '观影协会')
        self.assertEqual(ResumeData().campus, [])
        for template in TEMPLATES:
            html = render_resume(template['id'], data)
            self.assertIn('校园经历', html)
            self.assertIn('/campus/0/role', html)
            self.assertIn('/campus/0/bullets/0', html)
            self.assertIn('[待补]', html)
            self.assertNotIn(PLACEHOLDER_NAMES['work_experience'], html)
        from docx import Document
        doc = Document(io.BytesIO(resume_data_to_docx(data)))
        text = '\n'.join(p.text for p in doc.paragraphs)
        self.assertIn('校园经历', text)
        self.assertIn('观影协会', text)
        self.assertIn('约10张海报', text)
        self.assertNotIn(PLACEHOLDER_NAMES['work_experience'], text)
        self.assertIn('校园经历', resume_to_text(data))

    def test_profile_projection_and_labelled_import(self):
        context = {'facts': [{'id': 'f1', 'revision': 1, 'category': 'campus', 'subject': '观影协会',
                              'field': 'role', 'value': '宣传部副部长'},
                             {'id': 'f2', 'revision': 1, 'category': 'campus', 'subject': '观影协会',
                              'field': 'description', 'value': '制作海报'}]}
        result = context_to_collected_info(context)
        self.assertEqual(result['campus'][0]['role'], '宣传部副部长')
        self.assertEqual(result['campus'][0]['bullets'], ['制作海报'])
        self.assertEqual(parse_labelled_items('校园经历\n观影协会｜宣传部副部长\n制作约10张海报')['campus'][0]['name'], '观影协会')


if __name__ == '__main__':
    unittest.main()
