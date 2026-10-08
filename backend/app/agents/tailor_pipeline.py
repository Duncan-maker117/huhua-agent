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
from app.services.resume_versions import prepare_version, valid_bullet_metadata
from app.services.resume_limits import preserve_item_limits
from app.services.resume_facts import active_facts_for_writer


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
    for round_number in range(1, MAX_COMPRESSION_ROUNDS + 1):
        if measurement.get('within_page_limit') is not False:
            break
        actions = plan_compression(data, written.get('match_plan'), round_number=round_number, constraints=constraints)
        if scope != 'whole':
            def is_target(action):
                if action.get('op') != 'shorten_bullet':
                    return False
                path = action.get('target', '')
                if scope == 'bullet':
                    return path in targets
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
        for action in actions:
            before = deepcopy(data)
            if action.get('writer_required'):
                revised = await run_resume_writer(state.get('collected_info') or {}, profile, llm,
                    current_data=data, resume_meta=meta,
                    instruction=f"在保留事实、否定和原型限制的前提下缩短目标句，约{action['target_max_chars_estimate']}字以内。不能新增信息。",
                    scope='bullet', targets=[action['target']], **kwargs)
                data, meta = revised['resume_data'], revised['resume_meta']
                if revised.get('writer_diagnostic'):
                    compression_diagnostics.append(revised['writer_diagnostic'])
                written.setdefault('guard_fallbacks', []).extend(revised.get('guard_fallbacks') or [])
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
        if not changed:
            break
    version = prepare_version(state.get('resume_data') or {}, state.get('resume_meta') or {},
                               state.get('resume_versions') or [], data, meta,
                               label='定制简历' if scope == 'whole' else '局部修改')
    version['resume_meta'].update(match_plan=written.get('match_plan') or {},
                                  omitted=written.get('omitted') or [],
                                  page_check=measurement,
                                  writer_diagnostic=written.get('writer_diagnostic') or {},
                                  compression_writer_diagnostics=compression_diagnostics,
                                  guard_fallbacks=written.get('guard_fallbacks') or [])
    changes = written.get('change_summary') or []
    if not version['changed']:
        changes = []
    version['resume_meta']['change_summary'] = changes[:5]
    return {**version, 'match_plan': written.get('match_plan') or {},
            'session_constraints': constraints, 'page_check': measurement,
            'writer_diagnostic': written.get('writer_diagnostic') or {},
            'compression_writer_diagnostics': compression_diagnostics,
            'guard_fallbacks': written.get('guard_fallbacks') or [],
            'change_summary': changes[:5], 'compression_actions': compressed,
            'omitted': written.get('omitted') or []}
