"""Literal month ranges, scoped to one already identified experience."""
import re

from app.services.candidate_language import non_fact, placeholder_name
from app.services.resume_facts import new_fact


MONTH_RANGE = re.compile(
    r"(?<!\d)(?P<year>20\d{2})\s*[年./-]\s*(?P<month>1[0-2]|0?[1-9])\s*月?\s*"
    r"(?:到|至|[—–~～-])\s*(?:(?P<end_year>20\d{2})\s*[年./-]\s*)?"
    r"(?P<end_month>1[0-2]|0?[1-9])\s*月?(?!\d)"
)


def recover_experience_dates(patch: dict, evidence: str, outline: list[dict], turn_id: str) -> None:
    from app.agents.fact_extractor import _subject_owner
    owners = {row['item_id']: row for row in outline}
    owners.update({row['item_id']: row for row in patch['items']})
    for sentence in re.split(r'[。；;\n]', evidence):
        ranges = list(MONTH_RANGE.finditer(sentence))
        # Multiple ranges/owners in a sentence require an explicit model mapping.
        if len(ranges) != 1:
            continue
        match = ranges[0]
        if non_fact(sentence[:match.end()].strip()):
            continue
        named = [row for row in owners.values() if row.get('name')
                 and not placeholder_name(row['name']) and (row['name'] in sentence or (
                     row['section'] == 'campus' and row['name'].startswith('校园') and row['name'][2:] in sentence))]
        owner = named[0] if len(named) == 1 else None
        if not named:
            candidate = _subject_owner(match[0], sentence, list(owners.values()))
            if candidate and candidate['item_id'] in owners:
                owner = candidate
        if not owner or owner['section'] not in {'projects', 'campus', 'work_experience', 'internship', 'education', 'open_source'}:
            continue
        start = f"{match['year']}.{int(match['month']):02d}"
        end = f"{match['end_year'] or match['year']}.{int(match['end_month']):02d}"
        if end < start:
            continue  # Do not guess a year rollover from a two-month fragment.
        entry = next((row for row in patch['items'] if row['item_id'] == owner['item_id']), None)
        if entry is None:
            entry = {key: owner[key] for key in ('section', 'item_id', 'name')}
            entry.update(facts=[], raw_notes=[])
            patch['items'].append(entry)
        for field, value in (('start_date', start), ('end_date', end)):
            entry['facts'] = [f for f in entry['facts'] if f.get('field') != field]
            fact = new_fact(value, kind='context', quote=match[0], turn_id=turn_id)
            entry['facts'].append({**fact, 'field': field})
