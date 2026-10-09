"""Deterministic education, short-answer role binding, and edit receipts.

These helpers never invent a school name, a metric, or a responsibility the user
did not say. They only relocate or record text that is already in the turn.
"""

from __future__ import annotations

from copy import deepcopy
import re
import uuid

from app.services.resume_facts import new_fact, normalize_fact_store


_EDU_WORD = re.compile(r"大学|学院|专业|本科|硕士|博士|专科|大[一二三四]|研[一二三]|在读|学校")
_NOT_SCHOOL = {"我在大学", "在大学", "这所大学", "本校大学"}
_ROLE_QUESTION = re.compile(r"职责|分工|独立|团队|一个人|谁做")
_ROLE_ANSWER = re.compile(r"一个人|都是我|独立|我负责|我写|我做|本人")


def _clauses(message: str) -> list[str]:
    return [part.strip() for part in re.split(r"[，,。；;\n]", message) if part.strip()]


def _clean_school(name: str) -> str:
    cleaned = re.sub(
        r"^.*(?:写全称|写成|写为|改成|改为|换成|填成|填写|学校填|学校写|叫做|名叫|学校是|我是|我在|就读于|就读|毕业于|用|填|写)",
        "", name)
    cleaned = cleaned.strip("吧了的啊呀呢 ")
    if not cleaned or re.search(r"写|改|换|全称|填", cleaned):
        return ""
    return cleaned


def _school_token(clause: str) -> str:
    named = re.search(r"([\u4e00-\u9fffA-Za-z]{2,24}(?:大学|学院))", clause)
    if named:
        school = _clean_school(named.group(1))
        if school.endswith(("大学", "学院")) and school not in _NOT_SCHOOL and not school.startswith("我在") and len(school) >= 3:
            return school
    short = re.search(
        r"(?:我是|我在|就读|毕业于|学校(?:改成|改为|换成|写全称|写成|填|是)?)((?:[\u4e00-\u9fff]{2,6}?)大)(?!学)",
        clause)
    return short.group(1) if short else ""


def parse_education_fields(message: str) -> dict[str, str]:
    """Literal school, major, degree and grade spans. Abbreviations stay abbreviations."""
    if not isinstance(message, str) or not message.strip():
        return {}
    fields: dict[str, str] = {}
    for clause in _clauses(message):
        school_hint = _school_token(clause)
        if not _EDU_WORD.search(clause) and not school_hint:
            continue
        if re.search(r"项目|实习|做过|开发|上线|实现", clause) and not re.search(
            r"学校|我是|就读|专业|本科|硕士|在读|大[一二三四]", clause
        ):
            continue
        school = school_hint
        if school:
            fields["school"] = school
        major = re.search(r"([\u4e00-\u9fffA-Za-z0-9与和]{2,30})专业", clause)
        if major:
            fields["major"] = major.group(1)
        elif (studied := re.search(r"读([\u4e00-\u9fff]{2,8})", clause)):
            token = studied.group(1)
            if token not in {"本科", "硕士", "博士", "专科", "大学", "学院"}:
                fields["major"] = token
        degree = re.search(r"本科|硕士|博士|专科", clause)
        if degree:
            fields["degree"] = degree.group(0)
        grade = re.search(r"大[一二三四]|研[一二三]", clause)
        if grade:
            fields["grade"] = grade.group(0)
    school = fields.get("school") or ""
    if school and "major" not in fields:
        middle = re.search(re.escape(school) + r"([\u4e00-\u9fff]{2,12}?)(?:大[一二三四]|在读|的|$)", message)
        if middle:
            token = middle.group(1)
            if token and token not in {"本科", "硕士", "博士", "专科"}:
                fields["major"] = token
    return {key: value for key, value in fields.items() if value and value in message}


def education_confirmation(fields: dict) -> str:
    """Ask for a full school name without writing a guessed expansion."""
    school = fields.get("school") or ""
    if school and not school.endswith(("大学", "学院")):
        return f"「{school}」像是学校简称。请直接回复全称，或说明简历里就用这个简称。"
    return ""


def _quote_span(message: str, value: str) -> str:
    return value if value in message else ""


