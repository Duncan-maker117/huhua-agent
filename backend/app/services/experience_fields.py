"""Deterministic header values. Quotes are evidence, never display-ready copy.

Unknown dates stay in field_confirmations, outside active body facts. Relative
dates are resolved once at ingestion; no month, translation or role is invented.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import re
import unicodedata
from zoneinfo import ZoneInfo

from app.schemas.facts import FACT_FIELDS, FACT_LABELS, FACT_SECTIONS

HEADER_FIELDS = {'name', 'company', 'school', 'degree', 'major', 'role', 'title', 'start_date', 'end_date', 'date'}
_EDGES = ' \t\r\n，,。；;：:！!？?、"\'“”‘’「」『』'
_NAME_LEAD = re.compile(r'^(?:(?:这个|那个|这段|这个项目的)?(?:项目|经历|公司|组织|它)?'
                        r'(?:的)?(?:名字叫做|名字叫|名字是|名字为|名称是|名称为|名叫|叫做|名为|叫)|'
                        r'(?:名字|名称)\s*[:：]|就是|是)\s*[:：]?\s*')


def normalize_name(value):
    value = str(value or '').strip(_EDGES)
    while len(value) > 1 and (value[0], value[-1]) in {('【', '】'), ('[', ']'), ('《', '》'), ('（', '）'), ('(', ')')}:
        value = value[1:-1].strip(_EDGES)
    while value:
        clean = _NAME_LEAD.sub('', value, count=1).strip(_EDGES)
        if clean == value:
            break
        value = clean
    return value


def name_key(value):
    # Ignore typography, never remove a positioning/name suffix or meaningful
    # punctuation (C++, C# etc. are different names).
    value = unicodedata.normalize('NFKC', normalize_name(value)).casefold()
    return re.sub(r'[\s_\-‐‑‒–—―·•|]+', '', value)


def names_match(left, right):
    from app.services.candidate_language import placeholder_name
    if placeholder_name(left) or placeholder_name(right):
        return False
    a, b = name_key(left), name_key(right)
    return bool(a and b and a == b)


def names_similar(left, right):
    """Advisory/explicit-edit matching only; never a fact ingestion identity."""
    from app.services.candidate_language import placeholder_name
    if placeholder_name(left) or placeholder_name(right):
        return False
    a, b = (name_key(re.split(r'[｜|]', str(value or ''))[0]) for value in (left, right))
    if a == b:
        return bool(a)
    short, long = sorted((a, b), key=len)
    if len(short) < 4 or short in {'agent', '项目', '管理系统', '旅行规划', '简历工具', '个人项目'}:
        return False
    if re.fullmatch(r'[a-z0-9]+', short):
        contains = bool(re.search(r'(?<![a-z0-9])' + re.escape(short) + r'(?![a-z0-9])', long))
    else:
        contains = short in long
    from difflib import SequenceMatcher
    close = (len(short) >= 6 and re.findall(r'\d+', a) == re.findall(r'\d+', b)
             and SequenceMatcher(None, a, b).ratio() >= .85)
    return contains or close


def profile_item_refs(item):
    """Only archive item identity; a fact, message or upload is not an item."""
    refs = set()
    for row in [item, *(item.get('facts') or [])]:
        if row.get('profile_item_id'):
            refs.add(str(row['profile_item_id']))
        for ref in row.get('profile_refs') or []:
            if isinstance(ref, dict) and (key := ref.get('profile_item_id') or ref.get('item_id')):
                refs.add(str(key))
        source = row.get('source')
        if isinstance(source, dict) and (key := source.get('profile_item_id') or source.get('item_id')):
            refs.add(str(key))
    return refs


def same_experience(left, right, section):
    if profile_item_refs(left) & profile_item_refs(right):
        return True
    label = FACT_LABELS[section]
    if not names_match(left.get(label), right.get(label)):
        return False
    if section == 'education':
        # Missing program identity is not evidence of the same qualification.
        if not all(left.get(k) and right.get(k) and name_key(left[k]) == name_key(right[k])
                   for k in ('degree', 'major')):
            return False
    for key in ('start_date', 'end_date'):
        values = {normalize_date_value(value, end=key == 'end_date') or value
                  for row in (left, right) for value in [row.get(key), *[
                      f['text'] for f in row.get('facts') or [] if f.get('field') == key and f.get('status', 'active') == 'active']]
                  if value}
        if len(values) > 1:
            return False
    from app.services.resume_field_hygiene import sourced_role
    roles = {name_key(normalize_role(role)) for row in (left, right)
             for role in [sourced_role([], row.get('role') or row.get('title') or ''), *[
                 sourced_role([fact]) for fact in row.get('facts') or []]] if role}
    if len(roles) > 1:
        return False
    if section == 'open_source' and left.get('pr') and right.get('pr') and left['pr'] != right['pr']:
        return False
    if section == 'awards' and left.get('level') and right.get('level') and left['level'] != right['level']:
        return False
    return True


def normalize_role(value):
    value = str(value or '').strip(_EDGES)
    value = re.sub(r'^(?:(?:我|本人)(?:的角色)?(?:是)?|担任(?:的是|了)?|做的是|角色(?:是|为))\s*[:：]?\s*', '', value)
    value = re.sub(r'^(?:担任(?:的是|了)?|做的是|是)\s*', '', value).strip(_EDGES)
    if re.fullmatch(r'(?:个人项目|独立完成(?:的)?|(?:我)?自己做的|(?:我)?一个人做的)', value):
        return '个人项目'
    return value


def reference_date():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date()


def normalize_date_value(value, *, end=False, today=None):
    text = unicodedata.normalize('NFKC', str(value or '')).strip(_EDGES)
    if re.fullmatch(r'至今|现在|目前|今|now|present|current|ongoing', text, re.I):
        return '至今' if end else None
    expected = '预计' in text
    text = re.sub(r'^预计\s*|\s*(?:\(预计\)|预计)$', '', text).strip()
    relative = re.fullmatch(r'(前年|去年|今年)(?:\s*(\d{1,2})\s*月)?', text)
    if relative:
        year = (today or reference_date()).year + {'前年': -2, '去年': -1, '今年': 0}[relative[1]]
        month = relative[2]
    else:
        match = re.fullmatch(r'(\d{4}|\d{2})(?:\s*[年./-]\s*(\d{1,2})\s*月?|年)?', text)
        if not match:
            return None
        year, month = int(match[1]), match[2]
        if len(match[1]) == 2:
            year += 2000
    if not 1900 <= year <= 2099 or month is not None and not 1 <= int(month) <= 12:
        return None
    return str(year) + (f'.{int(month):02d}' if month else '') + ('（预计）' if expected else '')


_POINT = r'(?:(?:\d{4}|\d{2})(?:\s*[年./-]\s*\d{1,2}\s*月?|年)?|(?:前年|去年|今年)(?:\s*\d{1,2}\s*月)?)'
_NOW = r'(?:至今|现在|目前|now|present|current|ongoing)'
_DATED_POINT = rf'(?:预计\s*)?{_POINT}(?:\s*\(预计\))?'
_RANGE = re.compile(rf'({_DATED_POINT})\s*(?:至(?!今)|到|[-–—~～/]|to)\s*({_DATED_POINT}|{_NOW}|\d{{1,2}}月)', re.I)
_STARTED = re.compile(rf'({_DATED_POINT})\s*开始')


def parse_dates(value, target=None, *, today=None):
    text = unicodedata.normalize('NFKC', str(value or '')).strip(_EDGES)
    text = re.sub(r'^(?:项目)?(?:起止时间|时间|日期)(?:是|为|[:：])?\s*', '', text)
    target = target or {}
    if match := _STARTED.fullmatch(text):
        value = normalize_date_value(match[1], today=today)
        return {'start_date': value} if value else {}
    missing = [key for key in ('start_date', 'end_date') if not target.get(key)]
    field = missing[0] if len(missing) == 1 else 'start_date'
    single = normalize_date_value(text, end=field == 'end_date', today=today)
    if single:
        return {field: single}
    if re.fullmatch(r'(?:\d{4}|\d{2})[./-]\d{1,2}', text):
        return {}  # An invalid single month must not backtrack into a year range.
    match = _RANGE.fullmatch(text)
    if not match:
        match = re.fullmatch(rf'({_POINT})\s*({_NOW})', text, re.I)
    if match:
        if re.fullmatch(r'\d{2}', match[1]) and re.fullmatch(r'\d{2}', match[2]):
            return {}  # 26-13 is an invalid month, not evidence of two years.
        start = normalize_date_value(match[1], today=today)
        end = normalize_date_value(match[2], end=True, today=today)
        if start and re.fullmatch(r'\d{1,2}月', match[2]):
            end = normalize_date_value(start[:4] + '.' + match[2][:-1], end=True, today=today)
        if not start or not end or end != '至今' and end < start:
            return {}
        return {'start_date': start, 'end_date': end}
    return {}


def dates_in_text(value):
    """Extract literal periods/start statements from one item's own fact only."""
    text = unicodedata.normalize('NFKC', str(value or ''))
    text = re.sub(r'https?://[^\s，。；;<>]+', '', text)
    matches = list(_RANGE.finditer(text)) or list(_STARTED.finditer(text))
    matches = [m for m in matches if re.search(r'\d{4}|[年./]|前年|去年|今年', m[0])
               and not (m.start() and (text[m.start() - 1].isascii() and text[m.start() - 1].isalnum() or text[m.start() - 1] in './-'))
               and not re.match(r'[A-Za-z\d./-]|\s*(?:条|个|人|次|页|毫秒|秒|%|％)', text[m.end():])]
    values = [parse_dates(m[0]) for m in matches]
    return values[0] if len(values) == 1 else {}


