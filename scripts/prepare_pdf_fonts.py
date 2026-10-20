"""Build compact CFF fonts offline; keep the system Noto CJK fonts as fallback."""

import argparse
import hashlib
import json
from pathlib import Path
import time

from fontTools import subset
from fontTools.ttLib import TTCollection


FAMILY = 'Huhua Resume CJK'


def common_codepoints():
    # 标准字符集，不从简历或测试样例收集字符。
    result = set(range(0x250)) | set(range(0x2000, 0x2800))
    result.update(range(0x3000, 0x3100))
    result.update(range(0xFF00, 0xFFF0))
    for high in range(0xA1, 0xF8):
        for low in range(0xA1, 0xFF):
            try:
                result.update(map(ord, bytes((high, low)).decode('gb2312')))
            except UnicodeDecodeError:
                pass
    return result


def build_font(source, target, weight):
    started = time.perf_counter()
    with TTCollection(source, lazy=True) as collection:
        candidates = [font for font in collection.fonts
                      if font['name'].getDebugName(1) == 'Noto Sans CJK SC']
        if len(candidates) != 1:
            raise ValueError('Expected one Noto Sans CJK SC face')
        font = candidates[0]
        if 'CFF ' not in font or font['OS/2'].usWeightClass != weight:
            raise ValueError('Unexpected outline format or font weight')
        original_cmap = font.getBestCmap()
        expected = common_codepoints() & original_cmap.keys()
        options = subset.Options(hinting=True, desubroutinize=True,
                                 name_IDs=[0, 1, 2, 3, 4, 5, 6, 13, 14])
        subsetter = subset.Subsetter(options)
        subsetter.populate(unicodes=expected)
        subsetter.subset(font)
        style = 'Bold' if weight == 700 else 'Regular'
        names = {1: FAMILY, 2: style, 3: f'HuhuaResumeCJK-{style}',
                 4: f'{FAMILY} {style}', 6: f'HuhuaResumeCJK-{style}'}
        for record in font['name'].names:
            if record.nameID in names:
                record.string = names[record.nameID].encode(record.getEncoding())
        top = font['CFF '].cff.topDictIndex[0]
        top.FamilyName, top.FullName = FAMILY, f'{FAMILY} {style}'
        font['CFF '].cff.fontNames = [f'HuhuaResumeCJK-{style}']
        font.save(target)
        if set(font.getBestCmap()) != expected or font['OS/2'].usWeightClass != weight:
            raise ValueError('Font coverage or weight changed unexpectedly')
        return {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                'bytes': target.stat().st_size, 'codepoints': len(expected),
                'source_codepoints': len(original_cmap), 'glyphs': len(font.getGlyphOrder()),
                'weight': weight, 'seconds': round(time.perf_counter() - started, 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, default=Path('/usr/share/fonts/opentype/noto'))
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'data/fonts')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {'version': 1, 'family': FAMILY, 'format': 'CFF', 'fonts': {}}
    for style, weight in (('Regular', 400), ('Bold', 700)):
        filename = f'HuhuaResumeCJK-{style}.otf'
        manifest['fonts'][filename] = build_font(
            args.source_dir / f'NotoSansCJK-{style}.ttc', args.output_dir / filename, weight)
    (args.output_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
