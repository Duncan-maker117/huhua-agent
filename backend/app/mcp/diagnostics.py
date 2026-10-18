"""从生产排版的行框定位文稿字段；缩字收益和信息价值只作启发式建议。"""

from collections import defaultdict
import re


ITEM_GROUPS = {'education', 'work_experience', 'projects', 'campus', 'open_source', 'awards'}
BULLET_PATH = re.compile(r'^/(?:work_experience|projects|campus|open_source|awards)/\d+/(?:polished_bullets|bullets)/\d+$')


def section_diagnostics(data):
    """仅提示显式自定义栏目；不猜测经历成熟度，也不改写标题或内容。"""
    from app.mcp.writing_guide import STANDARD_SECTIONS, SECTION_RULES

    result = []
    titles = [(f'/sections/{index}/title', row['title']) for index, row in enumerate(data.get('sections') or [])]
    if data.get('sections') is None and data.get('experience_section_title'):
        titles.append(('/experience_section_title', data['experience_section_title']))
    for path, title in titles:
        if title.strip() and title.strip() not in STANDARD_SECTIONS:
            result.append({'path': path, 'code': 'nonstandard_section_title', 'severity': 'advisory',
                           'message': SECTION_RULES[0] + '建议栏目：' + ' / '.join(STANDARD_SECTIONS)})
    for index, row in enumerate(data.get('sections') or []):
        if row['kind'] == 'custom':
            result.append({'path': f'/sections/{index}', 'code': 'custom_section_review', 'severity': 'advisory',
                           'message': '请核对自定义栏目是否有足够的已完成内容。' + SECTION_RULES[1]})
    return result


def _value(data, path):
    value = data
    for part in path.lstrip('/').split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def layout_diagnostics(document, data):
    from weasyprint.formatting_structure.boxes import LineBox, TextBox

    fields = defaultdict(dict)
    # 使用模板已有的 data-field-path，不修改 HTML、CSS 或正文。
    for page_index, page in enumerate(document.pages):
        root = next(box.element for box in page._page_box.children if box.element is not None)
        parents = {child: parent for parent in root.iter() for child in parent}
        for line in page._page_box.descendants():
            if not isinstance(line, LineBox):
                continue
            key = (page_index + 1, round(line.position_y, 2))
            for box in line.descendants():
                if not isinstance(box, TextBox) or not box.text.strip():
                    continue
                element = box.element
                while element is not None and not element.get('data-field-path'):
                    element = parents.get(element)
                if element is None:
                    continue
                path = element.get('data-field-path')
                fields[path][key] = fields[path].get(key, '') + box.text

    items, sections = defaultdict(set), defaultdict(set)
    bullets, shorten, deletion, seen = [], [], [], {}
    for path, line_text in fields.items():
        parts = path.lstrip('/').split('/')
        group = parts[0]
        # 栏目标题与页眉不计入正文行数；自定义栏目按自身索引归组。
        if group in {'basic_info', 'experience_section_title'} or (group == 'sections' and parts[-1] == 'title'):
            continue
        section_path = '/skills' if group == 'skill_groups' else '/' + group
        if group == 'sections':
            section_path = '/'.join(['', *parts[:2]])
        sections[section_path].update(line_text)
        if group in ITEM_GROUPS and len(parts) > 2:
            items['/'.join(['', *parts[:2]])].update(line_text)
        if not BULLET_PATH.fullmatch(path):
            continue
        text = _value(data, path)
        row = {'path': path, 'lines': len(line_text), 'estimated': False,
               'pages': sorted({key[0] for key in line_text})}
        if len(line_text) > 1:
            count = len(line_text[max(line_text)].strip())
            hint = {'path': path, 'characters': count, 'lines_saved': 1, 'estimated': True,
                    'near_wrap': count <= 2,
                    'hint': f'再缩短约 {count} 个字可省一行；修改后必须重新测量。'}
            row['shorten'] = hint
            shorten.append(hint)
        bullets.append(row)
        normalized = re.sub(r'[\s，。；、：:;,.！!]', '', text)
        reason = ''
        duplicate_of = seen.get(normalized)
        if duplicate_of:
            reason = '与另一条可见要点文字重复；确认不是不同经历的必要说明后再合并。'
        elif re.fullmatch(r'(?:(?:现状|行动|能力)[：:]\s*)?(?:参与项目相关工作|完成相关工作|具有较强的学习能力|具有良好的沟通能力|认真负责|积极配合团队工作)[。！!]*', text.strip()):
            reason = '泛化表述，未说明具体对象、方法或交付物；请先核对是否可删除。'
        seen.setdefault(normalized, path)
        if len(document.pages) > 1 and reason:
            deletion.append({'path': path, 'lines_saved': len(line_text), 'estimated': True,
                             'reason': reason, **({'duplicate_of': duplicate_of} if duplicate_of else {})})

    shorten.sort(key=lambda row: (row['characters'], row['path']))
    deletion.sort(key=lambda row: (-row['lines_saved'], row['path']))
    return {
        'estimated': False,
        'method': 'production_weasyprint_line_boxes',
        'line_count_notice': '行数来自本次生产 PDF 排版的 LineBox，按页码与纵坐标去重。经历含标题和正文；栏目合计仅含带字段路径的正文（含经历标题），不含栏目标题、页眉、空白和边距。隐藏栏目/经历不计。',
        'suggestion_notice': '缩字数按末行可见字符估算，中英文宽度、标点禁则和分页约束可能改变收益；删减仅按重复/泛化措辞筛选，未评估岗位相关性。建议不修改内容，也不保证缩后恰好一页，须再 measure。',
        'experiences': [{'path': path, 'lines': len(lines), 'estimated': False} for path, lines in items.items()],
        'bullets': bullets,
        'sections': [{'path': path, 'lines': len(lines), 'estimated': False,
                      'includes_section_heading': False} for path, lines in sections.items()],
        'shorten_candidates': shorten, 'deletion_candidates': deletion,
    }


def next_step(checked, diagnostics):
    if checked['within_page_limit']:
        return '已在一页内；将 suggested_density 写入 resume.layout，再调用 huhua_resume_preview 自查。'
    if diagnostics['shorten_candidates']:
        row = diagnostics['shorten_candidates'][0]
        return (f"优先尝试把 {row['path']} 缩短约 {row['characters']} 个字，预计省一行；"
                '保留事实、限定和引用，按 suggested_density 固定密度后再 measure；不能保证一次回到一页。')
    if diagnostics['deletion_candidates']:
        row = diagnostics['deletion_candidates'][0]
        return f"核对 {row['path']} 是否可合并或删去，预计省 {row['lines_saved']} 行；保留必要事实，再 measure。"
    return '当前超一页，未找到有依据的局部缩字/低信息删除候选；结合栏目行数与岗位相关性合并表述，再 measure，不新增事实。'
