"""Frozen public comparison input; offline models, real routing and writeback gates."""
# ruff: noqa: E402 -- application imports require the repository backend path.
from pathlib import Path
import asyncio
import json
from copy import deepcopy
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.agents import resume_graph as graph
from app.agents.fact_extractor import apply_fact_patch, extract_facts_patch
from app.agents.resume_writer import run_resume_writer
from app.config import get_settings
from app.services.candidate_material import requests_fabrication, split_mixed_material
from app.services.candidate_sections import parse_header_fields
from app.services.experience_subjects import explicit_subject_spans
from app.services.fact_coverage import ensure_fact_coverage
from app.services.fact_guard import contribution_conflict, guard_bullets
from app.services.resume_delivery import (
    correct_export_claims, guard_delivery, omit_missing_placeholders, presents_resume_body,
    must_buffer_reply, ReplyStreamBuffer,
)
from app.services.resume_facts import new_fact, normalize_fact_store
from app.services.resume_limits import preserve_item_limits
from app.services.resume_review import resume_to_text
from app.services.resume_workspace import build_workspace
from test_campus_and_naming import EchoWriter, ExtractorStub, semantic_stub
from test_structure_plan import FakeModel, card, source, writer_draft

P1, P2, P3 = re.findall(r'```text\n(.*?)\n```', (Path(__file__).with_name('comparison_case_prompts.txt')).read_text(), re.S)[:3]
BODY = '# 林知夏\n## 教育背景\n海川理工大学\n## 项目经历\n- 访谈18名同学\n## 技能\nSQL基础查询\n邮箱：（邮箱已提供）'


def extraction_output(candidate):
    output = {'items': []}
    for span in explicit_subject_spans(candidate):
        body = candidate[span['start']:span['end']].split('】', 1)[-1]
        statements = re.split(r'[。；]', body)[1:]
        output['items'].append({'section': span['section'], 'name': span['name'],
                               'facts': [{'text': s, 'source_quote': s, 'kind': 'action'} for s in statements if s]})
    return output


def fixture():
    def row(item_id, name, texts):
        return {'item_id': item_id, 'name': name, 'facts': [new_fact(t) for t in texts]}
    collected = normalize_fact_store({
        'basic_info': {'name': '林知夏', 'phone': '1XX-XXXX-0000', 'email': 'linzhixia@example.invalid'},
        'projects': [row('p1', '拾光简历助手', [
            '负责访谈18名同学、整理需求', '离线测试中，同一组24个模拟任务的完成数从15个提高到20个',
            '这是课堂离线结果，项目未上线，没有真实用户增长或营收',
            '代码与模型接口主要由其他成员实现', '我是产品设计参与者，不是负责人']),
            row('p2', '校园问答RAG演示', [
                '用Python和Streamlit在本地搭建演示',
                '在120道自拟问题上，答案人工判定正确数由基础版本的71道提高到82道'])],
        'campus': [row('c1', 'AI学习社', ['协助2次分享会的报名与现场安排，不是社团负责人'])],
        'skills': [{'name': 'SQL只会SELECT、GROUP BY和LEFT JOIN等基础查询',
                    'source_quote': 'SQL只会SELECT、GROUP BY和LEFT JOIN等基础查询'}],
    })
    data = graph._serialize_to_resume_data({'collected_info': collected})
    return collected, data


