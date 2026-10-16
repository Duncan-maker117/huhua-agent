"""Literal subjects for one labelled line or one numbered experience.

These spans constrain ownership; they do not interpret duties as new subjects.
"""
import re

from app.services.candidate_language import safe_item_name


_LABELS = {
    '教育': 'education', '教育经历': 'education', '教育背景': 'education',
    '实习': 'internship', '实习经历': 'internship',
    '工作': 'work_experience', '工作经历': 'work_experience',
    '校园': 'campus', '校园经历': 'campus', '校园活动': 'campus',
    '项目': 'projects', '项目经历': 'projects', '技能': 'skills',
    '基本信息': '',
}
_MARKER = re.compile(r'(?m)(?:^[ \t]*|【)(?P<label>' + '|'.join(sorted(_LABELS, key=len, reverse=True))
                     + r')(?:[：:]|[一二三四五六七八九十\d]*】)|(?<!\d)\d+[）)]')


def explicit_subject_spans(text: str) -> list[dict]:
    spans = []
    markers = list(_MARKER.finditer(text))
    for index, marker in enumerate(markers):
        end = text.find('\n', marker.end())
        end = len(text) if end < 0 else end
        if index + 1 < len(markers):
            end = min(end, markers[index + 1].start())
        body = text[marker.end():end].strip()
        head = re.split(r'[。；;]', body, maxsplit=1)[0]
        section = _LABELS.get(marker['label'], '')
        name, fields = '', {}
        if section == 'skills':
            continue
        if section:
            name = re.split(r'[，,（(]', head, maxsplit=1)[0].strip()
            if section in {'internship', 'work_experience'}:
                role = re.search(r'[，,]\s*([^，,。；;\n]{2,24})', head)
                if role and re.search(r'实习|助理|工程师|运营|行政|专员|经理|设计师|文员', role[1]):
                    fields['title'] = role[1].strip()
        else:
            # A descriptive company is useful literal evidence even before its
            # proper name is supplied (e.g. 一家本地连锁烘焙品牌).
            employment = re.search(r'在\s*([^，,。；;\n]{2,30}?)\s*(?:做|当|任)\s*([^，,。；;\n]{2,24})', head)
            if employment and re.search(r'实习|助理|工程师|运营|行政|专员|经理|设计师|文员', employment[2]):
                name = re.sub(r'^一家', '', employment[1]).strip()
                fields['title'] = employment[2].strip()
                section = 'internship' if '实习' in fields['title'] else 'work_experience'
            elif re.match(r'(?:校)?[^，,。；;\n]{1,20}(?:社|协会|社团|学生会)(?:副?社长|会长|部长|干事|主席)', head):
                section = 'campus'
                name = re.split(r'[，,]', head, maxsplit=1)[0].removeprefix('校')
        if section == 'campus':
            role = re.fullmatch(r'(.+?)(副?社长|副?会长|副?部长|干事|主席)', name)
            if role:
                name, fields['role'] = role[1], role[2]
        if not section or not safe_item_name(name):
            continue
        spans.append({'start': marker.start(), 'end': end, 'section': section,
                      'name': name, 'fields': fields})
    return spans


def subject_span(quote: str, evidence: str) -> dict | None:
    if not quote or quote not in evidence:
        return None
    start = evidence.find(quote)
    return next((span for span in explicit_subject_spans(evidence)
                 if span['start'] <= start and start + len(quote) <= span['end']), None)


def company_description_fact(fact: dict, evidence: str) -> bool:
    """Recognize only literal employer appositives, never duties in parentheses."""
    if fact.get('field'):
        return False
    headers = []
    for span in explicit_subject_spans(evidence):
        if span['section'] in {'internship', 'work_experience'}:
            header = evidence[span['start']:span['end']]
            if match := re.search(re.escape(span['name']) + r'\s*[（(]([^）)\n]+)[）)]', header):
                headers.append((span['name'], match[1]))
    for match in re.finditer(r'(?:实习公司|公司)(?:名称|名字|名)?(?:叫做|叫|是|为|名为|[：:])\s*'
                             r'([^，,。；;（(\n]+?)\s*[（(]([^）)\n]+)[）)]', evidence):
        headers.append((match[1].strip(), match[2]))
    text = re.sub(r'^(?:实习公司|公司)(?:名称|名字|名)?(?:叫做|叫|是|为|名为|[：:])\s*', '', fact['text'])
    text = re.sub(r'^(?:实习|工作)(?:经历)?[：:]\s*', '', text)
    def compact(value):
        return re.sub(r'[\W_]', '', value)

    for name, description in headers:
        if re.search(r'我|本人|负责|参与|策划|完成|制作|撰写|整理|组织|开发|实现|设计|维护|发布|拍摄', description):
            continue
        if compact(text) in {compact(description), compact(name + description)}:
            return True
    return False