def absorb_education(collected: dict, previous: dict | None, message: str, turn_id: str = "") -> dict:
    """Put an education statement on the education item and drop a same-turn project alias."""
    fields = parse_education_fields(message)
    if not fields:
        return collected
    result = normalize_fact_store(collected)
    previous_ids = {
        item.get("item_id") for item in (previous or {}).get("projects") or [] if isinstance(item, dict)
    }
    school = fields.get("school") or ""
    kept_projects = []
    for item in result.get("projects") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        created_now = item.get("item_id") not in previous_ids
        facts = [fact for fact in item.get("facts") or [] if fact.get("status", "active") == "active"]
        action = any(fact.get("kind") in {"action", "deliverable", "method_tool", "result_metric", "result_qualitative"}
                     for fact in facts)
        if created_now and school and school in name and not action:
            continue
        kept_projects.append(item)
    result["projects"] = kept_projects
    items = result.setdefault("education", [])
    target = next((item for item in items if isinstance(item, dict) and (
        item.get("item_id") and school and (item.get("school") == school or school in str(item.get("school") or ""))
        or any(fact.get("field") == "school" and fact.get("status", "active") == "active" for fact in item.get("facts") or [])
    )), None)
    if target is None and len([item for item in items if isinstance(item, dict)]) == 1:
        target = next(item for item in items if isinstance(item, dict))
    if target is None:
        target = {"item_id": str(uuid.uuid4()), "school": "", "facts": [], "raw_notes": []}
        items.append(target)
    notes = target.setdefault("raw_notes", [])
    if message and message not in notes:
        notes.append(message)
    for field, value in fields.items():
        quote = _quote_span(message, value)
        if not quote:
            continue
        active = next((fact for fact in target.setdefault("facts", [])
                       if fact.get("field") == field and fact.get("status", "active") == "active"), None)
        if active and active.get("text") == value:
            target[field] = value
            continue
        if active:
            active["status"] = "superseded"
        fact = new_fact(value, kind="context", quote=quote, turn_id=turn_id)
        fact["field"] = field
        target.setdefault("facts", []).append(fact)
        if field != "grade":
            target[field] = value
    if school:
        target["school"] = school
    return result


def bind_role_followup(collected: dict, question: str, answer: str, turn_id: str = "") -> dict:
    """Attach a short ownership answer to the experience the previous question named."""
    if not isinstance(answer, str) or not isinstance(question, str):
        return collected
    if not _ROLE_QUESTION.search(question) or not _ROLE_ANSWER.search(answer) or len(answer) > 160:
        return collected
    result = normalize_fact_store(collected)
    named = re.findall(r"[「『]([^」』]{1,40})[」』]", question + answer)
    pools = [(item.get("name") or item.get("company") or "", item)
             for section in ("projects", "work_experience", "internship")
             for item in result.get(section) or [] if isinstance(item, dict)]
    target = None
    for label, item in pools:
        if label and (label in answer or any(label in token or token in label for token in named)):
            target = item
            break
    if target is None and len(pools) == 1:
        target = pools[0][1]
    if target is None:
        return collected
    quote = answer.strip()
    if any(fact.get("source_quote") == quote and fact.get("status", "active") == "active"
           for fact in target.get("facts") or []):
        return result
    target.setdefault("facts", []).append(new_fact(quote, kind="role", quote=quote, turn_id=turn_id))
    notes = target.setdefault("raw_notes", [])
    if quote not in notes:
        notes.append(quote)
    return result


def overlay_education(collected: dict, resume: dict | None) -> dict:
    """Copy active education field facts onto the draft. Grade renders in highlights."""
    resume = deepcopy(resume or {})
    rows = []
    for item in (collected or {}).get("education") or []:
        if not isinstance(item, dict):
            continue
        facts = [fact for fact in item.get("facts") or []
                 if isinstance(fact, dict) and fact.get("status", "active") == "active"]
        if not facts and not item.get("school"):
            continue
        row = {"item_id": item.get("item_id"), "school": item.get("school") or "",
               "degree": item.get("degree") or "", "major": item.get("major") or "",
               "start_date": item.get("start_date") or "", "end_date": item.get("end_date") or "",
               "highlights": item.get("highlights") or ""}
        grade = ""
        for fact in facts:
            field = fact.get("field")
            if field in {"school", "degree", "major", "start_date", "end_date"} and fact.get("text"):
                row[field] = fact["text"]
            elif field == "grade" and fact.get("text"):
                grade = fact["text"]
        if grade and grade not in row["highlights"]:
            row["highlights"] = (row["highlights"] + " " + grade).strip()
        if item.get("hidden") is True:
            row["hidden"] = True
        rows.append(row)
    if rows:
        resume["education"] = rows
    return resume


def education_edit_ops(message: str, collected: dict) -> list[dict]:
    """Header edits whose values are literal spans and already have an active fact."""
    fields = parse_education_fields(message)
    if not fields:
        return []
    item_id = ""
    for item in (collected or {}).get("education") or []:
        if isinstance(item, dict) and item.get("item_id"):
            item_id = item["item_id"]
            break
    if not item_id:
        return []
    ops = []
    for field in ("school", "major", "degree"):
        value = fields.get(field)
        if value:
            ops.append({"op": "set_field", "target": item_id, "args": {"field": field, "value": value}})
    return ops


