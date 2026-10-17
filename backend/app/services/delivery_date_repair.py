"""最终交付旧稿时修复已确认的日期伪要点，只利用因此空出的容量。"""
from copy import deepcopy
import re

from app.services.candidate_language import date_only, resume_bullet
from app.services.fact_guard import guard_bullets, strip_absence
from app.services.resume_facts import active_facts_for_writer
from app.services.resume_versions import text_hash


def _months(text):
    return {(int(year), int(month)) for year, month in re.findall(r'((?:19|20)\d{2})[年./-](\d{1,2})', text)}


async def repair_delivery_dates(data: dict, meta: dict, collected: dict, plan: dict, role_family: str = '') -> bool:
    from app.agents.resume_writer import _body_fact
    from app.services.fact_coverage import ensure_fact_coverage, text_covered
    from app.services.writing_style import format_rows

    source = active_facts_for_writer(collected)
    facts = {f['id']: f for section in ('projects', 'work_experience', 'internship', 'campus')
             for item in source.get(section) or [] for f in item.get('facts') or []}
    plans = {row['item_id']: row for row in plan.get('experience_plan', [])}
    omissions = {row['fact_id']: row for row in meta.get('fact_coverage', {}).get('facts', [])
                 if row.get('status') == 'omitted' and row.get('reason', '').startswith('本版条数上限')}
    selected = {fid for row in plan.get('requirements', []) for fid in row.get('fact_ids', [])}
    changed = False
    for section in ('projects', 'work_experience', 'campus'):
        if data.get('sections') is not None and section not in {s['kind'] for s in data['sections']}:
            continue
        for item in data.get(section) or []:
            item_id = item.get('item_id')
            if item.get('hidden') or plans.get(item_id, {}).get('treatment') == 'backup':
                continue
            field = 'polished_bullets' if section == 'projects' else 'bullets'
            body = item.get(field) or []
            headers = _months(str(item.get('start_date', '')) + ' ' + str(item.get('end_date', '')))
            records = meta.get('bullets', {}).get(item_id, [])
            rows, cleaned_any = [], False
            for index, text in enumerate(body):
                record = deepcopy(records[index]) if index < len(records) else {}
                refs = record.get('fact_ids', [])
                valid = record.get('text_hash') == text_hash(text) and refs and all(
                    fid in facts and facts[fid].get('item_id') == item_id for fid in refs)
                parts = re.split(r'([，,。；;\n])', text)
                cleaned = ''.join(parts[i] + (parts[i + 1] if i + 1 < len(parts) else '') for i in range(0, len(parts), 2)
                                  if not (valid and date_only(parts[i]) and _months(parts[i]) and _months(parts[i]) <= headers)).rstrip('，,；;\n')
                cleaned_any |= cleaned != text
                if cleaned != text:
                    record.pop('coverage_fact_ids', None)
                    record['text_hash'] = text_hash(cleaned)
                if cleaned:
                    rows.append({**record, 'text': cleaned})
            if not cleaned_any:
                continue
            changed = True
            # 不扩大原有条数，不恢复用户明确删去或主动设为备用的内容。
            slots = max(0, min(len(body), plans.get(item_id, {}).get('target_bullets', len(body))) - len(rows))
            missing = [f for fid, f in facts.items() if fid in omissions and f.get('item_id') == item_id
                       and _body_fact(f) and not text_covered(f['text'], [row['text'] for row in rows])]
            missing.sort(key=lambda f: (f['id'] not in selected, f.get('kind') != 'method_tool'))
            for fact in missing:
                if slots <= 0:
                    break
                text = resume_bullet(strip_absence(fact['text']), name=item.get('name') or item.get('company') or '')
                proposal = {'id': fact['id'], 'item_id': item_id, 'text': text, 'fact_ids': [fact['id']]}
                checked = await guard_bullets([proposal], list(facts.values()), lexical_only=True) if text else []
                if checked and checked[0]['verdict'] == 'pass':
                    rows.append(proposal)
                    slots -= 1
            if section == 'projects':
                rows = format_rows(rows, facts, plan.get('bullet_style', 'plain'), role_family=role_family)
            item[field] = [row['text'] for row in rows]
            meta.setdefault('bullets', {})[item_id] = [{**{k:v for k,v in row.items() if k != 'text'},
                                                       'text_hash':text_hash(row['text'])} for row in rows]
    if changed:
        ensure_fact_coverage(data, meta, collected)
    return changed
