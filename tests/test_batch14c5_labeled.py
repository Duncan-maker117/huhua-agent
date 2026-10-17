"""Frozen c4 facts/inputs, deliberately wrong models; no provider or server."""
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]
from app.agents import resume_graph as graph  # noqa: E402
from app.agents.fact_extractor import extract_facts_patch, apply_fact_patch  # noqa: E402
from app.agents.resume_writer import run_resume_writer  # noqa: E402
from app.agents.tailor_pipeline import constraints_for_turn  # noqa: E402
from app.schemas.writer import FactSlots  # noqa: E402
from app.services.labeled_writer import rule_slot, classify_items, finish_rows  # noqa: E402
from app.services.resume_versions import text_hash  # noqa: E402
from app.services.structure_plan import select_plan, edit_plan  # noqa: E402
from test_campus_and_naming import ExtractorStub, raw  # noqa: E402
from test_fact_guard import decision  # noqa: E402

FIXTURE = json.loads((ROOT / 'tests/fixtures/batch14c5-replay.json').read_text())['personas']


def collected(who):
    fixture = FIXTURE[who]
    project = {k: fixture['project'][k] for k in ('item_id', 'name', 'role', 'start_date', 'end_date')}
    fields = {v: k for k, v in project.items() if k != 'item_id'}
    facts = []
    for row in fixture['facts']:
        if row['item_id'] != project['item_id']:
            continue
        text = row['text']
        fact = {'id': row['fact_id'], 'item_id': project['item_id'], 'text': text, 'source_quote': text,
                'status': 'active', 'source': 'chat', 'kind': 'action'}
        if text in fields:
            fact['field'] = fields[text]
        elif '问题' in text:
            fact['kind'] = 'context'
        elif '上线' in text or '优化' in text:
            fact['kind'] = 'status_limit'
        facts.append(fact)
    project['facts'] = facts
    return {'projects': [project]}


class WrongModel:
    def __init__(self, invalid_classification=False, repair=False, hallucinate=False):
        self.calls = []
        self.invalid_classification, self.repair, self.hallucinate = invalid_classification, repair, hallucinate

    def with_structured_output(self, schema):
        async def invoke(messages):
            data = json.loads(messages[-1].content)
            self.calls.append((schema.__name__, data))
            if schema.__name__ == 'SemanticBatch':
                return {'decisions': [decision(r['id']) for r in data]}
            if schema.__name__ == 'FactSlots':
                return {'assignments': [{'fact_id': 'unknown' if self.invalid_classification else f['id'],
                                        'slot': '决策'} for f in data['facts']]}
            if schema.__name__ == 'StructurePlan':
                return {'recommended': {'bullet_style': 'plain', 'experience_plan': [
                    {'item_id': p['item_id'], 'treatment': 'lead', 'target_bullets': 3} for p in data['evidence']['projects']]}}
            if schema.__name__ == 'RepairOutput':
                if self.repair and 'labeled_slots' in data:
                    from app.services.labeled_writer import fallback_row
                    return {'bullets': [{'id': row['id'], 'fact_ids': row['fact_ids'],
                        'text': fallback_row(row['slot'], row['fact_ids'], '',
                            {f['id']: f for f in row['facts']}, '')['text']} for row in data['labeled_slots']]}
                return {'bullets': []}
            if schema.__name__ in {'WriterDraft', 'OnePassOutput'}:
                items = []
                for project in data['evidence']['projects']:
                    facts = project['facts']
                    refs = [f['id'] for f in facts if not f.get('field')]
                    items.append({'item_id': project['item_id'], 'section': 'projects', 'bullets': [
                        {'text': '决策：接入 MCP；提示词原型由本人完成；已上线可用，仍在优化。', 'fact_ids': refs},
                        {'text': '生成的简历和使用过程中的效果可能还差点意思，仍在优化', 'fact_ids': refs},
                        {'text': '现状：个人开发项目' + ('，1000 人使用' if self.hallucinate else ''), 'fact_ids': refs}]})
                draft = {'items': items}
                return draft if schema.__name__ == 'WriterDraft' else {'writer': draft, 'match_plan': {
                    'bullet_style': 'plain', 'experience_plan': [{'item_id': p['item_id'], 'treatment': 'lead', 'target_bullets': 3}
                                                              for p in data['evidence']['projects']]}}
            raise AssertionError(schema.__name__)
        return SimpleNamespace(ainvoke=invoke)


