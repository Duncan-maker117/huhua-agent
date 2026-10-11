"""Extract sparse, source-checked changes to the candidate fact master."""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import logging
import os
import re
import uuid

from app.schemas.facts import FACT_SECTIONS
from app.services.llm_compat import label_run, without_thinking
from app.services.resume_facts import new_fact, normalize_fact_store

logger = logging.getLogger(__name__)

_CONTRACT = """从候选人本轮消息抽取简历事实，只输出 JSON patch：
{"items":[{"section":"projects|work_experience|internship|education","item_id":"已有ID或空","name":"经历名","facts":[{"kind":"role|action|method_tool|deliverable|result_metric|result_qualitative|scope_scale|status_limit|context|team","text":"规范化陈述","source_quote":"本轮连续原文"}],"raw_notes":["本轮相关原话"]}],"basic_info":{},"skills":[],"corrections":[{"item_id":"","fact_id":"","replacement":{"kind":"","text":"","source_quote":""}}],"removals":[{"item_id":"","fact_id":""}]}。
口语可转书面，但不能新增数字、动作、职责、成果或工具；否定、计划、Demo、未上线必须保留。归属已有经历须用已有 item_id。
更正旧事实用 corrections，删除事实用 removals；删除文稿的句子不等于删除事实。
JD、示例、助手建议、计划要做的事情不能变成已完成事实。metadata_context 和 previous_assistant 只帮助理解短答和冲突，不是正文事实；source_quote 只能来自 message。
教育信息（学校、专业、学历、年级）归 education，不要建成项目。学校简称保持原词，不要自行扩写成全称。
半句话中已经说清的团队规模、本人分工等分别抽取；未完成的尾巴不影响前面的事实，不猜缺失内容。
不要返回整份 collected_info，不要添加未知字段。"""


def split_incomplete_tail(message: str) -> tuple[str, str]:
    if not isinstance(message, str):
        return message, ""
    match = re.search(r"(?:分别是|分别为|包括|例如|比如)[：:，,。.!！?？\s]*$", message or "")
    if not match:
        return message, ""
    return message[:match.start()].rstrip("：:，,。；; \t\n"), match.group().strip("：:，,。.!！?？ \t\n")


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


# ── 抽取覆盖检查：动作/结果类子句不得被静默丢弃 ─────────────────────────────
_CLAUSE_SPLIT = re.compile(r"[，,。；;！!？?：:\n、]+")
_ACTION_VERB = re.compile(
    r"做|写|搭|开发|设计|实现|改成|改为|改|优化|发了|发布|发|推广|查|修|解决|提升|降低|增加|减少|完成|负责|带|用|调|"
    r"训练|部署|上线|测试|分析|整理|蒸馏|获得|拿到|拿了|star|推荐|挑|接入|重构|迁移|爬|抓|标注|评估|对接|拆|统计|获奖|参与|主导|协助|组织|运营")
_NARRATIVE = re.compile(r"我|本人|后来|一开始|起初|最初|之后|最后|最终|现在|还|已经|做过|做的|写的|搭的|\d")
_INSTRUCTION = re.compile(
    r"帮我|给我|请|突出|按JD|按岗位|改改|改一下|写详细|写上|写进|也写|删掉|去掉|精简|压缩|调整|优化一下|换成|"
    r"能不能|可以吗|是否|要不要|吗|全称|出一版|生成|撤销|导出", re.I)
_PLAN_OR_NEGATED = re.compile(r"我(?:们)?(?:将|从未|并未|还?没有?|未|不曾|不)|计划|准备|打算|希望|想要|下个月|以后|将来|明天|还没")
_STATUS_CLAUSE = re.compile(r"开源|未上线|没上线|Demo|原型", re.I)
_RESULT_CLAUSE = re.compile(r"star|用户|提升|增长|降低|增加|减少|获奖|名|第一|\d", re.I)


def _fact_kind_for_clause(clause: str) -> str:
    """规则判定 kind，不调用模型。"""
    if _STATUS_CLAUSE.search(clause):
        return "status_limit"
    if re.search(r"[一二两三四五六七八九十\d]+(?:个)?人(?:的)?(?:团队|小组)", clause):
        return "team"
    if _RESULT_CLAUSE.search(clause) and re.search(r"\d", clause):
        return "result_metric"
    if re.search(r"提升|增长|降低|减少|获奖", clause):
        return "result_qualitative"
    if _ACTION_VERB.search(clause):
        return "action"
    return "context"