class MixedInputTest(unittest.TestCase):
    def test_frozen_p1_separates_recruiter_from_all_personal_sections(self):
        candidate, jd = split_mixed_material(P1)
        self.assertIn('能做用户访谈', jd)
        self.assertIn('重视真实贡献和沟通', jd)
        self.assertNotIn('【基本信息】', jd)
        self.assertNotIn('林知夏', jd)
        self.assertNotIn('能做用户访谈', candidate)
        for section in ('基本信息', '教育', '项目一', '项目二', '校园活动', '技能'):
            self.assertIn('【' + section + '】', candidate)
        self.assertIn('直接成稿', candidate)
        self.assertIn('缺失信息直接省略', candidate)
        self.assertTrue(graph._candidate_source_allowed(HumanMessage(content=P1)))
        self.assertTrue(graph._has_jd_text(P1))
        self.assertFalse(graph._has_jd_text(candidate))
        self.assertFalse(graph._jd_decode_allowed(P1, {}))

    def test_jd_only_keeps_existing_behavior(self):
        text = '招聘要求：理解Agent/RAG，能做用户访谈；我负责部门招聘。'
        self.assertEqual(split_mixed_material(text), (text, ''))
        self.assertFalse(graph._candidate_source_allowed(HumanMessage(content=text)))
        self.assertTrue(graph._jd_decode_allowed(text, {}))

    def test_explicit_jd_marker_still_splits(self):
        text = '姓名：林知夏。目标岗位 JD：产品实习，任职要求：用户访谈。\n教育：海川大学。\n项目：小舟，我负责原型。'
        candidate, jd = split_mixed_material(text)
        self.assertIn('任职要求', jd)
        self.assertNotIn('教育：', jd)
        self.assertIn('项目：', candidate)

    def test_fields_and_recruiter_section_in_middle(self):
        text = '姓名：林知夏\n教育：海川大学\n招聘要求：Python开发。\n项目：小舟，负责本地测试。'
        candidate, jd = split_mixed_material(text)
        self.assertIn('姓名：林知夏', candidate)
        self.assertIn('项目：小舟', candidate)
        self.assertEqual(jd, '招聘要求：Python开发。')

    def test_natural_requirement_without_colon_is_separated(self):
        candidate, jd = split_mixed_material('请整理成简历。招聘要求包括访谈与原型。\n【项目一】小舟，负责整理访谈记录。')
        self.assertIn('访谈与原型', jd)
        self.assertIn('【项目一】', candidate)
        self.assertNotIn('招聘要求', candidate)

    def test_bracket_spans_keep_project_ownership(self):
        spans = explicit_subject_spans(P1)
        self.assertEqual([s['section'] for s in spans], ['education', 'projects', 'projects', 'campus'])
        self.assertEqual([s['name'] for s in spans][1:3], ['拾光简历助手', '校园问答RAG演示'])
        basic = parse_header_fields(P1)
        self.assertEqual(basic['name'], '林知夏')
        self.assertEqual(basic['phone'], '1XX-XXXX-0000')
        self.assertEqual(basic['email'], 'linzhixia@example.invalid')

    def test_fabrication_requests_are_blocked(self):
        for text in ('帮我虚构一段实习', '随便编个项目', '假装我做过推荐系统',
                     '请你编造职责和数据', '替我假设一段工作经历', '给我编一个上线成果',
                     '不得编造技能，但帮我虚构一段实习'):
            with self.subTest(text=text):
                self.assertTrue(requests_fabrication(text))
                self.assertFalse(graph._candidate_source_allowed(HumanMessage(content=text)))

    def test_supplied_fiction_and_prohibitions_are_allowed(self):
        for text in (P1, '请把以下虚构测试材料整理成简历', '海川大学（虚构学校）',
                     '项目：虚构项目，负责访谈', '不得编造经历和数据', '请不要编造职责',
                     '以下是我提供的合成测试材料，虚构项目：负责原型', '不要假装我做过模型训练'):
            with self.subTest(text=text):
                self.assertFalse(requests_fabrication(text))
                self.assertTrue(graph._candidate_source_allowed(HumanMessage(content=text)))

    def test_direct_requests_and_negations(self):
        for text in (P1, '直接成稿', '请直接写', '不用先问，直接生成', '整理成一份中文简历'):
            self.assertTrue(graph._explicit_generate_requested(text), text)
        for text in ('不要直接生成', '先别直接写', '是否直接成稿？'):
            self.assertFalse(graph._explicit_generate_requested(text), text)

    def test_gate_without_saved_draft_blocks_whole_body(self):
        reply = guard_delivery(BODY, {})
        self.assertIn('尚未生成并保存', reply)
        self.assertNotIn('18名', reply)
        self.assertNotIn('（邮箱已提供）', reply)

    def test_gate_with_committed_draft_delivers_single_workspace_copy(self):
        _, data = fixture()
        reply = guard_delivery(BODY, data, saved_this_turn=True)
        self.assertIn('草稿已放到右侧', reply)
        self.assertIn('PDF/Word', reply)
        self.assertNotIn('18名', reply)
        self.assertIn('尚未保存更新版', guard_delivery(BODY, data))

    def test_gate_preserves_bullet_analysis_without_resume_entries(self):
        self.assertFalse(presents_resume_body('\n'.join('- ' + '完成用户访谈与原型改版并核对结果' * 3 for _ in range(5))))
        self.assertEqual(guard_delivery('建议保留离线测试口径。', {}), '建议保留离线测试口径。')

    def test_gate_accepts_combined_markdown_heading_styles(self):
        for text in (BODY.replace('## ', '## **'), BODY.replace('## ', '【'), BODY.replace('## ', '[')):
            with self.subTest(text=text):
                self.assertTrue(presents_resume_body(text))
                self.assertNotIn('18名', guard_delivery(text, {}))

    def test_capability_claims_follow_document_state(self):
        _, data = fixture()
        for text in ('当前环境不支持生成或下载 PDF。', '我无法生成文件，请复制正文。', '不能提供可下载的Word文件。'):
            self.assertIn('成稿后', correct_export_claims(text, {}))
            self.assertNotIn('不支持', correct_export_claims(text, data))
            self.assertNotIn('成稿后', correct_export_claims(text, data))
            self.assertIn('右侧「写简历」', correct_export_claims(text, data))
        self.assertEqual(correct_export_claims('本轮未能完成 PDF 页数校验。', {}), '本轮未能完成 PDF 页数校验。')

    def test_export_login_notice_matches_endpoint_policy(self):
        from app.services.resume_delivery import export_capability
        with patch.object(get_settings(), 'APP_ENV', 'production'):
            self.assertIn('登录', export_capability({}))
        with patch.object(get_settings(), 'APP_ENV', 'local'), patch.object(get_settings(), 'REQUIRE_ACCOUNT', False):
            self.assertNotIn('登录', export_capability({}))

    def test_omit_missing_values_only_in_visible_content(self):
        result = omit_missing_placeholders({'basic_info': {'name': '林知夏', 'phone': '待补充'},
                                           'projects': [{'name': '项目（待补名称）', 'role': '待补充', 'polished_bullets': ['完成访谈', '待补充']}],
                                           'verification_notes': ['日期待补充']})
        self.assertEqual(result['basic_info']['phone'], '')
        self.assertEqual(result['projects'][0]['name'], '项目')
        self.assertEqual(result['projects'][0]['polished_bullets'], ['完成访谈'])
        self.assertEqual(result['verification_notes'], ['日期待补充'])

    def test_limits_return_to_correct_item_and_metric_bullet(self):
        collected, data = fixture()
        data['projects'][0]['polished_bullets'] = ['访谈18名同学', '24个任务完成数由15个提高到20个']
        data['projects'][1]['polished_bullets'] = ['用Python搭建演示', '120道问题正确数从71道提高到82道']
        result, meta, _ = preserve_item_limits(data, {}, collected, item_ids=['p1', 'p2', 'c1'])
        p1, p2 = result['projects']
        self.assertIn('代码与模型接口主要由其他成员实现', str(p1))
        self.assertIn('不是负责人', str(p1))
        for limit in ('离线', '课堂'):
            self.assertIn(limit, p1['polished_bullets'][1])
        self.assertIn('未上线', p1['role'])
        self.assertNotIn('未上线', str(p1['polished_bullets']))
        self.assertNotIn('不是负责人', p1['role'])
        self.assertNotIn('离线', p1['polished_bullets'][0])
        for limit in ('本地', '自拟', '人工判定'):
            self.assertIn(limit, p2['polished_bullets'][1])
        self.assertNotIn('其他成员', str(p2))
        report = ensure_fact_coverage(result, meta, collected)
        boundary = next(row for row in report['facts'] if '其他成员' in row['text'])
        self.assertEqual(boundary['status'], 'covered')
        again, _, _ = preserve_item_limits(result, meta, collected, item_ids=['p1', 'p2', 'c1'])
        self.assertEqual(again, result)

    def test_supervisor_approval_and_hidden_items(self):
        collected = {'work_experience': [{'item_id': 'w', 'company': '店铺',
                     'facts': [new_fact('处理退款申请'), new_fact('退款由主管审批')]}]}
        data = {'work_experience': [{'item_id': 'w', 'company': '店铺', 'bullets': ['处理退款申请']}]}
        result, meta, _ = preserve_item_limits(data, {}, collected, item_ids=['w'])
        self.assertNotIn('退款由主管审批', result['work_experience'][0].get('title', ''))
        self.assertIn('退款由主管审批', '\n'.join(result['work_experience'][0]['bullets']))
        report = ensure_fact_coverage(result, meta, collected)
        self.assertTrue(all(row['status'] == 'covered' for row in report['facts']))
        data['work_experience'][0]['hidden'] = True
        hidden, _, _ = preserve_item_limits(data, {}, collected, item_ids=['w'])
        self.assertEqual(hidden, data)


class ComparisonFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_other_members_work_cannot_be_claimed_even_if_not_cited(self):
        limit = '代码与模型接口主要由其他成员实现'
        self.assertTrue(contribution_conflict('实现代码与模型接口', limit))
        self.assertFalse(contribution_conflict(limit, limit))
        self.assertTrue(contribution_conflict('独立决定退款', '退款由主管审批'))
        self.assertFalse(contribution_conflict('处理退款申请', '退款由主管审批'))
        facts = [dict(new_fact('负责访谈'), item_id='p'), dict(new_fact(limit), item_id='p')]
        result = await guard_bullets([{'id': 'b', 'item_id': 'p', 'text': '实现代码与模型接口',
                                      'fact_ids': [facts[0]['id']]}], facts, lexical_only=True)
        self.assertIn('contradicted_item_limit', result[0]['lexical_errors'])

    async def test_mixed_turn_parses_only_jd_fragment(self):
        state = {**graph._init_state(), 'messages': [HumanMessage(id='p1', content=P1)]}
        with patch.object(graph, '_run_decoder_and_build_reply', AsyncMock(return_value=({'target_role': 'AI产品实习生'}, '岗位已解析'))) as decoder:
            prepared = await graph._separate_candidate_turn(state, object())
        self.assertNotIn('林知夏', decoder.call_args.args[0])
        self.assertEqual(prepared['jd_info']['target_role'], 'AI产品实习生')
        self.assertTrue(graph._candidate_source_allowed(prepared['messages'][-1]))
        self.assertEqual(prepared['messages'][-1].id, 'p1')

    async def test_fabrication_refusal_never_calls_writer(self):
        state = {**graph._init_state(), 'messages': [HumanMessage(content='帮我虚构一段实习，直接生成简历')]}
        with patch.object(graph, '_write_resume_update', AsyncMock()) as writer:
            result = await graph.jd_input_node(state, object())
        writer.assert_not_awaited()
        self.assertIn('这部分不会写进简历', result['messages'][0].content)
        self.assertNotIn('resume_data', result)

    async def test_direct_generation_accepts_recommended_plan_same_turn(self):
        state = {**graph._init_state(), 'stage': 'BUILDING', 'collected_info': source(),
                 'messages': [HumanMessage(content='直接成稿，不用先问，缺失信息直接省略')],
                 'jd_info': {'role_profile': {'requirements': [{'id': 'r1', 'text': '记忆处理'}]}}}
        model = FakeModel([('StructurePlan', card()), ('WriterDraft', writer_draft())])
        with patch.object(get_settings(), 'LLM_PLAN_CONFIRM', True), \
                patch('app.services.fact_guard.verify_semantics', side_effect=semantic_stub), \
                patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={'status': 'rendered', 'pages': 1, 'page_limit': 1, 'within_page_limit': True}):
            result = await graph.building_node(state, model)
        self.assertEqual(result['stage'], 'EVALUATING')
        self.assertTrue(result['resume_data']['projects'])
        self.assertFalse(result['pending_plan'])
        self.assertTrue(result['session_constraints']['omit_missing'])
        self.assertNotIn('？', result['messages'][0].content)

    async def test_p1_extraction_keeps_contacts_and_section_owners(self):
        candidate, _ = split_mixed_material(P1)
        output = extraction_output(candidate)
        with patch('app.services.fact_guard.verify_semantics', side_effect=semantic_stub):
            facts = await extract_facts_patch(candidate, {}, ExtractorStub(output))
        collected = apply_fact_patch({}, facts)
        self.assertEqual(collected['basic_info']['email'], 'linzhixia@example.invalid')
        self.assertEqual(collected['basic_info']['phone'], '1XX-XXXX-0000')
        self.assertEqual(len(collected['projects']), 2)
        self.assertTrue(collected['campus'])
        self.assertNotIn('能做用户访谈', str(collected))

    async def test_frozen_three_turn_graph_sql_and_workspace_share_one_draft(self):
        from app.database import Base
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.services.session_store import load_resume_session
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix='huhua-batch11-'))
        engine = create_engine('sqlite:///' + str(Path(directory) / 'test.sqlite3'), connect_args={'check_same_thread': False})
        self.addCleanup(engine.dispose)
        factory = sessionmaker(bind=engine)
        self.enterContext(patch('app.services.session_store.SessionLocal', factory))
        self.enterContext(patch('app.services.conversation_store.SessionLocal', factory))
        Base.metadata.create_all(bind=engine)
        sid = 'batch11-' + uuid4().hex
        model = EchoWriter()
        compiled = graph.build_graph(model)
        candidate, _ = split_mixed_material(P1)
        with patch.object(graph, 'get_graph', return_value=compiled), \
                patch.object(get_settings(), 'LLM_PLAN_CONFIRM', True), \
                patch.object(graph, '_make_non_streaming_llm', return_value=ExtractorStub(extraction_output(candidate))), \
                patch.object(graph, '_run_decoder_and_build_reply', AsyncMock(return_value=({'target_role': 'AI产品实习生'}, '已解析'))), \
                patch('app.services.fact_guard.verify_semantics', side_effect=semantic_stub), \
                patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={'status': 'rendered', 'pages': 1, 'page_limit': 1, 'within_page_limit': True}), \
                patch('app.services.resume_capacity.measure_rendered_pages', return_value={'status': 'rendered', 'pages': 1, 'page_limit': 1, 'within_page_limit': True}):
            for index, prompt in enumerate((P1, P2, P3)):
                reply = ''.join([chunk async for chunk in graph.stream_agent([{'content': prompt}], sid, model)])
                stored = load_resume_session(sid)
                self.assertEqual(stored['stage'], 'EVALUATING', reply)
                self.assertTrue(stored['resume_data']['projects'])
                self.assertEqual(stored['resume_data']['basic_info']['email'], 'linzhixia@example.invalid')
                self.assertEqual(stored['resume_data']['basic_info']['phone'], '1XX-XXXX-0000')
                self.assertNotIn('（邮箱已提供）', reply)
                rendered = resume_to_text(stored['resume_data'])
                self.assertIn('代码与模型接口主要由其他成员实现', rendered)
                self.assertNotIn('待补', rendered)
                if index:
                    self.assertIn('12名', rendered, reply)
                    self.assertNotIn('18名', rendered)
                    self.assertNotIn('AI学习社', rendered)
                    self.assertIn('SQL仅基础查询', rendered)
                snapshot = await compiled.aget_state({'configurable': {'thread_id': sid}})
                self.assertEqual(snapshot.values['resume_data'], stored['resume_data'])

    async def test_compound_p2_corrects_removes_and_limits_then_p3_keeps_it(self):
        collected, data = fixture()
        state = {**graph._init_state(), 'collected_info': collected, 'resume_data': data,
                 'candidate_history_reconciled': True, 'messages': [HumanMessage(content=P2)]}
        self.assertEqual(graph.route_by_stage(state), 'evaluating')
        with patch('app.services.resume_capacity.measure_rendered_pages', return_value={'status': 'rendered', 'pages': 1}), \
                patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={'status': 'rendered', 'pages': 1}):
            result = await graph.evaluating_node(state, object())
            rendered = resume_to_text(result['resume_data'])
            self.assertIn('12名', rendered)
            self.assertNotIn('18名', rendered)
            self.assertNotIn('AI学习社', rendered)
            self.assertIn('SQL仅基础查询', rendered)
            self.assertEqual(result['resume_data']['basic_info'], data['basic_info'])
            final_state = {**state, **result, 'messages': [HumanMessage(content=P3)]}
            final = await graph.evaluating_node(final_state, object())
        self.assertNotIn('AI学习社', resume_to_text(final['resume_data']))
        self.assertIn('12名', resume_to_text(final['resume_data']))
        self.assertIn('SQL仅基础查询', resume_to_text(final['resume_data']))
        self.assertIn('右侧', final['messages'][0].content)

    async def test_stream_gate_buffers_uncommitted_body_and_repairs_history(self):
        values = {**graph._init_state(), 'messages': [AIMessage(id='reply', content=BODY)]}
        async def events(*args, **kwargs):
            for text in ('# 林知夏\n', BODY.split('\n', 1)[1]):
                yield 'custom', {'type': 'public_reply_delta', 'node': 'collecting', 'reply_id': 'reply', 'content': text}
            yield 'updates', {'collecting': {'messages': values['messages']}}
        fake = SimpleNamespace(astream=events, aget_state=AsyncMock(return_value=SimpleNamespace(values=values)), aupdate_state=AsyncMock())
        with patch.object(graph, 'get_graph', return_value=fake), \
                patch('app.services.session_store.save_resume_session', return_value={'resume_data': {}, 'resume_meta': {}}), \
                patch('app.services.conversation_store.update_conversation_title'):
            chunks = [s async for s in graph.stream_agent([{'content': '请交付完整简历正文'}], 'batch11-gate', object())]
        reply = ''.join(chunks)
        self.assertNotIn('18名', reply)
        self.assertNotIn('邮箱已提供', reply)
        self.assertIn('尚未生成并保存', reply)
        self.assertTrue(any('messages' in call.args[1] for call in fake.aupdate_state.call_args_list))

    async def test_writer_reattaches_omitted_contribution_limit(self):
        collected, data = fixture()
        with patch('app.services.fact_guard.verify_semantics', side_effect=semantic_stub):
            result = await run_resume_writer(collected, {}, EchoWriter(), current_data=data)
        self.assertIn('代码与模型接口主要由其他成员实现', str(result['resume_data']))
        self.assertNotIn('输出需求清单', str(result['resume_data']))
        workspace = build_workspace({**graph._init_state(), **result, 'collected_info': collected})
        self.assertTrue(workspace)