def date_like(value):
    """Only a complete header-shaped date, including malformed months; never an action."""
    text = str(value or '').strip(_EDGES)
    text = re.sub(r'^(?:项目)?(?:起止时间|时间|日期)(?:是|为|[:：])?\s*', '', text)
    return bool(_RANGE.fullmatch(unicodedata.normalize('NFKC', text)) or _STARTED.fullmatch(text) or re.fullmatch(rf'{_POINT}\s*{_NOW}', text, re.I)
                or re.fullmatch(r'(?:\d{2}|\d{4})[年./-]\d{1,2}月?|(?:前年|去年|今年)\d{1,2}月', text))


def normalize_field(field, value, *, today=None):
    if field in {'name', 'company', 'school'}:
        return normalize_name(value)
    if field in {'role', 'title'}:
        return normalize_role(value)
    if field in {'start_date', 'end_date', 'date'}:
        return normalize_date_value(value, end=field == 'end_date', today=today)
    return value


def require_confirmation(item, field, quote, *, fact=None):
    row = {**deepcopy(fact or {}), 'field': field, 'source_quote': quote,
           'item_id': item.get('item_id', ''), 'reason': 'unparsed_header',
           'message': '请按这句原话再确认一次字段值；未确认前不得写成要点。',
           'confirmation_attempts': int(str((fact or {}).get('question_id', '')).startswith('confirm_'))}
    row.pop('text', None)
    pending = item.setdefault('field_confirmations', [])
    pending[:] = [r for r in pending if r['field'] != field or r.get('turn_id') == row.get('turn_id')]
    if not any((r['field'], r['source_quote'], r.get('turn_id')) ==
               (field, quote, row.get('turn_id')) for r in pending):
        pending.append(row)


