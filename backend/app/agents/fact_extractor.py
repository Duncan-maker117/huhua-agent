"""Extract sparse, source-checked changes to the candidate fact master."""
from __future__ import annotations

import copy
import inspect
import json
import re
import uuid

from app.schemas.facts import FACT_SECTIONS
from app.services.resume_facts import new_fact, normalize_fact_store

_CONTRACT = """从候选人本轮消息抽取简历事实，只输出 JSON patch：
{"items":[{"section":"projects|work_experience|internship|education","item_id":"已有ID或空","name":"经历名","facts":[{"kind":"role|action|method_tool|deliverable|result_metric|result_qualitative|scope_scale|status_limit|context|team","text":"规范化陈述","source_quote":"本轮连续原文"}],"raw_notes":["本轮相关原话"]}],"basic_info":{},"skills":[],"corrections":[{"item_id":"","fact_id":"","replacement":{"kind":"","text":"","source_quote":""}}],"removals":[{"item_id":"","fact_id":""}]}。
口语可转书面，但不能新增数字、动作、职责、成果或工具；否定、计划、Demo、未上线必须保留。归属已有经历须用已有 item_id。
更正旧事实用 corrections，删除事实用 removals；删除文稿的句子不等于删除事实。
JD、示例、助手建议、计划要做的事情不能变成已完成事实。metadata_context 和 previous_assistant 只帮助理解短答和冲突，不是正文事实；source_quote 只能来自 message。
教育信息（学校、专业、学历、年级）归 education，不要建成项目。学校简称保持原词，不要自行扩写成全称。
不要返回整份 collected_info，不要添加未知字段。"""


def _candidate_evidence(message: str) -> str:
    """Exclude explicitly labelled external material while allowing mixed turns."""
    external = False
    kept = []
    external_label = re.compile(r"^(?:岗位职责|任职要求|职位要求|招聘要求|示例简历|简历范文|参考简历|参考材料|JD)[：:]$", re.I)
    candidate_label = re.compile(r"^(?:我的经历|本人经历|我做过|我的项目|补充我的事实)[：:]$")
    split_labels = re.compile(r"((?:岗位职责|任职要求|职位要求|招聘要求|示例简历|简历范文|参考简历|参考材料|JD|我的经历|本人经历|我做过|我的项目|补充我的事实)[：:])", re.I)
    for line in message.splitlines():
        plain = line.strip(" #*\t")
        if re.match(r"^(岗位职责|任职要求|职位要求|招聘要求|示例简历|简历范文|参考简历|参考材料|JD)$", plain, re.I):
            external = True
            continue
        if re.match(r"^(我的经历|本人经历|我做过|我的项目|补充我的事实)$", plain):
            external = False
            continue
        for part in split_labels.split(line):
            if external_label.fullmatch(part):
                external = True
            elif candidate_label.fullmatch(part):
                external = False
            elif not external:
                kept.append(part)
    return "\n".join(kept)


def _content(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "content"):
        value = value.content
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("```"):
            value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.I)
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return {}


def _is_large_rewrite(text: str, quote: str) -> bool:
    def compact(value: str) -> str:
        return re.sub(r"\s|[，。；、,.!?！？：:]", "", value).casefold()
    a, b = compact(text), compact(quote)
    return not a or not b or a != b


def _skill_affirmed(message: str, name: str) -> bool:
    for match in re.finditer(re.escape(name), message, re.I):
        before = message[max(0, match.start() - 12):match.start()]
        if not re.search(r"(?:不会|不懂|不熟悉|没用过|没学过|未使用|不掌握|不具备|计划(?:学习|使用)?|准备(?:学习|使用)?|打算(?:学习|使用)?|将(?:学习|使用)?)\s*$", before):
            return True
    return False


def _quote_has_unquoted_limit(message: str, quote: str) -> bool:
    """A model cannot crop '没有/计划' off the front of a source quote."""
    positions = list(re.finditer(re.escape(quote), message, re.I))
    if not positions:
        return True
    for match in positions:
        prefix = message[:match.start()]
        prefix = re.split(r"[，,。；;！？!?\n]|但是|不过|而是", prefix)[-1]
        if not re.search(r"(?:没有|尚未|并未|从未|未|没|不曾|不会|不|计划|准备|打算|将).{0,12}$", prefix):
            return False
    return True


