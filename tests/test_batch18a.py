"""Batch 18a: edit_url cross-account notice with isolated accounts and Node DOM checks."""
from pathlib import Path
import shutil
import unittest
from uuid import uuid4


import test_product_security_flow as security
from app.services.access_control import OTHER_ACCOUNT_MESSAGE
from app.services.session_store import delete_resume_session


class EditLinkAccountTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = security.ProductSecurityFlow.asyncSetUp
    cleanup = security.ProductSecurityFlow.cleanup
    login = security.ProductSecurityFlow.login
    fixture = security.ProductSecurityFlow.fixture

    def paths(self, sid):
        return (f'/api/chat/conversations/{sid}?from=mcp', f'/api/resume/current?session_id={sid}&from=mcp')

    async def test_other_account_returns_only_fixed_error_and_owner_still_reads(self):
        sid, _ = await self.fixture()
        for path in self.paths(sid):
            result = await self.b.get(path)
            self.assertEqual(result.status_code, 403, result.text)
            self.assertEqual(result.json(), {'detail': {'code': 'conversation_other_account', 'message': OTHER_ACCOUNT_MESSAGE}})
            self.assertEqual(result.headers['cache-control'], 'no-store')
            for secret in ('PRIVATE_CANARY', '课程工具', '后端参与者', 'a@example.test', self.account_a, sid):
                self.assertNotIn(secret, result.text)
            self.assertEqual((await self.a.get(path)).status_code, 200)

    async def test_normal_and_unknown_source_reads_keep_original_404(self):
        sid, _ = await self.fixture()
        for path in self.paths(sid):
            for marker in ('', 'from=web'):
                result = await self.b.get(path.replace('from=mcp', marker).rstrip('?&'))
                self.assertEqual(result.status_code, 404, result.text)
                self.assertNotIn('conversation_other_account', result.text)

    async def test_missing_and_deleted_sessions_keep_original_404(self):
        sid, _ = await self.fixture()
        delete_resume_session(sid)
        for session in (sid, str(uuid4())):
            for path in self.paths(session):
                result = await self.b.get(path)
                self.assertEqual(result.status_code, 404, result.text)
                self.assertNotIn('conversation_other_account', result.text)

    async def test_logged_out_does_not_disclose_existence(self):
        sid, _ = await self.fixture()
        await self.b.post('/api/account/logout')
        for path in self.paths(sid):
            result = await self.b.get(path)
            missing = await self.b.get(path.replace(sid, str(uuid4())))
            self.assertEqual(result.status_code, missing.status_code)
            self.assertEqual(result.json(), missing.json())
            self.assertNotIn('conversation_other_account', result.text)

    async def test_marker_does_not_change_write_authorization(self):
        sid, _ = await self.fixture()
        result = await self.b.delete(f'/api/chat/session/{sid}?from=mcp')
        self.assertEqual(result.status_code, 404)
        self.assertNotIn('conversation_other_account', result.text)


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class Batch18aDOMTests(unittest.TestCase):
    def check_dom(self, scenario):
        import subprocess
        result = subprocess.run(['node', str(Path(__file__).with_name('batch18a.dom.js')), scenario],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_editor_other_account_and_logout_return_link(self):
        self.check_dom('editor')

    def test_chat_other_account_switch_and_login_return(self):
        self.check_dom('chat')

    def test_shared_logout_clears_cache_preserves_url_and_handles_failure(self):
        self.check_dom('logout')
