"""Remaining replay failures: fictional evidence, fake writers, real PDF layout."""
from copy import deepcopy
import io
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import AsyncMock, patch

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.agents import resume_graph as graph
from app.agents.resume_writer import _WRITE_CONTRACT, _ONE_PASS_CONTRACT, run_resume_writer
from app.agents.tailor_pipeline import _retain_compressed_body, run_tailor_pipeline
from app.services.renderer import list_templates, render_resume
from app.services.resume_capacity import measure_rendered_pages, plan_compression
from app.services.resume_pdf import count_resume_pdf_pages, render_resume_pdf
from app.services.structure_plan import plan_summary, select_plan
from test_compression_retention import metadata, pass_decision
from test_replay_plan_intake_regressions import PlanModel
from test_structure_plan import card, fact, source


OWN = '在 DNS 被污染的代理网络下发现网页抓取失败并提交初版修复'
OTHER = '维护者指出方案会削弱防 SSRF 安全边界，改为独立显式开关后合并'
ORIGINAL = OWN + '；' + OTHER
LOST = '维护者指出方案会削弱防 SSRF 安全边界，改为拆成独立显式开关后合并'


def compression_case(section='open_source', merge=False, replacement=LOST, refs=('own', 'other')):
    field = 'polished_bullets' if section == 'projects' else 'bullets'
    texts = [OWN, OTHER] if merge else [ORIGINAL]
    current = {section: [{'item_id': 'oss', 'name': 'PaperKit', field: texts}]}
    evidence = {'bullets': {'oss': metadata(texts, [['own'], ['other']] if merge else [['own', 'other']])}}
    collected = {section: [{'item_id': 'oss', 'name': 'PaperKit', 'facts': [
        fact('own', OWN), fact('other', OTHER), {**fact('result', '改动已合并'), 'kind': 'result_qualitative'}]}]}
    proposed = deepcopy(current)
    proposed[section][0][field] = [replacement]
    revised = {'resume_data': proposed, 'resume_meta': {'bullets': {'oss': metadata([replacement], [list(refs)])}},
               'writer_diagnostic': {'status': 'model_completed'}}
    action = {'op': 'merge_bullets' if merge else 'shorten_bullet', 'item_id': 'oss',
              'target': f'/{section}/0/{field}' + ('' if merge else '/0')}
    return current, evidence, revised, action, collected


