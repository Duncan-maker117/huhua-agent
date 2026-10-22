"""Template preview caching, buffering and races with synthetic DOM/network."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class TemplatePreviewTests(unittest.TestCase):
    def check_dom(self, scenario):
        result = subprocess.run(
            ['node', str(Path(__file__).with_name('template_switch.dom.js')), scenario],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('template switch DOM checks passed', result.stdout)

    def test_cache(self):
        self.check_dom("cache")

    def test_hover(self):
        self.check_dom("hover")

    def test_revision(self):
        self.check_dom("revision")

    def test_rapid(self):
        self.check_dom("rapid")

    def test_staleNetwork(self):
        self.check_dom("staleNetwork")

    def test_idle(self):
        self.check_dom("idle")

    def test_fallback(self):
        self.check_dom("fallback")

    def test_reset(self):
        self.check_dom("reset")

    def test_failed(self):
        self.check_dom("failed")

    def test_interactions(self):
        self.check_dom("interactions")

    def test_fonts(self):
        self.check_dom("fonts")

    def test_history(self):
        self.check_dom("history")
