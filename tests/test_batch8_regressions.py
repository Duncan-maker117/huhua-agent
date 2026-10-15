"""Batch eight: synthetic source fixtures and deliberately imperfect model stubs."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import test_persona_regressions as persona
from test_campus_and_naming import EchoWriter, ExtractorStub, raw
from app.agents import resume_graph as graph
from app.agents.fact_extractor import extract_facts_patch, apply_fact_patch
from app.agents.resume_writer import run_resume_writer, _without_near_duplicate_rows
from app.agents.tailor_pipeline import infer_edit_scope, run_tailor_pipeline
from app.schemas.editor import ResumeData
from app.config import get_settings
from app.services.resume_sections import employment_type
from app.services.skill_groups import normalize_skill_groups


class BatchEightRegressions(unittest.IsolatedAsyncioTestCase):
    setUp = persona.PersonaRegressions.setUp

    async def ops_followup(self):
        before = await persona.facts_for('ops')
        patch_data = {'items': [
            {'section': 'campus', 'name': '读书协会', 'facts': [raw('我排版过 8 篇公众号文章')]},
            {'section': 'work_experience', 'name': '小巷咖啡', 'facts': [raw('咖啡店叫小巷咖啡'), raw('我用手机拍过 6 条短视频素材')]}]}
        extracted = await extract_facts_patch(persona.FIXTURES['ops']['followup'], before, ExtractorStub(patch_data))
        return before, apply_fact_patch(before, extracted)

    async def test_ops_dates_recovered_before_projection_and_writer(self):
        before, facts = await self.ops_followup()
        expected = {'campus': ('2024.09', '2025.06'), 'work_experience': ('2025.07', '2025.08')}
        for section, dates in expected.items():
            self.assertEqual(len(facts[section]), 1)
            self.assertEqual(facts[section][0]['item_id'], before[section][0]['item_id'])
            fields = {f.get('field'): f['text'] for f in facts[section][0]['facts']}
            self.assertEqual((fields['start_date'], fields['end_date']), dates)
        projected = graph._serialize_to_resume_data({'collected_info': facts})
        written = await run_resume_writer(facts, {}, EchoWriter(), current_data=projected)
        for data in (projected, written['resume_data']):
            for section, dates in expected.items():
                self.assertEqual((data[section][0]['start_date'], data[section][0]['end_date']), dates)

    async def test_date_only_followup_updates_same_named_items_without_model_fields(self):
        _, facts = await self.ops_followup()
        for text, section, dates in [
            ('读书协会是 2024 年 10 月到 2025 年 5 月。', 'campus', ('2024.10', '2025.05')),
            ('小巷咖啡，2025 年 7 月到 8 月。', 'work_experience', ('2025.07', '2025.08')),
        ]:
            revised = apply_fact_patch(facts, await extract_facts_patch(text, facts, ExtractorStub({})))
            data = graph._serialize_to_resume_data({'collected_info': revised})
            self.assertEqual(len(data[section]), 1)
            self.assertEqual(data[section][0]['item_id'], facts[section][0]['item_id'])
            self.assertEqual((data[section][0]['start_date'], data[section][0]['end_date']), dates)

    async def test_formatted_model_dates_recover_from_literal_range_validation(self):
        facts = await persona.facts_for('ops')
        campus = facts['campus'][0]
        quote = '2024 年 9 月到 2025 年 6 月'
        patch_data = {'items': [{'section': 'campus', 'item_id': campus['item_id'], 'name': campus['name'],
            'facts': [{'kind': 'context', 'field': field, 'text': value, 'source_quote': quote}
                      for field, value in [('start_date', '2024.09'), ('end_date', '2025.06')]]}]}
        extracted = await extract_facts_patch('读书协会是 ' + quote, facts, ExtractorStub(patch_data))
        data = graph._serialize_to_resume_data({'collected_info': apply_fact_patch(facts, extracted)})
        self.assertEqual((data['campus'][0]['start_date'], data['campus'][0]['end_date']), ('2024.09', '2025.06'))

    async def test_ambiguous_or_unowned_dates_do_not_attach_to_an_experience(self):
        _, facts = await self.ops_followup()
        for text in ('2025 年 7 月到 8 月。', '读书协会和小巷咖啡是 2025 年 7 月到 8 月。',
                     '小巷咖啡，2025 年 12 月到 2 月。'):
            result = await extract_facts_patch(text, facts, ExtractorStub({}))
            self.assertFalse(any(f.get('field') in {'start_date', 'end_date'} for i in result['items'] for f in i['facts']), text)

    async def test_part_time_survives_placeholder_rename_writer_and_schema(self):
        before, facts = await self.ops_followup()
        for value in (before, facts):
            data = graph._serialize_to_resume_data({'collected_info': value})
            self.assertEqual(data['work_experience'][0]['employment_type'], 'part_time')
            written = await run_resume_writer(value, {}, EchoWriter(), current_data=data)
            validated = ResumeData.model_validate(written['resume_data']).model_dump()
            self.assertEqual(validated['work_experience'][0]['employment_type'], 'part_time')
        self.assertEqual(employment_type({}, 'work_experience'), 'full_time')
        self.assertEqual(employment_type({}, 'internship'), 'internship')
        self.assertEqual(employment_type({'title': '全职行政助理'}, 'work_experience'), 'full_time')

    async def test_named_polish_hard_boundary_in_pipeline_and_failure_path(self):
        for name in ('ops', 'career'):
            facts = (await self.ops_followup())[1] if name == 'ops' else await persona.facts_for(name)
            data = graph._serialize_to_resume_data({'collected_info': facts})
            data.update(skills=['Excel', 'Word', 'PPT'], summary=' 原文自述\n', skill_groups={})
            instruction = persona.FIXTURES[name]['polish']
            selected, targets = infer_edit_scope(data, instruction, facts)
            self.assertEqual((selected, targets), ('item', [data['work_experience'][0]['item_id']]))
            malicious = deepcopy(data)
            malicious.update(skills=[], skill_groups={'办公软件': ['Excel']}, summary='重写')
            malicious['basic_info']['name'] = '错误姓名'
            malicious['education'] = []
            for row in malicious['campus']:
                row['bullets'] = ['不应改动']
            malicious['work_experience'][0]['bullets'] = ['目标条目新措辞']
            for failed in (False, True):
                output = {'resume_data': deepcopy(malicious), 'resume_meta': {}, 'match_plan': {},
                          'writer_diagnostic': {'status': 'model_fallback' if failed else 'model_completed'}}
                state = {'resume_data': deepcopy(data), 'collected_info': facts}
                with patch('app.agents.tailor_pipeline.run_resume_writer', AsyncMock(return_value=output)):
                    result = await run_tailor_pipeline(state, deepcopy(data), object(), instruction=instruction, scope='whole')
                protected = deepcopy(result['resume_data'])
                protected['work_experience'][0] = deepcopy(data['work_experience'][0])
                self.assertEqual(json.dumps(protected, ensure_ascii=False), json.dumps(data, ensure_ascii=False))
                if not failed:
                    self.assertEqual(result['resume_data']['work_experience'][0]['bullets'], ['目标条目新措辞'])

    async def test_named_rewrite_with_additional_facts_cannot_widen_writeback(self):
        facts = await persona.facts_for('career')
        data = graph._serialize_to_resume_data({'collected_info': facts})
        bad = deepcopy(data)
        bad.update(education=[], skills=['新增错误技能'], skill_groups={'办公软件': ['Excel']})
        bad['work_experience'][0]['bullets'] = ['目标新措辞']
        with patch('app.agents.tailor_pipeline.run_resume_writer', AsyncMock(return_value={
            'resume_data': bad, 'resume_meta': {}, 'match_plan': {}})):
            result = await run_tailor_pipeline({'resume_data': data, 'collected_info': facts}, data, object(),
                instruction='润色行政经历，我还负责整理文件', scope='whole')
        final = deepcopy(result['resume_data'])
        self.assertEqual(final['work_experience'][0]['bullets'], ['目标新措辞'])
        final['work_experience'] = data['work_experience']
        self.assertEqual(final, data)

    async def test_legacy_career_polish_does_not_enter_whole_document_plan_confirmation(self):
        facts = await persona.facts_for('career')
        before = graph._serialize_to_resume_data({'collected_info': facts})
        before.update(skills=['Excel', 'Word', 'PPT'], summary='保留原自述')
        before.pop('skill_groups', None)
        state = {**graph._init_state(), 'stage': 'COLLECTING', 'plan_required': True,
                 'candidate_history_reconciled': True, 'collected_info': facts,
                 'resume_data': deepcopy(before), 'messages': [HumanMessage(content=persona.FIXTURES['career']['polish'])]}
        with patch.object(get_settings(), 'LLM_PLAN_CONFIRM', True):
            result = await graph.collecting_node(state, EchoWriter())
        self.assertFalse(result.get('plan_card'))
        self.assertFalse(result.get('pending_plan'))
        self.assertIn('resume_data', result)
        after = deepcopy(result['resume_data'])
        after['work_experience'] = before['work_experience']
        self.assertEqual(json.dumps(after, ensure_ascii=False), json.dumps(before, ensure_ascii=False))

    async def test_final_save_protects_scope_even_if_graph_route_rewrites_other_fields(self):
        facts = await persona.facts_for('career')
        before = graph._serialize_to_resume_data({'collected_info': facts})
        before.update(skills=['Excel', 'Word'], skill_groups={}, summary='原样')
        class BadGraph:
            values = {'resume_data': deepcopy(before), 'collected_info': facts}
            async def aget_state(self, config):
                from types import SimpleNamespace
                return SimpleNamespace(values=deepcopy(self.values))
            async def astream(self, *args, **kwargs):
                self.values['resume_data']['skills'] = []
                self.values['resume_data']['skill_groups'] = {'办公软件': ['Excel']}
                self.values['resume_data']['work_experience'][0]['bullets'] = ['新的目标措辞']
                yield 'updates', {'evaluating': {'messages': [AIMessage(content='已更新')]}}
            async def aupdate_state(self, config, values):
                self.values.update(values)
        with patch.object(graph, 'get_graph', return_value=BadGraph()), patch('app.services.session_store.save_resume_session', side_effect=lambda **kw: kw) as save:
            _ = [chunk async for chunk in graph.stream_agent([{'content': persona.FIXTURES['career']['polish']}], 'scope', object())]
        final = save.call_args.kwargs['resume_data']
        self.assertEqual(final['skills'], before['skills'])
        self.assertEqual(final['skill_groups'], {})
        self.assertEqual(final['summary'], '原样')
        self.assertEqual(final['work_experience'][0]['bullets'], ['新的目标措辞'])

    def test_numeric_action_duplicates_keep_fuller_bullet_and_merge_citations(self):
        full = '参与公众号排版，完成 8 篇推文排版，其中 3 篇初稿由本人撰写'
        short = '撰写推文初稿 3 篇，排版公众号文章 8 篇'
        for texts in ((full, short), (short, full)):
            result = _without_near_duplicate_rows([{'text': text, 'fact_ids': [str(i)]} for i, text in enumerate(texts)])
            self.assertEqual([row['text'] for row in result], [full])
            self.assertEqual(set(result[0]['fact_ids']), {'0', '1'})

    def test_numeric_dedup_does_not_drop_different_actions_counts_or_ownership(self):
        original = '撰写推文初稿 3 篇，排版公众号文章 8 篇'
        for other in ('撰写推文初稿 8 篇，排版公众号文章 3 篇', '拍摄短视频 3 条，制作海报 8 张',
                      '完成8篇推文排版，其中3篇初稿由部长撰写',
                      original + '，另整理选题表'):
            rows = _without_near_duplicate_rows([{'text': original}, {'text': other}])
            self.assertIn(other, [row['text'] for row in rows])
            if '另整理' not in other:
                self.assertEqual(len(rows), 2, other)

    async def test_tech_bare_model_skill_recovers_literal_level_and_rejects_denial(self):
        result = await extract_facts_patch(persona.FIXTURES['tech']['initial'], {}, ExtractorStub({'skills': ['Redis', 'Kubernetes']}))
        facts = apply_fact_patch({}, result)
        self.assertIn('Redis（了解）', [r['name'] for r in facts['skills']])
        self.assertNotIn('Kubernetes', str(facts['skills']))
        written = await run_resume_writer(facts, {}, EchoWriter())
        self.assertIn('Redis（了解）', written['resume_data']['skills'])
        self.assertNotIn('Kubernetes', str(written['resume_data'].get('skill_groups')))

    async def test_skill_levels_survive_grouping_and_followup_without_duplicates(self):
        for phrase, expected in [('了解 Redis', 'Redis（了解）'), ('熟悉 Redis', 'Redis（熟悉）'),
                                 ('会一点 Redis', 'Redis（基础）'), ('基础 Redis', 'Redis（基础）')]:
            patch_data = await extract_facts_patch(phrase + '，没用过 Kubernetes', {}, ExtractorStub({'skills': ['Redis', 'Kubernetes']}))
            facts = apply_fact_patch({'skills': ['Redis']}, patch_data)
            self.assertEqual([r['name'] for r in facts['skills']], [expected])
            groups = normalize_skill_groups({'开发': ['Redis']}, [r['name'] for r in facts['skills']])
            self.assertEqual([v for group in groups.values() for v in group], [expected])


if __name__ == '__main__':
    unittest.main()
