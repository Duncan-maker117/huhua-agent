"""Deterministic education, short-answer role binding, and edit receipts.

These helpers never invent a school name, a metric, or a responsibility the user
did not say. They only relocate or record text that is already in the turn.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
import uuid

from app.services.candidate_language import discipline_name, safe_major
from app.services.fact_guard import strip_absence
from app.services.resume_facts import new_fact, normalize_fact_store


_EDU_WORD = re.compile(r"大学|学院|本科|硕士|博士|大专|专科|大[一二三四]|研[一二三]|在读|学校|毕业|入学|就读")
_MAJOR_FIELD = re.compile(r"专业(?:改成|改为|写成|写为|换成|为|是|[：:])\s*([^，,。；;\n]{2,30})")
_PROFESSIONAL_WORDING = re.compile(r"更专业|专业一点|专业化|专业的?(?:表达|措辞)|润色|写得")
_NOT_SCHOOL = {"我在大学", "在大学", "这所大学", "本校大学"}
_ROLE_QUESTION = re.compile(r"职责|分工|独立|团队|一个人|谁做")
_ROLE_ANSWER = re.compile(r"一个人|都是我|独立|我负责|我写|我做|本人")


_AWARD_LINE = re.compile(r"竞赛|比赛|大赛|杯|奖|证书")
_EDU_HEADER = re.compile(
    r"(?ms)^[ \t#]*(?:教育背景|教育经历|教育)[ \t]*[：:]?[ \t]*(?:\n)?(.*?)(?=^[ \t#]*(?:课程项目|项目经历|项目|实习经历|工作经历|实习|"
    r"校园经历|校园活动|社团经历|开源贡献|竞赛荣誉|竞赛和荣誉|竞赛与荣誉|技能|专业技能|奖项|荣誉|获奖|证书|自我评价|个人评价|个人定位)[ \t]*[：:]?|\Z)")


def _clauses(message: str) -> list[str]:
    return [part.strip() for part in re.split(r"[，,。；;\n]", message) if part.strip()]


def _clean_school(name: str) -> str:
    cleaned = re.sub(
        r"^.*(?:写全称|写成|写为|改成|改为|换成|填成|填写|学校填|学校写|叫做|名叫|学校是|我是|我在|就读于|就读|毕业于|用|填|写)",
        "", name)
    cleaned = cleaned.strip("吧了的啊呀呢 ").removeprefix("在")
    if not cleaned or re.search(r"写|改|换|全称|填", cleaned):
        return ""
    return cleaned


def _school_token(clause: str) -> str:
    if _AWARD_LINE.search(clause) or re.search(r"协会|社团|学生会|时候|工作", clause):
        return ""  # 竞赛/奖项/证书行不产生教育字段
    # 「…大学」后面紧跟 生/程序/竞赛/比赛/大赛/杯 时是更长名称的一部分（如「…大学生程序设计竞赛」），作废
    named = re.search(r"([\u4e00-\u9fffA-Za-z]{2,24}(?:大学|学院))(?!生|程序|竞赛|比赛|大赛|杯)", clause)
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
    section = _EDU_HEADER.search(message)
    # 有「教育背景」栏目时只从该栏取，避免奖项/项目行里的「…大学」干扰
    education_text = section.group(1) if section and section.group(1).strip() else message
    clauses = _clauses(education_text)
    for index, clause in enumerate(clauses):
        if re.search(r"协会|社团|学生会|宣传部|担任", clause):
            continue
        school_hint = _school_token(clause)
        labelled = _MAJOR_FIELD.search(clause)
        if (index > 0 and _school_token(clauses[index - 1]) and 'major' not in fields
                and discipline_name(clause) and not school_hint and not re.search(r'课程|项目|接口|系统', clause)
                and not re.search(r'本科|硕士|博士|大专|专科', clause)):
            fields['major'] = clause
        if not _EDU_WORD.search(clause) and not school_hint and not labelled:
            # A separate noun phrase is allowed inside an education paragraph.
            if not (_EDU_WORD.search(education_text) and re.fullmatch(r"[\w与和]{2,30}专业", clause)
                    and not _PROFESSIONAL_WORDING.search(clause)):
                continue
        if _PROFESSIONAL_WORDING.search(clause) and not labelled:
            continue
        if re.search(r"项目|实习|做过|开发|上线|实现", clause) and not re.search(
            r"学校|我是|就读|专业|本科|硕士|在读|大[一二三四]", clause
        ):
            continue
        school = school_hint
        if school:
            fields["school"] = school
        if labelled:
            fields["major"] = labelled[1]
        for field, label in (("end_date", "毕业"), ("start_date", "入学")):
            dated = re.search(label + r"(?:年份|时间|日期)?(?:为|是|于|[：:])?\s*(20\d{2})(?:年)?", clause)
            if dated:
                fields[field] = dated[1]
        major = re.search(r"([\u4e00-\u9fffA-Za-z0-9与和]{2,30})专业", clause)
        if major and not labelled:
            token = re.split(r"大学|学院|就读|学的是|读的是|读", major[1])[-1]
            if _EDU_WORD.search(education_text) and discipline_name(token):
                fields["major"] = token
        elif (studied := re.search(r"(?:就读|学的(?:是)?|读的是|读)(?!者)([\u4e00-\u9fff]{2,12}?)(?=专业|本科|专科|$)", clause)):
            token = studied.group(1)
            if token not in {"本科", "硕士", "博士", "专科", "大学", "学院"}:
                fields["major"] = token
        degree = re.search(r"本科|硕士|博士|大专|专科", clause)
        if degree:
            fields["degree"] = degree.group(0)
            if "major" not in fields:
                before = clause[:degree.start()].strip(" （(：: ")
                before = re.split(r"大学|学院|[｜|·]", before)[-1].strip(" （(：: ")
                if re.fullmatch(r"[\u4e00-\u9fffA-Za-z与和]{2,30}", before) and not re.search(r"就读|学历|我是|学校", before):
                    fields["major"] = before
        grade = re.search(r"大[一二三四]|研[一二三]", clause)
        if grade:
            fields["grade"] = grade.group(0)
    school = fields.get("school") or ""
    # A school somewhere in a message does not own its first date range.
    # Only an education paragraph/sentence can supply education dates.
    from app.services.experience_subjects import subject_span
    for sentence in re.split(r'[。；;\n]', education_text):
        dates = re.search(r"(20\d{2}[./年-]\d{1,2}月?)\s*[—–~～至-]\s*(20\d{2}[./年-]\d{1,2}月?|至今)", sentence)
        if not dates:
            continue
        scope = subject_span(dates[0], message)
        if scope and scope['section'] != 'education':
            continue
        if ((section and not re.search(r'实习|工作|项目|校园|技能', sentence))
                or (re.search(r'教育|入学|毕业|就读|大学|学院', sentence)
                    and not re.search(r'实习|公司|项目', sentence))):
            fields.update(start_date=dates[1], end_date=dates[2])
    if fields:
        scholarship = re.search(r"[^，,。；;\n]*(?:奖学金)[^，,。；;\n]*", education_text)
        if scholarship:
            fields["highlights"] = scholarship[0].strip()
    if school and "major" not in fields:
        middle = re.search(re.escape(school) + r"([\u4e00-\u9fff]{2,12}?)(?:大[一二三四]|在读|的|$)", message)
        if middle:
            token = middle.group(1)
            if token and token not in {"本科", "硕士", "博士", "专科"}:
                fields["major"] = token
    return {key: value for key, value in fields.items() if value and value in message
            and (key != "major" or safe_major(value))}


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
        or (not school and any(fact.get("field") == "school" and fact.get("status", "active") == "active" for fact in item.get("facts") or []))
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
        for old in target["facts"]:
            if old.get("field") == field and old.get("status", "active") == "active":
                old["status"] = "superseded"
        fact = new_fact(value, kind="context", quote=quote, turn_id=turn_id)
        fact["field"] = field
        target.setdefault("facts", []).append(fact)
        if field != "grade":
            target[field] = value
    if school:
        target["school"] = school
    return result


_COMMAND_SENTENCE = re.compile(r"先给我|给我出|帮我|请(?:你)?(?:先|帮|给)|出一版|生成|看看吧?$")


def _ownership_span(answer: str) -> str:
    """Keep the leading ownership statement; a trailing 「先给我出一版看看」 is a command, not a fact."""
    text = answer.strip()
    sentences = [part for part in re.findall(r"[^。！？!?\n]+[。！？!?]?", text) if part.strip()]
    kept = []
    for sentence in sentences:
        if _COMMAND_SENTENCE.search(sentence):
            break
        kept.append(sentence)
    span = "".join(kept).strip()
    return span if span and span in text else text


def bind_role_followup(collected: dict, question: str, answer: str, turn_id: str = "") -> dict:
    """Resolve each ownership sentence from its own name or matching role question."""
    if not isinstance(answer, str) or not isinstance(question, str):
        return collected
    collected = bind_reason_followup(collected, question, answer, turn_id)
    if not collected.get('pending_ownership') and (not _ROLE_QUESTION.search(question) or not _ROLE_ANSWER.search(answer)):
        return collected
    result = normalize_fact_store(collected)
    pools = [(item.get("name") or item.get("company") or "", item)
             for section in ("projects", "work_experience", "internship", "campus")
             for item in result.get(section) or [] if isinstance(item, dict)]
    def named(text):
        return [item for label, item in pools if label and re.search(
            r'(?<![A-Za-z0-9_])' + re.escape(label) + r'(?![A-Za-z0-9_])', text, re.I)]

    pending = result.get('pending_ownership') or []
    identified = named(answer)
    if pending and len(identified) == 1 and (answer.strip(' 。！!') == next(
            label for label, item in pools if item is identified[0]) or re.search(r'说的是|指的是|属于|团队是', answer)):
        target = identified[0]
        for row in pending[:1]:
            quote = row['source_quote']
            target.setdefault('facts', []).append(new_fact(quote, kind='role', quote=quote, turn_id=row.get('turn_id', '')))
            target.setdefault('raw_notes', []).append(quote)
        result['pending_ownership'] = pending[1:]
        return result
    if not _ROLE_QUESTION.search(question) or not _ROLE_ANSWER.search(answer):
        return result

    # A metric question naming A must not steal the answer to a role question
    # naming B. Only question sentences about ownership count as context.
    contextual = {item['item_id']: item for sentence in re.split(r'[。！？!?；;\n]', question)
                  if _ROLE_QUESTION.search(sentence) for item in named(sentence)}
    from app.agents.fact_extractor import split_incomplete_tail
    complete, _ = split_incomplete_tail(answer)
    for sentence in re.findall(r'[^。！？!?\n]+[。！？!?]?', complete):
        if not _ROLE_ANSWER.search(sentence):
            continue
        quote = _ownership_span(sentence).strip()
        if not quote or quote not in answer:
            continue
        explicit = named(quote)
        choices = explicit if explicit else list(contextual.values())
        target = choices[0] if len(choices) == 1 else None
        if target is None and not re.search(r"团队|分工|我们|队友|[两二三四五六七八九十2-9](?:个)?人", quote):
            continue
        moved = []
        for _, item in pools:
            kept = []
            for fact in item.get('facts') or []:
                source = str(fact.get('source_quote') or '')
                current = fact.get('status', 'active') == 'active' and (not fact.get('turn_id') or fact.get('turn_id') == turn_id)
                related = source and (source in quote or (quote in source and source in answer))
                if current and related and (target is None or item is not target):
                    if source in quote:
                        moved.append(fact)
                else:
                    kept.append(fact)
            item['facts'] = kept
            # Raw notes also reach fallback ownership resolution; remove a wrong
            # attachment there, retaining the rest of a multi-answer message.
            if target is None or item is not target:
                item['raw_notes'] = [rest for note in item.get('raw_notes') or []
                                     if (rest := note.replace(quote, '').strip())]
                for field in ('role', 'title'):
                    if item.get(field) and str(item[field]) in quote:
                        item.pop(field)
        if target is None:
            pending = result.setdefault('pending_ownership', [])
            if not any(row.get('source_quote') == quote for row in pending):
                pending.append({'source_quote': quote, 'turn_id': turn_id})
            elif turn_id:
                for row in pending:
                    if row.get('source_quote') == quote and not row.get('turn_id'):
                        row['turn_id'] = turn_id
            continue
        result['pending_ownership'] = [row for row in result.get('pending_ownership') or [] if row.get('source_quote') != quote]
        known = {fact.get('source_quote') for fact in target.setdefault('facts', [])}
        target['facts'].extend(fact for fact in moved if fact.get('source_quote') not in known)
        known.update(fact.get('source_quote') for fact in moved)
        if quote not in known:
            target['facts'].append(new_fact(quote, kind='role', quote=quote, turn_id=turn_id))
        if quote not in target.setdefault('raw_notes', []):
            target['raw_notes'].append(quote)
    return result


def bind_reason_followup(collected: dict, question: str, answer: str, turn_id: str = '') -> dict:
    """Bind a short reason answer only when its question identifies one item."""
    from app.agents.interviewer import NO_ANSWER
    if '这样做是为了解决什么' not in question or not answer.strip() or NO_ANSWER.fullmatch(answer.strip()):
        return collected
    if re.search(r'生成|导出|个人定位|写法|按推荐写|改简历|不知道|不清楚', answer):
        return collected
    # The same interviewer message can also ask for metrics. A numeric reply
    # must not acquire a causal meaning merely because the reason question led.
    if not re.search(r'为了|避免|防止|因为|以便|目的是|解决', answer) and re.search(
            r'\d|[一二三四五六七八九十]+(?:人|次|个)|用户量|指标|第二|第三', answer):
        return collected
    result = normalize_fact_store(collected)
    names = re.findall(r'「([^」]+)」的决策(?:「[^」]*」)?：这样做是为了解决什么', question)
    pools = [item for section in ('projects', 'work_experience', 'internship', 'campus')
             for item in result.get(section) or []]
    named = [item for item in pools if (label := item.get('name') or item.get('company')) and label in answer]
    choices = [item for item in (named or pools) if (item.get('name') or item.get('company')) in names]
    if len(choices) != 1:
        return collected
    target = choices[0]
    quote = answer.strip()
    # Keep exact source and deduplicate extraction of the same reply.
    existing = next((f for f in target.get('facts') or []
                     if f.get('status', 'active') == 'active' and f.get('source_quote') == quote), None)
    if existing is None:
        existing = new_fact(quote, kind='context', quote=quote, turn_id=turn_id)
        target.setdefault('facts', []).append(existing)
    existing['kind'] = 'context'
    # The prefix records what this reply answers; the original quote stays exact.
    existing['text'] = quote if re.search(r'为了|避免|防止|因为|以便|原因', quote) else '目的是' + quote
    if quote not in target.setdefault('raw_notes', []):
        target['raw_notes'].append(quote)
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
            if field in {"school", "degree", "major", "start_date", "end_date", "highlights"} and fact.get("text"):
                row[field] = fact["text"]
            elif field == "grade" and fact.get("text"):
                grade = fact["text"]
        body = [fact["text"] for fact in facts if not fact.get("field") and fact.get("text")]
        for text in body:
            if re.search(r"奖学金|荣誉|获奖", text) and text not in row["highlights"]:
                row["highlights"] = "\n".join(filter(None, (row["highlights"], text)))
        if item.get("links"):
            row["links"] = deepcopy(item["links"])
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


def wording_only(message: str) -> bool:
    """A request about phrasing carries no authority to change candidate fields."""
    return bool(re.search(r"润色|改写|写得|专业一点|专业化|专业的?表达", message or "")
                and not parse_education_fields(message)
                and not explicit_objective(message)
                and not re.search(r"补充(?:事实|经历)|新增|我还(?:做|负责|完成)|改成|改为|不是\s*\d", message))


def _item_labels(data: dict | None) -> list[str]:
    labels = []
    for section in ("projects", "work_experience", "education", "campus", "open_source", "awards"):
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
        from app.services.resume_layout import density_operations
        ops.extend(density_operations(clause))
        target = _match_label(clause, labels) or _ordinal_target(clause)
        if re.search(r"[一二两12]\s*页", clause):
            number = 2 if re.search(r"[两2]\s*页", clause) else 1
            ops.append({"op": "set_constraint", "target": "page_limit", "args": {"page_limit": number}})
            continue
        if parse_education_fields(clause) and re.search(
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
    for section in ("projects", "work_experience", "education", "campus", "open_source", "awards"):
        for item in (data or {}).get(section) or []:
            if isinstance(item, dict) and item.get("item_id"):
                label = str(item.get("name") or item.get("company") or item.get("school") or "")
                names[item["item_id"]] = label
    return name_matches(names.get(left, left), names.get(right, right))


def _op_key(op: dict) -> str:
    payload = {"op": op.get("op"), "target": str(op.get("target") or ""), "args": op.get("args") or {}}
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


_FIELD_ALIAS = {"学校": "school", "专业": "major", "学历": "degree", "年级": "grade"}
_FORBID_WRITING = re.compile(r"(?:不要编造|别编造|不要写|别写|不要出现)(?:出)?([^，。；;]{1,16})")


def _normalize_op(op: dict) -> dict:
    args = dict(op.get("args") or {})
    if op.get("op") == "set_field" and args.get("field") in _FIELD_ALIAS:
        args["field"] = _FIELD_ALIAS[args["field"]]
        op = {**op, "args": args}
    return op


_EDIT_VERB = re.compile(r"改|突出|详细|精简|压缩|压成|删|写|补|换|调整|重写|润色|优化|强调|侧重|展开|缩短|扩|加上|去掉")


def _requested_op(op: dict, message: str) -> bool:
    """Drop ops the user did not ask for, including a fake page constraint."""
    kind = op.get("op")
    if kind in {"rewrite", "refocus", "compress"} and not _EDIT_VERB.search(message or ""):
        # 「先给我出一版看看」这类回答没有编辑意图，不能凭空生成改写项再报 ❌。
        return False
    if kind == "set_constraint":
        if any(key in (op.get('args') or {}) for key in ('density_delta', 'density_source')):
            from app.services.resume_layout import density_operations
            return any(row['args'] == op.get('args') for row in density_operations(message))
        return bool(re.search(r"[一二两12]\s*页", message or ""))
    if kind == "set_field":
        if (op.get("args") or {}).get("field") == "objective":
            return bool(explicit_objective(message)) and (op.get("args") or {}).get("value") == explicit_objective(message)
        field = _FIELD_ALIAS.get((op.get("args") or {}).get("field"), (op.get("args") or {}).get("field"))
        if field == "major":
            value = str((op.get("args") or {}).get("value") or "")
            return safe_major(value) and parse_education_fields(message).get("major") == value
        if not re.search(r"学校|学历|本科|硕士|学院", message or ""):
            return False
        value = str((op.get("args") or {}).get("value") or "")
        return not value or value in (message or "")
    return True


_DETERMINISTIC_OPS = {"set_field", "clean_format", "move_item", "set_constraint"}
_EDUCATION_CLAUSE = re.compile(r"学校|专业(?:改|是|为|写|[：:])|学历|本科|硕士|博士|大专|年级|大[一二三四]|研[一二三]")


def deterministic_only(message: str, planned_ops: list[dict], writer_requests: list[dict],
                       before: dict, after: dict, direction: dict | None = None) -> bool:
    """True when the turn only edits education fields or format: the writer must not run.

    Project and work prose must stay byte-for-byte identical to the previous version.
    """
    if writer_requests or direction:
        return False
    if any(op.get('op') == 'set_constraint' and op.get('target') != 'density' for op in planned_ops):
        return False
    if planned_ops and any(op.get("op") == "move_item" for op in planned_ops):
        moved_ids = {op.get("target") for op in planned_ops if op.get("op") == "move_item"}
        moved_ids.update(item.get("item_id") for section in ("projects", "work_experience", "internship", "campus", "open_source", "awards")
                         for item in (before or {}).get(section) or []
                         if (item.get("name") or item.get("company")) in moved_ids)
        def unrelated(store):
            result = deepcopy(store or {})
            for section in ("projects", "work_experience", "internship", "campus", "open_source", "awards"):
                result[section] = [item for item in result.get(section) or []
                                   if item.get("item_id") not in moved_ids
                                   and (item.get("name") or item.get("company")) not in moved_ids]
                if not result[section]:
                    result.pop(section)
            result.pop("education", None)
            return result
        return (all(op.get("op") in _DETERMINISTIC_OPS for op in planned_ops)
                and unrelated(before) == unrelated(after))
    if any(key != "education" and (before or {}).get(key) != (after or {}).get(key)
           for key in set(before or {}) | set(after or {})):
        return False
    if planned_ops:
        return all(op.get("op") in _DETERMINISTIC_OPS for op in planned_ops)
    clauses = [clause for clause in edit_clauses(message) if _CLAUSE_INTENT.search(clause)]
    return bool(clauses) and (before or {}) != (after or {}) and all(
        _EDUCATION_CLAUSE.search(clause) for clause in clauses)


_DETAIL_REQUEST = re.compile(r"详细|展开|写细|具体一点|丰富")


def _detail_question(name: str, role_profile: dict | None, facts_text: str) -> str:
    """岗位手册「高价值追问」里的现成问句：第一个事实里还没覆盖的；没有手册用通用问句。"""
    from app.agents.career_prompt import pick_followup
    return pick_followup((role_profile or {}).get("role_family") or "other", facts_text)


def detail_gap_rows(message: str, rows: list[dict], before: dict, after_meta: dict,
                    collected: dict, role_profile: dict | None = None) -> list[dict]:
    """「写详细一点」但条目没有未使用的已披露事实：不能报 ✅，改为请用户补充。"""
    from app.services.resume_facts import active_facts_for_writer
    clauses = [clause for clause in edit_clauses(message) if _DETAIL_REQUEST.search(clause)]
    if not clauses:
        return rows
    evidence = active_facts_for_writer(collected or {})
    items = {item.get("item_id"): item for section in ("projects", "work_experience", "internship", "campus")
             for item in evidence.get(section) or [] if isinstance(item, dict)}
    output = []
    for row in rows:
        affected = [item_id for item_id in row.get("affected_item_ids") or [] if item_id in items]
        name = _display_target(row.get("target") or "", before, before)
        if row.get("op") == "rewrite" and row.get("status") == "done" and affected and any(
                name and name in clause for clause in clauses):
            item = items[affected[0]]
            cited = {fid for bullet in (after_meta.get("bullets") or {}).get(affected[0]) or []
                     if isinstance(bullet, dict) for fid in bullet.get("fact_ids") or []}
            unused = []
            for fact in item.get("facts") or []:
                text = strip_absence(fact.get("text") or "")
                if (fact.get("id") not in cited and text and fact.get("field") is None
                        and not re.fullmatch(r"(?:这是|是)?(?:个|一个)?(?:课程原型|原型|demo|模拟数据|小组作业)(?:项目)?", text, re.I)):
                    unused.append(fact)
            if not unused:
                facts_text = " ".join(str(fact.get("text") or "") for fact in item.get("facts") or [])
                output.append({"op": "need_detail", "target": name, "status": "needs_detail",
                               "reason": _detail_question(name, role_profile, facts_text),
                               "changed": False, "affected_item_ids": affected})
                continue
        output.append(row)
    return output


_OBJECTIVE_DIRECTIVE = re.compile(r"求职意向\s*(?:就)?\s*(?:写成|写|改成|改为|填成|填)\s*[：:]?\s*([^，。；;\n]{2,60})")


def explicit_objective(message: str) -> str:
    """用户明确说「求职意向就写 X」时的 X；必须逐字出现在原话里。"""
    match = _OBJECTIVE_DIRECTIVE.search(message or "")
    value = match.group(1).strip(" 。，；;“”\"'「」") if match else ""
    return value if value and value in (message or "") else ""


def contract_gap_rows(rows: list[dict], contract: dict, before: dict) -> list[dict]:
    """Edit-contract failures stay visible: no ✅ for an edit that changed nothing or dropped content."""
    if not contract:
        return rows
    reasons = {}
    for item_id in contract.get("no_op") or []:
        reasons[item_id] = "这次改写没能比上一版更突出岗位相关内容（相关内容已在最前并用了 JD 表达，再改只会编造），需要你补充更贴近岗位的事实"
    for item_id in contract.get("not_shorter") or []:
        reasons.setdefault(item_id, "没能压得比上一版更短，当前稿保持表述不变")
    for item_id in (contract.get("missing") or {}):
        reasons.setdefault(item_id, "有已披露的相关内容没能保留进改写稿，请再确认要保留什么")
    output = []
    for row in rows:
        affected = [item_id for item_id in row.get("affected_item_ids") or [] if item_id in reasons]
        if row.get("op") in {"rewrite", "refocus", "compress"} and affected:
            output.append({"op": "contract_gap", "target": _display_target(row.get("target") or "", before, before),
                           "status": "needs_detail", "reason": reasons[affected[0]], "changed": False,
                           "affected_item_ids": affected})
        else:
            output.append(row)
    return output


def writing_constraints(message: str) -> list[dict]:
    """「不要编造用户量」is a writing rule, not a page constraint."""
    rows = []
    for match in _FORBID_WRITING.finditer(message or ""):
        topic = match.group(1).strip("的了吧啊呀呢 ")
        if not topic or re.search(r"[一二两12]\s*页", topic):
            continue
        rows.append({"op": "honor", "target": topic, "status": "done", "changed": True,
                     "reason": "已遵守", "affected_item_ids": []})
    return rows


def choose_edit_plan(message: str, data: dict | None, model_plan: list[dict],
                     collected: dict | None = None, *, router_failed: bool = False) -> list[dict]:
    """Model plan stays primary. Rules only fill gaps, or stand in when routing failed.

    「求职意向就写 X」always becomes a literal set_field; the writer never rewrites it."""
    plan = _choose_edit_plan(message, data, model_plan, collected, router_failed=router_failed)
    moves = section_move_ops(message, data)
    if moves:
        moved_targets = {move["target"] for move in moves}
        explicit_writing = re.search(r"重写|改写|润色|精简|压缩|突出|展开|写详细", message)
        plan = [op for op in plan if op.get("op") != "move_item" and not (
            op.get("op") in {"rewrite", "refocus", "compress"} and not explicit_writing
            and (not op.get("target") or op.get("target") in moved_targets
                 or op.get("target") in {"whole", "all", "resume", "projects", "项目经历"}))]
        plan.extend(moves)
    value = explicit_objective(message)
    if value:
        plan = [op for op in plan if not (op.get("op") == "set_field"
                                          and (op.get("args") or {}).get("field") == "objective")]
        plan.append({"op": "set_field", "target": "basic_info",
                     "args": {"field": "objective", "value": value}})
    return plan


def section_move_ops(message: str, data: dict | None) -> list[dict]:
    """Explicit reclassification is a field edit, not a request to rewrite prose."""
    from app.services.edit_plan import SECTION_ALIASES, ITEM_SECTIONS
    destination = ""
    for alias, kind in SECTION_ALIASES.items():
        if kind not in ITEM_SECTIONS or len(alias) < 2:
            continue
        if re.search(r"(?:这是|这个是|这条是|这段是|属于|放到|放进|移到|移入|挪到|归入|改成|改为)\s*[「『]?" + re.escape(alias), message):
            destination = kind
            break
    if not destination or re.search(r"不要(?:放到|移到|改成)|别(?:放到|移到|改成)", message):
        return []
    target = _match_label(message, _item_labels(data)) or _ordinal_target(message)
    if not target:
        candidates = [item for section in ITEM_SECTIONS for item in (data or {}).get(section) or []
                      if isinstance(item, dict) and not item.get("hidden")]
        if len(candidates) == 1:
            target = candidates[0].get("item_id") or _item_labels(data)[0]
    args = {"section": destination}
    renamed = re.search(r"(?:标题|仓库名|名称)(?:用|写成|改成|是|为)\s*[「『“]?([^」』”，,。；;]+)", message)
    if renamed:
        args["name"] = renamed[1].strip()
    return [{"op": "move_item", "target": target, "args": args}]


def _choose_edit_plan(message: str, data: dict | None, model_plan: list[dict],
                      collected: dict | None = None, *, router_failed: bool = False) -> list[dict]:
    rules = []
    seen = set()
    for op in [*education_edit_ops(message, collected or {}), *deterministic_compound_plan(message, data)]:
        key = _op_key(op)
        if key not in seen:
            seen.add(key)
            rules.append(op)
    model_plan = [_normalize_op(op) for op in (model_plan or []) if _requested_op(op, message)]
    if router_failed or not model_plan:
        return rules or list(model_plan or [])
    plan = list(model_plan)
    covered = {_op_key(op) for op in plan}
    for op in rules:
        key = _op_key(op)
        if key not in seen and not _requested_op(op, message):
            continue
        if key in covered:
            continue
        if op.get("op") == "set_field":
            field = (op.get("args") or {}).get("field")
            value = (op.get("args") or {}).get("value")
            if any(existing.get("op") == "set_field"
                   and (existing.get("args") or {}).get("field") == field
                   and (existing.get("args") or {}).get("value") == value
                   for existing in plan):
                continue
        elif any(_same_target(op.get("target") or "", existing.get("target") or "", data) for existing in plan):
            continue
        plan.append(op)
        covered.add(key)
    return plan


_CLAUSE_INTENT = re.compile(r"突出|写详细|写细|写上|补一句|加上|补上|删|压成|精简|改成|改为|换成|写全称|学校|专业(?:改|是|为|写|[：:])")


def uncovered_edit_clauses(message: str, plan: list[dict], data: dict | None = None) -> list[dict]:
    """Every edit clause must become an op or an explicit 'I didn't understand' line."""
    labels = _item_labels(data)
    gaps = []
    for clause in edit_clauses(message):
        if not _CLAUSE_INTENT.search(clause):
            continue
        if _clause_has_op(clause, plan, labels, data):
            continue
        gaps.append({"op": "understand", "target": clause, "status": "needs_confirmation",
                     "reason": f"这项我没理解：『{clause}』，你是想加到哪段经历？",
                     "changed": False, "affected_item_ids": []})
    return gaps


