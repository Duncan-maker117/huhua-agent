"""Deterministic, item-local cleanup of repeated metrics and action clauses."""
from copy import deepcopy
import re

from app.services.fact_guard import extract_numbers
from app.services.resume_versions import text_hash

_CLAUSES = re.compile(r'[，；;,]')
_LIMIT = re.compile(r'仅|只|(?:尚|并)?未|没有|不是|不负责|由|指导|约|基础版本|测试环境|课堂|离线|本地|自拟|人工判定|模拟')
_ACTION = re.compile(r'负责|参与|访谈|整理|绘制|设计|编写|开发|实现|搭建|测试|判定|正确|提高|提升|降低|完成|'
                     r'处理|协助|维护|优化|上线|部署|发布|收集|制作|分析|改进|联调|使用|用|审批|验证')


def clause_key(text: str) -> str:
    from app.services.resume_limits import _limit_key
    value = _limit_key(text)
    value = re.sub(r'[^\w\u4e00-\u9fff]', '', value)
    value = re.sub(r'^(?:我|本人)', '', value)
    value = re.sub(r'^(?:用|以)(?=\d)', '在', value)
    value = re.sub(r'(?<=[制写理])了', '', value)
    return value


def clause_covered(clause: str, previous: str) -> bool:
    """Grammar-only near matches; unique numbers and qualifiers always win."""
    wanted, kept = clause_key(clause), clause_key(previous)
    if len(wanted) < 8 or not wanted or extract_numbers(clause) != extract_numbers(previous):
        return False
    if wanted == kept:
        return True
    if _LIMIT.search(clause) or _LIMIT.search(previous):
        return False
    # Same conservative character-set style as resume_limits._already_visible;
    # require both directions so an independent action cannot be swallowed.
    a = re.sub(r'[的了一个对把将在并和与及等]', '', wanted)
    b = re.sub(r'[的了一个对把将在并和与及等]', '', kept)
    return a == b


def _parts(text):
    return [part.strip(' 。') for part in _CLAUSES.split(text) if part.strip(' 。')]


def _merge_record(target, source, text):
    for field in ('fact_ids', 'req_ids'):
        target[field] = list(dict.fromkeys([*target.get(field, []), *source.get(field, [])]))
    # Entailment caches refer to whole old strings, not surviving fragments.
    target.pop('coverage_fact_ids', None)
    target['text_hash'] = text_hash(text)


def changed_bullet_items(before: dict, after: dict) -> set[str]:
    """Scope a generated edit to items whose body it actually changed."""
    changed = set()
    for section in ('projects', 'work_experience', 'internship', 'campus', 'open_source', 'awards'):
        field = 'polished_bullets' if section == 'projects' else 'bullets'
        old_items = {row.get('item_id'): row for row in before.get(section) or []}
        changed.update(row['item_id'] for row in after.get(section) or []
                       if row.get('item_id') and row.get(field) != old_items.get(row['item_id'], {}).get(field))
    return changed


def deduplicate_resume(data: dict, meta: dict, *, item_ids=None) -> bool:
    """Mutate canonical bullets and aligned citations; never cross item bounds."""
    changed = False
    allowed = None if item_ids is None else set(item_ids)
    for section in ('projects', 'work_experience', 'internship', 'campus', 'open_source', 'awards'):
        field = 'polished_bullets' if section == 'projects' else 'bullets'
        for item in data.get(section) or []:
            if item.get('hidden') or allowed is not None and item.get('item_id') not in allowed:
                continue
            original = item.get(field) or []
            if len(original) < 2 or not all(isinstance(text, str) for text in original):
                continue
            prior = meta.get('bullets', {}).get(item.get('item_id'), [])
            rows = []
            for index, text in enumerate(original):
                record = deepcopy(prior[index]) if index < len(prior) and prior[index].get('text_hash') == text_hash(text) else {}
                rows.append({'text': text, 'record': record})
            # Same complete numeric set (at least two values) is one metric.
            groups = {}
            for index, row in enumerate(rows):
                numbers = frozenset(extract_numbers(row['text']))
                if len(numbers) >= 2:
                    groups.setdefault(numbers, []).append(index)
            removed = set()
            for indices in groups.values():
                if len(indices) < 2:
                    continue
                winner = max(indices, key=lambda i: (len(set(_LIMIT.findall(rows[i]['text']))),
                                                     len(clause_key(rows[i]['text'])), -i))
                kept = rows[winner]
                for index in indices:
                    if index == winner:
                        continue
                    other = rows[index]
                    # Preserve independent actions and unique limitations even
                    # when they accompanied a duplicate metric in the old row.
                    for clause in _parts(other['text']):
                        if clause_key(clause) in clause_key(kept['text']):
                            continue
                        numbers = extract_numbers(clause)
                        if len(numbers) >= 2:
                            if set(_LIMIT.findall(clause)) <= set(_LIMIT.findall(kept['text'])):
                                continue
                        if not any(clause_covered(clause, part) for part in _parts(kept['text'])):
                            kept['text'] = kept['text'].rstrip('。；;，, ') + '，' + clause
                    _merge_record(kept['record'], other['record'], kept['text'])
                    removed.add(index)
            rows = [row for i, row in enumerate(rows) if i not in removed]
            cleaned = []
            for row in rows:
                parts, retained, targets = _parts(row['text']), [], []
                for clause in parts:
                    target = next((old for old in cleaned if any(
                        clause_covered(clause, part) for part in _parts(old['text']))), None)
                    if target is None:
                        retained.append(clause)
                    else:
                        targets.append(target)
                if targets:
                    row['text'] = '，'.join(retained)
                    for target in targets:
                        _merge_record(target['record'], row['record'], target['text'])
                    row['record'].pop('coverage_fact_ids', None)
                    row['record']['text_hash'] = text_hash(row['text'])
                    if row['text'] and not _ACTION.search(row['text']):
                        # A leftover scope/condition belongs with the action;
                        # never discard a unique qualifier as a dangling row.
                        target = targets[0]
                        target['text'] = target['text'].rstrip('。 ') + '，' + row['text']
                        _merge_record(target['record'], row['record'], target['text'])
                        row['text'] = ''
                if row['text']:
                    cleaned.append(row)
            texts = [row['text'] for row in cleaned]
            if texts != original:
                item[field] = texts
                if prior or any(row['record'].get('fact_ids') for row in cleaned):
                    meta.setdefault('bullets', {})[item['item_id']] = [
                        {**row['record'], 'text_hash': text_hash(row['text'])} for row in cleaned]
                changed = True
    return changed
