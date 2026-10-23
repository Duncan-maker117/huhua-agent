"""Offline quality regressions. All identities, contacts and project facts are fictional."""
from copy import deepcopy
from pathlib import Path
import sys
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]
from langchain_core.messages import HumanMessage
from app.agents import orchestrator_tools as tools
from app.services.resume_versions import document_diff
from app.services.tech_stack import project_item_stack
from app.services.resume_preflight import preflight_resume, clean_contacts, compact_code_links, normalize_date
from app.services.resume_versions import prepare_version, text_hash


def fixture():
    projects = [
        ('trip-a', 'mtagent｜多 Agent 协作的旅行行程规划应用', '项目发起人',
         ['问题：本人发现路线选择困难', '决策：支持偏好筛选', '迭代：增加失败路线回退', '现状：本地原型，尚未上线']),
        ('trip-b', '同路 mtagent｜关系画像驱动的本地路线规划 Agent', '个人项目',
         ['决策：实现关系画像', '现状：本地原型，尚未上线']),
        ('trip-c', 'mtagent｜旅行规划原型', '虚构竞赛项目', ['迭代：补充路线校验']),
        ('resume-a', '文舟简历｜根据素材编写简历的实验工具', '个人项目',
         ['问题：本人发现经历零散、不会对标 JD；AI 代写编造；先体验后登录；事实复核',
          '决策：本人做了几个关键决定：先体验后登录；事实复核；经历零散、不会对标 JD；AI 代写编造',
          '迭代：我们补充了素材核对',
          '现状：https://github.com/example-org/fictional-resume/pull/6 和 https://github.com/example-org/fictional-resume/pull/8 已合入上游']),
        ('resume-b', '文舟简历', '开发者', ['问题：是市面上当时体验过的简历工具都不满意']),
        ('code-a', 'CodeNest｜代码问答实验', '开发者', ['决策：实现索引查询']),
        ('code-b', 'Code Nest', '个人项目', ['迭代：修复索引失效']),
    ]
    data = {'basic_info': {'name': '虚构候选人甲', 'phone': '000-0000-0000', 'email': 'candidate@example.invalid',
        'links': [{'text': '个人主页', 'url': 'https://portfolio.example.invalid/'},
                  {'text': '个人主页', 'url': 'http://PORTFOLIO.example.invalid'},
                  {'text': '个人主页', 'url': 'portfolio.example.invalid/ ·'},
                  {'text': 'GitHub', 'url': 'github.com/fictional-candidate'},
                  {'text': 'GitHub', 'url': 'https://github.com/FICTIONAL-CANDIDATE/'},
                  {'text': '个人主页', 'url': 'fictional-candidate'}, {'text': '', 'url': ' · '}]},
        'education': [{'item_id': 'edu', 'school': '虚构示例学院', 'start_date': '2023.09', 'end_date': '预计2027年6月'}],
        'projects': [{'item_id': iid, 'name': name, 'role': role, 'start_date': '2025年9月',
                      'end_date': '', 'polished_bullets': body} for iid, name, role, body in projects]}
    data['projects'][3]['tech_stack'] = ['Python', 'FastAPI', '门槛', '让ai来做这个编写简历的人', '我们来提供素材']
    facts = {'projects': [{**deepcopy(row), 'facts': [
        {'id': row['item_id'] + '-f' + str(i), 'text': text, 'source_quote': text,
         'kind': 'action', 'status': 'active', 'profile_refs': [{'item_id': row['item_id'], 'fact_id': str(i)}]}
        for i, text in enumerate(row['polished_bullets'])]} for row in data['projects']]}
    return {'resume_data': data, 'resume_meta': {}, 'collected_info': facts, 'resume_versions': []}