# Public replay P1: plan and coverage facts, with erroneous extracted roles.
REPLAY_PLAN = {'bullet_style': 'plain',
 'requirements': [{'req_id': 'r1',
                   'status': 'direct',
                   'fact_ids': ['f_b3c7affb47e6441facd9dbbc192ce29c'],
                   'angle': '访谈 18 名同学并整理需求，直接对应「能做用户访谈」'},
                  {'req_id': 'r2',
                   'status': 'direct',
                   'fact_ids': ['f_b3c7affb47e6441facd9dbbc192ce29c', 'f_3598be38b62c4767ae8f1e60a508a80f'],
                   'angle': '从访谈整理需求并落到录入与修改流程原型，体现需求拆解到方案'},
                  {'req_id': 'r3',
                   'status': 'direct',
                   'fact_ids': ['f_3598be38b62c4767ae8f1e60a508a80f', 'f_27f0828ae2d5415684868f54a04c67b8'],
                   'angle': '绘制流程原型，并参与 8 名同学可用性测试后据反馈改版'},
                  {'req_id': 'r4',
                   'status': 'transferable',
                   'fact_ids': ['f_22c416fe166a45e192b108976d2f97ab',
                                'f_13dbc6896bf842848bd91584675048d4',
                                'f_dbeff9412f4241c5af8a22911be70a36'],
                   'angle': '没有正式数据分析岗经历，用「维护评测表 + 统计模拟任务完成数/人工判定正确数」的对比口径迁移表达基础数据分析'},
                  {'req_id': 'r5',
                   'status': 'direct',
                   'fact_ids': ['f_afbb5750674b461a814b9a520c07705b',
                                'f_dbeff9412f4241c5af8a22911be70a36',
                                'f_13dbc6896bf842848bd91584675048d4'],
                   'angle': '本地搭建 RAG 问答演示 + 维护评测表 + 自拟问题集对比，直接对应 Agent/RAG 理解与参与评测'},
                  {'req_id': 'r6',
                   'status': 'direct',
                   'fact_ids': ['f_0126cab9d18043b5865abc830d3e7fb3',
                                'f_2708201ad73b455eac552ff437b9f9dc',
                                'f_0c4d33ff2104485abe8b48c76fc9da9c',
                                'f_1b55e56409434003a02288b64783e5fd'],
                   'angle': '标题行与 bullet 保留「产品设计参与者」「参与者」「代码与模型接口主要由其他成员实现」等边界，体现真实贡献与沟通'}],
 'experience_plan': [{'item_id': '077d5e01-3ee7-4a59-82c2-ceed80b7d60d',
                      'treatment': 'lead',
                      'reason': '直接命中 JD 的「能做用户访谈」「需求拆解」「原型」三条硬要求：访谈 18 名同学、整理需求、绘制录入与修改流程原型，并有 8 人可用性测试与改版、24 '
                                '个模拟任务完成数 15→20 的离线结果，是这份简历最前排的证据。',
                      'target_bullets': 3},
                     {'item_id': '23ba07fe-326f-4a51-b5cb-65d48db5ff4b',
                      'treatment': 'lead',
                      'reason': '直接命中 JD 的「理解 Agent/RAG 并参与评测」：本地搭建 RAG 问答演示、整理问答材料并维护评测表、120 道自拟问题上人工判定正确数 '
                                '71→82，是学生简历里少见的评测意识证据。',
                      'target_bullets': 3},
                     {'item_id': '8344ec72-fb48-4d5c-b2b1-c9be5de8b91e',
                      'treatment': 'brief',
                      'reason': '与 AI 产品岗核心职责弱相关，但能体现 JD 提到的沟通与协作：协助 2 次分享会的报名与现场安排，一条带过即可。',
                      'target_bullets': 1}],
 'section_order': ['education',
                   'projects',
                   'campus',
                   'skills',
                   'work_experience',
                   'open_source',
                   'awards',
                   'certificates']}
REPLAY_SOURCE = {'basic_info': {'name': '林知夏',
                'phone': '1XX-XXXX-0000',
                'email': 'linzhixia@example.invalid',
                'location': '深圳',
                'objective': 'AI产品实习生（Agent方向）',
                'gender': '',
                'age': '',
                'birthday': '',
                'hometown': '',
                'political': '',
                'ethnicity': '',
                'height': '',
                'links': [],
                'availability': '可每周实习4天、连续3个月'},
 'skills': [{'name': 'Python能参考文档写简单脚本', 'source_quote': 'Python能参考文档写简单脚本'},
            {'name': 'SQL仅基础查询', 'source_quote': 'SQL仅基础查询'},
            {'name': 'Figma能画基础流程和低保真原型', 'source_quote': 'Figma能画基础流程和低保真原型'},
            {'name': '了解Agent工具调用与RAG基本流程', 'source_quote': '了解Agent工具调用与RAG基本流程'}],
 'projects': [{'item_id': '077d5e01-3ee7-4a59-82c2-ceed80b7d60d',
               'name': '拾光简历助手',
               'facts': [{'id': 'f_d02ad675838c4fa4969a41fc96478c10',
                          'text': '拾光简历助手',
                          'source_quote': '拾光简历助手',
                          'kind': 'context',
                          'status': 'active',
                          'field': 'name'},
                         {'id': 'f_0da12ac2b0c045a485b4c28ce087fb63',
                          'text': '4人课程项目',
                          'source_quote': '4人课程项目',
                          'kind': 'scope_scale',
                          'status': 'active'},
                         {'id': 'f_0126cab9d18043b5865abc830d3e7fb3',
                          'text': '我是产品设计参与者',
                          'source_quote': '我是产品设计参与者',
                          'kind': 'role',
                          'status': 'active'},
                         {'id': 'f_6d50dd4d806348ccab99c687a38aa661',
                          'text': '也没有管理团队',
                          'source_quote': '也没有管理团队',
                          'kind': 'action',
                          'status': 'active'},
                         {'id': 'f_b3c7affb47e6441facd9dbbc192ce29c',
                          'text': '负责访谈18名同学、整理需求',
                          'source_quote': '负责访谈18名同学、整理需求',
                          'kind': 'action',
                          'status': 'active'},
                         {'id': 'f_3598be38b62c4767ae8f1e60a508a80f',
                          'text': '绘制简历素材录入与修改流程原型',
                          'source_quote': '绘制简历素材录入与修改流程原型',
                          'kind': 'action',
                          'status': 'active'},
                         {'id': 'f_27f0828ae2d5415684868f54a04c67b8',
                          'text': '参与8名同学的可用性测试并据反馈改版',
                          'source_quote': '参与8名同学的可用性测试并据反馈改版',
                          'kind': 'action',
                          'status': 'active'},
                         {'id': 'f_22c416fe166a45e192b108976d2f97ab',
                          'text': '离线测试中，同一组24个模拟任务的完成数从15个提高到20个',
                          'source_quote': '离线测试中，同一组24个模拟任务的完成数从15个提高到20个',
                          'kind': 'result_metric',
                          'status': 'active'},
                         {'id': 'f_0c27b93555e740909f4d6ffc60599ffb',
                          'text': '这是课堂离线结果，项目未上线，没有真实用户增长或营收',
                          'source_quote': '这是课堂离线结果，项目未上线，没有真实用户增长或营收',
                          'kind': 'action',
                          'status': 'active'},
                         {'id': 'f_0c4d33ff2104485abe8b48c76fc9da9c',
                          'text': '代码与模型接口主要由其他成员实现',
                          'source_quote': '代码与模型接口主要由其他成员实现',
                          'kind': 'action',
                          'status': 'active'},
                         {'id': 'f_f441b7cc5ca8443fbef7ebc4983b2946',
                          'text': '2026.06',
                          'source_quote': '2026.06',
                          'kind': 'context',
                          'status': 'active',
                          'field': 'start_date'},
                         {'id': 'f_b0d5c28582dc48388fbcc33cfcc109f7',
                          'text': '2026.09',
                          'source_quote': '2026.09',
                          'kind': 'context',
                          'status': 'active',
                          'field': 'end_date'},
                         {'id': 'f_2708201ad73b455eac552ff437b9f9dc',
                          'text': '不是负责人',
                          'source_quote': '不是负责人',
                          'field': 'role',
                          'kind': 'role'}]},
              {'item_id': '23ba07fe-326f-4a51-b5cb-65d48db5ff4b',
               'name': '校园问答RAG演示',
               'facts': [{'id': 'f_40f6436417db4fd1a6ad4a693a85a638',
                          'text': '校园问答RAG演示',
                          'source_quote': '校园问答RAG演示',
                          'kind': 'context',
                          'status': 'active',
                          'field': 'name'},
                         {'id': 'f_250114ac117e44d58488f3da7c05957f',
                          'text': '2人课程项目',
                          'source_quote': '2人课程项目',
                          'kind': 'scope_scale',
                          'status': 'active'},
                         {'id': 'f_1b55e56409434003a02288b64783e5fd',
                          'text': '参与者',
                          'source_quote': '参与者',
                          'kind': 'role',
                          'status': 'active'},
                         {'id': 'f_afbb5750674b461a814b9a520c07705b',
                          'text': '用Python和Streamlit在本地搭建演示',
                          'source_quote': '用Python和Streamlit在本地搭建演示',
                          'kind': 'action',
                          'status': 'active'},
                         {'id': 'f_dbeff9412f4241c5af8a22911be70a36',
                          'text': '整理问答材料并维护评测表',
                          'source_quote': '整理问答材料并维护评测表',
                          'kind': 'action',
                          'status': 'active'},
                         {'id': 'f_13dbc6896bf842848bd91584675048d4',
                          'text': '在120道自拟问题上，答案人工判定正确数由基础版本的71道提高到82道',
                          'source_quote': '在120道自拟问题上，答案人工判定正确数由基础版本的71道提高到82道',
                          'kind': 'result_metric',
                          'status': 'active'},
                         {'id': 'f_ff8190c0a7b8431a96acfd6dd136f72c',
                          'text': '没有线上测试、生产部署或并发性能数据',
                          'source_quote': '没有线上测试、生产部署或并发性能数据',
                          'kind': 'action',
                          'status': 'active'},
                         {'id': 'f_d9c9f367f0854e759f0e235e9597dd0d',
                          'text': '2026.03',
                          'source_quote': '2026.03',
                          'kind': 'context',
                          'status': 'active',
                          'field': 'start_date'},
                         {'id': 'f_fb1206b2ec6f47c2a224b5abc5f299a7',
                          'text': '2026.05',
                          'source_quote': '2026.05',
                          'kind': 'context',
                          'status': 'active',
                          'field': 'end_date'}]}],
 'campus': [{'item_id': '8344ec72-fb48-4d5c-b2b1-c9be5de8b91e',
             'name': 'AI学习社活动志愿者',
             'facts': [{'id': 'f_f08a7b3430474ec6ab9a613d3a03470b',
                        'text': 'AI学习社活动志愿者',
                        'source_quote': 'AI学习社活动志愿者',
                        'kind': 'context',
                        'status': 'active',
                        'field': 'name'},
                       {'id': 'f_ac33da14c08e49b3920c9ac027934502',
                        'text': '活动志愿者',
                        'source_quote': '活动志愿者',
                        'kind': 'role',
                        'status': 'active'},
                       {'id': 'f_175c3fb7f6424aacbed52d2689b2b32c',
                        'text': '协助2次分享会的报名与现场安排',
                        'source_quote': '协助2次分享会的报名与现场安排',
                        'kind': 'action',
                        'status': 'active'},
                       {'id': 'f_b781b4a1ed364b0e88213d5318f0f69c',
                        'text': '2025.10',
                        'source_quote': '2025.10',
                        'kind': 'context',
                        'status': 'active',
                        'field': 'start_date'},
                       {'id': 'f_5518294920aa4305940fe0b6f8b46e62',
                        'text': '2026.01',
                        'source_quote': '2026.01',
                        'kind': 'context',
                        'status': 'active',
                        'field': 'end_date'},
                       {'id': 'f_negative_campus',
                        'text': '不是社团负责人',
                        'source_quote': '不是社团负责人',
                        'field': 'role',
                        'kind': 'role'}]}],
 'education': [{'item_id': 'c959a72a-c2e4-40e7-a851-3f6f7dff3864',
                'school': '海川理工大学',
                'facts': [{'id': 'f_eca3a93273ab4d91a5968dd322ca61a8',
                           'text': '海川理工大学',
                           'source_quote': '海川理工大学',
                           'kind': 'context',
                           'status': 'active',
                           'field': 'school'},
                          {'id': 'f_0a2fcaee7fa64420ae55fc8441d0f932',
                           'text': '计算机科学与技术',
                           'source_quote': '计算机科学与技术',
                           'kind': 'context',
                           'status': 'active',
                           'field': 'major'},
                          {'id': 'f_554d91891f064953a3425c4fdee7260f',
                           'text': '本科',
                           'source_quote': '本科',
                           'kind': 'context',
                           'status': 'active',
                           'field': 'degree'},
                          {'id': 'f_8be43d9a64c64b93a34a00e3cb1ca958',
                           'text': '未提供绩点、排名和奖学金',
                           'source_quote': '未提供绩点、排名和奖学金',
                           'kind': 'context',
                           'status': 'active',
                           'field': 'highlights'},
                          {'id': 'f_f3da9511e7e84c448d94d835efb0fb3d',
                           'text': '2023.09',
                           'source_quote': '2023.09',
                           'kind': 'context',
                           'status': 'active',
                           'field': 'start_date'},
                          {'id': 'f_c37b21307a0c415299f74f6525240326',
                           'text': '2027.06',
                           'source_quote': '2027.06',
                           'kind': 'context',
                           'status': 'active',
                           'field': 'end_date'}]}]}


