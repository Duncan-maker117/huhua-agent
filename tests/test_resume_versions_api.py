"""Version undo and encrypted current constraints on disposable local stores."""
import copy
import unittest
from unittest.mock import patch

from sqlalchemy import text
import test_product_security_flow as fixtures
from app.agents.resume_graph import _serialize_to_resume_data
from app.services.canonical_resume import resume_revision, save_canonical_resume, ResumeSaveUnavailable
from app.services.profile_bridge import prepare_graph_context
from app.services.resume_versions import prepare_version, text_hash
from app.services.session_store import load_resume_session, save_resume_session


class ResumeVersionsAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ProductSecurityFlow.asyncSetUp
    cleanup = fixtures.ProductSecurityFlow.cleanup
    login = fixtures.ProductSecurityFlow.login
    fixture = fixtures.ProductSecurityFlow.fixture

    async def versioned(self):
        sid, data = await self.fixture()
        facts = load_resume_session(sid)['collected_info']
        constraints = {'avoid': ['不要突出管理职责'], 'PRIVATE_CONSTRAINT_CANARY': True}
        changed = copy.deepcopy(data)
        changed['projects'][0]['description'] = '整理需求并形成清单'
        proposal = prepare_version(data, {}, [], changed, {}, label='更新版')
        saved = await save_canonical_resume(sid, resume_revision(data), changed, self.graph,
                    _serialize_to_resume_data, source='writer', resume_meta=proposal['resume_meta'],
                    resume_versions=proposal['resume_versions'], session_constraints=constraints)
        return sid, data, saved, facts, constraints

    async def test_undo_preserves_current_facts_constraints_and_reports_diff(self):
        sid, data, saved, facts, constraints = await self.versioned()
        restored = await self.a.post(f'/api/resume/session/{sid}/versions/undo', json={'expected_revision': saved['revision']})
        self.assertEqual(restored.status_code, 200, restored.text)
        result = restored.json()
        self.assertEqual(result['data'], data)
        self.assertTrue(result['diff'])
        self.assertTrue(result['version_id'])
        self.assertTrue(result['change_summary'])
        self.assertIn('workspace', result)
        stored = load_resume_session(sid)
        self.assertEqual(stored['collected_info'], facts)
        self.assertEqual(stored['session_constraints'], constraints)
        self.assertEqual(stored['resume_versions'], [])
        with self.engine.connect() as conn:
            raw = conn.execute(text('SELECT resume_state FROM resume_sessions WHERE session_id=:sid'), {'sid': sid}).scalar()
        self.assertNotIn('PRIVATE_CONSTRAINT_CANARY', raw)
        again = await self.a.post(f'/api/resume/session/{sid}/versions/undo', json={'expected_revision': saved['revision']})
        self.assertEqual(again.status_code, 409)

    async def test_foreign_session_stale_revision_and_unknown_version_cannot_write(self):
        sid, _, saved, _, _ = await self.versioned()
        before = load_resume_session(sid)
        foreign = await self.b.post(f'/api/resume/session/{sid}/versions/undo', json={'expected_revision': saved['revision']})
        self.assertEqual(foreign.status_code, 404)
        for body in ({'expected_revision': '0'*64},
                     {'expected_revision': saved['revision'], 'version_id': 'not-this-session'}):
            rejected = await self.a.post(f'/api/resume/session/{sid}/versions/undo', json=body)
            self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(load_resume_session(sid), before)

    async def test_undo_read_failure_is_retryable_and_preserves_history(self):
        from app.services.session_store import SessionStorageUnavailable
        sid, _, saved, _, _ = await self.versioned()
        before = load_resume_session(sid)
        with patch('app.api.resume_changes.load_resume_session', side_effect=SessionStorageUnavailable()):
            response = await self.a.post(f'/api/resume/session/{sid}/versions/undo', json={'expected_revision': saved['revision']})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(load_resume_session(sid), before)

    async def test_failed_undo_does_not_consume_history_or_change_checkpoint(self):
        sid, _, saved, _, _ = await self.versioned()
        before = load_resume_session(sid)
        config = {'configurable': {'thread_id': sid}}
        checkpoint = copy.deepcopy((await self.graph.aget_state(config)).values)
        with patch('sqlalchemy.orm.session.Session.commit', side_effect=RuntimeError('synthetic commit failure')):
            result = await self.a.post(f'/api/resume/session/{sid}/versions/undo', json={'expected_revision': saved['revision']})
        self.assertEqual(result.status_code, 503, result.text)
        self.assertEqual(load_resume_session(sid), before)
        state = (await self.graph.aget_state(config)).values
        for field in ('resume_data', 'resume_meta', 'resume_versions', 'collected_info', 'session_constraints'):
            self.assertEqual(state[field], checkpoint[field])

    async def test_checkpoint_recovery_and_failed_editor_include_constraints(self):
        sid, _, saved, _, constraints = await self.versioned()
        config = {'configurable': {'thread_id': sid}}
        await self.graph.aupdate_state(config, {'session_constraints': {'stale': True}}, as_node='building')
        await prepare_graph_context('account:' + self.account_a, sid, self.graph)
        self.assertEqual((await self.graph.aget_state(config)).values['session_constraints'], constraints)
        def fail(*_):
            raise RuntimeError('fail after checkpoint write')
        with self.assertRaises(ResumeSaveUnavailable):
            await save_canonical_resume(sid, saved['revision'], saved['data'], self.graph,
                _serialize_to_resume_data, source='writer', session_constraints={'new': True}, after_save=fail)
        self.assertEqual(load_resume_session(sid)['session_constraints'], constraints)
        self.assertEqual((await self.graph.aget_state(config)).values['session_constraints'], constraints)

    async def test_manual_rewrite_invalidates_ai_metadata_but_keeps_facts(self):
        from app.services.resume_facts import normalize_fact_store
        sid, data = await self.fixture()
        facts = normalize_fact_store(data)
        item_id = facts['projects'][0]['item_id']
        fact = facts['projects'][0]['facts'][0]
        data['projects'][0]['item_id'] = item_id
        data['projects'][0]['polished_bullets'] = [fact['text']]
        meta = {'bullets': {item_id: [{'fact_ids': [fact['id']], 'text_hash': text_hash(fact['text'])}]}}
        save_resume_session(sid, data, stage='EVALUATING', collected_info=facts, resume_meta=meta,
                            session_constraints={'keep': True})
        changed = copy.deepcopy(data)
        changed['projects'][0]['polished_bullets'] = ['用户手动补充测试记录']
        await save_canonical_resume(sid, resume_revision(data), changed, self.graph, _serialize_to_resume_data)
        stored = load_resume_session(sid)
        self.assertFalse(stored['resume_meta']['bullets'])
        self.assertIn(fact, stored['collected_info']['projects'][0]['facts'])
        self.assertEqual(stored['session_constraints'], {'keep': True})

    async def test_undo_cannot_revive_deleted_evidence_from_stored_snapshot(self):
        from app.services.resume_facts import normalize_fact_store
        sid, data = await self.fixture()
        facts = normalize_fact_store(data)
        item = facts['projects'][0]
        data['projects'][0]['item_id'] = item['item_id']
        obsolete = item['facts'][0]
        data['projects'][0]['polished_bullets'] = [obsolete['text']]
        save_resume_session(sid, data, stage='EVALUATING', collected_info=facts)
        current = copy.deepcopy(data)
        current['projects'][0]['description'] = '当前独立事实'
        current['projects'][0]['polished_bullets'] = ['当前独立事实']
        proposal = prepare_version(data, {}, [], current, {})
        obsolete['status'] = 'deleted'
        save_resume_session(sid, current, stage='EVALUATING', collected_info=facts,
                            resume_meta=proposal['resume_meta'], resume_versions=proposal['resume_versions'])
        stored = load_resume_session(sid)
        undone = await self.a.post(f'/api/resume/session/{sid}/versions/undo', json={'expected_revision': resume_revision(stored['resume_data'])})
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertNotIn(obsolete['text'], str(undone.json()['data']))
        self.assertEqual(load_resume_session(sid)['collected_info'], facts)

    async def test_undo_cannot_restore_summary_citing_a_deleted_fact(self):
        from app.services.resume_facts import normalize_fact_store
        sid, data = await self.fixture()
        facts = normalize_fact_store(data)
        fact = facts['projects'][0]['facts'][0]
        summary = '具有完整产品研究与交付经验'
        old = copy.deepcopy(data)
        old['self_evaluation'] = summary
        metadata = {'summary': {'fact_ids': [fact['id']], 'text_hash': text_hash(summary)}}
        current = copy.deepcopy(data)
        current['self_evaluation'] = '当前独立说明'
        proposal = prepare_version(old, metadata, [], current, {})
        fact['status'] = 'deleted'
        save_resume_session(sid, current, stage='EVALUATING', collected_info=facts,
                            resume_meta=proposal['resume_meta'], resume_versions=proposal['resume_versions'])
        stored = load_resume_session(sid)
        restored = await self.a.post(f'/api/resume/session/{sid}/versions/undo', json={'expected_revision': resume_revision(stored['resume_data'])})
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()['data']['self_evaluation'], '')
        self.assertNotIn('summary', load_resume_session(sid)['resume_meta'])

    async def test_undo_hides_newer_experience_without_removing_its_identity_or_facts(self):
        from app.services.resume_facts import normalize_fact_store
        sid, before = await self.fixture()
        old_facts = normalize_fact_store(before)
        before['projects'][0]['item_id'] = old_facts['projects'][0]['item_id']
        save_resume_session(sid, before, stage='EVALUATING', collected_info=old_facts)
        newer = copy.deepcopy(before)
        newer['projects'].append({'name': '新经历', 'description': '编写测试'})
        facts = normalize_fact_store(newer)
        new_item = facts['projects'][1]
        newer['projects'][1]['item_id'] = new_item['item_id']
        proposal = prepare_version(before, {}, [], newer, {})
        save_resume_session(sid, newer, stage='EVALUATING', collected_info=facts,
                            resume_meta=proposal['resume_meta'], resume_versions=proposal['resume_versions'])
        undone = await self.a.post(f'/api/resume/session/{sid}/versions/undo', json={'expected_revision': resume_revision(newer)})
        self.assertEqual(undone.status_code, 200, undone.text)
        hidden = next(item for item in undone.json()['data']['projects'] if item['item_id'] == new_item['item_id'])
        self.assertTrue(hidden['hidden'])
        self.assertEqual(load_resume_session(sid)['collected_info'], facts)

    async def test_deleted_session_and_removed_suggestion_routes_cannot_restore(self):
        sid, _, saved, _, _ = await self.versioned()
        deleted = await self.a.delete(f'/api/chat/session/{sid}')
        self.assertEqual(deleted.status_code, 200, deleted.text)
        undo = await self.a.post(f'/api/resume/session/{sid}/versions/undo', json={'expected_revision': saved['revision']})
        self.assertEqual(undo.status_code, 404)
        for action in ('preview', 'generate', 'apply', 'undo'):
            response = await self.a.post(f'/api/resume/session/{sid}/suggestions/{action}', json={})
            self.assertEqual(response.status_code, 404)
