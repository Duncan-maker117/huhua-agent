"""Small-overflow and plan-copy regressions: fictional data and fake models only."""
from copy import deepcopy
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from docx import Document
from langchain_core.messages import AIMessage, HumanMessage
from lxml.html import fromstring

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.agents import resume_graph as graph
from app.agents.resume_writer import _STRUCTURE_CONTRACT, run_resume_writer
from app.agents.tailor_pipeline import run_tailor_pipeline
from app.agents.triage_chain import TriageAction, TriageDecision
from app.services.renderer import _env, list_templates, render_resume
from app.services.resume_capacity import measure_rendered_pages, plan_compression, small_page_overflow
from app.services.resume_pdf import render_resume_pdf
from app.services.skill_groups import display_skill_rows
from app.services.structure_plan import phrase_prefix, plan_summary
from app.tools.resume_data_docx import resume_data_to_docx
from test_compression_retention import fixture, metadata, pass_decision, result
from test_replay_plan_intake_regressions import PlanModel
from test_structure_plan import card, source


GROUPS = {'产品方法': ['需求分析', '原型设计', '反馈分类'], 'AI': ['Agent', 'RAG'],
          '开发': ['Python', 'SQL'], '工具': ['Claude Code', 'Codex'], '其他': ['badcase 评测']}
SMALL = {'status': 'rendered', 'pages': 2, 'page_limit': 1, 'within_page_limit': False,
         'overflow_lines': 2, 'overflow_height_px': 50.6, 'overflow_page_ratio': 0.0483}


class SmallOverflowRegression(unittest.TestCase):
    def test_short_groups_share_rows_in_all_templates_and_word_with_original_edit_paths(self):
        data = {'basic_info': {'name': '合成候选人'}, 'skill_groups': deepcopy(GROUPS)}
        before = deepcopy(data)
        expected = ['；'.join(name + '：' + ' / '.join(items) for name, items in row)
                    for row in display_skill_rows(GROUPS)]
        for template in list_templates():
            with self.subTest(template=template['id']):
                root = fromstring(render_resume(template['id'], data, interactive=True))
                self.assertEqual([row.text_content() for row in root.find_class('skill-row')], expected)
                self.assertIn('工具：Claude Code / Codex；其他：badcase 评测', root.text_content())
                for name, items in GROUPS.items():
                    for index, text in enumerate(items):
                        node = root.xpath('.//*[@data-field-path=$path]', path=f'/skill_groups/{name}/{index}')
                        self.assertEqual(node[0].text_content(), text)
        paragraphs = [p.text for p in Document(io.BytesIO(resume_data_to_docx(data))).paragraphs]
        self.assertTrue(all(row in paragraphs for row in expected))
        self.assertEqual(data, before)

    def test_long_groups_and_only_two_groups_are_not_packed(self):
        for groups in ({'工具': ['Claude Code', 'Codex'], '其他': ['badcase 评测']},
                       {'一': ['很长的技能描述' * 9], '二': ['短项'], '三': ['很长的技能描述' * 9]}):
            self.assertTrue(all(len(row) == 1 for row in display_skill_rows(groups)))

    def test_real_t001_two_spilled_skill_lines_fit_after_compacting_without_deleting_experience(self):
        data = {'basic_info': {'name': '虚构候选人', 'objective': 'AI 产品实习'},
                'projects': [{'name': '虚构项目', 'polished_bullets': [
                    '整理用户反馈并分类，记录测试样例和已有功能的限制。'] * 30}],
                'skill_groups': deepcopy(GROUPS)}
        with patch.dict(_env.filters, {'display_skill_rows': lambda groups: [[entry] for entry in groups.items()]}):
            old = measure_rendered_pages(data, {'page_limit': 1})
            pdf = render_resume_pdf('t001-jianyue', data)
        self.assertEqual(old['pages'], 2)
        self.assertEqual(old['overflow_lines'], 2)
        self.assertTrue(small_page_overflow(old))
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf)) as document:
            tail = document.pages[-1].extract_text()
            self.assertIn('Claude Code', tail)
            self.assertIn('badcase', tail)
            self.assertNotIn('整理用户反馈', tail)
        from_pdf = measure_rendered_pages(data, {'page_limit': 1}, pdf_bytes=pdf)
        self.assertEqual(from_pdf['overflow_lines'], 2)
        self.assertTrue(small_page_overflow(from_pdf))
        new = measure_rendered_pages(data, {'page_limit': 1})
        self.assertEqual(new['pages'], 1)
        self.assertEqual(new['overflow_height_px'], 0)
        self.assertEqual(len(data['projects'][0]['polished_bullets']), 30)

    def test_small_overflow_prefers_merging_brief_bullets_and_never_hides_first(self):
        _, data, meta = fixture()
        plan = result(data, meta)['match_plan']
        plan['experience_plan'][0]['treatment'] = 'brief'
        actions = plan_compression(data, plan, page_check=SMALL)
        self.assertEqual(actions[0]['op'], 'merge_bullets')
        self.assertNotIn('hide_item', [action['op'] for action in actions])
        large = {**SMALL, 'overflow_page_ratio': 0.15}
        self.assertEqual(plan_compression(data, plan, page_check=large)[0]['op'], 'hide_item')
        self.assertFalse(small_page_overflow({**SMALL, 'pages': 3}))

    def test_reply_reports_two_lines_without_suggesting_removal(self):
        _, data, meta = fixture()
        plan = result(data, meta)['match_plan']
        plan['experience_plan'][0]['treatment'] = 'brief'
        reply = graph._writer_reply({'resume_data': data, 'changed': True, 'page_check': SMALL,
                                     'match_plan': plan})
        self.assertIn('超出约 2 行', reply)
        self.assertNotIn('超出 1 页', reply)
        self.assertNotIn('移除', reply)
        unknown = graph._writer_reply({'resume_data': data, 'page_check': {
            key: value for key, value in SMALL.items() if not key.startswith('overflow_')}})
        self.assertIn('内容延伸到第 2 页', unknown)
        self.assertNotIn('超出 1 页', unknown)
        height_only = graph._writer_reply({'resume_data': data, 'page_check': {**SMALL, 'overflow_lines': None}})
        self.assertIn('约占一页的 5%', height_only)


