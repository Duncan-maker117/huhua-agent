"""Second Flash replay fixes: fictional evidence and local model doubles only."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.agents import resume_graph as graph
from app.agents.resume_writer import _STRUCTURE_CONTRACT, run_resume_writer
from app.agents.triage_chain import TriageAction, TriageDecision
from app.config import get_settings
from app.schemas.writer import LENIENT_SCHEMAS, StructurePlan
from app.services.structure_plan import apply_plan_structure, select_plan
from test_replay_bug_regressions import BASIC, PERSONAL, ExtractModel, intake_state
from test_structure_plan import card, fact, source, state, writer_draft


class PlanModel:
    """Script plan/write; return configurable semantic verdicts for each batch."""
    def __init__(self, responses=(), *, fail_ids=(), abstract_fail_ids=(), missing_ids=(), semantic_error=False):
        self.responses = list(responses)
        self.fail_ids = set(fail_ids)
        self.abstract_fail_ids = set(abstract_fail_ids)
        self.missing_ids = set(missing_ids)
        self.semantic_error = semantic_error
        self.calls = []
        self.batches = []

    def with_structured_output(self, schema):
        model = self

        class Bound:
            async def ainvoke(self, messages):
                model.calls.append(schema.__name__)
                payload = json.loads(messages[-1].content)
                if schema.__name__ == 'SemanticBatch':
                    model.batches.append(payload)
                    if model.semantic_error:
                        raise RuntimeError('fake semantic unavailable')
                    return {'decisions': [{
                        'id': row['id'], 'subject_ok': True,
                        'actions_supported': row['id'] not in model.fail_ids | model.abstract_fail_ids,
                        'objects_supported': True, 'results_supported': row['id'] not in model.fail_ids, 'limits_kept': True,
                        'unsupported_spans': [], 'verdict': 'fail' if row['id'] in model.fail_ids else 'pass',
                    } for row in payload if row['id'] not in model.missing_ids]}
                expected, result = model.responses.pop(0)
                if schema.__name__ != expected:
                    raise AssertionError((schema.__name__, expected))
                return deepcopy(result)

        return Bound()


class PlanValidationRegression(unittest.IsolatedAsyncioTestCase):
    async def planned(self, raw=None, **model_options):
        model = PlanModel([('StructurePlan', raw or card())], **model_options)
        result = await run_resume_writer(source(), state()['jd_info']['role_profile'], model, phase='plan')
        return result, model

    async def test_31_to_40_char_positioning_does_not_retry_or_truncate_either_plan(self):
        for length in (31, 40):
            raw = card()
            for row in [raw['recommended'], *raw['alternatives']]:
                row['positioning'] = '综' * length
            with self.subTest(length=length):
                result, model = await self.planned(raw)
                self.assertEqual(result['writer_diagnostic']['status'], 'model_completed')
                self.assertEqual(result['writer_diagnostic']['schema_retry_count'], 0)
                for row in [result['structure_plan']['recommended'], *result['structure_plan']['alternatives']]:
                    self.assertEqual(row['positioning'], '综' * length)
                self.assertEqual(model.calls, ['StructurePlan', 'SemanticBatch'])
                self.assertEqual(len(model.batches[0]), 2)

    async def test_over_40_char_positioning_is_discarded_without_schema_fallback(self):
        raw = card()
        for row in [raw['recommended'], *raw['alternatives']]:
            row['positioning'] = '综' * 41
        result, model = await self.planned(raw)
        for row in [result['structure_plan']['recommended'], *result['structure_plan']['alternatives']]:
            self.assertEqual(row['positioning'], '')
        self.assertEqual(result['writer_diagnostic']['status'], 'model_completed')
        self.assertEqual(model.calls, ['StructurePlan'])

    async def test_lenient_structure_plan_drops_nested_extras_but_preserves_valid_plan(self):
        raw = card()
        raw['plan_note'] = 'discard'
        raw['recommended']['rec_note'] = 'discard'
        raw['recommended']['requirements'][0]['req_note'] = 'discard'
        raw['recommended']['experience_plan'][0]['item_note'] = 'discard'
        raw['recommended']['questions'] = [{'q': '还有材料吗', 'question_note': 'discard',
                                            'improves': {'item_id': 'p1', 'improvement_note': 'discard'}}]
        raw['alternatives'][0]['alt_note'] = 'discard'
        raw['alternatives'][0]['experience_plan'][0]['alt_item_note'] = 'discard'
        with patch.object(get_settings(), 'LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS', True):
            result, model = await self.planned(raw)
        self.assertEqual(result['writer_diagnostic']['status'], 'model_completed')
        self.assertEqual(result['writer_diagnostic']['schema_retry_count'], 0)
        self.assertEqual(result['structure_plan']['recommended']['label'], '主线叙事型')
        self.assertEqual(set(result['writer_diagnostic']['ignored_extra_fields']),
                         {'plan_note', 'rec_note', 'req_note', 'item_note', 'question_note'})  # Diagnostic cap is five names.
        self.assertEqual(model.calls, ['StructurePlan', 'SemanticBatch'])
        self.assertNotIn('discard', str(result['structure_plan']))

    async def test_synthesis_thesis_survives_without_full_lexical_coverage_or_semantic_call(self):
        raw = card()
        thesis = '串联用户问题与技术实践，突出从观察到落地的产品思考'
        for row in [raw['recommended'], *raw['alternatives']]:
            row.update(thesis=thesis, positioning='')
        result, model = await self.planned(raw)
        for row in [result['structure_plan']['recommended'], *result['structure_plan']['alternatives']]:
            self.assertEqual(row['thesis'], thesis)
        rendered = apply_plan_structure({'projects': []}, select_plan(result['structure_plan']))
        self.assertNotIn(thesis, str(rendered))
        self.assertEqual(model.calls, ['StructurePlan'])

    async def test_thesis_unsupported_numbers_and_units_are_cleared(self):
        collected = source()
        collected['projects'][0]['facts'].append(fact('f4', '核对20次'))
        for thesis in ('展示1000用户增长', '完成20个用户反馈整理', '完成20次调用'):
            with self.subTest(thesis=thesis):
                raw = card()
                raw['recommended'].update(thesis=thesis, positioning='')
                raw['alternatives'][0]['positioning'] = ''
                result = await run_resume_writer(collected, {}, PlanModel([('StructurePlan', raw)]), phase='plan')
                self.assertEqual(result['structure_plan']['recommended']['thesis'], '')

    async def test_positioning_verification_fails_closed_for_fail_missing_and_provider_error(self):
        for options in ({'fail_ids': ['plan_positioning_0']}, {'missing_ids': ['plan_positioning_0']},
                        {'semantic_error': True}):
            with self.subTest(options=options):
                result, model = await self.planned(**options)
                self.assertEqual(result['structure_plan']['recommended']['positioning'], '')
                self.assertEqual(model.calls, ['StructurePlan', 'SemanticBatch'])

    async def test_positioning_is_batched_with_bullets_during_confirmed_write(self):
        selected = select_plan(card())
        selected['positioning'] = '串联用户反馈与工程落地的产品实践者'
        written = writer_draft()
        written['items'][0]['bullets'][0]['text'] = '修复多语言记忆混杂问题'
        written.update(summary='这个未采用的摘要不需要额外核验', summary_fact_ids=['f1'])
        model = PlanModel([('WriterDraft', written)])
        result = await run_resume_writer(source(), {}, model, previous_plan=selected, phase='write')
        self.assertEqual(model.calls, ['WriterDraft', 'SemanticBatch', 'RepairOutput', 'SemanticBatch'])
        self.assertEqual({row['id'] for row in model.batches[0]}, {'b0', 'plan_positioning_0'})
        self.assertEqual(result['resume_data']['summary'], selected['positioning'])

    async def test_failed_positioning_during_write_clears_summary_but_keeps_body(self):
        selected = select_plan(card())
        model = PlanModel([('WriterDraft', writer_draft())], fail_ids=['plan_positioning_0'])
        result = await run_resume_writer(source(), {}, model, previous_plan=selected, phase='write')
        self.assertEqual(model.calls, ['WriterDraft', 'SemanticBatch', 'RepairOutput'])
        self.assertEqual(result['resume_data']['summary'], '')
        self.assertEqual(result['confirmed_plan']['positioning'], '')
        self.assertNotIn('summary', result['resume_meta'])
        self.assertEqual(result['resume_data']['projects'][0]['polished_bullets'], ['整理用户反馈并分类'])


class CandidateRoutingRegression(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for context in (
            patch.object(get_settings(), 'LLM_PLAN_CONFIRM', True),
            patch.object(graph, '_make_non_streaming_llm', side_effect=lambda llm, **kwargs: llm),
            patch.object(graph, 'stream_public_reply', AsyncMock(return_value=AIMessage(content='已收到资料。'))),
            patch('app.agents.interviewer.first_draft_ready', return_value=False),
            patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={
                'status': 'rendered', 'pages': 1, 'within_page_limit': True, 'page_limit': 1}),
        ):
            context.start()
            self.addCleanup(context.stop)

    async def test_successful_misclassified_decoder_never_runs_on_personal_data_in_intake(self):
        for node in (graph.jd_input_node, graph.collecting_node):
            for existing_jd in (True, False):
                with self.subTest(node=node.__name__, existing_jd=existing_jd):
                    current = intake_state()
                    if not existing_jd:
                        current.update(jd_info={}, jd_text='')
                    model = ExtractModel({'basic_info': BASIC})
                    with patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(
                            action=TriageAction.DECODE_JD, reason='fake false positive'))), \
                            patch.object(graph, '_run_decoder_and_build_reply', AsyncMock(return_value=(
                                {'job_title': '错误的求职意向岗位'}, 'decoded'))) as decoder:
                        result = await node(current, model)
                    decoder.assert_not_awaited()
                    if existing_jd:
                        self.assertNotIn('jd_info', result)
                    else:
                        self.assertEqual(result['jd_info']['role_profile']['source'], 'direction')
                    self.assertNotIn('jd_text', result)
                    self.assertEqual(result['collected_info']['basic_info']['name'], BASIC['name'])
                    self.assertEqual(result['collected_info']['education'][0]['school'], '示例甲大学')
                    self.assertNotIn('personal-turn', result.get('non_candidate_message_ids', []))

    async def test_pending_plan_supplement_extracts_before_new_card_and_preserves_original_jd(self):
        current = state(PERSONAL)
        current.update(pending_plan=card(), candidate_history_reconciled=True, jd_text='岗位职责：记忆处理。')
        current['messages'][0].id = 'fictional-supplement'
        raw = card()
        raw['recommended']['label'] = '补料后的方案'
        model = PlanModel([('StructurePlan', raw)])
        extraction = ExtractModel({'basic_info': BASIC})
        original = graph._extract_info_from_message
        async def extract_personal(text, info, llm):
            return await original(text, info, extraction)
        with patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(
                action=TriageAction.DECODE_JD, reason='fake false positive'))), \
                patch.object(graph, '_run_decoder_and_build_reply', AsyncMock(return_value=(
                    {'job_title': '错误岗位'}, 'decoded'))) as decoder, \
                patch.object(graph, '_extract_info_from_message', AsyncMock(side_effect=extract_personal)) as extract, \
                patch('app.agents.tailor_pipeline.run_tailor_pipeline', AsyncMock()) as pipeline:
            result = await graph.structure_plan_node(current, model)
        decoder.assert_not_awaited()
        extract.assert_awaited_once()
        pipeline.assert_not_awaited()
        self.assertEqual(result['collected_info']['basic_info']['name'], BASIC['name'])
        self.assertEqual(result['pending_plan']['recommended']['label'], '补料后的方案')
        self.assertEqual(result['stage'], 'BUILDING')
        self.assertEqual({**current, **result}['jd_info'], current['jd_info'])
        self.assertEqual({**current, **result}['jd_text'], current['jd_text'])
        self.assertFalse(result.get('version_id'))
        self.assertEqual(model.calls, ['StructurePlan', 'SemanticBatch'])

    async def test_pending_plan_section_list_imports_then_replans_without_decoder(self):
        material = '开源贡献：\nEchoKit｜修复记忆缓存\n竞赛和荣誉：\n示例竞赛一等奖\n技能：\nPython / Figma'
        current = state(material)
        current.update(pending_plan=card(), candidate_history_reconciled=True)
        model = PlanModel([('StructurePlan', card())])
        with patch.object(graph, '_run_decoder_and_build_reply', AsyncMock()) as decoder:
            result = await graph.structure_plan_node(current, model)
        decoder.assert_not_awaited()
        self.assertTrue(result['pending_plan'])
        self.assertIn('Python', str(result['collected_info']['skills']))
        self.assertTrue(result['collected_info']['awards'])
        self.assertEqual(result['stage'], 'BUILDING')

    async def test_pending_confirmation_writes_even_when_a_live_intake_preview_exists(self):
        current = state('按推荐写')
        current.update(pending_plan=card(), resume_data=graph._serialize_to_resume_data(current))
        model = PlanModel([('WriterDraft', writer_draft())])
        result = await graph.structure_plan_node(current, model)
        self.assertTrue(result['version_id'])
        self.assertFalse(result['pending_plan'])
        self.assertTrue(result['confirmed_plan'])
        self.assertEqual(model.calls, ['WriterDraft', 'SemanticBatch', 'RepairOutput'])

    async def test_explicit_decode_task_cannot_bypass_personal_data_guard(self):
        current = {**intake_state(), 'requested_task': 'decode_jd'}
        with patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(
                action=TriageAction.DECODE_JD, reason='fake'))), \
                patch.object(graph, '_run_decoder_and_build_reply', AsyncMock()) as decoder:
            result = await graph.skill_task_node(current, ExtractModel({'basic_info': BASIC}))
        decoder.assert_not_awaited()
        self.assertEqual(result['requested_task'], 'auto')
        self.assertEqual(result['collected_info']['basic_info']['name'], BASIC['name'])

    async def test_personal_data_in_evaluating_and_export_keeps_jd_without_decoding(self):
        for node in (graph.evaluating_node, graph.export_node):
            with self.subTest(node=node.__name__):
                current = intake_state()
                current['resume_data'] = {'basic_info': {'name': '旧名'}}
                with patch.object(graph, '_run_decoder_and_build_reply', AsyncMock()) as decoder:
                    result = await node(current, ExtractModel({'basic_info': BASIC}))
                decoder.assert_not_awaited()
                self.assertEqual({**current, **result}['jd_info'], current['jd_info'])
                self.assertEqual(result['collected_info']['basic_info']['name'], BASIC['name'])

    async def test_existing_jd_blocks_unmarked_prose_replacement_but_accepts_explicit_jd(self):
        for text, allowed in [('招聘产品实习生，负责需求分析与合作。', False),
                              ('岗位职责：需求分析。任职要求：实践经验。', True)]:
            with self.subTest(text=text):
                current = intake_state(text)
                with patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(
                        action=TriageAction.DECODE_JD, reason='fake'))), \
                        patch.object(graph, '_run_decoder_and_build_reply', AsyncMock(return_value=(
                            {'job_title': '新岗位'}, '已读岗位'))) as decoder:
                    result = await graph.collecting_node(current, ExtractModel({}))
                self.assertEqual(decoder.await_count, int(allowed))
                self.assertEqual('jd_info' in result, allowed)

    async def test_checkpoint_saves_supplement_before_issuing_fresh_plan(self):
        current = {**intake_state(), 'stage': 'BUILDING', 'pending_plan': card(), 'collected_info': source()}
        model = PlanModel([('StructurePlan', card())])
        compiled = graph.build_graph(model)
        config = {'configurable': {'thread_id': 'fictional-supplement-checkpoint'}}
        await compiled.aupdate_state(config, {**current, 'messages': []})
        original = graph._extract_info_from_message
        async def extract_personal(text, info, llm):
            return await original(text, info, ExtractModel({'basic_info': BASIC}))
        with patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(
                action=TriageAction.DECODE_JD, reason='fake'))), \
                patch.object(graph, '_extract_info_from_message', AsyncMock(side_effect=extract_personal)), \
                patch.object(graph, '_run_decoder_and_build_reply', AsyncMock()) as decoder, \
                patch.object(graph, 'get_graph', return_value=compiled), \
                patch("app.services.session_store.save_candidate_intake"), \
                patch('app.services.session_store.save_resume_session') as save:
            chunks = [chunk async for chunk in graph.stream_agent([{'content': PERSONAL}],
                      'fictional-supplement-checkpoint', model)]
        decoder.assert_not_awaited()
        self.assertTrue(chunks)
        self.assertEqual(save.call_args.kwargs['collected_info']['basic_info']['name'], BASIC['name'])
        snapshot = (await compiled.aget_state(config)).values
        self.assertTrue(snapshot['pending_plan'])
        latest = next(message for message in reversed(snapshot['messages']) if isinstance(message, HumanMessage))
        self.assertNotIn(latest.id, snapshot['non_candidate_message_ids'])

    async def test_explicit_decode_stream_keeps_personal_message_as_candidate_source(self):
        model = ExtractModel({'basic_info': BASIC})
        compiled = graph.build_graph(model)
        config = {'configurable': {'thread_id': 'fictional-explicit-decode'}}
        current = intake_state()
        await compiled.aupdate_state(config, {**current, 'messages': []})
        with patch.object(graph, 'run_triage', AsyncMock(return_value=TriageDecision(
                action=TriageAction.DECODE_JD, reason='fake'))), \
                patch.object(graph, '_run_decoder_and_build_reply', AsyncMock()) as decoder, \
                patch.object(graph, 'get_graph', return_value=compiled), \
                patch("app.services.session_store.save_candidate_intake"), \
                patch('app.services.session_store.save_resume_session') as save:
            chunks = [chunk async for chunk in graph.stream_agent([{'content': PERSONAL}],
                      'fictional-explicit-decode', model, task='decode_jd')]
        decoder.assert_not_awaited()
        self.assertTrue(chunks)
        self.assertEqual(save.call_args.kwargs['collected_info']['basic_info']['name'], BASIC['name'])
        snapshot = (await compiled.aget_state(config)).values
        latest = next(message for message in reversed(snapshot['messages']) if isinstance(message, HumanMessage))
        self.assertEqual(latest.additional_kwargs['career_material_type'], 'candidate')
        self.assertNotIn(latest.id, snapshot['non_candidate_message_ids'])
        self.assertEqual(snapshot['jd_info'], current['jd_info'])
        self.assertEqual(snapshot['requested_task'], 'auto')


class ConfirmationAndSkillRegression(unittest.IsolatedAsyncioTestCase):
    async def test_confirmation_without_pending_plan_never_rewrites_any_stage(self):
        for stage in ('JD_INPUT', 'COLLECTING', 'BUILDING', 'EVALUATING', 'EXPORT'):
            for command in ('按推荐写', '就按这个写', '用推荐方案', '用备选1'):
                with self.subTest(stage=stage, command=command), patch.object(get_settings(), 'LLM_PLAN_CONFIRM', True):
                    current = state(command)
                    current.update(stage=stage, pending_plan={}, resume_data={
                        'projects': [{'item_id': 'p1', 'polished_bullets': ['原稿']}]})
                    before = deepcopy(current)
                    compiled = graph.build_graph(PlanModel())
                    result = await compiled.ainvoke(current, {'configurable': {'thread_id': 'fictional-confirmation'}})
                    self.assertIn('当前稿已按方案写好', result['messages'][-1].content)
                    self.assertIn('重新定方案', result['messages'][-1].content)
                    self.assertEqual(result['resume_data'], before['resume_data'])
                    self.assertFalse(result['version_id'])

    async def test_partial_writer_preserves_all_five_supported_skill_groups(self):
        groups = {'产品方法': ['用户调研'], 'AI 与 Agent': ['RAG'], '开发': ['Python'],
                  '工具': ['Figma'], '内容运营': ['短视频']}
        collected = source()
        collected['skills'] = [value for values in groups.values() for value in values]
        current = {'skill_groups': deepcopy(groups), 'skills': list(collected['skills'])}
        written = writer_draft()
        written['skill_groups'] = {'产品方法': ['用户调研'], '开发': ['Python']}
        model = PlanModel([('OnePassOutput', {'match_plan': {}, 'writer': written})])
        result = await run_resume_writer(collected, {}, model, current_data=current)
        self.assertEqual(result['resume_data']['skill_groups'], groups)
        self.assertEqual(result['resume_data']['skills'], collected['skills'])
        self.assertEqual(current['skill_groups'], groups)

    async def test_partial_first_write_fills_source_skills_and_never_revives_deleted_skill(self):
        collected = source()
        collected['skills'] = [{'name': 'Figma', 'status': 'active'}, {'name': 'RAG', 'status': 'active'},
                               {'name': 'Kubernetes', 'status': 'deleted'}]
        current = {'skill_groups': {'工具': ['Figma'], '开发': ['Kubernetes']}}
        written = writer_draft()
        written['skill_groups'] = {'工具': ['Figma', 'Terraform']}
        model = PlanModel([('OnePassOutput', {'match_plan': {}, 'writer': written})])
        result = await run_resume_writer(collected, {}, model, current_data=current)
        self.assertEqual(set(result['resume_data']['skills']), {'Figma', 'RAG'})
        self.assertNotIn('Kubernetes', str(result['resume_data']['skill_groups']))
        self.assertNotIn('Terraform', str(result['resume_data']['skill_groups']))


class PlanContractRegression(unittest.TestCase):
    def test_lenient_schema_keeps_strict_wire_contract_and_validation_when_disabled(self):
        raw = card()
        raw['recommended']['extra_note'] = 'drop'
        with self.assertRaises(ValueError):
            StructurePlan.model_validate(raw)
        parsed = LENIENT_SCHEMAS[StructurePlan].model_validate(raw)
        self.assertEqual(parsed.recommended.label, raw['recommended']['label'])
        schema = LENIENT_SCHEMAS[StructurePlan].model_json_schema()
        self.assertFalse(schema['additionalProperties'])
        self.assertTrue(all(not row.get('additionalProperties', True) for row in schema['$defs'].values()))
        self.assertIn('1–3句且总长≤90字', _STRUCTURE_CONTRACT)

    def test_each_personal_feature_blocks_decode_without_jd_and_jd_features_allow_it(self):
        for personal in ('姓名：合成', '电话：13900000000', '邮箱：fictional@test.test', '教育：本科',
                         '学校：示例大学', 'GitHub：fictional', '开源贡献：修复缓存', '竞赛：示例杯',
                         '荣誉：一等奖', '技能：Python', '我做反馈分类', '我负责核对'):
            with self.subTest(personal=personal):
                self.assertFalse(graph._jd_decode_allowed(personal, {}))
        for label in ('岗位职责', '任职要求', '职位描述', '工作职责', '岗位要求', '加分项'):
            with self.subTest(label=label):
                self.assertTrue(graph._jd_decode_allowed(f'{label}：需求分析。', {'jd_text': '旧JD'}))
        self.assertFalse(graph._has_jd_text(PERSONAL))
        self.assertFalse(graph._looks_like_role_direction(PERSONAL))

    def test_collection_prompts_encourage_complete_materials_with_one_impactful_question(self):
        for stage in ('JD_INPUT', 'COLLECTING_ASK_EXP', 'COLLECTING_WRAP'):
            prompt = graph.STAGE_PROMPTS[stage]
            with self.subTest(stage=stage):
                self.assertIn('一次把所有经历和材料都贴进来', prompt)
                self.assertIn('旧简历、截图或列表', prompt)
                self.assertIn('每轮最多问一个', prompt)
                self.assertIn('会改变简历', prompt)
