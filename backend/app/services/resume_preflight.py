"""Deterministic delivery hygiene. Originals remain in the fact store/history.

No fuzzy semantic rewriting: merge proven identities, retain distinct clauses,
and normalize presentation without inventing dates, outcomes or technologies.
"""
from copy import deepcopy
import json
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from app.services.resume_versions import ITEM_SECTIONS, text_hash

_LABEL = re.compile(r'^(问题|决策|迭代|技术|现状|分工|评测)\s*[:：]\s*')
_SEPARATORS = ' \t\r\n·•|｜;；'


def quality_edit_requested(text):
    # A complaint is a request to remove proven duplication, not permission to
    # discard unrelated facts. A model paraphrase alone grants no authority.
    if re.search(r'不要(?:去重|合并)|不(?:要|用)(?:处理|删除|删掉)重复|保留重复|(?:不是|并非|不算|不)重复', text):
        return False
    return bool(re.search(r'重复|去重|合并|技术栈.*(?:不是技术|非技术|口语|污染)|'
                          r'(?:清理|整理).*技术栈', text))


def normalize_date(value):
    from app.services.experience_fields import normalize_date_value
    return normalize_date_value(value, end=True) or str(value or '').strip()


def _url(value):
    value = str(value or '').strip(_SEPARATORS).rstrip('/')
    candidate = value if re.match(r'https?://', value, re.I) else 'https://' + value
    try:
        parts = urlsplit(candidate)
        if not parts.hostname or '.' not in parts.hostname or re.search(r'[\s<>]', value):
            return value, '', ''
        normalized = urlunsplit(('https', parts.netloc.lower(), parts.path.rstrip('/'), parts.query, parts.fragment))
        return normalized, normalized.casefold(), parts.hostname.lower()
    except ValueError:
        return value, '', ''


def clean_contacts(basic):
    result = deepcopy(basic)
    links, handles = result.get('links') or [], set()
    for link in links:
        value, _, host = _url(link.get('url'))
        if host in {'github.com', 'www.github.com'} and len(urlsplit(value).path.strip('/').split('/')) == 1:
            handles.add(urlsplit(value).path.strip('/').casefold())
    kept, seen = [], set()
    for link in links:
        label = str(link.get('text') or '').strip(_SEPARATORS + '：:')
        value = str(link.get('url') or '').strip(_SEPARATORS)
        if not value:
            continue
        if re.fullmatch(r'@?[A-Za-z0-9_-]+', value) and (label.casefold() == 'github' or value.lstrip('@').casefold() in handles):
            value = 'https://github.com/' + value.lstrip('@')
        value, key, host = _url(value)
        if host in {'github.com', 'www.github.com'}:
            label = 'GitHub'
        elif label.casefold() == 'github':
            label = '个人主页' if host else '账号'
        elif not host and label == '个人主页':
            label = '账号'
        key = key or value.casefold()
        if key in seen:
            continue
        seen.add(key)
        kept.append({**link, 'text': label or ('个人主页' if host else '链接'), 'url': value})
    if 'links' in result:
        result['links'] = kept
    for field in ('phone', 'email', 'location'):
        if isinstance(result.get(field), str):
            result[field] = result[field].strip(_SEPARATORS)
    return result


def _same_experience(left, right, sources, section):
    from app.services.experience_fields import same_experience, profile_item_refs
    source_a, source_b = sources.get(left.get('item_id'), {}), sources.get(right.get('item_id'), {})
    if (profile_item_refs(left) | profile_item_refs(source_a)) & (profile_item_refs(right) | profile_item_refs(source_b)):
        return True
    # Empty display slots do not erase known conflicting source headers.
    effective_a = {**source_a, **{k: v for k, v in left.items() if v}}
    effective_b = {**source_b, **{k: v for k, v in right.items() if v}}
    return same_experience(effective_a, effective_b, section)


def _item_ids(item, meta):
    iid = item.get('item_id')
    return {x for x in [iid, *((meta or {}).get('merged_items') or {}).get(iid, [])] if x}


def distinct_pair(collected, meta, left, right):
    """True once the user has said these two entries are separate experiences."""
    marked = (collected or {}).get('distinct_experiences') or []
    a, b = _item_ids(left, meta), _item_ids(right, meta)
    return any(isinstance(pair, (list, tuple)) and len(pair) == 2
               and (pair[0] in a and pair[1] in b or pair[0] in b and pair[1] in a) for pair in marked)


