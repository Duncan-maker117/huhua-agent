"""Literal corrections are small fact/draft transactions, never writer prompts."""
from copy import deepcopy
import re
import uuid

from app.schemas.facts import FACT_SECTIONS
from app.services.resume_facts import new_fact, normalize_fact_store
from app.services.resume_versions import text_hash


def recover_experience_merges(patch: dict, evidence: str, outline: list[dict], turn_id: str) -> None:
    """Bind an explicit same-experience correction to uniquely matching topics.

    Model-proposed merge IDs are never trusted. Each source must be a placeholder
    (or a literal anonymous employer), with current facts matching a named topic.
    """
    from app.services.candidate_language import non_fact, placeholder_name, safe_item_name

    for sentence in re.split(r'[。；;\n]', evidence):
        if re.search(r'不是同一|并非同一|不同|不要|别把|不能|如果|假设|[？?]', sentence):
            continue
        same = re.search(r'([^，,。；;]+?)(?:都?是|均属于|都属于|属于)这?(?:同一段|同一个)'
                         r'(?:(?:实习|工作)(?:经历)?|经历|(?=[，,]|$))', sentence)
        same = same or re.search(r'([^，,。；;]+?)(?:不是|并非)(?:个人练习|个人项目|项目)(?:[，,]|$)', sentence)
        if not same:
            continue
        company = re.search(r'(实习公司|公司)(?:名称)?(?:叫|是|为|[：:])\s*([^，,。；;（(]+)', sentence)
        if not company or not safe_item_name(company[2].strip()):
            continue
        name = company[2].strip()
        section = 'internship' if '实习' in company[1] or '实习' in same[0] else 'work_experience'
        topics = [part.strip() for part in re.split(r'和|与|及|、', same[1]) if part.strip()]
        if len(topics) < 2:
            continue
        sources = []
        ambiguous = False
        for topic in topics:
            grams = {topic[i:i + 2] for i in range(len(topic) - 1)} - {'经历', '工作', '实习'}
            matches = []
            for row in outline:
                if row['section'] not in {'projects', 'work_experience', 'internship'}:
                    continue
                if not (placeholder_name(row['name']) or row['name'] == name or
                        re.fullmatch(r'(?:一家|某|本地).*(?:品牌|公司|门店)', row['name'])):
                    continue
                text = ' '.join(f['text'] for f in row['facts'] if not f.get('field') and not non_fact(f['text']))
                if topic in text or len({gram for gram in grams if gram in text}) >= 2:
                    matches.append(row)
            if len(matches) != 1:
                ambiguous = True
                break
            if matches[0] not in sources:
                sources.append(matches[0])
        if ambiguous or not sources:
            continue
        existing = {row['item_id']: row for row in [*outline, *patch['items']]
                    if row['section'] == section and re.split(r'[（(]', row['name'], maxsplit=1)[0].strip() == name}
        if len(existing) > 1:
            continue
        target = next(iter(existing.values()), None)
        target_id = target['item_id'] if target else str(uuid.uuid4())
        entry = next((row for row in patch['items'] if row['item_id'] == target_id), None)
        if entry is None:
            entry = {'section': section, 'item_id': target_id, 'name': name, 'facts': [], 'raw_notes': []}
            patch['items'].append(entry)
        entry['name'] = name
        fields = {'company': name}
        role = re.search(r'岗位(?:是|为|[：:])\s*([^，,。；;]+)', sentence)
        if role:
            fields['title'] = role[1].strip()
        for field, value in fields.items():
            entry['facts'].append({**new_fact(value, kind='role' if field == 'title' else 'context',
                                             quote=value, turn_id=turn_id), 'field': field})
        patch.setdefault('merges', []).append({
            'target_item_id': target_id, 'section': section, 'name': name,
            'source_item_ids': [row['item_id'] for row in sources if row['item_id'] != target_id],
            'source_quote': sentence, 'turn_id': turn_id,
        })