def _clause_has_op(clause: str, plan: list[dict], labels: list[str], data: dict | None = None) -> bool:
    from app.services.resume_layout import density_operations
    if density_operations(clause) and any(op.get('op') == 'set_constraint' and op.get('target') == 'density' for op in plan):
        return True
    if parse_education_fields(clause) and any(
        op.get("op") == "set_field" for op in plan
    ):
        return True
    if re.search(r"[一二两12]\s*页", clause) and any(op.get("op") == "set_constraint" for op in plan):
        return True
    if re.search(r"不要编造|别写|不要写", clause):
        return True
    mentioned = _match_label(clause, labels) or _ordinal_target(clause)
    verbs = {"refocus": r"突出|侧重|重点", "rewrite": r"详细|写细|补一句|写上|加上|改写|修改",
             "compress": r"精简|压缩|压成", "hide_item": r"删"}
    for op in plan:
        target = str(op.get("target") or "")
        display = _display_target(target, data or {}, data or {})
        same = (mentioned and _same_target(mentioned, target, data)) or (target and target in clause)
        same = same or any(label in clause and _same_target(label, display or target, data) for label in labels)
        if same:
            return True
        verb = verbs.get(op.get("op") or "")
        named = bool(mentioned and _same_target(mentioned, display or target, data))
        named = named or bool(target and target in clause) or bool(display and display in clause and display not in {"", "whole"})
        if verb and re.search(verb, clause) and named:
            return True
    return False


