"""Deterministic technology names and item-scoped, original-quote evidence.

Writers only project active facts. Explicit chat additions enter through
record_facts; direct editor input uses the existing append_editor_facts boundary.
"""
from __future__ import annotations

import re

ALIASES = {
    'mcp': 'MCP', 'toolcalling': 'Tool Calling', 'tool calling': 'Tool Calling',
    'longchain': 'LangChain', 'langchain': 'LangChain', 'langgraph': 'LangGraph',
    'rag': 'RAG', 'llm': 'LLM', 'python': 'Python', 'java': 'Java',
    'fastapi': 'FastAPI', 'react': 'React', 'vue': 'Vue', 'typescript': 'TypeScript',
    'javascript': 'JavaScript', 'mysql': 'MySQL', 'postgresql': 'PostgreSQL',
    'redis': 'Redis', 'docker': 'Docker', '长期记忆': '长期记忆', '记忆': '记忆',
}
# Chinese capability words are ordinary prose too ("帮用户记忆单词"); only an
# explicit list may turn them into stack items.
LIST_ONLY = {'长期记忆', '记忆'}
MAX_ITEMS = 8
SECTIONS = ('projects', 'work_experience')
SPLIT = re.compile(r'[,，、;；\n]+')
LABEL = re.compile(r'^\s*(?:[-*•]\s*)?(?:技术栈|技术|工具|框架|tech\s*stack)\s*[:：]\s*', re.I)
NEGATIVE = re.compile(r'没(?:有)?(?:用|使用|接入)?|未(?:使用|用|接入)?|不(?:使用|用|是)|不含|不涉及|去掉|删除|移除|计划|打算|拟用|准备|考虑|希望|待接入|如果|假设|例如|比如|推荐|可选|候选|要求|需要掌握|想学')


def normalize_name(value: str) -> str:
    value = re.sub(r'\s+', ' ', value).strip(' \t。；;，,、`')
    return ALIASES.get(value.casefold(), value)


def normalize_stack(values: list[str]) -> list[str]:
    result, seen = [], set()
    for value in values:
        name = normalize_name(value)
        if name and name.casefold() not in seen:
            result.append(name)
            seen.add(name.casefold())
    return result[:MAX_ITEMS]


def split_spaced(part: str) -> list[str]:
    """Split "mcp 记忆 toolcalling" when it names known items; keep "Spring Boot"."""
    tokens, result, i = part.split(), [], 0
    while i < len(tokens):
        pair = ' '.join(tokens[i:i + 2]).casefold()
        if i + 1 < len(tokens) and pair in ALIASES:
            result.append(' '.join(tokens[i:i + 2]))
            i += 2
        else:
            result.append(tokens[i])
            i += 1
    if len(result) > 1 and any(token.casefold() in ALIASES for token in result):
        return result
    return [part]


def split_stack(value: str) -> list[str]:
    return normalize_stack([token for part in SPLIT.split(value) for token in split_spaced(part.strip())])


def _pattern(name: str):
    variants = [key for key, value in ALIASES.items() if value == normalize_name(name)]
    variants.append(name)
    return re.compile(r'(?<![A-Za-z0-9_+#.])(?:' + '|'.join(
        re.escape(v) for v in sorted(set(variants), key=len, reverse=True)) + r')(?![A-Za-z0-9_+#])', re.I)


def normalize_prose(text: str) -> str:
    """Replace only bounded aliases from the same table used by stack fields."""
    pattern = re.compile(r'(?<![A-Za-z0-9_+#.])(?:' + '|'.join(
        re.escape(key) for key in sorted(ALIASES, key=len, reverse=True)) + r')(?![A-Za-z0-9_+#])', re.I)
    return pattern.sub(lambda match: ALIASES[match[0].casefold()], text)