def _requested_merge(left, right, section, request, dismissed=False):
    """Only names the user actually wrote can authorize merging look-alikes.

    “有内容重复” alone is a complaint, not a verdict about which entries are the
    same; look-alike names then stay separate and are put to the user instead.
    """
    from app.services.experience_fields import names_similar, name_key
    from app.services.candidate_language import placeholder_name
    if not request or not quality_edit_requested(request) or not re.search(r'重复|去重|合并', request):
        return False
    label = 'company' if section in {'work_experience', 'internship'} else 'school' if section == 'education' else 'name'
    a, b = left.get(label, ''), right.get(label, '')
    requested = name_key(request)
    # A generic cleanup never authorizes moving an unnamed item's facts.
    def mentioned(item, name):
        return bool(name and name_key(name) and name_key(name) in requested or item.get('item_id') and item['item_id'] in request)
    if any((not name or placeholder_name(name)) and not mentioned(item, name) for item, name in ((left, a), (right, b))):
        return False
    # Explicitly named labels may be the same user-declared item.
    if re.search(r'合并', request) and mentioned(left, a) and mentioned(right, b):
        return True
    if dismissed or not names_similar(a, b):
        return False
    # Look-alikes merge only when the request names what they have in common.
    core = min((name_key(re.split(r'[｜|]', str(name or ''))[0]) for name in (a, b)), key=len)
    return bool(core) and core in requested


def _possible_duplicate(left, right, sources, section):
    from app.services.experience_fields import names_similar
    from app.services.candidate_language import placeholder_name
    label = 'company' if section in {'work_experience', 'internship'} else 'school' if section == 'education' else 'name'
    if _same_experience(left, right, sources, section):
        return True
    if placeholder_name(left.get(label)) or placeholder_name(right.get(label)):
        return False
    if section == 'education' and any(left.get(k) and right.get(k) and left[k] != right[k] for k in ('degree', 'major')):
        return False
    a, b, c, d = (normalize_date(row.get(key)) for row in (left, right) for key in ('start_date', 'end_date'))
    if all(re.fullmatch(r'\d{4}\.\d{2}', value) for value in (a, b, c, d)) and (b < c or d < a):
        return False
    return names_similar(left.get(label), right.get(label))


_DUP_SECTIONS = ('projects', 'work_experience', 'internship', 'education', 'campus', 'open_source')
_DUP_NOUN = {'projects': '项目', 'work_experience': '工作经历', 'internship': '实习', 'education': '教育经历',
             'campus': '校园经历', 'open_source': '开源贡献'}
DUPLICATE_YES, DUPLICATE_NO = '是，合并成一条', '不是，分开保留'


def _display_name(item):
    name = item.get('name') or item.get('company') or item.get('school') or '未命名经历'
    return str(name)


def _duplicate_pairs(data, collected, meta):
    """Visible look-alike pairs the user has not already declared separate."""
    sources = {row['item_id']: row for section in (*ITEM_SECTIONS, 'internship')
               for row in (collected or {}).get(section) or [] if row.get('item_id')}
    for section in _DUP_SECTIONS:
        items = [row for row in (data or {}).get(section) or [] if not row.get('hidden')]
        for index, item in enumerate(items):
            for other_index, other in enumerate(items[index + 1:], index + 1):
                if _possible_duplicate(item, other, sources, section) and not distinct_pair(collected, meta, item, other):
                    yield section, index, other_index, item, other


def duplicate_question_id(left_id, right_id):
    return 'dup-' + text_hash(json.dumps(sorted([str(left_id), str(right_id)])))[:12]


def suspected_duplicates(data, collected=None, meta=None):
    """Pairs that merely look alike. Never merged without the user's word."""
    rows = []
    sources = {row['item_id']: row for section in (*ITEM_SECTIONS, 'internship')
               for row in (collected or {}).get(section) or [] if row.get('item_id')}
    for section, _, _, item, other in _duplicate_pairs(data, collected, meta):
        if not item.get('item_id') or not other.get('item_id') or _same_experience(item, other, sources, section):
            continue  # proven duplicates merge on their own; only look-alikes need a verdict
        rows.append({'section': section, 'ids': [item['item_id'], other['item_id']],
                     'names': [_display_name(item), _display_name(other)],
                     'question_id': duplicate_question_id(item['item_id'], other['item_id'])})
    return rows