def _display_target(target: str, before: dict, after: dict) -> str:
    for document in (before, after):
        for section in ("projects", "work_experience", "education", "campus", "open_source", "awards"):
            for item in document.get(section) or []:
                if isinstance(item, dict) and item.get("item_id") == target:
                    return str(item.get("name") or item.get("company") or item.get("school") or target)
    return target


def _education_value(document: dict, field: str) -> str:
    for item in (document or {}).get("education") or []:
        if isinstance(item, dict) and str(item.get(field) or "").strip():
            return str(item[field]).strip()
    return ""


def reconcile_report_rows(results: list[dict], before: dict, after: dict) -> list[dict]:
    """A field line follows the draft diff, not a failed internal op."""
    fields = ("school", "major", "degree")
    changed = [field for field in fields if _education_value(before, field) != _education_value(after, field)
               and _education_value(after, field)]
    prepared = []
    claimed = set()
    for row in results or []:
        if row.get("op") == "understand":
            prepared.append(row)
            continue
        if row.get("op") != "set_field":
            prepared.append(row)
            continue
        field = _FIELD_ALIAS.get(row.get("field") or "", row.get("field") or "")
        if not field and changed:
            field = next((item for item in changed if item not in claimed), "")
        if field in fields and _education_value(after, field):
            if field in claimed:
                continue
            claimed.add(field)
            satisfied = field not in changed and row.get("status") == "done" and row.get("reason") == "already_satisfied"
            prepared.append({**row, "field": field, "status": "done", "changed": field in changed,
                             "reason": "already_satisfied" if satisfied else ""})
            continue
        if not field:
            field = next((item for item in changed if item not in claimed), "")
            if field:
                claimed.add(field)
                prepared.append({**row, "field": field, "status": "done", "changed": True, "reason": ""})
        # A failed field op that did not change the draft stays off the receipt.
    return prepared


