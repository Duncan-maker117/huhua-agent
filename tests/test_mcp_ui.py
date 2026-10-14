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
            for asset, version in (('account-profile.js', '20261015-home1'),
                                   ('account-profile.css', '20261014-mcp2')):
                self.assertIn(asset + '?v=' + version, text)
