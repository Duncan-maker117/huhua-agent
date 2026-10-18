import tempfile
"""c6 saved inputs and adverse local writer replies; no service or real model."""
from copy import deepcopy
from difflib import SequenceMatcher
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]
from app.agents import resume_writer as writer  # noqa: E402
from app.services.resume_limits import _already_visible, preserve_item_limits  # noqa: E402
from app.services.resume_versions import text_hash  # noqa: E402
from test_fact_guard import decision  # noqa: E402
from test_batch14c5_labeled import WrongModel  # noqa: E402

FIXTURE = json.loads((ROOT / 'tests/fixtures/batch14c7-replay.json').read_text())
TECH = FIXTURE['tech']
PAIN_REWRITE = '学生难以梳理自身经历；需借助对话挖掘可写进简历的事实'


def collected(snapshot):
    """Reconstruct fields/kinds; original extractor responses were not saved."""
    result = {}
    for section in ('work_experience', 'projects'):
        result[section] = []
        for item in snapshot['resume_data'].get(section, []):
            clean = {k: v for k, v in item.items() if k not in {'bullets', 'polished_bullets', 'description'}}
            fields = {v: k for k, v in clean.items() if isinstance(v, str) and k != 'item_id'}
            facts = []
            for f in snapshot['resume_meta']['fact_coverage']['facts']:
                if f['item_id'] != item['item_id']:
                    continue
                text = f['text']
                row = {'id': f['fact_id'], 'item_id': f['item_id'], 'text': text, 'source_quote': text,
                       'kind': 'context' if '难以' in text else 'action', 'status': 'active'}
                if text in fields:
                    row['field'] = fields[text]
                facts.append(row)
            result[section].append({**clean, 'facts': facts})
    return result


class TechModel:
    """Replay the visible c6 polish body as a later contract repair.

    This proves a real late-stage hole, not an assertion about the unsaved
    provider response that originally caused it.
    """
    def __init__(self):
        self.calls = []
        snap = TECH['02-polish']
        self.item = snap['resume_data']['work_experience'][0]
        self.rows = [{'text': text, 'fact_ids': record['fact_ids']} for text, record in zip(
            self.item['bullets'], snap['resume_meta']['bullets'][self.item['item_id']])]

    def with_structured_output(self, schema):
        async def invoke(messages):
            payload = json.loads(messages[-1].content)
            self.calls.append((schema.__name__, payload))
            if schema.__name__ == 'SemanticBatch':
                return {'decisions': [decision(row['id']) for row in payload]}
            if schema.__name__ in {'OnePassOutput', 'WriterDraft'}:
                draft = {'items': [{'item_id': self.item['item_id'], 'section': 'work_experience',
                                    'bullets': self.rows}]}
                return {'match_plan': TECH['02-polish']['match_plan'], 'writer': draft} if schema.__name__ == 'OnePassOutput' else draft
            if schema.__name__ == 'RepairOutput':
                if 'edit_contract' in payload:
                    return {'bullets': [{'id': old['id'], **new}
                                        for old, new in zip(payload['violations'], self.rows)]}
                return {'bullets': []}
            raise AssertionError(schema.__name__)
        return SimpleNamespace(ainvoke=invoke)


class PainModel(WrongModel):
    def __init__(self):
        super().__init__()
        self.prompt = ''

    def with_structured_output(self, schema):
        if schema.__name__ == 'OnePassOutput':
            async def invoke(messages):
                self.prompt = '\n'.join(str(m.content) for m in messages)
                data = json.loads(messages[-1].content)
                project = data['evidence']['projects'][0]
                refs = [f['id'] for f in project['facts'] if '难以' in f['text']]
                return {'match_plan': {'experience_plan': [{'item_id': project['item_id'],
                    'treatment': 'lead', 'target_bullets': 4}]}, 'writer': {'items': [{
                    'item_id': project['item_id'], 'section': 'projects',
                    'bullets': [{'text': '问题：' + PAIN_REWRITE, 'fact_ids': refs}]}]}}
            return SimpleNamespace(ainvoke=invoke)
        return super().with_structured_output(schema)


