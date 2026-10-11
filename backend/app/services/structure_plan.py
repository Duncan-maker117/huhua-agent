"""Validated user-visible plans and deterministic confirmation/edit commands."""
from __future__ import annotations

from copy import deepcopy
import re

from app.schemas.writer import MatchPlan
from app.services.fact_guard import (TERM_FILE, contains_term, guard_bullets,
                                     lexical_fact_errors, ngram_overlap, validate_skill_groups)

SECTION_LABELS = {'education': '教育经历', 'work_experience': '工作/实习经历',
                  'projects': '项目经历', 'open_source': '开源贡献', 'awards': '竞赛荣誉',
                  'skills': '技能', 'certificates': '证书/活动'}
ALIASES = {'教育': 'education', '工作': 'work_experience', '实习': 'work_experience',
           '项目': 'projects', '开源': 'open_source', '荣誉': 'awards', '竞赛': 'awards',
           '技能': 'skills', '证书': 'certificates'}


def plan_action(text: str, card: dict | None = None) -> tuple[str, int]:
    cleaned = re.sub(r'\s+', '', text).rstrip('。！!')
    if re.search(r'重新定方案|重定方案|主线.{0,8}(?:换|改)|(?:换|改).{0,6}主线|定位.{0,8}(?:换|改)', cleaned):
        return 'replan', 0
    if re.search(r'直接写|先出一版|不用确认|不必确认', cleaned):
        return 'direct', 0
    if re.fullmatch(r'(?:请)?(?:按推荐写|就按这个|就按这个写|按这个写|用推荐(?:方案)?|确认推荐|按推荐方案写)', cleaned):
        return 'confirm', 0
    if card:
        for index, row in enumerate(card.get('alternatives') or [], 1):
            label = re.sub(r'\s+', '', row['label'])
            if cleaned in {f"用备选：{label}", f"用备选:{label}", f"用{label}",
                           f'用备选{index}', f'用备选方案{index}'}:
                return 'confirm', index
    match = re.fullmatch(r'用备选(?:方案)?([一二12])', cleaned)
    if match:
        return 'confirm', ('一二'.index(match[1]) + 1 if match[1] in '一二' else int(match[1]))
    match = re.fullmatch(r'(?:用|按)(?:第)?([一二三123])(?:个)?方案(?:写)?', cleaned)
    if match:
        return 'confirm', ('一二三'.index(match[1]) if match[1] in '一二三' else int(match[1]) - 1)
    if re.search(r'放.{0,10}(?:前|后)|移.{0,10}(?:前|后)|顺序|排.{0,8}(?:前|后)|不写|删掉|删除|去掉|压缩|简写', cleaned):
        return 'edit', 0
    return '', 0


def select_plan(card: dict, index: int = 0) -> dict | None:
    if index < 0 or index > len(card.get('alternatives') or []):
        return None
    result = deepcopy(card['recommended'])
    if index:
        alternative = card['alternatives'][index - 1]
        diffs = {row['item_id']: row for row in alternative['experience_plan']}
        result['experience_plan'] = [deepcopy(diffs.get(row['item_id'], row)) for row in result['experience_plan']]
        for key in ('label', 'positioning', 'thesis', 'section_order'):
            result[key] = deepcopy(alternative[key])
    return result


def positioning_guard_rows(card: dict, facts: dict) -> list[dict]:
    return [{'id': f'plan_positioning_{index}', 'text': sentence, 'fact_ids': list(facts),
             'semantic_only': True, 'claim_kind': 'positioning'}
            for index, row in enumerate([card['recommended'], *(card.get('alternatives') or [])[:2]])
            if (sentence := str(row.get('positioning') or '').strip()) and len(sentence) <= 40]