class ReplayWriter:
    """Deliberately omit the interview, even when the writer is asked to repair."""
    def __init__(self, *, interview=False):
        self.interview = interview

    def with_structured_output(self, schema):
        return SimpleNamespace(ainvoke=lambda messages: self.invoke(schema, messages))

    async def invoke(self, schema, messages):
        if 'RepairOutput' in schema.__name__:
            return {'bullets': []}
        items = []
        for section in ('projects', 'campus'):
            for item in REPLAY_SOURCE[section]:
                facts = item['facts']
                def bullet(text, *words):
                    return {'text': text, 'fact_ids': [next(f['id'] for f in facts if word in f['text']) for word in words]}
                if '拾光' in item['name']:
                    bullets = [
                        bullet('绘制简历素材录入与修改流程原型，参与8名同学的可用性测试并据反馈改版', '绘制', '可用性'),
                        bullet('课堂离线测试中，同一组24个模拟任务的完成数由15个提升至20个（代码与模型接口主要由其他成员实现）', '完成数', '代码与模型接口')]
                    if self.interview:
                        bullets.insert(0, bullet('访谈18名同学、整理需求', '访谈'))
                elif section == 'projects':
                    bullets = [bullet('用Python和Streamlit在本地搭建演示，整理问答材料并维护评测表', '本地', '评测表'),
                               bullet('在120道自拟问题上对比基础版本，答案人工判定正确数由71道提高到82道', '120道')]
                else:
                    bullets = [bullet('协助2次分享会的报名与现场安排', '协助2次')]
                items.append({'item_id': item['item_id'], 'section': section, 'bullets': bullets})
        return {'items': items, 'skill_groups': {'工具': ['Figma'], '开发': ['Python', 'SQL']}}


