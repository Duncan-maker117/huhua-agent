"""Guest replay A–G regressions: fictional sources and fake models only."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.agents import resume_graph as graph
from app.agents import tailor_pipeline as pipeline
from app.agents.fact_extractor import apply_fact_patch
from app.agents.resume_writer import run_resume_writer
from app.agents.turn_actions import bind_role_followup, parse_education_fields
from app.agents.triage_chain import TriageAction, TriageDecision
from app.config import get_settings
from app.schemas.writer import LENIENT_SCHEMAS, StructurePlan
from app.services.candidate_material import parse_existing_resume
from app.services.profile_bridge import sanitize_fact_history
from app.services.renderer import render_resume
from app.services.resume_capacity import (plan_compression, revalidate_committed_page_check,
                                         resume_data_hash)
from app.services.resume_facts import (active_facts_for_writer, append_editor_facts,
                                      new_fact, normalize_fact_store)
from app.services.resume_field_hygiene import trim_name_punctuation
from app.services.skill_groups import normalize_skill_groups, split_skills
from app.services.structure_plan import select_plan
from test_compression_retention import MERGED, OLD, fixture, metadata, pass_decision, result
from test_replay_bug_regressions import ExtractModel
from test_replay_plan_intake_regressions import PlanModel
from test_structure_plan import card, source, writer_draft


PERSONAL = ('姓名张三，人在深圳，求职意向是 AI 产品实习。\n'
            '电话 13800000000，邮箱 a@example.com，GitHub 是 fiction-user，个人主页 fiction.test。\n'
            '可实习时间：每周五天，六个月\n'
            '教育：示例北大学，计算机科学与技术本科，2023.09–2027.06，获得过校级三等奖学金')


class GuestIntakeRegression(unittest.IsolatedAsyncioTestCase):
    async def test_model_omitting_contacts_still_saves_all_guest_header_fields(self):
        model = ExtractModel({'basic_info': {'links': [], 'availability': ''}})
        collected = await graph._extract_info_from_message(PERSONAL, graph._empty_collected_info(), model)
        basic = collected['basic_info']
        for key, value in {'name': '张三', 'phone': '13800000000', 'email': 'a@example.com',
                           'location': '深圳', 'availability': '每周五天，六个月'}.items():
            self.assertEqual(basic[key], value)
        self.assertEqual([link['url'] for link in basic['links']], ['fiction-user', 'fiction.test'])
        outbound = str(model.calls[0])
        self.assertNotIn('13800000000', outbound)
        self.assertNotIn('a@example.com', outbound)
        self.assertIn('⟦电话:', outbound)
        self.assertIn('⟦邮箱:', outbound)
        data = graph._serialize_to_resume_data({'collected_info': collected})
        self.assertEqual(data['basic_info']['name'], '张三')
        self.assertIn('a@example.com', render_resume('t001-jianyue', data))

    async def test_following_project_turn_cannot_clear_contacts_links_or_availability(self):
        collected = await graph._extract_info_from_message(PERSONAL, {}, ExtractModel({}))
        original = deepcopy(collected['basic_info'])
        next_turn = '我在拾光项目整理了用户反馈。'
        updated = await graph._extract_info_from_message(next_turn, collected, ExtractModel({
            'basic_info': {'name': '', 'phone': '', 'email': '', 'location': '', 'links': [], 'availability': ''}}))
        self.assertEqual(updated['basic_info'], original)
        self.assertEqual(collected['basic_info'], original)

    def test_positive_sparse_link_patch_unions_without_mutating_prior(self):
        before = {'basic_info': {'links': [{'text': 'GitHub', 'url': 'fiction-user'}]}}
        addition = {'text': '个人主页', 'url': 'fiction.test'}
        saved = deepcopy(before)
        after = apply_fact_patch(before, {'basic_info': {'links': [addition]}})
        self.assertEqual(after['basic_info']['links'], [*saved['basic_info']['links'], addition])
        self.assertEqual(before, saved)

    async def test_writer_merges_contacts_over_blank_header_without_profile(self):
        collected = source()
        collected['basic_info'] = (await graph._extract_info_from_message(PERSONAL, {}, ExtractModel({})))['basic_info']
        current = {'basic_info': {key: '' for key in ('name', 'phone', 'email', 'location')}}
        written = await run_resume_writer(collected, {}, PlanModel([('WriterDraft', writer_draft())]),
                                          phase='write', previous_plan=select_plan(card()), current_data=current)
        for key in ('name', 'phone', 'email', 'location', 'links', 'availability'):
            self.assertEqual(written['resume_data']['basic_info'][key], collected['basic_info'][key])
        self.assertEqual(current['basic_info']['name'], '')

    async def test_glued_major_recovered_when_fake_model_only_supplies_degree(self):
        message = '教育：示例北大学，计算机科学与技术本科，2023.09–2027.06，获得过校级三等奖学金'
        model = ExtractModel({'items': [{'section': 'education', 'name': '示例北大学', 'facts': [
            {'field': 'degree', 'kind': 'context', 'text': '本科', 'source_quote': '本科'}]}]})
        collected = await graph._extract_info_from_message(message, {}, model)
        row = graph._serialize_to_resume_data({'collected_info': collected})['education'][0]
        self.assertEqual(row['major'], '计算机科学与技术')
        self.assertEqual(row['degree'], '本科')
        self.assertEqual((row['start_date'], row['end_date']), ('2023.09', '2027.06'))
        self.assertIn('校级三等奖学金', row['highlights'])
        self.assertEqual(len(collected['education']), 1)

    def test_glued_degree_spans_and_parenthesized_degree_share_parser(self):
        for degree in ('本科', '硕士', '博士', '专科'):
            for separator in ('', '（', ' ('):
                text = f'示例北大学，计算机科学与技术{separator}{degree}' + ('）' if separator else '')
                with self.subTest(text=text):
                    parsed = parse_education_fields(text)
                    self.assertEqual(parsed['major'], '计算机科学与技术')
                    self.assertEqual(parsed['degree'], degree)

    async def test_generation_instruction_does_not_skip_major_recovery(self):
        state = graph._init_state()
        state.update(stage='COLLECTING', candidate_history_reconciled=True,
                     messages=[HumanMessage(content=PERSONAL + '\n请生成简历。')])
        with patch.object(graph, '_make_non_streaming_llm', return_value=ExtractModel({})):
            update = await graph._collecting_turn_node(state, object())
        self.assertEqual(update['stage'], 'BUILDING')
        self.assertEqual(active_facts_for_writer(update['collected_info'])['education'][0]['facts'][1]['field'], 'degree')
        data = graph._serialize_to_resume_data(update)
        self.assertEqual(data['education'][0]['major'], '计算机科学与技术')

    def test_document_contact_example_domain_is_kept_when_explicitly_supplied(self):
        document = PERSONAL.replace('教育：', '教育背景：') + '\n项目经历：\n拾光｜需求核对\n整理反馈。'
        parsed = parse_existing_resume(document)
        self.assertEqual(parsed['basic_info']['email'], 'a@example.com')
        self.assertEqual(parsed['education'][0]['major'], '计算机科学与技术')


class PunctuationRegression(unittest.TestCase):
    def test_balanced_brackets_and_quotes_survive_trailing_sentence_punctuation(self):
        for name in ('示例 AI Agent 赛晋级复赛（星舟）', '示例赛 (StarFlow)',
                     '示例赛「星舟」', '示例“星舟”', '"StarFlow"', '示例（星舟(A)）'):
            with self.subTest(name=name):
                self.assertEqual(trim_name_punctuation(name + '。；！'), name)

    def test_only_unmatched_brackets_and_sentence_punctuation_are_removed(self):
        self.assertEqual(trim_name_punctuation('，示例赛（星舟。'), '示例赛星舟')
        self.assertEqual(trim_name_punctuation('示例赛星舟）！'), '示例赛星舟')
        self.assertEqual(trim_name_punctuation('C++'), 'C++')
        self.assertEqual(trim_name_punctuation("O'Reilly"), "O'Reilly")

    def test_skill_split_trims_before_suffix_cleanup_and_keeps_tool_names(self):
        self.assertEqual(split_skills(['用 Claude Code 和 Codex 辅助开发。']), ['Claude Code', 'Codex'])
        groups = normalize_skill_groups({'工具': ['Codex 辅助开发。', 'Claude Code。', 'C++。']})
        self.assertEqual(groups['工具'], ['Codex', 'Claude Code'])
        self.assertEqual(groups['开发'], ['C++'])
        self.assertEqual(normalize_fact_store({'skills': ['Codex。']})['skills'][0]['name'], 'Codex')


class PositioningDiagnosticRegression(unittest.IsolatedAsyncioTestCase):
    async def test_supported_synthesis_has_own_semantic_context_then_renders_in_summary(self):
        collected = source()
        collected['projects'][0]['facts'].append(new_fact('本人做了 Agent 记忆与评测。'))
        raw = card()
        sentence = '做过 Agent 记忆与评测的 AI 产品实习生'
        raw['recommended']['positioning'] = sentence
        model = PlanModel([('StructurePlan', raw), ('WriterDraft', writer_draft())])
        planned = await run_resume_writer(collected, {}, model, phase='plan')
        self.assertEqual(planned['structure_plan']['recommended']['positioning'], sentence)
        self.assertEqual(planned['writer_diagnostic']['positioning_rejected_reason'], '')
        self.assertEqual(model.batches[0][0]['claim_kind'], 'positioning')
        written = await run_resume_writer(collected, {}, model, phase='write',
                                          previous_plan=select_plan(planned['structure_plan']))
        self.assertEqual(written['resume_data']['summary'], sentence)
        self.assertIn(sentence, render_resume('t001-jianyue', written['resume_data']))
        self.assertEqual(sum(row['id'] == 'plan_positioning_0' for row in model.batches[-1]), 1)

    async def test_positioning_rejection_logs_fixed_reason_without_source_prose(self):
        for sentence, options, expected in (
            ('综' * 41, {}, 'over_40_chars'),
            ('带来10000用户', {}, 'lexical_fact_errors'),
            ('实践者', {'fail_ids': ['plan_positioning_0']}, 'semantic_rejected'),
            ('实践者', {'missing_ids': ['plan_positioning_0']}, 'semantic_rejected'),
            ('实践者', {'semantic_error': True}, 'semantic_rejected'),
        ):
            with self.subTest(expected=expected, options=options):
                raw = card()
                raw['recommended']['positioning'] = sentence
                result = await run_resume_writer(source(), {}, PlanModel([('StructurePlan', raw)], **options), phase='plan')
                self.assertEqual(result['structure_plan']['recommended']['positioning'], '')
                self.assertEqual(result['writer_diagnostic']['positioning_rejected_reason'], expected)
                self.assertNotIn(sentence, str(result['writer_diagnostic']))


class LenientPlanRegression(unittest.IsolatedAsyncioTestCase):
    async def test_repair_list_bounds_numeric_bounds_and_literal_format_without_retry(self):
        raw = card()
        raw['alternatives'] *= 4
        raw['recommended']['experience_plan'][0]['target_bullets'] = 20
        raw['recommended']['experience_plan'][1]['target_bullets'] = -5
        raw['recommended']['experience_plan'][0]['treatment'] = ' LEAD '
        raw['recommended']['requirements'][0]['status'] = ' DIRECT '
        raw['recommended']['questions'] = [{'q': '还有哪些资料？', 'value': 9}]
        saved = deepcopy(raw)
        with patch.object(get_settings(), 'LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS', True):
            result = await run_resume_writer(source(), {}, PlanModel([('StructurePlan', raw)]), phase='plan')
        diagnostic = result['writer_diagnostic']
        self.assertEqual(diagnostic['status'], 'model_completed')
        self.assertEqual(diagnostic['schema_retry_count'], 0)
        self.assertEqual(len(result['structure_plan']['alternatives']), 2)
        self.assertEqual({row['reason'] for row in diagnostic['schema_repairs']},
                         {'truncated_list', 'clamped_range', 'normalized_literal'})
        self.assertEqual(raw, saved)

    def test_strict_contract_still_rejects_bounds_and_unknown_literals(self):
        raw = card()
        raw['alternatives'] *= 3
        with self.assertRaises(ValueError):
            StructurePlan.model_validate(raw)
        parsed = LENIENT_SCHEMAS[StructurePlan].model_validate(raw)
        self.assertEqual(len(parsed.alternatives), 2)
        raw['recommended']['experience_plan'][0]['treatment'] = 'invented'
        with self.assertRaises(ValueError):
            LENIENT_SCHEMAS[StructurePlan].model_validate(raw)

    async def test_unrepairable_plan_keeps_safe_validation_diagnostic_on_fallback(self):
        raw = card()
        raw['recommended']['experience_plan'][0]['treatment'] = 'PRIVATE_INVALID_VALUE'
        class InvalidPlanModel:
            def with_structured_output(self, schema):
                class Bound:
                    async def ainvoke(self, messages):
                        return deepcopy(raw)
                return Bound()
        with patch.object(get_settings(), 'LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS', True):
            result = await run_resume_writer(source(), {}, InvalidPlanModel(), phase='plan')
        diagnostic = result['writer_diagnostic']
        self.assertEqual(diagnostic['status'], 'model_fallback')
        self.assertEqual(diagnostic['schema_failure_reason_code'], 'schema_validation_failed')
        self.assertEqual(diagnostic['schema_retry_count'], 1)
        self.assertTrue(any(row['type'] == 'literal_error' for row in diagnostic['validation_errors']))
        self.assertNotIn('PRIVATE_INVALID_VALUE', json.dumps(diagnostic))


TEAM = '三个人的团队 有一个设计前端 我负责agent设计 还有一个负责后端还有沙箱'
METRIC = '拾光简历上线后有 10个人用过 做了20次简历任务'


def ownership_source():
    return {'projects': [
        {'item_id': 'resume', 'name': '拾光简历', 'facts': [new_fact('本人整理简历核对规则。')], 'raw_notes': []},
        {'item_id': 'flow', 'name': 'StarFlow', 'role': '原型', 'facts': [new_fact('本人整理需求记录。')], 'raw_notes': []},
    ]}


class FollowupOwnershipRegression(unittest.IsolatedAsyncioTestCase):
    async def test_fake_extractor_wrong_attachment_is_relocated_by_corresponding_question(self):
        question = '拾光简历上线后有多少用户、完成多少任务？\nStarFlow 的团队多少人，你负责什么分工？'
        model = ExtractModel({'items': [{'section': 'projects', 'item_id': 'resume', 'name': '拾光简历',
            'facts': [{'kind': 'result_metric', 'text': METRIC, 'source_quote': METRIC},
                      {'kind': 'role', 'text': '负责agent设计', 'source_quote': '我负责agent设计'}],
            'raw_notes': [METRIC, TEAM]}]})
        collected = await graph._extract_with_previous_assistant(METRIC + '\n' + TEAM, ownership_source(), model, question)
        a, b = collected['projects']
        self.assertTrue(any(f['source_quote'] == METRIC for f in a['facts']))
        self.assertFalse(any('agent设计' in f['text'] for f in a['facts']))
        self.assertTrue(any('agent设计' in f['text'] for f in b['facts']))
        self.assertFalse(b.get('role'))
        self.assertFalse(collected.get('pending_ownership'))
        self.assertTrue(all('agent设计' not in note for note in a['raw_notes']))

    def test_ambiguous_role_questions_remove_wrong_fact_and_ask_one_question(self):
        collected = ownership_source()
        collected['projects'][0]['facts'].append(new_fact(TEAM, kind='role', turn_id='team-turn'))
        collected['projects'][0]['raw_notes'].append(TEAM)
        question = '拾光简历团队多少人？StarFlow 团队多少人，分别负责什么？'
        result = bind_role_followup(collected, question, METRIC + '\n' + TEAM, 'team-turn')
        self.assertFalse(any('agent设计' in f['text'] for row in result['projects'] for f in row['facts']))
        self.assertEqual(result['pending_ownership'][0]['source_quote'], TEAM)
        self.assertEqual(graph.unrecorded_notice(result, METRIC + '\n' + TEAM).strip(), '三人团队这句说的是哪个项目？')
        self.assertEqual(graph._keep_unextracted_experience(result, ownership_source(), HumanMessage(content=METRIC + '\n' + TEAM)), result)
        resolved = bind_role_followup(result, '三人团队这句说的是哪个项目？', 'StarFlow')
        self.assertFalse(resolved['pending_ownership'])
        self.assertEqual(resolved['projects'][1]['facts'][-1]['source_quote'], TEAM)
        self.assertEqual(resolved['projects'][1]['facts'][-1]['turn_id'], 'team-turn')

    def test_explicit_name_in_role_sentence_overrides_previous_question(self):
        answer = 'StarFlow：' + TEAM
        result = bind_role_followup(ownership_source(), '拾光简历的团队多少人，你负责什么？', answer)
        self.assertTrue(any('agent设计' in f['text'] for f in result['projects'][1]['facts']))
        self.assertFalse(any('agent设计' in f['text'] for f in result['projects'][0]['facts']))

    def test_only_one_existing_item_cannot_supply_unasked_subject(self):
        collected = ownership_source()
        collected['projects'] = collected['projects'][:1]
        result = bind_role_followup(collected, '另一个项目的团队分工是什么？', TEAM)
        self.assertTrue(result['pending_ownership'])
        self.assertFalse(any('agent设计' in f['text'] for f in result['projects'][0]['facts']))

    async def test_short_project_name_answer_resolves_pending_before_extraction_length_gate(self):
        collected = {'projects': [{'item_id': 'p', 'name': '星舟', 'facts': [], 'raw_notes': []}],
                     'pending_ownership': [{'source_quote': TEAM, 'turn_id': 'earlier-turn'}]}
        state = graph._init_state()
        state.update(collected_info=collected, messages=[AIMessage(content='三人团队这句说的是哪个项目？'),
                                                       HumanMessage(content='星舟')])
        decision = TriageDecision(action=TriageAction.ASK_EXPERIENCE, reason='fake short answer')
        with patch.object(graph, '_make_non_streaming_llm', return_value=object()), \
             patch.object(graph, 'run_triage', AsyncMock(return_value=decision)), \
             patch.object(graph, 'stream_public_reply', AsyncMock(return_value=AIMessage(content='收到。'))), \
             patch('app.agents.interviewer.first_draft_ready', return_value=False):
            result = await graph._collecting_turn_node(state, object())
        self.assertFalse(result['collected_info']['pending_ownership'])
        self.assertEqual(result['collected_info']['projects'][0]['facts'][0]['turn_id'], 'earlier-turn')

    def test_editor_intake_and_persistence_remove_status_role_while_keeping_fact(self):
        document = {'projects': [{'item_id': 'p', 'name': '星舟', 'role': '原型'}]}
        collected = append_editor_facts({}, {}, document, 'editor-turn')
        self.assertFalse(collected['projects'][0].get('role'))
        self.assertTrue(any(f['kind'] == 'status_limit' for f in collected['projects'][0]['facts']))
        cleaned = sanitize_fact_history({'collected_info': collected, 'resume_data': document})
        self.assertFalse(cleaned['resume_data']['projects'][0]['role'])
        self.assertEqual(document['projects'][0]['role'], '原型')

    async def test_legacy_status_role_is_cleared_from_state_and_untargeted_canonical_item(self):
        normalized = normalize_fact_store(ownership_source())
        self.assertFalse(normalized['projects'][1].get('role'))
        self.assertTrue(any(f['kind'] == 'status_limit' for f in normalized['projects'][1]['facts']))
        data = {'projects': [{'item_id': 'flow', 'name': 'StarFlow', 'role': '原型', 'polished_bullets': []}]}
        written = await run_resume_writer(source(), {}, PlanModel([('WriterDraft', writer_draft())]),
            phase='write', previous_plan=select_plan(card()), current_data=data, scope='item', targets=['p1'])
        self.assertFalse(written['resume_data']['projects'][0]['role'])
        self.assertEqual(data['projects'][0]['role'], '原型')
        self.assertFalse(graph._serialize_to_resume_data({'collected_info': ownership_source()})['projects'][1]['role'])


class SanitizedCapacityRegression(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, *, merge=True, fits=True):
        state, data, meta = fixture()
        state['confirmed_plan'] = {'experience_plan': [{'item_id': 'keep', 'treatment': 'keep'},
                                                       {'item_id': 'other', 'treatment': 'brief'}]}
        obsolete = new_fact('旧版原型', kind='role')
        obsolete.update(field='role', status='superseded')
        state['collected_info']['projects'][0]['facts'].append(obsolete)
        data['projects'][0]['role'] = '旧版原型'
        calls, measured = [], []

        async def writer(_source, _profile, _model, **kwargs):
            calls.append(kwargs)
            output = deepcopy(data if len(calls) == 1 else kwargs['current_data'])
            out_meta = deepcopy(meta if len(calls) == 1 else kwargs['resume_meta'])
            if len(calls) > 1:
                if merge:
                    output['projects'][0]['polished_bullets'] = [MERGED]
                    out_meta['bullets']['keep'] = metadata([MERGED], [['f0', 'f1']])
                else:
                    output['projects'][0]['polished_bullets'][0] = OLD[0].rstrip('。')
                    out_meta['bullets']['keep'] = metadata(output['projects'][0]['polished_bullets'])
            return result(output, out_meta)

        def measure(document, constraints):
            measured.append(deepcopy(document))
            compressed = len(document['projects'][0]['polished_bullets']) == 1 if merge else document['projects'][0]['polished_bullets'][0] != OLD[0]
            pages = 1 if compressed and fits else 2
            return {'status': 'rendered', 'pages': pages, 'within_page_limit': pages == 1,
                    'page_limit': 1, 'data_hash': resume_data_hash(document)}

        async def verify(pairs, _model, **kwargs):
            return {row['id']: pass_decision(row['id']) for row in pairs}

        planned = {'op': 'merge_bullets' if merge else 'shorten_bullet', 'item_id': 'keep',
                   'target': '/projects/0/polished_bullets' + ('' if merge else '/0'),
                   'writer_required': True, 'max_bullets': 1, 'target_max_chars_estimate': 12}
        with patch.object(pipeline, 'run_resume_writer', side_effect=writer), \
             patch.object(pipeline, 'measure_rendered_pages', side_effect=measure), \
             patch.object(pipeline, 'verify_semantics', side_effect=verify), \
             patch.object(pipeline, 'plan_compression', return_value=[planned]):
            output = await pipeline.run_tailor_pipeline(state, data, object(), instruction='压成一页')
        return output, calls, measured, state

    async def test_sanitizer_runs_before_measurement_then_confirmed_plan_allows_merge(self):
        output, calls, measured, state = await self.exercise()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]['phase'], 'write')
        self.assertEqual(calls[1]['scope'], 'item')
        self.assertTrue(all(not document['projects'][0].get('role') for document in measured))
        self.assertTrue(output['page_check']['within_page_limit'])
        self.assertEqual(output['page_check']['data_hash'], resume_data_hash(output['resume_data']))
        self.assertEqual(output['page_check']['content_integrity'], 'changed_by_fact_sanitizer')
        self.assertFalse(any(row.get('hidden') for row in output['resume_data']['projects']))
        self.assertEqual(sanitize_fact_history({**state, **output})['resume_data'], output['resume_data'])

    async def test_confirmed_plan_allows_shorten_without_removing_sibling_bullet(self):
        output, calls, _, _ = await self.exercise(merge=False)
        self.assertEqual(calls[1]['scope'], 'bullet')
        self.assertEqual(calls[1]['targets'], ['/projects/0/polished_bullets/0'])
        self.assertEqual(output['resume_data']['projects'][0]['polished_bullets'], [OLD[0].rstrip('。'), OLD[1]])
        self.assertTrue(output['page_check']['within_page_limit'])

    async def test_overflow_receipt_reports_delta_and_named_brief_candidate(self):
        output, _, _, _ = await self.exercise(fits=False)
        reply = graph._writer_reply(output)
        self.assertIn('内容延伸到第 2 页', reply)
        self.assertNotIn('超出 1 页', reply)
        self.assertIn('Beta', reply)
        self.assertIn('由你决定', reply)
        self.assertFalse(any(row.get('hidden') for row in output['resume_data']['projects']))

    def test_confirmed_brief_is_considered_for_shortening_before_any_hiding(self):
        data = {'projects': [{'item_id': 'brief', 'polished_bullets': ['很长的事实描述' * 20]}]}
        actions = plan_compression(data, {'experience_plan': [{'item_id': 'brief', 'treatment': 'brief'}]}, allow_hiding=False)
        self.assertEqual(actions[0]['op'], 'shorten_bullet')
        self.assertFalse(any(row['op'] == 'hide_item' for row in actions))

    def test_post_commit_sanitizer_overflow_keeps_measured_false_not_unknown(self):
        data = {'projects': []}
        meta = {'page_check': {'status': 'rendered', 'pages': 3, 'page_limit': 1}}
        with patch('app.services.resume_capacity.measure_rendered_pages', return_value={
            'status': 'rendered', 'pages': 2, 'page_limit': 1, 'within_page_limit': False,
            'data_hash': resume_data_hash(data)}):
            checked = revalidate_committed_page_check(data, meta, {}, content_changed=True)
        self.assertFalse(checked['page_check']['within_page_limit'])
        self.assertEqual(checked['page_check']['pages'], 2)


if __name__ == '__main__':
    unittest.main()
