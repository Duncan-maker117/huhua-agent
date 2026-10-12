"""Synthetic archive proposals, fake extractors and encrypted disposable SQL."""
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import test_profile_archive as fixtures
from app.models.profile import ProfileArchiveEvent, ProfileConflict, new_id
from app.services import profile_service as archive
from sqlalchemy import select


class ProfileMemoryRulesTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ArchiveTests.asyncSetUp
    asyncTearDown = fixtures.ArchiveTests.asyncTearDown
    add = fixtures.ArchiveTests.add
    profile = fixtures.ArchiveTests.profile
    event = fixtures.ArchiveTests.event
    run_proposals = fixtures.ArchiveTests.run_proposals
    proposal = fixtures.ArchiveTests.proposal

    async def test_narratives_append_and_merge_sources_against_every_existing_value(self):
        first = '负责接口开发与异常处理并编写完整的回归测试'
        second = '整理需求访谈并设计页面交互流程'
        self.add(field='description', value=first)
        self.event('测试项目：' + second, source_id='new-detail')
        await self.run_proposals([self.proposal(second, field='description')])
        # The repeated fact is the second value, not the legacy slot's first.
        self.event('测试项目：' + second + '。', source_id='same-detail')
        await self.run_proposals([self.proposal(second + '。', field='description')])
        profile = self.profile()
        self.assertEqual(len(profile['facts']), 2)
        self.assertEqual(profile['conflicts'], [])
        repeated = next(f for f in profile['facts'] if f['value'] == second)
        self.assertEqual(repeated['revision'], 1)
        self.assertEqual(len(repeated['sources']), 2)
        with self.factory() as db:
            context = archive.get_context(db, 'a', subject_ids=[f['id'] for f in profile['facts']])
            result = archive.context_to_collected_info(context)
        project = result['projects'][0]
        self.assertIn(first, project['description'])
        self.assertIn(second, project['description'])
        self.assertEqual(len(project['facts']), 2)

    def test_ngram_threshold_is_symmetric_and_protects_polarity_numbers_tools(self):
        old = '负责接口开发与异常处理并编写完整的回归测试'
        new = '负责接口开发与异常处理并编写完善的回归测试'
        self.assertTrue(archive.narrative_duplicate(old, new))
        self.assertTrue(archive.narrative_duplicate(new, old))
        with patch.object(archive, 'NARRATIVE_DUPLICATE_THRESHOLD', 1.0):
            self.assertFalse(archive.narrative_duplicate(old, new))
        self.assertFalse(archive.narrative_duplicate(old, old + '并负责需求访谈与产品原型设计交付'))
        for a, b in [('完成接口开发测试', '未完成接口开发测试'),
                     ('测试响应耗时1.5秒', '测试响应耗时15秒'),
                     ('测试覆盖达到10%', '测试覆盖达到10'),
                     ('使用Python编写完整测试', '使用Java编写完整测试'),
                     ('C++', 'C#'),
                     ('开发接口', '测试接口')]:
            self.assertFalse(archive.narrative_duplicate(a, b), (a, b))

    async def test_all_narrative_categories_append_without_conflicts(self):
        for category in ('project', 'work', 'open_source'):
            with self.subTest(category=category):
                self.add(category=category, field='description', value='整理需求')
                self.add(category=category, field='description', value='编写测试')
        profile = self.profile()
        self.assertEqual(len(profile['facts']), 6)
        self.assertEqual(profile['conflicts'], [])

    async def test_paraphrase_does_not_create_pending_confirmation(self):
        old = '负责接口开发与异常处理并编写完整的回归测试'
        self.add(field='description', value=old)
        value = '负责接口开发与异常处理并编写完善的回归测试'
        self.event('测试项目：' + value)
        await self.run_proposals([self.proposal(value, field='description')])
        fact = self.profile()['facts'][0]
        self.assertEqual(fact['value'], old)
        self.assertEqual(len(fact['sources']), 2)
        self.assertEqual(self.profile()['conflicts'], [])

    async def test_multiple_open_source_summaries_import_together(self):
        self.add(category='open_source', field='summary', value='支持HTTP2解析')
        self.add(category='open_source', field='summary', value='提供异步任务队列')
        profile = self.profile()
        self.assertEqual(len(profile['facts']), 2)
        with self.factory() as db:
            context = archive.get_context(db, 'a', subject_ids=[f['id'] for f in profile['facts']])
            projected = archive.context_to_collected_info(context)
        self.assertIn('支持HTTP2解析', projected['open_source'][0]['summary'])
        self.assertIn('提供异步任务队列', projected['open_source'][0]['summary'])
        self.assertEqual(len(projected['open_source'][0]['facts']), 2)

    async def test_state_progress_add_auto_updates_with_history_notification_and_undo(self):
        fact = self.add(field='status', value='原型阶段')
        self.event('测试项目现在已经上线了')
        await self.run_proposals([self.proposal('已经上线了', field='status')])
        profile = self.profile()
        self.assertEqual(profile['conflicts'], [])
        updated = profile['facts'][0]
        self.assertEqual(updated['history'][0]['value'], '原型阶段')
        self.assertEqual(updated['revision'], fact['revision'] + 1)
        self.assertEqual(profile['updates'][0]['previous_value'], '原型阶段')
        self.assertNotIn('auto_update', updated)
        url = f"/api/profile/facts/{fact['id']}/undo-update"
        denied = await self.client.post(url, json={'expected_revision': updated['revision']}, headers={'x-test-account': 'b'})
        self.assertEqual(denied.status_code, 404)
        response = await self.client.post(url, json={'expected_revision': updated['revision']}, headers={'x-test-account': 'a'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['value'], '原型阶段')
        self.assertEqual(self.profile()['updates'], [])
        with self.factory() as db:
            clean, _ = archive.sanitize_projection(db, 'a', {'projects': [{'name': '测试项目', 'description': '原型阶段'}]})
        self.assertEqual(clean['projects'][0]['description'], '原型阶段')
        repeat = await self.client.post(url, json={'expected_revision': updated['revision']}, headers={'x-test-account': 'a'})
        self.assertEqual(repeat.status_code, 409)

    async def test_explicit_effective_date_updates_even_for_add(self):
        self.add(field='status', value='原型阶段', effective_at=datetime(2026, 8, 1))
        self.event('测试项目在2026-09-01进入内测')
        await self.run_proposals([self.proposal('进入内测', field='status', effective_at=datetime(2026, 9, 1))])
        profile = self.profile()
        self.assertEqual(profile['facts'][0]['value'], '进入内测')
        self.assertEqual(len(profile['updates']), 1)
        self.assertEqual(profile['conflicts'], [])

    async def test_single_value_ambiguity_stays_pending_including_numeric_results(self):
        for index, (field, old, new) in enumerate([
            ('role', '参与者', '负责人'), ('status', '原型', '内测'),
            ('result', '累计10人使用', '累计20人使用'), ('start_date', '2025-01', '2025-02'),
        ]):
            subject = '测试项目' + str(index)
            self.add(subject=subject, field=field, value=old)
            self.event(subject + '：' + new, source_id=subject)
            await self.run_proposals([self.proposal(new, subject=subject, field=field)])
        self.assertEqual(len(self.profile()['conflicts']), 4)
        self.assertEqual(len(self.profile()['facts']), 4)

    async def test_metric_time_signal_updates_and_history_is_not_model_context(self):
        self.add(field='result', value='累计10人使用')
        self.event('测试项目现在累计20人使用')
        await self.run_proposals([self.proposal('累计20人使用', field='result')])
        fact = self.profile()['facts'][0]
        self.assertEqual(fact['value'], '累计20人使用')
        with self.factory() as db:
            context = archive.get_context(db, 'a', subject_ids=[fact['id']])
        self.assertNotIn('history', context['facts'][0])
        self.assertNotIn('10人', str(context))

    async def test_historical_future_other_clause_and_delayed_inputs_do_not_overwrite(self):
        self.add(field='status', value='正在内测', effective_at=datetime(2026, 9, 1))
        for index, (text, value, kwargs) in enumerate([
            ('测试项目以前已经上线', '已经上线', {}),
            ('测试项目计划现在上线', '计划现在上线', {}),
            ('另一个项目现在上线了，测试项目尚未上线', '尚未上线', {}),
            ('测试项目现在关闭了', '关闭了', {'recorded_at': datetime.now() - timedelta(days=30)}),
        ]):
            self.event(text, source_id='delayed-' + str(index), **kwargs)
            await self.run_proposals([self.proposal(value, field='status')])
            self.assertEqual(self.profile()['facts'][0]['value'], '正在内测')
        self.assertEqual(self.profile()['updates'], [])

    async def test_manual_correction_blocks_stale_undo(self):
        fact = self.add(field='status', value='原型')
        self.event('测试项目现在内测')
        await self.run_proposals([self.proposal('内测', field='status')])
        notice = self.profile()['updates'][0]
        with self.factory() as db:
            archive.edit_fact(db, 'a', fact['id'], value='停止维护', expected_revision=notice['revision'])
            db.commit()
        response = await self.client.post(f"/api/profile/facts/{fact['id']}/undo-update",
            json={'expected_revision': notice['revision']}, headers={'x-test-account': 'a'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.profile()['facts'][0]['value'], '停止维护')

    async def test_explicit_narrative_correction_targets_one_of_multiple_values(self):
        first = self.add(field='description', value='编写单元测试')
        self.add(field='description', value='整理用户访谈')
        self.event('更正测试项目，实际是编写集成测试')
        await self.run_proposals([self.proposal('编写集成测试', field='description', operation='correct',
                                              target_fact_id=first['id'], expected_revision=first['revision'])])
        self.assertEqual({f['value'] for f in self.profile()['facts']}, {'编写集成测试', '整理用户访谈'})
        self.assertEqual(self.profile()['conflicts'], [])

    async def test_deleted_narrative_does_not_resurrect_but_new_detail_can_append(self):
        first = self.add(field='description', value='编写单元测试')
        self.add(field='description', value='整理用户访谈')
        with self.factory() as db:
            archive.delete_fact(db, 'a', first['id'], first['revision'])
            db.commit()
        self.event('测试项目编写单元测试并整理产品原型')
        await self.run_proposals([self.proposal('编写单元测试', field='description'),
                                  self.proposal('整理产品原型', field='description')])
        self.assertEqual({f['value'] for f in self.profile()['facts']}, {'整理用户访谈', '整理产品原型'})

    async def test_legacy_migration_keeps_original_and_is_account_scoped_and_idempotent(self):
        old = '负责接口开发与异常处理并编写完整的回归测试'
        fact = self.add(field='description', value=old)
        same = '负责接口开发与异常处理并编写完善的回归测试'
        event_id = self.event('测试项目：' + same)
        with self.factory() as db:
            event = db.get(ProfileArchiveEvent, event_id)
            for proposed in (same, '完成用户访谈与原型设计'):
                conflict = ProfileConflict(id=new_id(), account_id='a', fact_id=fact['id'],
                    event_id=new_id(), expected_revision=fact['revision'], status='pending')
                conflict.payload = archive._seal(conflict, {'current_value': old, 'proposed_value': proposed,
                    'subject': '测试项目', 'field': 'description', 'source_id': event.source_id})
                db.add(conflict)
            db.commit()
        self.profile('b')
        with self.factory() as db:
            self.assertEqual(len(db.scalars(select(ProfileConflict).where(ProfileConflict.status == 'pending')).all()), 2)
        profile = self.profile()
        # Same wording is kept as a mention; a different description becomes
        # another entry of the same item. Nothing is left for the user to confirm.
        self.assertEqual(len(profile['conflicts']), 0)
        values = {fact['value']: fact for fact in profile['facts']}
        self.assertEqual(len(values[old]['sources']), 2)
        self.assertIn('完成用户访谈与原型设计', values)
        with self.factory() as db:
            self.assertEqual(archive.migrate_legacy_narrative_conflicts(db, 'a'), 0)
        self.assertEqual(self.profile()['revision'], profile['revision'])

    async def test_failure_api_has_safe_readable_reason_and_retry(self):
        event_id = self.event('测试项目完成测试')
        with self.factory() as db:
            event = db.get(ProfileArchiveEvent, event_id)
            event.status, event.error_code = 'failed', 'internal-secret-stacktrace'
            db.commit()
        response = await self.client.get('/api/profile', headers={'x-test-account': 'a'})
        self.assertNotIn('internal-secret-stacktrace', response.text)
        task = response.json()['archive_status']['tasks'][0]
        self.assertIn('稍后重试', task['message'])
        self.assertTrue(task['retryable'])
        retried = await self.client.post(f'/api/profile/tasks/{event_id}/retry', json={}, headers={'x-test-account': 'a'})
        self.assertEqual(retried.json()['status'], 'pending')

