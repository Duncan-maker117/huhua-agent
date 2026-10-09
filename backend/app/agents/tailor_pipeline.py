"""Run bounded writing, actual page checks and one document-version transaction."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import re

from app.agents.resume_writer import run_resume_writer
from app.services.resume_capacity import (
    MAX_COMPRESSION_ROUNDS, apply_deterministic_compression, measure_rendered_pages,
    normalize_session_constraints, plan_compression, resume_data_hash,
)
from app.services.resume_versions import prepare_version, text_hash, valid_bullet_metadata
from app.services.resume_limits import preserve_item_limits
from app.services.resume_facts import active_facts_for_writer
from app.services.fact_guard import verify_semantics


def turn_instruction(message: str) -> str:
    if '[文件:' in message or '[文件：' in message:
        return message.rsplit('\n\n---\n\n', 1)[-1] if '\n\n---\n\n' in message else ''
    return message


def constraints_for_turn(state: dict, message: str) -> dict:
    profile = (state.get('jd_info') or {}).get('role_profile') or {}
    instruction = turn_instruction(message)
    overrides = {}
    pages = re.findall(r'([一二两12])\s*页', instruction)
    if pages:
        overrides['page_limit'] = {'一': 1, '1': 1, '二': 2, '两': 2, '2': 2}[pages[-1]]
    if re.search(r'(?:用|改成|改为|需要|写一份|生成)(?:一份)?英文', instruction):
        overrides['language'] = 'en'
    elif re.search(r'(?:用|改成|改为|需要)(?:一份)?中文', instruction):
        overrides['language'] = 'zh-CN'
    return normalize_session_constraints(state.get('session_constraints'),
                                         seniority=profile.get('seniority', 'unknown'), overrides=overrides)


def infer_edit_scope(data: dict, instruction: str) -> tuple[str, list[str]]:
    """Unambiguous named/ordinal selections; PR5 router handles compound intents."""
    matches = []
    aliases = {}
    for section in ('projects', 'work_experience'):
        for item in data.get(section) or []:
            name = item.get('name') or item.get('company')
            if not isinstance(name, str) or not item.get('item_id'):
                continue
            # A parser's stray function word must not select an unrelated item.
            if len(name.strip()) >= 2 and name.casefold() in instruction.casefold():
                matches.append(item['item_id'])
            for alias in re.findall(r'[“「"\']([^”」"\']{2,})[”」"\']', name):
                aliases.setdefault(alias.casefold(), set()).add(item['item_id'])
    for alias, item_ids in aliases.items():
        if len(item_ids) == 1 and alias in instruction.casefold():
            matches.extend(item_ids)
    ordinal = re.search(r'第([一二三四五六七八九十1-9])(?:个|段)?(项目|经历|实习|工作)', instruction)
    if ordinal:
        number = int(ordinal[1]) if ordinal[1].isdigit() else '一二三四五六七八九十'.index(ordinal[1]) + 1
        section = 'projects' if ordinal[2] == '项目' else 'work_experience'
        visible = [item for item in data.get(section) or [] if not item.get('hidden')]
        if number <= len(visible) and visible[number - 1].get('item_id'):
            matches.append(visible[number - 1]['item_id'])
        elif not matches:
            return 'item', []
    return ('item', list(dict.fromkeys(matches))) if matches else ('whole', [])


def _has_visible_experience_body(data: dict) -> bool:
    for section, field in (('projects', 'polished_bullets'), ('work_experience', 'bullets')):
        for item in data.get(section) or []:
            if not isinstance(item, dict) or item.get('hidden'):
                continue
            body = [item.get('description'), *(item.get(field) or [])]
            if any(isinstance(text, str) and text.strip() for text in body):
                return True
    return False


def _sanitize_preserved_state(state: dict) -> dict:
    """Revocations also apply to undo snapshots; old page counts then expire."""
    from app.services.profile_bridge import sanitize_fact_history
    source = active_facts_for_writer(state.get('collected_info') or {})
    active_items = {
        'projects': {item['item_id'] for item in source.get('projects') or []},
        'work_experience': {item['item_id'] for section in ('work_experience', 'internship')
                            for item in source.get(section) or []},
    }
    skills = {skill.get('name') for skill in source.get('skills') or []}
    result = sanitize_fact_history(state)
    for before, version in zip(state.get('resume_versions') or [], result.get('resume_versions') or []):
        draft = version.get('resume_data') or {}
        for section, identifiers in active_items.items():
            if section in draft:
                draft[section] = [item for item in draft[section] or []
                                  if item.get('item_id') in identifiers]
        if 'skills' in draft:
            draft['skills'] = [skill for skill in draft['skills'] or [] if skill in skills]
        if 'skill_groups' in draft:
            draft['skill_groups'] = {heading: kept for heading, names in (draft['skill_groups'] or {}).items()
                                     if (kept := [name for name in names if name in skills])}
        if draft == (before.get('resume_data') or {}):
            continue
        meta = valid_bullet_metadata(draft, version.get('resume_meta') or {})
        page = meta.get('page_check') or {}
        if page:
            meta['page_check'] = {**page, 'status': 'stale', 'pages': None, 'within_page_limit': None,
                                  'data_hash': resume_data_hash(draft),
                                  'pre_sanitization_data_hash': page.get('data_hash'),
                                  'reason': 'fact_history_sanitized'}
        version['resume_meta'] = meta
        if 'resume_draft' in version:
            from app.services.resume_review import resume_to_text
            version['resume_draft'] = resume_to_text(draft)
    return result


def _preserve_supported_body(state: dict, base_data: dict) -> dict:
    """Keep prior prose only for identities still backed by the fact master.

    The deterministic projection owns confirmed fields and deletions. A prior
    polished body is presentation, never a replacement source of facts.
    """
    from app.services.resume_versions import text_hash
    source = active_facts_for_writer(state.get('collected_info') or {})
    current = state.get('resume_data') or {}
    data = deepcopy(base_data)
    meta = deepcopy(state.get('resume_meta') or {})
    active_refs = {fact['id'] for section in ('projects', 'work_experience', 'internship', 'education')
                   for item in source.get(section) or [] for fact in item.get('facts') or []}
    for section, source_sections, body_fields in (
        ('projects', ('projects',), ('description', 'polished_bullets')),
        ('work_experience', ('work_experience', 'internship'), ('description', 'bullets')),
    ):
        active_items = {item['item_id'] for source_section in source_sections
                        for item in source.get(source_section) or []}
        old = {item.get('item_id'): item for item in current.get(section) or [] if item.get('item_id')}
        order = {item.get('item_id'): index for index, item in enumerate(current.get(section) or [])
                 if item.get('item_id')}
        rows = []
        for item in data.get(section) or []:
            identifier = item.get('item_id')
            if identifier not in active_items:
                continue
            prior = old.get(identifier)
            if prior:
                for field in body_fields:
                    if field in prior:
                        item[field] = deepcopy(prior[field])
                if 'hidden' not in item and 'hidden' in prior:
                    item['hidden'] = prior['hidden']
            rows.append(item)
        rows.sort(key=lambda item: order.get(item.get('item_id'), len(order)))
        if section in data or section in current:
            data[section] = rows
    summary = current.get('self_evaluation') or ''
    summary_meta = meta.get('summary') or {}
    refs = summary_meta.get('fact_ids') or []
    if refs and set(refs) <= active_refs and summary_meta.get('text_hash') == text_hash(summary):
        data['self_evaluation'] = summary
    preserved = _sanitize_preserved_state({
        'collected_info': deepcopy(state.get('collected_info') or {}),
        'resume_data': data, 'resume_meta': meta,
        'resume_versions': deepcopy(state.get('resume_versions') or []),
    })
    preserved['resume_meta'] = valid_bullet_metadata(preserved['resume_data'], preserved['resume_meta'])
    return preserved


def _compression_item(data: dict, action: dict) -> tuple[str, dict] | None:
    parts = str(action.get('target', '')).split('/')
    if len(parts) < 3 or parts[1] not in {'projects', 'work_experience'} or not parts[2].isdigit():
        return None
    rows = data.get(parts[1]) or []
    index = int(parts[2])
    if index >= len(rows) or not isinstance(rows[index], dict):
        return None
    item = rows[index]
    if action.get('item_id') and item.get('item_id') != action['item_id']:
        return None
    return parts[1], item


def _supported_compression_body(item: dict, section: str, meta: dict, collected: dict,
                                indices: list[int] | None = None) -> list[str] | None:
    field = 'polished_bullets' if section == 'projects' else 'bullets'
    body = item.get(field) or []
    selected = list(range(len(body))) if indices is None else indices
    if (not body or not selected or any(index < 0 or index >= len(body) for index in selected)
            or any(not isinstance(body[index], str) or not body[index].strip() for index in selected)):
        return None
    source = active_facts_for_writer(collected)
    sections = ('projects',) if section == 'projects' else ('work_experience', 'internship')
    facts = {fact['id'] for key in sections for row in source.get(key) or []
             if row.get('item_id') == item.get('item_id') for fact in row.get('facts') or [] if fact.get('id')}
    records = (meta.get('bullets') or {}).get(item.get('item_id')) or []
    if ((indices is None and len(records) != len(body))
            or any(index >= len(records) for index in selected)):
        return None
    for index in selected:
        text, record = body[index], records[index]
        if not isinstance(record, dict):
            return None
        refs = record.get('fact_ids') or []
        if (not isinstance(refs, list) or not refs or any(not isinstance(ref, str) for ref in refs)
                or not set(refs) <= facts or record.get('text_hash') != text_hash(text)):
            return None
    return body


def _compression_indices(action: dict, section: str) -> list[int] | None:
    if action.get('op') == 'merge_bullets':
        return None
    parts = str(action.get('target', '')).split('/')
    field = 'polished_bullets' if section == 'projects' else 'bullets'
    if action.get('op') != 'shorten_bullet' or len(parts) != 5 or parts[3] != field or not parts[4].isdigit():
        return []
    return [int(parts[4])]


async def _retain_compressed_body(before: dict, meta: dict, revised: dict, action: dict,
                                  collected: dict, llm) -> tuple[dict, dict, str]:
    target = _compression_item(before, action)
    if target is None:
        return before, meta, 'invalid_target'
    section, original_item = target
    indices = _compression_indices(action, section)
    prior = _supported_compression_body(original_item, section, meta, collected, indices)
    if prior is None:
        return before, meta, 'unverified_current_bullets'
    if (revised.get('writer_diagnostic') or {}).get('status') != 'model_completed':
        return before, meta, 'writer_not_completed'
    rows = (revised.get('resume_data') or {}).get(section) or []
    proposed_items = [item for item in rows if isinstance(item, dict)
                      and item.get('item_id') == original_item.get('item_id')]
    if len(proposed_items) != 1 or proposed_items[0].get('hidden'):
        return before, meta, 'invalid_compressed_item'
    proposed_meta = revised.get('resume_meta') or {}
    proposed = _supported_compression_body(proposed_items[0], section, proposed_meta, collected, indices)
    if proposed is None or (indices is None and len(proposed) != 1) or (indices is not None and len(proposed) != len(prior)):
        return before, meta, 'invalid_or_unverified_compressed_bullet'
    old_texts = prior if indices is None else [prior[index] for index in indices]
    new_texts = proposed if indices is None else [proposed[index] for index in indices]
    # Reverse entailment checks retention, independently from the writer's
    # forward fact guard. Matching citation IDs alone never proves retention.
    pairs = [{'id': f'retain_{index}', 'text': text, 'source_quotes': new_texts}
             for index, text in enumerate(old_texts)]
    try:
        decisions = await verify_semantics(pairs, llm, timeout=30)
        passed = all((decisions.get(row['id']) or {}).get('verdict') == 'pass' for row in pairs)
    except Exception:
        passed = False
    if not passed:
        return before, meta, 'semantic_retention_failed'
    # Only the selected body and its provenance may cross this boundary. Even
    # a malformed local writer cannot change a header or a sibling experience.
    data, metadata = deepcopy(before), deepcopy(meta)
    selected = _compression_item(data, action)[1]
    field = 'polished_bullets' if section == 'projects' else 'bullets'
    if indices is None:
        selected[field] = deepcopy(proposed)
        metadata.setdefault('bullets', {})[selected['item_id']] = deepcopy(
            proposed_meta['bullets'][selected['item_id']])
    else:
        for index in indices:
            selected[field][index] = proposed[index]
            metadata['bullets'][selected['item_id']][index] = deepcopy(
                proposed_meta['bullets'][selected['item_id']][index])
    return data, metadata, 'accepted'


async def apply_deterministic_update(state: dict, base_data: dict, instruction: str = '') -> dict:
    """Save a field-only edit (education, format) without calling the writer.

    Project and work prose is taken from the previous version unchanged.
    """
    constraints = constraints_for_turn(state, instruction)
    current = state.get('resume_data') or {}
    data = deepcopy(current)
    data['education'] = deepcopy(base_data.get('education') or current.get('education') or [])
    version = prepare_version(current, state.get('resume_meta') or {}, state.get('resume_versions') or [],
                              data, deepcopy(state.get('resume_meta') or {}), label='确认资料更新')
    measurement = await asyncio.to_thread(measure_rendered_pages, version['resume_data'], constraints)
    diagnostic = {'status': 'not_called', 'reason': 'deterministic_only'}
    version['resume_meta'].update(page_check=measurement, writer_diagnostic=diagnostic,
                                  guard_fallbacks=[], change_summary=[])
    return {**version, 'match_plan': deepcopy(state.get('match_plan') or {}),
            'session_constraints': constraints, 'page_check': measurement,
            'writer_diagnostic': diagnostic, 'compression_writer_diagnostics': [],
            'compression_retention_checks': [], 'guard_fallbacks': [], 'change_summary': [],
            'compression_actions': [], 'omitted': deepcopy((state.get('resume_meta') or {}).get('omitted') or [])}


async def run_tailor_pipeline(state: dict, base_data: dict, llm, *, structured_llm=None,
                              instruction: str = '', mode: str = 'one_pass',
                              scope: str = 'whole', targets=()) -> dict:
    constraints = constraints_for_turn(state, instruction)
    profile = deepcopy((state.get('jd_info') or {}).get('role_profile') or {})
    profile['target_role'] = ((state.get('jd_info') or {}).get('role_direction')
                              or (state.get('jd_info') or {}).get('job_title')
                              or (base_data.get('basic_info') or {}).get('objective') or '')
    kwargs = {'structured_llm': structured_llm, 'constraints': constraints, 'mode': mode}
    written = await run_resume_writer(state.get('collected_info') or {}, profile, llm,
        current_data=base_data, resume_meta=state.get('resume_meta') or {},
        instruction=turn_instruction(instruction), scope=scope, targets=targets, **kwargs)
    if ((written.get('writer_diagnostic') or {}).get('status') == 'model_fallback'
            and _has_visible_experience_body(state.get('resume_data') or {})):
        # Keep valid prior prose without undoing confirmed corrections/removals.
        # The failed writer's plan never authorizes compression or hiding.
        from app.services.resume_versions import document_diff
        preserved = _preserve_supported_body(state, base_data)
        data, meta = preserved['resume_data'], preserved['resume_meta']
        diff = document_diff(state['resume_data'], data)
        if diff:
            version = prepare_version(state['resume_data'], state.get('resume_meta') or {},
                preserved['resume_versions'], data, meta, label='确认资料更新（改写未完成）')
            # The new pre-change snapshot is subject to the same fact revocations.
            version = _sanitize_preserved_state({**version, 'collected_info': preserved['collected_info']})
        else:
            version = {**preserved, 'version_id': meta.get('version_id'), 'changed': False, 'diff': []}
        data = version['resume_data']
        meta = valid_bullet_metadata(data, version['resume_meta'])
        measurement = await asyncio.to_thread(measure_rendered_pages, data, constraints)
        diagnostic = {**deepcopy(written['writer_diagnostic']),
                      'fallback_action': 'preserved_existing_draft',
                      'deterministic_updates_applied': bool(diff)}
        meta.update(page_check=measurement, writer_diagnostic=diagnostic,
                    compression_writer_diagnostics=[], guard_fallbacks=[], change_summary=[])
        plan = deepcopy(meta.get('match_plan') or state.get('match_plan') or {})
        return {**version, 'resume_data': data, 'resume_meta': meta,
                'collected_info': preserved['collected_info'],
                'match_plan': plan, 'session_constraints': constraints,
                'page_check': measurement, 'writer_diagnostic': diagnostic,
                'compression_writer_diagnostics': [], 'compression_actions': [],
                'guard_fallbacks': [],
                'change_summary': [], 'omitted': deepcopy(meta.get('omitted') or [])}
    data = written['resume_data']
    meta = written['resume_meta']
    measurement = await asyncio.to_thread(measure_rendered_pages, data, constraints)
    compressed = []
    compression_diagnostics = []
    retention_checks = []
    attempted_without_progress = set()
    rejected_compression_items = set()
    for round_number in range(1, MAX_COMPRESSION_ROUNDS + 1):
        if measurement.get('within_page_limit') is not False:
            break
        actions = plan_compression(data, written.get('match_plan'), round_number=round_number, constraints=constraints)
        if scope != 'whole':
            def is_target(action):
                if action.get('op') not in {'shorten_bullet', 'merge_bullets'}:
                    return False
                path = action.get('target', '')
                if scope == 'bullet':
                    return action.get('op') == 'shorten_bullet' and path in targets
                parts = path.split('/')
                if len(parts) < 3 or not parts[2].isdigit():
                    return False
                section, index = parts[1], int(parts[2])
                if scope == 'section':
                    return section in targets
                rows = data.get(section) or []
                return index < len(rows) and (rows[index].get('item_id') in targets or f'/{section}/{index}' in targets)
            actions = [action for action in actions if is_target(action)]
        if not actions:
            break
        changed = False
        writer_used = False
        for action in actions:
            key = (action.get('op'), action.get('target'), action.get('item_id'))
            target = _compression_item(data, action)
            if key in attempted_without_progress or (target and target[1].get('item_id') in rejected_compression_items):
                continue
            before = deepcopy(data)
            if action.get('writer_required'):
                if writer_used:
                    continue
                is_merge = action['op'] == 'merge_bullets'
                if target is None or _supported_compression_body(
                        target[1], target[0], meta, state.get('collected_info') or {},
                        _compression_indices(action, target[0])) is None:
                    retention_checks.append({'item_id': action.get('item_id') or (target[1].get('item_id') if target else None),
                                             'op': action['op'], 'target': action['target'], 'status': 'rejected',
                                             'reason': 'unverified_current_bullets'})
                    if target:
                        rejected_compression_items.add(target[1].get('item_id'))
                    continue
                writer_used = True
                request = ('将目标经历当前全部已核验的句子合并成恰好一条；保留每条的本人行动、产物、成果、'
                           'PR 编号、团队分工和状态限制，不能只保留第一条。不能新增信息。' if is_merge else
                           f"在保留事实、否定和原型限制的前提下缩短目标句，约{action['target_max_chars_estimate']}字以内。不能新增信息。")
                compression_instruction = f"本轮原始编辑要求：\n{turn_instruction(instruction)}\n\n本次容量压缩：{request}"
                revised = await run_resume_writer(state.get('collected_info') or {}, profile, llm,
                    current_data=data, resume_meta=meta,
                    instruction=compression_instruction,
                    scope='item' if is_merge else 'bullet',
                    targets=[action['item_id'] if is_merge else action['target']], **kwargs)
                if revised.get('writer_diagnostic'):
                    compression_diagnostics.append(revised['writer_diagnostic'])
                data, meta, reason = await _retain_compressed_body(before, meta, revised, action,
                    state.get('collected_info') or {}, structured_llm or llm)
                retention_checks.append({'item_id': target[1].get('item_id'),
                                         'op': action['op'], 'target': action['target'],
                                         'status': 'accepted' if reason == 'accepted' else 'rejected',
                                         'reason': reason})
                if reason != 'accepted':
                    rejected_compression_items.add(target[1].get('item_id'))
                if data != before:
                    written.setdefault('guard_fallbacks', []).extend(revised.get('guard_fallbacks') or [])
                else:
                    attempted_without_progress.add(key)
            else:
                data = apply_deterministic_compression(data, [action])
                meta = valid_bullet_metadata(data, meta)
                if action.get('op') == 'cap_bullets':
                    data, meta, limit_fallbacks = preserve_item_limits(
                        data, meta, state.get('collected_info') or {}, item_ids=[action['item_id']],
                        reason='compression_preserved_status_limit')
                    written.setdefault('guard_fallbacks', []).extend(limit_fallbacks)
            if data != before:
                changed = True
                compressed.append(action)
                measurement = await asyncio.to_thread(measure_rendered_pages, data, constraints)
            if measurement.get('within_page_limit') is not False:
                break
        if not changed and not writer_used:
            break
    version = prepare_version(state.get('resume_data') or {}, state.get('resume_meta') or {},
                               state.get('resume_versions') or [], data, meta,
                               label='定制简历' if scope == 'whole' else '局部修改')
    version['resume_meta'].update(match_plan=written.get('match_plan') or {},
                                  omitted=written.get('omitted') or [],
                                  page_check=measurement,
                                  writer_diagnostic=written.get('writer_diagnostic') or {},
                                  compression_writer_diagnostics=compression_diagnostics,
                                  compression_retention_checks=retention_checks,
                                  guard_fallbacks=written.get('guard_fallbacks') or [])
    changes = written.get('change_summary') or []
    if not version['changed']:
        changes = []
    version['resume_meta']['change_summary'] = changes[:5]
    return {**version, 'match_plan': written.get('match_plan') or {},
            'session_constraints': constraints, 'page_check': measurement,
            'writer_diagnostic': written.get('writer_diagnostic') or {},
            'compression_writer_diagnostics': compression_diagnostics,
            'compression_retention_checks': retention_checks,
            'guard_fallbacks': written.get('guard_fallbacks') or [],
            'change_summary': changes[:5], 'compression_actions': compressed,
            'omitted': written.get('omitted') or []}