class Quality18DReproduction(unittest.IsolatedAsyncioTestCase):
    async def test_merge_request_reaches_a_real_edit_without_writer(self):
        state = fixture()
        literal = '简历好像有内容重复了，合并重复的 mtagent 条目、删掉技术栈里不是技术的内容'
        state['messages'] = [HumanMessage(content=literal)]
        with patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={'pages': 1}), \
             patch.object(tools, '_write', side_effect=AssertionError('deterministic cleanup needs no model')):
            result = await tools.edit_resume(state, {'instruction': '删除重复内容，清理技术栈'}, tools.ToolContext())
        self.assertTrue(result.result.get('changed'), result.result)
        # “mtagent” is the only name given: the other look-alike pairs stay put.
        self.assertEqual(len(result.update['resume_data']['projects']), 5)

    def test_stack_quote_is_not_proof_of_a_technology_name(self):
        item = {'item_id': 'p', 'polished_bullets': [], 'tech_stack': ['门槛', '让ai来做这个编写简历的人', '我们来提供素材']}
        fact = {'id': 'f', 'kind': 'action', 'dimension': 'decision',
                'source_quote': '降低门槛、让ai来做这个编写简历的人、我们来提供素材'}
        project_item_stack(item, [fact], {})
        self.assertFalse(item.get('tech_stack'))

    def test_invisible_metadata_is_not_a_document_change(self):
        before = fixture()['resume_data']
        after = deepcopy(before)
        after['projects'][0].update(source='profile', profile_refs=[{'item_id': 'source'}], hidden=False)
        self.assertEqual(document_diff(before, after), [])