class Batch14c7Tests(unittest.IsolatedAsyncioTestCase):
    async def polish(self, model):
        before = TECH['01-initial']
        iid = before['resume_data']['work_experience'][0]['item_id']
        return await writer.run_resume_writer(collected(before), {
            'role_family': 'backend', 'required_skills': ['Java', 'Spring Boot', 'MySQL', 'Redis'],
            'jd_language': ['订单查询接口', 'Redis 缓存', '联合索引', '接口测试用例']}, model,
            current_data=before['resume_data'], resume_meta=before['resume_meta'],
            instruction=TECH['02-polish']['input'], scope='item', targets=[iid],
            previous_plan=before['match_plan'], constraints={'preserve_explicit_limits': True})

    async def test_late_contract_repair_reproduces_loss_and_final_gate_merges_count(self):
        with patch.object(writer, '_restore_final_metrics', AsyncMock(return_value={})):
            old = await self.polish(TechModel())
        self.assertNotIn('12 条', ' '.join(old['resume_data']['work_experience'][0]['bullets']))
        source_before = deepcopy(TECH)
        model = TechModel()
        result = await self.polish(model)
        self.assertTrue(any('edit_contract' in data for _, data in model.calls if isinstance(data, dict)))
        rows = result['resume_data']['work_experience'][0]['bullets']
        self.assertEqual(len(rows), 3)
        body = ' '.join(rows)
        for value in ('12 条接口测试用例', '420ms', '170ms', '导师指导', 'Redis', '前端', '订单查询', '测试环境', '没做线上压测'):
            self.assertIn(value, body)
        iid = model.item['item_id']
        records = result['resume_meta']['bullets'][iid]
        count = next(f for f in result['resume_meta']['fact_coverage']['facts'] if '12 条' in f['text'])
        self.assertEqual(count['status'], 'covered')
        self.assertTrue(any('12 条' in text and count['fact_id'] in rec['fact_ids'] for text, rec in zip(rows, records)))
        self.assertEqual([text_hash(t) for t in rows], [r['text_hash'] for r in records])
        self.assertIn(count['fact_id'], result['writer_diagnostic']['final_metric_restored'][iid])
        self.assertEqual(source_before, TECH)
        # Same numeric correction used by the next replay round keeps the count.
        from app.services.fact_corrections import apply_literal_corrections, correction_pairs
        pairs = correction_pairs(TECH['03-correction']['input'])
        corrected = apply_literal_corrections(collected(TECH['01-initial']), result['resume_data'], result['resume_meta'], pairs)['resume_data']
        self.assertIn('12 条', ' '.join(corrected['work_experience'][0]['bullets']))
        self.assertIn('190ms', ' '.join(corrected['work_experience'][0]['bullets']))
        out = Path(tempfile.gettempdir(), 'huhua-b14c7')
        out.mkdir(exist_ok=True)
        (out / 'tech-stub.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))

    async def test_final_numeric_recovery_respects_backup_zero_and_scope(self):
        source = collected(TECH['02-polish'])
        _, items, _ = writer._source_evidence(source)
        iid = source['work_experience'][0]['item_id']
        for treatment, cap, allowed in [('backup', 3, {iid}), ('brief', 1, {iid}), ('lead', 0, {iid}), ('lead', 3, set())]:
            with self.subTest(treatment=treatment, cap=cap, allowed=allowed):
                data, meta = deepcopy(TECH['02-polish']['resume_data']), deepcopy(TECH['02-polish']['resume_meta'])
                before = deepcopy(data)
                missing = await writer._restore_final_metrics(data, meta, items, {iid: treatment}, {iid: cap}, allowed, TechModel())
                self.assertFalse(missing)
                self.assertEqual(before, data)

    async def test_final_numeric_recovery_is_idempotent_and_preserves_other_items(self):
        source = collected(TECH['02-polish'])
        _, items, _ = writer._source_evidence(source)
        iid = source['work_experience'][0]['item_id']
        data, meta = deepcopy(TECH['02-polish']['resume_data']), deepcopy(TECH['02-polish']['resume_meta'])
        await writer._restore_final_metrics(data, meta, items, {iid: 'lead'}, {iid: 3}, {iid}, TechModel())
        before = deepcopy((data, meta))
        self.assertFalse(await writer._restore_final_metrics(data, meta, items, {iid: 'lead'}, {iid: 3}, {iid}, TechModel()))
        self.assertEqual(before, (data, meta))
        self.assertEqual(data['projects'], TECH['02-polish']['resume_data']['projects'])

    def test_ownership_paraphrase_is_covered_before_append_and_idempotent(self):
        source = collected(TECH['01-initial'])
        project = source['projects'][0]
        text = '登录模块由组内另一位同学实现'
        data = {'projects': [{'item_id': project['item_id'], 'name': project['name'], 'polished_bullets': [text]}]}
        fact = next(f for f in project['facts'] if '登录模块' in f['text'])
        source = {'projects': [{**project, 'facts': [fact]}]}
        meta = {'bullets': {project['item_id']: [{'fact_ids': [fact['id']], 'text_hash': text_hash(text)}]}}
        result, metadata, _ = preserve_item_limits(data, meta, source, item_ids=[project['item_id']])
        self.assertEqual(result['projects'][0]['polished_bullets'], [text])
        again, records, _ = preserve_item_limits(result, metadata, source, item_ids=[project['item_id']])
        self.assertEqual((again, records), (result, metadata))
        self.assertEqual(records['bullets'][project['item_id']][0]['text_hash'], text_hash(text))

    def test_ownership_equivalence_preserves_actor_object_negation_and_scope(self):
        fact = '登录模块是另一位同学写的'
        self.assertTrue(_already_visible(fact, ['登录模块由组内另一位同学实现']))
        for other in ('搜索模块由组内另一位同学实现', '登录模块由本人实现', '登录模块由另一位同事实现',
                      '登录模块由另一位同学计划实现', '登录模块由另一位同学协助实现', '登录模块并非由另一位同学实现',
                      '并非登录模块由另一位同学实现', '计划登录模块由另一位同学实现', '登录模块由另一位同学实现了一部分'):
            with self.subTest(other=other):
                self.assertFalse(_already_visible(fact, [other]))

    def test_saved_aipm_pain_was_model_output_not_deterministic_fallback(self):
        diag = FIXTURE['aipm']['05-plan_confirm']['resume_meta']['writer_diagnostic']
        trace = next(v for k, v in diag['slot_lines'].items() if k.endswith(':问题'))
        self.assertEqual(trace['final_handling'], 'model')
        self.assertEqual(trace['retry_count'], 0)
        self.assertEqual([a['stage'] for a in trace['attempts']], ['model'])
        self.assertEqual(trace['writer_output'][0]['text'].rstrip('。'), trace['final_text'])

    async def test_pain_paraphrase_instruction_reaches_writer_and_preserves_fact(self):
        snapshot = FIXTURE['aipm']['05-plan_confirm']
        model = PainModel()
        result = await writer.run_resume_writer(collected(snapshot), {'role_family': 'ai_pm'}, model)
        self.assertIn('不整句照搬答案', model.prompt)
        self.assertIn('不能把用户需求写成已实现的功能或成果', model.prompt)
        project = result['resume_data']['projects'][0]
        pain = next(t for t in project['polished_bullets'] if t.startswith('问题：'))
        original = next(f for f in snapshot['resume_meta']['fact_coverage']['facts'] if '难以' in f['text'])
        self.assertEqual(pain, '问题：' + PAIN_REWRITE)
        self.assertLessEqual(SequenceMatcher(None, pain, original['text'], autojunk=False).find_longest_match().size, 24)
        record = next(r for r in result['resume_meta']['bullets'][project['item_id']] if r.get('slot') == '问题')
        self.assertEqual(record['fact_ids'], [original['fact_id']])
        self.assertEqual(record['text_hash'], text_hash(pain))


if __name__ == '__main__':
    unittest.main()
