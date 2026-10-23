"""Read-only workspace evidence, frozen export bytes and isolated UI regressions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.api import resume  # noqa: E402
from app.services.renderer import render_resume  # noqa: E402
from app.services.resume_versions import text_hash  # noqa: E402
from app.services.resume_workspace import build_workspace, tailor_metadata  # noqa: E402


def fixture():
    data = {'basic_info': {'name': '合成测试', 'phone': '13800000000', 'email': 'test@example.invalid'},
            'projects': [{'item_id': 'p', 'name': '反馈工具', 'polished_bullets': ['整理反馈', '验证本地流程'], 'tech_stack': ['Python']}],
            'campus': [{'item_id': 'c', 'name': '志愿活动', 'bullets': ['整理活动记录']}]}
    def record(value, *ids):
        return {'text_hash': text_hash(value), 'fact_ids': list(ids)}
    values = {'collected_info': {'projects': [{'item_id': 'p', 'facts': [
        {'id': 'f1', 'kind': 'action', 'text': '整理反馈', 'source_quote': '我整理了反馈，邮箱 test@example.invalid，电话 13800000000', 'status': 'active'},
        {'id': 'f2', 'kind': 'action', 'text': '验证本地流程', 'source_quote': '我做过本地验证', 'status': 'superseded'},
        {'id': 'f3', 'kind': 'method_tool', 'text': '使用 Python', 'source_quote': '我用的是 Python', 'status': 'active'},
        {'id': 'unused', 'kind': 'action', 'text': '未引用材料', 'source_quote': '不应下发的私人材料', 'status': 'active'}]}],
        'campus': [{'item_id': 'c', 'facts': [{'id': 'fc', 'kind': 'action', 'text': '整理活动记录', 'status': 'active'}]}]},
        'resume_meta': {'bullets': {'p': [record('整理反馈', 'f1'), record('验证本地流程', 'f2', 'missing')],
                                     'c': [record('整理活动记录', 'fc')]},
                        'tech_stack': {'p': [record('Python', 'f3')]}}, 'resume_data': data,
        'stage': 'EVALUATING', 'messages': []}
    return data, values


class EvidenceProjectionTest(unittest.TestCase):
    def test_only_hash_validated_references_and_requested_fields(self):
        data, values = fixture()
        facts = build_workspace(values, data)['tailor']['evidence']['facts']
        self.assertEqual(set(facts), {'f1', 'f2', 'f3', 'fc'})
        self.assertEqual(set(facts['f1']), {'item_id', 'kind', 'text', 'source_quote', 'active'})
        self.assertEqual(facts['f1']['item_id'], 'p')
        self.assertEqual(facts['fc']['source_quote'], '')
        self.assertNotIn('不应下发的私人材料', str(facts))

    def test_inactive_and_missing_facts(self):
        data, values = fixture()
        for status in ('superseded', 'deleted', 'removed'):
            with self.subTest(status=status):
                values['collected_info']['projects'][0]['facts'][1]['status'] = status
                facts = tailor_metadata(values, data)['evidence']['facts']
                self.assertFalse(facts['f2']['active'])
                self.assertTrue(facts['f1']['active'])
                self.assertNotIn('missing', facts)

    def test_manual_edits_invalidate_bullets_and_stack_before_indexing(self):
        data, values = fixture()
        data['projects'][0]['polished_bullets'][0] = '手改新内容'
        data['projects'][0]['tech_stack'][0] = 'Rust'
        view = tailor_metadata(values, data)
        self.assertEqual(view['resume_meta']['bullets']['p'][0], {})
        self.assertEqual(set(view['evidence']['facts']), {'f2', 'fc'})
        data['projects'][0]['polished_bullets'][1] = '又改了一条'
        self.assertEqual(set(tailor_metadata(values, data)['evidence']['facts']), {'fc'})

    def test_reorder_and_duplicate_text_keep_positional_metadata(self):
        data, values = fixture()
        data['projects'][0]['polished_bullets'] = ['验证本地流程', '整理反馈', '整理反馈']
        view = tailor_metadata(values, data)
        self.assertEqual(view['resume_meta']['bullets']['p'][0]['fact_ids'], ['f2', 'missing'])
        self.assertEqual(view['resume_meta']['bullets']['p'][1]['fact_ids'], ['f1'])
        self.assertEqual(view['resume_meta']['bullets']['p'][2], {})

    def test_projection_does_not_mutate_state_or_alias_fact_rows(self):
        data, values = fixture()
        before = deepcopy(values)
        view = build_workspace(values, data)
        self.assertEqual(values, before)
        view['tailor']['evidence']['facts']['f1']['source_quote'] = '修改展示副本'
        self.assertEqual(values, before)

    def test_contacts_follow_workspace_policy_without_new_redaction(self):
        data, values = fixture()
        view = build_workspace(values, data)
        for key in ('email', 'phone'):
            value = data['basic_info'][key]
            self.assertEqual(view['experiences']['basic_info'][key], value)
            self.assertIn(value, view['tailor']['evidence']['facts']['f1']['source_quote'])

    def test_fact_id_alias_and_legacy_active_default(self):
        data, values = fixture()
        fact = values['collected_info']['projects'][0]['facts'][0]
        fact['fact_id'] = fact.pop('id')
        fact.pop('status')
        self.assertTrue(tailor_metadata(values, data)['evidence']['facts']['f1']['active'])

    def test_no_metadata_means_empty_evidence(self):
        data, values = fixture()
        values['resume_meta'] = {}
        self.assertEqual(tailor_metadata(values, data)['evidence'], {'facts': {}})
        self.assertEqual(tailor_metadata({}, {})['evidence'], {'facts': {}})

    def test_get_guest_workspace_never_writes_or_invokes_model(self):
        data, values = fixture()
        before = deepcopy(values)
        graph = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(values=deepcopy(values))), aupdate_state=AsyncMock())
        stored = {'resume_data': data, 'has_authoritative_state': True,
                  **{key: values[key] for key in ('collected_info', 'resume_meta')}}
        app = FastAPI()
        app.include_router(resume.router, prefix='/api/resume')
        with (patch.object(resume, 'authorize_session', return_value='guest-evidence'),
              patch.object(resume, 'session_can_read_checkpoint', return_value=True),
              patch.object(resume, 'load_resume_session', return_value=stored),
              patch.object(resume, 'get_graph', return_value=graph),
              patch.object(resume, '_llm_for_graph', return_value=object()),
              patch.object(resume, 'save_canonical_resume', AsyncMock()) as save,
              patch('sqlalchemy.orm.Session.commit', side_effect=AssertionError('GET committed')) as commit,
              patch('sqlalchemy.orm.Session.flush', side_effect=AssertionError('GET flushed')) as flush):
            response = TestClient(app).get('/api/resume/current?session_id=guest-evidence')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('f1', response.json()['workspace']['tailor']['evidence']['facts'])
        self.assertFalse(response.json()['workspace']['tailor']['evidence']['facts']['f2']['active'])
        save.assert_not_called()
        commit.assert_not_called()
        flush.assert_not_called()
        graph.aupdate_state.assert_not_awaited()
        self.assertEqual(values, before)


class EvidenceRenderTest(unittest.TestCase):
    def test_export_and_editor_html_match_approved_baseline_all_templates(self):
        baseline = json.loads((ROOT / 'tests/fixtures/batch19a-render-baseline.json').read_text())
        for filename, digest in baseline['sha256'].items():
            with self.subTest(filename=filename):
                template = filename.split('.')[0]
                html = render_resume(template, baseline['data'], interactive='.interactive.' in filename)
                self.assertEqual(hashlib.sha256(html.encode()).hexdigest(), digest)
                self.assertNotIn('resume-evidence', html)

    def test_main_workspace_only_loads_evidence_bridge(self):
        index = (ROOT / 'web/index.html').read_text()
        editor = (ROOT / 'web/resume.html').read_text()
        self.assertIn('HuhuaEvidence?.decorate(highlighted)', index)
        self.assertNotIn('evidence', editor)
        self.assertNotIn('resume-preview.js', index)
        css = (ROOT / 'web/resume-workspace.css').read_text()
        self.assertIn('#evidence-bar, #evidence-card { display: none !important; }', css)


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class EvidenceDomTest(unittest.TestCase):
    def check_dom(self, name):
        result = subprocess.run(['node', str(ROOT / 'tests/batch19a.dom.js'), name],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('evidence DOM passed: ' + name, result.stdout)

    def test_stats(self):
        self.check_dom('stats')

    def test_preferences_and_storage_failures(self):
        self.check_dom('preferences')

    def test_card_content_and_safe_rendering(self):
        self.check_dom('cards')

    def test_draft_safe_actions_and_locate(self):
        self.check_dom('actions')

    def test_close_focus_and_disabled_mode(self):
        self.check_dom('closing')

    def test_template_switch_stale_messages_and_mobile(self):
        self.check_dom('switching')

    def test_iframe_markers_keyboard_and_print(self):
        self.check_dom('bridge')