def confirmation_requests(collected):
    return [deepcopy(row) for section in FACT_SECTIONS for item in collected.get(section) or []
            for row in item.get('field_confirmations') or []]


def normalize_item_fields(item, section):
    """Shared fact-store boundary used by cards, extraction, editor and imports."""
    from app.services.resume_facts import new_fact
    label = FACT_LABELS[section]
    facts, normalized = item.get('facts') or [], []
    if section == 'education':
        from app.services.education_fields import recover_education_identity
        recover_education_identity(item)
    for field in (label, 'role', 'title', 'start_date', 'end_date', 'date'):
        raw = item.get(field)
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = normalize_field(field, raw)
        if value is None:
            item.pop(field, None)
            if not any(f.get('field') == field for f in facts):
                require_confirmation(item, field, raw)
        else:
            item[field] = value
            if value != raw and not any(f.get('field') == field for f in facts):
                key = '\0'.join((item.get('item_id', ''), field, raw))
                facts.append({**new_fact(value, quote=raw, kind='role' if field in {'role', 'title'} else 'context'),
                              'id': 'fh_' + hashlib.sha256(key.encode()).hexdigest()[:24], 'field': field})
    for fact in facts:
        if fact.get('status', 'active') != 'active':
            normalized.append(fact)
            continue
        field, text = fact.get('field'), fact['text']
        fields = parse_dates(text, item) if date_like(text) else {}
        if (field in {None, 'dates', 'duration'} and date_like(text)
                or field in {'start_date', 'end_date'} and len(fields) == 2):
            if not fields:
                require_confirmation(item, 'dates', fact.get('source_quote', text), fact=fact)
                continue
            for index, (key, value) in enumerate(fields.items()):
                normalized.append({**deepcopy(fact), 'id': fact['id'] + ('__' + key if index else ''),
                                   'field': key, 'kind': 'context', 'text': value})
                item[key] = value
            continue
        # A combined education/context sentence remains intact as evidence;
        # its dates also receive source-bound structured facts.
        if not field:
            for key, value in dates_in_text(text).items():
                if not item.get(key) and not any(f.get('field') == key and f.get('status', 'active') == 'active' for f in facts):
                    item[key] = value
                    normalized.append({**deepcopy(fact), 'id': fact['id'] + '__' + key,
                                       'field': key, 'kind': 'context', 'text': value})
        from app.services.resume_field_hygiene import positive_role
        role_field = not field and fact.get('kind') == 'role' and positive_role(text)
        value = normalize_field('role' if role_field else field, text)
        if value is None:
            require_confirmation(item, field, fact.get('source_quote', text), fact=fact)
            continue
        fact['text'] = value
        normalized.append(fact)
        if field in FACT_FIELDS[section] and (not item.get(field) or field in {'start_date', 'end_date'}):
            item[field] = value
    item['facts'] = normalized