class SmallOverflowPipelineRegression(unittest.IsolatedAsyncioTestCase):
    async def test_fake_shorten_finishes_before_any_experience_hiding(self):
        state, data, meta = fixture()
        old = '整理已有用户反馈并将所有反馈逐项记录后分类。'
        short = '整理并分类用户反馈。'
        data['projects'][0]['polished_bullets'] = [old]
        meta['bullets']['keep'] = metadata([old], [['f0']])
        state['collected_info']['projects'][0]['facts'] = [{
            'id': 'f0', 'kind': 'action', 'text': old, 'source_quote': old, 'status': 'active'}]
        original = deepcopy(state['collected_info'])
        calls = []

        async def writer(_source, _profile, _llm, **kwargs):
            calls.append(kwargs)
            current = deepcopy(data if len(calls) == 1 else kwargs['current_data'])
            evidence = deepcopy(meta if len(calls) == 1 else kwargs['resume_meta'])
            if len(calls) > 1:
                current['projects'][0]['polished_bullets'] = [short]
                evidence['bullets']['keep'] = metadata([short], [['f0']])
            output = result(current, evidence)
            output['match_plan']['experience_plan'][0]['treatment'] = 'brief'
            return output

        def measure(current, _constraints):
            fits = current['projects'][0]['polished_bullets'] == [short]
            return {**SMALL, 'pages': 1 if fits else 2, 'within_page_limit': fits,
                    'overflow_page_ratio': 0 if fits else SMALL['overflow_page_ratio']}

        async def verify(pairs, _llm, **kwargs):
            return {row['id']: pass_decision(row['id']) for row in pairs}

        with patch('app.agents.tailor_pipeline.run_resume_writer', side_effect=writer), \
                patch('app.agents.tailor_pipeline.measure_rendered_pages', side_effect=measure), \
                patch('app.agents.tailor_pipeline.verify_semantics', side_effect=verify):
            output = await run_tailor_pipeline(state, data, object(), instruction='压到一页')
        self.assertEqual([call['scope'] for call in calls], ['whole', 'bullet'])
        self.assertTrue(output['page_check']['within_page_limit'])
        self.assertEqual([action['op'] for action in output['compression_actions']], ['shorten_bullet'])
        self.assertTrue(all(not item.get('hidden') for item in output['resume_data']['projects']))
        self.assertEqual(state['collected_info'], original)


