"""用户在编辑指令里点名要写进/突出的内容：事实库回补 + 回执核对。

只做确定性判断（不调用模型）：
- named_terms：从指令里抽取「突出 X」「X 也写上」里的 X；
- recover_named_facts：事实库没有、但 raw_notes / 历史原话里有时，用该子句原文补一条保守事实；
- named_content_rows：改写/调整重点的 ✅ 必须在目标条目里真的出现点名内容，否则降为 ⚠。
"""
from __future__ import annotations

import re

from app.schemas.facts import FACT_SECTIONS

_SEGMENT = re.compile(r"[，,。；;！!\n]+")
_EMPHASIS = re.compile(
    r"(?:突出|强调|主打|着重(?:写|突出)?|重点(?:写|突出|放|讲)?|体现|多写|多讲|多说|展开写|写出)(?:一下|下)?(.+)$")
_ADD = re.compile(
    r"^(.+?)(?:也|还|都)?(?:要|得|需要|请)?(?:写上|写进去|写进|写入|加上|加进去|加入|补上|补进去|放上|放进去|带上|写出来|提一下)")
_LIST_SPLIT = re.compile(r"和|与|以及|及|、|还有|并且")
_LEADING = re.compile(r"^(?:把|将|再|还|也|要|我的|我们的|我|请|帮我|一下|下)+")
_VERB_LEAD = re.compile(r"^(?:解决了?|做了?|搞定?|完成了?|负责了?|处理了?)(?!的)")
_TRAILING = re.compile(r"(?:(?:那|这)(?:一)?(?:块|部分|方面|点|段|些)|的?(?:内容|经历|部分|方面))$")
_GENERIC = {
    "亮点", "重点", "技术", "细节", "技术细节", "成果", "能力", "经历", "项目", "内容", "优势", "核心", "价值",
    "数据", "结果", "贡献", "简历", "岗位", "jd", "全部", "所有", "这个", "那个", "它", "这些", "那些", "详细",
    "具体", "更多", "相关经历", "相关内容", "关键词", "匹配", "成绩", "表现",
}
_FIELD_WORDS = re.compile(r"学校|专业|学历|姓名|电话|邮箱|求职意向|自我评价|总结|页|模板|字体|排版|技能栏|教育")

# 点名词在事实/正文里可能换了说法（口语 -> 书面）。同义组内任一出现即视为出现。
SYNONYMS = {
    "幻觉": ("幻觉", "不存在", "虚构", "编造", "凭空", "瞎推荐", "不实"),
    "抖音": ("抖音",),
}


def _fold(text) -> str:
    return re.sub(r"\s+", "", str(text or "")).casefold()


def _variants(term: str) -> tuple[str, ...]:
    folded = _fold(term)
    values = {folded}
    for key, group in SYNONYMS.items():
        if key in folded:
            values.update(_fold(item) for item in group)
    return tuple(sorted(values))


def term_present(term: str, text: str) -> bool:
    """点名词是否出现在文本里。含英文词的复合词（agent 设计）以英文部分为准；其余按字面或同义词。"""
    haystack = _fold(text)
    folded = _fold(term)
    if folded in haystack or any(v and v in haystack for v in _variants(term)):
        return True
    ascii_part = re.findall(r"[a-z][a-z0-9._+-]{1,}", folded)
    cjk_part = re.sub(r"[a-z0-9._+\- ]+", "", folded)
    return bool(ascii_part) and bool(cjk_part) and all(token in haystack for token in ascii_part)


def _clean(term: str, labels: list[str]) -> str:
    value = term.strip(" 　的了吧啊呀")
    for label in sorted(labels, key=len, reverse=True):
        if label:
            value = re.sub(re.escape(label), "", value, flags=re.I)
    previous = None
    while previous != value:
        previous = value
        value = _LEADING.sub("", value)
        value = _VERB_LEAD.sub("", value)
        value = _TRAILING.sub("", value)
        value = value.strip(" 　的了吧啊呀")
    return value


def _only_generic(term: str) -> bool:
    rest = _fold(term)
    for word in sorted(_GENERIC, key=len, reverse=True):
        rest = rest.replace(word, "")
    return len(rest) < 2


def named_terms(message: str, labels: list[str] | None = None) -> list[dict]:
    """[{term, label}]：label 是同一子句里点名的条目名（可为空）。"""
    labels = [str(l) for l in labels or [] if l]
    found: list[dict] = []
    for segment in _SEGMENT.split(message or ""):
        segment = segment.strip()
        if not segment:
            continue
        label = next((l for l in sorted(labels, key=len, reverse=True) if l.casefold() in segment.casefold()), "")
        pieces: list[str] = []
        if (match := _EMPHASIS.search(segment)):
            pieces = _LIST_SPLIT.split(match.group(1))
        elif (match := _ADD.search(segment)):
            pieces = _LIST_SPLIT.split(match.group(1))
        for piece in pieces:
            term = _clean(piece, labels)
            if (len(term) < 2 or _only_generic(term) or _FIELD_WORDS.search(term)
                    or any(_fold(term) == _fold(l) for l in labels)):
                continue
            if not any(row["term"] == term for row in found):
                found.append({"term": term, "label": label})
    return found


def item_text(item: dict) -> str:
    parts = []
    for key in ("polished_bullets", "bullets", "highlights"):
        value = item.get(key)
        if isinstance(value, list):
            parts.extend(str(v.get("text", "")) if isinstance(v, dict) else str(v) for v in value)
    for key in ("description", "summary", "subtitle"):
        if isinstance(item.get(key), str):
            parts.append(item[key])
    return "\n".join(parts)