class Quality18DPreflight(unittest.TestCase):
    def test_comprehensive_fixture_and_idempotence(self):
        state = fixture()
        original = deepcopy(state)
        data, meta, report = preflight_resume(state['resume_data'], state['resume_meta'], state['collected_info'], merge_request='有内容重复，合并 mtagent、文舟简历、CodeNest')
        self.assertEqual(state, original)
        self.assertEqual(len(data['projects']), 3)
        self.assertEqual(len(report['merged']), 3)
        trip, resume, code = data['projects']
        self.assertEqual(trip['item_id'], 'trip-a')
        for fact in ('支持偏好筛选', '实现关系画像', '增加失败路线回退', '补充路线校验', '尚未上线'):
            self.assertIn(fact, str(trip['polished_bullets']))
        for fact in ('实现索引查询', '修复索引失效'):
            self.assertIn(fact, str(code['polished_bullets']))
        self.assertEqual(resume['tech_stack'], ['Python', 'FastAPI'])
        prose = '；'.join(resume['polished_bullets'])
        for phrase in ('先体验后登录', '事实复核', '经历零散、不会对标 JD', 'AI 代写编造'):
            self.assertEqual(prose.count(phrase), 1, prose)
        for phrase in ('本人', '我们', '是市面上当时', 'https://github.com'):
            self.assertNotIn(phrase, prose)
        self.assertIn('团队补充', prose)
        self.assertIn('PR #6、#8 已合入上游', prose)
        self.assertEqual(data['education'][0]['end_date'], '2027.06（预计）')
        self.assertEqual({row['start_date'] for row in data['projects']}, {'2025.09'})
        self.assertEqual(data['basic_info']['links'], [
            {'text': '个人主页', 'url': 'https://portfolio.example.invalid'},
            {'text': 'GitHub', 'url': 'https://github.com/fictional-candidate'}])
        self.assertEqual(preflight_resume(data, meta, state['collected_info'])[:2], (data, meta))
        from app.services.ask_user import draft_dimensions
        self.assertIn('iteration', draft_dimensions({'resume_data': data}, 'trip-a'))

    def test_only_shared_profile_item_can_identify_renames(self):
        for field in ('profile_refs', 'source', 'profile_item_id'):
            with self.subTest(field=field):
                data = {'projects': [{'item_id': 'a', 'name': '旧项目代号', 'polished_bullets': ['开发查询接口']},
                                     {'item_id': 'b', 'name': '新的项目名称', 'polished_bullets': ['修复缓存失效']}]}
                for row in data['projects']:
                    row[field] = [{'fact_id': 'shared-fact'}] if field == 'profile_refs' else {'item_id': 'shared-item'} if field == 'source' else 'shared-item'
                result, _, _ = preflight_resume(data)
                self.assertEqual(len(result['projects']), 2 if field == 'profile_refs' else 1)
                self.assertEqual(len(result['projects'][0]['polished_bullets']), 1 if field == 'profile_refs' else 2)

    def test_same_document_or_generic_suffix_does_not_merge_distinct_projects(self):
        data = {'projects': [{'item_id': str(i), 'name': name, 'source': 'same-upload', 'polished_bullets': ['开发接口']}
                             for i, name in enumerate(('订单 Agent', '库存 Agent', 'Agent'))]}
        self.assertEqual(len(preflight_resume(data)[0]['projects']), 3)
        numbered = {'projects': [{'item_id': str(i), 'name': name} for i, name in enumerate(('Project1', 'Project10', 'Project1Pro'))]}
        self.assertEqual(len(preflight_resume(numbered)[0]['projects']), 3)

    def test_most_informative_entry_wins_and_provenance_coverage_follows_it(self):
        from app.services.fact_coverage import ensure_fact_coverage
        data = {'projects': [
            {'item_id': 'brief', 'name': '合成项目', 'polished_bullets': ['开发查询接口']},
            {'item_id': 'full', 'name': '合成项目', 'polished_bullets': ['实现索引过期后的缓存重建并增加失败重试']} ]}
        source = {'projects': [{**row, 'facts': [{'id': row['item_id'] + '-fact', 'kind': 'action',
                   'text': row['polished_bullets'][0], 'source_quote': row['polished_bullets'][0]}]} for row in data['projects']]}
        result, meta, _ = preflight_resume(data, collected=source)
        self.assertEqual(result['projects'][0]['item_id'], 'full')
        coverage = ensure_fact_coverage(result, meta, source)
        self.assertEqual(coverage['covered'], 2, coverage)

    def test_separate_engagements_and_hidden_items_are_preserved(self):
        items = [{'item_id': 'a', 'name': '示例项目', 'start_date': '2024.01', 'end_date': '2024.02'},
                 {'item_id': 'b', 'name': '示例项目', 'start_date': '2025.01', 'end_date': '2025.02'},
                 {'item_id': 'c', 'name': '示例项目', 'hidden': True}]
        self.assertEqual(len(preflight_resume({'projects': items})[0]['projects']), 3)

    def test_merged_citations_stay_aligned_and_revocable(self):
        from app.services.profile_bridge import sanitize_fact_history
        state = fixture()
        state['resume_meta']['bullets'] = {
            row['item_id']: [{'text_hash': text_hash(f['text']), 'fact_ids': [f['id']]} for f in row['facts']]
            for row in state['collected_info']['projects']}
        data, meta, _ = preflight_resume(state['resume_data'], state['resume_meta'], state['collected_info'], merge_request='有内容重复，合并 mtagent、文舟简历、CodeNest')
        for item in data['projects']:
            for line, record in zip(item['polished_bullets'], meta['bullets'][item['item_id']]):
                self.assertEqual(record['text_hash'], text_hash(line))
                self.assertTrue(record['fact_ids'])
        self.assertIn('trip-b', meta['merged_items']['trip-a'])
        state['collected_info']['projects'][1]['facts'][0]['status'] = 'superseded'
        cleaned = sanitize_fact_history({**state, 'resume_data': data, 'resume_meta': meta})
        self.assertNotIn('实现关系画像', str(cleaned['resume_data']['projects']))

    def test_known_stack_is_preserved_and_sentences_are_rejected_at_source(self):
        from app.services.tech_stack import pure_stack, normalize_stack, extract_stack
        self.assertEqual(normalize_stack(['Spring Boot', 'C++', '向量检索', '我们提供素材', '门槛', 'Python']),
                         ['Spring Boot', 'C++', '向量检索', 'Python'])
        self.assertEqual(pure_stack('技术栈：门槛、让ai来做这个编写简历的人、我们来提供素材'), [])
        self.assertEqual(extract_stack({'dimension': 'decision', 'source_quote': '让ai来做这个编写简历的人，我们来提供素材'}), [])

    def test_prose_detection_and_outage_fallback_preserve_team_and_negation(self):
        from app.services.auto_polish_gate import needs_polish
        from app.services.candidate_language import resume_bullet
        self.assertIn('first_person', needs_polish('问题：本人发现需求不清晰'))
        self.assertIn('colloquial', needs_polish('问题：是市面上当时体验过的简历工具都不满意'))
        text = resume_bullet('迭代：我们完成回归测试；现状：本人未上线服务')
        self.assertIn('团队完成', text)
        self.assertIn('未上线', text)
        self.assertNotIn('本人', text)

    def test_duplicate_short_clauses_do_not_erase_distinct_limits_or_numbers(self):
        data = {'projects': [{'item_id': 'p', 'name': '合成项目', 'polished_bullets': [
            '问题：事实复核；事实复核', '决策：事实复核；本地测试 6 次；线上测试 8 次；尚未上线']} ]}
        body = preflight_resume(data)[0]['projects'][0]['polished_bullets']
        self.assertEqual(str(body).count('事实复核'), 1)
        for term in ('本地测试 6 次', '线上测试 8 次', '尚未上线'):
            self.assertIn(term, str(body))

    def test_contact_type_and_empty_separator_cleanup(self):
        links = clean_contacts({'links': [{'text': 'GitHub', 'url': 'fixture-user'},
            {'text': '个人主页', 'url': 'https://GITHUB.com/FIXTURE-USER/'},
            {'text': 'GitHub', 'url': 'https://portfolio.example.invalid/'}, {'text': '个人主页', 'url': 'unknown-handle'},
            {'text': '个人主页', 'url': ' · '}]})['links']
        self.assertEqual([row['text'] for row in links], ['GitHub', '个人主页', '账号'])
        self.assertFalse(any(row['url'].endswith(('·', '/')) for row in links))

    def test_dates_preserve_unknowns_and_expected_status(self):
        for value in ('2027/6', '2027-06', '2027年6月', '2027.6'):
            self.assertEqual(normalize_date(value), '2027.06')
        self.assertEqual(normalize_date('预计2027年6月'), '2027.06（预计）')
        for value in ('至今', '2027', '2027.13', ''):
            self.assertEqual(normalize_date(value), value)

    def test_commit_and_cross_repository_prs_keep_identity_without_inventing_status(self):
        text = compact_code_links('https://github.com/example-org/fictional-a/pull/6、https://github.com/example-org/fictional-b/pull/6 待审核')
        self.assertIn('fictional-a PR #6', text)
        self.assertIn('fictional-b PR #6', text)
        self.assertIn('待审核', text)
        self.assertNotIn('合入', text)
        self.assertEqual(compact_code_links('提交 https://github.com/example-org/fictional-a/commit/abcdef1234567890'), '提交 commit abcdef1')

    def test_metadata_rekey_and_invisible_whitespace_do_not_create_version(self):
        before = {'projects': [{'item_id': 'a', 'name': '合成项目', 'polished_bullets': ['开发查询接口']}]}
        after = deepcopy(before)
        after['projects'][0].update(item_id='b', hidden=False, source='profile')
        after['projects'][0]['polished_bullets'] = ['开发查询接口\u200b']
        result = prepare_version(before, {'version_id': 'original'}, [], after, {})
        self.assertFalse(result['changed'])
        self.assertEqual(result['version_id'], 'original')
        self.assertEqual(result['resume_versions'], [])
        self.assertEqual(document_diff({}, {'basic_info': {'name': ' '}, 'skills': [], 'summary': ''}), [])
        self.assertTrue(document_diff({'layout': {'density': 1}}, {'layout': {'density': 0}}))

    def test_followup_is_scoped_to_item_and_nonempty_dimension(self):
        from app.services.ask_user import validate_card
        state = {**fixture(), 'intake_stage': 'ready', 'stage': 'EVALUATING'}
        args = {'subject': 'trip-a', 'questions': [{'id': 'iteration', 'prompt': 'badcase 与迭代是什么？', 'kind': 'text'},
                {'id': 'evaluation', 'prompt': '评测方式是什么？', 'kind': 'text'}]}
        card = validate_card(args, state, 'turn')
        self.assertEqual([q['id'] for q in card['questions']], ['evaluation'])
        state['resume_data']['projects'][0]['polished_bullets'] = ['迭代：待补充']
        self.assertEqual(len(validate_card(args, state, 'turn')['questions']), 2)
        args['subject'] = 'code-a'
        self.assertEqual(len(validate_card(args, state, 'turn')['questions']), 2)

    def test_frontend_diff_card_ignores_identical_display_text(self):
        self.assertIsNotNone(shutil.which('node'))
        result = subprocess.run(['node', str(ROOT / 'tests/quality_18d.dom.js')], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class Quality18DIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch('app.agents.tailor_pipeline.measure_rendered_pages', return_value={'pages': 1, 'within_page_limit': True}))
        self.enterContext(patch('app.services.resume_capacity.measure_rendered_pages', return_value={'pages': 1, 'within_page_limit': True}))

    async def test_named_complaint_merges_and_second_edit_is_unchanged(self):
        state = fixture()
        state['messages'] = [HumanMessage(content='简历好像有内容重复了铁铁，合并 mtagent、文舟简历、CodeNest')]
        first = await tools.edit_resume(state, {'instruction': '删除重复内容'}, tools.ToolContext())
        self.assertEqual(first.result['status'], 'ok', first.result)
        self.assertEqual(len(first.update['resume_data']['projects']), 3)
        self.assertEqual(first.update['resume_versions'][-1]['resume_data'], state['resume_data'])
        self.assertEqual(first.update['resume_versions'][-1]['resume_meta'], state['resume_meta'])
        self.assertEqual(state['collected_info'], fixture()['collected_info'])
        second = await tools.edit_resume({**state, **first.update}, {'instruction': '删除重复内容'}, tools.ToolContext())
        self.assertEqual(second.result['status'], 'unchanged', second.result)
        self.assertFalse(second.result['changed'])
        self.assertEqual(second.result['change_summary'], [])
        self.assertEqual(second.result['document_changes'], [])
        current = {**state, **first.update}
        literal = '合并重复的同路 mtagent｜关系画像驱动的本地路线规划 Agent'
        current['messages'] = [HumanMessage(content=literal)]
        named_retry = await tools.edit_resume(current, {'instruction': literal}, tools.ToolContext())
        self.assertEqual(named_retry.result['status'], 'unchanged', named_retry.result)

    async def test_model_paraphrase_does_not_authorize_merge(self):
        state = fixture()
        for literal in ('把学校名称改一下', '不要合并重复的项目'):
            state['messages'] = [HumanMessage(content=literal)]
            result = await tools.edit_resume(state, {'instruction': '合并重复条目'}, tools.ToolContext())
            self.assertFalse(result.update)
            self.assertNotEqual(result.result['status'], 'ok')

    async def test_merge_with_page_limit_cannot_succeed_as_constraint_only_noop(self):
        # HEAD emitted only set_constraint and returned unchanged with 7 entries.
        literal = '合并重复的 mtagent 条目，整理成一页'
        state = {**fixture(), 'messages': [HumanMessage(content=literal)]}
        with patch.object(tools, '_write', side_effect=AssertionError('no writer needed')):
            result = await tools.edit_resume(state, {'instruction': literal}, tools.ToolContext())
        self.assertEqual(result.result['status'], 'ok', result.result)
        # Only the named entries merge; the other look-alikes are put to the user.
        self.assertEqual(len(result.update['resume_data']['projects']), 5)
        self.assertEqual([row['item_id'] for row in result.update['resume_data']['projects']][:1], ['trip-a'])
        self.assertTrue(result.result['card_shown'])
        self.assertEqual(result.update['session_constraints']['page_limit'], 1)

    async def test_metadata_only_tool_result_has_no_success_receipt(self):
        from unittest.mock import AsyncMock
        state = fixture()
        state['messages'] = [HumanMessage(content='润色整个简历')]
        after = deepcopy(state['resume_data'])
        after['projects'][0]['profile_refs'] = [{'item_id': 'new-binding'}]
        fake = tools.ToolOutcome({'status': 'ok', 'changed': True, 'change_summary': ['已更新']},
                                 {'resume_data': after, 'resume_meta': {}})
        with patch.object(tools, '_write', new=AsyncMock(return_value=fake)):
            result = await tools.edit_resume(state, {'instruction': '润色整个简历'}, tools.ToolContext())
        self.assertEqual(result.result['status'], 'unchanged')
        self.assertEqual(result.result['change_summary'], [])
        self.assertEqual(result.update['diff'], [])

    async def test_write_draft_checks_the_final_projection_before_version_and_measurement(self):
        state = fixture()
        state.update(resume_data={}, confirmed_plan={'experience_plan': []}, messages=[HumanMessage(content='直接出稿')])
        async def pipeline(*args, **kwargs):
            return {'resume_data': fixture()['resume_data'], 'resume_meta': {}, 'changed': True}
        with patch('app.agents.tailor_pipeline.run_tailor_pipeline', side_effect=pipeline):
            outcome = await tools.write_draft(state, {}, tools.ToolContext(llm=object()))
        self.assertEqual(outcome.result['status'], 'ok', outcome.result)
        data = outcome.update['resume_data']
        self.assertEqual(len(data['projects']), 7)
        self.assertEqual(data['projects'][3]['tech_stack'], ['Python', 'FastAPI'])
        self.assertEqual(len(outcome.result['experience_inventory']['included']), 8)
        self.assertTrue(outcome.update['resume_meta']['version_id'])

    async def test_polish_failure_uses_existing_safe_fallback_for_labeled_first_person(self):
        from app.agents.resume_writer import _polish_rows
        text = '迭代：本人补充素材核对'
        facts = {'f': {'id': 'f', 'item_id': 'p', 'kind': 'action', 'text': text, 'source_quote': text}}
        rows = [{'id': 'r', 'item_id': 'p', 'text': text, 'fact_ids': ['f']}]
        from unittest.mock import AsyncMock
        with patch('app.agents.resume_writer._call', new=AsyncMock(side_effect=RuntimeError('offline'))):
            result = await _polish_rows(rows, facts, None, None, 'ai_pm')
        self.assertEqual(result[0]['text'], '迭代：补充素材核对')
        self.assertEqual(result[0]['polish']['method'], 'deterministic')


