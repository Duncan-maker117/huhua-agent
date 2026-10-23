"""本人提交的结构化答案直接入事实；题干仅作为语境，不能充当经历证据。"""
import re

from app.services.ask_user import question_dimension, subject_key
from app.services.resume_facts import new_fact, normalize_fact_store
from app.schemas.facts import FACT_LABELS, FACT_SECTIONS
from app.services.experience_fields import (
    merge_normalized_experiences, normalize_field, parse_dates, require_confirmation,
    matching_item, names_match,
)


def answer_field(identifier: str, prompt: str) -> str:
    """Only explicit identity questions can populate an experience heading."""
    text = f"{identifier} {prompt}".lower()
    if re.search(r"手机|电话|邮箱|联系方式|姓名|学校.*专业", text):
        return ""
    if identifier == "dates" or "起止时间" in prompt:
        return "dates"
    for field, pattern in (
        ("start_date", r"start[_-]?(?:date|time)|开始.*(?:时间|年月)|哪年.*开始"),
        ("end_date", r"end[_-]?(?:date|time)|结束.*(?:时间|年月)|哪年.*结束"),
        ("role", r"\brole\b|角色|担任.*职务"),
        ("name", r"(?:project|experience|company)[_-]?name|名称|名字|叫什么"),
    ):
        if re.search(pattern, text):
            return field
    return ""


def answer_dates(value: str, target: dict) -> dict:
    return parse_dates(value, target)


def append_answer(target: dict, value: str, *, message, question_id: str,
                  prompt: str, dimension: str = "", kind: str = "action") -> None:
    value = value.strip()
    if not value or re.fullmatch(r"不知道|不清楚|不确定|未知|跳过", value):
        return
    provenance = {"question_id": question_id, "question_prompt": prompt,
                  "answer_value": value, "item_id": target.get("item_id", ""),
                  "dimension": dimension}
    # 重试同一条 HumanMessage 不复制事实，其他轮重复陈述仍保留其独立来源。
    if any(f.get("turn_id") == message.id and f.get("question_id") == question_id
           and f.get("answer_value") == value for f in target.setdefault("facts", [])):
        return
    fact = new_fact(value, kind=kind, quote=value, turn_id=message.id or "",
                    source_name="用户本人回答")
    fact.update(provenance)
    fact["sources"][0].update(provenance)
    target["facts"].append(fact)


