"""本人提交的结构化答案直接入事实；题干仅作为语境，不能充当经历证据。"""
from copy import deepcopy
import re

from app.services.ask_user import question_dimension, subject_key
from app.services.resume_facts import new_fact, normalize_fact_store
from app.schemas.facts import FACT_SECTIONS


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


def apply_answers(collected: dict, message) -> dict:
    result = normalize_fact_store(collected)
    answers = message.additional_kwargs.get("answers") or {}
    card = message.additional_kwargs.get("answer_card") or {}
    if not card or answers.get("turn_id") != card.get("turn_id"):
        return result
    subject = str(card.get("subject") or "").strip().casefold()
    if subject:
        aliases = [item for section in FACT_SECTIONS for item in result.get(section) or []
                   if subject in {str(item.get(field) or "").strip().casefold() for field in ("item_id", "name", "company", "school")}]
        if len(aliases) != 1:
            return result
    key = subject_key(card.get("subject", ""), {"collected_info": result})
    matches = [item for section in FACT_SECTIONS for item in result.get(section) or []
               if item.get("item_id") == key]
    if len(matches) != 1:
        return result  # 归属不唯一时不能把答案挂到最后一段经历。
    target = matches[0]
    questions = {q["id"]: q for q in card.get("questions") or []}
    for answer in answers.get("items") or []:
        question = questions.get(answer.get("id"))
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
            append_answer(target, value, message=message, question_id=question["id"],
                          prompt=question["prompt"], dimension=dimension, kind=kind)
    return deepcopy(result)