class Batch11bQualityTest(unittest.IsolatedAsyncioTestCase):
    async def write_replay(self, *, interview=False):
        source = deepcopy(REPLAY_SOURCE)
        current = graph._serialize_to_resume_data({'collected_info': source})
        profile = {'requirements': [{'id': r['req_id'], 'text': r['angle']} for r in REPLAY_PLAN['requirements']]}
        with patch('app.services.fact_guard.verify_semantics', side_effect=semantic_stub):
            result = await run_resume_writer(source, profile, ReplayWriter(interview=interview),
                current_data=current, previous_plan=REPLAY_PLAN, phase='write',
                constraints={'omit_missing': True}, instruction='直接成稿')
        return source, result

    async def test_confirmed_replay_plan_repairs_missing_interview_in_rendered_body(self):
        for interview in (False, True):
            with self.subTest(writer_included_interview=interview):
                _, result = await self.write_replay(interview=interview)
                body = result['resume_data']['projects'][0]['polished_bullets']
                self.assertEqual(len(body), 3)
                self.assertIn('访谈18名同学', resume_to_text(result['resume_data']))
                self.assertEqual(result['match_plan']['experience_plan'][0]['target_bullets'], 3)
                row = next(f for f in result['resume_meta']['fact_coverage']['facts'] if f['fact_id'] == 'f_b3c7affb47e6441facd9dbbc192ce29c')
                self.assertEqual(row['status'], 'covered')

    async def test_replay_render_has_positive_roles_and_natural_limits(self):
        _, result = await self.write_replay()
        data = result['resume_data']
        text = resume_to_text(data)
        self.assertIn('产品设计参与者', data['projects'][0]['role'])
        self.assertIn('参与者', data['projects'][1]['role'])
        self.assertEqual('活动志愿者', data['campus'][0]['role'])
        for item in [*data['projects'], *data['campus']]:
            self.assertNotRegex(item['role'], '不是|没有|并非')
        first, second = data['projects']
        self.assertIn('4人课程项目', first['role'])
        self.assertIn('未上线', first['role'])
        self.assertIn('2人课程项目', second['role'])
        self.assertNotIn('代码与模型接口主要由其他成员实现', first['role'])
        self.assertIn('代码与模型接口主要由其他成员实现', '\n'.join(first['polished_bullets']))
        for item in data['projects']:
            body = '\n'.join(item['polished_bullets'])
            self.assertNotRegex(body, '人课程项目|未上线|没有|不是|，(?:离线|课堂|本地)(?:，|$)')
        metric = next(b for b in first['polished_bullets'] if '完成数' in b)
        self.assertNotIn('其他成员', metric)
        for word in ('完成数', '24', '15', '20', '课堂', '离线'):
            self.assertEqual(metric.count(word), 1, metric)
        metric = next(b for b in second['polished_bullets'] if '正确数' in b)
        for word in ('120', '71', '82', '自拟', '人工判定'):
            self.assertEqual(metric.count(word), 1, metric)
        self.assertNotIn('未提供', text)
        self.assertIn('Figma能画基础流程和低保真原型', text)
        self.assertIn('了解Agent工具调用与RAG基本流程', text)

    async def test_replay_p2_corrects_rendered_interview_and_sql_writeback(self):
        from app.database import Base
        from app.services.session_store import save_resume_session, load_resume_session
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        source, result = await self.write_replay()
        state = {**graph._init_state(), **result, 'collected_info': source, 'candidate_history_reconciled': True,
                 'messages': [HumanMessage(content=P2)]}
        with patch('app.services.resume_capacity.measure_rendered_pages', return_value={'status': 'rendered', 'pages': 1}), \
                patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={'status': 'rendered', 'pages': 1}):
            updated = await graph.evaluating_node(state, object())
            with tempfile.TemporaryDirectory(prefix='huhua-b11b-') as directory:
                engine = create_engine('sqlite:///' + str(Path(directory) / 'test.db'))
                try:
                    Base.metadata.create_all(engine)
                    with patch('app.services.session_store.SessionLocal', sessionmaker(bind=engine)):
                        save_resume_session('replay-b11b', updated['resume_data'], stage='EVALUATING',
                                            collected_info=updated['collected_info'], resume_meta=updated['resume_meta'])
                        stored = load_resume_session('replay-b11b')
                finally:
                    engine.dispose()
        rendered = resume_to_text(stored['resume_data'])
        self.assertIn('访谈12名同学', rendered)
        self.assertNotIn('18名', rendered)
        self.assertNotIn('AI学习社', rendered)
        self.assertIn('SQL仅基础查询', rendered)
        self.assertIn('Figma能画基础流程和低保真原型', rendered)
        self.assertIn('了解Agent工具调用与RAG基本流程', rendered)

    async def test_intake_restores_full_skill_declarations_from_sparse_model(self):
        candidate, _ = split_mixed_material(P1)
        output = extraction_output(candidate)
        output['skills'] = ['Python', 'Figma', 'SQL']
        with patch('app.services.fact_guard.verify_semantics', side_effect=semantic_stub):
            collected = apply_fact_patch({}, await extract_facts_patch(candidate, {}, ExtractorStub(output)))
        names = [s['name'] for s in collected['skills']]
        self.assertIn('Figma能画基础流程和低保真原型', names)
        self.assertIn('Python能参考文档写简单脚本', names)
        self.assertIn('了解Agent工具调用与RAG基本流程', names)
        self.assertNotIn('Figma', names)
        self.assertNotIn('没有模型训练经验', str(names))
        self.assertNotIn('未提供', resume_to_text(graph._serialize_to_resume_data({'collected_info': collected})))

    def test_numeric_repair_does_not_replace_interview_with_team_scale(self):
        from app.agents.resume_writer import _numeric_fact, _missing_metric_facts, _append_metric_bullets
        from app.schemas.writer import WrittenItem
        source = REPLAY_SOURCE['projects'][0]
        facts = {f['id']: f for f in source['facts']}
        self.assertFalse(_numeric_fact(next(f for f in facts.values() if f['text'] == '4人课程项目')))
        self.assertTrue(_numeric_fact(facts['f_b3c7affb47e6441facd9dbbc192ce29c']))
        item = WrittenItem(item_id=source['item_id'], section='projects', bullets=[
            {'text': '访谈18名同学、整理需求', 'fact_ids': ['f_b3c7affb47e6441facd9dbbc192ce29c']},
            {'text': '参与8名同学的可用性测试并据反馈改版', 'fact_ids': ['f_27f0828ae2d5415684868f54a04c67b8']},
            {'text': '课堂离线测试中，同一组24个模拟任务的完成数由15个提升至20个', 'fact_ids': ['f_22c416fe166a45e192b108976d2f97ab']}])
        writers, items, caps = {item.item_id: item}, {item.item_id: ('projects', source)}, {item.item_id: 3}
        missing = _missing_metric_facts(writers, items, {item.item_id: 'lead'}, caps)
        self.assertEqual(missing, {})
        _append_metric_bullets(writers, items, missing, caps)
        self.assertIn('访谈18名同学', str(item.bullets))

    def test_metric_equivalence_keeps_objects_and_direction(self):
        from app.services.fact_coverage import text_covered
        source = '同一组24个模拟任务的完成数从15个提高到20个'
        self.assertTrue(text_covered(source, ['同一组 24 个模拟任务的完成数由 15 个提升至 20 个']))
        self.assertFalse(text_covered(source, ['同一组24个模拟任务的完成数由20个提升至15个']))
        self.assertFalse(text_covered(source, ['同一组24个模拟任务的失败数由15个提升至20个']))

    def test_education_notes_removed_without_dropping_actual_honors(self):
        from app.services.education_fields import clean_education_item
        item = clean_education_item({'highlights': '未提供绩点、排名和奖学金。获得校级三等奖。'})
        self.assertEqual(item['highlights'], '获得校级三等奖。')

    async def test_non_lead_role_allows_sourced_responsibility_but_blocks_promotion(self):
        from app.services.fact_guard import contradicts_limit
        facts = [dict(new_fact('负责访谈18名同学、整理需求'), item_id='p'),
                 dict(new_fact('不是负责人'), item_id='p')]
        rows = await guard_bullets([{'id': 'b', 'item_id': 'p', 'text': facts[0]['text'],
                                    'fact_ids': [facts[0]['id']]}], facts, lexical_only=True)
        self.assertEqual(rows[0]['verdict'], 'pass', rows)
        for claim in ('项目负责人', '管理团队', '负责整个项目'):
            self.assertTrue(contradicts_limit(claim, '不是负责人，也没有管理团队'))
        for denied, claim in (('没有真实用户增长或营收', '实现营收'),
                              ('没有线上测试、生产部署或并发性能数据', '完成线上测试'),
                              ('没有线上测试、生产部署或并发性能数据', '部署到生产'),
                              ('没有线上测试、生产部署或并发性能数据', '支撑1000并发')):
            self.assertTrue(contradicts_limit(claim, denied), claim)

    def test_dirty_metric_tail_cleaned_once_and_provenance_stays_aligned(self):
        from app.services.resume_versions import text_hash
        source = deepcopy(REPLAY_SOURCE)
        data = graph._serialize_to_resume_data({'collected_info': source})
        project = data['projects'][0]
        project['polished_bullets'] = [
            '负责访谈18名同学、整理需求',
            '课堂离线测试中，同一组24个模拟任务的完成数由15个提升至20个（代码与模型接口主要由其他成员实现），同一组24个模拟任务的完成数从15个提高到20个，4人课程项目，离线，课堂，项目未上线，没有真实用户增长或营收']
        data, meta, _ = preserve_item_limits(data, {}, source, item_ids=[project['item_id']])
        metric = data['projects'][0]['polished_bullets'][1]
        for token in ('完成数', '24', '15', '20', '课堂', '离线'):
            self.assertEqual(metric.count(token), 1, metric)
        self.assertNotRegex(metric, '其他成员|没有|未上线|4人|，离线|，课堂')
        again, meta2, _ = preserve_item_limits(data, meta, source, item_ids=[project['item_id']])
        self.assertEqual(again, data)
        for text, record in zip(again['projects'][0]['polished_bullets'], meta2.get('bullets', {}).get(project['item_id'], [])):
            self.assertEqual(record['text_hash'], text_hash(text))

    def test_live_correction_survives_history_filter_but_old_text_cannot(self):
        from app.services.profile_bridge import sanitize_fact_history
        old = {**new_fact('负责访谈18名同学、整理需求'), 'status': 'superseded'}
        new = {**new_fact('负责访谈12名同学、整理需求'), 'replaces': old['id']}
        data = {'collected_info': {'projects': [{'item_id': 'p', 'facts': [old, new]}]},
                'resume_data': {'projects': [{'item_id': 'p', 'polished_bullets': [new['text'], old['text']]}]}}
        result = sanitize_fact_history(data)
        self.assertEqual(result['resume_data']['projects'][0]['polished_bullets'], [new['text']])

    async def test_confirmed_plan_repairs_selected_non_numeric_fact_before_other_work(self):
        source = deepcopy(REPLAY_SOURCE)
        project = source['projects'][0]
        interview = next(f for f in project['facts'] if '访谈' in f['text'])
        interview['text'] = interview['source_quote'] = '整理用户访谈记录与需求'
        project['facts'].insert(0, new_fact('整理项目文件目录', kind='action'))
        profile = {'requirements': [{'id': row['req_id'], 'text': row['angle']} for row in REPLAY_PLAN['requirements']]}
        with patch('app.services.fact_guard.verify_semantics', side_effect=semantic_stub):
            result = await run_resume_writer(source, profile, ReplayWriter(),
                current_data=graph._serialize_to_resume_data({'collected_info': source}),
                previous_plan=REPLAY_PLAN, phase='write')
        body = result['resume_data']['projects'][0]['polished_bullets']
        self.assertEqual(len(body), 3)
        self.assertIn('整理用户访谈记录与需求', ' '.join(body))
        self.assertNotIn('整理项目文件目录', ' '.join(body))

    def test_body_buffer_requires_recognizable_start(self):
        for text in ('不必着急，先说一下项目。', '没有问题。你的简历还缺哪些信息？', '项目里用了什么技能？'):
            self.assertFalse(must_buffer_reply(text), text)
        for text in ('# 林知夏\n', '## 教育背景\n', '邮箱：linzhixia@example.invalid\n'):
            self.assertTrue(must_buffer_reply(text), text)

    def test_capability_sentence_buffer_releases_at_boundary(self):
        buffer = ReplyStreamBuffer({})
        self.assertEqual(buffer.feed('先核对经历。'), '先核对经历。')
        self.assertEqual(buffer.feed('PDF文件'), '')
        self.assertEqual(buffer.feed('无法生成'), '')
        corrected = buffer.feed('。')
        self.assertIn('右侧「写简历」', corrected)
        self.assertNotIn('无法生成', corrected)
        self.assertEqual(buffer.feed('接'), '接')
        self.assertFalse(buffer.buffered)
        self.assertEqual(buffer.feed('着说你的项目。'), '着说你的项目。')

    async def test_followup_first_token_is_yielded_before_model_second_token(self):
        for first in ('不', '无', '简历', '项目', '技能'):
            with self.subTest(first=first):
                release = asyncio.Event()
                second_requested = False
                content = first + '方面还有什么想补充的？'
                values = {**graph._init_state(), 'messages': [AIMessage(id='reply', content=content)]}
                async def events(*args, **kwargs):
                    nonlocal second_requested
                    yield 'custom', {'type': 'public_reply_delta', 'node': 'collecting', 'reply_id': 'reply', 'content': first}
                    second_requested = True
                    await release.wait()
                    yield 'custom', {'type': 'public_reply_delta', 'node': 'collecting', 'reply_id': 'reply', 'content': content[len(first):]}
                    yield 'updates', {'collecting': {'messages': values['messages']}}
                fake = SimpleNamespace(astream=events, aget_state=AsyncMock(return_value=SimpleNamespace(values=values)), aupdate_state=AsyncMock())
                with patch.object(graph, 'get_graph', return_value=fake), \
                        patch('app.services.session_store.save_resume_session', return_value={'resume_data': {}, 'resume_meta': {}}), \
                        patch('app.services.conversation_store.update_conversation_title'):
                    stream = graph.stream_agent([{'content': '项目要怎么补充？'}], 'b11b-first-token', object())
                    try:
                        chunk = await asyncio.wait_for(anext(stream), timeout=1)
                        self.assertEqual(chunk, first)
                        self.assertFalse(second_requested)
                    finally:
                        release.set()
                    rest = ''.join([chunk async for chunk in stream])
                    self.assertEqual(chunk + rest, content)


