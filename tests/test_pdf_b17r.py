"""Offline font preparation, preview scheduling and public-cache regressions."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Lock
import time
import unittest
from unittest.mock import patch

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTCollection, TTFont
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.config import Settings  # noqa: E402
from app.services import mcp_preview, mcp_service, pdf_fonts, template_previews  # noqa: E402

spec = importlib.util.spec_from_file_location('prepare_pdf_fonts', ROOT / 'scripts/prepare_pdf_fonts.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
PNG = b'\x89PNG\r\n\x1a\nsynthetic-public-preview'


def synthetic_font(family, weight):
    builder = FontBuilder(1000, isTTF=False)
    glyphs = {'.notdef': 0, 'A': 65, 'common': ord('中'), 'rare': ord('龘')}
    builder.setupGlyphOrder(list(glyphs))
    builder.setupCharacterMap({value: key for key, value in glyphs.items() if value})
    builder.setupHorizontalMetrics({key: (1000, 0) for key in glyphs})
    builder.setupHorizontalHeader(ascent=880, descent=-120)
    builder.setupNameTable({'familyName': family, 'styleName': 'Bold' if weight == 700 else 'Regular',
                           'psName': family.replace(' ', '') + str(weight)})
    builder.setupOS2(sTypoAscender=880, sTypoDescender=-120, usWeightClass=weight)
    builder.setupPost()
    strings = {}
    for key in glyphs:
        pen = T2CharStringPen(1000, None)
        pen.moveTo((0, 0))
        pen.lineTo((300, 700))
        pen.lineTo((600, 0))
        pen.closePath()
        strings[key] = pen.getCharString()
    builder.setupCFF('Synthetic', {'FullName': family, 'FamilyName': family}, strings, {})
    return builder.font


class FontBuildTests(unittest.TestCase):
    def test_build_selects_sc_face_keeps_weights_and_leaves_source_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for weight in (400, 700):
                source, target = root / f'{weight}.ttc', root / f'{weight}.otf'
                collection = TTCollection()
                collection.fonts = [synthetic_font('Noto Sans CJK JP', weight),
                                    synthetic_font('Noto Sans CJK SC', weight)]
                collection.save(source)
                before = source.read_bytes()
                row = prepare.build_font(source, target, weight)
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(row['weight'], weight)
                with TTFont(target) as font:
                    self.assertIn('CFF ', font)
                    self.assertNotIn('glyf', font)
                    self.assertEqual(font['OS/2'].usWeightClass, weight)
                    self.assertEqual(set(font.getBestCmap()), {65, ord('中')})
                    self.assertEqual(font['name'].getDebugName(1), 'Huhua Resume CJK')
                    self.assertEqual(font['hmtx'].metrics[font.getBestCmap()[ord('中')]], (1000, 0))
                with self.assertRaisesRegex(ValueError, 'font weight'):
                    prepare.build_font(source, target, 700 if weight == 400 else 400)

    def test_standard_character_set_includes_kana_and_symbols_without_sample_input(self):
        chars = prepare.common_codepoints()
        for char in '简体かなカナ★①≤→Ａ':
            self.assertIn(ord(char), chars)
        self.assertNotIn(ord('龘'), chars)

    def test_partial_font_install_falls_back_without_synthesizing_bold(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(_env_file=None, PDF_CJK_FONT_DIR=directory)
            with patch('app.config.get_settings', return_value=settings):
                (Path(directory) / pdf_fonts.FONT_FILES[0]).write_bytes(b'regular')
                self.assertEqual(pdf_fonts.font_resources(), ('', {}))
                (Path(directory) / pdf_fonts.FONT_FILES[1]).write_bytes(b'bold')
                css, resources = pdf_fonts.font_resources()
                self.assertEqual(resources, {'huhua-font:400': b'regular', 'huhua-font:700': b'bold'})
                self.assertIn("'Noto Sans CJK SC'", css)
                self.assertIn('font-weight: 700', css)
                self.assertNotIn(directory, css)
                settings.PDF_CJK_FONT_DIR = ''
                self.assertEqual(pdf_fonts.font_resources(), ('', {}))

    def test_installed_fonts_do_not_open_arbitrary_pdf_file_or_network_access(self):
        from app.services.resume_pdf import render_resume_pdf

        with tempfile.TemporaryDirectory() as directory:
            for filename, weight in zip(pdf_fonts.FONT_FILES, (400, 700)):
                synthetic_font('Noto Sans CJK SC', weight).save(Path(directory) / filename)
            settings = Settings(_env_file=None, PDF_CJK_FONT_DIR=directory)
            with patch('app.config.get_settings', return_value=settings):
                for url in ('file:///etc/passwd', 'https://example.test/private', 'huhua-font:../../private'):
                    html = f'<html><head></head><body>A中<img src="{url}"></body></html>'
                    with patch('app.services.resume_pdf.render_resume', return_value=html):
                        with self.assertRaisesRegex(ValueError, 'not an uploaded image'):
                            render_resume_pdf('t001-jianyue', {})


class PreviewSchedulingTests(unittest.TestCase):
    def tearDown(self):
        mcp_service.template_preview.cache_clear()

    def test_timeout_is_configurable_and_default_covers_slow_fallback(self):
        settings = Settings(_env_file=None)
        self.assertGreaterEqual(settings.MCP_PREVIEW_TIMEOUT_SECONDS, 40 * 2)
        self.assertGreaterEqual(settings.MCP_PREVIEW_QUEUE_TIMEOUT_SECONDS, 3 * settings.MCP_PREVIEW_TIMEOUT_SECONDS)
        settings.MCP_PREVIEW_TIMEOUT_SECONDS = 123
        with patch('app.config.get_settings', return_value=settings), \
                patch.object(mcp_preview.subprocess, 'run', return_value=subprocess.CompletedProcess(
                    [], 0, (1).to_bytes(4, 'big') + PNG, b'')) as run:
            self.assertEqual(mcp_preview.render_preview('t001-jianyue', {}), (PNG, 1))
            self.assertEqual(run.call_args.kwargs['timeout'], 123)
        for name in ('MCP_PREVIEW_TIMEOUT_SECONDS', 'MCP_PREVIEW_QUEUE_TIMEOUT_SECONDS'):
            for value in (0, -1):
                with self.assertRaises(ValidationError):
                    Settings(_env_file=None, **{name: value})

    def test_seven_gallery_requests_queue_and_never_run_more_than_two_children(self):
        lock = Lock()
        active = maximum = calls = 0
        def render(*args, **kwargs):
            nonlocal active, maximum, calls
            with lock:
                active += 1
                maximum = max(maximum, active)
                calls += 1
            time.sleep(0.025)
            with lock:
                active -= 1
            return subprocess.CompletedProcess([], 0, (1).to_bytes(4, 'big') + PNG, b'')
        mcp_service.template_preview.cache_clear()
        with patch.object(mcp_preview.subprocess, 'run', side_effect=render), \
                patch.object(mcp_service, 'load_prebuilt_preview', return_value=None), \
                ThreadPoolExecutor(max_workers=7) as pool:
            results = list(pool.map(mcp_service.template_preview, mcp_service._template_preview_locks))
        self.assertEqual(results, [PNG] * 7)
        self.assertEqual((calls, maximum, active), (7, 2, 0))

    def test_same_template_misses_are_coalesced_and_success_is_reused(self):
        mcp_service.template_preview.cache_clear()
        def render(*args, **kwargs):
            time.sleep(0.02)
            return PNG, 1
        with patch.object(mcp_service, 'render_preview', side_effect=render) as run, \
                patch.object(mcp_service, 'load_prebuilt_preview', return_value=None), \
                ThreadPoolExecutor(max_workers=7) as pool:
            self.assertEqual(list(pool.map(mcp_service.template_preview, ['t001-jianyue'] * 7)), [PNG] * 7)
            self.assertEqual(mcp_service.template_preview('t001-jianyue'), PNG)
            self.assertEqual(run.call_count, 1)
            self.assertTrue(run.call_args.kwargs['wait_for_slot'])

    def test_failed_render_is_not_cached(self):
        mcp_service.template_preview.cache_clear()
        with patch.object(mcp_service, 'load_prebuilt_preview', return_value=None), \
                patch.object(mcp_service, 'render_preview', side_effect=[mcp_preview.PreviewTimeout(), (PNG, 1)]) as run:
            with self.assertRaises(mcp_preview.PreviewTimeout):
                mcp_service.template_preview('t001-jianyue')
            self.assertEqual(mcp_service.template_preview('t001-jianyue'), PNG)
            self.assertEqual(run.call_count, 2)

    def test_queue_has_its_own_bounded_wait_without_starting_child(self):
        from fastapi import HTTPException
        settings = Settings(_env_file=None, MCP_PREVIEW_QUEUE_TIMEOUT_SECONDS=0.02)
        for _ in range(2):
            self.assertTrue(mcp_preview._slots.acquire(blocking=False))
        try:
            with patch('app.config.get_settings', return_value=settings), patch.object(mcp_preview.subprocess, 'run') as run:
                with self.assertRaises(HTTPException) as error:
                    mcp_preview.render_preview('t001-jianyue', {}, wait_for_slot=True)
                self.assertEqual(error.exception.status_code, 503)
                run.assert_not_called()
        finally:
            for _ in range(2):
                mcp_preview._slots.release()


class PrebuiltPreviewTests(unittest.TestCase):
    def test_prebuilt_is_used_only_when_source_and_image_hashes_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(_env_file=None, MCP_TEMPLATE_PREVIEW_DIR=directory)
            manifest = {'fingerprint': 'current', 'images': {'t001-jianyue': hashlib.sha256(PNG).hexdigest()}}
            (root / 'manifest.json').write_text(json.dumps(manifest))
            (root / 't001-jianyue.png').write_bytes(PNG)
            mcp_service.template_preview.cache_clear()
            try:
                with patch('app.config.get_settings', return_value=settings), \
                        patch.object(template_previews, 'preview_fingerprint', return_value='current'), \
                        patch.object(mcp_service, 'render_preview', side_effect=AssertionError('prebuilt must not render')):
                    self.assertEqual(mcp_service.template_preview('t001-jianyue'), PNG)
                    (root / 't001-jianyue.png').write_bytes(PNG + b'corrupt')
                    self.assertIsNone(template_previews.load_prebuilt_preview('t001-jianyue'))
                    (root / 't001-jianyue.png').write_bytes(PNG)
                    manifest['fingerprint'] = 'old'
                    (root / 'manifest.json').write_text(json.dumps(manifest))
                    self.assertIsNone(template_previews.load_prebuilt_preview('t001-jianyue'))
                    (root / 'manifest.json').write_text('{broken')
                    self.assertIsNone(template_previews.load_prebuilt_preview('t001-jianyue'))
            finally:
                mcp_service.template_preview.cache_clear()

    def test_font_bytes_participate_in_prebuilt_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'font.otf'
            path.write_bytes(b'old')
            with patch.object(template_previews, 'font_paths', return_value=[path]):
                before = template_previews.preview_fingerprint()
                path.write_bytes(b'new')
                self.assertNotEqual(before, template_previews.preview_fingerprint())


if __name__ == '__main__':
    unittest.main()
