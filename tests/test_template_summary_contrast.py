"""Use the production CSS cascade to check every selectable template."""
import unittest
import shutil
import subprocess
from pathlib import Path

from weasyprint import HTML
from app.services.renderer import list_templates, render_resume


def luminance(color):
    rgb = color.to('srgb').coordinates
    return sum(weight * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4)
               for weight, v in zip((.2126, .7152, .0722), rgb))


class SummaryContrastTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_template_switch_dom(self):
        result = subprocess.run(['node', str(Path(__file__).with_name('template_switch.dom.js'))],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_summary_title_and_text_have_normal_text_contrast_in_all_seven_templates(self):
        self.assertEqual(len(list_templates()), 7)
        for template in list_templates():
            with self.subTest(template=template['id']):
                document = HTML(string=render_resume(template['id'], {
                    'basic_info': {'name': '虚构同学'}, 'summary': '以接口开发与测试为个人方向。',
                })).render()
                checked = set()

                def walk(box, background=1.0, classes=()):
                    bg = box.style['background_color']
                    if bg.alpha == 1:
                        background = luminance(bg)
                    own = box.element.get('class', '').split() if box.element is not None else []
                    classes = (*classes, *own)
                    for target in ('positioning', 'positioning-title'):
                        if target in classes and getattr(box, 'text', ''):
                            foreground = luminance(box.style['color'])
                            ratio = (max(background, foreground) + .05) / (min(background, foreground) + .05)
                            self.assertGreaterEqual(ratio, 4.5, (template['id'], target, ratio))
                            checked.add(target)
                    for child in box.all_children():
                        walk(child, background, classes)

                for page in document.pages:
                    walk(page._page_box)
                self.assertEqual(checked, {'positioning', 'positioning-title'})