if __name__ == '__main__':
    unittest.main()


class Batch11SmallFollowups(unittest.TestCase):
    def test_role_equal_to_item_name_is_not_repeated(self):
        from app.services.resume_field_hygiene import sourced_role
        facts = [{'text': 'AI学习社活动志愿者', 'field': 'role'}]
        self.assertEqual(sourced_role(facts, '', 'AI学习社活动志愿者'), '')
        self.assertEqual(sourced_role(facts, '', '校园分享会'), 'AI学习社活动志愿者')

    def test_section_removal_does_not_also_hide_items(self):
        from app.agents.turn_actions import choose_edit_plan
        data = {'campus': [{'item_id': 'c1', 'name': 'AI学习社活动志愿者', 'bullets': ['协助报名']}]}
        plan = choose_edit_plan('删除「校园活动」这一整段，之后不再恢复', data, [], None, router_failed=True)
        self.assertIn('remove_section', [op['op'] for op in plan])
        self.assertNotIn('hide_item', [op['op'] for op in plan])


class TechReplayWriter:
    """The tech replay's three/two bullet budgets, with deliberate omissions."""
    def with_structured_output(self, schema):
        return SimpleNamespace(ainvoke=lambda messages: self.invoke(schema, messages))

    async def invoke(self, schema, messages):
        if schema.__name__ == 'RepairOutput':
            return {'bullets': []}
        payload = json.loads(messages[-1].content)
        rows = []
        for section in ('work_experience', 'projects'):
            for item in payload['evidence'].get(section, []):
                facts = item['facts']
                def bullet(text, *words):
                    return {'text': text, 'fact_ids': [next(f['id'] for f in facts if word in f['text']) for word in words]}
                if section == 'work_experience':
                    bullets = [
                        bullet('参与订单服务，团队 4 人，负责订单查询接口和参数校验', '团队', '参数校验'),
                        bullet('在导师指导下给订单列表加 Redis 缓存，并在测试环境对慢查询加联合索引优化查询', 'Redis', '联合索引'),
                        bullet('编写 12 条接口测试用例，并跟前端同学联调', '12 条', '联调')]
                else:
                    bullets = [bullet('负责商品发布和搜索接口，使用 Spring Boot、MySQL', '商品发布', 'Spring Boot'),
                               bullet('登录模块由另一位同学编写', '登录模块')]
                rows.append({'item_id': item['item_id'], 'section': section, 'bullets': bullets})
        return {'items': rows}