class PersonalCompressionRegression(unittest.IsolatedAsyncioTestCase):
    async def test_shortening_and_merging_cannot_leave_only_maintainer_actions_even_if_verifier_passes(self):
        for section in ('projects', 'work_experience', 'open_source'):
            for merge in (False, True):
                with self.subTest(section=section, merge=merge):
                    args = compression_case(section, merge)
                    verifier = AsyncMock(return_value={'retain_0': pass_decision('retain_0')})
                    with patch('app.agents.tailor_pipeline.verify_semantics', verifier):
                        data, evidence, reason = await _retain_compressed_body(*args, object())
                    self.assertEqual(data, args[0])
                    self.assertEqual(evidence, args[1])
                    self.assertEqual(reason, 'personal_action_missing')
                    verifier.assert_not_awaited()

    async def test_only_result_or_other_subject_references_do_not_satisfy_personal_fact_rule(self):
        for refs in (('result',), ('other',)):
            args = compression_case(replacement='发现网页抓取失败并提交修复；' + OTHER, refs=refs)
            with patch('app.agents.tailor_pipeline.verify_semantics', AsyncMock()) as verifier:
                data, evidence, reason = await _retain_compressed_body(*args, object())
            self.assertEqual((data, evidence), args[:2])
            self.assertEqual(reason, 'personal_action_missing')
            verifier.assert_not_awaited()

    async def test_bullet_without_own_action_can_still_be_shortened(self):
        args = compression_case(replacement='维护者要求改为独立开关后合并', refs=('other',))
        args[1]['bullets']['oss'] = metadata([ORIGINAL], [['other']])
        verifier = AsyncMock(return_value={'retain_0': pass_decision('retain_0')})
        with patch('app.agents.tailor_pipeline.verify_semantics', verifier):
            _, _, reason = await _retain_compressed_body(*args, object())
        self.assertNotEqual(reason, 'personal_action_missing')

    async def test_own_action_method_or_deliverable_can_survive_with_references_and_semantic_retention(self):
        for kind in ('action', 'method_tool', 'deliverable'):
            for merge in (False, True):
                args = compression_case(merge=merge, replacement='发现抓取失败并提交修复；' + OTHER)
                args[-1]['open_source'][0]['facts'][0]['kind'] = kind
                async def verify(pairs, _llm, **kwargs):
                    return {row['id']: pass_decision(row['id']) for row in pairs}
                with patch('app.agents.tailor_pipeline.verify_semantics', side_effect=verify):
                    data, evidence, reason = await _retain_compressed_body(*args, object())
                self.assertEqual(reason, 'accepted')
                self.assertEqual(data, args[2]['resume_data'])
                self.assertEqual(evidence, args[2]['resume_meta'])

    async def test_rejected_open_source_compression_is_recorded_and_does_not_hide_confirmed_experience(self):
        data, meta, revised, _, collected = compression_case()
        plan = {'experience_plan': [{'item_id': 'oss', 'treatment': 'lead', 'target_bullets': 1}]}
        initial = {'resume_data': data, 'resume_meta': meta, 'match_plan': plan,
                   'writer_diagnostic': {'status': 'model_completed'}}
        revised['match_plan'] = plan
        state = {'collected_info': collected, 'resume_data': data, 'resume_meta': meta,
                 'confirmed_plan': plan, 'jd_info': {'role_profile': {}}}
        with patch('app.agents.tailor_pipeline.run_resume_writer', AsyncMock(side_effect=[initial, revised])), \
                patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={
                    'status': 'rendered', 'pages': 2, 'within_page_limit': False, 'page_limit': 1,
                    'overflow_lines': 3, 'overflow_page_ratio': .06}):
            output = await run_tailor_pipeline(state, data, object(), instruction='压到一页')
        self.assertEqual(output['resume_data'], data)
        self.assertEqual(output['compression_retention_checks'][0]['reason'], 'personal_action_missing')
        self.assertEqual(output['compression_retention_checks'][0]['status'], 'rejected')
        self.assertEqual(output['compression_actions'], [])

    def test_both_writer_modes_state_personal_compression_contract(self):
        for contract in (_WRITE_CONTRACT, _ONE_PASS_CONTRACT):
            self.assertIn('shorten_bullet/merge_bullets', contract)
            self.assertIn('主语为本人的 action/method_tool/deliverable', contract)
            self.assertIn('保留原句', contract)


SHORT = '整理用户反馈并分类，记录测试样例和已有功能限制。'
# Keep capacity pressure without relying on duplicated prose (preflight removes it).
LONG = SHORT + ''.join(f'按原始记录{mode}核对用户反馈分类与测试样例，并记录已有功能的限制。'
                       for mode in ('逐项', '逐条', '分组', '分类'))


def three_line_fixture():
    return {'basic_info': {'name': '虚构候选人', 'objective': 'AI 产品实习'}, 'projects': [
        {'item_id': 'lead', 'name': '虚构反馈项目', 'polished_bullets': [LONG]},
        {'item_id': 'keep', 'name': '虚构核对项目', 'polished_bullets': [LONG]}],
        'open_source': [{'item_id': 'oss', 'name': 'PaperKit', 'bullets': ['修复网页抓取的显式开关。']}],
        'certificates': [f'虚构活动{i}：核对分类记录并保留功能限制。' for i in range(20)],
        'awards': [{'item_id': f'award{i}', 'name': f'虚构方案设计与反馈整理竞赛奖项{i}', 'level': '校级二等奖'} for i in range(4)],
        'sections': [{'id': k, 'kind': k, 'title': v} for k, v in [('projects', '项目经历'),
                     ('open_source', '开源贡献'), ('certificates', '证书/活动'), ('awards', '竞赛荣誉')]]}