async def extract_facts_patch(message: str, collected: dict, llm, *, turn_id: str = "",
                              metadata_context=None, semantic_check=None,
                              previous_assistant: str = "") -> dict:
    """Reject individual unsupported facts while retaining the rest of a patch."""
    from app.services.fact_guard import lexical_fact_errors, normalize_text, verify_semantics

    empty = {"items": [], "basic_info": {}, "skills": [], "corrections": [], "removals": [], "rejected": []}
    if not isinstance(message, str) or not message.strip() or llm is None:
        return empty
    visible = normalize_fact_store(collected)
    outline = [{"section": section, "item_id": item.get("item_id"),
                "name": item.get("name") or item.get("company") or item.get("school") or "",
                "facts": [{"id": f.get("id"), "text": f.get("text")}
                          for f in item.get("facts", []) if f.get("status") == "active"]}
               for section in FACT_SECTIONS for item in visible.get(section, []) if isinstance(item, dict)]
    payload = {"message": message, "existing": outline, "metadata_context": metadata_context or [],
               "previous_assistant": (previous_assistant or "")[:500]}
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from app.services.model_privacy import ContactRedactor, redact_model_messages
        privacy = ContactRedactor()
        messages = redact_model_messages([SystemMessage(content=_CONTRACT),
                                          HumanMessage(content=json.dumps(payload, ensure_ascii=False))], privacy)
        response = await llm.ainvoke(messages)
        candidate = privacy.restore(_content(response))
    except Exception:
        return empty
    if not isinstance(candidate, dict):
        return empty
    result = copy.deepcopy(empty)
    evidence = _candidate_evidence(message)
    known = {(item.get("item_id"), fact.get("id")) for section in FACT_SECTIONS
             for item in visible.get(section, []) if isinstance(item, dict)
             for fact in item.get("facts", []) if fact.get("status") == "active"}
    known_items = {item.get("item_id") for section in FACT_SECTIONS
                   for item in visible.get(section, []) if isinstance(item, dict)}
    semantic_pairs = []
    pending = []

    def validated(raw):
        if not isinstance(raw, dict):
            return None
        text, quote = str(raw.get("text", "")).strip(), str(raw.get("source_quote", "")).strip()
        if not text or not quote or normalize_text(quote) not in normalize_text(evidence):
            result["rejected"].append({"text": text, "reason": "source_quote_not_in_candidate_message"})
            return None
        if _quote_has_unquoted_limit(evidence, quote):
            result["rejected"].append({"text": text, "reason": "source_quote_omits_limit"})
            return None
        if (errors := lexical_fact_errors(text, quote)):
            result["rejected"].append({"text": text, "reason": errors})
            return None
        fact = new_fact(text, kind=raw.get("kind", "context"), quote=quote,
                        source="chat", turn_id=turn_id)
        if _is_large_rewrite(text, quote):
            semantic_pairs.append({"id": fact["id"], "text": text, "source_quotes": [quote]})
            pending.append(fact)
        return fact

    for raw_item in candidate.get("items", []) if isinstance(candidate.get("items"), list) else []:
        if not isinstance(raw_item, dict) or raw_item.get("section") not in FACT_SECTIONS:
            continue
        item_id = raw_item.get("item_id")
        if item_id and item_id not in known_items:
            result["rejected"].append({"text": str(raw_item.get("name", "")), "reason": "unknown_item_id"})
            continue
        if not item_id and raw_item.get("name") and normalize_text(raw_item["name"]) not in normalize_text(evidence):
            result["rejected"].append({"text": str(raw_item["name"]), "reason": "item_name_not_in_candidate_message"})
            continue
        raw_facts = raw_item.get("facts") if isinstance(raw_item.get("facts"), list) else []
        facts = [fact for raw in raw_facts if (fact := validated(raw))]
        raw_notes = raw_item.get("raw_notes") if isinstance(raw_item.get("raw_notes"), list) else []
        notes = [note for note in raw_notes
                 if isinstance(note, str) and note.strip() and normalize_text(note) in normalize_text(evidence)]
        if not facts and not notes:
            continue
        result["items"].append({"section": raw_item["section"], "item_id": item_id or str(uuid.uuid4()),
                                "name": str(raw_item.get("name", "")).strip(), "facts": facts,
                                "raw_notes": list(dict.fromkeys(notes))})
    for raw in candidate.get("corrections", []) if isinstance(candidate.get("corrections"), list) else []:
        if not isinstance(raw, dict) or (raw.get("item_id"), raw.get("fact_id")) not in known:
            if isinstance(raw, dict):
                result["rejected"].append({"text": str(raw.get("fact_id", "")), "reason": "unknown_correction_target"})
            continue
        replacement = validated(raw.get("replacement"))
        if replacement:
            result["corrections"].append({"item_id": raw["item_id"], "fact_id": raw["fact_id"], "replacement": replacement})
    for raw in candidate.get("removals", []) if isinstance(candidate.get("removals"), list) else []:
        if isinstance(raw, dict) and (raw.get("item_id"), raw.get("fact_id")) in known:
            result["removals"].append({"item_id": raw["item_id"], "fact_id": raw["fact_id"]})
        elif isinstance(raw, dict):
            result["rejected"].append({"text": str(raw.get("fact_id", "")), "reason": "unknown_removal_target"})
    basic = candidate.get("basic_info")
    if isinstance(basic, dict):
        for key, value in basic.items():
            if key in {"name", "phone", "email", "location", "city", "github", "objective"} and isinstance(value, str) and value.strip() and normalize_text(value) in normalize_text(evidence) and not _quote_has_unquoted_limit(evidence, value):
                result["basic_info"][key] = value.strip()
    skills = candidate.get("skills")
    if isinstance(skills, list):
        for value in skills:
            name = value if isinstance(value, str) else value.get("name") if isinstance(value, dict) else ""
            quote = value.get("source_quote", name) if isinstance(value, dict) else name
            if name and quote and normalize_text(quote) in normalize_text(evidence) and normalize_text(name) in normalize_text(quote) and _skill_affirmed(evidence, name) and not lexical_fact_errors(name, quote):
                result["skills"].append({"name": name, "source_quote": quote, "source": "chat", "turn_id": turn_id})
    if semantic_pairs:
        try:
            checker = semantic_check or (lambda pairs: verify_semantics(pairs, llm))
            verdicts = checker(semantic_pairs)
            if inspect.isawaitable(verdicts):
                verdicts = await verdicts
        except Exception:
            verdicts = {}
        failed = {fact["id"] for fact in pending
                  if not isinstance(verdicts, dict) or verdicts.get(fact["id"], {}).get("verdict") != "pass"}
        result["rejected"].extend({"text": fact["text"], "reason": "semantic_verification_failed"}
                                  for fact in pending if fact["id"] in failed)
        for item in result["items"]:
            item["facts"] = [fact for fact in item["facts"] if fact["id"] not in failed]
        result["items"] = [item for item in result["items"] if item["facts"] or item["raw_notes"]]
        result["corrections"] = [entry for entry in result["corrections"] if entry["replacement"]["id"] not in failed]
    for item in result["items"]:
        item["raw_notes"].extend(fact["source_quote"] for fact in item["facts"]
                                 if fact["source_quote"] not in item["raw_notes"])
    result["items"] = [item for item in result["items"] if item["facts"] or item["raw_notes"]]
    return result