def duplicate_question(pair):
    """Question for the existing ask_user card; names are cut to fit its limit."""
    noun = _DUP_NOUN.get(pair['section'], '经历')
    frame = '「」和「」是同一个' + noun + '吗？'
    room = (40 - len(frame)) // 2
    short = [re.split(r'[｜|]', name)[0].strip() for name in pair['names']]
    short = [name if len(name) <= room else name[:max(room - 1, 1)] + '…' for name in short]
    return {'id': pair['question_id'], 'prompt': f'「{short[0]}」和「{short[1]}」是同一个{noun}吗？',
            'kind': 'single', 'options': [DUPLICATE_YES, DUPLICATE_NO], 'allow_other': False, 'placeholder': ''}


def apply_duplicate_answers(data, meta, collected, answers):
    """Carry out the user's verdicts: merge on yes, remember on no. Nothing else changes."""
    pairs = {row['question_id']: row for row in suspected_duplicates(data, collected, meta)}
    output, metadata, facts = data, meta, deepcopy(collected or {})
    merge, apart, unmatched = [], [], 0
    for answer in (answers or {}).get('items') or []:
        pair = pairs.get(answer.get('id'))
        values = answer.get('value') or []
        values = values if isinstance(values, list) else [values]
        if not pair:
            unmatched += 1
        elif DUPLICATE_YES in values and DUPLICATE_NO not in values:
            merge.append(pair)
        elif DUPLICATE_NO in values and DUPLICATE_YES not in values:
            apart.append(pair)
    merged = []
    if merge:
        output, metadata, report = preflight_resume(data, meta, facts, body_ids=set(),
                                                     confirmed_pairs=[row['ids'] for row in merge])
        done = {x for row in report['merged'] for x in (row['item_id'], *row['merged_ids'])}
        merged = [row for row in merge if set(row['ids']) <= done]
    marked = facts.setdefault('distinct_experiences', []) if apart else None
    for row in apart:
        if sorted(row['ids']) not in [sorted(pair) for pair in marked]:
            marked.append(list(row['ids']))
    return {'data': output, 'meta': metadata, 'collected': facts, 'merged': merged, 'apart': apart,
            'failed': [row for row in merge if row not in merged], 'unmatched': unmatched}