class ThreeLinePageRegression(unittest.IsolatedAsyncioTestCase):
    async def test_actual_three_spilled_lines_fit_after_one_or_two_fake_shortens_with_all_confirmed_items_kept(self):
        data = three_line_fixture()
        collected = {'basic_info': deepcopy(data['basic_info']), 'certificates': deepcopy(data['certificates'])}
        meta = {'bullets': {}}
        for section in ('projects', 'open_source', 'awards'):
            field = 'polished_bullets' if section == 'projects' else 'bullets'
            collected[section] = []
            for item in data[section]:
                texts = item.get(field) or [item['name']]
                ids = [item['item_id'] + f'-f{i}' for i in range(len(texts))]
                collected[section].append({**item, 'facts': [fact(fid, text) for fid, text in zip(ids, texts)]})
                if field in item:
                    meta['bullets'][item['item_id']] = metadata(texts, [[fid] for fid in ids])
        plan = {'experience_plan': [{'item_id': iid, 'treatment': 'lead', 'target_bullets': 1}
                                    for iid in ('lead', 'keep', 'oss')]}
        # Exercise content compression with an explicitly locked layout.
        data['layout'] = {'density': 0, 'density_source': 'user'}
        state = {'collected_info': collected, 'resume_data': deepcopy(data), 'resume_meta': meta,
                 'confirmed_plan': plan, 'jd_info': {'role_profile': {}}}
        before = deepcopy(state)
        self.assertEqual(count_resume_pdf_pages('t001-jianyue', data), 2)
        self.assertEqual(measure_rendered_pages(data, {'page_limit': 1})['overflow_lines'], 3)
        calls = []
        async def writer(_source, _profile, _model, **kwargs):
            calls.append(kwargs['scope'])
            current, evidence = deepcopy(kwargs['current_data']), deepcopy(kwargs['resume_meta'])
            if kwargs['scope'] == 'bullet':
                _, section, index, field, bullet = kwargs['targets'][0].split('/')
                item = current[section][int(index)]
                text = LOST if reject_first and len(calls) == 2 else SHORT
                item[field][int(bullet)] = text
                refs = evidence['bullets'][item['item_id']][int(bullet)]['fact_ids']
                evidence['bullets'][item['item_id']][int(bullet)] = metadata([text], [refs])[0]
            return {'resume_data': current, 'resume_meta': evidence, 'match_plan': plan,
                    'writer_diagnostic': {'status': 'model_completed'}}
        async def verify(pairs, _model, **kwargs):
            return {row['id']: pass_decision(row['id']) for row in pairs}
        for reject_first in (False, True):
            calls.clear()
            current_base = deepcopy(data)
            # Both boundary fixtures spill exactly three lines. The tighter
            # one needs both long bullets; the other has room for one rejection.
            if reject_first:
                current_base['certificates'] = current_base['certificates'][:17]
            current_state = {**state, 'resume_data': deepcopy(current_base), 'collected_info': {
                **collected, 'certificates': deepcopy(current_base['certificates'])}}
            before_run = deepcopy(current_state)
            self.assertEqual(measure_rendered_pages(current_base, {'page_limit': 1})['overflow_lines'], 3)
            with self.subTest(reject_first=reject_first), \
                    patch('app.agents.tailor_pipeline.run_resume_writer', side_effect=writer), \
                    patch('app.agents.tailor_pipeline.verify_semantics', side_effect=verify):
                output = await run_tailor_pipeline(current_state, current_base, object(), instruction='保留所有确认经历，压到一页')
            self.assertEqual(count_resume_pdf_pages('t001-jianyue', output['resume_data']), 1)
            self.assertEqual(output['page_check']['pages'], 1)
            self.assertTrue(output['page_check']['within_page_limit'])
            self.assertIn(len(calls), (2, 3))
            self.assertEqual(calls[1:], ['bullet'] * (len(calls) - 1))
            self.assertTrue(all(row['op'] == 'shorten_bullet' for row in output['compression_actions']))
            if reject_first:
                self.assertEqual(calls, ['whole', 'bullet', 'bullet'])
                self.assertEqual([row['status'] for row in output['compression_retention_checks']], ['rejected', 'accepted'])
                self.assertEqual(output['resume_data']['projects'][0]['polished_bullets'], [LONG])
                self.assertEqual(output['resume_data']['projects'][1]['polished_bullets'], [SHORT])
            for section in ('projects', 'open_source', 'awards'):
                self.assertEqual([item['item_id'] for item in output['resume_data'][section]],
                                 [item['item_id'] for item in data[section]])
                self.assertTrue(all(not item.get('hidden') for item in output['resume_data'][section]))
            self.assertEqual(output['resume_data']['certificates'], current_base['certificates'])
            self.assertEqual(output['resume_data']['awards'], data['awards'])
            self.assertEqual(current_state, before_run)
        self.assertEqual(state, before)

    def test_awards_can_split_after_first_line_and_title_stays_with_it(self):
        data = {'basic_info': {'name': '虚构候选人'}, 'projects': [{'name': '虚构反馈项目', 'polished_bullets': [
            '整理用户反馈并分类，记录测试样例和已有功能的限制。'] * 32}], 'awards': [
            {'name': f'虚构方案设计与反馈整理竞赛奖项{i}', 'level': '校级二等奖'} for i in range(10)]}
        self.assertEqual(count_resume_pdf_pages('t001-jianyue', data), 2)
        with pdfplumber.open(io.BytesIO(render_resume_pdf('t001-jianyue', data))) as document:
            first, second = [page.extract_text() for page in document.pages]
        self.assertIn('竞赛荣誉', first)
        self.assertIn('奖项0', first)
        self.assertNotIn('竞赛荣誉', second)
        self.assertIn('奖项9', second)
        full = re.sub(r'\s+', '', first + second)
        self.assertTrue(all(item['name'] in full for item in data['awards']))

    def test_all_six_templates_allow_section_splitting_and_keep_title_with_first_line(self):
        for template in list_templates():
            html = render_resume(template['id'], three_line_fixture())
            self.assertRegex(html, r'\.section, \.item\s*\{[^}]*break-inside: auto')
            self.assertRegex(html, r'\.section-title\s*\{[^}]*break-after: avoid')
            self.assertRegex(html, r'\.awards-compact\s*\{[^}]*orphans: 1; widows: 1')
            self.assertNotRegex(html, r'\.section\s*\{[^}]*(?:page-)?break-inside:\s*avoid')

    def test_small_overflow_can_try_next_longest_after_first_rejection(self):
        actions = plan_compression(three_line_fixture(), {}, allow_hiding=False, page_check={
            'pages': 2, 'page_limit': 1, 'within_page_limit': False, 'overflow_lines': 3, 'overflow_page_ratio': .06})
        shortens = [row for row in actions if row['op'] == 'shorten_bullet']
        self.assertEqual([row['target'] for row in shortens], ['/projects/0/polished_bullets/0', '/projects/1/polished_bullets/0'])