def apply_answers(collected: dict, message, *, project_fields: bool = True) -> dict:
    result = normalize_fact_store(collected)
    answers = message.additional_kwargs.get("answers") or {}
    card = message.additional_kwargs.get("answer_card") or {}
    if not card or answers.get("turn_id") != card.get("turn_id"):
        return result
    subject = str(card.get("subject") or "").strip().casefold()
    if subject:
        aliases = [item for section in FACT_SECTIONS for item in result.get(section) or []
                   if subject in {str(item.get(field) or "").strip().casefold() for field in ("item_id", "name", "company", "school")}
                   or any(subject in {str(row.get('item_id', '')).casefold(), str(row.get('name', '')).casefold()}
                          for row in item.get('merged_from') or [])]
        if len(aliases) != 1:
            return result
    key = subject_key(card.get("subject", ""), {"collected_info": result})
    matches = [item for section in FACT_SECTIONS for item in result.get(section) or []
               if item.get("item_id") == key]
    if len(matches) != 1:
        return result  # 归属不唯一时不能把答案挂到最后一段经历。
    target = matches[0]
    section = next(section for section in FACT_SECTIONS if target in result.get(section, []))
    questions = {q["id"]: q for q in card.get("questions") or []}
    for answer in answers.get("items") or []:
        question = questions.get(answer.get("id"))
        if question and (answer.get('skipped') or answer.get('unknown')):
            for row in target.get('field_confirmations') or []:
                if 'confirm_' + row['field'] == question['id']:
                    row['confirmation_attempts'] = 1
        if not question or answer.get("skipped") or answer.get("unknown"):
            continue
        dimension = question_dimension(question["id"], question["prompt"])
        kind = {"tech_stack": "method_tool", "problem": "context",
                "status": "status_limit", "links": "deliverable"}.get(dimension, "action")
        values = answer.get("value") or []
        values = values if isinstance(values, list) else [values]
        for value in dict.fromkeys(values):
            if not isinstance(value, str):
                continue
            # allow_other 的任意自填也属于本人陈述；不从未选选项补事实。
            if question["kind"] != "text" and value not in question.get("options", []) and not question.get("allow_other"):
                continue
            if project_fields:
                from app.agents.interviewer import NO_ANSWER
                if NO_ANSWER.fullmatch(value.strip()) or value.strip() in {"不确定", "未知"}:
                    for row in target.get('field_confirmations') or []:
                        if 'confirm_' + row['field'] == question['id']:
                            row['confirmation_attempts'] = 1
                    continue
            if project_fields and (field := answer_field(question["id"], question["prompt"])):
                from app.services.candidate_language import placeholder_name
                from app.services.intake import _write_field
                value = value.strip()
                if not value or NO_ANSWER.fullmatch(value) or value in {"不确定", "未知"}:
                    continue
                if any(f.get('turn_id') == message.id and f.get('question_id') == question['id']
                       and f.get('answer_value') == value for f in target.get('facts') or []):
                    continue
                if field == "dates":
                    from app.schemas.facts import FACT_FIELDS
                    dates = answer_dates(value, target) if len(set(values)) == 1 else {}
                    if dates and all(key in FACT_FIELDS[section] for key in dates):
                        for key, date in dates.items():
                            fact = _write_field(target, key, date, message, source_quote=value)
                            provenance = {"question_id": question["id"], "question_prompt": question["prompt"],
                                          "dimension": dimension, "answer_value": value}
                            fact.update(provenance)
                            fact["sources"][0].update(provenance)
                    else:
                        require_confirmation(target, field, value, fact={'turn_id': message.id,
                            'question_id': question['id'], 'question_prompt': question['prompt']})
                    continue
                field = FACT_LABELS[section] if field == "name" else "title" if field == "role" and section in {"work_experience", "internship"} else field
                from app.schemas.facts import FACT_FIELDS
                projectable = field in FACT_FIELDS[section] and len(set(values)) == 1
                quote = value
                value = normalize_field(field, value)
                if field == FACT_LABELS[section]:
                    candidate = {**target, field: value}
                    existing = matching_item([row for row in result.get(section) or [] if row is not target], candidate, section)
                    if existing:
                        value = existing[field]
                    elif names_match(target.get(field), value):
                        value = target[field]
                    projectable = projectable and (not target.get(field) or placeholder_name(target[field])
                                                    or names_match(target[field], value))
                if not projectable or not value:
                    require_confirmation(target, field, quote, fact={'turn_id': message.id,
                        'question_id': question['id'], 'question_prompt': question['prompt']})
                    continue
                fact = _write_field(target, field, value, message, source_quote=quote)
                provenance = {"question_id": question["id"], "question_prompt": question["prompt"],
                              "dimension": dimension}
                fact.update(provenance)
                fact["sources"][0].update(provenance)
                continue
            append_answer(target, value, message=message, question_id=question["id"],
                          prompt=question["prompt"], dimension=dimension, kind=kind)
    return merge_normalized_experiences(normalize_fact_store(result), collected)


def project_answer_fields(data: dict, collected: dict) -> None:
    """Project confirmed answer fields without replacing a real saved name."""
    from app.services.candidate_language import placeholder_name
    for section in FACT_SECTIONS:
        for source in collected.get(section) or []:
            targets = [item for item in data.get("work_experience" if section == "internship" else section) or []
                       if item.get("item_id") in {source.get("item_id"), *[row.get('item_id') for row in source.get('merged_from') or []]}]
            for target in targets:
                label = FACT_LABELS[section]
                if source.get('merged_from') and (placeholder_name(target.get(label, '')) or names_match(target.get(label), source.get(label))):
                    target[label] = source.get(label, '')
                for fact in source.get("facts") or []:
                    field = fact.get("field")
                    if (field not in {label, "start_date", "end_date", "role", "title"}
                            or not fact.get("question_id") or fact.get("status", "active") != "active"):
                        continue
                    if field == label and not placeholder_name(target.get(field, "")):
                        continue
                    target[field] = normalize_field(field, fact["text"]) or ''