def apply_fact_patch(collected: dict, patch: dict) -> dict:
    """Apply validated sparse patch; previous facts remain available for audit."""
    result = normalize_fact_store(collected)
    result.setdefault("basic_info", {}).update(copy.deepcopy(patch.get("basic_info") or {}))
    skills = result.setdefault("skills", [])
    for skill in patch.get("skills") or []:
        if isinstance(skill, dict) and skill.get("name") and not any(
            isinstance(old, dict) and old.get("name", "").casefold() == skill["name"].casefold() for old in skills
        ):
            skills.append(copy.deepcopy(skill))
    by_id = {item.get("item_id"): item for section in FACT_SECTIONS
             for item in result.get(section, []) if isinstance(item, dict)}
    for entry in patch.get("items") or []:
        section, item_id = entry.get("section"), entry.get("item_id")
        if section not in FACT_SECTIONS or not item_id:
            continue
        item = by_id.get(item_id)
        if item is None:
            label = {"projects": "name", "education": "school", "internship": "company", "work_experience": "company"}[section]
            item = {"item_id": item_id, label: entry.get("name", ""), "facts": [], "raw_notes": []}
            result.setdefault(section, []).append(item)
            by_id[item_id] = item
        existing = {fact.get("id") for fact in item.setdefault("facts", [])}
        item["facts"].extend(copy.deepcopy(fact) for fact in entry.get("facts", []) if fact.get("id") not in existing)
        notes = item.setdefault("raw_notes", [])
        notes.extend(note for note in entry.get("raw_notes", []) if note not in notes)
    for entry in patch.get("corrections") or []:
        item = by_id.get(entry.get("item_id"))
        if item is None:
            continue
        old = next((fact for fact in item["facts"] if fact.get("id") == entry.get("fact_id") and fact.get("status") == "active"), None)
        if old and isinstance(entry.get("replacement"), dict):
            old["status"] = "superseded"
            replacement = copy.deepcopy(entry["replacement"])
            replacement["replaces"] = old["id"]
            item["facts"].append(replacement)
            quote = replacement.get("source_quote")
            if quote and quote not in item.setdefault("raw_notes", []):
                item["raw_notes"].append(quote)
    for entry in patch.get("removals") or []:
        item = by_id.get(entry.get("item_id"))
        if item:
            for fact in item["facts"]:
                if fact.get("id") == entry.get("fact_id"):
                    fact["status"] = "deleted"
    return result