def merge_experiences(data, meta, collected, *, merge_request='', confirmed_pairs=()):
    sources = {row.get('item_id'): row for section in (*ITEM_SECTIONS, 'internship')
               for row in collected.get(section) or [] if row.get('item_id')}
    merges = []
    confirmed = {frozenset(pair) for pair in confirmed_pairs}
    for section in ('projects', 'work_experience', 'internship', 'education', 'campus', 'open_source'):
        items = data.get(section) or []
        groups = []
        for item in items:
            def together(member):
                if frozenset((item.get('item_id'), member.get('item_id'))) in confirmed:
                    return True
                dismissed = distinct_pair(collected, meta, item, member)
                return bool(not dismissed and _same_experience(item, member, sources, section)
                            or _requested_merge(item, member, section, merge_request, dismissed))
            group = next((g for g in groups if not item.get('hidden') and all(
                not member.get('hidden') and together(member) for member in g)), None)
            if group is None:
                groups.append([item])
            else:
                group.append(item)
        merged = []
        field = 'polished_bullets' if section == 'projects' else 'bullets'
        for group in groups:
            if len(group) == 1:
                merged.extend(group)
                continue
            def information(row):
                clauses = {re.sub(r'\s+', '', part) for line in row.get(field) or [row.get('description') or '']
                           for part in re.split(r'[，,。；;\n]', line) if part.strip()}
                return (sum(len(part) for part in clauses), len(clauses),
                        sum(bool(row.get(k)) for k in ('role', 'start_date', 'end_date')))
            main = max(group, key=information)
            iid = main.get('item_id')
            ids = list(dict.fromkeys(x for row in group for x in [row.get('item_id'), *meta.get('merged_items', {}).get(row.get('item_id'), [])] if x))
            meta.setdefault('merged_items', {})[iid] = ids
            for old_id in ids:
                if old_id != iid:
                    meta['merged_items'].pop(old_id, None)
            conflicts = meta.setdefault('merge_conflicts', {}).setdefault(iid, {})
            for key in ('role', 'title', 'degree', 'major', 'project_type', 'positioning', 'start_date', 'end_date'):
                values = list(dict.fromkeys(row[key] for row in group if row.get(key)))
                if len(values) > 1:
                    conflicts[key] = values
                if not main.get(key) and values:
                    main[key] = values[0]
            records, body, stacks, tech_records, links = [], [], [], [], []
            for row in [main, *(r for r in group if r is not main)]:
                prior = meta.get('bullets', {}).get(row.get('item_id'), [])
                lines = row.get(field) or (row.get('description') or '').splitlines()
                for index, line in enumerate(lines):
                    record = deepcopy(prior[index]) if index < len(prior) and prior[index].get('text_hash') == text_hash(line) else {}
                    body.append(line)
                    records.append(record)
                old_tech = meta.get('tech_stack', {}).get(row.get('item_id'), [])
                stacks.extend(row.get('tech_stack') or [])
                tech_records.extend(deepcopy(old_tech))
                links.extend(row.get('links') or [])
            main[field] = body
            if section == 'projects' and body:
                main['description'] = ''
            if stacks:
                main['tech_stack'] = list(dict.fromkeys(stacks))
            if links:
                main['links'] = list({(row.get('text'), row.get('url')): row for row in links}.values())
            meta.setdefault('bullets', {})[iid] = records
            if tech_records:
                meta.setdefault('tech_stack', {})[iid] = tech_records
            merged.append(main)
            merges.append({'item_id': iid, 'merged_ids': [x for x in ids if x != iid]})
        if section in data:
            data[section] = merged
    return merges


_CODE_URL = re.compile(r'https?://github\.com/([\w.-]+/[\w.-]+)/(pull/(\d+)|commit/([0-9a-f]{7,40}))/?', re.I)


def compact_code_links(text):
    matches = list(_CODE_URL.finditer(text))
    repositories = {m[1].casefold() for m in matches}
    def replace(match):
        prefix = match[1] + ' ' if len(repositories) > 1 else ''
        return prefix + ('PR #' + match[3] if match[3] else 'commit ' + match[4][:7])
    result = _CODE_URL.sub(replace, text)
    if len(repositories) == 1:
        result = re.sub(r'(?<=\d)\s*(?:和|与|及|、|，|,)\s*PR\s*(?=#\d)', '、', result)
    # "PR https://…/pull/6" already carried its own label.
    return re.sub(r'\bPR\s+PR #', 'PR #', result, flags=re.I)


def clean_prose(text):
    """Safe final fallback for labeled prose; substantive rewriting stays in writer."""
    from app.services.candidate_language import strip_oral_prefixes
    return compact_code_links(strip_oral_prefixes(text))


def _body_cleanup(item, meta, field):
    original = item.get(field) or []
    if not original:
        return
    iid = item.get('item_id')
    prior = meta.get('bullets', {}).get(iid, [])
    rows, seen = [], {}
    for index, old in enumerate(original):
        text = clean_prose(old)
        record = deepcopy(prior[index]) if index < len(prior) and prior[index].get('text_hash') == text_hash(old) else {}
        label = _LABEL.match(text)
        body = text[label.end():] if label else text
        # Semicolon/comma delimited identical claims, including short labeled
        # points. Never substring-match, drop negations, or conflate numbers.
        kept = []
        for part in re.split(r'[；;，,]', body):
            part = part.strip(' 。')
            if not part:
                continue
            key = re.sub(r'\s+', '', part).casefold()
            key = re.sub(r'^发现(?=.{4})', '', key)
            comparable = len(key) >= 4 and not re.fullmatch(r'[\d.%％/次天人年月]+', key)
            if comparable and key in seen:
                target = seen[key]
                target['record']['fact_ids'] = list(dict.fromkeys([
                    *target['record'].get('fact_ids', []), *record.get('fact_ids', [])]))
                target['record'].pop('coverage_fact_ids', None)
            else:
                kept.append(part)
                if comparable:
                    seen[key] = {'record': record}
        if kept:
            # Keep punctuation byte-for-byte when there was no repetition.
            cleaned = text if len(kept) == len([p for p in re.split(r'[；;，,]', body) if p.strip(' 。')]) else (
                (label[0] if label else '') + '；'.join(kept))
            if record and cleaned != old:
                record.pop('coverage_fact_ids', None)
                record['text_hash'] = text_hash(cleaned)
            rows.append({'text': cleaned, 'record': record})
    item[field] = [row['text'] for row in rows]
    if prior or any(row['record'] for row in rows):
        meta.setdefault('bullets', {})[iid] = [
            {**row['record'], 'text_hash': text_hash(row['text'])} if row['record'] else {} for row in rows]


