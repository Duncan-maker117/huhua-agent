"""Validated user-visible plans and deterministic confirmation/edit commands."""
from __future__ import annotations

from copy import deepcopy
import re

from app.schemas.writer import MatchPlan
from app.services.fact_guard import (TERM_FILE, contains_term, guard_bullets,
                                     lexical_fact_errors, ngram_overlap, normalize_text, validate_skill_groups)

SECTION_LABELS = {'education': '教育经历', 'work_experience': '工作/实习经历',
                  'projects': '项目经历', 'open_source': '开源贡献', 'awards': '竞赛荣誉',
                  'skills': '技能', 'certificates': '证书/活动'}
ALIASES = {'教育': 'education', '工作': 'work_experience', '实习': 'work_experience',
           '项目': 'projects', '开源': 'open_source', '荣誉': 'awards', '竞赛': 'awards',
           '技能': 'skills', '证书': 'certificates'}


_IDENTITY = re.compile(r'实习生|工程师|产品经理|经理|设计师|分析师|研究员|开发者|负责人|专家|创始人|主理人')


def profile_edit(text: str) -> str | None:
    match = re.fullmatch(r'\s*(?:请)?(?:把|将)?个人定位(?:改成|改为|换成)[：:\s]*(.+)', text, re.S)
    return match[1].strip() if match else None


def style_edit(text: str) -> str | None:
    match = re.fullmatch(r'\s*(?:写法[：:]?|(?:请)?(?:把)?写法(?:改成|改为|切换为))\s*(问题[-—－]决策[-—－]结果|普通|labeled|plain)[。\s]*', text)
    return ('plain' if match[1] in {'普通', 'plain'} else 'labeled') if match else None


def stance_errors(sentence: str, facts: dict) -> list[str]:
    """Conservative noun-surface gate; semantic review still checks the synthesis.

    The object of 关注/重视/致力于 ends at a colon or sentence boundary. Each
    noun chunk must occur in original active evidence, with >=2 distinct facts
    contributing. Duplicate fact copies do not count as independent support.
    """
    quotes = {normalize_text(f.get('source_quote') or f.get('text') or '')
              for f in facts.values() if f.get('status', 'active') == 'active'}
    for match in re.finditer(r'(?:关注|重视|致力于)([^。！？!?：:；;]+)', sentence):
        chunks = re.split(r'的|与|和|及|、|，|,|\s+', match[1])
        nouns = [normalize_text(word) for word in chunks if word.strip()]
        supporting = {quote for quote in quotes if any(word in quote for word in nouns)}
        if not nouns or any(not any(word in quote for quote in quotes) for word in nouns):
            return ['unsupported_stance_terms']
        if len(supporting) < 2:
            return ['stance_needs_two_facts']
    return []

def user_plan_text(text: str, profile: dict | None = None) -> str:
    """Translate internal requirement/signal references only in prose slots."""
    profile = profile or {}
    labels = {row.get('id'): str(row.get('text') or '')[:40]
              for row in profile.get('requirements') or []}
    labels.update({row.get('id'): str(row.get('signal') or '')[:40]
                   for row in profile.get('core_signals') or []})
    value = re.sub(r'(?<![A-Za-z0-9_])[rs]\d+(?![A-Za-z0-9_])',
                   lambda match: labels.get(match[0], ''), str(text or ''))
    value = re.sub(r'([、/，,；;])(?:\s*[、/，,；;])+', r'\1', value)
    return value.strip(' 、/，,；;')


def readable_plan(plan: dict, profile: dict | None = None) -> dict:
    result = deepcopy(plan)
    for field in ('label', 'thesis', 'positioning', 'summary_angle'):
        if field in result:
            result[field] = user_plan_text(result[field], profile)
    for entry in result.get('experience_plan') or []:
        entry['reason'] = user_plan_text(entry.get('reason'), profile)
    for entry in result.get('requirements') or []:
        if 'angle' in entry:
            entry['angle'] = user_plan_text(entry['angle'], profile)
    for row in result.get('questions') or []:
        for field in ('q', 'why'):
            if field in row:
                row[field] = user_plan_text(row[field], profile)
        if 'options' in row:
            row['options'] = [user_plan_text(option, profile) for option in row['options']]
    return result