class ReceiptReasonRegression(unittest.TestCase):
    def test_final_receipt_uses_first_reason_phrase_under_twenty_chars(self):
        plan = select_plan(card())
        plan['experience_plan'][0]['reason'] = 'EchoKit 修复跨语言记忆污染，直接对应岗位的工程核验。'
        result = {'resume_data': {'projects': [{'name': '纸舟计划', 'polished_bullets': ['整理反馈']}]},
                  'changed': True, 'confirmed_plan': plan, 'match_plan': plan, 'plan_summary': plan_summary(plan, source())}
        reply = graph._writer_reply(result) + graph._interview_suffix({'collected_info': source()}, result)[0]
        self.assertIn('EchoKit（修复跨语言记忆污染）', reply)
        self.assertNotIn('按已确认方案重点展示', reply)

    def test_missing_or_too_long_unbroken_reason_shows_name_without_placeholder(self):
        for reason in (None, '', '这个完整短语长度超过二十字且没有任何标点可供安全截断所以不能使用'):
            plan = select_plan(card())
            plan['experience_plan'][0]['reason'] = reason
            summary = plan_summary(plan, source())
            self.assertEqual(summary.splitlines()[1], '重点：EchoKit')
            self.assertLessEqual(len('**这版的思路**：' + summary), 150)


class DerivedPositioningRegression(unittest.IsolatedAsyncioTestCase):
    async def test_deleted_or_other_subject_facts_and_background_do_not_make_a_positioning(self):
        collected = source()
        for section in ('projects', 'open_source'):
            collected[section][0]['facts'][0]['kind'] = 'context'
            collected[section][0]['facts'].extend([{**fact('obsolete-' + section, '提升10000用户增长'), 'status': 'superseded'},
                                                  fact('other-' + section, '维护者完成修复并合并')])
        raw = card()
        for row in [raw['recommended'], *raw['alternatives']]:
            row.update(positioning='', thesis='突出产品思考')
        output = await run_resume_writer(collected, {}, PlanModel([('StructurePlan', raw)]), phase='plan')
        self.assertEqual(output['structure_plan']['recommended']['positioning'], '')
        self.assertEqual(output['writer_diagnostic']['positioning_source'], 'empty')
        self.assertEqual(output['writer_diagnostic']['positioning_fallback_reason'], 'model_empty')


if __name__ == '__main__':
    unittest.main()
