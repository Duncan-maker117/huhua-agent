"""Run the production account panel against synthetic DOM/API fixtures."""
from pathlib import Path
import shutil
import subprocess
import unittest


class AccountProfilePanelTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_grouped_profile_confirmations_cancel_retry_and_undo(self):
        result = subprocess.run(['node', str(Path(__file__).with_name('account_profile.dom.js'))],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