def preflight_resume(data, meta=None, collected=None, *, merge=True, body_ids=None, merge_request='', confirmed_pairs=()):
    """原话是依据不是成品；只做确定性清理，实质改写走 writer 的核验/降级路径。"""
    from app.services.tech_stack import normalize_stack
    from app.services.resume_versions import valid_bullet_metadata
    from app.services.experience_fields import normalize_field
    output = deepcopy(data)
    metadata = valid_bullet_metadata(output, meta or {})
    report = {'merged': merge_experiences(output, metadata, collected or {}, merge_request=merge_request,
                                          confirmed_pairs=confirmed_pairs) if merge else []}
    if 'basic_info' in output:
        output['basic_info'] = clean_contacts(output['basic_info'])
    for section in ITEM_SECTIONS:
        for item in output.get(section) or []:
            for key in ('name', 'company', 'school', 'role', 'title', 'start_date', 'end_date', 'date'):
                if key in item:
                    item[key] = normalize_field(key, item[key]) or ''
            if 'tech_stack' in item:
                item['tech_stack'] = normalize_stack(item['tech_stack'])
            if item.get('hidden') or body_ids is not None and item.get('item_id') not in body_ids:
                continue
            _body_cleanup(item, metadata, 'polished_bullets' if section == 'projects' else 'bullets')
            if item.get('description'):
                item['description'] = clean_prose(item['description'])
    metadata = valid_bullet_metadata(output, metadata)
    if collected:
        from app.services.fact_coverage import ensure_fact_coverage
        ensure_fact_coverage(output, metadata, collected)
    return output, metadata, report