def matching_item(items, candidate, section):
    """Ambiguous names and disjoint engagements are never silently coalesced."""
    matches = [row for row in items if row is not candidate and not row.get('hidden')
               and not candidate.get('hidden') and same_experience(row, candidate, section)]
    return matches[0] if matches and all(same_experience(a, b, section)
                                        for index, a in enumerate(matches) for b in matches[index + 1:]) else None


def canonicalize_catalog_names(store, catalog):
    """Use an already available archive name without importing its other facts."""
    changed = False
    categories = {'projects': 'project', 'work_experience': 'work', 'internship': 'work',
                  'campus': 'campus', 'open_source': 'open_source', 'awards': 'awards'}
    for section, category in categories.items():
        label = FACT_LABELS[section]
        known = [{label: normalize_name(row.get('name')), 'start_date': row.get('start'),
                  'end_date': row.get('end'), 'role': row.get('role'), 'profile_item_id': row.get('profile_item_id') or row.get('id')}
                 for row in catalog or [] if row.get('category') == category]
        for item in store.get(section) or []:
            match = matching_item(known, item, section)
            if match is None:
                continue
            changed = changed or item.get(label) != match[label]
            item[label] = match[label]
            for fact in item.get('facts') or []:
                if fact.get('field') == label and fact.get('status', 'active') == 'active' and names_match(fact['text'], match[label]):
                    fact['text'] = match[label]
    return changed


def merge_normalized_experiences(store, previous):
    """Only proven identities coalesce, including duplicates in one extraction."""
    from app.services.fact_corrections import apply_experience_merges
    for section in ('projects', 'work_experience', 'internship', 'education', 'campus', 'open_source'):
        label = FACT_LABELS[section]
        prior = {row['item_id']: row for row in previous.get(section) or [] if row.get('item_id')}
        rows = store.get(section) or []
        for row in rows[:]:
            if not row.get('item_id'):
                continue  # Legacy records must acquire stable IDs before a merge.
            if not any(item is row for item in rows):
                continue
            target = matching_item([item for item in rows if item.get('item_id')], row, section)
            if target is None:
                continue
            # Keep established/first identity, independently of spelling length.
            row_established, target_established = row['item_id'] in prior, target['item_id'] in prior
            if (row_established and not target_established
                    or row_established == target_established and rows.index(row) < rows.index(target)):
                row, target = target, row
            # Preserve the established spelling, ID, facts and source bindings.
            quote = next((f.get('source_quote') for f in row.get('facts') or [] if f.get('field') == label), row.get(label, ''))
            pending = deepcopy(row.get('field_confirmations') or [])
            active_names = {f['id'] for item in (target, row) for f in item.get('facts') or []
                            if f.get('field') == label and f.get('status', 'active') == 'active'}
            apply_experience_merges(store, [{'section': section, 'name': target[label],
                'target_item_id': target['item_id'], 'source_item_ids': [row['item_id']],
                'source_quote': quote, 'turn_id': ''}])
            for fact in target.get('facts') or []:
                if fact.get('field') == label and names_match(fact['text'], target[label]):
                    fact['text'] = target[label]
                    if fact['id'] in active_names:
                        fact['status'] = 'active'
            if pending:
                target.setdefault('field_confirmations', []).extend({**r, 'item_id': target['item_id']} for r in pending)
            normalize_item_fields(target, section)
    return store