def edit_clauses(message: str) -> list[str]:
    if not isinstance(message, str) or not message.strip():
        return []
    clauses = [part.strip() for part in re.split(r"[；;\n]+|(?:^|\s)\d+[.、]\s*", message) if part.strip()]
    if len(clauses) == 1:
        pieces = [part.strip() for part in re.split(r"[，,]", message) if part.strip()]
        if len(pieces) >= 2:
            clauses = pieces
    return clauses


def _item_labels(data: dict | None) -> list[str]:
    labels = []
    for section in ("projects", "work_experience", "education"):
        for item in (data or {}).get(section) or []:
            if isinstance(item, dict):
                label = item.get("name") or item.get("company") or item.get("school") or ""
                if label:
                    labels.append(str(label))
    return labels


def name_matches(query: str, label: str) -> bool:
    """Case-folded prefix or token match. Queries shorter than 3 characters must be exact."""
    left = re.sub(r"\s+", "", str(query or "")).casefold()
    right = re.sub(r"\s+", "", str(label or "")).casefold()
    if not left or not right:
        return False
    if left == right:
        return True
    if len(left) < 3:
        return False
    if right.startswith(left) or left.startswith(right):
        return True
    tokens = [token for token in re.split(r"[\s·|/._-]+", str(label or "").casefold()) if token]
    return any(token == left or token.startswith(left) for token in tokens)


def _match_label(clause: str, labels: list[str]) -> str:
    for label in labels:
        if label and label in clause:
            return label
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9._-]{1,}|[\u4e00-\u9fff]{2,}", clause)
    hits = [label for label in labels if any(name_matches(token, label) for token in tokens)]
    if not hits:
        return ""
    return max(hits, key=len)


def _ordinal_target(clause: str) -> str:
    match = re.search(r"第[一二两三四五六七八九十\d]+(?:个|段|条)?(?:项目|经历|工作|实习|教育)", clause)
    return match.group(0) if match else ""


def deterministic_compound_plan(message: str, data: dict | None = None) -> list[dict]:
    """Fallback ops for one user message. A single vague verb stays empty."""
    labels = _item_labels(data)
    ops = []
    for clause in edit_clauses(message):
        target = _match_label(clause, labels) or _ordinal_target(clause)
        if re.search(r"[一二两12]\s*页", clause):
            number = 2 if re.search(r"[两2]\s*页", clause) else 1
            ops.append({"op": "set_constraint", "target": "page_limit", "args": {"page_limit": number}})
            continue
        if re.search(r"学校|专业|学历|本科|硕士|大[一二三四]", clause) and re.search(
            r"改成|改为|换成|加上|补充|写成|写全称|全称|填", clause
        ):
            continue
        if re.search(r"删掉|删除|删了|去掉|移除|不要放|别放", clause):
            ops.append({"op": "hide_item", "target": target or _ordinal_target(clause), "args": {}})
        elif re.search(r"精简|压缩|缩短|收成一条|合成一条|留一条|各留|压成", clause):
            ops.append({"op": "compress", "target": target, "args": {}})
        elif re.search(r"突出|侧重|重点", clause):
            ops.append({"op": "refocus", "target": target, "args": {}})
        elif re.search(r"详细|展开|写细|写具体|写清楚|补一句|加上|写上|补上", clause):
            ops.append({"op": "rewrite", "target": target, "args": {}})
        elif re.search(r"改成|改为|换成|改写|修改", clause) and target:
            ops.append({"op": "rewrite", "target": target, "args": {}})
    return ops


def _same_target(left: str, right: str, data: dict | None) -> bool:
    if not left or not right:
        return False
    if left == right or name_matches(left, right) or name_matches(right, left):
        return True
    names = {}
    for section in ("projects", "work_experience", "education"):
        for item in (data or {}).get(section) or []:
            if isinstance(item, dict) and item.get("item_id"):
                label = str(item.get("name") or item.get("company") or item.get("school") or "")
                names[item["item_id"]] = label
    return name_matches(names.get(left, left), names.get(right, right))


def _op_key(op: dict) -> tuple:
    return (op.get("op"), str(op.get("target") or ""), tuple(sorted((op.get("args") or {}).items())))