def _experience_items(document: dict):
    for section in ("projects", "work_experience", "internship", "campus"):
        for item in (document or {}).get(section) or []:
            if isinstance(item, dict) and not item.get("hidden"):
                yield item


def item_label(item: dict) -> str:
    return str(item.get("name") or item.get("company") or "")


def _fact_corpus(item: dict) -> str:
    rows = [f"{f.get('text', '')} {f.get('source_quote', '')}" for f in item.get("facts") or []
            if isinstance(f, dict) and f.get("status", "active") == "active"]
    return "\n".join(rows)


def term_in_facts(collected: dict, term: str) -> bool:
    for section in FACT_SECTIONS:
        for item in (collected or {}).get(section) or []:
            if isinstance(item, dict) and term_present(term, _fact_corpus(item)):
                return True
    return False


def _clause_with(term: str, text: str) -> str:
    for clause in re.split(r"[，,。；;！!？?\n]+", text or ""):
        if term_present(term, clause) and len(clause.strip()) >= 4:
            return clause.strip()
    return ""


def recover_named_facts(message: str, collected: dict, history: list[str], labels: list[str]) -> tuple[dict, list[str]]:
    """点名内容不在事实库时，从 raw_notes / 历史原话里取含该词的子句原文补一条保守事实。

    返回 (新的 collected, 已回补的词)。取不到的词不处理，由回执报「没有记录到」。"""
    import copy
    from app.agents.fact_extractor import _fact_kind_for_clause, _quote_has_unquoted_limit, _third_person
    from app.services.fact_guard import lexical_fact_errors
    from app.services.resume_facts import new_fact

    result = copy.deepcopy(collected or {})
    recovered: list[str] = []
    for row in named_terms(message, labels):
        term = row["term"]
        if term_in_facts(result, term):
            continue
        owner, clause = None, ""
        for section in ("projects", "work_experience", "internship", "campus"):
            for item in result.get(section) or []:
                if not isinstance(item, dict):
                    continue
                for note in item.get("raw_notes") or []:
                    if (found := _clause_with(term, note)):
                        owner, clause = item, found
                        break
                if owner:
                    break
            if owner:
                break
        if owner is None:
            for text in reversed(history):
                if (found := _clause_with(term, text)):
                    owner = _owner_by_position(result, text, found)
                    clause = found
                    break
        if owner is None or not clause or lexical_fact_errors(clause, clause) or _quote_has_unquoted_limit(clause, clause):
            continue
        owner.setdefault("facts", []).append(new_fact(_third_person(clause), kind=_fact_kind_for_clause(clause), quote=clause, source="chat"))
        notes = owner.setdefault("raw_notes", [])
        if clause not in notes:
            notes.append(clause)
        recovered.append(term)
    return result, recovered


def _owner_by_position(collected: dict, text: str, clause: str):
    """历史原话里 clause 之前最近出现名字的经历。"""
    start = text.find(clause)
    best, best_pos = None, -1
    for section in ("projects", "work_experience", "internship", "campus"):
        for item in collected.get(section) or []:
            label = item_label(item) if isinstance(item, dict) else ""
            pos = text.casefold().rfind(label.casefold(), 0, start + len(clause)) if label else -1
            if pos > best_pos:
                best, best_pos = item, pos
    return best


def _find(document: dict, item_id: str):
    return next((i for i in _experience_items(document) if i.get("item_id") == item_id), None)


def named_content_rows(message: str, rows: list[dict], before: dict, after: dict, collected: dict) -> list[dict]:
    """改写/调整重点的 ✅ 需要点名内容真的出现在目标条目里；否则改成 ⚠ 并说明缺什么。"""
    labels = [item_label(i) for i in _experience_items(after)] + [item_label(i) for i in _experience_items(before)]
    terms = named_terms(message, labels)
    if not terms:
        return rows
    after_items = list(_experience_items(after))
    corpus = {item.get("item_id"): _fact_corpus(item) for section in ("projects", "work_experience", "internship", "campus")
              for item in (collected or {}).get(section) or [] if isinstance(item, dict)}
    output = [dict(r) for r in rows]
    extra: list[dict] = []
    for entry in terms:
        term, label = entry["term"], entry["label"]
        scoped = [i for i in after_items if label and label.casefold() == item_label(i).casefold()]
        pool = scoped or after_items
        if any(term_present(term, item_text(i)) for i in pool):
            continue
        holder = next((i for i in pool if term_present(term, corpus.get(i.get("item_id"), ""))), None)
        if holder is None:
            holder = next((i for i in after_items if term_present(term, corpus.get(i.get("item_id"), ""))), None)
        name = item_label(holder) if holder else label
        if holder is None and not term_in_facts(collected, term):
            reason = f"我没有记录到「{term}」，能再说一下吗"
        else:
            reason = f"「{term}」在事实库里有，但这版没有写进去，没能完成"
        target = holder or (scoped[0] if scoped else None)
        target_id = target.get("item_id") if target else ""
        converted = False
        for row in output:
            if (row.get("op") in {"rewrite", "refocus"} and row.get("status") == "done"
                    and target_id and target_id in (row.get("affected_item_ids") or [])
                    and (row.get("changed") or _find(before, target_id) != _find(after, target_id))):
                row.update(op="named_gap", target=name or row.get("target"), status="needs_detail", reason=reason, changed=False)
                converted = True
                break
        if not converted:
            extra.append({"op": "named_gap", "target": name or term, "status": "needs_detail",
                          "reason": reason, "changed": False, "affected_item_ids": [target_id] if target_id else []})
    return output + extra
