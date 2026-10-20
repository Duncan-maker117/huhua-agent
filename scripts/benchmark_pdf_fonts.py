"""Offline production-font benchmark and seven-template PNG comparison."""

import argparse
import io
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def worker(args):
    import pdfplumber
    import weasyprint.pdf.fonts as fonts
    from app.services import resume_pdf
    from app.services.pdf_fonts import font_paths

    if args.scheme == 'prepared' and not font_paths():
        raise ValueError('Prepared benchmark requires both generated font assets')
    if args.scheme != 'harfbuzz':
        fonts.harfbuzz_subset = None  # 只在隔离基准进程模拟生产 fontTools 路径。
    elif not fonts.harfbuzz_subset:
        return {'unavailable': 'HarfBuzz-Subset'}
    original = resume_pdf.render_resume
    resume_pdf.render_resume = lambda *a, **kw: original(*a, **kw).replace(
        '</head>', "<style>body {font-family:'Noto Sans CJK SC' !important;}</style></head>")
    data = json.loads((ROOT / 'data/sample_resume.json').read_text())
    if args.case == 'coverage':
        # Independent typography probes, unrelated to candidate fixtures.
        data = {'basic_info': {'name': '龘龗𠮷繁體臺灣かなカナ①★'},
                'summary': '龘龗𠮷繁體臺灣かなカナ①★ ∑≤→ café',
                'projects': [{'name': '龘龗𠮷繁體臺灣かなカナ①★',
                              'polished_bullets': ['龘龗𠮷繁體臺灣かなカナ①★ ∑≤→ café']}]}
    seen = []
    clean = fonts.Font.clean
    def track(font, *a, **kw):
        seen.append({'family': font.family, 'weight': font.weight, 'missing': sorted(font.missing)})
        return clean(font, *a, **kw)
    fonts.Font.clean = track
    options = {'hinting': True} if args.scheme == 'hinting' else {'full_fonts': True} if args.scheme == 'full-fonts' else {}
    times = []
    for _ in range(args.rounds):
        seen.clear()
        start = time.perf_counter()
        content = resume_pdf._render(args.template, data, lambda d: d.write_pdf(**options))
        times.append(time.perf_counter() - start)
    directory = args.output / args.case / args.scheme
    directory.mkdir(parents=True, exist_ok=True)
    pdf = directory / f'{args.template}.pdf'
    pdf.write_bytes(content)
    with pdfplumber.open(io.BytesIO(content)) as doc:
        text = ''.join(''.join((page.extract_text() or '').split()) for page in doc.pages)
        page_count = len(doc.pages)
        weights = sorted({char['fontname'].split('+')[-1] for page in doc.pages for char in page.chars})
    return {'seconds': times, 'median': statistics.median(times), 'bytes': len(content),
            'pages': page_count, 'fonts': seen, 'pdf_fonts': weights, 'text': text,
            'pdf': str(pdf.relative_to(args.output))}


def compare(args, before, after, label):
    from PIL import Image, ImageChops

    assert before['pages'] == after['pages'], label
    result = {'text_equal': before.pop('text') == after.pop('text'), 'pages': []}
    for page in range(1, before['pages'] + 1):
        images = []
        for row in (before, after):
            pdf = args.output / row['pdf']
            prefix = pdf.with_name(pdf.stem + f'-page{page}')
            subprocess.run(['pdftoppm', '-f', str(page), '-l', str(page), '-r', '144',
                            '-singlefile', '-png', str(pdf), str(prefix)], check=True, capture_output=True)
            images.append(Image.open(str(prefix) + '.png').convert('RGB'))
        assert images[0].size == images[1].size, label
        diff = ImageChops.difference(*images)
        channels = diff.split()
        maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
        histogram = maximum.histogram()
        total = images[0].width * images[0].height
        path = args.output / 'diffs' / f'{label}-page{page}.png'
        path.parent.mkdir(exist_ok=True)
        # 白底红色标记所有非零像素；零差异时为全白。
        mask = maximum.point(lambda x: 255 if x else 0)
        Image.composite(Image.new('RGB', diff.size, 'red'), Image.new('RGB', diff.size, 'white'), mask).save(path)
        result['pages'].append({'changed_ratio': sum(histogram[1:]) / total,
                                'over16_ratio': sum(histogram[17:]) / total,
                                'max_channel_delta': max(i for i, n in enumerate(histogram) if n),
                                'diff': str(path.relative_to(args.output))})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--font-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--scheme', default='baseline')
    parser.add_argument('--template', default='t001-jianyue')
    parser.add_argument('--case', default='sample')
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.worker:
        print(json.dumps(worker(args), ensure_ascii=False))
        return
    args.output.mkdir(parents=True, exist_ok=True)
    config = args.output / 'fonts.conf'
    config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
                      f'<dir>{escape(str(args.source_dir.resolve()))}</dir>'
                      f'<cachedir>{escape(str(args.output / "fontconfig-cache"))}</cachedir>'
                      '<alias><family>sans-serif</family><prefer><family>Noto Sans CJK SC</family>'
                      '</prefer></alias></fontconfig>')
    from app.services.renderer import list_templates
    report = {'platform': platform.platform(), 'python': sys.version, 'rounds': args.rounds,
              'templates': {}, 'options': {}, 'coverage': {}}
    def run(scheme, template, case='sample'):
        env = {**os.environ, 'FONTCONFIG_FILE': str(config),
               'PDF_CJK_FONT_DIR': str(args.font_dir.resolve()) if scheme == 'prepared' else '',
               'LLM_API_KEY': '', 'TAVILY_API_KEY': '', 'DEEPSEEK_TOOLS_API_KEY': '', 'ENABLE_RAG': 'false'}
        start = time.perf_counter()
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker',
                                 '--source-dir', str(args.source_dir), '--font-dir', str(args.font_dir),
                                 '--output', str(args.output), '--rounds', str(args.rounds),
                                 '--scheme', scheme, '--template', template, '--case', case],
                                env=env, check=True, capture_output=True, text=True, timeout=300)
        row = json.loads(result.stdout)
        row['process_wall_seconds'] = time.perf_counter() - start
        print(scheme, template, case, row.get('median'), flush=True)
        return row
    for template in list_templates():
        template_id = template['id']
        before, after = run('baseline', template_id), run('prepared', template_id)
        comparison = compare(args, before, after, template_id)
        report['templates'][template_id] = {'baseline': before, 'prepared': after, 'comparison': comparison}
    for scheme in ('hinting', 'full-fonts', 'harfbuzz'):
        row = run(scheme, 't001-jianyue')
        row.pop('text', None)
        report['options'][scheme] = row
    before, after = run('baseline', 't001-jianyue', 'coverage'), run('prepared', 't001-jianyue', 'coverage')
    comparison = compare(args, before, after, 'coverage')
    report['coverage'] = {'baseline': before, 'prepared': after, 'comparison': comparison}
    (args.output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    assert all(row['comparison']['text_equal'] for row in report['templates'].values())
    assert all({font['weight'] for font in row['prepared']['fonts']
                if font['family'] == 'Huhua Resume CJK'} == {400, 700}
               for row in report['templates'].values())
    assert report['coverage']['comparison']['text_equal']
    assert not any(font['missing'] for row in [*report['templates'].values(), report['coverage']]
                   for scheme in ('baseline', 'prepared') for font in row[scheme]['fonts'])


if __name__ == '__main__':
    main()
