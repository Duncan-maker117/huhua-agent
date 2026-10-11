"""Fact/document boundaries use disposable encrypted SQL and checkpoint stores."""
import copy
import hashlib
import unittest

from sqlalchemy import create_engine, inspect, text

import test_product_security_flow as fixtures
from app.agents.resume_graph import _serialize_to_resume_data
from app.services.canonical_resume import ResumeSaveUnavailable, resume_revision, save_canonical_resume
from app.services.profile_bridge import prepare_graph_context, sanitize_fact_history
from app.services.resume_facts import normalize_fact_store
from app.services.schema_migrations import migrate_schema, require_current_schema
from app.services.session_store import load_resume_session, save_resume_session, SessionStorageUnavailable


class FactDraftStorageTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ProductSecurityFlow.asyncSetUp
    cleanup = fixtures.ProductSecurityFlow.cleanup
    login = fixtures.ProductSecurityFlow.login
    fixture = fixtures.ProductSecurityFlow.fixture

    async def master(self):
        sid, data = await self.fixture()
        facts = normalize_fact_store(copy.deepcopy(data))
        data['projects'][0]['item_id'] = facts['projects'][0]['item_id']
        save_resume_session(sid, data, stage='EVALUATING', collected_info=facts,
                            resume_meta={'marker': 'committed'}, resume_versions=[])
        await self.graph.aupdate_state({'configurable': {'thread_id': sid}},
            {'resume_data': data, 'collected_info': facts, 'resume_meta': {'marker': 'committed'},
             'resume_versions': []}, as_node='building')
        return sid, data, facts

    async def save(self, sid, old, data, **kwargs):
        return await save_canonical_resume(sid, resume_revision(old), data, self.graph,
                                          _serialize_to_resume_data, **kwargs)

    async def test_writer_and_restore_keep_master_editor_adds_and_delete_keeps_facts(self):
        sid, data, facts = await self.master()
        polished = copy.deepcopy(data)
        polished['projects'][0]['polished_bullets'] = ['整理需求并形成清单']
        saved = await self.save(sid, data, polished, source='writer', collected_info={'projects': []})
        self.assertEqual(load_resume_session(sid)['collected_info'], facts)
        edited = copy.deepcopy(saved['data'])
        edited['projects'][0]['polished_bullets'].append('补充编写接口测试')
        saved = await self.save(sid, saved['data'], edited)
        new_facts = load_resume_session(sid)['collected_info']
        added = next(f for f in new_facts['projects'][0]['facts'] if f['text'] == '补充编写接口测试')
        self.assertEqual(added['source'], 'editor')
        self.assertEqual(added['source_quote'], '补充编写接口测试')
        deleted = copy.deepcopy(saved['data'])
        deleted['projects'][0]['polished_bullets'] = []
        await self.save(sid, saved['data'], deleted)
        self.assertEqual(load_resume_session(sid)['collected_info'], new_facts)
        await self.save(sid, deleted, polished, source='restore')
        self.assertEqual(load_resume_session(sid)['collected_info'], new_facts)

    async def test_failure_rolls_back_document_master_metadata_and_versions(self):
        sid, data, _ = await self.master()
        before = load_resume_session(sid)
        config = {'configurable': {'thread_id': sid}}
        old_checkpoint = copy.deepcopy((await self.graph.aget_state(config)).values)
        changed = copy.deepcopy(data)
        changed['projects'][0]['polished_bullets'] = ['新增未提交文字']
        def fail(*_):
            raise RuntimeError('synthetic commit boundary failure')
        with self.assertRaises(ResumeSaveUnavailable):
            await self.save(sid, data, changed, resume_meta={'marker': 'uncommitted'},
                            resume_versions=[{'resume_data': changed}], after_save=fail)
        after = load_resume_session(sid)
        for key in ('resume_data', 'collected_info', 'resume_meta', 'resume_versions'):
            self.assertEqual(after[key], before[key])
            self.assertEqual((await self.graph.aget_state(config)).values.get(key), old_checkpoint.get(key))

    async def test_sql_whole_state_repairs_ahead_checkpoint_and_is_encrypted(self):
        sid, data, facts = await self.master()
        config = {'configurable': {'thread_id': sid}}
        await self.graph.aupdate_state(config, {'resume_data': {'bad': 'uncommitted'},
            'collected_info': {'bad': 'uncommitted'}, 'resume_meta': {'bad': 'uncommitted'},
            'resume_versions': [{'bad': 'uncommitted'}]}, as_node='building')
        await prepare_graph_context('account:' + self.account_a, sid, self.graph)
        state = (await self.graph.aget_state(config)).values
        self.assertEqual(state['resume_data'], data)
        self.assertEqual(state['collected_info'], facts)
        self.assertEqual(state['resume_meta'], load_resume_session(sid)['resume_meta'])
        self.assertEqual(state['resume_meta']['marker'], 'committed')
        self.assertEqual(state['resume_versions'], [])
        with self.engine.connect() as conn:
            raw = conn.execute(text('SELECT resume_state FROM resume_sessions WHERE session_id=:sid'), {'sid': sid}).scalar()
        self.assertNotIn('参与需求整理', raw)
        self.assertNotIn('committed', raw)
        self.assertTrue(load_resume_session(sid)['has_authoritative_state'])

    async def test_server_ids_register_but_cross_session_ids_and_forged_editor_ids_fail(self):
        sid, data, facts = await self.master()
        other, other_data = await self.fixture()
        with self.assertRaises(SessionStorageUnavailable):
            save_resume_session(other, data, stage='EVALUATING', collected_info=facts)
        forged = copy.deepcopy(data)
        forged['projects'][0]['item_id'] = 'client-invented'
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            await self.save(sid, data, forged)
        self.assertEqual(load_resume_session(other)['resume_data'], other_data)

    async def test_explicit_draft_item_removal_does_not_delete_master(self):
        sid, data, facts = await self.master()
        deleted = copy.deepcopy(data)
        deleted['projects'] = []
        await self.save(sid, data, deleted, removed_item_ids=[data['projects'][0]['item_id']])
        self.assertEqual(load_resume_session(sid)['collected_info']['projects'], facts['projects'])

    async def test_disabled_turn_removes_facts_notes_and_history(self):
        from app.services.profile_service import enqueue_archive_event, disable_source
        from app.services.profile_bridge import purge_invalidated_copies
        sid, data, facts = await self.master()
        item = facts['projects'][0]
        fact = item['facts'][0]
        fact['turn_id'] = 'turn-to-forget'
        line = fact['text']
        data['projects'][0]['polished_bullets'] = [line]
        meta = {'bullets': {item['item_id']: [{'fact_ids': [fact['id']],
                 'text_hash': hashlib.sha256(line.encode()).hexdigest()}]}}
        save_resume_session(sid, data, stage='EVALUATING', collected_info=facts, resume_meta=meta,
                            resume_versions=[{'resume_data': copy.deepcopy(data), 'resume_meta': copy.deepcopy(meta)}])
        with self.factory() as db:
            enqueue_archive_event(db, self.account_a, 'turn-to-forget', sid,
                                  {'human_text': line, 'source_kind': 'self'})
            disable_source(db, self.account_a, 'turn-to-forget', original_id=True)
            db.commit()
        await purge_invalidated_copies('account:' + self.account_a, self.graph)
        stored = load_resume_session(sid)
        self.assertNotIn(fact['id'], [entry['id'] for entry in stored['collected_info']['projects'][0]['facts']])
        self.assertEqual(stored['collected_info']['projects'][0]['raw_notes'], [])
        self.assertNotIn(line, str(stored['resume_versions']))
        self.assertEqual(stored['resume_data']['projects'][0]['polished_bullets'], [])

    async def test_import_into_existing_fact_master_adds_writer_visible_evidence(self):
        from app.services.resume_facts import active_facts_for_writer
        sid, data, facts = await self.master()
        response = await self.a.post('/api/profile/facts', json={
            'category': 'project', 'subject': '课程工具', 'field': 'result', 'value': '整理交付清单'})
        profile_fact = response.json()['facts'][0]
        imported = await self.a.post(f'/api/resume/session/{sid}/profile-facts', json={'fact_ids': [profile_fact['id']]})
        self.assertEqual(imported.status_code, 200, imported.text)
        stored = load_resume_session(sid)
        evidence = active_facts_for_writer(stored['collected_info'])['projects'][0]['facts']
        added = next(entry for entry in evidence if entry['text'] == '整理交付清单')
        self.assertEqual(added['source'], 'import')
        self.assertEqual(added['profile_refs'], [{'fact_id': profile_fact['id'], 'revision': profile_fact['revision']}])
        await self.a.delete(f"/api/profile/facts/{profile_fact['id']}?expected_revision={profile_fact['revision']}")
        self.assertNotIn('整理交付清单', str(active_facts_for_writer(load_resume_session(sid)['collected_info'])))

    async def test_profile_bound_fact_invalidation_clears_quotes_and_old_versions(self):
        from app.services.profile_bridge import prepare_graph_context
        sid, _ = await self.fixture()
        response = await self.a.post('/api/profile/facts', json={
            'category': 'project', 'subject': '来源项目', 'field': 'description', 'value': '参与整理需求'})
        profile_fact = response.json()['facts'][0]
        imported = await self.a.post(f'/api/resume/session/{sid}/profile-facts', json={'fact_ids': [profile_fact['id']]})
        self.assertEqual(imported.status_code, 200, imported.text)
        stored = load_resume_session(sid)
        facts = normalize_fact_store(stored['collected_info'])
        item = next(x for x in facts['projects'] if x.get('name') == '来源项目')
        data = stored['resume_data']
        target = next(x for x in data['projects'] if x.get('name') == '来源项目')
        target['polished_bullets'] = ['参与梳理需求']
        meta = {'bullets': {item['item_id']: [{'fact_ids': [item['facts'][0]['id']],
                'text_hash': hashlib.sha256('参与梳理需求'.encode()).hexdigest()}]}}
        save_resume_session(sid, data, stage='EVALUATING', collected_info=facts, resume_meta=meta,
                            resume_versions=[{'resume_data': copy.deepcopy(data), 'resume_meta': copy.deepcopy(meta)}])
        response = await self.a.delete(f"/api/profile/facts/{profile_fact['id']}?expected_revision={profile_fact['revision']}")
        self.assertEqual(response.status_code, 200, response.text)
        stored = load_resume_session(sid)
        self.assertNotIn('参与整理需求', str(stored['collected_info']))
        self.assertNotIn('参与梳理需求', str(stored['resume_versions']))
        await prepare_graph_context('account:' + self.account_a, sid, self.graph)
        self.assertNotIn('参与整理需求', str((await self.graph.aget_state({'configurable': {'thread_id': sid}})).values['collected_info']))


