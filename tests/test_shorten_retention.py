"""A later shortening pass cannot undo a successful retention check."""
import asyncio
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.agents.tailor_pipeline import run_tailor_pipeline  # noqa: E402
from test_compression_retention import fixture, result, metadata, OLD, MERGED, pass_decision  # noqa: E402

SHORT = '组织代码索引与执行模块；PR #7 已合入上游，测试由队友负责。'


class ShortenRetentionTest(unittest.TestCase):
    def exercise(self, *, merge_first=False, replacement=SHORT, verdict='pass',
                 fallback=False, stale=False, scope='whole', manual_sibling=False):
        state, data, meta = fixture()
        if not merge_first:
            data['projects'][0]['polished_bullets'] = [MERGED]
            meta['bullets']['keep'] = metadata([MERGED], [['f0', 'f1']])
        index = 0
        if manual_sibling:
            data['projects'][0]['polished_bullets'].insert(0, '保留手工原句')
            meta['bullets']['keep'].insert(0, {})
            index = 1
        state['resume_data'], state['resume_meta'] = deepcopy(data), deepcopy(meta)
        calls, batches = [], []
        target = f'/projects/0/polished_bullets/{index}'
        structured = object()

        async def writer(_facts, _profile, _model, **kwargs):
            calls.append((kwargs['scope'], kwargs['targets']))
            if len(calls) == 1:
                return result(data, meta)
            current, evidence = deepcopy(kwargs['current_data']), deepcopy(kwargs['resume_meta'])
            if kwargs['scope'] == 'item':
                current['projects'][0]['polished_bullets'] = [MERGED]
                evidence['bullets']['keep'] = metadata([MERGED], [['f0', 'f1']])
            else:
                current['projects'][0]['polished_bullets'][index] = replacement
                evidence['bullets']['keep'][index] = metadata([replacement], [['f0', 'f1']])[0]
                if stale:
                    evidence['bullets']['keep'][index]['text_hash'] = 'stale'
                # Deliberately attempt unrelated edits: the adoption boundary
                # must discard them even when the selected sentence passes.
                current['basic_info']['name'] = 'Changed header'
                current['projects'][1]['name'] = 'Changed sibling'
                if manual_sibling:
                    current['projects'][0]['polished_bullets'][0] = 'Changed manual sibling'
            output = result(current, evidence)
            if fallback and kwargs['scope'] == 'bullet':
                output['writer_diagnostic']['status'] = 'model_fallback'
            return output

        async def verify(pairs, model, **_kwargs):
            self.assertIs(model, structured)
            batches.append(deepcopy(pairs))
            merged_step = len(pairs) == 2
            if not merged_step and verdict == 'error':
                raise ValueError('structured verifier failed')
            if not merged_step and verdict == 'missing':
                return {}
            return {row['id']: {**pass_decision(row['id']),
                    'verdict': 'pass' if merged_step or verdict == 'pass' else 'fail'} for row in pairs}

        with patch('app.agents.tailor_pipeline.run_resume_writer', side_effect=writer), \
                patch('app.agents.tailor_pipeline.verify_semantics', side_effect=verify), \
                patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={
                    'status': 'rendered', 'pages': 2, 'page_limit': 1, 'within_page_limit': False}):
            output = asyncio.run(run_tailor_pipeline(state, data, object(), structured_llm=structured,
                instruction='保留 PR 和队友分工，压缩为一页。', scope=scope,
                targets=[target] if scope == 'bullet' else ()))
        return output, data, meta, calls, batches

    def test_successful_merge_cannot_lose_pr_in_second_round_shortening(self):
        output, data, meta, calls, batches = self.exercise(merge_first=True, replacement=OLD[0], verdict='fail')
        self.assertEqual([scope for scope, _ in calls], ['whole', 'item', 'bullet'])
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[1][0]['text'], MERGED)
        self.assertEqual(batches[1][0]['source_quotes'], [OLD[0]])
        self.assertEqual(output['resume_data']['projects'][0]['polished_bullets'], [MERGED])
        self.assertEqual(output['resume_meta']['bullets']['keep'], metadata([MERGED], [['f0', 'f1']]))
        self.assertEqual([(row['op'], row['status']) for row in output['compression_retention_checks']],
                         [('merge_bullets', 'accepted'), ('shorten_bullet', 'rejected')])
        self.assertEqual(output['compression_retention_checks'][-1]['target'], '/projects/0/polished_bullets/0')
        self.assertFalse(output['page_check']['within_page_limit'])

    def test_never_merged_sentence_also_rejects_lost_evidence(self):
        output, data, meta, calls, batches = self.exercise(replacement=OLD[0], verdict='fail')
        self.assertEqual(output['resume_data'], data)
        self.assertEqual(output['resume_meta']['bullets'], meta['bullets'])
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(batches), 1)

    def test_shortening_failure_missing_verdict_and_stale_hash_keep_original(self):
        for options in ({'fallback': True}, {'stale': True}, {'verdict': 'error'}, {'verdict': 'missing'}):
            with self.subTest(options=options):
                output, data, meta, calls, _ = self.exercise(**options)
                self.assertEqual(output['resume_data'], data)
                self.assertEqual(output['resume_meta']['bullets'], meta['bullets'])
                self.assertEqual(len(calls), 2)
                self.assertFalse(output['page_check']['within_page_limit'])

    def test_selected_bullet_can_shorten_with_manual_sibling_untouched(self):
        output, data, meta, calls, batches = self.exercise(scope='bullet', manual_sibling=True)
        expected = deepcopy(data)
        expected['projects'][0]['polished_bullets'][1] = SHORT
        self.assertEqual(output['resume_data'], expected)
        self.assertEqual(output['resume_meta']['bullets']['keep'][0], {})
        self.assertEqual(output['resume_meta']['bullets']['keep'][1], metadata([SHORT], [['f0', 'f1']])[0])
        self.assertTrue(all(len(batch) == 1 for batch in batches))
        self.assertLessEqual(len(batches), 2)
        self.assertLessEqual(len(calls), 3)


if __name__ == '__main__':
    unittest.main()
