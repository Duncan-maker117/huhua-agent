"""MCP panel behavior using the repository's synthetic DOM fixture."""
from pathlib import Path
import os
import shutil
import subprocess
import unittest


class MCPPanelTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_token_once_configs_revocation_inbox_edit_confirm_reject_and_badge(self):
        for timezone in ('Asia/Shanghai', 'America/New_York'):
            with self.subTest(timezone=timezone):
                result = subprocess.run(['node', str(Path(__file__).with_name('mcp_profile.dom.js'))],
                                        env={**os.environ, 'TZ': timezone}, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_both_pages_use_updated_panel_assets(self):
        root = Path(__file__).resolve().parents[1]
        for page in ('index.html', 'resume.html'):
            text = (root / 'web' / page).read_text()
            for asset, version in (('account-profile.js', '20261017-home4'),
                                   ('account-profile.css', '20261017-home4')):
                self.assertIn(asset + '?v=' + version, text)

    def test_workbench_connect_entries_are_separate_from_profile_actions(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / 'web/index.html').read_text()
        js = (root / 'web/account-profile.js').read_text()
        self.assertIn('id="btn-ai-assistant" class="app-nav-link" href="/connect"', html)
        self.assertIn('id="btn-ai-assistant-mobile"', html)
        self.assertIn('>MCP</a>', html)
        self.assertIn('<a id="btn-ai-assistant-mobile" class="account-entry mobile-ai-entry" href="/connect">MCP</a>', html)
        composer_links = html.split('id="composer-links"', 1)[1].split('</div>', 1)[0]
        self.assertIn('id="btn-gen-resume"', composer_links)
        self.assertEqual(composer_links.count('<a '), 1)
        actions = js.split('function renderProfile()', 1)[1].split("const actions = node('div', undefined, 'profile-actions');", 1)[1].split('content.append(actions);', 1)[0]
        self.assertNotIn('连接 AI 助手', actions)
        self.assertIn("button('补充一条信息'", actions)