class FactHistoryTests(unittest.TestCase):
    def test_deleted_fact_cannot_return_through_version_bullets_or_metadata(self):
        text_value = '已失效经历'
        draft = {'projects': [{'item_id': 'i1', 'polished_bullets': [text_value, '手写独立内容']}]}
        meta = {'bullets': {'i1': [{'fact_ids': ['f1'], 'text_hash': hashlib.sha256(text_value.encode()).hexdigest()}]}}
        state = {'collected_info': {'projects': [{'facts': [{'id': 'f1', 'status': 'deleted'}]}]},
                 'resume_data': draft, 'resume_meta': meta,
                 'resume_versions': [{'resume_data': copy.deepcopy(draft), 'resume_meta': copy.deepcopy(meta)}]}
        clean = sanitize_fact_history(state)
        for version in [clean, *clean['resume_versions']]:
            self.assertEqual(version['resume_data']['projects'][0]['polished_bullets'], ['手写独立内容'])
            self.assertEqual(version['resume_meta']['bullets']['i1'], [])

    def test_inactive_facts_clean_legacy_prose_and_education_without_metadata(self):
        state = {'collected_info': {
                    'projects': [{'item_id': 'p1', 'facts': [{'id': 'f1', 'text': '上线 PaperTool', 'source_quote': '上线 PaperTool', 'status': 'deleted'}]}],
                    'education': [{'item_id': 'e1', 'facts': [{'id': 'f2', 'text': 'Old College', 'source_quote': 'Old College', 'field': 'school', 'status': 'superseded'}]}]},
                 'resume_data': {'projects': [{'item_id': 'p1', 'name': '工具', 'description': '上线 PaperTool',
                                               'polished_bullets': ['上线了 PaperTool', '整理接口测试']}],
                                 'education': [{'item_id': 'e1', 'school': 'Old College', 'major': '计算机'}]},
                 'resume_meta': {}, 'resume_draft': '上线 PaperTool，Old College'}
        state['resume_versions'] = [{'resume_data': copy.deepcopy(state['resume_data']), 'resume_meta': {}}]
        cleaned = sanitize_fact_history(state)
        self.assertNotIn('PaperTool', str(cleaned['resume_data']))
        self.assertNotIn('Old College', str(cleaned['resume_versions']))
        self.assertNotIn('Old College', cleaned['resume_draft'])
        self.assertEqual(cleaned['resume_data']['projects'][0]['polished_bullets'], ['整理接口测试'])
        self.assertEqual(cleaned['resume_data']['education'][0]['major'], '计算机')

    def test_summary_citation_invalidation_clears_current_and_history(self):
        summary = '具备独立负责整体架构交付的经验'
        fact = {'id': 'f1', 'text': '主导系统架构', 'source_quote': '主导系统架构', 'status': 'superseded'}
        meta = {'summary': {'fact_ids': ['f1'], 'text_hash': hashlib.sha256(summary.encode()).hexdigest()}}
        state = {'collected_info': {'projects': [{'item_id': 'p1', 'facts': [fact]}]},
                 'resume_data': {'self_evaluation': summary}, 'resume_meta': meta,
                 'resume_draft': summary,
                 'resume_versions': [{'resume_data': {'self_evaluation': summary}, 'resume_meta': copy.deepcopy(meta)}]}
        cleaned = sanitize_fact_history(state)
        self.assertEqual(cleaned['resume_data']['self_evaluation'], '')
        self.assertNotIn('summary', cleaned['resume_meta'])
        self.assertNotIn(summary, cleaned['resume_draft'])
        self.assertEqual(cleaned['resume_versions'][0]['resume_data']['self_evaluation'], '')

    def test_legacy_summary_and_master_copy_cannot_revive_deleted_claim(self):
        fact = {'id': 'f1', 'text': '上线PaperTool并获得100万用户',
                'source_quote': '上线PaperTool并获得100万用户', 'status': 'deleted'}
        summary = '上线了PaperTool并获得100万用户'
        state = {'collected_info': {'projects': [{'item_id': 'p1', 'facts': [fact]}],
                                   'personal_summary': summary, 'self_evaluation': summary},
                 'resume_data': {'self_evaluation': summary}, 'resume_meta': {},
                 'resume_versions': [{'resume_data': {'self_evaluation': summary}, 'resume_meta': {}}]}
        cleaned = sanitize_fact_history(state)
        self.assertEqual(cleaned['collected_info']['personal_summary'], '')
        self.assertEqual(cleaned['collected_info']['self_evaluation'], '')
        self.assertEqual(cleaned['resume_data']['self_evaluation'], '')
        self.assertEqual(cleaned['resume_versions'][0]['resume_data']['self_evaluation'], '')

    def test_manual_summary_rewrite_invalidates_metadata_without_deleting_independent_text(self):
        current = '整理用户反馈并分类'
        original = '负责旧系统架构'
        state = {'collected_info': {'projects': [{'item_id': 'p1', 'facts': [
                    {'id': 'f1', 'text': original, 'source_quote': original, 'status': 'deleted'}]}]},
                 'resume_data': {'self_evaluation': current},
                 'resume_meta': {'summary': {'fact_ids': ['f1'], 'text_hash': hashlib.sha256(original.encode()).hexdigest()}}}
        cleaned = sanitize_fact_history(state)
        self.assertEqual(cleaned['resume_data']['self_evaluation'], current)
        self.assertNotIn('summary', cleaned['resume_meta'])

    def test_edited_text_invalidates_only_its_old_metadata(self):
        old = '原文'
        state = {'collected_info': {'projects': [{'facts': [{'id': 'f1', 'status': 'active'}]}]},
                 'resume_data': {'projects': [{'item_id': 'i1', 'polished_bullets': ['用户修改文字']}]},
                 'resume_meta': {'bullets': {'i1': [{'fact_ids': ['f1'], 'text_hash': hashlib.sha256(old.encode()).hexdigest()}]}}}
        clean = sanitize_fact_history(state)
        self.assertEqual(clean['resume_data'], state['resume_data'])
        self.assertEqual(clean['resume_meta']['bullets']['i1'], [])

    def test_old_schema_rejected_until_explicit_migration(self):
        engine = create_engine('sqlite://')
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE resume_sessions (session_id VARCHAR PRIMARY KEY, owner_key VARCHAR, version INTEGER)'))
            conn.execute(text('CREATE TABLE schema_versions (component VARCHAR PRIMARY KEY, version INTEGER)'))
            conn.execute(text("INSERT INTO schema_versions VALUES ('product_profile', 1)"))
        with self.assertRaises(RuntimeError):
            require_current_schema(engine)
        self.assertNotIn('resume_state', {c['name'] for c in inspect(engine).get_columns('resume_sessions')})
        migrate_schema(engine, allow_legacy=True)
        require_current_schema(engine)
        self.assertIn('resume_state', {c['name'] for c in inspect(engine).get_columns('resume_sessions')})
        engine.dispose()