async def validate_structure_plan(card: dict, source: dict, profile: dict, items: dict, facts: dict,
                                  *, llm=None, positioning_checks: dict | None = None, diagnostic: dict | None = None) -> dict:
    from app.agents.resume_writer import _validate_plan
    if positioning_checks is None:
        checks = await guard_bullets(positioning_guard_rows(card, facts), list(facts.values()),
                                     user_skills=source.get('skills') or [], llm=llm)
        positioning_checks = {row['id']: row for row in checks}
    quotes = '\n'.join(str(fact.get('source_quote') or fact.get('text') or '') for fact in facts.values())
    terms = TERM_FILE.read_text().splitlines() if TERM_FILE.is_file() else []

    def validated(row, index):
        raw = {key: row[key] for key in MatchPlan.model_fields if key in row}
        plan = _validate_plan(MatchPlan.model_validate(raw), source, profile, items, facts)
        # Thesis is a card-only narrative, not resume prose. Check concrete
        # claims, numbers and units without requiring full lexical coverage.
        thesis = str(row.get('thesis') or '').strip()
        concrete_terms = [term.strip() for term in terms if term.strip() and not term.startswith('#')
                          and contains_term(thesis, term.strip())]
        thesis_errors = [error for error in lexical_fact_errors(thesis, quotes)
                         if error.startswith(('unsupported_numbers:', 'unsupported_quantity_unit:'))]
        thesis_errors.extend(validate_skill_groups({'terms': concrete_terms}, list(facts.values()), source.get('skills') or []))
        plan['thesis'] = thesis if not thesis_errors else ''
        sentence = str(row.get('positioning') or '').strip()
        check = positioning_checks.get(f'plan_positioning_{index}') or {}
        reason = ('empty' if not sentence else 'over_40_chars' if len(sentence) > 40 else
                  'lexical_fact_errors' if check.get('lexical_errors') else
                  'semantic_result_missing' if not check else
                  'semantic_rejected' if check.get('verdict') != 'pass' else '')
        plan['positioning'] = sentence if not reason else ''
        if diagnostic is not None and index == 0:
            diagnostic['positioning_rejected_reason'] = reason
            if reason and check.get('semantic'):
                # Fixed failure dimensions only; do not log model prose or PII.
                semantic = check['semantic']
                diagnostic['positioning_failed_dimensions'] = [key for key in (
                    'subject_ok', 'actions_supported', 'objects_supported', 'results_supported', 'limits_kept')
                    if semantic.get(key) is False]
                codes = {'semantic_verification_unavailable', 'semantic_verification_failed', 'semantic_result_missing_or_duplicate'}
                diagnostic['positioning_semantic_reason_codes'] = [span for span in semantic.get('unsupported_spans') or [] if span in codes]
        plan['label'] = str(row.get('label') or '主线叙事型')[:60]
        requirements = {req['id']: req.get('text', '') for req in profile.get('requirements') or [] if req.get('id')}
        for entry in plan['experience_plan']:
            item = items[entry['item_id']][1]
            name = item.get('name') or item.get('company') or entry['item_id']
            ids = {fact['id'] for fact in item['facts']}
            match = next((req for req in plan['requirements'] if ids.intersection(req['fact_ids'])), None)
            texts = [fact.get('source_quote') or fact.get('text') or '' for fact in item['facts']]
            if not entry['reason'].startswith('按你的要求') and (not entry['reason'].strip()
                    or not any(ngram_overlap(entry['reason'], text) >= 0.08 for text in texts)):
                detail = next((text for text, fact in zip(texts, item['facts']) if not fact.get('field')), texts[0])
                relationship = (f"可对应岗位的「{requirements.get(match['req_id'], '')}」" if match else '尚无事实直接对应当前 JD 要求')
                entry['reason'] = f"「{name}」记录了「{detail}」；{relationship}。"
        return plan

    recommended = validated(card['recommended'], 0)
    result = {'recommended': recommended, 'alternatives': []}
    for index, raw in enumerate((card.get('alternatives') or [])[:2], 1):
        merged = select_plan({'recommended': recommended, 'alternatives': [raw]}, 1)
        alternative = validated(merged, index)
        if alternative['label'] in {row['label'] for row in [recommended, *result['alternatives']]}:
            alternative['label'] += f"（备选{len(result['alternatives']) + 1}）"
        baseline = {row['item_id']: row for row in recommended['experience_plan']}
        result['alternatives'].append({**{key: alternative[key] for key in ('label', 'positioning', 'thesis', 'section_order')},
                                      'experience_plan': [row for row in alternative['experience_plan'] if row != baseline[row['item_id']]]})
    if not result['alternatives']:
        # The model can fail; still offer a transparent conservative alternative.
        diffs = [{**row, 'treatment': 'keep', 'target_bullets': 2} for row in recommended['experience_plan']
                 if row['treatment'] != 'keep']
        result['alternatives'] = [{'label': '经历均衡型', 'positioning': '', 'thesis': '',
                                   'section_order': list(recommended['section_order']), 'experience_plan': diffs}]
    return result