def check_resume(data, collected=None, *, jd_info=None, has_jd=False, meta=None):
    """Inspect the delivered document without cleaning it or changing evidence.

    Reuse the delivery rules on copies. Already-fixed presentation issues thus
    disappear naturally; uncertain wording/identity decisions remain advisory.
    """
    from app.services.auto_polish_gate import needs_polish
    from app.services.tech_stack import is_technology_name
    data, collected = data or {}, collected or {}
    issues = []

    def issue(category, section, item_id, field, message, suggestion, *,
              severity='warning', auto_fixable=False, key=''):
        identifier = json.dumps([category, section, item_id, field, key], ensure_ascii=False)
        issues.append({'id': 'precheck-' + text_hash(identifier)[:16], 'category': category,
                       'severity': severity, 'section': section, 'item_id': item_id,
                       'field': field, 'message': message, 'suggestion': suggestion,
                       'auto_fixable': auto_fixable})

    sources = {row['item_id']: row for section in (*ITEM_SECTIONS, 'internship')
               for row in collected.get(section) or [] if row.get('item_id')}
    from app.services.resume_versions import valid_bullet_metadata
    # Merge state only counts while the merged-away entries are really gone.
    live_meta = valid_bullet_metadata(data, meta or {})
    for section, index, other_index, item, other in _duplicate_pairs(data, collected, live_meta):
        names = [_display_name(row) for row in (item, other)]
        issue('duplicate_experience', section, item.get('item_id'), None,
              f'「{names[0]}」与「{names[1]}」可能重复；名称相近或时间重叠不能证明是同一段经历。',
              '如果是同一个项目，可以让我合并；不同经历请保持独立。' if section == 'projects' else '如果是同一段经历，可以让我合并。',
              key=f'{index}:{other_index}')
    for section in (*ITEM_SECTIONS, 'internship'):
        items = [row for row in data.get(section) or [] if not row.get('hidden')]
        if section not in {'projects', 'work_experience', 'internship', 'education', 'campus', 'open_source'}:
            continue
        for index, item in enumerate(items):
            merged = [x for x in (live_meta.get('merged_items') or {}).get(item.get('item_id'), []) if x != item.get('item_id')]
            conflicts = {**(sources.get(item.get('item_id'), {}).get('merge_conflicts') or {}),
                         **((live_meta.get('merge_conflicts') or {}).get(item.get('item_id'), {}) if merged else {})}
            for field in ('role', 'title'):
                if len(conflicts.get(field) or []) > 1:
                    issue('role_conflict', section, item.get('item_id'), field,
                          '合并来源包含不同角色：' + '、'.join(conflicts[field]) + '；当前保留主条目的角色。',
                          '请确认这段经历应采用哪个角色，不自动拼接。', key=str(index))

    basic = data.get('basic_info') or {}
    links = basic.get('links') or []
    nonempty = [row for row in links if str(row.get('url') or '').strip(_SEPARATORS)]
    cleaned = clean_contacts(basic)
    if len(cleaned.get('links') or []) < len(nonempty):
        issue('duplicate_contact', 'basic_info', None, 'links',
              '联系方式中存在指向同一地址的重复链接。',
              '统一链接协议和末尾斜杠，每个地址只保留一次。', auto_fixable=True)
    if any((clean_contacts({'links': [row]})['links'] or [{}])[0].get('text') != row.get('text')
           for row in nonempty):
        issue('contact_label', 'basic_info', None, 'links',
              '部分链接的标签与地址类型不一致或缺少标签。',
              'GitHub 地址标为 GitHub，其他网站标为个人主页；不确定的账号类型请先确认。')

    def prose(text, section, iid, field, key):
        reasons = needs_polish(text)
        if {'first_person', 'colloquial', 'narrative_opening'} & set(reasons):
            issue('oral_phrase', section, iid, field, '这处文字带有口语或第一人称叙述。',
                  '原话是依据不是成品：改为动词开头的简历表达，去口语和冗余；不得新增事实、数字或扩大参与程度，保留团队分工、否定和未上线等限制。', key=key)
        compactable = compact_code_links(text) != text
        if compactable or re.search(r'https?://[^\s<>，。；;]{80,}', text):
            issue('long_link', section, iid, field, '正文中的完整链接较长，影响阅读和排版。',
                  'GitHub PR/commit 改用编号或短哈希；其他网址改为简短链接标签并保留目标地址。',
                  auto_fixable=compactable and not re.search(r'https?://[^\s<>，。；;]{80,}', compact_code_links(text)),
                  key=key)

    for section in ITEM_SECTIONS:
        for index, item in enumerate(data.get(section) or []):
            if item.get('hidden'):
                continue
            iid = item.get('item_id')
            locator = iid or str(index)
            for field in ('start_date', 'end_date', 'date'):
                value = str(item.get(field) or '').strip()
                normalized = normalize_date(value)
                if normalized != value:
                    issue('date_format', section, iid, field, '这处日期与统一的年月格式不一致。',
                          f'改为 {normalized}；不补充原材料中没有的月份。', auto_fixable=True, key=locator)
                elif value and not re.fullmatch(r'\d{4}(?:\.(?:0[1-9]|1[0-2]))?(?:（预计）)?|至今|现在', value):
                    issue('date_format', section, iid, field, '这处日期无法确认是有效的年月。',
                          '核实原始年月后填写 YYYY.MM；只知道年份时保留年份，不猜测月份。',
                          severity='error', key=locator)
            if any(not is_technology_name(name) for name in item.get('tech_stack') or []):
                issue('tech_stack_noise', section, iid, 'tech_stack', '技术栈中含有可能不是技术名称的文字。',
                      '将产品说明和口语移入经历描述，只保留实际使用的技术；陌生专有名词请先核实。', key=locator)
            heading = ' '.join(str(item.get(key) or '') for key in
                               ('name', 'company', 'school', 'role', 'title', 'positioning', 'project_type'))
            if sum(2 if unicodedata.east_asian_width(char) in 'WF' else 1 for char in heading.strip()) > 64:
                issue('title_overflow', section, iid, 'title', '这条经历的标题较长，可能挤压日期或换行。',
                      '保留项目或单位名与角色，将功能说明移入正文，并用排版检查确认实际效果。',
                      severity='info', key=locator)
            field = 'polished_bullets' if section == 'projects' else 'bullets'
            lines = item.get(field) or []
            probe_item = deepcopy(item)
            _body_cleanup(probe_item, {}, field)
            if probe_item.get(field, []) != [clean_prose(line) for line in lines]:
                issue('repeated_point', section, iid, field, '这条经历的要点中有重复表述。',
                      '同一动作只表达一次，合并前保留独有数字、分工和限制条件。', key=locator)
            for line_index, line in enumerate(lines):
                prose(line, section, iid, field, f'{locator}:{line_index}')
            for field in ('description', 'highlights', 'summary'):
                if item.get(field) and not (field == 'description' and lines):
                    prose(item[field], section, iid, field, locator)
    for field in ('summary', 'self_evaluation'):
        if data.get(field):
            prose(data[field], field, None, field, '')

    if has_jd:
        for requirement in _jd_gaps(data, collected, jd_info or {}, meta or {}):
            issue('jd_gap', 'resume', None, None,
                  f'稿件中尚未找到对应证据的岗位要求：{requirement}。',
                  '核对是否已有真实经历能证明这项要求；有则补充具体做法，没有则保留差距，不编造能力。',
                  key=requirement)
    return {'status': 'ok', 'issues': issues,
            'counts': {level: sum(row['severity'] == level for row in issues)
                       for level in ('error', 'warning', 'info')}}