def plan_action(text: str, card: dict | None = None) -> tuple[str, int]:
    if profile_edit(text) is not None or style_edit(text):
        return 'edit', 0
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
        for key in ('profile_statement', 'profile_statement_source', 'profile_statement_fact_ids', 'bullet_style'):
            result.pop(key, None)
            if key in alternative:
                result[key] = deepcopy(alternative[key])
        result.pop('positioning_source', None)
        if alternative.get('positioning_source') == 'derived':
            result['positioning_source'] = 'derived'
    return result


def accept_profile(plan: dict) -> dict:
    result = deepcopy(plan)
    if result.get('profile_statement') and result.get('profile_statement_source') != 'user':
        result['profile_statement_source'] = 'confirmed'
    return result


def _accepted_profile(plan: dict, facts: dict) -> bool:
    return (plan.get('profile_statement_source') == 'user' or
            (plan.get('profile_statement_source') == 'confirmed'
             and bool(plan.get('profile_statement_fact_ids'))
             and set(plan['profile_statement_fact_ids']) <= facts.keys()))


def positioning_guard_rows(card: dict, facts: dict) -> list[dict]:
    return [{'id': f'plan_positioning_{index}', 'text': sentence, 'fact_ids': list(facts),
             'semantic_only': not bool(row.get('profile_statement')), 'claim_kind': 'positioning'}
            for index, row in enumerate([card['recommended'], *(card.get('alternatives') or [])[:2]])
            if not _accepted_profile(row, facts)
            and (sentence := str(row.get('profile_statement') or row.get('positioning') or '').strip())
            and len(sentence) <= (90 if row.get('profile_statement') else 40)]


