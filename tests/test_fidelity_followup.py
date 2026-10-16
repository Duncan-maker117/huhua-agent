"""Fictional design graduate replay with deliberately incomplete model output."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from test_campus_and_naming import ExtractorStub, EchoWriter, raw, semantic_stub
from test_resume_writer import FakeModel
from app.agents import resume_graph as graph
from app.agents.fact_extractor import apply_fact_patch, extract_facts_patch, _owner_item
from app.agents.resume_writer import run_resume_writer, _without_repeated_fact_rows, _without_near_duplicate_rows
from app.agents.turn_actions import parse_education_fields
from app.schemas.editor import ResumeData
from app.services.candidate_skills import canonical_skill_text
from app.services.education_fields import clean_education_value
from app.services.fact_coverage import ensure_fact_coverage, text_covered
from app.services.fact_guard import normalize_text, validate_skill_groups
from app.services.resume_facts import new_fact, normalize_fact_store
from app.services.resume_review import resume_to_text
from app.services.resume_sections import get_resume_sections
from app.services.renderer import render_resume

WORK_FACTS = ['采购实验配件与测量器材', '对接客户信息', '用办公平台提报申请付款', '网站报价',
              '采购对接3家客户及散客', '办公区日常用品管理与采购', '员工考勤管理记录',
              '办公室卫生管理', '考勤和办公用品覆盖30余人', '对接3家客户']
COURSE = '大学摄影课中的商业摄影作业：店铺网页设计，产品拍摄和页面排版，基本独立完成'
TOOLS = '我会用ps和ai做设计，会用Word/Exce/pptl，做过日常摄影和产品拍摄，用过即梦和workbuddy辅助排版，用过可画'


def work_source():
    return {'work_experience': [{'item_id': 'work', 'company': '松澜仪器公司',
                                'facts': [new_fact(text) for text in WORK_FACTS]}]}


class FidelityFollowupTests(unittest.IsolatedAsyncioTestCase):
    async def test_incomplete_writer_restores_responsibilities_even_with_all_ids(self):
        source = work_source()
        facts = source['work_experience'][0]['facts']
        model = FakeModel([('OnePassOutput', {'match_plan': {}, 'writer': {'items': [{
            'item_id': 'work', 'section': 'work_experience', 'bullets': [
                {'text': '采购实验配件与测量器材，采购对接3家客户及散客',
                 'fact_ids': [fact['id'] for fact in facts]}]}]}})])
        with patch('app.services.fact_guard.verify_semantics', semantic_stub):
            result = await run_resume_writer(source, {}, model)
        bullets = result['resume_data']['work_experience'][0]['bullets']
        for text in WORK_FACTS:
            self.assertTrue(text_covered(text, bullets), (text, bullets))
        self.assertEqual(result['resume_meta']['fact_coverage']['coverage_rate'], 1)
        self.assertGreater(result['writer_diagnostic']['coverage_restored'], 0)
        self.assertNotIn('对接3家客户', bullets)

    async def test_secondary_writer_failure_and_compound_fact_keep_administration(self):
        for compound in (False, True):
            source = work_source()
            if compound:
                source['work_experience'][0]['facts'] = [new_fact('；'.join(WORK_FACTS))]
            result = await run_resume_writer(source, {}, EchoWriter(fail=True), primary_call=False)
            bullets = result['resume_data']['work_experience'][0]['bullets']
            self.assertTrue(all(text_covered(text, bullets) for text in WORK_FACTS))

    async def test_explicit_count_has_per_fact_omissions_and_public_reason(self):
        with patch('app.services.fact_guard.verify_semantics', semantic_stub):
            result = await run_resume_writer(work_source(), {}, EchoWriter(), instruction='只保留2条重点')
        omitted = [row for row in result['resume_meta']['fact_coverage']['facts'] if row['status'] == 'omitted']
        self.assertTrue(omitted)
        self.assertTrue(all(row['reason'] for row in omitted))
        self.assertIn('备用', ' '.join(result['change_summary']))

    async def test_course_cannot_bind_campus_by_id_name_or_followup(self):
        current = {'campus': [{'item_id': 'club', 'name': '大学生观影协会',
                               'facts': [new_fact('用可画制作海报')]}],
                   'followup_target': {'item_id': 'club', 'section': 'campus'}}
        for owner in ({'item_id': 'club'}, {'name': '大学生观影协会'}, {'name': '摄影作业'}):
            with self.subTest(owner=owner):
                result = apply_fact_patch(current, await extract_facts_patch(COURSE, current, ExtractorStub({
                    'items': [{'section': 'campus', **owner, 'facts': [raw(COURSE)]}]})))
                self.assertEqual(len(result['campus'][0]['facts']), 1)
                self.assertEqual(result['projects'][0]['name'], '店铺网页设计')
                self.assertEqual(result['projects'][0]['facts'][0]['source_quote'], COURSE)
                with patch('app.services.fact_guard.verify_semantics', semantic_stub):
                    written = await run_resume_writer(result, {}, EchoWriter())
                self.assertNotIn('产品拍摄', ' '.join(written['resume_data']['campus'][0]['bullets']))
                self.assertIn('产品拍摄', ' '.join(written['resume_data']['projects'][0]['polished_bullets']))
        owner = {'section': 'campus', 'item_id': 'club', 'name': '大学生观影协会',
                 'facts': [new_fact('协会宣传部制作海报')], 'raw_notes': []}
        self.assertIsNone(_owner_item([owner], COURSE, '协会宣传部制作海报，' + COURSE, normalize_text))

    async def test_education_clean_at_intake_and_legacy_render(self):
        values = {'school': '学校是澄川职业学院', 'major': '专业为视觉设计', 'degree': '学历是专科',
                  'start_date': '入学年份是2020年', 'end_date': '毕业年份为2023年'}
        sentence = '，'.join(values.values())
        result = await extract_facts_patch(sentence, {}, ExtractorStub({'items': [{
            'section': 'education', 'name': '澄川职业学院',
            'facts': [raw(value, field=field) for field, value in values.items()]}]}))
        fields = {f.get('field'): f['text'] for f in result['items'][0]['facts']}
        self.assertEqual(fields['major'], '视觉设计')
        self.assertEqual(fields['end_date'], '2023')
        self.assertEqual(parse_education_fields(sentence)['end_date'], '2023')
        for field, value in values.items():
            clean = clean_education_value(field, value)
            self.assertEqual(clean_education_value(field, clean), clean)
        legacy = {'education': [values]}
        self.assertEqual(ResumeData.model_validate(legacy).education[0].major, '视觉设计')
        self.assertNotIn('专业为', resume_to_text(legacy))
        self.assertNotIn('毕业年份', render_resume('t001-jianyue', legacy))
        from app.services.canonical_resume import current_canonical
        loaded = current_canonical({}, {'resume_data': legacy}, lambda _: {})
        self.assertEqual(loaded['education'][0]['major'], '视觉设计')
        self.assertEqual(legacy['education'][0]['major'], '专业为视觉设计')
        store = normalize_fact_store({'education': [{**values, 'facts': [new_fact('视觉设计')]}]})
        self.assertEqual(store['education'][0]['end_date'], '2023')

    async def test_course_omitted_or_fragment_only_without_followup(self):
        current = {'campus': [{'item_id': 'club', 'name': '观影协会', 'facts': [new_fact('制作社团海报')]}]}
        for output in ({}, {'items': [{'section': 'campus', 'item_id': 'club',
                                       'facts': [raw('产品拍摄和页面排版')]}]}):
            result = apply_fact_patch(current, await extract_facts_patch(COURSE, current, ExtractorStub(output)))
            self.assertEqual(len(result['campus'][0]['facts']), 1)
            self.assertEqual(len(result['projects']), 1)
            self.assertEqual(result['projects'][0]['name'], '店铺网页设计')

    async def test_skills_aliases_levels_groups_and_unsupported_rejected(self):
        result = await extract_facts_patch(TOOLS, {}, ExtractorStub({'skills': [
            {'name': '精通Photoshop', 'source_quote': TOOLS}, {'name': 'Figma', 'source_quote': TOOLS}]}))
        self.assertEqual(result['uncovered'], [])
        source = apply_fact_patch({}, result)
        written = await run_resume_writer(source, {}, EchoWriter())
        groups = written['resume_data']['skill_groups']
        self.assertEqual(set(groups), {'设计工具', 'AI 工具', '办公软件', '其他'})
        self.assertEqual(groups['办公软件'], ['Word', 'Excel', 'PPT'])
        self.assertIn('Photoshop', groups['设计工具'])
        self.assertIn('Illustrator', groups['设计工具'])
        self.assertIn('用过可画', groups['设计工具'])
        self.assertEqual(groups['AI 工具'], ['用过即梦', '用过WorkBuddy'])
        self.assertNotIn('精通', ' '.join(written['resume_data']['skills']))
        self.assertEqual(validate_skill_groups({'工具': ['精通Photoshop', 'Figma']}, [], source['skills']), ['精通Photoshop', 'Figma'])
        self.assertEqual(canonical_skill_text('我用过AI'), '我用过AI')
        self.assertEqual(canonical_skill_text('我做设计，会用AI'), '我做设计，会用Illustrator')
        denied = await extract_facts_patch('我没用过PS和AI，计划学习WorkBuddy', {}, ExtractorStub({}))
        self.assertEqual(denied['skills'], [])

    async def test_many_declared_tools_never_truncated_and_writer_cannot_upgrade(self):
        source = {'skills': [{'name': name, 'source_quote': name} for name in
                            ['会用Photoshop', '会用Illustrator', '会用Word', '会用Excel', '会用PPT',
                             '用过即梦', '用过WorkBuddy', '用过可画', '摄影', '排版', '素描', '速写', '调色']]}
        model = FakeModel([('OnePassOutput', {'match_plan': {}, 'writer': {'skill_groups': {
            '设计工具': ['精通Photoshop', 'Figma'], '办公软件': ['精通Excel']}}})])
        written = await run_resume_writer(source, {}, model)
        flat = written['resume_data']['skills']
        self.assertEqual(set(flat), {row['name'].removeprefix('会用') for row in source['skills']})
        self.assertGreater(len(written['resume_data']['skill_groups']['其他']), 3)

    async def test_pipeline_reports_facts_omitted_by_final_compression(self):
        from app.agents.tailor_pipeline import run_tailor_pipeline
        from app.services.resume_versions import text_hash
        source = work_source()
        data = {'work_experience': [{'item_id': 'work', 'company': '松澜仪器公司', 'bullets': WORK_FACTS[:]}]}
        records = [{'fact_ids': [fact['id']], 'text_hash': text_hash(fact['text'])}
                   for fact in source['work_experience'][0]['facts']]
        written = {'resume_data': data, 'resume_meta': {'bullets': {'work': records}}, 'match_plan': {},
                   'writer_diagnostic': {'status': 'model_completed'}, 'change_summary': []}
        async def writer(*args, **kwargs):
            return deepcopy(written)
        def measure(current, constraints):
            return {'status': 'synthetic', 'within_page_limit': len(current['work_experience'][0]['bullets']) <= 2}
        with patch('app.agents.tailor_pipeline.run_resume_writer', writer), \
                patch('app.agents.tailor_pipeline.measure_rendered_pages', measure), \
                patch('app.agents.tailor_pipeline.plan_compression', return_value=[
                    {'op': 'cap_bullets', 'target': '/work_experience/0/bullets', 'item_id': 'work', 'max_bullets': 1}]):
            result = await run_tailor_pipeline({'collected_info': source, 'resume_data': {}, 'resume_meta': {}}, data, object())
        self.assertTrue(any(row['status'] == 'omitted' for row in result['resume_meta']['fact_coverage']['facts']))
        self.assertIn('备用', graph._writer_reply(result))
        self.assertNotIn('办公室卫生管理', graph._writer_reply(result))
        self.assertIn('可在右侧『核对』查看', graph._writer_reply(result))


class FidelityDeterministicTests(unittest.TestCase):
    def test_shared_ids_and_overlapping_words_do_not_prove_duplicate(self):
        facts = [new_fact('采购办公用品；管理员工考勤')]
        rows = [{'text': '采购办公用品', 'fact_ids': [facts[0]['id']]},
                {'text': '管理员工考勤', 'fact_ids': [facts[0]['id']]}]
        self.assertEqual(_without_repeated_fact_rows(rows, facts), rows)
        similar = [{'text': text, 'fact_ids': []} for text in ('负责办公区日常用品采购', '负责办公区日常卫生管理')]
        self.assertEqual(_without_near_duplicate_rows(similar), similar)
        self.assertFalse(text_covered('管理员工考勤和办公用品', ['管理员工考勤']))
        duplicates = [{'text': '对接3家客户', 'fact_ids': ['a']},
                      {'text': '采购对接3家客户及散客', 'fact_ids': ['b']}]
        for ordered in (duplicates, duplicates[::-1]):
            kept = _without_near_duplicate_rows(ordered)
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0]['text'], '采购对接3家客户及散客')
            self.assertEqual(set(kept[0]['fact_ids']), {'a', 'b'})

    def test_full_time_internship_mixed_and_legacy_titles(self):
        def title(data):
            return next(row['title'] for row in get_resume_sections(data) if row['kind'] == 'work_experience')
        full = {'company': '松澜', 'bullets': ['毕业一年做了采购和行政的工作']}
        intern = {'company': '溪禾', 'employment_type': 'internship', 'bullets': ['整理材料']}
        for rows, expected in (([full], '工作经历'), ([intern], '实习经历'), ([full, intern], '工作经历')):
            for sections in (None, [{'id': 'w', 'kind': 'work_experience', 'title': '实习经历'}]):
                self.assertEqual(title({'work_experience': rows, 'sections': sections}), expected)
        data = graph._serialize_to_resume_data({'collected_info': {'internship': [intern]}})
        self.assertEqual(title(data), '实习经历')

    def test_final_audit_catches_compression_loss_and_hidden_sections(self):
        source = work_source()
        data = {'work_experience': [{'item_id': 'work', 'bullets': [WORK_FACTS[0]]}]}
        original = deepcopy(data)
        report = ensure_fact_coverage(data, {}, source)
        self.assertEqual(data, original)
        self.assertEqual(len(report['facts']), len(WORK_FACTS))
        self.assertTrue(all(row.get('reason') for row in report['facts'] if row['status'] == 'omitted'))
        data['sections'] = []
        self.assertEqual(ensure_fact_coverage(data, {}, source)['covered'], 0)