def render_operation_report(results: list[dict], before: dict, after: dict) -> list[str]:
    """One line per requested op, from the op itself and the actual draft diff."""
    labels = {"rewrite": "改写", "compress": "压缩", "refocus": "调整重点", "set_field": "修改字段",
              "delete_item": "删除", "hide_item": "隐藏", "cap_bullets": "限制条数",
              "remove_section": "去掉栏目", "set_constraint": "更新篇幅要求", "clean_format": "清理格式",
              "honor": "已遵守", "move_item": "移动栏目"}
    hidden_targets = {"", "whole", "understand", "set_field", "set_constraint"}

    def find(document: dict, item_id: str):
        for section in ("projects", "work_experience", "education", "campus", "open_source", "awards"):
            for item in document.get(section) or []:
                if isinstance(item, dict) and item.get("item_id") == item_id:
                    return item
        return None

    lines = []
    for row in reconcile_report_rows(results, before, after):
        op = row.get("op") or "操作"
        if op == "understand":
            lines.append("⚠ " + str(row.get("reason") or "这项我没理解"))
            continue
        if op == "contract_gap":
            lines.append(f"⚠ {row.get('target')}：{row.get('reason')}")
            continue
        if op == "named_gap":
            lines.append(f"⚠ {row.get('target')}：{row.get('reason')}")
            continue
        if op == "need_detail":
            lines.append(f"⚠ {row.get('target')}：现有资料都已写进去了，想写得更详细需要你补充，比如：{row.get('reason')}")
            continue
        if op == "honor":
            topic = str(row.get("target") or "").strip()
            lines.append(f"✅ 已遵守：未写{topic}" if topic else "✅ 已遵守这条限制")
            continue
        if op == 'set_constraint' and row.get('target') == 'density':
            title = '调整排版'
        elif op == "set_field":
            field_name = {"school": "学校", "major": "专业", "degree": "学历", "grade": "年级",
                          "name": "姓名", "phone": "电话", "email": "邮箱"}.get(row.get("field") or "", "")
            title = f"修改{field_name}" if field_name else "修改经历信息"
        else:
            label = labels.get(op, "修改")
            target = _display_target(row.get("target") or "", before, after)
            if target in hidden_targets or target == row.get("op"):
                target = ""
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
    return list(dict.fromkeys(lines))  # refocus+rewrite 同一目标同一原因时只报一行