def apply_experience_merges(store: dict, merges: list[dict]) -> None:
    """Move original fact IDs/sources and remove the obsolete item identities."""
    from app.schemas.facts import FACT_LABELS
    from app.services.candidate_language import non_fact, placeholder_name
    from app.services.experience_subjects import company_description_fact

    for merge in merges:
        section = merge['section']
        target = next((row for row in store.get(section, [])
                       if row['item_id'] == merge['target_item_id']), None)
        if target is None:
            continue
        confirmed_fields = {f['field']: f['text'] for f in target.get('facts', [])
                            if f.get('field') and f.get('status', 'active') == 'active'}
        source_ids = set(merge['source_item_ids'])
        for source_section in FACT_SECTIONS:
            for source in store.get(source_section, [])[:]:
                if source['item_id'] not in source_ids:
                    continue
                known = {fact['id'] for fact in target['facts']}
                target['facts'].extend(deepcopy(fact) for fact in source.get('facts', []) if fact['id'] not in known)
                for key in ('raw_notes', 'links'):
                    values = target.setdefault(key, [])
                    values.extend(deepcopy(value) for value in source.get(key, []) if value not in values)
                audit = {
                    'item_id': source['item_id'], 'section': source_section,
                    'name': source.get(FACT_LABELS[source_section], ''),
                    'source_quote': merge['source_quote'], 'turn_id': merge['turn_id'],
                }
                if audit not in target.setdefault('merged_from', []):
                    target['merged_from'].append(audit)
                store[source_section].remove(source)
        target[FACT_LABELS[section]] = merge['name']
        # Imported placeholder labels and old classification instructions are
        # audit history, not active resume claims after a merge.
        for fact in target['facts']:
            if fact.get('status', 'active') != 'active':
                continue
            if (non_fact(fact['text']) or non_fact(fact.get('source_quote', ''))
                    or company_description_fact(fact, merge['source_quote'])
                    or company_description_fact(fact, fact.get('source_quote', ''))):
                fact['status'] = 'deleted'
            elif fact.get('field') in confirmed_fields and fact['text'] != confirmed_fields[fact['field']]:
                fact['status'] = 'superseded'
            elif fact.get('field') == 'name' or (fact.get('field') == 'company' and fact['text'] != merge['name']):
                fact['status'] = 'superseded'
            elif placeholder_name(fact['text']):
                fact['status'] = 'superseded'
        target['raw_notes'] = [note for note in target.get('raw_notes', []) if not non_fact(note)]
        if (store.get('followup_target') or {}).get('item_id') in source_ids:
            store.pop('followup_target', None)


_NUMBER = r"\d+(?:\.\d+)?\s*(?:ms|毫秒|秒|场|条|人|名|次|个|篇|张|页|%|％)"
_REVERSE = re.compile(r"(?P<new>" + _NUMBER + r")[，,\s]*(?:而?不是|并非)\s*(?P<old>" + _NUMBER + r")", re.I)
_FORWARD = re.compile(r"(?P<old>" + _NUMBER + r")\s*(?:改成|改为|改|更正为|替换为)\s*(?P<new>" + _NUMBER + r")", re.I)
_QUOTED = re.compile(r"[“「\"](?P<old>[^”」\"\n]+)[”」\"]\s*(?:改成|改为|替换为)\s*[“「\"](?P<new>[^”」\"\n]+)[”」\"]")