def clean_stack_prose(text: str, stack: list[str]) -> str:
    """Remove only complete name-list clauses covered by the visible stack."""
    text = normalize_prose(text)
    if not stack:
        return text
    if (names := pure_stack(text, bare=True)) and set(names) <= set(stack):
        return ''
    name = '(?:' + '|'.join(re.escape(n) for n in sorted(stack, key=len, reverse=True)) + ')'
    listing = re.compile(
        r'(^|[，,；;。\n])\s*(?:并且|并|且|同时|以及|还)?\s*'
        r'(?:(?:(?:这个|该|本)?项目)?(?:使用|采用|用了|用到)(?:了)?\s*|(?:技术栈|技术|工具|框架)\s*[:：]\s*|(?=' + name + '))'
        + name + r'(?:\s*(?:[、,，/]|以及|和|与|及|\s)\s*' + name + r')*'
        r'\s*(?:方案|技术|框架|工具|搭建\s*(?:agent|智能体)\s*能力)?\s*'
        r'(?=$|[，,、；;。\n]|(?:并且|并|且|同时|以及|还)(?:可|能够|能)?(?:通过|用|实现|负责|完成|接入))', re.I)
    # The delimiter belongs to the remaining prose; no concrete use is matched.
    def remove(match):
        tail = text[match.end():]
        # A comma may continue an incompletely covered list ("MCP, Rust").
        # Only an independently identifiable action may follow a removed list.
        if re.match(r'^[，,、]', tail) and not re.match(
                r'^[，,、\s]+(?:并且|并|且|同时|以及|还)?\s*(?:可|能够|能)?(?:通过|用|实现|负责|完成|接入|开发|支持|构建|整理|项目)', tail):
            return match[0]
        return match[1]
    cleaned = listing.sub(remove, text)
    if cleaned == text:
        return text
    cleaned = re.sub(r'([，,、；;。\n])[，,、；;。\n\s]+', r'\1', cleaned).strip(' ，,、；;。\n')
    # Only strip dangling conjunctions after a list was actually removed.
    # Do not damage words such as 并发, 同时性, 还有待 or 还原.
    cleaned = re.sub(r'^(?:(?:并且|并|且|同时|以及|还)[\s，,、；;]*)+'
                     r'(?=(?:可|能够|能)?(?:通过|用|实现|负责|完成|接入|开发|支持|构建|整理))', '', cleaned)
    cleaned = re.sub(r'^可通过', '通过', cleaned)
    return cleaned + ('。' if cleaned and text.endswith('。') else '')


def clean_item_prose(item: dict, facts: list[dict], meta: dict, *, indices=None) -> None:
    from copy import deepcopy
    from app.services.fact_coverage import text_covered
    from app.services.resume_versions import text_hash
    iid = item.get('item_id')
    field = 'polished_bullets' if 'polished_bullets' in item else 'bullets'
    records = meta.get('bullets', {}).get(iid, [])
    by_id = {f['id']: f for f in facts if f.get('id') and f.get('status', 'active') == 'active'}
    kept, citations = [], []
    for index, line in enumerate(item.get(field) or []):
        cleaned = clean_stack_prose(line, item.get('tech_stack') or []) if indices is None or index in indices else line
        if not cleaned:
            continue
        record = deepcopy(records[index]) if index < len(records) else {}
        if cleaned != line and record:
            if record.get('text_hash') != text_hash(line):
                record = {}
            else:
                # A pure list no longer supports the remaining action. Compound
                # source facts remain citations, but lose unproved full coverage.
                record['fact_ids'] = [fid for fid in record.get('fact_ids', []) if fid in by_id
                                     and clean_stack_prose(by_id[fid]['text'], item.get('tech_stack') or [])]
                record['coverage_fact_ids'] = [fid for fid in record.get('coverage_fact_ids', []) if fid in by_id
                    and (cleaned == normalize_prose(line) or text_covered(normalize_prose(by_id[fid]['text']), [cleaned]))]
                record['text_hash'] = text_hash(cleaned)
        kept.append(cleaned)
        citations.append(record)
    if kept != (item.get(field) or []):
        item[field] = kept
        meta.setdefault('bullets', {})[iid] = citations
    if indices is None and item.get('description'):
        item['description'] = '\n'.join(cleaned for line in item['description'].splitlines()
                                       if (cleaned := clean_stack_prose(line, item.get('tech_stack') or [])))


