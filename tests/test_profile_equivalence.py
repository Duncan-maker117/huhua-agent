"""虚构事实、临时加密库与离线脚本的回归，不连接真实数据或模型。"""

from contextlib import redirect_stdout
from datetime import datetime, timedelta
import hashlib
import io
import json
import sqlite3
import unittest
from unittest.mock import patch

import test_profile_archive as fixtures
from app.models.profile import ProfileArchiveEvent, ProfileConflict, ProfileFact, ProfileSource, new_id
from app.services import profile_service as archive
from app.services.profile_equivalence import equivalent_value, normalize_skill, split_skill_values
from scripts import replay_profile_equivalence as replay


class EquivalenceUnitTests(unittest.TestCase):
    def test_date_formats_precision_and_mood(self):
        for value in ('2027.06', '2027-06', '2027/6', '2027年6月', '2027年06月', '2027.6'):
            with self.subTest(value=value):
                self.assertEqual(equivalent_value('education', 'end_date', '预计2027年6月毕业', value), 'old_more_specific')
                self.assertEqual(equivalent_value('education', 'end_date', value, '预计2027年6月毕业'), 'new_more_specific')
        for old, new, result in [
            ('2027.06', '2027.07', 'different'), ('2026.06', '2027.06', 'different'),
            ('2027', '2027年6月', 'new_more_specific'), ('2027.06', '2027', 'old_more_specific'),
            ('2027/6/1', '2027年6月1日', 'same'), ('2027/6/1', '2027/6/2', 'different'),
            ('2027/6', '2027/6/1', 'new_more_specific'), ('至今', '现在', 'same'),
            ('预计2027.06毕业', '2027年6月已毕业', 'new_more_specific'),
            ('2027年6月已毕业', '预计2027.06毕业', 'old_more_specific'),
            ('2027年6月毕业', '于2027年6月毕业', 'new_more_specific'),
            ('预计2027年6月毕业', '计划于2027年6月毕业', 'same'),
            ('将于2027年6月毕业', '预计于2027年6月毕业', 'same'),
        ]:
            with self.subTest(old=old, new=new):
                self.assertEqual(equivalent_value('education', 'end_date', old, new), result)

    def test_date_failures_and_extra_claims_are_not_equivalent(self):
        for value in ('27年6月', '2027/13', '2027/0', '2027/6/0', '2027/2/30', '预计2027年6月未毕业',
                      '2027年6月毕业率90%', '2027-06至2028-06', '大概明年', '2027年6月使用Python',
                      '2027年6月已经计划毕业'):
            self.assertEqual(equivalent_value('education', 'end_date', value, '2027.06'), 'different', value)
        for category, field in [('awards', 'date'), ('project', 'start'), ('work', 'end'), ('basic', 'custom_date')]:
            self.assertEqual(equivalent_value(category, field, '2027/6', '2027.06'), 'same')

    def test_degree_aliases_are_education_only(self):
        for values in [('本科', '学士', 'Bachelor', 'B.S.', 'BS', 'BE'),
                       ('硕士', '研究生', 'Master', 'M.S.', 'MS'), ('博士', 'PhD', 'Ph.D.'), ('专科', '大专')]:
            for value in values:
                self.assertEqual(equivalent_value('education', 'degree', values[0], value), 'same')
        self.assertEqual(equivalent_value('education', 'degree', '本科', '硕士'), 'different')
        self.assertEqual(equivalent_value('project', 'role', '研究生', '硕士'), 'different')

    def test_school_aliases_do_not_use_ambiguous_subsequences(self):
        for old, new, result in [('哈商大', '哈尔滨商业大学', 'new_more_specific'),
                                 ('哈尔滨商业大学', '哈商大', 'old_more_specific'),
                                 ('哈尔滨商业大学（南校区）', '哈尔滨 商业大学', 'same'),
                                 ('北大', '北京交通大学', 'different'),
                                 ('北大', '北京大学', 'new_more_specific'),
                                 ('北大', '北京工业大学', 'different'),
                                 ('哈尔滨商业大学(联合培养)', '哈尔滨商业大学', 'different')]:
            self.assertEqual(equivalent_value('education', 'school', old, new), result)

    def test_short_fields_keep_numbers_tools_and_negations(self):
        for old, new in [('10人', '20人'), ('1.5秒', '15秒'), ('10%', '10'), ('-10', '10'), ('未完成', '完成'),
                         ('不会Python', '会Python'), ('C++', 'C#'), ('Python', 'Java'),
                         ('Node.js', 'Nodejs'), ('使用2种工具', '使用3种工具')]:
            self.assertEqual(equivalent_value('project', 'role', old, new), 'different', (old, new))
        self.assertEqual(equivalent_value('project', 'role', ' 后端，开发。', '后端开发'), 'same')
        self.assertEqual(equivalent_value('project', 'role', 'PYTHON', 'python'), 'same')

    def test_skill_splitting_aliases_and_proficiency(self):
        items = split_skill_values('熟悉 py / js、ts,langgraph，langchain；fastapi;mysql 和 pg 及 k8s 与 llm 以及 rag + Rust')
        self.assertEqual([item['value'] for item in items], ['Python', 'JavaScript', 'TypeScript', 'LangGraph',
                         'LangChain', 'FastAPI', 'MySQL', 'PostgreSQL', 'Kubernetes', 'LLM', 'RAG', 'Rust'])
        self.assertEqual({item['proficiency'] for item in items}, {'熟悉'})
        self.assertEqual(split_skill_values('熟悉 Python 和精通 RAG'), [
            {'value': 'Python', 'proficiency': '熟悉'}, {'value': 'RAG', 'proficiency': '精通'}])
        self.assertEqual(normalize_skill(' Fast API '), 'fastapi')
        self.assertEqual(split_skill_values(' 自定义工具 ')[0]['value'], '自定义工具')
        self.assertEqual(split_skill_values('Python（精通）'), [{'value': 'Python', 'proficiency': '精通'}])
        self.assertEqual(split_skill_values('熟练使用 Python'), [{'value': 'Python', 'proficiency': '熟练'}])

    def test_protected_technical_names_and_negative_input(self):
        self.assertEqual([item['value'] for item in split_skill_values('C++ + C# / Node.js / CI/CD / TCP/IP')],
                         ['C++', 'C#', 'Node.js', 'CI/CD', 'TCP/IP'])
        for value in ('不会 Python', '不熟悉 RAG', '未使用过 Java', '没有掌握 C++'):
            self.assertEqual(split_skill_values(value), [])
        self.assertEqual(split_skill_values('无监督学习'), [{'value': '无监督学习', 'proficiency': None}])

    def test_skill_proficiency_prefix_does_not_truncate_chinese_words(self):
        for value in ('会议纪要', '会计', '熟练度评估', '了解程度', '掌握程度', '使用过程分析',
                      '会', '熟悉', '精通', '熟练', '掌握', '了解', '使用过', '熟练使用', '（熟悉）'):
            with self.subTest(value=value):
                self.assertEqual(split_skill_values(value), [{'value': value, 'proficiency': None}])

    def test_skill_proficiency_prefix_keeps_explicit_boundaries_and_inheritance(self):
        for word in ('会', '熟悉', '精通', '熟练', '掌握', '了解', '使用过'):
            for gap in ('', ' ', '\t'):
                with self.subTest(word=word, gap=gap):
                    self.assertEqual(split_skill_values(f'{word}{gap}Python 和 RAG'), [
                        {'value': 'Python', 'proficiency': word}, {'value': 'RAG', 'proficiency': word}])
        for value in ('熟练使用 Python', '熟练使用Python'):
            self.assertEqual(split_skill_values(value), [{'value': 'Python', 'proficiency': '熟练'}])
        self.assertEqual(split_skill_values('熟悉 原型设计'), [{'value': '原型设计', 'proficiency': '熟悉'}])

    def test_skill_group_labels_are_removed_per_line(self):
        for value, expected in [
            ('技术：Python / FastAPI', ['Python', 'FastAPI']),
            ('产品：PRD、原型设计', ['PRD', '原型设计']),
            (' 产品：PRD、原型设计\n 技术: Python / FastAPI ', ['PRD', '原型设计', 'Python', 'FastAPI']),
            ('产品: PRD\r\n技术：熟悉 Python', ['PRD', 'Python']),
            ('一二三四五六七八：Python', ['Python']),
        ]:
            with self.subTest(value=value):
                self.assertEqual([item['value'] for item in split_skill_values(value)], expected)

    def test_skill_group_labels_are_short_and_do_not_cross_separators(self):
        value = '一二三四五六七八九：Python'
        self.assertEqual(split_skill_values(value), [{'value': value, 'proficiency': None}])
        for separator in ('/', '、', ',', '，', '；', ';', '+', '\n'):
            with self.subTest(separator=separator):
                self.assertEqual([item['value'] for item in split_skill_values(f'Python{separator}技术：RAG')],
                                 ['Python', 'RAG' if separator == '\n' else '技术：RAG'])

    def test_ab_testing_names_are_protected_with_case_and_spacing(self):
        for value in ('A/B测试', 'A/B 测试', 'A/B Test', 'a/b test', 'a / b TEST',
                      'A / B 测试', 'A/ B测试', 'A /B  Test'):
            with self.subTest(value=value):
                self.assertEqual([item['value'] for item in split_skill_values(f'{value} / Python')],
                                 [value, 'Python'])
        self.assertEqual([item['value'] for item in split_skill_values('A/B')], ['A', 'B'])

    def test_chinese_skill_phrases_keep_conjunctions(self):
        for value in ('数据分析与可视化', '用户研究和需求分析', '数据分析及可视化',
                      '用户研究以及需求分析', '数据分析 与 可视化', '用户研究 以及 需求分析', '普及推广'):
            with self.subTest(value=value):
                self.assertEqual(split_skill_values(value), [{'value': value, 'proficiency': None}])

    def test_skill_conjunctions_split_next_to_ascii_names(self):
        for conjunction in ('和', '及', '与', '以及'):
            for gap in ('', ' ', '\t'):
                for left, right in (('Python', 'RAG'), ('Python', '原型设计'), ('原型设计', 'RAG'),
                                    ('C++', '原型设计'), ('原型设计', '.NET')):
                    with self.subTest(conjunction=conjunction, gap=gap, left=left, right=right):
                        value = f'{left}{gap}{conjunction}{gap}{right}'
                        self.assertEqual([item['value'] for item in split_skill_values(value)], [left, right])
        self.assertEqual(split_skill_values('熟悉 Python和FastAPI'), [
            {'value': 'Python', 'proficiency': '熟悉'}, {'value': 'FastAPI', 'proficiency': '熟悉'}])

    def test_skill_symbol_separators_still_split_chinese_names(self):
        for separator in ('/', '、', ',', '，', '；', ';', '+', '\n'):
            with self.subTest(separator=separator):
                self.assertEqual([item['value'] for item in split_skill_values(f'原型设计{separator}数据分析')],
                                 ['原型设计', '数据分析'])


class ProfileEquivalenceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ArchiveTests.asyncSetUp
    asyncTearDown = fixtures.ArchiveTests.asyncTearDown
    add = fixtures.ArchiveTests.add
    profile = fixtures.ArchiveTests.profile
    event = fixtures.ArchiveTests.event
    run_proposals = fixtures.ArchiveTests.run_proposals
    proposal = fixtures.ArchiveTests.proposal

    def legacy(self, value, *, category='skill', field='skill', subject='技能', account='a'):
        event_id = self.event(value, account=account, source_id=new_id())
        with self.factory() as db:
            event = db.get(ProfileArchiveEvent, event_id)
            source = db.get(ProfileSource, event.source_id)
            row = ProfileFact(id=new_id(), account_id=account, category=category, status='active', revision=1,
                              slot_key=archive._key(account, [category, subject, field]))
            row.payload = archive._seal(row, {'subject': subject, 'field': field, 'value': value,
                'source_ids': [source.id], 'recorded_at': archive._iso(source.recorded_at),
                'last_mentioned_at': archive._iso(source.recorded_at), 'history': [], 'effective_at': None})
            db.add(row)
            event.status = 'completed'
            db.commit()
            return row.id

    def conflict(self, fact_id, proposed, *, revision=None, disabled=False):
        event_id = self.event(proposed, source_id=new_id())
        with self.factory() as db:
            fact, event = db.get(ProfileFact, fact_id), db.get(ProfileArchiveEvent, event_id)
            old = archive._open(fact)
            row = ProfileConflict(id=new_id(), account_id='a', fact_id=fact_id,
                event_id=event_id, expected_revision=revision or fact.revision, status='pending')
            row.payload = archive._seal(row, {'subject': old['subject'], 'field': old['field'],
                'current_value': old['value'], 'proposed_value': proposed, 'source_id': event.source_id})
            db.add(row)
            event.status = 'completed'
            if disabled:
                db.get(ProfileSource, event.source_id).disabled = True
            db.commit()
            return row.id

    async def test_planned_date_kept_and_different_month_conflicts(self):
        self.add(category='education', subject='测试大学', field='end_date', value='预计2027年6月毕业')
        for index, value in enumerate(('2027.06', '2027.07')):
            self.event('测试大学 ' + value, source_id=str(index))
            await self.run_proposals([self.proposal(value, category='education', subject='测试大学', field='end_date')])
            profile = self.profile()
            self.assertEqual(profile['facts'][0]['value'], '预计2027年6月毕业')
            self.assertEqual(len(profile['conflicts']), index)

    async def test_date_refine_history_and_undo(self):
        fact = self.add(category='education', subject='测试大学', field='end_date', value='预计2027.06毕业')
        self.event('测试大学2027年6月已毕业')
        await self.run_proposals([self.proposal('2027年6月已毕业', category='education', subject='测试大学', field='end_date')])
        profile = self.profile()
        updated = profile['facts'][0]
        self.assertEqual(updated['value'], '2027年6月已毕业')
        self.assertEqual(updated['history'][0]['reason'], 'refine')
        self.assertEqual(profile['conflicts'], [])
        self.assertEqual(len(profile['updates']), 1)
        with self.factory() as db:
            undone = archive.undo_fact_update(db, 'a', fact['id'], expected_revision=updated['revision'])
            db.commit()
        self.assertEqual(undone['value'], fact['value'])
        self.assertEqual(self.profile()['updates'], [])

    async def test_degree_and_school_integration(self):
        self.add(category='education', subject='学校', field='degree', value='本科')
        self.add(category='education', subject='学校', field='school', value='哈商大')
        self.event('学校 学士 哈尔滨商业大学')
        await self.run_proposals([self.proposal(value, category='education', subject='学校', field=field)
                                 for field, value in [('degree', '学士'), ('school', '哈尔滨商业大学')]])
        values = {fact['field']: fact['value'] for fact in self.profile()['facts']}
        self.assertEqual(values, {'degree': '本科', 'school': '哈尔滨商业大学'})
        self.assertEqual(self.profile()['conflicts'], [])

    async def test_skills_are_set_across_subjects_and_project_flat(self):
        self.add(category='skill', subject='技术', field='skill', value='Python / FastAPI / LangGraph')
        self.event('会 Python 和 RAG')
        await self.run_proposals([self.proposal('会 Python 和 RAG', category='skill', subject='能力', field='tool')])
        profile = self.profile()
        self.assertEqual({fact['value'] for fact in profile['facts']}, {'Python', 'FastAPI', 'LangGraph', 'RAG'})
        self.assertEqual(profile['conflicts'], [])
        self.event('py / PYTHON / fastapi', source_id='repeat')
        await self.run_proposals([self.proposal('py / PYTHON / fastapi', category='skill', field='skill')])
        profile = self.profile()
        self.assertEqual(len(profile['facts']), 4)
        with self.factory() as db:
            context = archive.get_context(db, 'a', subject_ids=[fact['id'] for fact in profile['facts']])
        projected = archive.context_to_collected_info(context, {'skills': ['python', 'py']})
        self.assertEqual(len(projected['skills']), 4)
        self.assertEqual({normalize_skill(value['name'] if isinstance(value, dict) else value)
                          for value in projected['skills']}, {'python', 'fastapi', 'langgraph', 'rag'})

    async def test_skill_proficiency_update_undo_and_following_mention(self):
        fact = self.add(category='skill', subject='技能', field='skill', value='熟悉 Python')
        self.event('精通 Python')
        await self.run_proposals([self.proposal('精通 Python', category='skill', subject='技能', field='skill')])
        updated = self.profile()['facts'][0]
        self.assertEqual(updated['value'], 'Python')
        self.assertEqual(updated['proficiency'], '精通')
        self.assertEqual(updated['history'][0]['proficiency'], '熟悉')
        self.assertEqual(updated['update']['previous_proficiency'], '熟悉')
        with self.factory() as db:
            projected, _ = archive.sanitize_projection(db, 'a', {'skills': ['Python']})
            self.assertEqual(projected['skills'], ['Python'])
            undone = archive.undo_fact_update(db, 'a', fact['id'], expected_revision=updated['revision'])
            db.commit()
        self.assertEqual(undone['proficiency'], '熟悉')
        self.event('Python', source_id='after-undo')
        await self.run_proposals([self.proposal('Python', category='skill', subject='技能', field='skill')])
        self.assertEqual(len(self.profile()['facts'][0]['sources']), 2)
        self.assertEqual(self.profile()['conflicts'], [])

    async def test_manual_proficiency_correction_preserves_future_mentions(self):
        fact = self.add(category='skill', subject='技能', field='skill', value='熟悉 Python')
        with self.factory() as db:
            updated = archive.edit_fact(db, 'a', fact['id'], value='了解 py', expected_revision=fact['revision'])
            db.commit()
        self.assertEqual(updated['proficiency'], '了解')
        self.event('Python')
        await self.run_proposals([self.proposal('Python', category='skill', field='skill')])
        self.assertEqual(len(self.profile()['facts'][0]['sources']), 2)
        self.assertEqual(self.profile()['facts'][0]['proficiency'], '了解')

    async def test_skill_duplicate_does_not_change_revision_and_stale_proficiency_cannot_overwrite(self):
        fact = self.add(category='skill', subject='技能', field='skill', value='精通 Python')
        self.event('熟悉 Python', recorded_at=datetime.now() - timedelta(days=30))
        await self.run_proposals([self.proposal('熟悉 Python', category='skill', field='skill')])
        updated = self.profile()['facts'][0]
        self.assertEqual(updated['proficiency'], '精通')
        self.assertEqual(updated['revision'], fact['revision'])
        self.assertEqual(len(updated['sources']), 2)
        self.assertEqual(self.profile()['conflicts'], [])

    async def test_skill_negation_and_deleted_alias_do_not_resurrect(self):
        fact = self.add(category='skill', subject='技能', field='skill', value='Python')
        self.event('不会 Python')
        await self.run_proposals([self.proposal('不会 Python', category='skill', field='skill')])
        self.assertEqual(len(self.profile()['facts']), 1)
        with self.factory() as db:
            archive.delete_fact(db, 'a', fact['id'], fact['revision'])
            db.commit()
        self.event('会 py 和 RAG', source_id='deleted')
        await self.run_proposals([self.proposal('会 py 和 RAG', category='skill', field='skill')])
        self.assertEqual([fact['value'] for fact in self.profile()['facts']], ['RAG'])
        self.assertEqual(self.profile()['conflicts'], [])

    async def test_explicit_skill_correction_updates_identity(self):
        fact = self.add(category='skill', subject='技能', field='skill', value='Python')
        self.event('更正技能，实际是 Java')
        await self.run_proposals([self.proposal('Java', category='skill', subject='技能', field='skill',
            operation='correct', target_fact_id=fact['id'], expected_revision=fact['revision'])])
        profile = self.profile()
        self.assertEqual([fact['value'] for fact in profile['facts']], ['Java'])
        self.event('Java', source_id='corrected')
        await self.run_proposals([self.proposal('Java', category='skill', field='skill')])
        self.assertEqual(len(self.profile()['facts']), 1)

    async def test_legacy_bundles_and_conflicts_migrate_once_and_account_scoped(self):
        skill_id = self.legacy('Python / FastAPI / LangGraph')
        conflict_id = self.conflict(skill_id, '会 Python 和 RAG')
        date_id = self.legacy('预计2027年6月毕业', category='education', field='end_date', subject='虚构大学')
        date_conflict = self.conflict(date_id, '2027.06')
        school_id = self.legacy('哈商大', category='education', field='school', subject='虚构大学')
        school_conflict = self.conflict(school_id, '哈尔滨商业大学')
        self.profile('b')
        with self.factory() as db:
            self.assertEqual(db.get(ProfileConflict, conflict_id).status, 'pending')
        profile = self.profile()
        self.assertEqual(len([fact for fact in profile['facts'] if fact['category'] == 'skill']), 4)
        self.assertEqual(profile['conflicts'], [])
        self.assertIn('预计2027年6月毕业', [fact['value'] for fact in profile['facts']])
        self.assertIn('哈尔滨商业大学', [fact['value'] for fact in profile['facts']])
        with self.factory() as db:
            for conflict in (conflict_id, date_conflict, school_conflict):
                self.assertEqual(db.get(ProfileConflict, conflict).status, 'equivalent')
            self.assertEqual(archive.migrate_legacy_skill_facts(db, 'a'), 0)
            self.assertEqual(archive.migrate_legacy_equivalent_conflicts(db, 'a'), 0)
        self.assertEqual(self.profile(), profile)

    async def test_migration_keeps_real_stale_and_disabled_conflicts(self):
        fact_id = self.legacy('2027.06', category='education', field='end_date', subject='虚构大学')
        conflicts = [self.conflict(fact_id, '2027.07'), self.conflict(fact_id, '2027年6月', revision=8),
                     self.conflict(fact_id, '预计2027年6月毕业', disabled=True)]
        self.profile()
        with self.factory() as db:
            self.assertEqual([db.get(ProfileConflict, value).status for value in conflicts], ['pending'] * 3)

    async def test_refinement_migration_keeps_other_real_conflicts_reviewable(self):
        fact_id = self.legacy('2027.06', category='education', field='end_date', subject='测试大学')
        refined = self.conflict(fact_id, '预计2027年6月毕业')
        different = self.conflict(fact_id, '2027.07')
        profile = self.profile()
        self.assertEqual(profile['facts'][0]['value'], '预计2027年6月毕业')
        self.assertEqual([conflict['id'] for conflict in profile['conflicts']], [different])
        self.assertEqual(profile['conflicts'][0]['expected_revision'], profile['facts'][0]['revision'])
        with self.factory() as db:
            self.assertEqual(db.get(ProfileConflict, refined).status, 'equivalent')
            self.assertEqual(db.get(ProfileConflict, different).status, 'pending')
        self.assertEqual(self.profile(), profile)

    async def test_skill_migration_conflicts_require_matching_revision_and_enabled_source(self):
        fact = self.add(category='skill', subject='技能', field='skill', value='Python')
        stale = self.conflict(fact['id'], 'RAG', revision=9)
        disabled = self.conflict(fact['id'], 'LangGraph', disabled=True)
        profile = self.profile()
        self.assertEqual([fact['value'] for fact in profile['facts']], ['Python'])
        with self.factory() as db:
            self.assertEqual(db.get(ProfileConflict, stale).status, 'pending')
            self.assertEqual(db.get(ProfileConflict, disabled).status, 'pending')
        self.assertEqual(self.profile(), profile)

    async def test_stale_skill_migration_cannot_overwrite_manual_correction(self):
        fact_id = self.legacy('Python / RAG')
        with self.factory() as stale:
            cached = stale.get(ProfileFact, fact_id)
            with self.factory() as fresh:
                archive.edit_fact(fresh, 'a', fact_id, value='Java', expected_revision=1)
                fresh.commit()
            self.assertEqual(cached.revision, 1)
            with self.assertRaises(archive.ProfileRevisionConflict):
                archive.migrate_legacy_skill_facts(stale, 'a')
            stale.rollback()
        self.assertEqual([fact['value'] for fact in self.profile()['facts']], ['Java'])

    async def test_migration_deduplicates_existing_skills_and_respects_deletion(self):
        deleted = self.add(category='skill', subject='技能', field='skill', value='Python')
        self.add(category='skill', subject='技能', field='skill', value='FastAPI')
        with self.factory() as db:
            archive.delete_fact(db, 'a', deleted['id'], deleted['revision'])
            db.commit()
        self.legacy('py / FastAPI / RAG')
        profile = self.profile()
        self.assertEqual({fact['value'] for fact in profile['facts']}, {'FastAPI', 'RAG'})
        self.assertEqual(self.profile(), profile)

    async def test_legacy_proficiency_update_keeps_all_source_references(self):
        self.add(category='skill', subject='技能', field='skill', value='熟悉 Python')
        self.legacy('精通 py / RAG')
        profile = self.profile()
        fact = next(fact for fact in profile['facts'] if fact['value'] == 'Python')
        self.assertEqual(fact['proficiency'], '精通')
        self.assertEqual(fact['history'][0]['proficiency'], '熟悉')
        self.assertEqual([source['excerpt'] for source in fact['sources']], ['精通 py / RAG'])
        self.assertEqual(self.profile(), profile)

    async def test_offline_repeated_alias_bundle_counts_as_one_expected_item(self):
        self.legacy('py / Python / PYTHON')
        counts = replay.replay(self.path, self.crypto)
        self.assertEqual(counts['skill_bundles'], 1)
        self.assertEqual(counts['skill_bundle_expected_items'], 1)
        self.assertEqual(counts['skill_expected_items'], 1)

    async def test_offline_script_is_read_only_and_only_outputs_counts(self):
        self.legacy('Python / FastAPI / LangGraph')
        fact_id = self.legacy('预计2027年6月毕业', category='education', field='end_date', subject='private-marker')
        self.conflict(fact_id, '2027.06')
        self.conflict(fact_id, '2027.07')
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        connect = sqlite3.connect

        def read_only(database, **kwargs):
            self.assertTrue(database.endswith('?mode=ro'))
            self.assertTrue(kwargs['uri'])
            db = connect(database, **kwargs)
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("UPDATE profile_facts SET status = 'deleted'")
            return db

        stream = io.StringIO()
        with patch.object(replay.sqlite3, 'connect', side_effect=read_only), patch.object(replay, 'crypto_from_settings', return_value=self.crypto), patch('app.config.Settings') as settings, redirect_stdout(stream):
            self.assertEqual(replay.replay(self.path, self.crypto)['pending_total'], 2)
            self.assertEqual(replay.main([str(self.path)]), 0)
            settings.assert_called_once_with(_env_file=None)
        output = stream.getvalue()
        counts = json.loads(output)
        self.assertEqual(counts['pending_total'], 2)
        self.assertEqual(counts['equivalence']['old_more_specific'], 1)
        self.assertEqual(counts['equivalence']['different'], 1)
        self.assertEqual(counts['skill_bundles'], 1)
        self.assertEqual(counts['skill_bundle_expected_items'], 3)
        self.assertEqual(counts['by_category_field']['education/end_date']['different'], 1)
        for value in ('Python', '2027', 'private-marker', str(self.path)):
            self.assertNotIn(value, output)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    async def test_offline_failure_does_not_print_private_exception(self):
        stream = io.StringIO()
        with patch.object(replay, 'replay', side_effect=ValueError('private-marker')), patch.object(replay, 'crypto_from_settings'), patch('app.config.Settings'), redirect_stdout(stream):
            self.assertEqual(replay.main([str(self.path)]), 1)
        self.assertEqual(json.loads(stream.getvalue()), {'errors': 1})