def correction_pairs(message: str, collected: dict | None = None) -> list[dict]:
    pairs = []
    for pattern in (_REVERSE, _FORWARD, _QUOTED):
        for match in pattern.finditer(message or ""):
            if re.sub(r"\s", "", match['old']) == re.sub(r"\s", "", match['new']):
                continue
            start = max(message.rfind(mark, 0, match.start()) for mark in ('。', '；', ';', '\n')) + 1
            if re.search(r'不要|别把|不能|如果|假设', message[start:match.start()]):
                continue
            pairs.append({'old': match['old'], 'new': match['new'], 'quote': match[0],
                          'context': message[start:match.start()]})
    if not pairs and collected is not None:
        for match in re.finditer(r'([^。；;\n]{2,40}?)(?:改成|改为|更正为)\s*(' + _NUMBER + r')', message or '', re.I):
            context, new = match[1], match[2]
            if re.search(r'不要|别把|不能|如果|假设', context):
                continue
            terms = {context[i:i + 2] for i in range(len(context) - 1)
                     if re.fullmatch(r'[\u4e00-\u9fff]{2}', context[i:i + 2])}
            unit = re.sub(r'^[\d.]+\s*', '', new)
            old_values = {value.group() for section in FACT_SECTIONS for item in (collected or {}).get(section, [])
                          for fact in item.get('facts', []) if fact.get('status', 'active') == 'active'
                          and any(term in fact.get('text', '') for term in terms)
                          for value in re.finditer(r'\d+(?:\.\d+)?\s*' + re.escape(unit), fact.get('text', ''), re.I)}
            pairs.append({'old': old_values.pop() if len(old_values) == 1 else '', 'new': new,
                          'quote': match[0], 'context': context})
    return pairs


def _pattern(value: str):
    pieces = re.findall(r"\d+(?:\.\d+)?|[^\s\d]+", value)
    body = r"\s*".join(re.escape(piece) for piece in pieces)
    return re.compile((r"(?<![\d.])" if value[0].isdigit() else "") + body
                      + (r"(?![A-Za-z0-9])" if value[-1].isascii() and value[-1].isalnum() else ""), re.I)


def _replace(text: str, pair: dict) -> str:
    def replacement(match):
        # Keep the original spacing between numbers and units.
        old = re.fullmatch(r"(\d+(?:\.\d+)?)(\s*)(.+)", match[0])
        new = re.fullmatch(r"(\d+(?:\.\d+)?)(\s*)(.+)", pair['new'])
        if old and new and old[3].casefold() == new[3].casefold():
            return new[1] + old[2] + old[3]
        return pair['new']
    return _pattern(pair['old']).sub(replacement, text)


