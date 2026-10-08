"""Automatic one-bullet compression must retain the supported second claim."""
import asyncio
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.agents.tailor_pipeline import run_tailor_pipeline  # noqa: E402
from app.services.resume_capacity import plan_compression, apply_deterministic_compression  # noqa: E402


OLD = ['组织代码索引与执行模块。', '相关改动通过 PR #7 合入上游；测试由队友负责。']
MERGED = '组织代码索引与执行模块，相关改动通过 PR #7 合入上游；测试由队友负责。'


def metadata(texts, ids=None):
    return [{'text_hash': hashlib.sha256(text.encode()).hexdigest(),
             'fact_ids': (ids[index] if ids else [f'f{index}'])}
            for index, text in enumerate(texts)]


def fixture():
    data = {'projects': [{'item_id': 'keep', 'name': 'Alpha', 'polished_bullets': list(OLD)},
                         {'item_id': 'other', 'name': 'Beta', 'polished_bullets': ['核对名单']}],
            'work_experience': [], 'basic_info': {'name': 'Candidate'}, 'self_evaluation': ''}
    meta = {'bullets': {'keep': metadata(OLD), 'other': metadata(['核对名单'], [['fo']])}}
    source = {'projects': [
        {'item_id': 'keep', 'name': 'Alpha', 'facts': [
            {'id': f'f{i}', 'kind': 'action', 'text': text, 'source_quote': text,
             'source': 'chat', 'status': 'active'} for i, text in enumerate(OLD)]},
        {'item_id': 'other', 'name': 'Beta', 'facts': [
            {'id': 'fo', 'kind': 'action', 'text': '核对名单', 'source_quote': '核对名单',
             'source': 'chat', 'status': 'active'}]},
    ]}
    state = {'collected_info': source, 'resume_data': deepcopy(data), 'resume_meta': deepcopy(meta),
             'resume_versions': [], 'jd_info': {'role_profile': {}}}
    return state, data, meta


def result(data, meta):
    return {'resume_data': deepcopy(data), 'resume_meta': deepcopy(meta),
            'match_plan': {'experience_plan': [{'item_id': 'keep', 'treatment': 'keep', 'target_bullets': 2},
                                              {'item_id': 'other', 'treatment': 'lead', 'target_bullets': 1}]},
            'writer_diagnostic': {'status': 'model_completed'}, 'guard_fallbacks': [], 'change_summary': ['修改']}


def pass_decision(identifier):
    return {'id': identifier, 'verdict': 'pass', 'subject_ok': True, 'actions_supported': True,
            'objects_supported': True, 'results_supported': True, 'limits_kept': True,
            'unsupported_spans': []}


