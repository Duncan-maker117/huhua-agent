"""Structured attachment/paste intake and numeric boundaries; synthetic only."""
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

import test_persona_regressions as persona
from test_campus_and_naming import EchoWriter
from app.agents import resume_graph as graph
from app.agents.resume_writer import run_resume_writer
from app.services.candidate_material import _append_wrapped, looks_like_existing_resume, parse_existing_resume
from app.services.candidate_language import constraint_only, resume_bullet
from app.services.candidate_sections import parse_labelled_items
from app.services.fact_guard import _quantity_units, lexical_fact_errors, guard_bullets
from app.services.resume_facts import normalize_fact_store
from app.services.resume_workspace import build_workspace


BLOCK = persona.ATTACHMENT[persona.ATTACHMENT.index('学生组织：'):persona.ATTACHMENT.index('\n\n技能：')]


class SparseDesignWriter(EchoWriter):
    """Reproduce the frozen writer's tool-only, one-bullet campus choice."""
    async def ainvoke(self, messages):
        result = await super().ainvoke(messages)
        for item in result['writer']['items']:
            if item['section'] == 'campus':
                facts = next(row['facts'] for row in self.payload['evidence']['campus'] if row['item_id'] == item['item_id'])
                poster = next(fact for fact in facts if '6 张' in fact['text'])
                item['bullets'] = [{'text': '使用 Photoshop 和 Illustrator。', 'fact_ids': [poster['id']]}]
        return result