def _bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)} or ({text} if text else set())


def _clause_covered(clause: str, quotes: list[str], whole: str = "") -> bool:
    grams = _bigrams(clause)
    for quote in quotes:
        if not quote:
            continue
        if clause in quote or quote in clause:
            return True
        if grams and len(grams & _bigrams(quote)) / len(grams) >= 0.7:
            return True
    # 子句里的动作词全部落在某条已接受事实的原文片段内，也算覆盖（事实只引了子句的后半段）。
    start = whole.find(clause) if whole else -1
    verbs = [(start + m.start(), start + m.end()) for m in _ACTION_VERB.finditer(clause)] if start >= 0 else []
    spans = []
    for quote in quotes:
        at = whole.find(quote) if quote and whole else -1
        if at >= 0:
            spans.append((at, at + len(quote)))
    return bool(verbs) and all(any(a >= lo and b <= hi for lo, hi in spans) for a, b in verbs)


def uncovered_action_clauses(evidence: str, quotes: list[str]) -> list[str]:
    """候选人原话中含动作/结果类动词、却没有对应已接受事实的子句（保持原文）。"""
    from app.services.fact_guard import normalize_text
    complete, tail = split_incomplete_tail(evidence)
    normalized = [normalize_text(q) for q in quotes]
    whole = normalize_text(complete)
    rows = []
    clauses = _CLAUSE_SPLIT.split(complete)
    if tail:
        clauses = [part for clause in clauses for part in re.split(r"\s+(?=有一个|我|本人|还有一个)", clause)]
    for raw in clauses:
        clause = raw.strip()
        if len(clause) < 6 or _INSTRUCTION.search(clause) or _PLAN_OR_NEGATED.search(clause) or re.fullmatch(r"(?:我)?(?:还)?做过.{0,6}(?:东西|项目|事情?)", clause):
            continue
        team = tail and re.search(r"[一二两三四五六七八九十\d]+(?:个)?人(?:的)?(?:团队|小组)", clause)
        if not (team or (_ACTION_VERB.search(clause) and _NARRATIVE.search(clause))):
            continue
        if _clause_covered(normalize_text(clause), normalized, whole):
            continue
        if clause not in rows:
            rows.append(clause)
    return rows


def _reason_code(reason) -> str:
    if isinstance(reason, list):
        return ",".join(str(r) for r in reason[:3])
    return str(reason)


def _log_rejected(rejected: list[dict], turn_id: str) -> None:
    """只记错误码与 hash；benchmark（合成数据）设置 HUHUA_RECORD_REJECTED_TEXT=1 时记原文。"""
    record_text = os.environ.get("HUHUA_RECORD_REJECTED_TEXT") == "1"
    for row in rejected:
        digest = hashlib.sha256(str(row.get("text", "")).encode("utf-8")).hexdigest()[:10]
        extra = f" text={row.get('text')!r}" if record_text else ""
        logger.info("fact_rejected turn=%s code=%s hash=%s%s", turn_id or "-", _reason_code(row.get("reason")), digest, extra)