def edit_plan(plan: dict, text: str, collected: dict) -> tuple[dict, bool]:
    """Apply named/section order and inclusion choices; never edit fact master."""
    result = deepcopy(plan)
    labels = {item.get('item_id'): item.get('name') or item.get('company') or ''
              for section in (*SECTION_LABELS, 'internship') for item in collected.get(section) or [] if isinstance(item, dict)}
    changed = False
    explicit_order = bool(re.search(r'顺序|依次', text))
    if explicit_order:
        matches = [(match.start(), section) for alias, section in ALIASES.items() for match in re.finditer(alias, text)]
        specified = list(dict.fromkeys(section for _, section in sorted(matches)))
        if len(specified) > 1:
            result['section_order'] = [*specified, *[section for section in result['section_order'] if section not in specified]]
            changed = True
    for clause in re.split(r'[，,。；;\n]', text):
        named = [entry for entry in result.get('experience_plan') or []
                 if labels.get(entry['item_id']) and labels[entry['item_id']].casefold() in clause.casefold()]
        named.sort(key=lambda row: clause.casefold().index(labels[row['item_id']].casefold()))
        name_spans = [(clause.casefold().index(labels[row['item_id']].casefold()), len(labels[row['item_id']])) for row in named]
        sections = [(match.start(), section) for alias, section in ALIASES.items()
                    for match in re.finditer(alias, clause)
                    if not any(start <= match.start() < start + length for start, length in name_spans)]
        sections = list(dict.fromkeys(section for _, section in sorted(sections)))
        ordinal = re.search(r'第([一二三四五六七八九1-9])(?:个|段)?(项目|经历|开源贡献|工作|实习)', clause)
        if ordinal:
            number = int(ordinal[1]) if ordinal[1].isdigit() else '一二三四五六七八九'.index(ordinal[1]) + 1
            section = {'项目': 'projects', '开源贡献': 'open_source', '工作': 'work_experience', '实习': 'work_experience'}.get(ordinal[2])
            ids = {item.get('item_id') for key in (('work_experience', 'internship') if section == 'work_experience' else (section,))
                   for item in collected.get(key) or [] if isinstance(item, dict)} if section else set(labels)
            candidates = [row for row in result['experience_plan'] if row['item_id'] in ids and row['treatment'] != 'backup']
            named = [candidates[number - 1]] if number <= len(candidates) else []
            sections = []
        if re.search(r'不写|删除|删掉|去掉|不要写', clause):
            for entry in result.get('experience_plan') or []:
                if entry in named or (not named and re.search(r'所有|全部|栏目|整栏|项目经历|工作经历|实习经历|开源贡献', clause)
                        and any(entry['item_id'] == item.get('item_id')
                        for section in sections for item in collected.get(section) or [] if isinstance(item, dict))):
                    entry.update(treatment='backup', target_bullets=0, reason=f"按你的要求，本版不写「{labels.get(entry['item_id'])}」。")
                    changed = True
        elif re.search(r'压缩|简写', clause):
            for entry in named:
                entry.update(treatment='brief', target_bullets=1, reason=f"按你的要求，压缩「{labels.get(entry['item_id'])}」的篇幅。")
                changed = True
        if sections and not explicit_order and re.search(r'前|后|顺序', clause):
            order = result['section_order']
            moving = sections[0]
            order.remove(moving)
            if len(sections) > 1:
                anchor = sections[1]
                order.insert(order.index(anchor) + (1 if re.search(r'后', clause) else 0), moving)
            elif re.search(r'前', clause):
                order.insert(0, moving)
            else:
                order.append(moving)
            changed = True
        elif named and re.search(r'前|后', clause):
            order = result['experience_plan']
            moving = named[0]
            order.remove(moving)
            if len(named) > 1:
                order.insert(order.index(named[1]) + (1 if re.search(r'后', clause) else 0), moving)
            elif re.search(r'前', clause):
                order.insert(0, moving)
            else:
                order.append(moving)
            changed = True
    return result, changed


def apply_plan_structure(data: dict, plan: dict) -> dict:
    result = deepcopy(data)
    rank = {row['item_id']: index for index, row in enumerate(plan.get('experience_plan') or [])}
    treatments = {row['item_id']: row['treatment'] for row in plan.get('experience_plan') or []}
    for section in SECTION_LABELS:
        rows = result.get(section)
        if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
            rows.sort(key=lambda row: rank.get(row.get('item_id'), len(rank)))
            for row in rows:
                if row.get('item_id') in treatments:
                    row['hidden'] = treatments[row['item_id']] == 'backup'
    from app.agents.resume_writer import _apply_section_order
    _apply_section_order(result, plan['section_order'])
    result['self_evaluation'] = plan.get('positioning') or ''
    if result['self_evaluation'] and not any(row.get('kind') == 'self_evaluation' for row in result['sections']):
        result['sections'].append({'id': 'self_evaluation', 'kind': 'self_evaluation', 'title': '个人定位', 'content': ''})
    return result


def plan_guidance(card: dict, collected: dict) -> dict:
    names = {item.get('item_id'): item.get('name') or item.get('company') or item.get('item_id')
             for section in (*SECTION_LABELS, 'internship') for item in collected.get(section) or [] if isinstance(item, dict)}
    display = deepcopy(card)
    for row in [display['recommended'], *display.get('alternatives', [])]:
        for entry in row['experience_plan']:
            entry['name'] = names.get(entry['item_id'], entry['item_id'])
    return {'kind': 'structure_plan', 'title': '定方案', 'question': '选好方案后开始写首稿',
            'structure_plan': display, 'allow_free_text': True,
            'options': [{'label': '按推荐写', 'value': '按推荐写'},
                        *[{'label': f"用备选：{row['label']}", 'value': f"用备选：{row['label']}"} for row in display['alternatives']]]}


def plan_summary(plan: dict, collected: dict) -> str:
    names = {item.get('item_id'): item.get('name') or item.get('company') or item.get('item_id')
             for section in (*SECTION_LABELS, 'internship') for item in collected.get(section) or [] if isinstance(item, dict)}
    parts = [plan.get('thesis') or plan.get('label') or '按已确认方案组织经历']
    parts.extend(f"重点写「{names.get(row['item_id'], row['item_id'])}」：{row['reason']}"
                 for row in plan.get('experience_plan') or [] if row['treatment'] == 'lead')
    return ' '.join(parts)