class PlanCopyRegression(unittest.TestCase):
    def test_complete_sentence_newline_and_short_balanced_reasons(self):
        plan = card()['recommended']
        thesis = '围绕评测方案与 badcase 分析展示已有实践。'
        plan['thesis'] = thesis + '还有第二句不应拼接。'
        plan['experience_plan'][0]['reason'] = 'EchoKit 修复记忆污染，体现核验能力。'
        summary = plan_summary(plan, source())
        self.assertEqual(summary.splitlines()[0], thesis)
        self.assertEqual(summary.splitlines()[1], '重点：EchoKit（修复记忆污染）')
        self.assertLessEqual(len('**这版的思路**：' + summary), 150)

    def test_long_thesis_and_reason_end_at_phrases_with_no_partial_words_or_open_marks(self):
        plan = card()['recommended']
        plan['thesis'] = '展示已有评测实践，' + '与 SuperLongTechnologyWord 相关的表述' * 8
        plan['experience_plan'][0]['reason'] = 'EchoKit 修复记忆污染，唯一同时命中「评测方案 + badcase 分析」与其他实践' * 5
        summary = plan_summary(plan, source())
        self.assertEqual(summary.splitlines()[0], '展示已有评测实践。')
        self.assertIn('EchoKit（修复记忆污染）', summary)
        self.assertNotIn('…', summary)
        self.assertEqual(summary.count('（'), summary.count('）'))
        self.assertEqual(summary.count('「'), summary.count('」'))
        self.assertLessEqual(len('**这版的思路**：' + summary), 150)

    def test_punctuation_inside_quotes_and_parentheses_does_not_break_sentence(self):
        plan = card()['recommended']
        plan['thesis'] = '围绕「评测，反馈」展示实践（含原型）。第二句。'
        self.assertEqual(plan_summary(plan, source()).splitlines()[0], '围绕「评测，反馈」展示实践（含原型）。')
        self.assertEqual(phrase_prefix('完整短语，未闭合「后续内容', 40), '完整短语')
        self.assertEqual(phrase_prefix('SuperLongTechnologyWord', 10), '')

    def test_collecting_contract_has_natural_acknowledgement_and_private_save_rule(self):
        prompt = graph.STAGE_PROMPTS['COLLECTING_WRAP']
        public, private = prompt.split('内部约束', 1)
        self.assertIn('已记下，右侧草稿会同步更新', public)
        self.assertNotIn('保存尚未完成', public)
        self.assertNotIn('正在同步草稿', public)
        self.assertIn('不得复述给用户', private)
        self.assertIn('不得声称已保存完成', private)
        self.assertIn('positioning 必填', _STRUCTURE_CONTRACT)