def choose_edit_plan(message: str, data: dict | None, model_plan: list[dict],
                     collected: dict | None = None, *, router_failed: bool = False) -> list[dict]:
    """Model plan stays primary. Rules only fill gaps, or stand in when routing failed."""
    rules = []
    seen = set()
    for op in [*education_edit_ops(message, collected or {}), *deterministic_compound_plan(message, data)]:
        key = _op_key(op)
        if key not in seen:
            seen.add(key)
            rules.append(op)
    if router_failed or not model_plan:
        return rules or list(model_plan or [])
    plan = list(model_plan)
    covered = {_op_key(op) for op in plan}
    for op in rules:
        key = _op_key(op)
        if key in covered:
            continue
        # A rule op is redundant when the model already named the same item and verb family.
        if any(_same_target(op.get("target") or "", existing.get("target") or "", data) for existing in plan):
            continue
        plan.append(op)
        covered.add(key)
    return plan


_CLAUSE_INTENT = re.compile(r"突出|写详细|写细|写上|补一句|加上|补上|删|压成|精简|改成|改为|换成|写全称|学校|专业")


def uncovered_edit_clauses(message: str, plan: list[dict], data: dict | None = None) -> list[dict]:
    """Every edit clause must become an op or an explicit 'I didn't understand' line."""
    labels = _item_labels(data)
    gaps = []
    for clause in edit_clauses(message):
        if not _CLAUSE_INTENT.search(clause):
            continue
        if _clause_has_op(clause, plan, labels):
            continue
        gaps.append({"op": "understand", "target": clause, "status": "needs_confirmation",
                     "reason": f"这项我没理解：『{clause}』，你是想加到哪段经历？",
                     "changed": False, "affected_item_ids": []})
    return gaps


def _clause_has_op(clause: str, plan: list[dict], labels: list[str]) -> bool:
    if re.search(r"学校|专业|学历|写全称|填", clause) and any(
        op.get("op") == "set_field" for op in plan
    ):
        return True
    if re.search(r"[一二两12]\s*页", clause) and any(op.get("op") == "set_constraint" for op in plan):
        return True
    mentioned = _match_label(clause, labels) or _ordinal_target(clause)
    for op in plan:
        target = str(op.get("target") or "")
        if mentioned and (mentioned == target or name_matches(mentioned, target) or name_matches(target, mentioned)):
            return True
        if target and target in clause:
            return True
    return False


def _display_target(target: str, before: dict, after: dict) -> str:
    for document in (before, after):
        for section in ("projects", "work_experience", "education"):
            for item in document.get(section) or []:
                if isinstance(item, dict) and item.get("item_id") == target:
                    return str(item.get("name") or item.get("company") or item.get("school") or target)
    return target


def render_operation_report(results: list[dict], before: dict, after: dict) -> list[str]:
    """One line per requested op, from the op itself and the actual draft diff."""
    labels = {"rewrite": "改写", "compress": "压缩", "refocus": "调整重点", "set_field": "修改字段",
              "delete_item": "删除", "hide_item": "隐藏", "cap_bullets": "限制条数",
              "remove_section": "去掉栏目", "set_constraint": "更新篇幅要求", "clean_format": "清理格式"}

    def find(document: dict, item_id: str):
        for section in ("projects", "work_experience", "education"):
            for item in document.get(section) or []:
                if isinstance(item, dict) and item.get("item_id") == item_id:
                    return item
        return None

    lines = []
    for row in results or []:
        op = row.get("op") or "操作"
        if op == "set_field":
            field_name = {"school": "学校", "major": "专业", "degree": "学历", "grade": "年级",
                          "name": "姓名", "phone": "电话", "email": "邮箱"}.get(row.get("field") or "", "字段")
            title = f"修改{field_name}"
        else:
            label = labels.get(op, op)
            target = _display_target(row.get("target") or "", before, after)
            title = f"{label} {target}".strip()
        status = row.get("status")
        if status == "needs_confirmation":
            lines.append(f"⚠ {title}：{row.get('reason') or '需要你确认目标'}")
            continue
        if status == "cannot":
            lines.append(f"❌ {title}：{row.get('reason') or '做不到'}")
            continue
        if status != "done":
            lines.append(f"❌ {title}：没有执行")
            continue
        affected = row.get("affected_item_ids") or []
        if row.get("reason") == "already_satisfied":
            lines.append(f"✅ {title}：原本已经满足")
            continue
        changed = bool(row.get("changed"))
        if affected:
            changed = changed or any(find(before, item_id) != find(after, item_id) for item_id in affected)
        elif op in {"rewrite", "compress", "refocus"} and (target in {"", "whole"}):
            changed = changed or before != after
        if row.get("reason") == "等待 writer 改写" and not changed:
            lines.append(f"❌ {title}：文稿里没有对应改动")
            continue
        if changed or op == "set_constraint":
            lines.append(f"✅ {title}")
        else:
            lines.append(f"❌ {title}：没有产生改动")
    return lines