def mention_position(name: str, quote: str) -> int | None:
    """Literal/alias matches only; reject negative, hypothetical and planned use."""
    for match in _pattern(name).finditer(quote):
        # A negation before a comma-separated list applies to the whole list.
        start = max(quote.rfind(mark, 0, match.start()) for mark in ('。', '；', ';', '\n')) + 1
        prefix = quote[start:match.start()]
        # Separate edit clauses have separate polarity: removing one name does
        # not negate an explicit addition after the comma.
        additions = list(re.finditer(r'[，,]\s*(?:并|再|同时)?\s*(?:加上|添加|补上)\s*', prefix))
        if additions:
            prefix = prefix[additions[-1].end():]
        if NEGATIVE.search(prefix) or re.match(r'\s*(?:去掉|删掉|删除|移除|不用)', quote[match.end():]):
            continue
        return match.start()
    return None


def quote_of(fact: dict) -> str:
    return str(fact.get('source_quote') or fact.get('text') or '')


def supporting_ids(name: str, facts: list[dict]) -> list[str]:
    return [fact['id'] for fact in facts if fact.get('id') and fact.get('status', 'active') == 'active'
            and mention_position(name, quote_of(fact)) is not None
            and (not fact.get('replaces') or mention_position(name, fact.get('text', '')) is not None)]


def pure_stack(text: str, *, bare: bool = False) -> list[str]:
    """Only a list of names moves out of bullets; action sentences stay intact."""
    match = LABEL.match(text)
    if not match and not bare:
        return []
    body = text[match.end():] if match else text
    body = re.sub(r'^(?:(?:这个|该)?项目)?(?:使用|用了|采用|用到)(?:了)?\s*', '', body)
    parts = [token for part in SPLIT.split(body.strip().rstrip('。')) for token in split_spaced(part.strip())]
    if not parts or any(not p.strip() or len(p.strip()) > 48 or re.search(
            r'使用|采用|基于|接入|实现|开发|构建|完成|负责|支持|用于|通过|进行|借助|调用|编程|涉及|提交|重叠|估算|为|已|尚|不|以及|等|[:：。！？!?]', p) for p in parts):
        return []
    if any(not re.fullmatch(r'[A-Za-z0-9\u4e00-\u9fff+#./ _()（）-]+', p.strip()) for p in parts):
        return []
    # Without an explicit heading, a lone unknown word/sentence is not a list.
    if not match and len(parts) == 1 and parts[0].strip().casefold() not in ALIASES:
        return []
    # Without an explicit heading, require recognisable names, not prose.
    if not match and any(p.strip().casefold() not in ALIASES and not re.fullmatch(
            r'[A-Za-z][A-Za-z0-9+#. /_-]{0,47}', p.strip()) for p in parts):
        return []
    return normalize_stack(parts)


def extract_stack(fact: dict) -> list[str]:
    if fact.get('field') and fact['field'] != 'tech_stack':
        return []
    quote = quote_of(fact)
    candidates = [name for name in dict.fromkeys(ALIASES.values()) if name not in LIST_ONLY]
    candidates += pure_stack(quote, bare=fact.get('dimension') == 'tech_stack' or fact.get('field') == 'tech_stack')
    # Explicit use/list syntax also supports technologies outside the alias map.
    match = re.search(r'(?:技术栈\s*[:：为是]?|(?:使用|用了|用到|采用)(?:了|的技术(?:是)?)?)\s*(.+)', quote)
    if match:
        body = re.split(r'[。；;\n]', match[1])[0]
        candidates += pure_stack('技术栈：' + body)
    hits = [(position, name) for name in normalize_stack_unbounded(candidates)
            if (position := mention_position(name, quote)) is not None]
    return [name for position, name in sorted(hits, key=lambda row: row[0])
            if not any(other != name and name in other and start <= position < start + len(other)
                       for start, other in hits)]


def normalize_stack_unbounded(values):
    result, seen = [], set()
    for value in values:
        name = normalize_name(value)
        if name and name.casefold() not in seen:
            result.append(name)
            seen.add(name.casefold())
    return result