async def extract_facts_patch(message: str, collected: dict, llm, *, turn_id: str = "",
                              metadata_context=None, semantic_check=None,
                              previous_assistant: str = "") -> dict:
    """Reject individual unsupported facts while retaining the rest of a patch."""
    from app.services.fact_guard import lexical_fact_errors, normalize_text, verify_semantics

    complete, tail = split_incomplete_tail(message)
    empty = {"items": [], "basic_info": {}, "skills": [], "corrections": [], "removals": [], "rejected": [], "uncovered": [],
             "incomplete": [tail] if tail else []}
    if not isinstance(message, str) or not message.strip() or llm is None:
        return empty
    visible = normalize_fact_store(collected)
    outline = [{"section": section, "item_id": item.get("item_id"),
                "name": item.get("name") or item.get("company") or item.get("school") or "",
                "facts": [{"id": f.get("id"), "text": f.get("text")}
                          for f in item.get("facts", []) if f.get("status") == "active"]}
               for section in FACT_SECTIONS for item in visible.get(section, []) if isinstance(item, dict)]
    payload = {"message": complete, "existing": outline, "metadata_context": metadata_context or [],
               "previous_assistant": (previous_assistant or "")[:500]}
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from app.services.model_privacy import ContactRedactor, redact_model_messages
        privacy = ContactRedactor()
        messages = redact_model_messages([SystemMessage(content=_CONTRACT),
                                          HumanMessage(content=json.dumps(payload, ensure_ascii=False))], privacy)
        from app.config import get_settings
        model = llm if getattr(get_settings(), "LLM_EXTRACTOR_THINKING", True) else without_thinking(llm)
        response = await label_run(model, "fact_extractor").ainvoke(messages)
        candidate = privacy.restore(_content(response))
    except Exception:
        return empty
    if not isinstance(candidate, dict):
        return empty
    result = copy.deepcopy(empty)
    evidence = _candidate_evidence(complete)
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
            checker = semantic_check or (lambda pairs: verify_semantics(pairs, llm, run_name="extract_verify"))
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
    if tail and not result["items"] and not re.search(r"新项目|另一个项目|另外一个项目", evidence):
        owners = [item for item in outline if item["section"] in {"projects", "work_experience", "internship"}
                  and item["name"] and (item["name"] in evidence or (
                      item["name"] in previous_assistant and re.search(r"团队|分工|负责|几人|人数", previous_assistant)))]
        if len(owners) == 1:
            owner = owners[0]
            result["items"].append({"section": owner["section"], "item_id": owner["item_id"],
                                    "name": owner["name"], "facts": [], "raw_notes": [evidence]})
    coverage_evidence = evidence + (" " + tail if tail else "")
    _cover_dropped_clauses(result, coverage_evidence, turn_id, lexical_fact_errors, normalize_text)
    for item in result["items"]:
        item["raw_notes"].extend(fact["source_quote"] for fact in item["facts"]
                                 if fact["source_quote"] not in item["raw_notes"])
    result["items"] = [item for item in result["items"] if item["facts"] or item["raw_notes"]]
    _log_rejected(result["rejected"], turn_id)
    return result


def _cover_dropped_clauses(result: dict, evidence: str, turn_id: str, lexical_fact_errors, normalize_text) -> None:
    """未被任何已接受事实覆盖的动作/结果子句：用子句原文作保守事实重试，仍不行则记入 uncovered。"""
    quotes = [fact["source_quote"] for item in result["items"] for fact in item["facts"]]
    quotes += [entry["replacement"]["source_quote"] for entry in result["corrections"]]
    for clause in uncovered_action_clauses(evidence, quotes):
        owner = _owner_item(result["items"], clause, evidence, normalize_text)
        errors = lexical_fact_errors(clause, clause) if owner is not None else ["no_owner_item"]
        if owner is None or errors or _quote_has_unquoted_limit(evidence, clause):
            result["rejected"].append({"text": clause, "reason": "coverage_fallback_failed:" + _reason_code(errors or "limit")})
            result["uncovered"].append(clause)
            continue
        owner["facts"].append(new_fact(_third_person(clause), kind=_fact_kind_for_clause(clause), quote=clause,
                                       source="chat", turn_id=turn_id))
        logger.info("fact_coverage_fallback turn=%s hash=%s", turn_id or "-",
                    hashlib.sha256(clause.encode("utf-8")).hexdigest()[:10])


def _third_person(clause: str) -> str:
    """去掉句首的「我(还/也)」口语主语，其余原文不动（不新增信息）；去完为空则保持原句。"""
    cleaned = re.sub(r"^(.{0,3}?)我(?:还|也|又|就)?", r"\1", clause, count=1).strip()
    return cleaned if len(cleaned) >= 4 else clause


def _owner_item(items: list[dict], clause: str, evidence: str, normalize_text):
    """子句归属：同一句（按句号切分）里已有事实/raw_notes 的经历；跨句不猜归属。"""
    wanted = normalize_text(clause)
    sentence = next((part for part in re.split(r"(?<=[。！？!?\n])", evidence) if clause in part), "")
    sentence_norm = normalize_text(sentence)
    candidates = [item for item in items if item["section"] in {"projects", "work_experience", "internship"}]
    for item in candidates:
        if any(wanted in normalize_text(note) for note in item.get("raw_notes", [])):
            return item
    start = sentence.find(clause)
    best, best_end = None, -1
    for item in candidates:
        for fact in item["facts"]:
            pos = sentence.find(fact["source_quote"]) if sentence else -1
            if 0 <= pos <= start and pos > best_end and normalize_text(fact["source_quote"]) in sentence_norm:
                best, best_end = item, pos
    if best is None and split_incomplete_tail(evidence)[1]:
        same_sentence = [item for item in candidates if any(
            normalize_text(fact["source_quote"]) in sentence_norm for fact in item["facts"])]
        if len(same_sentence) == 1:
            return same_sentence[0]
    return best


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
