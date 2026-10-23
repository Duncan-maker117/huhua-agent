"""Header-answer regressions; all candidate details and project work are fictional."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]
from langchain_core.messages import HumanMessage
from app.services.answer_facts import apply_answers, project_answer_fields
from app.services.resume_facts import new_fact, normalize_fact_store
from app.services.experience_fields import normalize_name, normalize_role, parse_dates, normalize_date_value


def answer_fixture(values=('叫做huhuaagent', '26.5-至今', '个人项目')):
    store = normalize_fact_store({'projects': [{'item_id': 'fictional-p', 'name': '项目（待补名称）',
        'facts': [new_fact('实现本地文本检索', quote='我做了本地文本检索')]}]})
    questions = [dict(id=key, prompt=prompt, kind='text') for key, prompt in (
        ('name', '这段经历叫什么名字？'), ('dates', '起止时间是什么（年/月，仍在进行可填至今）？'),
        ('role', '你在这段经历中是什么角色？'))]
    card = dict(turn_id='fictional-card', subject='fictional-p', questions=questions)
    message = HumanMessage(content='已提交问题卡', id='fictional-answer', additional_kwargs={
        'answer_card': card, 'answers': dict(turn_id=card['turn_id'],
            items=[dict(id=q['id'], value=v) for q, v in zip(questions, values)])})
    return store, message


class Quality18FReproduction(unittest.TestCase):
    def test_original_three_answers_are_fields_never_bullets(self):
        store, message = answer_fixture()
        result = apply_answers(store, message, project_fields=True)
        item = result['projects'][0]
        for field, expected in dict(name='huhuaagent', start_date='2026.05', end_date='至今', role='个人项目').items():
            self.assertEqual(item.get(field), expected)
        self.assertEqual([f['text'] for f in item['facts'] if not f.get('field')], ['实现本地文本检索'])
        draft = {'projects': [{'item_id': 'fictional-p', 'name': '项目（待补名称）', 'polished_bullets': ['实现本地文本检索']}]}
        project_answer_fields(draft, result)
        self.assertEqual(draft['projects'][0]['start_date'], '2026.05')
        self.assertEqual(result, apply_answers(result, message, project_fields=True))
        from app.services.resume_workspace import build_workspace
        card = build_workspace({'collected_info': result}, draft)['experiences']['items'][0]
        self.assertEqual((card['name'], card['period'], card['role']), ('huhuaagent', '2026.05 — 至今', '个人项目'))
        self.assertEqual(card['bullets'], ['实现本地文本检索'])

    def test_raw_quotes_survive_field_normalization(self):
        store, message = answer_fixture(('名字是“lumen agent”', '2026.5~now', '我是自己做的'))
        item = apply_answers(store, message, project_fields=True)['projects'][0]
        facts = {f['field']: f for f in item['facts'] if f.get('field')}
        for field, expected, quote in (
            ('name', 'lumen agent', '名字是“lumen agent”'), ('start_date', '2026.05', '2026.5~now'),
            ('end_date', '至今', '2026.5~now'), ('role', '个人项目', '我是自己做的')):
            self.assertEqual(facts[field]['text'], expected)
            self.assertEqual(facts[field]['source_quote'], quote)
            self.assertEqual(facts[field]['sources'][0]['source_quote'], quote)
            self.assertEqual(facts[field]['answer_value'], quote)

    def test_invalid_date_is_not_body_evidence(self):
        store, message = answer_fixture(('lumen', '26.13-至今', '个人项目'))
        item = apply_answers(store, message, project_fields=True)['projects'][0]
        self.assertNotIn('start_date', item)
        self.assertFalse(any(f['text'] == '26.13-至今' for f in item['facts']))
        self.assertEqual(item['field_confirmations'][0]['source_quote'], '26.13-至今')


class Quality18FFields(unittest.TestCase):
    def test_date_variants(self):
        for raw, expected in (
            ('26.5-至今', {'start_date': '2026.05', 'end_date': '至今'}),
            ('2026.5~now', {'start_date': '2026.05', 'end_date': '至今'}),
            ('26年5月到现在', {'start_date': '2026.05', 'end_date': '至今'}),
            ('2025/9-2026/1', {'start_date': '2025.09', 'end_date': '2026.01'}),
            ('去年9月', {'start_date': '2025.09'}),
            ('前年12月到今年1月', {'start_date': '2024.12', 'end_date': '2026.01'}),
            ('2025-09 — 2026-01', {'start_date': '2025.09', 'end_date': '2026.01'}),
            ('２０２５．９～２０２６．１', {'start_date': '2025.09', 'end_date': '2026.01'}),
            ('2025年3月到6月', {'start_date': '2025.03', 'end_date': '2025.06'}),
            ('2025.09 至今', {'start_date': '2025.09', 'end_date': '至今'}),
            ('2025-03', {'start_date': '2025.03'}),
            ('2026-08 / 至今', {'start_date': '2026.08', 'end_date': '至今'}),
            ('25年到26年', {'start_date': '2025', 'end_date': '2026'}),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(parse_dates(raw, today=date(2026, 10, 23)), expected)
        self.assertEqual(parse_dates('now', {'start_date': '2026.05'}), {'end_date': '至今'})
        self.assertEqual(normalize_date_value('预计2027年6月'), '2027.06（预计）')

    def test_invalid_dates_do_not_parse_partial_substrings(self):
        for raw in ('26.0-至今', '26.13-至今', '26-13', '2025/26', '2026.5-2025.9', '2025年12月到1月',
                    '2026.5-2026.123', '大概夏天吧', '2026.05做了2个接口', '至今', '26.5-至今，另一个项目2025.9-2026.1'):
            with self.subTest(raw=raw):
                self.assertEqual(parse_dates(raw, today=date(2026, 10, 23)), {})

    def test_names_only_remove_speech_preserve_spelling(self):
        for prefix in ('叫做', '叫', '名字是', '名字叫', '就是', '是', '它叫', '项目叫', '项目名字是'):
            with self.subTest(prefix=prefix):
                self.assertEqual(normalize_name(prefix + '“lUmEn-agent”！'), 'lUmEn-agent')
        self.assertEqual(normalize_name('Map++'), 'Map++')
        self.assertEqual(normalize_name('地图（课程）'), '地图（课程）')
        self.assertEqual(normalize_name('【名字是“lUmEn-agent”】'), 'lUmEn-agent')

    def test_roles_preserve_participation_and_limits(self):
        for raw in ('个人项目', '我是个人项目', '独立完成', '自己做的', '我做的是自己做的'):
            self.assertEqual(normalize_role(raw), '个人项目', raw)
        for raw, expected in (('我是后端参与者', '后端参与者'), ('担任测试成员', '测试成员'),
                              ('做的是需求分析', '需求分析'), ('不是负责人', '不是负责人')):
            self.assertEqual(normalize_role(raw), expected)

    def test_legacy_date_only_facts_become_headers_and_keep_quote(self):
        for raw in ('26.5-至今', '2026.5~now', '26年5月到现在', '2025/9-2026/1'):
            fact = new_fact(raw)
            store = normalize_fact_store({'projects': [{'name': 'Lumen', 'facts': [fact]}]})
            item = store['projects'][0]
            self.assertEqual({f['field'] for f in item['facts']}, {'start_date', 'end_date'})
            self.assertTrue(all(f['source_quote'] == raw for f in item['facts']))
            self.assertEqual(normalize_fact_store(store), store)

    def test_invalid_extracted_and_imported_fields_are_pending(self):
        for field in ('start_date', 'end_date'):
            fact = {**new_fact('26.13'), 'field': field}
            result = normalize_fact_store({'projects': [{'name': 'Lumen', field: '26.13', 'facts': [fact]}]})
            item = result['projects'][0]
            self.assertNotIn(field, item)
            self.assertEqual(item['facts'], [])
            self.assertEqual(item['field_confirmations'][0]['source_quote'], '26.13')
            self.assertEqual(normalize_fact_store(result), result)

    def test_alias_answer_merges_with_established_name_and_id(self):
        store, message = answer_fixture(('叫做lumenagent', '26.5-至今', '自己做的'))
        store['projects'].insert(0, {'item_id': 'established', 'name': 'Lumen Agent',
                                    'facts': [new_fact('测试检索接口')]})
        old_fact_ids = {f['id'] for item in store['projects'] for f in item['facts']}
        result = apply_answers(store, message)
        self.assertEqual(len(result['projects']), 1)
        item = result['projects'][0]
        self.assertEqual((item['item_id'], item['name']), ('established', 'Lumen Agent'))
        self.assertTrue(old_fact_ids <= {f['id'] for f in item['facts']})
        self.assertTrue(any(f['source_quote'] == '叫做lumenagent' for f in item['facts']))
        self.assertEqual(next(f for f in item['facts'] if f['source_quote'] == '叫做lumenagent')['status'], 'active')
        self.assertEqual(result, apply_answers(result, message))
        draft = {'projects': [{'item_id': 'fictional-p', 'name': '项目（待补名称）', 'polished_bullets': ['实现本地文本检索']}]}
        project_answer_fields(draft, result)
        self.assertEqual(draft['projects'][0]['name'], 'Lumen Agent')

    def test_patch_alias_merge_matches_preflight_and_preserves_quote(self):
        from app.agents.fact_extractor import apply_fact_patch
        from app.services.resume_preflight import preflight_resume
        for name in ('lumenagent', 'LUMEN-AGENT', '叫做“Lumen—Agent”'):
            store = normalize_fact_store({'projects': [{'item_id': 'p', 'name': 'Lumen Agent', 'facts': [new_fact('实现检索')]}]})
            fact = {**new_fact(name), 'field': 'name'}
            result = apply_fact_patch(store, {'items': [{'section': 'projects', 'item_id': 'new', 'name': name, 'facts': [fact]}]})
            self.assertEqual(len(result['projects']), 1, name)
            self.assertEqual(result['projects'][0]['name'], 'Lumen Agent')
            self.assertEqual(next(f for f in result['projects'][0]['facts'] if f['id'] == fact['id'])['source_quote'], name)
            data = {'projects': [{'item_id': 'p', 'name': 'Lumen Agent'}, {'item_id': 'new', 'name': name}]}
            self.assertEqual(len(preflight_resume(data)[0]['projects']), 1)

    def test_distinct_and_ambiguous_project_names_are_not_merged(self):
        from app.agents.fact_extractor import apply_fact_patch
        for names in (('Agent', '库存 Agent'), ('Project1', 'Project10'), ('光舟 Lumen Agent', '另一 Lumen Agent', 'lumenagent')):
            store = normalize_fact_store({'projects': [{'item_id': str(i), 'name': name, 'facts': [new_fact('实现检索')]}
                                                     for i, name in enumerate(names[:-1])]})
            result = apply_fact_patch(store, {'items': [{'section': 'projects', 'item_id': 'new', 'name': names[-1], 'facts': [new_fact('增加校验')]}]})
            self.assertEqual(len(result['projects']), len(names))

    def test_profile_import_uses_shared_fields_and_reuses_existing_name(self):
        from app.services.profile_service import context_to_collected_info
        current = normalize_fact_store({'projects': [{'item_id': 'p', 'name': 'Lumen Agent', 'facts': [new_fact('实现检索')]}]})
        raw = dict(name='叫做lumenagent', start_date='26.5', end_date='now', role='我是自己做的')
        context = {'facts': [dict(id=key, category='project', subject='lumenagent', field=key, value=value, revision=1)
                             for key, value in raw.items()]}
        bindings = []
        result = context_to_collected_info(context, current, projection_bindings=bindings)
        self.assertEqual(len(result['projects']), 1)
        item = result['projects'][0]
        self.assertEqual(item['name'], 'Lumen Agent')
        self.assertEqual((item['start_date'], item['end_date'], item['role']), ('2026.05', '至今', '个人项目'))
        for field, quote in raw.items():
            fact = next(f for f in item['facts'] if f.get('field') == field)
            self.assertEqual(fact['source_quote'], quote)
            self.assertEqual(fact['profile_refs'], [{'fact_id': field, 'revision': 1}])
        self.assertTrue(all(row['item_id'] == 'p' for row in bindings))
        self.assertEqual(context_to_collected_info(context, result), result)

    def test_profile_invalid_date_has_no_body_fallback(self):
        from app.services.profile_service import context_to_collected_info
        context = {'facts': [dict(id='bad-date', category='project', subject='光舟工具', field='start_date', value='26.13', revision=1)]}
        item = context_to_collected_info(context)['projects'][0]
        self.assertFalse(item.get('start_date'))
        self.assertFalse(item['facts'])
        self.assertEqual(item['field_confirmations'][0]['source_quote'], '26.13')

    def test_intake_form_fields_share_normalization_and_quotes(self):
        from app.services.intake import apply_submission
        result = apply_submission({}, {'kind': 'experiences', 'items': [dict(name='名字是lumenagent', type='项目',
            start='2026-05', end='至今', role='担任后端参与者', summary='实现本地文本检索')]}, HumanMessage(content='表单', id='form'))
        item = result['collected_info']['projects'][0]
        self.assertEqual((item['name'], item['start_date'], item['role']), ('lumenagent', '2026.05', '后端参与者'))
        self.assertEqual(next(f for f in item['facts'] if f.get('field') == 'start_date')['source_quote'], '2026-05')

    def test_19a_evidence_keeps_original_quote_for_normalized_fact(self):
        from app.services.resume_workspace import tailor_metadata
        from app.services.resume_versions import text_hash
        store, message = answer_fixture()
        result = apply_answers(store, message)
        fact = next(f for f in result['projects'][0]['facts'] if f.get('field') == 'name')
        data = {'projects': [{'item_id': 'fictional-p', 'name': 'huhuaagent', 'polished_bullets': ['实现本地文本检索']}]}
        values = {'collected_info': result, 'resume_meta': {'bullets': {'fictional-p': [
            {'text_hash': text_hash('实现本地文本检索'), 'fact_ids': [fact['id']]}]}}}
        evidence = tailor_metadata(values, data)['evidence']['facts'][fact['id']]
        self.assertEqual(evidence['text'], 'huhuaagent')
        self.assertEqual(evidence['source_quote'], '叫做huhuaagent')

    def test_oral_fillers_trigger_preflight_and_fallback_preserves_limits(self):
        from app.services.auto_polish_gate import needs_polish
        from app.services.resume_preflight import check_resume
        from app.services.candidate_language import resume_bullet
        for text in ('叫做检索项目', '这个实现了检索', '那个支持本地缓存', '就是参与后端开发', '然后团队实现检索'):
            self.assertIn('colloquial', needs_polish(text))
            issues = check_resume({'projects': [{'item_id': 'p', 'polished_bullets': [text]}]})['issues']
            self.assertTrue(any(issue['category'] == 'oral_phrase' for issue in issues))
        self.assertEqual(resume_bullet('然后参与检索开发，尚未上线'), '参与检索开发，尚未上线')
        self.assertEqual(resume_bullet('就是我们完成接口测试'), '团队完成接口测试')

    def test_valid_confirmation_resolves_pending_without_losing_raw_answer(self):
        store, message = answer_fixture(('lumen', '26.13-至今', '个人项目'))
        result = apply_answers(store, message)
        retry = deepcopy(message)
        retry.id = 'confirmed'
        retry.additional_kwargs['answer_card']['questions'] = [dict(id='confirm_dates', prompt='请确认起止时间？', kind='text')]
        retry.additional_kwargs['answers']['items'] = [dict(id='confirm_dates', value='26.5-至今')]
        result = apply_answers(result, retry)
        item = result['projects'][0]
        self.assertFalse(item.get('field_confirmations'))
        self.assertEqual((item['start_date'], item['end_date']), ('2026.05', '至今'))
        self.assertTrue(all(f['source_quote'] == '26.5-至今' for f in item['facts'] if f.get('field') in {'start_date', 'end_date'}))

    def test_whole_document_import_normalizes_and_reuses_canonical_name(self):
        from app.agents.resume_graph import _merge_imported_candidate
        old = {'projects': [{'item_id': 'existing', 'name': 'Lumen Agent', 'facts': [new_fact('实现检索')]}]}
        incoming = {'projects': [{'name': '项目叫lumen-agent', 'role': '我是个人项目',
                                 'start_date': '26.5', 'end_date': 'now', 'description': '完成本地检索测试'}]}
        result = _merge_imported_candidate(old, incoming)
        self.assertEqual(len(result['projects']), 1)
        item = result['projects'][0]
        self.assertEqual((item['item_id'], item['name']), ('existing', 'Lumen Agent'))
        self.assertEqual((item['start_date'], item['end_date']), ('2026.05', '至今'))
        self.assertTrue(any(f['source_quote'] == '项目叫lumen-agent' for f in item['facts']))

    def test_same_name_disjoint_dates_are_distinct_engagements(self):
        from app.agents.fact_extractor import apply_fact_patch
        old = normalize_fact_store({'projects': [{'item_id': 'p', 'name': 'Lumen Agent', 'start_date': '2023.01', 'end_date': '2023.06',
                                                  'facts': [new_fact('实现原型')]}]})
        facts = [dict(new_fact(value), field=field) for field, value in [('start_date', '2026.05'), ('end_date', '2026.09')]]
        result = apply_fact_patch(old, {'items': [{'section': 'projects', 'item_id': 'new', 'name': 'lumen-agent', 'facts': facts}]})
        self.assertEqual(len(result['projects']), 2)

    def test_range_mislabeled_as_start_date_is_split_not_body(self):
        fact = {**new_fact('26.5-至今'), 'field': 'start_date'}
        item = normalize_fact_store({'projects': [{'name': 'Lumen', 'facts': [fact]}]})['projects'][0]
        self.assertEqual((item['start_date'], item['end_date']), ('2026.05', '至今'))
        self.assertEqual({f['field'] for f in item['facts']}, {'start_date', 'end_date'})


class Quality18FIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_card_uses_unimported_profile_catalog_name_without_importing_body(self):
        from app.agents.orchestrator_tools import record_facts, ToolContext
        store, message = answer_fixture(('叫做lumenagent', '26.5-至今', '个人项目'))
        state = {'collected_info': store, 'messages': [message], 'profile_items': [
            dict(id='archive', name='Lumen Agent', category='project', start='2026.05', end='至今',
                 role='个人项目', summary='另一个尚未选择的档案事实', fact_ids=['not-selected'])]}
        result = await record_facts(state, {'source_id': 'current'}, ToolContext())
        item = result.update['collected_info']['projects'][0]
        self.assertEqual(item['name'], 'Lumen Agent')
        self.assertEqual(next(f for f in item['facts'] if f.get('field') == 'name')['source_quote'], '叫做lumenagent')
        self.assertNotIn('另一个尚未选择的档案事实', str(result.update['collected_info']))

    async def test_new_fillers_use_existing_writer_failure_fallback(self):
        from app.agents.resume_writer import _polish_rows
        from unittest.mock import AsyncMock
        quote = '然后我们参与这个检索模块开发，尚未上线'
        fact = {**new_fact(quote), 'item_id': 'p'}
        rows = [dict(id='b', item_id='p', text=quote, fact_ids=[fact['id']])]
        with patch('app.agents.resume_writer._call', AsyncMock(side_effect=RuntimeError('offline'))) as writer:
            result = await _polish_rows(rows, {fact['id']: fact}, None, None, 'other')
        writer.assert_awaited_once()
        self.assertEqual(result[0]['text'], '团队参与检索模块开发')
        self.assertEqual(fact['source_quote'], quote)  # 未上线 remains a writing constraint, never upgraded to 上线.
        self.assertEqual(result[0]['polish']['method'], 'deterministic')

    async def test_extractor_accepts_only_deterministically_supported_normalized_dates(self):
        from app.agents.fact_extractor import extract_facts_patch, apply_fact_patch
        from test_fact_extractor import FakeLLM
        quote = '26.5-至今'
        for value, accepted in [('2026.05', True), ('2025.05', False)]:
            candidate = {'items': [dict(section='projects', name='Lumen', facts=[
                dict(field='start_date', text=value, source_quote=quote, kind='context')])]}
            patch_data = await extract_facts_patch('Lumen项目，' + quote, {}, FakeLLM(candidate))
            facts = apply_fact_patch({}, patch_data).get('projects', [])
            self.assertEqual(any(f.get('field') == 'start_date' and f['text'] == value for item in facts for f in item['facts']), accepted)

    async def test_record_facts_card_path_does_not_call_extractor(self):
        from app.agents.orchestrator_tools import record_facts, ToolContext
        from unittest.mock import AsyncMock
        store, message = answer_fixture()
        with patch('app.agents.fact_extractor.extract_facts_patch', new_callable=AsyncMock) as extract:
            result = await record_facts({'collected_info': store, 'messages': [message]}, {'source_id': 'current'}, ToolContext())
        extract.assert_not_awaited()
        self.assertEqual(result.result['status'], 'ok')
        self.assertEqual(result.update['collected_info']['projects'][0]['start_date'], '2026.05')

    async def test_record_facts_extraction_uses_shared_normalization(self):
        from app.agents.orchestrator_tools import record_facts, ToolContext
        from test_fact_extractor import FakeLLM
        raw = [('name', '叫做lumenagent'), ('start_date', '26.5'), ('end_date', 'now'), ('role', '我是自己做的')]
        text = '项目名字是lumenagent。' + '；'.join(value for _, value in raw) + '；实现本地检索。'
        model = FakeLLM({'items': [{'section': 'projects', 'name': 'lumenagent', 'facts': [
            dict(field=field, text=value, source_quote=value, kind='context') for field, value in raw]}]})
        result = await record_facts({'messages': [HumanMessage(content=text, id='extract')]}, {'source_id': 'current'}, ToolContext(llm=model))
        item = result.update['collected_info']['projects'][0]
        self.assertEqual((item['name'], item['start_date'], item['end_date'], item['role']), ('lumenagent', '2026.05', '至今', '个人项目'))
        for field, quote in raw:
            self.assertEqual(next(f for f in item['facts'] if f.get('field') == field)['source_quote'], quote)

    async def test_failed_date_returns_partial_and_confirmation_request(self):
        from app.agents.orchestrator_tools import record_facts, ToolContext
        store, message = answer_fixture(('lumen', '记不清，大概夏天', '个人项目'))
        result = await record_facts({'collected_info': store, 'messages': [message]}, {'source_id': 'current'}, ToolContext())
        self.assertEqual(result.result['status'], 'partial')
        self.assertEqual(result.result['field_confirmations'][0]['source_quote'], '记不清，大概夏天')

    async def test_orchestrator_reasks_bad_date_once_and_keeps_valid_fields(self):
        from app.agents import orchestrator as loop, orchestrator_tools as tools
        from app.config import Settings
        from app.services.ask_user import pending_card
        from test_orchestrator import Model
        from test_orchestrator_p2i import answer_state, question
        from test_orchestrator_tools import measured
        state = answer_state([question('name', '这段经历叫什么名字？'), question('dates', '起止时间是什么？'), question('role', '你是什么角色？')],
                             ['叫做lumenagent', '26.13-至今', '个人项目'])
        with patch('app.config.get_settings', return_value=Settings(_env_file=None, AGENT_MODE='loop')), \
             patch('app.services.resume_capacity.measure_rendered_pages', side_effect=measured):
            result = await loop.run_orchestrator(state, Model([{'content': ''}]), registry=tools.TOOLS)
            self.assertEqual(result['resume_data']['projects'][0]['name'], 'lumenagent')
            self.assertNotIn('26.13-至今', str(result['resume_data']))
            next_state = {**state, **result, 'messages': state['messages'] + result['messages']}
            card = pending_card(next_state)
            self.assertEqual([q['id'] for q in card['questions']], ['confirm_dates'])
            retry = HumanMessage(content='已提交问题卡', id='retry', additional_kwargs={'answer_card': card,
                'answers': {'turn_id': card['turn_id'], 'items': [{'id': 'confirm_dates', 'value': '26.14-至今'}]}})
            next_state['messages'].append(retry)
            second = await loop.run_orchestrator(next_state, Model([{'content': ''}]), registry=tools.TOOLS)
            self.assertNotIn('26.14-至今', str({**next_state, **second}['resume_data']))
            self.assertFalse(any(q['id'] == 'confirm_dates' for q in pending_card({**next_state, **second}) .get('questions', [])))


import test_resume_provenance as provenance_fixture


class Quality18FProfileRevocation(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = provenance_fixture.ResumeProvenanceTests.asyncSetUp
    cleanup = provenance_fixture.ResumeProvenanceTests.cleanup
    login = provenance_fixture.ResumeProvenanceTests.login
    fixture = provenance_fixture.ResumeProvenanceTests.fixture
    fact = provenance_fixture.ResumeProvenanceTests.fact
    imported = provenance_fixture.ResumeProvenanceTests.imported
    linked = provenance_fixture.ResumeProvenanceTests.linked
    current = provenance_fixture.ResumeProvenanceTests.current

    async def test_normalized_import_date_remains_bound_for_revocation(self):
        sid, fact, view = await self.imported(field='start_date', value='26.5', subject='虚构光舟工具')
        self.assertEqual(self.linked(view['data'])['start_date'], '2026.05')
        response = await self.a.delete(f"/api/profile/facts/{fact['id']}?expected_revision={fact['revision']}")
        self.assertEqual(response.status_code, 200, response.text)
        data = (await self.current(sid))['data']
        self.assertNotIn('2026.05', str(data))
