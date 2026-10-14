"""Literal corrections are small fact/draft transactions, never writer prompts."""
from copy import deepcopy
import re

from app.schemas.facts import FACT_SECTIONS
from app.services.resume_facts import new_fact, normalize_fact_store
from app.services.resume_versions import text_hash


_NUMBER = r"\d+(?:\.\d+)?\s*(?:ms|毫秒|秒|场|条|人|次|个|篇|张|页|%|％)"
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