class Batch11cTechTest(unittest.IsolatedAsyncioTestCase):
    async def source(self, *, broad_quote=False):
        from test_batch10_regressions import TECH, tech_output, raw
        output = tech_output()
        work = output['items'][0]
        work['facts'] += [raw('参与订单服务，团队 4 人'), raw('用 Spring Boot 和 MySQL'),
                         raw('在导师指导下给订单列表加了 Redis 缓存'),
                         raw('在测试环境对一个慢查询加了联合索引'), raw('没做线上压测'),
                         raw('编写了 12 条接口测试用例'), raw('跟前端同学联调')]
        # The snapshot's active coverage has no 420/170 fact. Reproduce both
        # cropped extraction and an overbroad quote whose text lost the result.
        if broad_quote:
            work['facts'][-4]['source_quote'] += '，平均耗时由约 420ms 降到约 170ms'
        with patch('app.services.fact_guard.verify_semantics', side_effect=semantic_stub):
            extracted = await extract_facts_patch(TECH, {}, ExtractorStub(output))
        return apply_fact_patch({}, extracted)

    async def write(self, source, *, current=None, meta=None, polish=False):
        current = current or graph._serialize_to_resume_data({'collected_info': source})
        plan = {'requirements': [], 'experience_plan': [
            {'item_id': row['item_id'], 'treatment': 'lead' if section != 'projects' else 'keep',
             'target_bullets': 3 if section != 'projects' else 2, 'reason': '按回放预算保留技术证据'}
            for section in ('work_experience', 'internship', 'projects') for row in source.get(section, [])]}
        with patch('app.services.fact_guard.verify_semantics', side_effect=semantic_stub):
            return await run_resume_writer(source, {}, TechReplayWriter(), current_data=current,
                resume_meta=meta or {}, previous_plan=plan, phase='write',
                constraints={'preserve_explicit_limits': polish}, instruction='保留测试环境限制' if polish else '直接成稿')

    async def test_cropped_and_broad_quote_extraction_recover_metric_as_active_evidence(self):
        for broad in (False, True):
            with self.subTest(broad_quote=broad):
                source = await self.source(broad_quote=broad)
                facts = [f for section in ('internship', 'work_experience') for item in source.get(section, []) for f in item['facts']]
                self.assertTrue(any('420' in f['text'] and '170' in f['text'] and f['status'] == 'active' for f in facts), facts)

    async def test_metric_recovery_does_not_invent_an_owner_or_complete_a_plan(self):
        from test_batch10_regressions import raw
        for text, output in (
            ('平均耗时由约 420ms 降到约 170ms。', {'items': []}),
            ('在云舟科技做后端开发实习生，计划把平均耗时由约 420ms 降到约 170ms。',
             {'items': [{'section': 'internship', 'name': '云舟科技', 'facts': [raw('后端开发实习生', field='title')]}]}),
            ('在云舟科技做后端开发实习生，未把平均耗时由约 420ms 降到约 170ms。',
             {'items': [{'section': 'internship', 'name': '云舟科技', 'facts': [raw('后端开发实习生', field='title')]}]})):
            with self.subTest(text=text), patch('app.services.fact_guard.verify_semantics', side_effect=semantic_stub):
                result = await extract_facts_patch(text, {}, ExtractorStub(output))
                self.assertFalse(any('170' in f['text'] for item in result['items'] for f in item['facts']))

    async def test_legacy_mislabelled_role_is_body_evidence_without_mutating_source(self):
        source = await self.source()
        project = source['projects'][0]
        duty = next(f for f in project['facts'] if '商品发布' in f['text'])
        duty.update(kind='role', field='role')
        original = deepcopy(source)
        result = await self.write(source)
        rendered = result['resume_data']['projects'][0]
        self.assertNotIn('负责', rendered['role'])
        self.assertIn('商品发布', '\n'.join(rendered['polished_bullets']))
        self.assertEqual(source, original)

    async def test_three_turn_body_limits_and_literal_correction(self):
        from app.services.fact_corrections import apply_literal_corrections, correction_pairs
        from app.services.resume_versions import text_hash
        source = await self.source()
        initial = await self.write(source)
        for polish in (False, True):
            result = (await self.write(source, current=initial['resume_data'], meta=initial['resume_meta'], polish=True)) if polish else initial
            data = result['resume_data']
            work, project = data['work_experience'][0], data['projects'][0]
            body = '\n'.join(work['bullets'])
            self.assertIn('420', body)
            self.assertIn('170', body)
            self.assertIn('12', body)
            self.assertNotIn('后端开发实习生', body)
            self.assertNotRegex(project['role'], '负责商品|登录|同学')
            project_body = '\n'.join(project['polished_bullets'])
            self.assertRegex(project_body, '登录.*同学')
            self.assertIn('实验室', project_body)
            self.assertIn('只给班里演示', project_body)
            self.assertEqual(body.count('联合索引'), 1)
            if not polish:
                self.assertNotRegex(body, '(?:没|未)做线上压测')
            self.assertLessEqual(len(work['bullets']), 3)
            self.assertLessEqual(len(project['polished_bullets']), 2)
            for item, field in ((work, 'bullets'), (project, 'polished_bullets')):
                records = result['resume_meta']['bullets'][item['item_id']]
                self.assertEqual(len(records), len(item[field]))
                self.assertEqual([r['text_hash'] for r in records], [text_hash(t) for t in item[field]])
        corrected = apply_literal_corrections(source, data, result['resume_meta'],
                                             correction_pairs('把 170ms 更正为 190ms，其他数字保持不变'))
        self.assertNotIn('error', corrected)
        old, new = resume_to_text(data), resume_to_text(corrected['resume_data'])
        self.assertEqual(new, old.replace('170', '190'))
        from test_persona_regressions import FIXTURES
        state = {**graph._init_state(), **result, 'collected_info': source, 'stage': 'EVALUATING',
                 'candidate_history_reconciled': True,
                 'messages': [HumanMessage(content=FIXTURES['tech']['correction'])]}
        with patch.object(graph, '_write_resume_update', AsyncMock(side_effect=AssertionError('literal edit must not rewrite'))), \
                patch('app.services.resume_capacity.measure_rendered_pages', return_value={'status': 'rendered', 'pages': 1}), \
                patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={'status': 'rendered', 'pages': 1}):
            routed = await graph.evaluating_node(state, object())
        self.assertEqual(resume_to_text(routed['resume_data']), new)
        self.assertIn('已更新正文', routed['messages'][0].content)

    def test_header_role_rejects_duties_and_keeps_actual_titles(self):
        from app.services.resume_field_hygiene import sourced_role
        for value in ('负责商品发布和搜索接口', '登录模块是另一位同学写的', '退款由主管审批'):
            self.assertEqual(sourced_role([{'text': value, 'kind': 'role'}], value), '')
        self.assertEqual(sourced_role([{'text': '后端开发实习生', 'kind': 'role'}], '负责查询接口'), '后端开发实习生')

    def test_title_echo_is_not_a_body_bullet(self):
        from app.services.candidate_language import resume_bullet
        self.assertEqual(resume_bullet('后端开发实习生', role='后端开发实习生'), '')
        self.assertEqual(resume_bullet('后端开发实习生，编写12条测试', role='后端开发实习生'), '编写12条测试')

    def test_limit_recovery_is_idempotent_without_duplicate_parentheses(self):
        source = {'work_experience': [{'item_id': 'w', 'company': '云舟科技', 'facts': [
            new_fact('在测试环境对一个慢查询加了联合索引'), new_fact('没做线上压测')]}]}
        data = {'work_experience': [{'item_id': 'w', 'company': '云舟科技', 'bullets': [
            '在测试环境对慢查询加联合索引优化查询（在测试环境对一个慢查询加了联合索引）（没做线上压测）']} ]}
        for explicit in (False, True):
            result, meta, _ = preserve_item_limits(data, {}, source, item_ids=['w'], constraints={'preserve_explicit_limits': explicit})
            body = result['work_experience'][0]['bullets'][0]
            self.assertEqual(body.count('联合索引'), 1)
            self.assertNotIn('（', body)
            self.assertEqual(body.count('没做线上压测'), int(explicit))
            again, _, _ = preserve_item_limits(result, meta, source, item_ids=['w'], constraints={'preserve_explicit_limits': explicit})
            self.assertEqual(again, result)