async def validate_structure_plan(card: dict, source: dict, profile: dict, items: dict, facts: dict,
                                  *, llm=None, positioning_checks: dict | None = None, diagnostic: dict | None = None) -> dict:
    from app.agents.resume_writer import _validate_plan
    facts = {fid: fact for fid, fact in facts.items() if fact.get('status', 'active') == 'active'}
    # Verify the same wording that will be shown/written, including ID expansion.
    card = {'recommended': readable_plan(card['recommended'], profile),
            'alternatives': [readable_plan(row, profile) for row in card.get('alternatives') or []]}
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
        is_profile = bool(row.get('profile_statement'))
        sentence = str(row.get('profile_statement') or row.get('positioning') or '').strip()
        check = positioning_checks.get(f'plan_positioning_{index}') or {}
        semantic = check.get('semantic') or {}
        # The header line is resume prose: a job title or identity is only
        # usable when the candidate said it (a target role is not an identity).
        identities = [word for word in _IDENTITY.findall(sentence) if word not in quotes]
        sentence_terms = [term.strip() for term in terms if term.strip() and not term.startswith('#')
                          and contains_term(sentence, term.strip())]
        unsupported_tools = validate_skill_groups({'terms': sentence_terms}, list(facts.values()), source.get('skills') or [])
        limit = 90 if is_profile else 40
        profile_errors = (lexical_fact_errors(sentence, quotes) + stance_errors(sentence, facts)) if is_profile else []
        if is_profile and (len([s for s in re.split(r'[。！？!?]+', sentence) if s.strip()]) not in {2, 3}
                           or re.search(r'这个人|候选人|让面试官记住', sentence)):
            profile_errors.append('not_resume_profile')
        reason = ('empty' if not sentence else f'over_{limit}_chars' if len(sentence) > limit else
                  'profile_fact_errors' if profile_errors else
                  'lexical_fact_errors' if check.get('lexical_errors') or unsupported_tools else
                  'unsupported_identity' if identities else
                  'semantic_result_missing' if not check else
                  'semantic_rejected' if check.get('verdict') != 'pass' else '')
        if _accepted_profile(row, facts):
            reason = ''  # Confirmed/user prose is not sent back for another approval.
            plan['profile_statement_source'] = row['profile_statement_source']
        if is_profile and not reason:
            plan['profile_statement_fact_ids'] = row.get('profile_statement_fact_ids') or list(facts)
        plan['profile_statement'] = sentence if is_profile and not reason else ''
        plan['positioning'] = sentence if not is_profile and not reason else ''
        # A sentence stitched from fact fragments reads worse than no line at
        # all; an empty positioning simply leaves the header line out.
        fallback, fallback_reason = '', ('model_empty' if reason == 'empty' else '')
        if fallback:
            plan['positioning_source'] = 'derived'
        if diagnostic is not None and index == 0:
            diagnostic['positioning_rejected_reason'] = reason
            diagnostic['positioning_source'] = 'derived' if fallback else 'empty' if reason else 'model'
            diagnostic['positioning_fallback_reason'] = fallback_reason
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
        return readable_plan(plan, profile)

    recommended = validated(card['recommended'], 0)
    result = {'recommended': recommended, 'alternatives': []}
    for index, raw in enumerate((card.get('alternatives') or [])[:2], 1):
        merged = select_plan({'recommended': recommended, 'alternatives': [raw]}, 1)
        alternative = validated(merged, index)
        if alternative['label'] in {row['label'] for row in [recommended, *result['alternatives']]}:
            alternative['label'] += f"（备选{len(result['alternatives']) + 1}）"
        baseline = {row['item_id']: row for row in recommended['experience_plan']}
        result['alternatives'].append({**{key: alternative[key] for key in ('label', 'positioning', 'profile_statement', 'bullet_style', 'thesis', 'section_order')},
                                      **{key: alternative[key] for key in ('profile_statement_source', 'profile_statement_fact_ids') if key in alternative},
                                      **({'positioning_source': 'derived'} if alternative.get('positioning_source') == 'derived' else {}),
                                      'experience_plan': [row for row in alternative['experience_plan'] if row != baseline[row['item_id']]]})
    if not result['alternatives']:
        # The model can fail; still offer a transparent conservative alternative.
        diffs = [{**row, 'treatment': 'keep', 'target_bullets': 2} for row in recommended['experience_plan']
                 if row['treatment'] != 'keep']
        result['alternatives'] = [{'label': '经历均衡型', 'positioning': recommended['positioning'], 'thesis': '',
                                   'profile_statement': recommended['profile_statement'], 'bullet_style': recommended['bullet_style'],
                                   **{key: recommended[key] for key in ('profile_statement_source', 'profile_statement_fact_ids') if key in recommended},
                                   **({'positioning_source': 'derived'} if recommended.get('positioning_source') == 'derived' else {}),
                                   'section_order': list(recommended['section_order']), 'experience_plan': diffs}]
    return result


def edit_plan(plan: dict, text: str, collected: dict) -> tuple[dict, bool]:
    """Apply named/section order and inclusion choices; never edit fact master."""
    result = deepcopy(plan)
    if (statement := profile_edit(text)) is not None:
        result.update(profile_statement=statement, positioning='', profile_statement_source='user')
        return result, True
    if style := style_edit(text):
        result['bullet_style'] = style
        return result, True
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
    result['summary'] = plan.get('profile_statement') or plan.get('positioning') or ''
    return result


