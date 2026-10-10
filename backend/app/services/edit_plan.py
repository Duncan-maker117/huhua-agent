"""Execute the reversible, deterministic part of a compound resume edit."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping, Sequence
import unicodedata

from app.services.resume_capacity import normalize_session_constraints
from app.services.resume_facts import active_facts_for_writer
from app.services.resume_sections import DEFAULT_SECTIONS


ITEM_SECTIONS = ("projects", "work_experience", "education")
WRITER_OPS = {"rewrite", "compress", "refocus"}
SECTION_ALIASES = {"项目": "projects", "项目经历": "projects", "projects": "projects",
                   "工作": "work_experience", "经历": "work_experience", "实习": "work_experience",
                   "工作经历": "work_experience", "实习经历": "work_experience",
                   "work_experience": "work_experience", "教育": "education", "教育背景": "education",
                   "education": "education", "技能": "skills", "技能证书": "skills", "skills": "skills",
                   "证书": "certificates", "certificates": "certificates",
                   "自我评价": "self_evaluation", "个人总结": "self_evaluation",
                   "self_evaluation": "self_evaluation"}
BASIC_FIELDS = {"name", "phone", "email", "location", "objective", "gender", "age", "birthday",
                "hometown", "political", "ethnicity", "height"}
HEADER_FIELDS = {"projects": {"name", "role", "start_date", "end_date"},
                 "work_experience": {"company", "title", "start_date", "end_date"},
                 "education": {"school", "degree", "major", "start_date", "end_date"}}
FIELD_LABELS = {"name": ("姓名",), "phone": ("电话", "手机号"), "email": ("邮箱",),
                "location": ("地点", "所在地", "城市"), "objective": ("求职意向", "目标岗位"),
                "role": ("角色", "职责"), "title": ("职位", "岗位"),
                "start_date": ("开始时间", "起始时间", "日期"),
                "end_date": ("结束时间", "截止时间", "日期")}
_ORDINAL = re.compile(r"第([一二两三四五六七八九十\d]+)(?:个|段|条)?(项目|经历|工作|实习|教育)")
_ITEM_POINTER = re.compile(r"^/(projects|work_experience|education)/(\d+)(?:/([^/]+)(?:/(\d+))?)?$")
_MARKDOWN_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")


def _fold(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or ""))).casefold()


def _literal_in(value: str, instruction: str) -> bool:
    return bool(value) and _fold(value) in _fold(instruction)


def _ordinal_value(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    return digits.get(value)


def _items(data: dict, section: str) -> list[tuple[str, int, dict]]:
    return [(section, index, item) for index, item in enumerate(data.get(section) or [])
            if isinstance(item, dict)]


def _label(item: dict) -> str:
    return str(item.get("name") or item.get("company") or item.get("school") or "")


def _fuzzy_name(target: str, item: dict) -> bool:
    from app.agents.turn_actions import name_matches
    return name_matches(target, _label(item))


def _resolve_items(data: dict, target: str, *, section_hint: str = "") -> tuple[list[tuple[str, int, dict]], str]:
    target = str(target or "").strip()
    if not target:
        return [], "未指定目标"
    if target in SECTION_ALIASES and SECTION_ALIASES[target] in ITEM_SECTIONS:
        section = SECTION_ALIASES[target]
        rows = list(_items(data, section))
        return rows, "" if rows else "该栏目没有可修改的经历"
    pointer = _ITEM_POINTER.fullmatch(target)
    if pointer:
        section, index = pointer[1], int(pointer[2])
        rows = data.get(section) or []
        if index < len(rows) and isinstance(rows[index], dict):
            return [(section, index, rows[index])], ""
        return [], "目标序号超出范围"
    ordinal = _ORDINAL.fullmatch(target)
    if ordinal:
        number = _ordinal_value(ordinal[1])
        section = SECTION_ALIASES[ordinal[2]]
        rows = list(_items(data, section))
        if number is None or number < 1 or number > len(rows):
            return [], "目标序号超出范围"
        return [rows[number - 1]], ""
    sections = [section_hint] if section_hint in ITEM_SECTIONS else ITEM_SECTIONS
    exact = [row for section in sections for row in _items(data, section)
             if target == row[2].get("item_id") or _fold(target) == _fold(_label(row[2]))]
    candidates = exact or [row for section in sections for row in _items(data, section) if _fuzzy_name(target, row[2])]
    if len(candidates) > 1:
        return [], "同名经历不止一条，请指定序号或 item_id"
    return (candidates, "") if candidates else ([], "没有找到指定经历，请给名称或序号")


def _target_mentioned(target: str, rows: Sequence[tuple[str, int, dict]], instruction: str) -> bool:
    if _literal_in(target, instruction):
        return True
    if any(_literal_in(item.get("name") or item.get("company") or item.get("school") or "", instruction)
           for _, _, item in rows):
        return True
    for section, index, _ in rows:
        label = "项目" if section == "projects" else "经历" if section == "work_experience" else "教育"
        for phrase in re.findall(r"第[一二两三四五六七八九十\d]+(?:个|段|条)?(?:项目|经历|工作|实习|教育)", instruction):
            ordinal = _ORDINAL.fullmatch(phrase)
            if ordinal and SECTION_ALIASES[ordinal[2]] == section and _ordinal_value(ordinal[1]) == index + 1:
                return True
        if re.search(rf"(?:第一个|第一段|第1个|第1段){label}", instruction) and index == 0:
            return True
    return False


def _authorized_item_removal(target: str, rows: Sequence[tuple[str, int, dict]], instruction: str) -> bool:
    if len(rows) != 1:
        return False
    if not _target_mentioned(target, rows, instruction):
        return False
    return any(re.search(r"删除|删掉|去掉|移除|隐藏|不展示|不放|不要|误识别|备用", clause)
               and (_literal_in(target, clause) or any(
                   _literal_in(item.get("name") or item.get("company") or item.get("school") or "", clause)
                   for _, _, item in rows) or _ORDINAL.search(clause))
               for clause in re.split(r"[；;。，,\n]", instruction))


def _section_scope_explicit(target: str, instruction: str) -> bool:
    section = SECTION_ALIASES.get(target)
    if section not in ITEM_SECTIONS:
        return False
    labels = {"projects": "项目", "work_experience": "(?:工作|实习|经历)",
              "education": "教育"}
    label = labels[section]
    return bool(re.search(rf"(?:所有|全部|每个|各个|各|[一二两三四五六七八九十\d]+个).{{0,6}}{label}"
                          rf"|{label}.{{0,6}}(?:各|全部|都)", instruction))


def _explicit_clear(field: str, instruction: str) -> bool:
    return any(any(label in clause for label in FIELD_LABELS.get(field, (field,)))
               and re.search(r"删除|清空|移除|去掉", clause)
               for clause in re.split(r"[；;。，,\n]", instruction))


def _result(index: int, op: str, target: str, status: str, reason: str = "", *, changed: bool = False,
            affected: Sequence[str] = (), field: str = "") -> dict:
    row = {"index": index, "op": op, "target": target, "status": status, "reason": reason,
           "changed": changed, "affected_item_ids": list(affected)}
    if field:
        row["field"] = field
    return row


def _active_header_value(collected: dict, section: str, item_id: str, field: str, value: str) -> bool:
    evidence = active_facts_for_writer(collected or {})
    sources = ("work_experience", "internship") if section == "work_experience" else (section,)
    for source_section in sources:
        for item in evidence.get(source_section) or []:
            if item.get("item_id") == item_id and any(
                fact.get("field") == field and _fold(fact.get("text")) == _fold(value)
                for fact in item.get("facts") or []
            ):
                return True
    return False


def _cap_value(args: dict, instruction: str):
    """「最多两条/各两条/两条以内」→ 2。先看模型参数（整数、数字串、中文数字），再看用户原话。"""
    from app.services.fact_guard import _chinese_number
    for key in ("n", "max_bullets", "limit", "max", "count", "max_count"):
        value = args.get(key)
        if type(value) is int:
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip():
            text = value.strip().removesuffix("条").strip()
            if text.isdigit():
                return int(text)
            if re.fullmatch(r"[零〇一二两三四五六七八九十]+", text):
                return _chinese_number(text)
    match = re.search(r"(?:最多|至多|不超过|各|每个[^，。；]{0,6}?|保留)\s*([零一二两三四五六七八九十\d]+)\s*条", instruction or "")
    if match:
        text = match[1]
        return int(text) if text.isdigit() else _chinese_number(text)
    return None


def _number_in_instruction(number: int, instruction: str, unit: str) -> bool:
    variants = {0: ("零",), 1: ("一",), 2: ("二", "两"), 3: ("三",),
                4: ("四",), 5: ("五",)}
    forms = "|".join([str(number), *variants.get(number, ())])
    return bool(re.search(rf"(?:{forms})\s*{unit}", instruction))


def _clean_text(value: str) -> tuple[str, list[dict]]:
    links = []

    def replace(match: re.Match) -> str:
        links.append({"text": match[1], "url": match[2]})
        return match[1]

    result = _MARKDOWN_LINK.sub(replace, value)
    result = re.sub(r"(?m)^\s*(?:#{1,6}\s+|[-*•▸]\s+)", "", result)
    result = re.sub(r"\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`",
                    lambda match: next(group for group in match.groups() if group is not None), result)
    return result, links


def _clean_item(item: dict) -> bool:
    before = deepcopy(item)
    links = list(item.get("links") or [])
    for field in ("name", "company", "school", "role", "title", "description", "highlights"):
        if isinstance(item.get(field), str):
            item[field], found = _clean_text(item[field])
            links.extend(found)
    for field in ("polished_bullets", "bullets"):
        if isinstance(item.get(field), list):
            cleaned = []
            for bullet in item[field]:
                if isinstance(bullet, str):
                    text, found = _clean_text(bullet)
                    cleaned.append(text)
                    links.extend(found)
                else:
                    cleaned.append(bullet)
            item[field] = cleaned
    if links:
        item["links"] = list({(entry.get("text"), entry.get("url")): entry for entry in links
                              if isinstance(entry, dict)}.values())
    return item != before


def _dedupe_skills(data: dict) -> bool:
    before = (deepcopy(data.get("skills")), deepcopy(data.get("skill_groups")))

    def unique(values: list, seen: set[str]) -> list:
        result = []
        for value in values:
            key = _fold(value.get("name", "") if isinstance(value, dict) else str(value))
            if key and key not in seen:
                seen.add(key)
                result.append(value)
        return result

    groups = data.get("skill_groups")
    if isinstance(groups, dict) and groups:
        group_seen: set[str] = set()
        data["skill_groups"] = {name: unique(list(values), group_seen) for name, values in groups.items()
                                if isinstance(values, list)}
    if isinstance(data.get("skills"), list):
        data["skills"] = unique(data["skills"], set())
    from app.services.skill_groups import sync_flat_skills
    sync_flat_skills(data)
    return before != (data.get("skills"), data.get("skill_groups"))


def _constraint_overrides(args: dict, instruction: str) -> tuple[dict, str]:
    allowed = {key: args[key] for key in ("page_limit", "language", "template_id") if key in args}
    if not allowed:
        return {}, "没有可设置的约束"
    if "page_limit" in allowed and not _number_in_instruction(allowed["page_limit"], instruction, "页"):
        return {}, "页数没有出现在本轮用户原话中"
    if "language" in allowed:
        word = "英文" if str(allowed["language"]).lower().startswith("en") else "中文"
        if word not in instruction and not _literal_in(str(allowed["language"]), instruction):
            return {}, "语言没有出现在本轮用户原话中"
    if "template_id" in allowed and not _literal_in(str(allowed["template_id"]), instruction):
        return {}, "模板编号没有出现在本轮用户原话中"
    return allowed, ""


def execute_edit_plan(
    data: dict, constraints: Mapping[str, Any] | None, edit_plan: Sequence[dict], *,
    collected_info: dict | None = None, instruction: str = "",
) -> dict:
    """Apply deterministic ops on copies and batch resolvable writer ops.

    Each result is independent. Unresolved targets ask only about their own op;
    no model-provided set_field value is accepted without literal user evidence.
    """
    output = deepcopy(data or {})
    original = deepcopy(output)
    limits = normalize_session_constraints(constraints)
    original_facts = deepcopy(collected_info or {})
    results = []
    writer_targets: list[tuple[str, str]] = []
    writer_whole = False
    for index, raw in enumerate(edit_plan or []):
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        if not isinstance(raw, dict):
            results.append(_result(index, "", "", "cannot", "操作格式不正确"))
            continue
        op = str(raw.get("op") or "")
        target = str(raw.get("target") or "")
        args = raw.get("args") if isinstance(raw.get("args"), dict) else {}
        if op == "clean_format" and SECTION_ALIASES.get(target) == "skills":
            if not re.search(r"技能.{0,8}(?:重复|精简|去重|整理)|(?:重复|精简|去重|整理).{0,8}技能", instruction):
                results.append(_result(index, op, target, "needs_confirmation", "未明确要求整理技能栏目"))
                continue
            changed = _dedupe_skills(output)
            results.append(_result(index, op, target, "done", "" if changed else "already_satisfied",
                                   changed=changed))
            continue
        if op in ("delete_item", "hide_item", "cap_bullets", "clean_format", *WRITER_OPS):
            if op in WRITER_OPS and target == "whole":
                writer_whole = True
                results.append(_result(index, op, target, "done"))
                continue
            lookup = original if _ORDINAL.fullmatch(target) else output
            rows, error = _resolve_items(lookup, target, section_hint=str(args.get("section") or ""))
            if error:
                if (op in ("delete_item", "hide_item") and error.startswith("没有找到指定经历")
                        and _literal_in(target, instruction)
                        and any(target and target in str(value) for value in (output.get("basic_info") or {}).values())):
                    # 目标已不在文稿里，且作为基本信息（如所在地）保留：用户目的已达成
                    results.append(_result(index, op, target, "done", "already_satisfied", changed=False))
                    continue
                results.append(_result(index, op, target, "needs_confirmation", error))
                continue
            if lookup is original:
                rows = [(section, item_index, output[section][item_index])
                        for section, item_index, _ in rows]
            affected = [row[2].get("item_id", "") for row in rows]
            if target in SECTION_ALIASES and len(rows) > 1 and op not in ("delete_item", "hide_item") \
                    and not _section_scope_explicit(target, instruction):
                results.append(_result(index, op, target, "needs_confirmation", "未明确要求修改该栏目内的全部经历"))
                continue
            if op in ("delete_item", "hide_item"):
                if not _authorized_item_removal(target, rows, instruction):
                    results.append(_result(index, op, target, "needs_confirmation", "删除或隐藏目标未在本轮指令中明确指认"))
                    continue
                changed = any(row[2].get("hidden") is not True for row in rows)
                for _, _, item in rows:
                    item["hidden"] = True
                results.append(_result(index, op, target, "done", "" if changed else "already_satisfied",
                                       changed=changed, affected=affected))
            elif op == "cap_bullets":
                n = _cap_value(args, instruction)
                if type(n) is not int or not 0 <= n <= 5:
                    results.append(_result(index, op, target, "cannot", "条数必须是 0 到 5 的整数"))
                    continue
                if not _number_in_instruction(n, instruction, "条"):
                    results.append(_result(index, op, target, "cannot", "条数没有出现在本轮用户原话中"))
                    continue
                changed = False
                for section, _, item in rows:
                    field = "polished_bullets" if section == "projects" else "bullets" if section == "work_experience" else ""
                    if not field:
                        continue
                    if field and isinstance(item.get(field), list) and len(item[field]) > n:
                        item[field] = item[field][:n]
                        changed = True
                results.append(_result(index, op, target, "done", "" if changed else "already_satisfied",
                                       changed=changed, affected=affected))
            elif op == "clean_format":
                if target not in SECTION_ALIASES and not _target_mentioned(target, rows, instruction):
                    results.append(_result(index, op, target, "needs_confirmation", "格式清理目标未在本轮指令中明确指认"))
                    continue
                changed = False
                for _, _, item in rows:
                    changed = _clean_item(item) or changed
                results.append(_result(index, op, target, "done", "" if changed else "already_satisfied",
                                       changed=changed, affected=affected))
            else:
                pointer = _ITEM_POINTER.fullmatch(target)
                if pointer and pointer[3] in {"polished_bullets", "bullets"} and pointer[4] is not None:
                    section, item_index, field, bullet_index = pointer[1], int(pointer[2]), pointer[3], int(pointer[4])
                    expected = "polished_bullets" if section == "projects" else "bullets"
                    if field != expected or bullet_index >= len(output[section][item_index].get(field) or []):
                        results.append(_result(index, op, target, "needs_confirmation", "目标 bullet 序号超出范围"))
                        continue
                    writer_targets.append(("bullet", target))
                else:
                    writer_targets.extend(("item", item_id) for item_id in affected if item_id)
                results.append(_result(index, op, target, "done", "等待 writer 改写", affected=affected))
            continue
        if op == "set_field":
            pointer = re.fullmatch(r"/basic_info/([^/]+)", target)
            field = str(args.get("field") or (pointer[1] if pointer else ""))
            field = {"学校": "school", "专业": "major", "学历": "degree", "年级": "grade"}.get(field, field)
            value = args.get("value")
            if not isinstance(value, str):
                results.append(_result(index, op, target, "cannot", "字段值必须是文字"))
                continue
            if pointer and field != pointer[1]:
                results.append(_result(index, op, target, "cannot", "字段路径与参数不一致"))
                continue
            if target in ("basic_info", "/basic_info") or pointer:
                if field not in BASIC_FIELDS:
                    results.append(_result(index, op, target, "cannot", "不是可直接修改的基本信息字段"))
                    continue
                clear = not value and _explicit_clear(field, instruction)
                if not (_literal_in(value, instruction) or clear):
                    results.append(_result(index, op, target, "cannot", "值未出现在本轮用户原话中"))
                    continue
                basic = output.setdefault("basic_info", {})
                changed = basic.get(field) != value
                basic[field] = value
                results.append(_result(index, op, target, "done", "" if changed else "already_satisfied",
                                       changed=changed, field=field))
                continue
            item_pointer = _ITEM_POINTER.fullmatch(target)
            if item_pointer and item_pointer[3] and not field:
                field = item_pointer[3]
            if item_pointer and item_pointer[3] and field != item_pointer[3]:
                results.append(_result(index, op, target, "cannot", "字段路径与参数不一致"))
                continue
            rows, error = _resolve_items(output, target)
            if error:
                results.append(_result(index, op, target, "needs_confirmation", error))
                continue
            section, _, item = rows[0]
            if len(rows) != 1 or field not in HEADER_FIELDS.get(section, set()):
                results.append(_result(index, op, target, "cannot", "仅能设置已确认的经历页眉字段"))
                continue
            if (item.get(field) != value and
                    (not _literal_in(value, instruction)
                     or not _active_header_value(original_facts, section, item.get("item_id"), field, value))):
                results.append(_result(index, op, target, "needs_confirmation", "该页眉值还没有对应的 active fact"))
                continue
            previous = item.get(field)
            changed = previous != value
            item[field] = value
            results.append(_result(index, op, target, "done", "" if changed else "already_satisfied",
                                   changed=changed, affected=[item.get("item_id", "")], field=field))
            continue
        if op == "remove_section":
            kind = SECTION_ALIASES.get(target) or SECTION_ALIASES.get(str(args.get("section") or ""))
            if not kind:
                results.append(_result(index, op, target, "needs_confirmation", "没有找到指定栏目"))
                continue
            if not any(kind == SECTION_ALIASES.get(alias) and alias in clause
                       and re.search(r"删除|删掉|去掉|移除|不展示|不放|不要", clause)
                       for alias in SECTION_ALIASES for clause in re.split(r"[；;。，,\n]", instruction)):
                results.append(_result(index, op, target, "needs_confirmation", "栏目删除未在本轮指令中明确提出"))
                continue
            sections = output.get("sections")
            if sections is None:
                sections = [{"id": key, "kind": key, "title": title, "content": ""}
                            for key, title in DEFAULT_SECTIONS]
            kept = [row for row in sections if row.get("kind") != kind]
            changed = len(kept) != len(sections)
            output["sections"] = kept
            results.append(_result(index, op, target, "done", "" if changed else "already_satisfied",
                                   changed=changed))
            continue
        if op == "set_constraint":
            overrides, error = _constraint_overrides(args, instruction)
            if error:
                results.append(_result(index, op, target, "cannot", error))
                continue
            try:
                updated = normalize_session_constraints(limits, overrides=overrides)
            except (TypeError, ValueError):
                results.append(_result(index, op, target, "cannot", "约束值不在支持范围内"))
                continue
            changed = updated != limits
            limits = updated
            results.append(_result(index, op, target, "done", "" if changed else "already_satisfied",
                                   changed=changed))
            continue
        results.append(_result(index, op, target, "cannot", "不支持的操作"))
    writer_requests = []
    if writer_whole:
        writer_requests.append({"scope": "whole", "targets": [], "instruction": instruction})
    elif writer_targets:
        kinds = {kind for kind, _ in writer_targets}
        scope = "bullet" if kinds == {"bullet"} else "item"
        targets = [target if scope == "bullet" or kind == "item" else
                   output[_ITEM_POINTER.fullmatch(target)[1]][int(_ITEM_POINTER.fullmatch(target)[2])].get("item_id", "")
                   for kind, target in writer_targets]
        writer_requests.append({"scope": scope, "targets": list(dict.fromkeys(target for target in targets if target)),
                                "instruction": instruction})
    return {"data": output, "constraints": limits, "operation_results": results,
            "writer_requests": writer_requests}