class BatchNineRegressions(unittest.IsolatedAsyncioTestCase):
    setUp = persona.PersonaRegressions.setUp

    def assert_campus(self, item):
        self.assertEqual(item['role'], '宣传部成员')
        self.assertEqual((item['start_date'], item['end_date']), ('2023.09', '2024.06'))
        fields = {f.get('field'): f['text'] for f in item['facts'] if f.get('field')}
        self.assertEqual(fields['role'], item['role'])
        self.assertEqual(fields['start_date'], item['start_date'])
        self.assertEqual(fields['end_date'], item['end_date'])
        body = [f for f in item['facts'] if not f.get('field')]
        self.assertEqual(len(body), 2)
        self.assertRegex(body[0]['text'], r'按部长给的文案制作过 6 张活动海报')
        self.assertEqual(body[1]['kind'], 'status_limit')
        self.assertIn('没有负责活动策划', body[1]['text'])
        self.assertTrue(all('\n' not in f['text'] for f in item['facts']))

    def test_labelled_block_splits_fields_actions_and_limit_with_original_sources(self):
        item = parse_labelled_items(BLOCK, source='import', source_name='design-material.txt')['campus'][0]
        self.assert_campus(item)
        for fact in item['facts']:
            self.assertIn(fact['source_quote'], BLOCK)
            self.assertEqual(fact['sources'][0]['name'], 'design-material.txt')

    def test_attachment_and_paste_share_atomic_import_and_missing_projection(self):
        for prefix, source in [('[文件: design-material.txt]\n', 'design-material.txt'), ('', '粘贴资料')]:
            facts = normalize_fact_store(parse_existing_resume(prefix + persona.ATTACHMENT))
            self.assert_campus(facts['campus'][0])
            self.assertTrue(all(f['sources'][0]['name'] == source for f in facts['campus'][0]['facts']))
            workspace = build_workspace({'collected_info': facts})
            row = next(row for row in workspace['experiences']['items'] if '协会' in row['name'])
            self.assertNotIn('你的职责与分工', row['missing'])
            self.assertNotIn('经历时间', row['missing'])

    def test_company_role_aliases_and_inherited_dates_stay_in_their_own_blocks(self):
        for title in ('公司', '公司名称', '实习公司'):
            for role in ('职务', '角色', '岗位'):
                text = (f'{title}：示例科技\n{role}：开发实习生\n时间：2025 年 7 月到 8 月\n'
                        '编写了 12 条测试；没有上线。\n\n' + BLOCK)
                result = parse_existing_resume(text)
                item = result['internship' if title == '实习公司' else 'work_experience'][0]
                self.assertEqual(item['company'], '示例科技')
                self.assertEqual(item['role'], '开发实习生')
                self.assertEqual((item['start_date'], item['end_date']), ('2025.07', '2025.08'))
                self.assertEqual(len([f for f in item['facts'] if not f.get('field')]), 2)
                self.assert_campus(result['campus'][0])
                self.assertNotIn('海报', str(item))

    def test_structured_project_preserves_line_boundaries_and_excludes_date_bullets(self):
        text = ('项目名称：合成课程\n角色：界面设计\n时间：2025 年 3 月到 6 月\n'
                '3 人课程小组\n绘制 12 个页面；整理 18 个组件。\n技能：Figma')
        # A complete labelled block is sufficient; no personal header required.
        result = parse_existing_resume(text)
        self.assertIsNotNone(result)
        item = result['projects'][0]
        self.assertEqual((item['role'], item['start_date'], item['end_date']), ('界面设计', '2025.03', '2025.06'))
        body = [f['text'] for f in item['facts'] if not f.get('field')]
        self.assertIn('3 人课程小组', body)
        self.assertIn('绘制 12 个页面', body)
        self.assertFalse(any('2025' in line or '时间：' in line for line in body))
        self.assertTrue(all(f['source_quote'] in text for f in item['facts']))

    def test_repeated_attachment_retains_each_fact_source_without_duplicate_items(self):
        text = f'[文件: one.txt]\n{persona.ATTACHMENT}\n\n[文件: two.txt]\n{persona.ATTACHMENT}'
        result = parse_existing_resume(text)
        self.assertEqual(len(result['campus']), 1)
        self.assert_campus(result['campus'][0])
        for fact in result['campus'][0]['facts']:
            self.assertEqual({s['name'] for s in fact['sources']}, {'one.txt', 'two.txt'})

    def test_changed_attachment_fields_keep_both_sources_and_only_selected_active_values(self):
        revised = BLOCK.replace('宣传部成员', '宣传部干事').replace('2024.06', '2024.05')
        result = parse_existing_resume(f'[文件: old.txt]\n{BLOCK}\n\n[文件: new.txt]\n{revised}')
        item = result['campus'][0]
        self.assertEqual((item['role'], item['end_date']), ('宣传部干事', '2024.05'))
        conflicts = {c['field']: c for c in result['field_conflicts']}
        self.assertEqual({v['source'] for v in conflicts['role']['values']}, {'old.txt', 'new.txt'})
        for field in ('role', 'end_date'):
            self.assertEqual([f['text'] for f in item['facts'] if f.get('field') == field and f['status'] == 'active'], [item[field]])

    def test_missing_or_invalid_fields_do_not_absorb_the_next_experience(self):
        for date in ('2025 年 12 月到 2 月', ''):
            text = ('学生组织：青年志愿者协会\n制作 6 张海报。\n'
                    '项目名称：合成课程\n' + (f'时间：{date}\n' if date else '') + '绘制 12 个页面。')
            result = parse_existing_resume(text)
            self.assertEqual(result['campus'][0]['name'], '青年志愿者协会')
            self.assertNotIn('12 个', str(result['campus'][0]))
            project = result['projects'][0]
            self.assertFalse(project.get('start_date'))
            self.assertFalse(project.get('end_date'))
            self.assertIn('绘制 12 个页面', project['description'])

    def test_ownership_prefix_keeps_delivery_while_pure_limits_stay_constraints(self):
        for text in ('按部长给的文案制作过 6 张活动海报',
                     '按部长给的文案用 Photoshop 和 Illustrator 制作 6 张活动海报',
                     '没有负责活动策划但制作过 6 张活动海报'):
            self.assertFalse(constraint_only(text))
            self.assertIn('6 张', resume_bullet(text))
        for text in ('文案由部长提供', '我没有负责活动策划'):
            self.assertTrue(constraint_only(text))

    async def test_design_first_draft_keeps_six_posters_team_and_headers_with_sparse_writer(self):
        for prefix in ('[文件: design-material.txt]\n', ''):
            instruction = persona.FIXTURES['design']['initial'] if prefix else '请按以上真实材料直接生成 UI 设计实习生简历。'
            text = prefix + persona.ATTACHMENT + '\n\n---\n\n' + instruction
            state = {**graph._init_state(), 'messages': [HumanMessage(content=text, id='batch9')]}
            with patch.object(graph, '_run_decoder_and_build_reply', AsyncMock(side_effect=AssertionError('not JD'))):
                result = await graph.jd_input_node(state, SparseDesignWriter())
            campus = result['resume_data']['campus'][0]
            self.assertEqual((campus['role'], campus['start_date'], campus['end_date']), ('宣传部成员', '2023.09', '2024.06'))
            self.assertRegex(' '.join(campus['bullets']), r'6\s*张.*海报')
            self.assertNotRegex(' '.join(campus['bullets']), r'(?<!没有)(?:负责|主导|策划了)活动策划')
            project = result['resume_data']['projects'][0]
            body = project['description'] + ' '.join(project['polished_bullets'])
            self.assertIn('3 人课程小组', body)
            self.assertNotRegex(body, r'2025[.年]|063\s*人')

    async def test_one_bullet_campus_plan_restores_poster_count_without_promoting_limit(self):
        facts = normalize_fact_store(parse_existing_resume('[文件: design-material.txt]\n' + persona.ATTACHMENT))
        campus = facts['campus'][0]
        plan = {'experience_plan': [{'item_id': campus['item_id'], 'treatment': 'keep', 'target_bullets': 1}]}
        result = await run_resume_writer(facts, {}, SparseDesignWriter(), previous_plan=plan, phase='write')
        body = ' '.join(result['resume_data']['campus'][0]['bullets'])
        self.assertRegex(body, r'6\s*张.*海报')
        self.assertIn('按部长给的文案', body)
        self.assertNotIn('负责活动策划', body)

    async def test_writer_cannot_turn_separate_ownership_limit_into_activity_planning(self):
        item = parse_existing_resume(BLOCK)['campus'][0]
        facts = [{**fact, 'item_id': item['item_id']} for fact in item['facts']]
        poster = next(f for f in facts if not f.get('field') and '6 张' in f['text'])
        for claim in ('策划活动，制作 6 张活动海报', '负责活动策划，制作 6 张活动海报'):
            checked = await guard_bullets([{'id': 'b', 'item_id': item['item_id'], 'text': claim,
                                           'fact_ids': [poster['id']]}], facts)
            self.assertEqual(checked[0]['verdict'], 'fail')
            self.assertIn('contradicted_item_limit', checked[0]['lexical_errors'])

    def test_soft_wrap_cannot_fuse_adjacent_numbers_or_break_chinese_words(self):
        for left, right, expected in [('2025.03—2025.06', '3 人课程小组', '2025.03—2025.06 3 人课程小组'),
                                      ('整理 12', '18 个组件', '整理 12 18 个组件'),
                                      ('体验', '割裂。', '体验割裂。'), ('Google', 'Stitch', 'Google Stitch')]:
            lines = [left]
            _append_wrapped(lines, right)
            self.assertEqual(lines, [expected])

    async def test_numeric_guard_rejects_concatenated_date_and_new_063_quantity(self):
        quote = '2025.03—2025.06\n3 人课程小组'
        self.assertEqual(_quantity_units(quote), {('3', '人')})
        self.assertEqual(_quantity_units('调用 20 次'), {('20', '次调用')})
        for text in ('2025.03—2025.063 人课程小组', '063 人课程小组'):
            self.assertTrue(any(e.startswith('unsupported_numbers:') for e in lexical_fact_errors(text, quote)))
            facts = [{'id': 'f1', 'item_id': 'p1', 'text': quote, 'source_quote': quote, 'kind': 'team'}]
            checked = await guard_bullets([{'id': 'b1', 'item_id': 'p1', 'text': text, 'fact_ids': ['f1']}], facts)
            self.assertEqual(checked[0]['verdict'], 'fail')
        self.assertEqual(lexical_fact_errors('3 人课程小组', quote), [])

    def test_spoken_ops_tech_and_single_line_course_keep_extraction_route(self):
        for text in (persona.FIXTURES['ops']['initial'], persona.FIXTURES['tech']['initial'],
                     '课程项目：校园借物 App 概念设计，我负责界面设计。', '公司：示例科技'):
            self.assertFalse(looks_like_existing_resume(text))
            self.assertIsNone(parse_existing_resume(text))


if __name__ == '__main__':
    unittest.main()