def project_item_stack(item: dict, facts: list[dict], meta: dict, *, proposed=(), proposed_ids=(),
                       autofill: bool = True) -> None:
    """Validate proposals, migrate list bullets, and preserve per-name citations."""
    from app.services.resume_versions import text_hash
    iid = item.get('item_id')
    active = [f for f in facts if f.get('status', 'active') == 'active']
    excluded = set(meta.get('tech_stack_excluded', {}).get(iid, []))
    names = list(item.get('tech_stack') or [])
    cited = [f for f in active if f.get('id') in proposed_ids]
    names += [name for name in proposed if supporting_ids(name, cited)]
    field = 'polished_bullets' if 'polished_bullets' in item or ('description' in item and 'bullets' not in item) else 'bullets'
    for line in [*(item.get(field) or []), *(item.get('description') or '').splitlines()]:
        names += [name for name in pure_stack(line, bare=True) if supporting_ids(name, active)]
    if autofill:
        names += [name for fact in active for name in extract_stack(fact)]
    supported = {}
    for name in normalize_stack_unbounded(names):
        refs = supporting_ids(name, active)
        if refs and name.casefold() not in excluded:
            supported[name] = refs
    def order(name):
        return next((i, mention_position(name, quote_of(f))) for i, f in enumerate(active)
                    if f['id'] in supported[name])
    stack = sorted(supported, key=order)[:MAX_ITEMS]
    if stack:
        item['tech_stack'] = stack
    else:
        item.pop('tech_stack', None)
    meta.setdefault('tech_stack', {})[iid] = [
        {'text_hash': text_hash(name), 'fact_ids': supported[name]} for name in stack]

    clean_item_prose(item, active, meta)


def stack_covers_fact(item: dict, records: list[dict], fact: dict, *, bullet_records=()) -> bool:
    """Lists live in the stack; compound facts still need a cited action body."""
    from app.services.resume_versions import text_hash
    names = pure_stack(fact.get('text', ''), bare=True)
    if not names:
        match = re.fullmatch(r'(?:.*?项目)?(?:使用|用了|采用)(?:了)?\s*(.+)', fact.get('text', '').rstrip('。'))
        names = pure_stack('技术栈：' + match[1]) if match else []
    valid = {name for name, record in zip(item.get('tech_stack') or [], records)
             if record.get('text_hash') == text_hash(name) and fact['id'] in record.get('fact_ids', [])}
    if names and set(names) <= valid:
        return True
    text = normalize_prose(fact.get('text', ''))
    remaining = clean_stack_prose(text, sorted(valid))
    if not remaining or remaining == text:
        return False
    from app.services.fact_coverage import text_covered
    body = item.get('polished_bullets') or item.get('bullets') or []
    cited_body = [line for line, record in zip(body, bullet_records)
                  if record.get('text_hash') == text_hash(line) and fact['id'] in record.get('fact_ids', [])]
    return text_covered(remaining, cited_body)


def _edit_target(rows, instruction: str):
    """Resolve the subject, separately from technology names in the operations."""
    subject = re.split(r'技术栈|加上|添加|补上|去掉|删掉|删除|移除|用了|使用了|用到', instruction, maxsplit=1)[0]
    def compact(value):
        return re.sub(r'\s+|的', '', value).casefold()
    named = [row for row in rows if (name := row[2].get('name') or row[2].get('company'))
             and compact(name) in compact(subject)]
    if named:
        return named
    if re.search(r'实习|工作经历|公司', subject):
        rows = [row for row in rows if row[0] == 'work_experience']
    elif '项目' in subject:
        rows = [row for row in rows if row[0] == 'projects']
    if len(rows) <= 1:
        return rows
    for _, _, item in rows:
        for name in item.get('tech_stack') or []:
            subject = _pattern(name).sub('', subject)
    subject = re.sub(r'请|帮我|给|把|将|为|那个|这个|那段|这段|项目|工作经历|实习|经历|公司|的', ' ', subject)
    terms = re.findall(r'[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}', subject.casefold())
    if not terms:
        return rows
    def matches(row, body=False):
        item = row[2]
        text = item.get('name') or item.get('company') or ''
        if body:
            text += ' ' + ' '.join([item.get('description') or '', *(item.get('polished_bullets') or item.get('bullets') or [])])
        return all(compact(term) in compact(text) for term in terms)
    return [row for row in rows if matches(row)] or [row for row in rows if matches(row, True)]