def apply_literal_corrections(collected: dict, data: dict, meta: dict, pairs: list[dict]) -> dict:
    """Resolve one owner per pair, update every reference, or roll back the turn."""
    from app.agents.fact_extractor import apply_fact_patch

    facts = normalize_fact_store(collected)
    draft, metadata = deepcopy(data), deepcopy(meta)
    references = metadata.setdefault('bullets', {})
    for pair in pairs:
        if not pair['old']:
            return {'error': '未能唯一定位更正前的数值，当前正文未更改。'}
        old_pattern, new_pattern = _pattern(pair['old']), _pattern(pair['new'])
        owners = [(section, item) for section in FACT_SECTIONS for item in facts.get(section, [])
                  if any(f.get('status', 'active') == 'active' and old_pattern.search(f.get('text', ''))
                         for f in item.get('facts', []))]
        if len(owners) > 1:
            context = pair['context']
            named = [(section, item) for section, item in owners
                     if (label := item.get('name') or item.get('company') or item.get('school')) and label in context]
            if named:
                owners = named
            else:
                terms = {context[i:i + 2] for i in range(len(context) - 1)
                         if re.fullmatch(r"[\u4e00-\u9fff]{2}", context[i:i + 2])}
                owners = [(section, item) for section, item in owners if any(
                    term in f.get('text', '') for term in terms for f in item.get('facts', [])
                    if f.get('status', 'active') == 'active' and old_pattern.search(f.get('text', '')))]
        if len(owners) != 1:
            return {'error': f"未能唯一定位「{pair['old']}」对应的事实，当前正文未更改。"}
        _, owner = owners[0]
        matching = [fact for fact in owner.get('facts', [])
                    if fact.get('status', 'active') == 'active' and old_pattern.search(fact.get('text', ''))]
        context = re.sub(r'刚才|有个|数据|纠正|更正|优化后|约|是|：|:', '', pair['context'])
        terms = {context[i:i + 2] for i in range(len(context) - 1)
                 if re.fullmatch(r'[\u4e00-\u9fff]{2}', context[i:i + 2])}
        focused = [fact for fact in matching if any(term in fact['text'] for term in terms)]
        if focused:
            matching = focused
        elif len({re.sub(r'\s', '', fact['text']) for fact in matching}) > 1:
            return {'error': f"「{pair['old']}」对应多条事实，无法确定要更正哪一条，当前正文未更改。"}
        matching_ids = {fact['id'] for fact in matching}
        unrelated = [fact for fact in owner.get('facts', []) if fact.get('status', 'active') == 'active'
                     and old_pattern.search(fact.get('text', '')) and fact['id'] not in matching_ids]
        corrections, replacements = [], {}
        for fact in matching:
            replacement = new_fact(_replace(fact['text'], pair), kind=fact.get('kind', 'context'),
                                   quote='原始材料：' + (fact.get('source_quote') or fact['text']) + '\n本轮更正：' + pair['quote'])
            replacement['sources'] = [*deepcopy(fact.get('sources') or []),
                                      {'source': 'chat', 'source_quote': pair['quote'], 'turn_id': '', 'name': ''}]
            if fact.get('field'):
                replacement['field'] = fact['field']
            corrections.append({'item_id': owner['item_id'], 'fact_id': fact['id'], 'replacement': replacement})
            replacements[fact['id']] = replacement['id']
        facts = apply_fact_patch(facts, {'corrections': corrections})
        changed_texts = []
        for section in FACT_SECTIONS:
            for item in draft.get(section, []):
                records = references.get(item.get('item_id'), [])
                for field in ('bullets', 'polished_bullets'):
                    for index, text in enumerate(item.get(field) or []):
                        record = records[index] if index < len(records) else {}
                        cited = set(record.get('fact_ids') or []) & replacements.keys()
                        if item.get('item_id') != owner['item_id'] and not cited:
                            continue
                        if unrelated and not cited and not any(term in text for term in terms):
                            continue
                        if old_pattern.search(text):
                            if unrelated and len(old_pattern.findall(text)) > 1:
                                return {'error': '同一句中有多个相同旧值，无法安全定位片段；当前正文未更改。'}
                            item[field][index] = _replace(text, pair)
                            changed_texts.append(item[field][index])
                            record['text_hash'] = text_hash(item[field][index])
                            record.pop('coverage_fact_ids', None)
                        for key in ('fact_ids', 'coverage_fact_ids'):
                            if key in record:
                                record[key] = [replacements.get(fid, fid) for fid in record[key]]
                if item.get('item_id') == owner['item_id']:
                    for field in ('description', 'raw_description'):
                        if isinstance(item.get(field), str) and old_pattern.search(item[field]):
                            if unrelated:
                                return {'error': '经历描述中有相同数值的其他事实，无法安全定位片段；当前正文未更改。'}
                            item[field] = _replace(item[field], pair)
                            changed_texts.append(item[field])
        summary = metadata.get('summary') or {}
        if set(summary.get('fact_ids') or []) & replacements.keys():
            if old_pattern.search(draft.get('summary') or ''):
                draft['summary'] = _replace(draft['summary'], pair)
                changed_texts.append(draft['summary'])
                summary['text_hash'] = text_hash(draft['summary'])
            summary['fact_ids'] = [replacements.get(fid, fid) for fid in summary['fact_ids']]
        # No successful receipt for a fact-only edit or an unsuccessful substitution.
        if not changed_texts or any(old_pattern.search(text) for text in changed_texts) or not all(
                new_pattern.search(text) for text in changed_texts):
            return {'error': f"事实已定位，但当前正文未找到可替换的「{pair['old']}」引用；本轮未保存更正。"}
    return {'collected_info': facts, 'resume_data': draft, 'resume_meta': metadata}