class CompressionRetentionTest(unittest.TestCase):
    def exercise(self, *, verdict='pass', replacement=MERGED, diagnostic='model_completed',
                 corrupt_before=False, corrupt_after=False, scope='whole', targets=(), always_overflow=False):
        state, data, meta = fixture()
        if corrupt_before:
            meta['bullets']['keep'][1]['text_hash'] = 'stale'
        calls, checks = [], []
        structured_model = object()

        async def writer(_source, _profile, _model, **kwargs):
            calls.append(deepcopy({key: kwargs[key] for key in ('scope', 'targets', 'instruction', 'constraints')}))
            if len(calls) == 1:
                return result(data, meta)
            edited = deepcopy(kwargs['current_data'])
            edited_meta = deepcopy(kwargs['resume_meta'])
            if kwargs['scope'] == 'item':
                edited['projects'][0]['polished_bullets'] = replacement if isinstance(replacement, list) else [replacement]
                edited_meta['bullets']['keep'] = metadata(edited['projects'][0]['polished_bullets'],
                                                         [['f0', 'f1']] * len(edited['projects'][0]['polished_bullets']))
                if corrupt_after:
                    edited_meta['bullets']['keep'][0]['fact_ids'] = ['removed']
            returned = result(edited, edited_meta)
            returned['writer_diagnostic']['status'] = diagnostic
            return returned

        async def verify(pairs, model, **_kwargs):
            self.assertIs(model, structured_model)
            checks.append(deepcopy(pairs))
            if verdict == 'error':
                raise ValueError('local double failure')
            if verdict == 'missing':
                return {pairs[0]['id']: pass_decision(pairs[0]['id'])}
            return {row['id']: (pass_decision(row['id']) if verdict == 'pass'
                               else {**pass_decision(row['id']), 'verdict': 'fail'}) for row in pairs}

        def measure(current, constraints):
            fits = not always_overflow and current['projects'][0]['polished_bullets'] == [MERGED]
            return {'status': 'rendered', 'pages': 1 if fits else 2, 'page_limit': constraints['page_limit'],
                    'within_page_limit': fits}

        with patch('app.agents.tailor_pipeline.run_resume_writer', side_effect=writer), \
                patch('app.agents.tailor_pipeline.measure_rendered_pages', side_effect=measure), \
                patch('app.agents.tailor_pipeline.verify_semantics', side_effect=verify):
            output = asyncio.run(run_tailor_pipeline(state, data, object(), structured_llm=structured_model,
                instruction='请保留 PR 合入结果、团队分工，压到一页。', scope=scope, targets=targets))
        self.assertEqual(state['collected_info'], fixture()[0]['collected_info'])
        return output, calls, checks, data

    def test_second_bullet_pr_and_team_boundary_are_semantically_checked(self):
        output, calls, checks, original = self.exercise()
        self.assertEqual(output['resume_data']['projects'][0]['polished_bullets'], [MERGED])
        self.assertEqual(calls[1]['scope'], 'item')
        self.assertEqual(calls[1]['targets'], ['keep'])
        self.assertIn('请保留 PR 合入结果、团队分工', calls[1]['instruction'])
        self.assertEqual(calls[1]['constraints']['page_limit'], 1)
        self.assertEqual([row['text'] for row in checks[0]], OLD)
        self.assertTrue(all(row['source_quotes'] == [MERGED] for row in checks[0]))
        self.assertEqual(output['resume_data']['projects'][1], original['projects'][1])
        self.assertTrue(output['page_check']['within_page_limit'])

    def test_same_fact_ids_do_not_make_lost_pr_or_limits_pass(self):
        output, calls, checks, original = self.exercise(verdict='fail', replacement=OLD[0])
        self.assertEqual(output['resume_data'], original)
        self.assertEqual(len(checks), 1)
        self.assertEqual(len(calls), 2)
        self.assertFalse(output['page_check']['within_page_limit'])

    def test_failed_uncertain_or_invalid_merge_keeps_original_without_repeat(self):
        cases = ({'verdict': 'error'}, {'verdict': 'missing'}, {'diagnostic': 'model_fallback'}, {'replacement': []},
                 {'replacement': list(OLD)}, {'corrupt_before': True}, {'corrupt_after': True})
        for parameters in cases:
            with self.subTest(parameters=parameters):
                output, calls, checks, original = self.exercise(**parameters)
                self.assertEqual(output['resume_data'], original)
                self.assertLessEqual(len(calls), 2)
                self.assertFalse(output['page_check']['within_page_limit'])

    def test_bullet_scope_cannot_merge_its_siblings(self):
        output, calls, checks, original = self.exercise(scope='bullet', targets=['/projects/0/polished_bullets/0'])
        self.assertEqual(output['resume_data'], original)
        self.assertFalse(any(call['scope'] == 'item' for call in calls))
        self.assertEqual(checks, [])

    def test_item_scope_can_merge_only_selected_item(self):
        output, calls, checks, original = self.exercise(scope='item', targets=['keep'])
        self.assertEqual(output['resume_data']['projects'][0]['polished_bullets'], [MERGED])
        self.assertEqual(output['resume_data']['projects'][1], original['projects'][1])
        self.assertTrue(checks)

    def test_unselected_item_cannot_be_merged(self):
        output, calls, checks, original = self.exercise(scope='item', targets=['other'])
        self.assertEqual(output['resume_data'], original)
        self.assertEqual(len(calls), 1)
        self.assertEqual(checks, [])

    def test_section_scope_can_merge_authorized_project(self):
        output, calls, checks, _ = self.exercise(scope='section', targets=['projects'])
        self.assertEqual(output['resume_data']['projects'][0]['polished_bullets'], [MERGED])
        self.assertEqual(len(checks), 1)

    def test_two_rounds_use_at_most_two_writer_compressions(self):
        output, calls, checks, _ = self.exercise(always_overflow=True)
        self.assertEqual(len(calls), 3)
        self.assertEqual([call['scope'] for call in calls], ['whole', 'item', 'bullet'])
        self.assertEqual(len(checks), 2)
        self.assertFalse(output['page_check']['within_page_limit'])

    def test_capacity_plans_merge_and_never_deterministically_truncates_it(self):
        _, data, meta = fixture()
        actions = plan_compression(data, result(data, meta)['match_plan'])
        self.assertEqual(actions[0]['op'], 'merge_bullets')
        self.assertTrue(actions[0]['writer_required'])
        self.assertEqual(apply_deterministic_compression(data, actions), data)

    def test_two_keep_items_are_merged_in_separate_rounds(self):
        state, data, meta = fixture()
        data['projects'][1]['polished_bullets'] = ['核对名单', '记录缺失项']
        state['collected_info']['projects'][1]['facts'].append(
            {'id': 'fo2', 'kind': 'action', 'text': '记录缺失项', 'source_quote': '记录缺失项',
             'source': 'chat', 'status': 'active'})
        meta['bullets']['other'] = metadata(data['projects'][1]['polished_bullets'], [['fo'], ['fo2']])
        calls, batches = [], []

        async def writer(_source, _profile, _model, **kwargs):
            calls.append((kwargs['scope'], kwargs['targets']))
            current, evidence = deepcopy(kwargs['current_data']), deepcopy(kwargs['resume_meta'])
            if len(calls) == 1:
                current, evidence = deepcopy(data), deepcopy(meta)
            else:
                identifier = kwargs['targets'][0]
                row = next(row for row in current['projects'] if row['item_id'] == identifier)
                row['polished_bullets'] = ['；'.join(row['polished_bullets'])]
                refs = [ref for old in evidence['bullets'][identifier] for ref in old['fact_ids']]
                evidence['bullets'][identifier] = metadata(row['polished_bullets'], [refs])
            output = result(current, evidence)
            output['match_plan']['experience_plan'][1]['treatment'] = 'keep'
            return output

        async def verify(pairs, _model, **_kwargs):
            batches.append(pairs)
            self.assertTrue(all(row['text'] in row['source_quotes'][0] for row in pairs))
            return {row['id']: pass_decision(row['id']) for row in pairs}

        with patch('app.agents.tailor_pipeline.run_resume_writer', side_effect=writer), \
                patch('app.agents.tailor_pipeline.verify_semantics', side_effect=verify), \
                patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={
                    'status': 'rendered', 'pages': 2, 'page_limit': 1, 'within_page_limit': False}):
            output = asyncio.run(run_tailor_pipeline(state, data, object(), instruction='压到一页'))
        self.assertEqual(calls, [('whole', ()), ('item', ['keep']), ('item', ['other'])])
        self.assertEqual(len(batches), 2)
        self.assertEqual([len(row['polished_bullets']) for row in output['resume_data']['projects']], [1, 1])


if __name__ == '__main__':
    unittest.main()
