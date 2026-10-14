"""Repeated UI actions against synthetic DOM and pending API requests."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class FrontendReentrancyTests(unittest.TestCase):
    def check_dom(self, scenario):
        result = subprocess.run(
            ['node', str(Path(__file__).with_name('frontend_reentrancy.dom.js')), scenario],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('frontend reentrancy DOM check passed', result.stdout)

    def test_rename_single_form_and_pending_save(self):
        self.check_dom('rename')

    def test_job_single_form_and_pending_save(self):
        self.check_dom('job')

    def test_fact_single_form_and_pending_save(self):
        self.check_dom('fact')

    def test_existing_mcp_submission_guards(self):
        self.check_dom('mcp')

    def test_review_single_flight_and_session_change(self):
        self.check_dom('review')

    def test_superseded_undo_stays_disabled_after_failure(self):
        self.check_dom('undo')

    def test_editor_pending_save_disables_retry(self):
        self.check_dom('save')

    def test_draft_creation_disables_trigger(self):
        self.check_dom('draft')

    def test_export_disables_options_and_retry(self):
        self.check_dom('exporting')

    def test_editor_escape_saves_and_respects_nested_dialogs(self):
        self.check_dom('escape')

    def test_editor_modal_reuses_frame_and_escape_closes(self):
        self.check_dom('modal')

    def test_preview_forwards_escape(self):
        self.check_dom('previewEscape')