def _jd_gaps(data, collected, jd_info, meta):
    """Literal matching plus valid writer evidence; never infer missing ability."""
    from app.services.resume_review import resume_to_text, _contains_skill, _skill_parts
    from app.services.resume_versions import valid_bullet_metadata
    from app.services.tech_stack import NEGATIVE
    profile = jd_info.get('role_profile') or {}
    if profile.get('source') == 'direction':
        return []
    visible = {row.get('item_id') for section in ITEM_SECTIONS
               for row in data.get(section) or [] if not row.get('hidden')}
    active = {fact.get('id') for section in (*ITEM_SECTIONS, 'internship')
              for row in collected.get(section) or [] for fact in row.get('facts') or []
              if fact.get('status', 'active') == 'active'}
    valid = valid_bullet_metadata(data, meta)
    covered = {req for iid, records in valid.get('bullets', {}).items() if iid in visible
               for record in records if set(record.get('fact_ids') or []) & active
               for req in record.get('req_ids') or []}
    # A mention in a negative/planned clause is not evidence of actual use.
    clauses = [part for part in re.split(r'[，,。；;\n]', resume_to_text(data)) if not NEGATIVE.search(part)]
    requirements = [(row.get('text', ''), row.get('id'), False) for row in profile.get('requirements') or []
                    if row.get('source', 'jd') == 'jd']
    requirements += [(text, None, True) for text in jd_info.get('required_skills') or []]
    requirements += [(text, None, False) for text in jd_info.get('hard_requirements') or []]
    missing = []
    for text, req_id, skill in requirements:
        if not isinstance(text, str) or not text.strip() or req_id and req_id in covered:
            continue
        terms = _skill_parts(text) if skill else [text]
        if any(_contains_skill(clause, term) for clause in clauses for term in terms if term.strip()):
            continue
        if text not in missing:
            missing.append(text)
    return missing


def precheck_context_hash(state):
    from app.services.resume_capacity import resume_data_hash
    return resume_data_hash({key: state.get(key) for key in ('collected_info', 'jd_info', 'jd_text', 'jd_skipped')})


def precheck_for_state(state):
    from app.services.resume_capacity import resume_data_hash
    data = state.get('resume_data') or {}
    jd = state.get('jd_info') or {}
    has_jd = not state.get('jd_skipped') and bool(state.get('jd_text') or jd)
    return {**check_resume(data, state.get('collected_info'), jd_info=jd, has_jd=has_jd,
                           meta=state.get('resume_meta')),
            'data_hash': resume_data_hash(data), 'context_hash': precheck_context_hash(state)}