def plan_guidance(card: dict, collected: dict, profile: dict | None = None) -> dict:
    names = {item.get('item_id'): item.get('name') or item.get('company') or item.get('item_id')
             for section in (*SECTION_LABELS, 'internship') for item in collected.get(section) or [] if isinstance(item, dict)}
    display = deepcopy(card)
    display['recommended'] = readable_plan(display['recommended'], profile)
    display['alternatives'] = [readable_plan(row, profile) for row in display.get('alternatives', [])]
    for row in [display['recommended'], *display.get('alternatives', [])]:
        for entry in row['experience_plan']:
            entry['name'] = names.get(entry['item_id'], entry['item_id'])
    return {'kind': 'structure_plan', 'title': '定方案', 'question': '选好方案后开始写首稿',
            'structure_plan': display, 'allow_free_text': True,
            'options': [{'label': '按推荐写', 'value': '按推荐写'},
                        *[{'label': f"用备选：{row['label']}", 'value': f"用备选：{row['label']}"} for row in display['alternatives']]]}


def plan_summary(plan: dict, collected: dict, profile: dict | None = None) -> str:
    names = {item.get('item_id'): item.get('name') or item.get('company') or item.get('item_id')
             for section in (*SECTION_LABELS, 'internship') for item in collected.get(section) or [] if isinstance(item, dict)}
    plan = readable_plan(plan, profile)
    leads = [row for row in plan.get('experience_plan') or [] if row['treatment'] == 'lead'][:3]
    labels = [phrase_prefix(str(names.get(row['item_id']) or '这段经历'), 24) or '这段经历' for row in leads]
    budget = 150 - len('**这版的思路**：')
    thesis = plan.get('thesis') or plan.get('label') or '按已确认方案组织经历'
    # A full sentence first, then a separate lead line. Reserve short reasons
    # before choosing a punctuation boundary; never slice the final output.
    thesis_limit = min(80, budget - sum(len(name) + 12 for name in labels) - 5)
    thesis = phrase_prefix(thesis, thesis_limit - 1, first_sentence=True) or '按已确认方案组织经历'
    thesis = thesis.rstrip('。！？!?') + '。'
    parts = []
    for row, name in zip(leads, labels):
        remaining_names = sum(len(label) + 12 for label in labels[len(parts) + 1:])
        remaining = budget - len(thesis) - 4 - sum(len(part) + 1 for part in parts) - len(name) - 3 - remaining_names
        reason = row.get('reason', '')
        reason = re.sub(r'^[「“]?' + re.escape(name) + r'[」”]?\s*', '', reason).strip(' ：:，,；;。')
        reason = re.sub(r'^的', '', reason)
        limit = max(0, min(20, remaining))
        reason = phrase_prefix(reason, limit, first_phrase=True)
        parts.append(f'{name}（{reason}）' if reason else name)
    return thesis + ('\n重点：' + '、'.join(parts) if parts else '')


def phrase_prefix(text: str, limit: int, *, first_sentence: bool = False, first_phrase: bool = False) -> str:
    """Keep a whole phrase, ending only at punctuation outside paired marks."""
    text = str(text or '').strip().rstrip('。；;，,')
    pairs = {'(': ')', '（': '）', '[': ']', '【': '】', '「': '」', '『': '』', '“': '”', '‘': '’'}
    stack, boundaries = [], []
    sentence_end = None
    for index, char in enumerate(text):
        if char in {'"', "'"} and not (char == "'" and 0 < index < len(text) - 1
                                          and text[index - 1].isalnum() and text[index + 1].isalnum()):
            if stack and stack[-1] == char:
                stack.pop()
            else:
                stack.append(char)
        elif char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack[-1] != char:
                break
            stack.pop()
        period = char == '.' and (index + 1 == len(text) or text[index + 1].isspace())
        if not stack and (char in '。；;，,！？!?' or period):
            boundaries.append(index)
            if first_phrase:
                return text[:index].strip() if 0 < index <= limit else ''
            if first_sentence and sentence_end is None and (char in '。！？!?' or period):
                sentence_end = index
        if index == len(text) - 1 and not stack:
            boundaries.append(len(text))
    end = max((end for end in boundaries if 0 < end <= limit
               and (sentence_end is None or end <= sentence_end)), default=0)
    return text[:end].strip().rstrip('。；;，,！？!?.')