class Batch14c5Tests(unittest.IsolatedAsyncioTestCase):
    async def real_with_pains(self):
        source = collected('aipm_real')
        message = FIXTURE['aipm_real']['inputs'][3]
        # c4 emitted the other facts but omitted every pain. Reproduce that
        # imperfect extractor, then use the production literal recovery.
        patch = await extract_facts_patch(message, source, ExtractorStub({'items': []}), turn_id='c5-pains')
        return apply_fact_patch(source, patch)

    def test_real_replay_has_no_pains_and_synthetic_profile_was_overwritten(self):
        self.assertEqual(FIXTURE['aipm']['role_profile']['role_family'], 'other')
        self.assertEqual(FIXTURE['aipm']['plan']['bullet_style'], 'plain')
        self.assertFalse(any(rule_slot(f) == '问题' for f in collected('aipm_real')['projects'][0]['facts']))

    def test_free_answer_keeps_ai_direction_and_actual_change_still_works(self):
        state = graph._direction_profile_update({}, FIXTURE['aipm']['inputs'][0])
        self.assertEqual(state['jd_info']['role_profile']['role_family'], 'ai_pm')
        self.assertEqual(graph._direction_profile_update(state, FIXTURE['aipm']['inputs'][2]), {})
        changed = graph._direction_profile_update(state, '我改投后端开发实习')
        self.assertEqual(changed['jd_info']['role_profile']['role_family'], 'backend')

    async def test_missing_four_pains_are_literal_context_not_instructions(self):
        source = await self.real_with_pains()
        pains = [f for f in source['projects'][0]['facts'] if f.get('turn_id') == 'c5-pains' and f['kind'] == 'context']
        self.assertEqual(len(pains), 4, pains)
        message = FIXTURE['aipm_real']['inputs'][3]
        self.assertTrue(all(f['source_quote'] in message for f in pains))
        self.assertNotIn('writing_rules', constraints_for_turn({}, message))
        self.assertTrue(constraints_for_turn({}, '不要生成不存在的经历').get('writing_rules'))

    async def test_unknown_answer_instruction_external_and_ambiguous_owner_are_not_pains(self):
        source = collected('aipm_real')
        for message in ('我不知道怎么写简历', '请帮我解决简历无法编辑的问题',
                        '参考简历：\n用户逐项填空繁琐'):
            result = await extract_facts_patch(message, source, ExtractorStub({'items': []}))
            self.assertFalse(result['items'], message)
        source['projects'].append({**deepcopy(source['projects'][0]), 'item_id': 'peer', 'name': '另一项目'})
        result = await extract_facts_patch('用户逐项填空繁琐', source, ExtractorStub({'items': []}))
        self.assertFalse(result['items'])

    async def test_new_unnamed_project_owns_pains_and_kind_is_corrected(self):
        message = FIXTURE['aipm_real']['inputs'][3]
        result = await extract_facts_patch(message, {}, ExtractorStub({'items': [{'section': 'projects', 'name': '',
            'facts': [raw('这是我的个人开发项目'), raw('ai工具总是不知道简历的结构应该怎么样才好', kind='action')]}]}))
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(len([f for f in result['items'][0]['facts'] if rule_slot(f) == '问题']), 4)

    async def test_plan_write_and_one_pass_lock_style_with_wrong_models(self):
        for who in FIXTURE:
            source = await self.real_with_pains() if who == 'aipm_real' else collected(who)
            before = deepcopy(source)
            model = WrongModel(invalid_classification=True, hallucinate=True)
            planned = await run_resume_writer(source, {'role_family': 'ai_pm'}, model, phase='plan',
                                             previous_plan={'bullet_style': 'plain'})
            plan = select_plan(planned['structure_plan'])
            self.assertEqual(plan['bullet_style'], 'labeled')
            for kwargs in ({'phase': 'write', 'previous_plan': plan}, {}):
                result = await run_resume_writer(source, {'role_family': 'ai_pm'}, model, **kwargs)
                self.assertEqual(result['match_plan']['bullet_style'], 'labeled')
                if kwargs:
                    self.assertEqual(result['confirmed_plan']['bullet_style'], 'labeled')
                project = result['resume_data']['projects'][0]
                body = project['polished_bullets']
                self.assertTrue(body)
                self.assertLessEqual(len(body), 4)
                self.assertTrue(all(re.match(r'^(问题|决策|迭代|技术|现状)：', line) for line in body), body)
                self.assertTrue(any(line.startswith('问题：') for line in body), body)
                self.assertNotIn('1000', str(body))
                self.assertNotIn('差点意思', str(body))
                self.assertNotIn('个人开发项目', str(body))
                decisions = ' '.join(line for line in body if line.startswith('决策：'))
                self.assertTrue(decisions, body)
                self.assertFalse(re.search('本人|上线|优化|原型|独立', decisions), decisions)
                if who == 'aipm_real':
                    pain = next(line for line in body if line.startswith('问题：'))
                    for word in ('填空', '复制粘贴', '无法编辑', '结构'):
                        self.assertIn(word, pain)
                    self.assertLessEqual(str(body).count('已上线'), 1, body)
                for line, record in zip(body, result['resume_meta']['bullets'][project['item_id']]):
                    self.assertEqual(record['text_hash'], text_hash(line))
                    slots = result['resume_meta']['labeled_slots'][project['item_id']]
                    self.assertEqual({slots[fid] for fid in record['fact_ids']}, {line.split('：')[0]})
                    trace = result['writer_diagnostic']['slot_lines'][project['item_id'] + ':' + record['slot']]
                    if trace['final_handling'] != 'deterministic_fallback':
                        self.assertLessEqual(len(re.split('[；;。]', line.rstrip('。；;'))), 3)
                Path('/private/tmp/huhua-b14c5/' + who + '-stub.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
            self.assertEqual(source, before)
            names = [name for name, _ in model.calls]
            self.assertIn('FactSlots', names)
            self.assertIn('RepairOutput', names)

    async def test_user_plain_choice_survives_plan_revalidation_and_writer(self):
        source = collected('aipm')
        model = WrongModel()
        planned = await run_resume_writer(source, {'role_family': 'ai_pm'}, model, phase='plan')
        plan, _ = edit_plan(select_plan(planned['structure_plan']), '写法：普通', source)
        result = await run_resume_writer(source, {'role_family': 'ai_pm'}, model, phase='write', previous_plan=plan)
        self.assertEqual(result['confirmed_plan']['bullet_style'], 'plain')
        self.assertEqual(result['confirmed_plan']['bullet_style_source'], 'user')
        self.assertEqual(result['match_plan']['bullet_style_source'], 'user')
        resumed = await run_resume_writer(source, {'role_family': 'ai_pm'}, model,
            resume_meta={'match_plan': result['match_plan']})
        self.assertEqual(resumed['match_plan']['bullet_style'], 'plain')
        self.assertEqual(resumed['match_plan']['bullet_style_source'], 'user')
        self.assertNotIn('FactSlots', [name for name, _ in model.calls])

    async def test_slot_schema_membership_duplicates_and_enum_fail_closed(self):
        facts = [{'id': 'f', 'text': '用户逐项填空繁琐', 'kind': 'context'}]
        for output in ({'assignments': [{'fact_id': 'wrong', 'slot': '问题'}]},
                       {'assignments': [{'fact_id': 'f', 'slot': '问题'}] * 2},
                       {'assignments': [{'fact_id': 'f', 'slot': '成果'}]}):
            async def call(*args, **kwargs):
                return FactSlots.model_validate(output)
            diagnostic = {}
            result = await classify_items({'p': ('projects', {'facts': facts})}, {'p'}, call, None, 'ai_pm', diagnostic)
            self.assertEqual(result, {'p': {'f': '问题'}})
            self.assertEqual(diagnostic['slot_classification_fallbacks'], ['p'])

    async def test_plain_output_is_relabelled_and_mixed_output_retried(self):
        facts = {'f': {'id': 'f', 'item_id': 'p', 'text': '接入 MCP 供用户使用自己的 AI',
                       'source_quote': '接入 MCP 供用户使用自己的 AI', 'kind': 'action'}}
        from app.agents.resume_writer import _call
        model = WrongModel(repair=True)
        for text in ('接入 MCP 供用户使用自己的 AI', '决策：本人完成原型；已上线'):
            diagnostic = {}
            result = await finish_rows([{'text': text, 'fact_ids': ['f']}], {'f': '决策'}, 1, 'p', facts,
                                       '', _call, model, model, 'ai_pm', diagnostic)
            self.assertEqual(result[0]['text'], '决策：接入 MCP 供用户使用自己的 AI')
            if '本人' in text:
                self.assertEqual(diagnostic['slot_repairs'], ['p'])
            else:
                self.assertNotIn('slot_repairs', diagnostic)

    async def test_semantic_failure_never_publishes_unguarded_rewrite(self):
        from app.agents.resume_writer import _call
        facts = {'f': {'id': 'f', 'item_id': 'p', 'text': '仍在优化生成效果',
                       'source_quote': '生成效果还差点意思，仍在优化', 'kind': 'status_limit'}}
        class Reject(WrongModel):
            def with_structured_output(self, schema):
                if schema.__name__ == 'SemanticBatch':
                    async def invoke(messages):
                        return {'decisions': []}
                    return SimpleNamespace(ainvoke=invoke)
                return super().with_structured_output(schema)
        model = Reject()
        rows = await finish_rows([{'text': '生成效果显著提高', 'fact_ids': ['f']}], {'f': '现状'},
                                 1, 'p', facts, '', _call, model, model, 'ai_pm', {})
        # c6: semantic failure rejects the rewrite, but normalized source facts
        # are delivered independently of the unavailable semantic provider.
        self.assertEqual([row['text'] for row in rows], ['现状：仍在优化生成效果'])
        self.assertEqual(rows[0]['fact_ids'], ['f'])

    async def test_wrong_refs_and_new_numbers_cannot_bypass_slot_guard(self):
        from app.agents.resume_writer import _call
        facts = {'f': {'id': 'f', 'item_id': 'p', 'text': '已上线', 'source_quote': '已上线', 'kind': 'status_limit'},
                 'peer': {'id': 'peer', 'item_id': 'other', 'text': '1000 人使用',
                          'source_quote': '1000 人使用', 'kind': 'result_metric'}}
        model = WrongModel()
        for refs in (['f'], ['f', 'peer'], ['unknown']):
            rows = await finish_rows([{'text': '已上线，1000 人使用', 'fact_ids': refs}], {'f': '现状'},
                                     1, 'p', facts, '', _call, model, model, 'ai_pm', {})
            self.assertEqual([row['text'] for row in rows], ['现状：已上线'])
            self.assertEqual(rows[0]['fact_ids'], ['f'])

    async def test_heading_fact_and_question_do_not_become_body_rows(self):
        from app.agents.resume_writer import _call
        facts = {'f': {'id': 'f', 'item_id': 'p', 'text': '对话式简历工作台',
                       'source_quote': '对话式简历工作台', 'kind': 'context'}}
        model = WrongModel()
        rows = await finish_rows([{'text': '对话式简历工作台', 'fact_ids': ['f']}], {'f': '技术'},
                                 4, 'p', facts, '', _call, model, model, 'ai_pm', {},
                                 heading_texts=['对话式简历工作台'])
        self.assertEqual(rows, [])
        self.assertEqual(rule_slot({'text': '对话挖经历这块做过哪些设计取舍', 'kind': 'action'}), '不用')

    async def test_explicit_three_row_cap_and_empty_slot_remain_binding(self):
        source = await self.real_with_pains()
        item_id = source['projects'][0]['item_id']
        for cap in (0, 3):
            result = await run_resume_writer(source, {'role_family': 'ai_pm'}, WrongModel(), phase='write',
                previous_plan={'bullet_style': 'labeled', 'experience_plan': [
                    {'item_id': item_id, 'treatment': 'lead', 'target_bullets': cap}]})
            body = result['resume_data']['projects'][0]['polished_bullets']
            self.assertLessEqual(len(body), cap)
            if cap:
                self.assertEqual([line.split('：')[0] for line in body], ['问题', '决策', '现状'])

    def test_presentation_path_has_no_unlabeled_or_title_only_rows(self):
        from app.services.writing_style import format_rows
        facts = {'nature': {'text': '个人开发项目', 'kind': 'role'},
                 'status': {'text': '简历生成效果仍在优化', 'kind': 'status_limit'}}
        rows = [{'text': '个人开发项目', 'fact_ids': ['nature']},
                {'text': '简历生成效果仍在优化', 'fact_ids': ['status']},
                {'text': '无来源的描述', 'fact_ids': []}]
        result = format_rows(rows, facts, 'labeled', role_family='ai_pm')
        self.assertEqual([row['text'] for row in result], ['现状：简历生成效果仍在优化'])
        self.assertEqual(format_rows(rows, facts, 'plain', role_family='other'), rows)
        self.assertEqual(rule_slot({'text': '真实模型效果仍需验证', 'kind': 'status_limit'}), '现状')

    def test_plain_work_counts_remain_unchanged_even_in_ai_profile(self):
        from app.agents.resume_writer import _source_evidence, _validate_plan
        from app.schemas.writer import MatchPlan
        source = {'work_experience': [{'item_id': 'w', 'company': '某公司', 'facts': [
            {'id': 'f', 'text': '整理资料', 'source_quote': '整理资料', 'kind': 'action', 'status': 'active'}]}]}
        evidence, items, facts = _source_evidence(source)
        plan = MatchPlan(bullet_style='labeled', experience_plan=[
            {'item_id': 'w', 'treatment': 'keep', 'target_bullets': 4}])
        result = _validate_plan(plan, evidence, {'role_family': 'ai_pm'}, items, facts)
        self.assertEqual(result['experience_plan'][0]['target_bullets'], 2)
