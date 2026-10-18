"""Bake seven public PNG previews into a release image without any API calls."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data/template_previews')
    parser.add_argument('--font-dir', type=Path, default=ROOT / 'data/fonts')
    args = parser.parse_args()
    os.environ['PDF_CJK_FONT_DIR'] = str(args.font_dir)
    from app.services.mcp_preview import render_preview
    from app.services.pdf_fonts import font_paths
    from app.services.renderer import list_templates
    from app.services.template_previews import preview_fingerprint

    if not font_paths():
        raise ValueError('Build both PDF font assets before baking previews')
    data = json.loads((ROOT / 'data/sample_resume.json').read_text())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {'fingerprint': preview_fingerprint(), 'images': {}}
    for template in list_templates():
        template_id = template['id']
        content, _ = render_preview(template_id, data, dpi=48, wait_for_slot=True)
        (args.output_dir / f'{template_id}.png').write_bytes(content)
        manifest['images'][template_id] = hashlib.sha256(content).hexdigest()
    (args.output_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'previews': len(manifest['images']), 'fingerprint': manifest['fingerprint']}))


if __name__ == '__main__':
    main()