class PositioningPolishRegression(unittest.IsolatedAsyncioTestCase):
    async def test_collecting_fake_reply_receives_natural_acknowledgement_with_save_rule_private(self):
        from unittest.mock import AsyncMock
        from test_replay_bug_regressions import ExtractModel

        state = {**graph._init_state(), 'stage': 'COLLECTING', 'collected_info': source(),
                 'candidate_history_reconciled': True, 'messages': [
                     HumanMessage(content='我在纸舟计划整理用户反馈并分类。')]}
        model = ExtractModel({})

        async def public_reply(_llm, messages):
            public = messages[0].content.split('内部约束', 1)[0]
            self.assertIn('已记下，右侧草稿会同步更新', public)
            self.assertNotIn('保存尚未完成', public)
            return AIMessage(content='已记下，右侧草稿会同步更新。')

        with patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(
                action=TriageAction.WRAP_EXPERIENCE, reason='fake', experience_snippet=state['messages'][0].content))), \
                patch.object(graph, '_make_non_streaming_llm', return_value=model), \
                patch.object(graph, 'stream_public_reply', side_effect=public_reply):
            output = await graph.collecting_node(state, model)
        self.assertEqual(output['messages'][0].content, '已记下，右侧草稿会同步更新。')
        self.assertNotIn('已保存', output['messages'][0].content)
        self.assertTrue(output['resume_data']['projects'])

    async def test_abstract_action_rejection_is_relaxed_without_new_claims(self):
        raw = card()
        raw['recommended']['positioning'] = '通过记忆修复展示产品实践'
        model = PlanModel([('StructurePlan', raw)], abstract_fail_ids=['plan_positioning_0'])
        output = await run_resume_writer(source(), {}, model, phase='plan')
        self.assertEqual(output['structure_plan']['recommended']['positioning'], raw['recommended']['positioning'])
        self.assertTrue(output['writer_diagnostic']['positioning_semantic_relaxed'])

    async def test_missing_and_empty_positioning_recover_only_literal_fact_supported_thesis_clause(self):
        for missing in (True, False):
            raw = card()
            raw['recommended']['thesis'] = '修复跨语言记忆污染，展示产品实践。'
            if missing:
                del raw['recommended']['positioning']
            else:
                raw['recommended']['positioning'] = ''
            output = await run_resume_writer(source(), {}, PlanModel([('StructurePlan', raw)]), phase='plan')
            self.assertEqual(output['structure_plan']['recommended']['positioning'], '修复跨语言记忆污染')
            diagnostic = output['writer_diagnostic']
            self.assertEqual(diagnostic['positioning_model_output'], 'missing' if missing else 'empty')
            self.assertEqual(diagnostic['positioning_rejected_reason'], 'empty')
            self.assertEqual(diagnostic['positioning_source'], 'derived')
            self.assertEqual(diagnostic['positioning_fallback_reason'], 'supported_thesis_clause')

    async def test_no_supported_thesis_derives_from_lead_facts_with_diagnostic_reason(self):
        raw = card()
        raw['recommended'].update(positioning='', thesis='突出观察到落地的产品思考')
        output = await run_resume_writer(source(), {}, PlanModel([('StructurePlan', raw)]), phase='plan')
        self.assertEqual(output['structure_plan']['recommended']['positioning'], 'EchoKit：修复跨语言记忆污染')
        self.assertEqual(output['writer_diagnostic']['positioning_source'], 'derived')
        self.assertEqual(output['writer_diagnostic']['positioning_fallback_reason'], 'lead_experience_facts')

    async def test_new_numbers_and_tools_are_rejected_even_with_fake_semantic_pass(self):
        for sentence in ('带来10000用户', '使用 Kubernetes 做产品实践'):
            raw = card()
            raw['recommended']['positioning'] = sentence
            output = await run_resume_writer(source(), {}, PlanModel([('StructurePlan', raw)]), phase='plan')
            self.assertEqual(output['structure_plan']['recommended']['positioning'], '')
            self.assertEqual(output['writer_diagnostic']['positioning_rejected_reason'], 'lexical_fact_errors')

    async def test_new_outcome_is_rejected_and_fixed_dimensions_are_logged(self):
        class OutcomeModel(PlanModel):
            def with_structured_output(self, schema):
                parent = super().with_structured_output(schema)
                if schema.__name__ != 'SemanticBatch':
                    return parent

                class Bound:
                    async def ainvoke(self, messages):
                        value = await parent.ainvoke(messages)
                        for decision in value['decisions']:
                            if decision['id'] == 'plan_positioning_0':
                                decision.update(results_supported=False, verdict='fail')
                        return value
                return Bound()

        raw = card()
        raw['recommended']['positioning'] = '成功提升业务收入的产品实践者'
        output = await run_resume_writer(source(), {}, OutcomeModel([('StructurePlan', raw)]), phase='plan')
        self.assertEqual(output['structure_plan']['recommended']['positioning'], '')
        self.assertEqual(output['writer_diagnostic']['positioning_rejected_reason'], 'semantic_rejected')
        self.assertEqual(output['writer_diagnostic']['positioning_failed_dimensions'], ['results_supported'])


if __name__ == '__main__':
    unittest.main()
