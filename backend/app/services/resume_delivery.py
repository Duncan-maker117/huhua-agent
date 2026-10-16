"""Public delivery receipts must describe the canonical, committed document."""
import re

from app.services.session_store import resume_data_has_content


def delivery_requested(text: str) -> bool:
    text = re.sub(r'(?:不要|先别|不必|不用)(?:直接)?(?:成稿|生成|写)[^。；;\n]*', '', text or '')
    return bool(re.search(r'直接(?:成稿|生成|写)|整理成.{0,60}简历|完整(?:更新版|成果|正文|简历)|'
                          r'交付最终|最终投递版|不用先问', text or ''))


def export_capability(data: dict) -> str:
    from app.config import get_settings
    settings = get_settings()
    login = '' if settings.APP_ENV == 'local' and not settings.REQUIRE_ACCOUNT else '导出需要登录。'
    capability = ('PDF/Word 可在右侧「写简历」下载。' if resume_data_has_content(data or {})
                  else '成稿后可在右侧「写简历」下载 PDF/Word。')
    return capability + login


def correct_export_claims(text: str, data: dict) -> str:
    """Replace capability denials, not a genuine export/render failure notice."""
    parts = re.split(r'(?<=[。！？!?\n])', text)
    for index, part in enumerate(parts):
        if (re.search(r'不支持|无法|不能|没法|不具备', part)
                and re.search(r'PDF|Word|文件|下载', part, re.I)
                and re.search(r'生成|导出|下载|提供|支持|附件', part)):
            parts[index] = export_capability(data) + ('\n' if part.endswith('\n') else '')
    return ''.join(parts)


_SECTION = (r'基本信息|个人信息|教育(?:背景|经历)?|项目(?:经历|经验)|'
            r'工作(?:经历|经验)|实习经历|校园(?:活动|经历)|专业技能|技能(?:证书)?|自我评价')
_BULLET = re.compile(r'^\s*(?:[-*·•▸]|\d+[.、])\s+\S')
_CONTACT = re.compile(r'^(?:邮箱|电子邮箱|电话|手机|email|phone)\s*[:：]', re.I)


def _label(line: str) -> str:
    return re.sub(r'^#{1,6}\s*', '', line.strip()).strip('*【】[] ')


def _entry_header(line: str) -> bool:
    value = _label(line)
    return bool(not value.startswith('|') and len(re.split(r'[|｜]', value)) >= 3
                and re.search(r'(?:19|20)\d{2}[.年/-]\d{1,2}', value))


def _identity_header(line: str) -> bool:
    value = _label(line)
    return bool(_CONTACT.match(value) or re.match(r'^姓名\s*[:：]\s*\S', value)
                or (re.match(r'^\s*#\s+', line) and re.fullmatch(r'[\u4e00-\u9fff]{2,4}', value)
                    and not re.fullmatch(_SECTION, value)))


def _draft_heading(line: str) -> bool:
    return bool(re.match(r'^\s*(?:#{1,6}\s|\*\*)', line)
                and re.search(r'草稿|简历(?:正文|初稿)|投递版', line))


def resume_body_spans(text: str) -> list[tuple[int, int]]:
    """Find document blocks by entry/identity headers followed by actual bullets.

    Analysis tables, gap lists and editing explanations never establish a body.
    A draft section can enclose several entries, but its following explanation
    or question is outside the replacement span.
    """
    lines = text.splitlines(keepends=True)
    offsets, offset = [], 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    offsets.append(offset)
    spans = []
    index = 0
    while index < len(lines):
        if not (_entry_header(lines[index]) or _identity_header(lines[index])):
            index += 1
            continue
        start, stop, has_bullet = index, index + 1, False
        # A short Chinese heading alone is not proof of a person's name.
        # Bare names need a resume section/contact underneath; explicit 姓名
        # and dated entry headers already provide that context.
        identity_context = bool(_entry_header(lines[index]) or _CONTACT.match(_label(lines[index]))
                                or re.match(r'^姓名\s*[:：]', _label(lines[index])))
        previous = index - 1
        while previous >= 0 and not lines[previous].strip():
            previous -= 1
        if previous >= 0 and _draft_heading(lines[previous]):
            start = previous
        last_content = lines[index]
        while stop < len(lines):
            line, value = lines[stop], _label(lines[stop])
            if re.match(r'^(?:改动说明|修改说明|说明|建议|问题|接下来|你(?:接待|是否))\s*[:：—-]?', value):
                break
            section = bool(re.fullmatch(_SECTION + r'[:：]?', value))
            identity_context = identity_context or section or bool(_CONTACT.match(value)) or _entry_header(line)
            if re.match(r'^\s*#{1,6}\s', line) and not (section or _entry_header(line)):
                break
            if _BULLET.match(line):
                has_bullet = True
            # An unindented prose paragraph after a blank line is commentary.
            elif (has_bullet and value and not lines[stop - 1].strip()
                  and not (section or _entry_header(line) or _CONTACT.match(value)
                           or re.match(r'^(?:技能|求职意向)[:：]', value)
                           or re.fullmatch(_SECTION + r'[:：]?', _label(last_content)))):
                break
            if value:
                last_content = line
            stop += 1
        if has_bullet and identity_context:
            spans.append((offsets[start], offsets[stop]))
            index = stop
        else:
            index += 1
    return spans


def presents_resume_body(text: str) -> bool:
    return bool(resume_body_spans(text))