class Quality18DTemplateGeometry(unittest.TestCase):
    def test_all_seven_templates_wrap_titles_inside_a4_and_separate_dates(self):
        from app.services.renderer import list_templates, render_resume
        from app.services.resume_pdf import _render
        templates = list_templates()
        self.assertEqual(len(templates), 7)
        data = preflight_resume(fixture()['resume_data'])[0]
        data['projects'] = [data['projects'][0]]
        data['projects'][0].update(
            name='虚构路线规划项目｜' + '面向多人协作的偏好选择与路线约束规划实验应用' * 5,
            positioning='使用合成测试数据验证流程', role='项目开发者', end_date='2026.06')
        for template in templates:
            with self.subTest(template=template['id']):
                html = render_resume(template['id'], data)
                document = _render(template['id'], data, lambda document: document)
                text_boxes = [box for page in document.pages for box in page._page_box.descendants()
                              if getattr(box, 'text', '')]
                headers = [box for page in document.pages for box in page._page_box.descendants()
                           if box.element is not None and 'project-head' in box.element.get('class', '').split()
                           and box.__class__.__name__ == 'FlexBox']
                self.assertEqual(len(headers), 1)
                header = headers[0]
                title, date = header.children
                self.assertGreater(title.height, 25, 'long title must wrap')
                self.assertGreaterEqual(date.position_x, title.position_x + title.width + 4)
                for box in text_boxes:
                    self.assertGreaterEqual(box.position_x, -0.1)
                    self.assertLessEqual(box.position_x + box.width, 794.5, repr(box.text))
                visible = ''.join(box.text for box in text_boxes)
                self.assertIn('2025.09', visible)
                self.assertIn('2026.06', visible)
                self.assertEqual(visible.count('个人主页'), 1)
                self.assertEqual(visible.count('GitHub'), 1)
                self.assertNotRegex(visible, r'·\s*(?:教育|虚构示例学院)')