def parse_stack_edit(data: dict, instruction: str) -> dict | None:
    """Parse additions/removals as one bounded edit, without re-extracting facts."""
    rows = [(section, index, item) for section in SECTIONS
            for index, item in enumerate(data.get(section) or []) if not item.get('hidden')]
    if not rows:
        return None
    removal = re.search(r'去掉|删掉|删除|移除', instruction)
    addition = re.search(r'(?:技术栈\s*(?:加上|加|添加|补上|为|是|[:：])?\s*|(?:用了|使用了|用到(?:了)?)\s*)([^。；;\n]+)', instruction)
    marking = re.search(r'(?:标(?:注|一下)?|补充|加上|写上).{0,5}技术栈', instruction)
    if not removal and not addition and not marking:
        return None
    if not removal and '技术栈' not in instruction:
        # "新项目使用了 X 做 Y" is new experience material, not a delta on
        # whichever document happens to exist already.
        return None
    # A generic delete instruction belongs here only when it names a stack term.
    if not addition and not marking and '技术栈' not in instruction and not any(
            _pattern(name).search(instruction) for _, _, item in rows for name in item.get('tech_stack') or []):
        return None
    candidates = _edit_target(rows, instruction)
    if removal and '技术栈' not in instruction and len(candidates) > 1:
        candidates = [row for row in candidates if any(_pattern(name).search(instruction)
                      for name in row[2].get('tech_stack') or [])]
    if len(candidates) != 1:
        return {'error': '请指明要修改技术栈的项目或工作经历。'}
    section, index, item = candidates[0]
    added, removed = [], []
    explicit_additions = list(re.finditer(
        r'(?:加上|添加|补上)\s*(?:技术栈\s*)?(.+?)'
        r'(?=[，,、\s]*(?:并|再|同时)?\s*(?:去掉|删掉|删除|移除|加上|添加|补上)|[。；;\n]|$)', instruction))
    if explicit_additions:
        for match in explicit_additions:
            body = match[1].strip(' ，,、')
            names = pure_stack('技术栈：' + body) if not NEGATIVE.search(body) else []
            if not names:
                return {'error': '没有识别到完整的新增技术名称，技术栈未修改。'}
            added.extend(names)
    elif addition:
        body = re.split(r'(?:[，,、\s]*(?:并|再|同时)?\s*)?(?:去掉|删掉|删除|移除)', addition[1], maxsplit=1)[0]
        body = body.strip(' ，,、')
        removal_only = removal and body in {'', '全部', '整行'}
        added = pure_stack('技术栈：' + body) if not removal_only and not NEGATIVE.search(body) else []
        if not added and not marking and not removal_only:
            return {'error': '没有识别到完整的新增技术名称，技术栈未修改。'} if '技术栈' in instruction else None
    if removal:
        after = re.split(r'[。；;\n]|加上|添加|补上', instruction[removal.end():], maxsplit=1)[0].strip(' ，,、')
        before = instruction[:removal.start()].rsplit('，', 1)[-1].rsplit(',', 1)[-1]
        requested = after or before
        hits = [(name, match.span()) for name in item.get('tech_stack') or []
                for match in _pattern(name).finditer(requested)]
        removed = [name for name, (start, end) in hits if not any(
            left <= start and end <= right and (left, right) != (start, end) for _, (left, right) in hits)]
        if re.search(r'技术栈(?:全部|整行)?$', requested.strip()):
            removed = list(item.get('tech_stack') or [])
        # An unknown removal is a no-op, never permission to clear the stack.
    if not added and not removed and not marking:
        return {'error': '没有识别到可增删的技术名称，技术栈未修改。'} if '技术栈' in instruction else None
    op = 'update' if added and removed else 'remove' if removed else 'add'
    return {'section': section, 'index': index, 'item_id': item.get('item_id'), 'op': op,
            'names': removed if op == 'remove' else added, 'remove_names': removed}


def item_facts(collected: dict, edit: dict) -> list[dict]:
    sections = ('work_experience', 'internship') if edit['section'] == 'work_experience' else ('projects',)
    return [fact for section in sections for item in collected.get(section) or []
            if item.get('item_id') == edit['item_id'] for fact in item.get('facts') or []]


