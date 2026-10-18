import tempfile
"""c5 saved facts and separately identified c4 evaluation evidence; offline only."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]
from app.agents.resume_writer import _call, run_resume_writer  # noqa: E402
from app.services.fact_guard import guard_bullets  # noqa: E402
from app.services.labeled_writer import _checked, finish_rows, rule_slot  # noqa: E402
from app.services.project_heading import apply_project_headings  # noqa: E402
from app.schemas.writer import WrittenItem  # noqa: E402
from app.services.resume_versions import text_hash  # noqa: E402
from test_fact_guard import decision  # noqa: E402
from test_batch14c5_labeled import WrongModel, collected as c4_collected  # noqa: E402

FIXTURE = json.loads((ROOT / 'tests/fixtures/batch14c6-replay.json').read_text())['personas']


def collected(who):
    data = FIXTURE[who]
    project = {key: data['project'][key] for key in ('item_id', 'name', 'role', 'start_date', 'end_date')}
    fields = {value: key for key, value in project.items() if key != 'item_id'}
    project['facts'] = []
    for row in data['facts']:
        text = row['text']
        fact = {'id': row['fact_id'], 'item_id': project['item_id'], 'text': text,
                'source_quote': text, 'kind': 'action', 'status': 'active'}
        if text in fields:
            fact['field'] = fields[text]
        elif rule_slot(fact) == '问题':
            fact['kind'] = 'context'
        elif rule_slot(fact) == '现状':
            fact['kind'] = 'status_limit'
        project['facts'].append(fact)
    return {'projects': [project]}


def fact(text, fid='f', **kw):
    return {'id': fid, 'item_id': 'p', 'text': text, 'source_quote': text, 'kind': 'action', **kw}


class RejectModel(WrongModel):
    """Unavailable semantic results and missing repair rows force source fallback."""
    def with_structured_output(self, schema):
        if schema.__name__ == 'SemanticBatch':
            async def invoke(messages):
                data = json.loads(messages[-1].content)
                self.calls.append((schema.__name__, data))
                return {'decisions': []}
            return SimpleNamespace(ainvoke=invoke)
        return super().with_structured_output(schema)


class ClauseModel(RejectModel):
    def __init__(self, bad=''):
        super().__init__()
        self.bad = bad

    def with_structured_output(self, schema):
        if schema.__name__ == 'SemanticBatch':
            async def invoke(messages):
                data = json.loads(messages[-1].content)
                self.calls.append((schema.__name__, data))
                decisions = []
                for row in data:
                    value = decision(row['id'])
                    if self.bad and self.bad in row['text']:
                        value.update(verdict='fail', actions_supported=False, unsupported_spans=[self.bad])
                    decisions.append(value)
                return {'decisions': decisions}
            return SimpleNamespace(ainvoke=invoke)
        return super().with_structured_output(schema)


class Batch14c6Tests(unittest.IsolatedAsyncioTestCase):
    async def finish(self, facts, rows=(), model=None, cap=5, assignments=None):
        model = model or RejectModel()
        diagnostic = {}
        result = await finish_rows(list(rows), assignments or {fid: rule_slot(f) for fid, f in facts.items()},
            cap, 'p', facts, '', _call, model, model, 'ai_pm', diagnostic)
        return result, diagnostic, model

    def test_c5_missing_aipm_evaluation_is_absent_input_not_guard_loss(self):
        data = FIXTURE['aipm']
        self.assertNotIn('71', ''.join(data['inputs']))
        self.assertFalse(any(rule_slot(f) in {'问题', '迭代'} for f in collected('aipm')['projects'][0]['facts']))
        self.assertTrue(any('71' in f['text'] for f in c4_collected('aipm')['projects'][0]['facts']))
        self.assertEqual(len(FIXTURE['aipm_real']['diagnostic']['slot_undelivered']), 2)

    async def test_c5_real_facts_survive_unavailable_semantics_end_to_end(self):
        source = collected('aipm_real')
        before = deepcopy(source)
        current = {'projects': [deepcopy(FIXTURE['aipm_real']['project'])], 'verification_notes': [
            '「胡话简历」的问题、现状素材未能形成通过事实校验的正文，原事实保留在核对页。',
            '另一个需核对事项']}
        current_before = deepcopy(current)
        model = RejectModel()
        result = await run_resume_writer(source, {'role_family': 'ai_pm'}, model, current_data=current)
        item = result['resume_data']['projects'][0]
        body = item['polished_bullets']
        pain = next(row for row in body if row.startswith('问题：'))
        for word in ('填空', '复制粘贴', '无法编辑', '结构'):
            self.assertIn(word, pain)
        self.assertTrue(any(row.startswith('决策：') and 'MCP' in row for row in body))
        self.assertTrue(any(row.startswith('现状：') and '上线' in row for row in body))
        self.assertTrue(item['positioning'].startswith('面向'))
        self.assertNotRegex(' '.join(body), '甚至|非常|可能|差点意思')
        self.assertEqual(before, source)
        self.assertEqual(current_before, current)
        for row, record in zip(body, result['resume_meta']['bullets'][item['item_id']]):
            self.assertEqual(text_hash(row), record['text_hash'])
            self.assertEqual(record['fact_ids'], record['coverage_fact_ids'])
        self.assertNotIn('slot_undelivered', result['writer_diagnostic'])
        self.assertFalse(any('未能形成' in s for s in result['resume_data'].get('verification_notes', [])))
        self.assertIn('另一个需核对事项', result['resume_data']['verification_notes'])
        output = Path(tempfile.gettempdir(), 'huhua-b14c6')
        output.mkdir(exist_ok=True)
        (output / 'aipm_real-stub.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))

    async def test_c5_aipm_function_is_positioning_and_never_in_technology(self):
        result = await run_resume_writer(collected('aipm'), {'role_family': 'ai_pm'}, RejectModel())
        item = result['resume_data']['projects'][0]
        self.assertIn('学生', item['positioning'])
        tech = next(row for row in item['polished_bullets'] if row.startswith('技术：'))
        self.assertIn('API', tech)
        self.assertIn('Cursor', tech)
        self.assertNotIn('对话', tech)
        self.assertFalse(any('71' in row for row in item['polished_bullets']))
        output = Path(tempfile.gettempdir(), 'huhua-b14c6')
        output.mkdir(exist_ok=True)
        (output / 'aipm-c5-stub.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))

    async def test_c4_complete_aipm_facts_keep_problem_choice_evaluation_and_status(self):
        # The 5/71 source is explicitly c4, never represented as c5 model output.
        source = c4_collected('aipm')
        before = deepcopy(source)
        result = await run_resume_writer(source, {'role_family': 'ai_pm'}, RejectModel())
        item = result['resume_data']['projects'][0]
        rows = item['polished_bullets']
        self.assertEqual([s.split('：')[0] for s in rows], ['问题', '决策', '迭代', '现状'])
        evaluation = next(s for s in rows if s.startswith('迭代：'))
        self.assertRegex(evaluation, r'71\s*条断言')
        self.assertRegex(evaluation, r'5\s*个虚拟求职者')
        self.assertIn('或方案', evaluation)
        self.assertEqual(source, before)
        output = Path(tempfile.gettempdir(), 'huhua-b14c6')
        output.mkdir(exist_ok=True)
        (output / 'aipm-c4-complete-stub.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))

    async def test_supported_pain_synthesis_is_checked_by_clause_and_fact_union(self):
        facts = {f['id']: {**f, 'item_id': 'p'} for f in collected('aipm_real')['projects'][0]['facts'] if rule_slot(f) == '问题'}
        text = '普通简历工具需逐项填空，AI 优化的经历要手动复制粘贴；生成的 PDF 无法编辑，且不懂简历结构'
        row = {'id': 'p:问题', 'item_id': 'p', 'slot': '问题', 'text': text, 'fact_ids': list(facts)}
        reports, model = {}, ClauseModel()
        accepted = await _checked([row], facts, model, reports=reports)
        self.assertIn(row['id'], accepted)
        self.assertEqual(len(reports[row['id']]['clauses']), 4)
        for name, batch in model.calls:
            if name == 'SemanticBatch':
                for claim in batch:
                    self.assertIn(claim['claim_kind'], {'labeled_clause', 'slot_retention'})
                    if claim['claim_kind'] == 'labeled_clause':
                        self.assertGreaterEqual(len(claim['source_quotes']), 4)
                        self.assertEqual(claim['row_context'], text)

    async def test_pain_synonyms_pass_without_semantic_provider_and_plain_stays_strict(self):
        facts = [fact('普通简历工具需要用户一个一个填空，非常繁琐')]
        # Per-clause normalization does not globally weaken the plain guard.
        rows = [{'id': 'p:问题', 'item_id': 'p', 'slot': '问题',
                 'text': '普通简历工具需要用户逐项填空，非常低效', 'fact_ids': ['f']}]
        accepted = await _checked(rows, {'f': facts[0]}, None)
        self.assertTrue(accepted)
        plain = await guard_bullets(rows, facts, llm=None, lexical_only=True)
        self.assertIn('unsupported_manner:逐项', plain[0]['lexical_errors'])

    async def test_retry_receives_specific_failure_and_success_is_recorded(self):
        facts = {'f': fact('已上线', kind='status_limit')}
        model = RejectModel(repair=True)
        rows, diagnostic, _ = await self.finish(facts, [{'text': '已上线，1000 人使用', 'fact_ids': ['f']}], model)
        self.assertEqual(rows[0]['text'], '现状：已上线')
        trace = diagnostic['slot_lines']['p:现状']
        self.assertEqual(trace['retry_count'], 1)
        self.assertEqual(trace['final_handling'], 'retry')
        failures = trace['attempts'][0]['failures']
        self.assertIn('数字', {f['category'] for f in failures})
        payload = next(data for name, data in model.calls if name == 'RepairOutput')
        self.assertEqual(payload['labeled_slots'][0]['failures'], failures)
        self.assertNotIn('slot_fallbacks', diagnostic)

    async def test_retry_and_semantic_failure_restore_source_not_hallucination(self):
        facts = {'f': fact('仍在优化生成效果', source_quote='生成效果还差点意思，仍在优化', kind='status_limit')}
        rows, diagnostic, _ = await self.finish(facts, [{'text': '生成效果显著提高', 'fact_ids': ['f']}])
        self.assertEqual([row['text'] for row in rows], ['现状：仍在优化生成效果'])
        trace = diagnostic['slot_lines']['p:现状']
        self.assertEqual(trace['final_handling'], 'deterministic_fallback')
        self.assertEqual([a['stage'] for a in trace['attempts']], ['model', 'retry', 'deterministic_fallback'])
        self.assertEqual(trace['selected_fact_ids'], ['f'])
        self.assertTrue(trace['attempts'][0]['failures'])

    async def test_coverage_failure_has_missing_fact_details(self):
        facts = {'f': fact('用 71 条断言自动检查成稿'), 'g': fact('回放 5 个虚拟求职者的对话', 'g')}
        row = {'id': 'p:迭代', 'item_id': 'p', 'slot': '迭代', 'text': '用 71 条断言自动检查成稿', 'fact_ids': list(facts)}
        reports = {}
        accepted = await _checked([row], facts, RejectModel(), reports=reports)
        self.assertFalse(accepted)
        self.assertTrue(any(f.get('fact_id') == 'g' and f['code'] == 'fact_coverage_failed'
                            for f in reports[row['id']]['failures']))

    async def test_cross_slot_and_foreign_refs_are_diagnosed_and_not_reused(self):
        facts = {'f': fact('已上线'), 'other': fact('1000 人使用', 'other', item_id='peer')}
        rows, diag, _ = await self.finish(facts, [{'text': '现状：已上线，1000 人使用', 'fact_ids': ['f', 'other']}],
                                         assignments={'f': '现状', 'other': '现状'})
        self.assertEqual(rows[0]['fact_ids'], ['f'])
        self.assertEqual(rows[0]['text'], '现状：已上线')
        self.assertEqual(diag['slot_lines']['p:现状']['attempts'][0]['failures'][0]['code'], 'cross_slot_fact_ids')

    async def test_fallback_removes_fillers_keeps_qualifiers_and_is_not_length_truncated(self):
        texts = ['甚至仅在本地用 71 条断言检查成稿', '非常繁琐的填空流程',
                 '约 5 个虚拟求职者参与回放', '对比不同提示词或方案', '保留测试记录' * 45]
        facts = {str(i): fact(text, str(i)) for i, text in enumerate(texts)}
        rows, diag, _ = await self.finish(facts, assignments={fid: '迭代' for fid in facts})
        self.assertGreater(len(rows[0]['text']), 240)
        self.assertNotRegex(rows[0]['text'], '甚至|非常')
        for term in ('仅在本地', '71 条断言', '约 5 个虚拟求职者', '或方案'):
            self.assertIn(term, rows[0]['text'])
        self.assertEqual(rows[0]['fact_ids'], list(facts))
        self.assertEqual(diag['slot_lines']['p:迭代']['final_handling'], 'deterministic_fallback')

    async def test_constraint_only_empty_and_explicit_cap_recorded(self):
        facts = {'f': fact('没有用户量'), 'g': fact('已上线', 'g')}
        rows, diag, _ = await self.finish(facts, assignments={'f': '问题', 'g': '现状'}, cap=1)
        self.assertEqual(rows, [])
        self.assertEqual(diag['slot_lines']['p:问题']['final_handling'], 'constraints_only')
        self.assertEqual(diag['slot_lines']['p:现状']['final_handling'], 'omitted_by_explicit_cap')

    async def test_negation_in_pain_is_retained_not_treated_as_constraint(self):
        facts = {'f': fact('AI 生成的 PDF 用户无法编辑', kind='context')}
        rows, _, _ = await self.finish(facts)
        self.assertIn('无法编辑', rows[0]['text'])

    async def test_pending_status_is_not_promoted_when_removing_possible(self):
        facts = {'f': fact('可能上线下一版本', kind='status_limit')}
        rows, _, _ = await self.finish(facts)
        self.assertNotIn('可能', rows[0]['text'])
        self.assertIn('尚待确认', rows[0]['text'])
        self.assertNotIn('已上线', rows[0]['text'])

    async def test_semantic_rejection_of_action_is_diagnosed(self):
        facts = {'f': fact('核对了接口字段')}
        row = {'id': 'p:迭代', 'item_id': 'p', 'slot': '迭代', 'text': '修复了接口字段', 'fact_ids': ['f']}
        reports = {}
        self.assertFalse(await _checked([row], facts, ClauseModel(bad='修复'), reports=reports))
        self.assertIn('动作', {f['category'] for f in reports[row['id']]['failures']})
        self.assertTrue(any(f.get('span') == '修复' for f in reports[row['id']]['failures']))

    async def test_positioning_retries_bad_output_then_sources_audience_and_category(self):
        facts = {'f': fact('通过对话帮学生挖掘经历并撰写简历'), 'g': fact('AI简历助手「胡话简历」', 'g')}
        item = {'item_id': 'p', 'name': '胡话简历', 'facts': list(facts.values())}
        output, meta, diagnostic, model = {'p': ('projects', {})}, {}, {}, RejectModel()
        writer = WrittenItem(item_id='p', section='projects', title={
            'positioning': '1000 万人使用的 AI 工具', 'fact_ids': ['f']})
        await apply_project_headings({'p': writer}, output, {'p': ('projects', item)}, facts, meta, model,
            call=_call, writer_model=model, role_family='ai_pm', diagnostic=diagnostic)
        text = output['p'][1]['positioning']
        self.assertEqual(text, '面向学生的AI简历助手')
        self.assertEqual(meta['project_headings']['p']['text_hash'], text_hash(text))
        trace = diagnostic['slot_lines']['p:positioning']
        self.assertEqual(trace['retry_count'], 1)
        self.assertEqual(trace['final_handling'], 'deterministic_fallback')
        self.assertIn('数字', {f['category'] for f in trace['attempts'][0]['failures']})

    async def test_positioning_only_empty_when_audience_or_category_missing(self):
        facts = {'f': fact('用 Python 编写接口')}
        source = {'name': '项目', 'facts': list(facts.values())}
        output, diag = {'p': ('projects', {})}, {}
        model = RejectModel()
        await apply_project_headings({'p': WrittenItem(item_id='p', section='projects')}, output,
            {'p': ('projects', source)}, facts, {}, model, call=_call, writer_model=model,
            role_family='ai_pm', diagnostic=diag)
        self.assertNotIn('positioning', output['p'][1])
        self.assertEqual(diag['slot_lines']['p:positioning']['final_handling'], 'empty_insufficient_evidence')

    def test_functions_override_bad_method_tool_kind(self):
        for kind in ('action', 'method_tool', 'deliverable'):
            self.assertEqual(rule_slot(fact('通过对话帮学生挖掘经历并撰写简历', kind=kind)), '标题性质')
        self.assertEqual(rule_slot(fact('直接调用大模型 API', kind='method_tool')), '技术')
        self.assertEqual(rule_slot(fact('提示词与原型由本人完成', kind='method_tool')), '标题性质')
        self.assertEqual(rule_slot(fact('完成本地闭环原型，演示版使用本地数据与模拟模型', kind='status_limit')), '现状')

    async def test_status_cleanup_preserves_local_scope_and_deduplicates(self):
        facts = {'f': fact('仅在本地生成的简历和使用过程中的效果可能差点意思，还在优化'),
                 'g': fact('仅在本地生成的简历和使用过程中的效果可能差点意思，还在优化', 'g')}
        rows, _, _ = await self.finish(facts, assignments={'f': '现状', 'g': '现状'})
        self.assertEqual(rows[0]['text'], '现状：仅在本地简历生成与使用效果仍在优化')
        self.assertEqual(rows[0]['fact_ids'], ['f', 'g'])

    async def test_mixed_constraint_fact_is_not_reported_as_body_coverage(self):
        facts = {'f': fact('已上线'), 'g': fact('没有用户量', 'g')}
        rows, _, _ = await self.finish(facts, assignments={'f': '现状', 'g': '现状'})
        self.assertEqual(rows[0]['text'], '现状：已上线')
        self.assertEqual(rows[0]['fact_ids'], ['f'])
        self.assertEqual(rows[0]['coverage_fact_ids'], ['f'])

    async def test_new_units_entities_status_and_negation_have_specific_diagnostics(self):
        cases = [
            ('用 71 条断言检查成稿', '用 71 次调用检查成稿', '迭代', '数字'),
            ('用 Python 编写接口', '用 Kubernetes 编写接口', '技术', '实体'),
            ('计划上线', '已上线', '现状', '状态'),
            ('已上线', '尚未上线', '现状', '否定'),
            ('查看错分图片', '逐张查看错分图片', '迭代', '限定'),
        ]
        for source, text, slot, category in cases:
            with self.subTest(text=text):
                facts = {'f': fact(source)}
                row = {'id': 'p:' + slot, 'item_id': 'p', 'slot': slot, 'text': text, 'fact_ids': ['f']}
                reports = {}
                self.assertFalse(await _checked([row], facts, ClauseModel(), reports=reports))
                self.assertIn(category, {f['category'] for f in reports[row['id']]['failures']})

    async def test_bad_repair_id_keeps_returned_text_in_diagnostic(self):
        from app.schemas.writer import RepairOutput
        async def call(*args, **kwargs):
            return RepairOutput(bullets=[{'id': 'wrong', 'text': '已上线', 'fact_ids': ['f']}])
        facts, diagnostic = {'f': fact('已上线')}, {}
        rows = await finish_rows([], {'f': '现状'}, 1, 'p', facts, '', call, None, None, 'ai_pm', diagnostic)
        trace = diagnostic['slot_lines']['p:现状']
        self.assertEqual(rows[0]['text'], '现状：已上线')
        self.assertEqual(trace['final_handling'], 'deterministic_fallback')
        self.assertEqual(trace['attempts'][1]['model_rows'][0]['text'], '已上线')
        self.assertIn('repair_id_mismatch', {f['code'] for f in trace['attempts'][1]['failures']})

    async def test_legacy_recovery_cannot_hide_original_writer_failure(self):
        facts, diagnostic, model = {'f': fact('已上线')}, {}, RejectModel()
        original = [{'text': '已上线，1000 人使用', 'fact_ids': ['f']}]
        rows = await finish_rows([{'text': '已上线', 'fact_ids': ['f']}], {'f': '现状'}, 1,
            'p', facts, '', _call, model, model, 'ai_pm', diagnostic, model_rows=original)
        trace = diagnostic['slot_lines']['p:现状']
        self.assertEqual(trace['writer_output'], original)
        self.assertEqual(trace['attempts'][0]['text'], original[0]['text'])
        self.assertIn('数字', {f['category'] for f in trace['attempts'][0]['failures']})
        self.assertEqual(trace['retry_count'], 1)
        self.assertEqual(rows[0]['text'], '现状：已上线')
