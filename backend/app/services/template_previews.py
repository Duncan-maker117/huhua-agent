"""Versioned build-time previews contain only the application's public sample."""

import hashlib
from importlib.metadata import version
import json
from pathlib import Path

from app.services.pdf_fonts import font_paths
from app.services.renderer import ROOT, TEMPLATE_DIR


def preview_fingerprint():
    paths = [ROOT / 'data/sample_resume.json', *sorted(TEMPLATE_DIR.glob('*.j2'))]
    paths += [Path(__file__).with_name(name + '.py') for name in (
        'renderer', 'resume_pdf', 'resume_layout', 'resume_sections', 'skill_groups',
        'pdf_fonts', 'mcp_preview', 'template_previews')]
    paths += font_paths()
    digest = hashlib.sha256(b'huhua-public-preview-v1-dpi48')
    for package in ('weasyprint', 'fonttools', 'pdfplumber', 'pypdfium2'):
        digest.update(version(package).encode())
    for path in paths:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_prebuilt_preview(template_id):
    from app.config import get_settings

    directory = Path(get_settings().MCP_TEMPLATE_PREVIEW_DIR)
    try:
        manifest = json.loads((directory / 'manifest.json').read_text())
        if manifest['fingerprint'] != preview_fingerprint():
            return None
        content = (directory / f'{template_id}.png').read_bytes()
        if (content.startswith(b'\x89PNG\r\n\x1a\n')
                and hashlib.sha256(content).hexdigest() == manifest['images'][template_id]):
            return content
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None
