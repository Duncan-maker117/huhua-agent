"""Version history is document-only, bounded and evidence-aware."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.resume_versions import prepare_version, restore_payload, document_diff, valid_bullet_metadata, text_hash


class ResumeVersionsTests(unittest.TestCase):
    def data(self, text='实现原型接口'):
        return {'projects': [{'item_id': 'p1', 'name': 'Example', 'polished_bullets': [text]}]}

    def test_changed_version_snapshots_previous_document_and_caps_at_ten(self):
        old, new = self.data(), self.data('整理接口测试')
        old_meta = {'version_id': 'before', 'bullets': {'p1': [{'fact_ids': ['f1'], 'text_hash': text_hash('实现原型接口')}]}}
        versions = [{'version_id': str(i)} for i in range(15)]
        snapshot = copy.deepcopy((old, old_meta, versions))
        result = prepare_version(old, old_meta, versions, new, {}, label='精简项目')
        self.assertEqual(len(result['resume_versions']), 10)
        self.assertEqual(result['resume_versions'][-1]['resume_data'], old)
        self.assertNotIn('collected_info', result['resume_versions'][-1])
        self.assertEqual((old, old_meta, versions), snapshot)
        self.assertTrue(result['changed'])
        self.assertEqual(result['diff'][0]['item_id'], 'p1')

    def test_noop_does_not_create_snapshot_and_manual_change_drops_evidence(self):
        data = self.data()
        meta = {'version_id': 'v1', 'bullets': {'p1': [{'fact_ids': ['f1'], 'text_hash': text_hash('旧文字')}]}}
        result = prepare_version(data, meta, [], data, meta)
        self.assertFalse(result['changed'])
        self.assertEqual(result['resume_versions'], [])
        self.assertEqual(valid_bullet_metadata(data, meta)['bullets'], {})
        self.assertEqual(result['version_id'], 'v1')

    def test_restore_uses_saved_target_not_client_body_and_truncates_history(self):
        before, after = self.data(), self.data('新表述')
        state = {'resume_data': after, 'collected_info': {}, 'resume_versions': [
            {'version_id': 'v1', 'resume_data': before, 'resume_meta': {}}]}
        result = restore_payload(state)
        self.assertEqual(result['resume_data'], before)
        self.assertEqual(result['resume_versions'], [])
        self.assertNotIn('collected_info', result)
        self.assertTrue(result['diff'])
        with self.assertRaises(ValueError):
            restore_payload(state, 'forged')

    def test_restore_hides_later_items_without_permanent_identity_removal(self):
        old, current = self.data(), self.data()
        current['projects'].append({'item_id': 'p2', 'name': 'Later', 'polished_bullets': ['编写测试']})
        payload = restore_payload({'resume_data': current, 'collected_info': {}, 'resume_versions': [
            {'version_id': 'v1', 'resume_data': old, 'resume_meta': {}}]})
        self.assertTrue(payload['resume_data']['projects'][1]['hidden'])
        self.assertEqual(payload['resume_data']['projects'][1]['item_id'], 'p2')

    def test_reorder_has_observable_diff_even_when_text_is_identical(self):
        old = {'projects': [{'item_id': 'a'}, {'item_id': 'b'}]}
        new = {'projects': list(reversed(old['projects']))}
        self.assertEqual(document_diff(old, new)[0]['field'], 'order')

    def test_reordered_bullets_keep_corresponding_evidence_and_writer_context(self):
        from app.agents.resume_writer import _safe_current_targets
        a, b = '编写接口', '整理测试记录'
        meta = {'bullets': {'p1': [
            {'text_hash': text_hash(a), 'fact_ids': ['f1']},
            {'text_hash': text_hash(b), 'fact_ids': ['f2']}]}}
        original = copy.deepcopy(meta)
        data = {'projects': [{'item_id': 'p1', 'polished_bullets': [b, a]}]}
        cleaned = valid_bullet_metadata(data, meta)
        self.assertEqual([row['fact_ids'] for row in cleaned['bullets']['p1']], [['f2'], ['f1']])
        facts = {'f1': {'id': 'f1', 'item_id': 'p1', 'text': '写了接口'},
                 'f2': {'id': 'f2', 'item_id': 'p1', 'text': '整理过测试记录'}}
        context = _safe_current_targets(data, cleaned, {'p1'}, facts)
        self.assertEqual(context[0]['bullets'], [{'index': 0, 'text': b}, {'index': 1, 'text': a}])
        self.assertEqual(meta, original)

    def test_inserted_and_deleted_text_preserve_holes_without_borrowing_evidence(self):
        a, b = '编写接口', '整理测试记录'
        meta = {'bullets': {'p1': [
            {'text_hash': text_hash(a), 'fact_ids': ['f1']},
            {'text_hash': text_hash(b), 'fact_ids': ['f2']}]}}
        data = {'projects': [
            {'item_id': 'p1', 'polished_bullets': ['新增手动文字', b, '其他新文字']},
            {'item_id': 'p2', 'polished_bullets': [a, b]}]}
        cleaned = valid_bullet_metadata(data, meta)
        self.assertEqual(cleaned['bullets']['p1'], [{}, meta['bullets']['p1'][1], {}])
        self.assertNotIn('p2', cleaned['bullets'])
        data['projects'][0]['polished_bullets'] = [b]
        self.assertEqual(valid_bullet_metadata(data, cleaned)['bullets']['p1'], [meta['bullets']['p1'][1]])

    def test_duplicate_text_consumes_each_matching_record_once(self):
        text = '编写接口'
        rows = [{'text_hash': text_hash(text), 'fact_ids': [fid]} for fid in ['f1', 'f2']]
        data = {'work_experience': [{'item_id': 'w1', 'bullets': [text, text, text]}]}
        cleaned = valid_bullet_metadata(data, {'bullets': {'w1': rows}})
        self.assertEqual(cleaned['bullets']['w1'], [*rows, {}])


if __name__ == '__main__':
    unittest.main()
