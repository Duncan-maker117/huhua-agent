"""Document history and per-item diff; facts are never restored from versions."""
from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import uuid

ITEM_SECTIONS = ('education', 'work_experience', 'projects', 'campus', 'open_source', 'awards')


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def valid_bullet_metadata(data: dict, meta: dict) -> dict:
    """A manual rewrite invalidates its AI evidence, including after reordering."""
    result = deepcopy(meta or {})
    existing = result.get('bullets') or {}
    valid = {}
    for section, field in (('projects', 'polished_bullets'), ('work_experience', 'bullets'), ('campus', 'bullets'), ('open_source', 'bullets'), ('awards', 'bullets')):
        for item in data.get(section) or []:
            available = defaultdict(deque)
            for record in existing.get(item.get('item_id'), []):
                if isinstance(record, dict) and record.get('text_hash'):
                    available[record['text_hash']].append(record)
            # Preserve positional holes: consumers align these rows with the
            # visible bullets. Each saved record can attest to one occurrence.
            records = []
            for line in item.get(field) or []:
                matches = available[text_hash(line)]
                records.append(matches.popleft() if matches else {})
            if any(records):
                valid[item['item_id']] = records
    result['bullets'] = valid
    return result


def document_diff(before: dict, after: dict) -> list[dict]:
    """Stable identities pair renamed/reordered experiences without losing removals."""
    changes = []
    for section in ITEM_SECTIONS:
        old_items, new_items = before.get(section) or [], after.get(section) or []
        def keyed(items):
            return {item.get('item_id') or f'{section}:{index}': item for index, item in enumerate(items)}
        old, new = keyed(old_items), keyed(new_items)
        for item_id in dict.fromkeys([*old, *new]):
            if old.get(item_id) != new.get(item_id):
                changes.append({'section': section, 'item_id': item_id,
                                'before': deepcopy(old.get(item_id)), 'after': deepcopy(new.get(item_id))})
        old_order, new_order = list(old), list(new)
        if old_order != new_order and set(old_order) == set(new_order):
            changes.append({'section': section, 'item_id': None, 'field': 'order',
                            'before': old_order, 'after': new_order})
    for field in ('basic_info', 'skills', 'skill_groups', 'certificates', 'summary', 'self_evaluation', 'sections', 'layout'):
        if before.get(field) != after.get(field):
            changes.append({'section': field, 'item_id': None,
                            'before': deepcopy(before.get(field)), 'after': deepcopy(after.get(field))})
    return changes


def prepare_version(current_data: dict, current_meta: dict, versions: list, new_data: dict,
                    new_meta: dict, *, label: str = '简历更新') -> dict:
    """Return one atomic save payload; the caller commits data/meta/history together."""
    diff = document_diff(current_data or {}, new_data or {})
    history = deepcopy(versions or [])
    meta = valid_bullet_metadata(new_data, new_meta)
    if not diff:
        return {'resume_data': deepcopy(new_data), 'resume_meta': meta,
                'resume_versions': history[-10:], 'version_id': (current_meta or {}).get('version_id'),
                'diff': [], 'changed': False}
    created_at = datetime.now(UTC).isoformat()
    if current_data:
        history.append({'version_id': (current_meta or {}).get('version_id') or str(uuid.uuid4()),
                        'label': (current_meta or {}).get('label') or '修改前',
                        'created_at': created_at, 'resume_data': deepcopy(current_data),
                        'resume_meta': deepcopy(current_meta or {})})
    version_id = str(uuid.uuid4())
    meta.update(version_id=version_id, label=label)
    return {'resume_data': deepcopy(new_data), 'resume_meta': meta, 'resume_versions': history[-10:],
            'version_id': version_id, 'diff': diff, 'changed': True}


def restore_payload(stored: dict, version_id: str | None = None) -> dict:
    """Select only an existing stored document snapshot, retaining current fact master."""
    history = stored.get('resume_versions') or []
    if not history:
        raise ValueError('没有可撤销的版本')
    index = len(history) - 1
    if version_id is not None:
        index = next((i for i, row in enumerate(history) if row.get('version_id') == version_id), -1)
        if index < 0:
            raise ValueError('版本不存在或已经过期')
    selected = deepcopy(history[index])
    restored = selected.setdefault('resume_data', {})
    for section in ITEM_SECTIONS:
        if section not in restored and not (stored.get('resume_data') or {}).get(section):
            continue
        restored_items = restored.setdefault(section, [])
        ids = {item.get('item_id') for item in restored_items if item.get('item_id')}
        for item in (stored.get('resume_data') or {}).get(section) or []:
            if item.get('item_id') and item['item_id'] not in ids:
                restored_items.append({**deepcopy(item), 'hidden': True})
    from app.services.profile_bridge import sanitize_fact_history
    cleaned = sanitize_fact_history({'collected_info': deepcopy(stored.get('collected_info') or {}),
                                     'resume_data': selected.get('resume_data') or {},
                                     'resume_meta': selected.get('resume_meta') or {}})
    meta = valid_bullet_metadata(cleaned['resume_data'], cleaned['resume_meta'])
    meta['version_id'] = selected['version_id']
    return {'resume_data': cleaned['resume_data'], 'resume_meta': meta,
            'resume_versions': deepcopy(history[:index]), 'version_id': selected['version_id'],
            'diff': document_diff(stored.get('resume_data') or {}, cleaned['resume_data'])}


EDUCATION_CORRECTION_NOTE = '学校、专业等基本信息的更正属于事实资料，撤销不会还原；要改回请直接告诉我。'


def education_correction_note(collected: dict | None) -> str:
    """撤销只恢复文稿；用户更正过的教育字段（事实母版）保留。有更正时回执里说清这一点。"""
    for item in (collected or {}).get('education') or []:
        if not isinstance(item, dict):
            continue
        for fact in item.get('facts') or []:
            if (isinstance(fact, dict) and fact.get('status') == 'superseded'
                    and fact.get('field') in {'school', 'major', 'degree', 'grade', 'start_date', 'end_date'}):
                return EDUCATION_CORRECTION_NOTE
    return ''
