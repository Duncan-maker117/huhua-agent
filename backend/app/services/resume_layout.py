"""Shared, bounded layout choices. No content edits or model calls."""

from __future__ import annotations

import re
from typing import Mapping


def resume_density(data: Mapping) -> int:
    value = (data.get('layout') or {}).get('density', 0)
    return value if type(value) is int and 0 <= value <= 3 else 0


# Preserve each template's density-zero geometry, including decorative wrappers.
# Sizes are pt; spacing is CSS px; page padding retains its original unit.
_BASE = {
    't001-jianyue': (10.5, 10, 11.5, 1.7, 14, 8, 6, 14, 14, 14, '16mm', '12mm'),
    't002-jianyue': (10, 9.5, 11, 1.65, 0, 8, 5, 14, 14, 12, '28px', '0px'),
    't004-jianyue': (10, 9.5, 11, 1.65, 0, 6, 4, 12, 0, 10, '28px', '0px'),
    't1000': (10, 9.5, 11, 1.65, 12, 8, 5, 14, 16, 12, '14mm', '12mm'),
    't1001': (10, 9.5, 11, 1.65, 12, 8, 5, 14, 22, 12, '16mm', '12mm'),
    't1002-jianyue': (10, 9.5, 11, 1.7, 12, 8, 4, 16, 28, 10, '16mm', '12mm'),
    't003-shenlan': (10, 10, 11, 1.45, 12, 8, 0, 0, 0, 8, '35pt', '35pt'),
}


def _scale_length(value: str, factor: float) -> str:
    match = re.fullmatch(r'([\d.]+)(\w+)', value)
    return f'{float(match[1]) * factor:g}{match[2]}'


def layout_css_values(template_id: str, data: Mapping) -> dict[str, str]:
    density = resume_density(data)
    body, content, heading, line, top, bottom, pad, left, right, item, page_x, page_y = _BASE.get(template_id, _BASE['t001-jianyue'])
    spacing = (1, .65, .5, .4)[density]
    page_scale = (1, 1, .92, .88)[density]
    compact = density > 0
    return {
        'body-font-size': f'{(body if density < 2 else 10 if density == 2 else 9.5):g}pt',
        'content-font-size': f'{(content if density < 3 else 9.5):g}pt',
        'item-title-size': f'{(body if density < 2 else 10 if density == 2 else 9.5):g}pt',
        'section-font-size': f'{heading - (.5 if density == 3 else 0):g}pt',
        'line-height': f'{line if not compact else min(line, (1.5, 1.42, 1.38)[density - 1]):g}',
        'section-top': f'{top * spacing:g}px', 'section-bottom': f'{bottom * spacing:g}px',
        'section-padding-y': f'{pad * spacing:g}px',
        'section-padding-left': f'{left:g}px', 'section-padding-right': f'{right:g}px',
        'section-gap': f'{12 * spacing:g}px', 'item-gap': f'{item * spacing:g}px',
        'li-gap': f'{(8 / 3 if template_id == "t003-shenlan" else 3) * spacing:g}px',
        'skill-gap': f'{(8 / 3 if template_id == "t003-shenlan" else 3) * spacing:g}px',
        'item-header-gap': f'{(4 if template_id in {"t001-jianyue", "t1000", "t1001", "t003-shenlan"} else 3) * spacing:g}px',
        'sub-gap': f'{(4 if template_id in {"t001-jianyue", "t003-shenlan"} else 3) * spacing:g}px',
        'page-x': _scale_length(page_x, page_scale), 'page-y': _scale_length(page_y, page_scale),
        'page-margin-y': f'{(10, 10, 9, 8)[density]}mm',
        'wrapper-top': f'{(20 if template_id == "t004-jianyue" else 0) * page_scale:g}px',
        'wrapper-bottom': f'{(20 if template_id == "t004-jianyue" else 24) * page_scale:g}px',
        'header-padding-y': f'{14 * spacing:g}px',
        'summary-font-size': f'{9.5 if density == 3 else 10:g}pt',
        'summary-line-height': f'{min(1.45 if template_id == "t003-shenlan" else 1.5, (1.5, 1.5, 1.42, 1.38)[density]):g}',
        'section-line-height': f'{(15 if density < 3 else 14):g}pt' if template_id == 't003-shenlan' else 'inherit',
        'contribution-gap': f'{4 * spacing:g}px',
    }


_DENSITY_REQUEST = re.compile(
    r'字(?:体)?\s*(大|小)(?:一点|一些|些|点)|排(?:版)?\s*(紧凑|紧|松)(?:一点|一些|些|点)?|自动调整(?:排版)?'
)


def density_operations(message: str) -> list[dict]:
    """Only literal requests become deterministic set_constraint operations."""
    operations = []
    for clause in re.split(r'[，,。；;！!？?\n]', message or ''):
        if re.search(r'不要|先别|暂不|不想|要不要|是否|你觉得|建议|比如|例如|假设', clause):
            continue
        for match in _DENSITY_REQUEST.finditer(clause):
            args = {'density_source': 'auto'} if match[0].startswith('自动') else {
                'density_delta': -1 if match[1] == '大' or match[2] == '松' else 1}
            operations.append({'op': 'set_constraint', 'target': 'density', 'args': args})
    return operations


def density_only_request(message: str) -> bool:
    if not density_operations(message):
        return False
    rest = _DENSITY_REQUEST.sub('', message or '')
    rest = re.sub(r'请|帮我|麻烦|把|将|简历|排版|字体|给我|再|一下|就|改成|改为|调|更|得|了|好|可以|能不能', '', rest)
    return not re.sub(r'[\s，,。；;！!？?]', '', rest)