def record_stack_edit(collected: dict, edit: dict, quote: str, turn_id: str) -> dict:
    """Only record_facts calls this narrow intake adapter with original user text."""
    from copy import deepcopy
    from app.services.resume_facts import new_fact
    result = deepcopy(collected)
    if edit.get('error') or edit['op'] not in {'add', 'update'} or not edit['names']:
        return result
    owners = [item for section in ('projects', 'work_experience', 'internship')
              for item in result.get(section) or [] if item.get('item_id') == edit['item_id']]
    if len(owners) != 1:
        return result
    owner = owners[0]
    for name in edit['names']:
        if not supporting_ids(name, owner.get('facts') or []) and mention_position(name, quote) is not None:
            fact = new_fact(name, kind='method_tool', quote=quote, turn_id=turn_id)
            fact['dimension'] = 'tech_stack'
            owner.setdefault('facts', []).append(fact)
    return result


def apply_stack_edit(data: dict, meta: dict, collected: dict, edit: dict) -> tuple[dict, dict]:
    from copy import deepcopy
    from app.services.resume_versions import text_hash
    output, metadata = deepcopy(data), deepcopy(meta)
    item = output[edit['section']][edit['index']]
    iid = item.get('item_id')
    excluded = metadata.setdefault('tech_stack_excluded', {}).setdefault(iid, [])
    facts = item_facts(collected, edit)
    added = (edit['names'] or [name for fact in facts for name in extract_stack(fact)]) if edit['op'] != 'remove' else []
    if any(not supporting_ids(name, facts) for name in added):
        raise ValueError('record_facts_first')
    removed = {normalize_name(name).casefold() for name in
               (edit['names'] if edit['op'] == 'remove' else edit.get('remove_names', []))}
    kept = [name for name in item.get('tech_stack') or [] if name.casefold() not in removed]
    stack = normalize_stack_unbounded([*kept, *added])
    if len(stack) > MAX_ITEMS:
        raise ValueError('tech_stack_limit')
    excluded[:] = [name for name in dict.fromkeys([*excluded, *sorted(removed)])
                   if name not in {n.casefold() for n in added}]
    old = {row.get('text_hash'): row for row in metadata.get('tech_stack', {}).get(iid, [])}
    metadata.setdefault('tech_stack', {})[iid] = [
        old.get(text_hash(name), {'text_hash': text_hash(name), 'fact_ids': supporting_ids(name, facts)})
        for name in stack]
    if stack:
        item['tech_stack'] = stack
    else:
        item.pop('tech_stack', None)
    # A stack edit never reprojects or rewrites existing body text or evidence.
    return output, metadata


def stack_receipt(data: dict) -> list[dict]:
    """Describe the actual projected document, not rejected candidate prose."""
    return [{'name': item.get('name') or item.get('company') or '',
             'tech_stack': list(item['tech_stack']),
             'message': '已按规范名 ' + '、'.join(item['tech_stack']) + ' 写入技术栈。'}
            for section in SECTIONS for item in data.get(section) or []
            if item.get('tech_stack') and not item.get('hidden')]


async def stack_edit_update(state: dict, instruction: str, edit: dict) -> dict:
    """One version transaction, preserving the pre-edit document and metadata."""
    import asyncio
    from app.agents.tailor_pipeline import constraints_for_turn
    from app.services.resume_capacity import measure_rendered_pages
    from app.services.resume_review import resume_to_text
    from app.services.resume_versions import prepare_version
    data, meta = apply_stack_edit(state['resume_data'], state.get('resume_meta') or {},
                                 state.get('collected_info') or {}, edit)
    from app.services.fact_coverage import ensure_fact_coverage
    ensure_fact_coverage(data, meta, state.get('collected_info') or {})
    measurement = await asyncio.to_thread(measure_rendered_pages, data, constraints_for_turn(state, instruction))
    result = prepare_version(state['resume_data'], state.get('resume_meta') or {}, state.get('resume_versions') or [],
                             data, meta, label='技术栈更新')
    summary = ['已更新技术栈'] if result['changed'] else ['技术栈未变化']
    result['resume_meta'].update(page_check=measurement, change_summary=summary)
    result.update(stage='EVALUATING', resume_draft=resume_to_text(data), change_summary=summary, page_check=measurement)
    return result