def guard_delivery(text: str, data: dict, *, saved_this_turn: bool = False, preserve_prefix: int = 0) -> str:
    """Replace only unstreamed document blocks; an SSE prefix is immutable."""
    if saved_this_turn and resume_data_has_content(data or {}):
        receipt = '草稿已放到右侧「写简历」。'
    elif resume_data_has_content(data or {}):
        receipt = '本轮尚未保存更新版，右侧仍是此前的稿件。'
    else:
        receipt = '本轮尚未生成并保存简历正文，右侧还没有可交付的稿件。'
    spans = []
    for start, stop in resume_body_spans(text):
        if start < preserve_prefix < stop:
            # A late plain-text entry header may already be on the wire.
            # Finish that line unchanged before appending its body receipt.
            newline = text.find('\n', preserve_prefix)
            start = newline + 1 if newline >= 0 else stop
        if preserve_prefix <= start < stop:
            spans.append((start, stop))
    tail, cursor = [], preserve_prefix
    for start, stop in spans:
        tail.extend((text[cursor:start], receipt))
        # A stand-alone delivery receipt also explains where exports live.
        if start == 0 and stop == len(text):
            tail.append(export_capability(data))
        elif stop < len(text):
            tail.append('\n\n')
        cursor = stop
    tail.append(text[cursor:])
    return text[:preserve_prefix] + correct_export_claims(''.join(tail), data)


def must_buffer_reply(text: str) -> bool:
    """Only recognizable document starts hold the rest of a public reply."""
    if any(_entry_header(line) or _draft_heading(line) for line in text.splitlines()):
        return True
    section = _SECTION
    return bool(re.search(
        r'(?m)^\s*(?:#{1,6}\s*|\*\*|【|\[)(?:' + section + r')(?:\*\*|】|\])?\s*(?:[:：]|$)|'
        r'(?m:^\s*(?:' + section + r')\s*[:：]?\s*\n)|'
        r'(?m:^\s*(?:#{1,6}\s+|姓名\s*[:：]\s*)[\u4e00-\u9fff]{2,4}\s*(?:\n|$))|'
        r'(?mi:^\s*(?:邮箱|电子邮箱|电话|手机|email|phone)\s*[:：]\s*\S+)', text))


class ReplyStreamBuffer:
    """Stream ordinary tokens immediately; hold only an unfinished file sentence.

    Full-document detection is sticky for this reply. File claims are evaluated
    at each sentence boundary, so the next sentence can stream normally again.
    """

    def __init__(self, data: dict, *, delivery: bool = False):
        self.data = data
        self.raw = ''
        self.consumed = 0
        self.buffered = delivery

    def feed(self, content: str, *, final: bool = False) -> str:
        self.raw += content
        self.buffered = self.buffered or must_buffer_reply(self.raw)
        if self.buffered:
            return ''
        output = []
        while self.consumed < len(self.raw):
            line_start = self.raw.rfind('\n', 0, self.consumed) + 1
            line_end = self.raw.find('\n', self.consumed)
            line = self.raw[line_start:line_end if line_end >= 0 else len(self.raw)]
            # Do not emit half a Markdown/name/contact header before it can
            # be classified. Analysis headings release at the line boundary.
            probe = line.lstrip()
            if not final and line_end < 0 and (probe.startswith(('#', '*', '【', '['))
                    or any(marker.startswith(probe) or probe.startswith(marker)
                           for marker in ('姓名：', '邮箱：', '电话：', '手机：', 'Email:', 'Phone:'))):
                break
            boundaries = list(re.finditer(r'[。！？!?\n]', self.raw[:self.consumed]))
            start = boundaries[-1].end() if boundaries else 0
            end = re.search(r'[。！？!?\n]', self.raw[self.consumed:])
            stop = self.consumed + end.end() if end else len(self.raw)
            sentence = self.raw[start:stop]
            capability = bool(re.search(r'PDF|Word|文件|下载', sentence, re.I))
            if capability and not end and not final:
                break
            corrected = correct_export_claims(sentence, self.data) if capability else sentence
            prefix = self.raw[start:self.consumed]
            if corrected.startswith(prefix):
                output.append(corrected[len(prefix):])
            else:
                # A provider can reveal "PDF" only after streaming a denial's
                # prefix. SSE cannot retract it; explicitly correct that prefix.
                output.append('（更正：' + corrected + '）')
            self.consumed = stop
        return ''.join(output)


def omit_missing_placeholders(data: dict) -> dict:
    """Remove editorial placeholders from visible fields, keep audit metadata."""
    from copy import deepcopy
    result = deepcopy(data)
    def clean(value):
        if isinstance(value, str):
            from app.services.candidate_language import editorial_absence
            value = ''.join(part for part in re.split(r'(?<=[。；;\n])', value) if not editorial_absence(part))
            return re.sub(r'[（(【\[]?[^，,。；;\n（）()【】\[\]]{0,12}(?:待补充|待补|待填写|待提供)[^，,。；;\n（）()【】\[\]]*[）)】\]]?', '', value).strip(' ，,；;')
        if isinstance(value, list):
            return [v for item in value if (v := clean(item))]
        if isinstance(value, dict):
            return {key: (entry if key in {'item_id', 'hidden', 'verification_notes'} else clean(entry))
                    for key, entry in value.items()}
        return value
    return clean(result)
