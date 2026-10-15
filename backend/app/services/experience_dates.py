"""Literal month ranges, scoped to one already identified experience."""
import re

from app.services.candidate_language import non_fact, placeholder_name
from app.services.resume_facts import new_fact


MONTH_RANGE = re.compile(
    r"(?<!\d)(?P<year>20\d{2})\s*[年./-]\s*(?P<month>1[0-2]|0?[1-9])\s*月?\s*"
    r"(?:到|至|[—–~～-])\s*(?:(?P<end_year>20\d{2})\s*[年./-]\s*)?"
    r"(?P<end_month>1[0-2]|0?[1-9])\s*月?(?!\d)"
)


def parse_month_range(text: str) -> tuple[str, str] | None:
    """One literal, chronological range; never infer a rollover year."""
    matches = list(MONTH_RANGE.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    start = f"{match['year']}.{int(match['month']):02d}"
    end = f"{match['end_year'] or match['year']}.{int(match['end_month']):02d}"
    return (start, end) if end >= start else None


def recover_experience_dates(patch: dict, evidence: str, outline: list[dict], turn_id: str) -> None:
    from app.agents.fact_extractor import _subject_owner
    from app.services.experience_subjects import explicit_subject_spans
    owners = {row['item_id']: row for row in outline}
    owners.update({row['item_id']: row for row in patch['items']})
    spans = explicit_subject_spans(evidence)
    segments = [(evidence[span['start']:span['end']], span) for span in spans]
    # Keep the free-text fallback, but do not let sentence-level ambiguity or
    # an introductory personal header override an explicit numbered subject.
    unscoped = list(evidence)
    for span in spans:
        unscoped[span['start']:span['end']] = ' ' * (span['end'] - span['start'])
    segments.extend((sentence, None) for sentence in re.split(r'[。；;\n]', ''.join(unscoped)))
    for sentence, span in segments:
        ranges = list(MONTH_RANGE.finditer(sentence))
        # Multiple ranges/owners in a sentence require an explicit model mapping.
        if len(ranges) != 1:
            continue
        match = ranges[0]
        if not span and non_fact(sentence[:match.end()].strip()):
            continue
        named = [row for row in owners.values() if row.get('name')
                 and not placeholder_name(row['name']) and (row['name'] in sentence or (
                     row['section'] == 'campus' and row['name'].startswith('校园') and row['name'][2:] in sentence))]
        if span:
            scoped = [row for row in owners.values()
                      if row['section'] == span['section'] and row['name'] == span['name']]
            owner = scoped[0] if len(scoped) == 1 else None
        else:
            owner = named[0] if len(named) == 1 else None
        if not span and not owner and re.match(r'\s*教育(?:时间|日期|起止时间)', sentence):
            education = [row for row in owners.values() if row['section'] == 'education']
            owner = education[0] if len(education) == 1 else None
        if not span and not owner and not named:
            candidate = _subject_owner(match[0], sentence, list(owners.values()))
            if candidate and candidate['item_id'] in owners:
                owner = candidate
        if not owner or owner['section'] not in {'projects', 'campus', 'work_experience', 'internship', 'education', 'open_source'}:
            continue
        dates = parse_month_range(sentence)
        if not dates:
            continue
        start, end = dates
        entry = next((row for row in patch['items'] if row['item_id'] == owner['item_id']), None)
        if entry is None:
            entry = {key: owner[key] for key in ('section', 'item_id', 'name')}
            entry.update(facts=[], raw_notes=[])
            patch['items'].append(entry)
        # A date-only clause can also sit inside a compound header (date +
        # team size). Keep its substantive remainder and original provenance;
        # an inline dated action is not a header clause and stays unchanged.
        kept = []
        for fact in entry['facts']:
            if not fact.get('field'):
                parts = re.split(r'[，,。；;]', fact['text'])
                body = [part for part in parts if not (
                    MONTH_RANGE.fullmatch(part.strip()) and parse_month_range(part) == dates)]
                if len(body) != len(parts):
                    fact['text'] = '，'.join(part.strip() for part in body if part.strip())
                if not fact['text'] or fact['text'] in {start, end}:
                    continue
            kept.append(fact)
        entry['facts'] = kept
        for field, value in (('start_date', start), ('end_date', end)):
            # Remove wrong same-turn mappings even when the model quoted only
            # one endpoint of a range from a different experience.
            for other in patch['items']:
                if other['item_id'] != owner['item_id']:
                    other['facts'] = [f for f in other['facts'] if not (
                        f.get('field') == field and f.get('source_quote')
                        and evidence.count(f['source_quote']) == 1
                        and f['source_quote'] in match[0])]
            entry['facts'] = [f for f in entry['facts'] if f.get('field') != field]
            fact = new_fact(value, kind='context', quote=match[0], turn_id=turn_id)
            prior = next((row for row in outline if row['item_id'] == owner['item_id']), {})
            old_fields = [old for old in prior.get('facts', []) if old.get('field') == field and old['text'] != value]
            if not old_fields:
                entry['facts'].append({**fact, 'field': field})
            for old in old_fields:
                patch['corrections'].append({'item_id': owner['item_id'], 'fact_id': old['id'],
                                             'replacement': {**fact, 'field': field}})
