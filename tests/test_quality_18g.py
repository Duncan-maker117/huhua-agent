"""Fictional pre-release extraction replay; no real model or personal records."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]
from langchain_core.messages import HumanMessage
from app.services.resume_facts import normalize_fact_store
from app.services.experience_fields import merge_normalized_experiences
from app.services.fact_corrections import merge_new_experience_identities
from app.services.resume_preflight import preflight_resume, check_resume

MESSAGE = '''项目1：mtagent，多 Agent 协作的旅行行程规划应用，我是项目发起人，2025.09 开始。用 FastAPI + SSE + Pydantic 做流式后端，设计了 Profiler/Planner/Refiner 多 Agent 架构。
项目2：同路 mtagent，关系画像驱动的本地路线规划 Agent，个人项目，2026.01 开始。本人发现情侣、家庭、朋友出游需求差异很大，本人做了几个关键决定：设计四种关系画像，加入必去点和返程时间约束。现状：PR https://github.com/demo-org/demo-repo/pull/6 和 https://github.com/demo-org/demo-repo/pull/8 已合入上游。
另外我还做过一个给用户做简历的 Web 应用，用 FastAPI 写后端，收集过 4 类 bad case 并逐条修复。
教育：某某大学 计算机科学与技术 本科 2023.09—预计2027年6月。'''


def fixture():
    data = json.loads((ROOT / 'tests/fixtures/quality-18g-collected-info.json').read_text())
    for section, items in data.items():
        for item in items:
            for i, fact in enumerate(item['facts']):
                fact.update(id=f"{item['item_id']}-f{i}", source_quote=fact['text'],
                            source='chat', turn_id='fictional-message', status='active')
    return data


def replay():
    store = merge_normalized_experiences(normalize_fact_store(fixture()), {})
    merge_new_experience_identities(store, {}, MESSAGE, 'fictional-message')
    return store


class Quality18GRegression(unittest.TestCase):
    def test_only_typographic_name_variants_are_equal(self):
        from app.services.experience_fields import names_match
        for left, right, expected in [('LUMEN Agent', 'ｌｕｍｅｎ—agent', True), ('m-t agent', 'MT－Agent', True),
                                      ('mtagent', '同路 mtagent', False), ('工具｜旅行', '工具', False),
                                      ('C++ 工具', 'C# 工具', False), ('项目（待补名称）', '项目(待补名称)', False),
                                      ('待命名经历', '待命名经历', False), ('', '', False)]:
            self.assertEqual(names_match(left, right), expected, (left, right))

    def test_conflicting_dates_or_roles_never_auto_merge_even_when_periods_overlap(self):
        for section, label in [('projects', 'name'), ('work_experience', 'company'), ('internship', 'company')]:
            for field, left, right in [('start_date', '2025.09', '2026.01'), ('end_date', '2026.09', '至今'),
                                       ('role', '项目发起人', '个人项目'), ('title', '后端开发', '产品经理')]:
                rows = [dict(item_id='a', **{label: 'Lumen Agent', field: left}, facts=[]),
                        dict(item_id='b', **{label: 'lumen-agent', field: right}, facts=[])]
                store = normalize_fact_store({section: rows})
                self.assertEqual(len(store[section]), 2, (section, field))
                self.assertEqual(len(preflight_resume({section: rows})[0][section]), 2, (section, field))

    def test_shared_turn_source_or_fact_is_not_shared_experience(self):
        for shared in [dict(turn_id='one', source='chat'), dict(source={'turn_id': 'one', 'source_id': 'upload'}),
                       dict(profile_refs=[{'fact_id': 'same-fact'}])]:
            rows = [dict(item_id='a', name='mtagent', **shared), dict(item_id='b', name='同路 mtagent', **shared),
                    dict(item_id='c', name='项目（待补名称）', **shared)]
            self.assertEqual(len(normalize_fact_store({'projects': rows})['projects']), 3)
            self.assertEqual(len(preflight_resume({'projects': rows})[0]['projects']), 3)

    def test_archive_item_identity_merges_renames_and_retains_role_conflict(self):
        rows = [dict(item_id='a', name='虚构旧名', role='项目发起人', profile_refs=[{'item_id': 'archive'}],
                     polished_bullets=['设计检索接口和缓存失效处理并补充边界测试']),
                dict(item_id='b', name='虚构新名', role='开发者', profile_refs=[{'item_id': 'archive'}],
                     polished_bullets=['修复索引'])]
        output, meta, _ = preflight_resume({'projects': rows})
        self.assertEqual(len(output['projects']), 1)
        self.assertEqual(output['projects'][0]['role'], '项目发起人')
        self.assertTrue(any(row['category'] == 'role_conflict' for row in check_resume(output, meta=meta)['issues']))
        facts = normalize_fact_store({'projects': rows})
        self.assertEqual(len(facts['projects']), 1)
        self.assertEqual(facts['projects'][0]['role'], '项目发起人')
        self.assertTrue(any(row['category'] == 'role_conflict' for row in check_resume(output, facts)['issues']))

    def test_placeholder_needs_explicit_mention_even_during_cleanup(self):
        data = {'projects': [dict(item_id='a', name='Lumen', polished_bullets=['实现接口']),
                             dict(item_id='b', name='项目（待补名称）', polished_bullets=['修复缓存'])]}
        self.assertEqual(len(preflight_resume(data, merge_request='有内容重复，合并')[0]['projects']), 2)
        self.assertEqual(len(preflight_resume(data, merge_request='把 Lumen 和项目（待补名称）合并')[0]['projects']), 1)

    def test_education_check_reports_duplicates_but_other_degrees_stay_separate(self):
        rows = [dict(item_id='a', school='某某大学', degree='本科', major='计算机科学与技术'),
                dict(item_id='b', school='某某大学', degree='本科', major='计算机科学与技术'),
                dict(item_id='c', school='某某大学', degree='硕士', major='计算机科学与技术')]
        issues = check_resume({'education': rows})['issues']
        self.assertEqual(len(issues), 1)
        self.assertEqual((issues[0]['category'], issues[0]['section']), ('duplicate_experience', 'education'))
        self.assertEqual(len(normalize_fact_store({'education': rows})['education']), 2)

    def test_dates_from_each_experience_fact_stay_scoped_and_keep_quote(self):
        from app.services.resume_facts import new_fact
        for section, label in [('projects', 'name'), ('internship', 'company'), ('education', 'school')]:
            for raw, expected in [('2025.09 开始', {'start_date': '2025.09'}),
                                  ('2023.09—预计2027年6月', {'start_date': '2023.09', 'end_date': '2027.06（预计）'}),
                                  ('任职期间 2025.09—2026.01', {'start_date': '2025.09', 'end_date': '2026.01'})]:
                row = normalize_fact_store({section: [{label: '虚构名称', 'facts': [new_fact(raw)]}]})[section][0]
                for field, value in expected.items():
                    self.assertEqual(row[field], value)
                    fact = next(f for f in row['facts'] if f.get('field') == field)
                    self.assertEqual(fact['source_quote'], raw)
                if 'end_date' not in expected:
                    self.assertFalse(row.get('end_date'))

    def test_metrics_and_urls_do_not_supply_dates(self):
        from app.services.experience_fields import dates_in_text
        for text in ('耗时从 20-25ms 降至 10ms', '处理了 2023-2027 个请求', '结果 20-25',
                     'PR https://github.com/demo-org/2025-2026/pull/6 已合入'):
            self.assertEqual(dates_in_text(text), {}, text)

    def test_real_demo_stage_is_still_preserved(self):
        from app.services.resume_limits import _phase_label
        self.assertEqual(_phase_label('仅完成本地 Demo，尚未上线'), 'Demo')
        self.assertEqual(_phase_label('PR https://github.com/demo-org/demo-repo/pull/6 已合入'), '')

    def test_catalog_does_not_rename_contained_names(self):
        from app.services.experience_fields import canonicalize_catalog_names
        store = normalize_fact_store(fixture())
        before = deepcopy(store)
        canonicalize_catalog_names(store, [dict(id='archive', category='project', name='同路 mtagent')])
        self.assertEqual(store, before)

    def test_whole_resume_import_keeps_conflicting_or_placeholder_items(self):
        from app.agents.resume_graph import _merge_imported_candidate
        for first, second in [('mtagent', '同路 mtagent'), ('项目（待补名称）', '项目（待补名称）'), ('Lumen', 'Lumen')]:
            current = {'projects': [dict(item_id='a', name=first, start_date='2025.09', description='实现查询接口')]}
            incoming = {'projects': [dict(item_id='b', name=second, start_date='2026.01', description='实现缓存')]}
            result = _merge_imported_candidate(current, incoming)
            self.assertEqual(len(result['projects']), 2)
            self.assertNotIn('实现缓存', str(result['projects'][0]['facts']))

    def test_profile_import_matches_all_identity_fields_before_binding(self):
        from app.services.profile_service import context_to_collected_info
        for name, start, expected in [('同路 mtagent', '2025.09', 2), ('mtagent', '2026.01', 2), ('MT—Agent', '2025.09', 1)]:
            facts = [dict(id=key, category='project', subject=name, field=key, value=value, revision=1)
                     for key, value in [('name', name), ('description', '实现缓存'), ('start_date', start)]]
            current = normalize_fact_store({'projects': [dict(item_id='a', name='mtagent', start_date='2025.09', description='实现接口')]})
            result = context_to_collected_info({'facts': facts}, current)
            self.assertEqual(len(result['projects']), expected, (name, start))
            if expected == 2:
                self.assertNotIn('实现缓存', str(result['projects'][0]['facts']))

    def test_reimport_same_profile_item_retains_main_role_and_reports_other_role(self):
        from app.services.profile_service import context_to_collected_info
        current = normalize_fact_store({'projects': [dict(item_id='a', profile_item_id='archive', name='虚构旧名', role='项目发起人')]})
        incoming = {'facts': [dict(id='role-fact', category='project', profile_item_id='archive', subject='虚构新名',
                                  field='role', value='开发者', revision=1)]}
        result = context_to_collected_info(incoming, current)
        self.assertEqual(len(result['projects']), 1)
        self.assertEqual(result['projects'][0]['role'], '项目发起人')
        self.assertTrue(any(row['category'] == 'role_conflict' for row in check_resume(result, result)['issues']))

    def test_old_extraction_keeps_three_projects_and_recovers_dates(self):
        store = replay()
        self.assertEqual([p['name'] for p in store['projects']], ['mtagent', '同路 mtagent', '项目（待补名称）'])
        self.assertEqual([p.get('start_date', '') for p in store['projects']], ['2025.09', '2026.01', ''])
        self.assertNotIn('bad case', str(store['projects'][:2]))
        self.assertIn('4 类 bad case', str(store['projects'][2]))
        self.assertEqual(len(store['education']), 1)
        edu = store['education'][0]
        self.assertEqual((edu['start_date'], edu['end_date']), ('2023.09', '2027.06（预计）'))
        self.assertEqual(edu['major'], '计算机科学与技术')
        self.assertEqual(normalize_fact_store(store), store)

    def test_pr_url_is_not_project_stage(self):
        from app.services.resume_limits import preserve_item_limits
        store = normalize_fact_store(fixture())
        source = store['projects'][1]
        data = {'projects': [{'item_id': source['item_id'], 'name': source['name'], 'role': '个人项目',
                              'polished_bullets': ['设计四种关系画像']}]}
        output, _, _ = preserve_item_limits(data, {}, store, item_ids=[source['item_id']])
        self.assertEqual(output['projects'][0]['role'], '个人项目')

    def test_similar_names_are_advisory_only(self):
        data = {'projects': [dict(item_id='a', name='mtagent', start_date='2025.09'),
                             dict(item_id='b', name='同路 mtagent', start_date='2026.01')]}
        self.assertEqual(len(preflight_resume(data)[0]['projects']), 2)
        issues = check_resume(data)['issues']
        duplicate = next(row for row in issues if row['category'] == 'duplicate_experience')
        self.assertIn('如果是同一个项目，可以让我合并', duplicate['suggestion'])

    def test_close_spelling_and_overlapping_periods_only_raise_advice(self):
        data = {'projects': [dict(item_id='a', name='LumenAgent', start_date='2025.09', end_date='2026.07'),
                             dict(item_id='b', name='LumenAgnet', start_date='2026.01', end_date='2026.09')]}
        self.assertEqual(len(preflight_resume(data)[0]['projects']), 2)
        self.assertTrue(any(row['category'] == 'duplicate_experience' for row in check_resume(data)['issues']))

    def test_three_exact_education_duplicates_coalesce_with_all_original_ids(self):
        base = dict(school='某某大学', major='计算机科学与技术', degree='本科')
        result = normalize_fact_store({'education': [dict(base, item_id=i) for i in ('a', 'b', 'c')]})
        self.assertEqual(len(result['education']), 1)
        row = result['education'][0]
        self.assertEqual({row['item_id'], *[old['item_id'] for old in row['merged_from']]}, {'a', 'b', 'c'})


class Quality18GIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_actual_extractor_routing_keeps_three_old_model_items(self):
        from app.agents.fact_extractor import extract_facts_patch, apply_fact_patch
        from test_fact_extractor import FakeLLM
        old = fixture()
        candidate = {'items': [{'section': section, 'name': row.get('name') or row.get('school'),
                               'facts': [dict(f, source_quote=f['source_quote'].replace('使用 FastAPI', '用 FastAPI')) for f in row['facts']]}
                              for section, rows in old.items() for row in rows]}
        extracted = await extract_facts_patch(MESSAGE, {}, FakeLLM(candidate), turn_id='fictional-message')
        store = apply_fact_patch({}, extracted)
        self.assertEqual([p['name'] for p in store['projects']], ['mtagent', '同路 mtagent', '项目（待补名称）'])
        self.assertNotIn('bad case', str(store['projects'][:2]))
        self.assertIn('bad case', str(store['projects'][2]))

    async def test_full_writer_pipeline_keeps_ownership_and_no_false_demo(self):
        from app.agents.orchestrator_tools import write_draft, ToolContext
        from test_orchestrator_tools import Writer, measured
        store = replay()
        state = dict(collected_info=store, messages=[HumanMessage(content='直接写稿')],
                     confirmed_plan={'bullet_style': 'plain', 'experience_plan': [dict(item_id=p['item_id'],
                         treatment='lead', target_bullets=4) for p in store['projects']]})
        with patch('app.agents.tailor_pipeline.measure_rendered_pages', side_effect=measured), \
                patch('app.services.resume_capacity.measure_rendered_pages', side_effect=measured):
            result = await write_draft(state, {}, ToolContext(llm=Writer(invented=True)))
        projects = result.update['resume_data']['projects']
        self.assertEqual([p['name'] for p in projects], ['mtagent', '同路 mtagent', '项目（待补名称）'])
        self.assertNotIn('bad case', str(projects[:2]))
        self.assertIn('4 类 bad case', str(projects[2]))
        self.assertTrue(all(' · ' not in p.get('role', '') for p in projects))
        self.assertTrue(any(row['category'] == 'duplicate_experience' for row in result.update['resume_meta']['precheck']['issues']))

    async def test_record_facts_replays_old_extraction_without_identity_loss(self):
        from app.agents.orchestrator_tools import record_facts, ToolContext
        old = fixture()
        payload = {'items': [{**row, 'section': section, 'name': row.get('name') or row.get('school'),
                              'facts': [*row['facts'], *[dict(id=f'{row["item_id"]}-{key}', text=row[key],
                                  source_quote=row[key], kind='context', field=key)
                                  for key in ('degree', 'major') if row.get(key)]]}
                             for section, rows in old.items() for row in rows]}
        with patch('app.agents.fact_extractor.extract_facts_patch', AsyncMock(return_value=payload)):
            result = await record_facts({'messages': [HumanMessage(content=MESSAGE, id='fictional-message')]},
                                        {'source_id': 'current'}, ToolContext(llm=object()))
        store = result.update['collected_info']
        self.assertEqual(len(store['projects']), 3)
        self.assertNotIn('bad case', str(store['projects'][:2]))
        self.assertEqual(len(store['education']), 1)
        self.assertEqual(store['education'][0]['end_date'], '2027.06（预计）')

    async def test_write_inventory_matches_final_document_and_omissions(self):
        from app.agents import orchestrator_tools as tools, orchestrator as loop
        from app.agents.orchestrator_context import project_tool_result
        from app.services.model_privacy import ContactRedactor
        store = replay()
        data = {'projects': [dict(item_id='trip-original', name='mtagent', role='项目发起人', polished_bullets=['实现流式后端'])]}
        meta = {'merged_items': {'trip-original': ['trip-original', 'trip-relationship']}}
        fake = tools.ToolOutcome({'status': 'ok'}, {'resume_data': data, 'resume_meta': meta})
        state = {'collected_info': store, 'confirmed_plan': {'experience_plan': [
            dict(item_id='resume-unnamed', treatment='backup', target_bullets=0)]}}
        with patch.object(tools, '_write', AsyncMock(return_value=fake)), patch.object(tools, '_draft_followup', return_value=None):
            result = await tools.write_draft(state, {}, tools.ToolContext())
        inventory = result.result['experience_inventory']
        self.assertEqual([p['name'] for p in inventory['included']], ['mtagent'])
        reasons = {p['name']: p['reason'] for p in inventory['not_included']}
        self.assertEqual(reasons['同路 mtagent'], 'merged')
        self.assertEqual(reasons['项目（待补名称）'], 'backup')
        self.assertEqual(project_tool_result('write_draft', result.result, ContactRedactor())['experience_inventory'], inventory)
        self.assertIn('experience_inventory', loop.SYSTEM_PROMPT)

    async def test_explicit_user_merge_still_works(self):
        from app.agents.orchestrator_tools import edit_resume, ToolContext
        from app.agents.resume_graph import _serialize_to_resume_data
        store = normalize_fact_store(fixture())
        data = _serialize_to_resume_data({'collected_info': store, 'messages': []})
        state = dict(collected_info=store, resume_data=data, resume_meta={}, messages=[
            HumanMessage(content='mtagent 和同路 mtagent 是同一个项目，合并')])
        with patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={'pages': 1}):
            result = await edit_resume(state, {'instruction': state['messages'][0].content}, ToolContext())
        self.assertEqual(len(result.update['resume_data']['projects']), 2)
        self.assertEqual(result.update.get('collected_info', state['collected_info']), store)
        self.assertTrue(any(p['name'] == '项目（待补名称）' for p in result.update['resume_data']['projects']))
