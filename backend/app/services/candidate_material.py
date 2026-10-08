"""Source-preserving, deterministic import of Chinese resume documents.

Uploads are parsed independently. Explicit uncertainty and conflicting fields
remain review notes; an old draft is not a reason to discard entire sections.
"""
from __future__ import annotations

import copy
import re

_PROJECT_SECTION = re.compile(r"^项目经历(?:\s*[（(].*[）)])?$")
_EDUCATION_SECTION = re.compile(r"^教育(?:背景|经历)(?:\s*[（(].*[）)])?$")
_SKILL_SECTION = re.compile(r"^(?:产品与技术能力|专业技能|技能(?:与工具)?)(?:\s*[（(].*[）)])?$")
_AWARD_SECTION = re.compile(r"^(?:校园活动|获奖经历|荣誉奖项|证书|竞赛与活动)(?:\s*[（(].*[）)])?$")
_STOP_SECTION = re.compile(
    r"^(?:编辑记录|到馆后的定稿顺序|定稿顺序|后续计划|工作计划|自我评价|"
    r"个人总结|个人定位|工作经历|实习经历)(?:\s*[（(].*[）)])?$"
)
_PROJECT_HEADING = re.compile(r"^([^｜|\n]{2,90})[｜|](.+)$")
_FILE_BOUNDARY = re.compile(r"(?m)^\[文件[:：]\s*([^\]\n]{1,200})\]\s*\n?")
_DATE = re.compile(r"(?<!\d)(20\d{2})(?:\s*[.．/年]\s*(0?[1-9]|1[0-2])(?!\d)\s*月?)?(?!\d)")
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_UNSAFE_CLAUSE = re.compile(
    r"待补|待核实|待确认|定稿|下一步|后续验证方案|需要你|请你|"
    r"不以演示代替|训练营名称与奖项未经|候选范围"
)
_ROLE = re.compile(r"独立开发者|独立开发|项目发起人|项目负责人|(?:负责|主导)[^，。；\n]{2,45}")
_LABELS = {"姓名", "求职意向", "求职方向", "简历", "个人简历", "联系方式", "教育背景", "项目经历"}
_BASIC_FIELD = re.compile(r"^(姓名|求职意向|求职方向|电话|手机|手机号|邮箱|电子邮箱|GitHub)[：:]\s*(.+)$", re.I)
_PROJECT_METADATA = re.compile(r"^(?:个人|[^，。；|｜]{0,30}(?:训练营|黑客松|课程|竞赛))项目\s*[|｜·•]\s*(.+)$")
_NON_CANDIDATE = re.compile(
    r"(?mi)^\s*(?:#{1,6}\s*)?(?:示例简历|简历范文|参考简历|参考材料|虚构简历|以下是范文|他人简历|"
    r"任职要求|职位要求|招聘要求|岗位职责|职位详情|(?:新的?|目标)?\s*JD)\s*[:：\n]"
)
_DOCUMENT_INSTRUCTION = re.compile(
    r"^(?:请|帮我(?:生成|制作|整理)|"
    r"不需要(?:自我评价|重复摘要|继续追问)|不要(?:虚构|添加|写入|再问)|没有真实业务成效数字|"
    r"(?:使用|保留|删除|去掉).{0,24}(?:模块|章节|摘要|自我评价))"
)


def _plain(line: str) -> str:
    return line.replace("**", "").strip()


def _resume_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"^\s*#{1,6}\s+", "", raw).strip()
        # Chat messages commonly put a section label and its first fact on one
        # line. Normalize only known labels, never arbitrary prose or commands.
        label, separator, content = re.sub(r"^\*\*(.+?)\*\*", r"\1", line).replace(":", "：", 1).partition("：")
        if separator and any(pattern.fullmatch(label.strip()) for pattern in (
            _PROJECT_SECTION, _EDUCATION_SECTION, _SKILL_SECTION, _AWARD_SECTION,
        )):
            lines.extend([label.strip(), content.strip()])
        else:
            lines.append(line)
    return lines


def _documents(text: str) -> list[tuple[str, str]]:
    matches = list(_FILE_BOUNDARY.finditer(text))
    if not matches:
        return [("粘贴资料", text)]
    documents = []
    if text[:matches[0].start()].strip():
        documents.append(("附带文字", text[:matches[0].start()]))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        documents.append((match.group(1).strip(), text[match.end():end]))
    return documents


def _dates(text: str) -> tuple[str, str]:
    dates = [year + (f".{int(month)}" if month else "") for year, month in _DATE.findall(text)]
    end = dates[1] if len(dates) > 1 else "至今" if dates and re.search(r"至今|现在", text) else ""
    return dates[0] if dates else "", end


def _project_heading(line: str) -> dict | None:
    if _BASIC_FIELD.match(_plain(line)) or _PROJECT_METADATA.fullmatch(_plain(line)):
        return None
    match = _PROJECT_HEADING.fullmatch(_plain(line))
    if match:
        name, detail = match.groups()
    else:
        # Ordinary prose containing a year cannot become a project heading.
        bold = re.fullmatch(r"\*\*(.+?)\*\*\s*(?:[·•]\s*(.*))?", line)
        if not bold:
            return None
        title, suffix = bold.groups()
        parts = re.split(r"\s{2,}|\s+(?=[\u4e00-\u9fff])", title.strip(), maxsplit=1)
        name = parts[0]
        detail = " · ".join(p for p in (parts[1] if len(parts) > 1 else "", suffix) if p)
    name = name.strip(" ·•[] ")
    if not name or len(name) > 90 or name in _LABELS:
        return None
    start_date, end_date = _dates(detail)
    subtitle = re.split(r"[·•]", detail, maxsplit=1)[0].strip()
    if _DATE.fullmatch(subtitle):
        subtitle = ""
    status_bits = [
        bit.strip() for bit in re.findall(r"[\[［]([^\]］]+)[\]］]", detail)
        if not _DATE.search(bit) and not re.search(r"负责|主导|待核|待补", bit)
    ]
    # Bracketed editorial labels are not a confirmed role. Ordinary title
    # metadata, such as “独立开发者 · 2025”, is an explicit source statement.
    role = _ROLE.search(re.sub(r"[\[［][^\]］]*[\]］]", "", detail))
    return {
        "name": name, "role": re.split(r"[·•]|\s*20\d{2}", role.group(0))[0].strip() if role else "",
        "start_date": start_date, "end_date": end_date,
        "_description_lines": [part for part in (subtitle, *status_bits) if part],
        "_body_started": False,
    }


def _looks_like_document(text: str) -> bool:
    if _NON_CANDIDATE.search(text):
        return False
    lines = _resume_lines(text)
    sections = {
        name for name, pattern in (("projects", _PROJECT_SECTION), ("education", _EDUCATION_SECTION),
                                  ("skills", _SKILL_SECTION), ("awards", _AWARD_SECTION))
        if any(pattern.fullmatch(_plain(line)) for line in lines)
    }
    # Omitted "项目经历" is common in complete chat submissions. Require
    # corroborating resume sections instead of treating every pipe as a resume.
    has_context = "projects" in sections or (len(sections) >= 2 and "education" in sections)
    return has_context and any(
        _project_heading(line) for line in lines if not _DOCUMENT_INSTRUCTION.match(_plain(line))
    )


def looks_like_existing_resume(text: str) -> bool:
    if not isinstance(text, str) or len(text) < 80:
        return False
    return any(_looks_like_document(body) for _, body in _documents(text))


def _safe_clauses(line: str, name: str, notes: list[str]) -> list[str]:
    kept = []
    for raw in re.findall(r"[^。；]+[。；]?", line):
        clause = raw.strip()
        if not clause:
            continue
        if _UNSAFE_CLAUSE.search(clause):
            note = f"{name}：个人职责与具体动作待核对。"
            if "待补" in clause and note not in notes:
                notes.append(note)
            continue
        kept.append(clause.rstrip("；"))
    return kept


def _education(line: str) -> dict | None:
    parts = [part.strip().rstrip("。") for part in re.split(r"[·•|｜，,]", line) if part.strip()]
    if len(parts) < 2 or not re.search(r"大学|学院|学校", parts[0]):
        return None
    degree_match = re.search(r"[（(](本科|硕士|博士|专科)[）)]", parts[1])
    degree = degree_match.group(1) if degree_match else next((part for part in parts[2:] if part in {"本科", "硕士", "博士", "专科"}), "")
    return {
        "school": parts[0], "degree": degree,
        "major": re.sub(r"[（(](?:本科|硕士|博士|专科)[）)]", "", parts[1]).strip(),
        "start_date": "", "end_date": next((part for part in parts[2:] if re.search(r"20\d{2}", part)), ""),
        "highlights": "",
    }


def _append_wrapped(lines: list[str], line: str) -> None:
    """Join PDF soft wraps, while retaining bullets and labelled paragraphs."""
    is_new = bool(re.match(r"^[-*•▸]\s*|^[^：:]{2,16}[：:]", line))
    line = re.sub(r"^[-*•▸]\s*", "", line).strip()
    if not line:
        return
    if lines and not is_new and not re.search(r"[。！？；.!?]$", lines[-1]):
        joiner = " " if re.search(r"[A-Za-z]$", lines[-1]) and re.match(r"[A-Za-z]", line) else ""
        lines[-1] += joiner + line
    else:
        lines.append(line)


def _parse_document(text: str) -> dict | None:
    if not _looks_like_document(text):
        return None
    notes = ["内容来自所提供的简历资料；明确陈述已保留，缺失与冲突项需核对。"]
    result = {"basic_info": {}, "education": [], "projects": [], "skills": [], "certificates": [], "verification_notes": notes}
    summary_lines: list[str] = []
    basic = result["basic_info"]
    section = "intro"
    current: dict | None = None
    heading_uncertain = False

    def finish_project() -> None:
        nonlocal current
        if current is None:
            return
        paragraphs = current.pop("_description_lines")
        current.pop("_body_started", None)
        current["description"] = "\n".join(dict.fromkeys(
            clause for line in paragraphs for clause in _safe_clauses(line, current["name"], notes)
        ))
        statuses = []
        for pattern, value in ((r"尚未上线|未上线|没有上线", "未上线"), (r"已上线|已经上线", "已上线")):
            if re.search(pattern, current["description"]):
                statuses.append(value)
        current["_release_status"] = statuses
        result["projects"].append(current)
        current = None

    for raw in _resume_lines(text):
        if not raw:
            continue
        line = _plain(raw)
        if _DOCUMENT_INSTRUCTION.match(line):
            continue
        next_section = None
        if _EDUCATION_SECTION.fullmatch(line):
            next_section = "education"
        elif _PROJECT_SECTION.fullmatch(line):
            next_section = "projects"
        elif _SKILL_SECTION.fullmatch(line):
            next_section = "skills"
        elif _AWARD_SECTION.fullmatch(line):
            next_section = "certificates"
        elif line in {"自我评价", "个人总结", "个人定位"}:
            next_section = "summary"
        elif _STOP_SECTION.fullmatch(line):
            next_section = "excluded"
        if next_section:
            finish_project()
            section = next_section
            heading_uncertain = bool(re.search(r"待(?:本人)?核|待确认|候选", line))
            if heading_uncertain and section in {"skills", "certificates"}:
                notes.append(f"{line}：该节明确标为未核实，未作为已确认技能或奖项写入。")
            continue
        if section in {"intro", "education"}:
            field_match = _BASIC_FIELD.fullmatch(line)
            if field_match:
                label, value = field_match.groups()
                field = {"姓名": "name", "求职意向": "objective", "求职方向": "objective",
                         "电话": "phone", "手机": "phone", "手机号": "phone", "邮箱": "email",
                         "电子邮箱": "email", "github": "github"}.get(label.lower())
                if field == "phone":
                    value = match.group(0) if (match := _PHONE.search(value)) else ""
                elif field == "email":
                    value = match.group(0) if (match := _EMAIL.search(value)) and not match.group(0).lower().endswith("@example.com") else ""
                if field and value:
                    basic.setdefault(field, value)
                continue
            # A well-formed project heading after explicit candidate facts can
            # start the project section even when the user omitted its label.
            if (section == "education" or basic.get("name")) and _project_heading(raw) and not _education(line):
                section = "projects"
        if section == "intro":
            title = _PROJECT_HEADING.fullmatch(line)
            if title and title.group(1).strip() in {"求职意向", "求职方向"}:
                basic.setdefault("objective", title.group(2).strip())
            elif (title and title.group(1).strip() not in _LABELS and "简历" not in title.group(1)
                  and not _EMAIL.search(line) and not _PHONE.search(line)):
                basic.setdefault("name", title.group(1).strip())
                basic.setdefault("objective", title.group(2).strip())
            elif not basic.get("name") and re.fullmatch(r"[\u4e00-\u9fff·]{2,5}", line) and line not in _LABELS:
                basic["name"] = line
            email, phone = _EMAIL.search(line), _PHONE.search(line)
            if email and not email.group(0).lower().endswith("@example.com"):
                basic.setdefault("email", email.group(0))
            if phone:
                basic.setdefault("phone", phone.group(0))
            if "联系方式" in line and (not email or not phone or "xxxx" in line.lower()):
                notes.append("联系方式不完整或已脱敏，需补齐并核对。")
        elif section == "education":
            item = _education(line)
            if item and item not in result["education"]:
                result["education"].append(item)
        elif section == "projects":
            heading = _project_heading(raw)
            if heading:
                finish_project()
                current = heading
                continue
            if current is not None:
                if not current["_body_started"] and not re.match(r"^[-*•▸]", line):
                    start, end = _dates(line)
                    role = _ROLE.search(line)
                    role_line = _PROJECT_METADATA.fullmatch(line)
                    is_metadata = (len(line) <= 110 and (start or role or role_line)
                                   and not re.search(r"[。；，]|没有|并非|不是|未负责|不负责", line)
                                   and not _UNSAFE_CLAUSE.search(line))
                    if is_metadata:
                        if start:
                            current["start_date"] = current["start_date"] or start
                            current["end_date"] = current["end_date"] or end
                        if role:
                            current["role"] = re.split(r"\s*20\d{2}", role.group(0))[0].strip(" ·")
                        elif role_line:
                            current["role"] = role_line.group(1).strip()
                        current["_description_lines"].append(line)
                        continue
                current["_body_started"] = True
                _append_wrapped(current["_description_lines"], line)
        elif section in {"skills", "certificates"} and not heading_uncertain:
            if not _UNSAFE_CLAUSE.search(line):
                _append_wrapped(result[section], line)
        elif section == "summary" and not _UNSAFE_CLAUSE.search(line):
            _append_wrapped(summary_lines, line)
    finish_project()
    result["personal_summary"] = "\n".join(summary_lines)
    return result


def _compatible_date(left: str, right: str) -> str | None:
    if left == right:
        return left
    if re.fullmatch(r"20\d{2}", left) and right.startswith(left + "."):
        return right
    if re.fullmatch(r"20\d{2}", right) and left.startswith(right + "."):
        return left
    return None


def parse_existing_resume(text: str) -> dict | None:
    """Retain source sections and expose conflicts instead of choosing a winner.

    Extra ``field_conflicts`` and ``imported_documents`` metadata is optional for
    callers; standard resume fields and readable verification notes remain.
    """
    if not isinstance(text, str):
        return None
    parsed = [(name, result) for name, body in _documents(text) if (result := _parse_document(body))]
    if not parsed:
        return None
    merged = {"basic_info": {}, "education": [], "projects": [], "skills": [], "certificates": [],
              "verification_notes": [], "imported_documents": [], "field_conflicts": [], "personal_summary": ""}
    owners: dict[tuple, list[dict]] = {}
    conflicts: dict[tuple, dict] = {}
    projects: dict[str, dict] = {}
    schools: dict[tuple, dict] = {}
    project_statuses: dict[str, dict] = {}

    def merge_field(target: dict, item: dict, field: str, identity: tuple, source: str) -> None:
        value = item.get(field, "")
        if not value:
            return
        key = (*identity, field)
        options = owners.setdefault(key, [])
        if not any(option["value"] == value and option["source"] == source for option in options):
            options.append({"value": value, "source": source})
        old = target.get(field, "")
        if key in conflicts:
            conflicts[key]["values"] = copy.deepcopy(options)
            return
        if not old:
            target[field] = value
            return
        compatible = _compatible_date(old, value) if field in {"start_date", "end_date"} else old if old == value else None
        if compatible is not None:
            target[field] = compatible
            return
        target[field] = ""
        conflict = {"scope": identity[0], "name": identity[1], "field": field, "values": copy.deepcopy(options)}
        conflicts[key] = conflict
        merged["field_conflicts"].append(conflict)

    for source, result in parsed:
        merged["imported_documents"].append({"name": source, "project_count": len(result["projects"]),
                                             "education_count": len(result["education"])})
        for field in result["basic_info"]:
            merge_field(merged["basic_info"], result["basic_info"], field, ("basic_info", "个人信息"), source)
        for item in result["education"]:
            identity = (item["school"].casefold(), item["major"].casefold())
            if identity not in schools:
                schools[identity] = {"school": item["school"], "major": item["major"]}
                merged["education"].append(schools[identity])
            for field in ("degree", "start_date", "end_date", "highlights"):
                merge_field(schools[identity], item, field, ("education", item["school"]), source)
        for item in result["projects"]:
            identity = item["name"].casefold()
            if identity not in projects:
                projects[identity] = {"name": item["name"], "role": "", "start_date": "", "end_date": "", "description": ""}
                merged["projects"].append(projects[identity])
            target = projects[identity]
            for field in ("role", "start_date", "end_date"):
                merge_field(target, item, field, ("projects", item["name"]), source)
            for status in item.get("_release_status", []):
                merge_field(project_statuses.setdefault(identity, {}), {"release_status": status},
                            "release_status", ("projects", item["name"]), source)
            target["description"] = "\n".join(dict.fromkeys(filter(None, [*target["description"].splitlines(), *item["description"].splitlines()])))
        for field in ("skills", "certificates", "verification_notes"):
            merged[field] = list(dict.fromkeys([*merged[field], *result[field]]))
        merged["personal_summary"] = "\n".join(dict.fromkeys(filter(None, [*merged["personal_summary"].splitlines(), *result["personal_summary"].splitlines()])))
    field_labels = {"role": "职责", "start_date": "开始时间", "end_date": "结束时间", "objective": "求职方向", "name": "姓名", "release_status": "上线状态"}
    for conflict in merged["field_conflicts"]:
        options = "；".join(f"{option['source']}：{option['value']}" for option in conflict["values"])
        merged["verification_notes"].append(f"{conflict['name']}的{field_labels.get(conflict['field'], conflict['field'])}有多份资料差异（{options}），待核对后采用。")
    merged["verification_notes"] = merged["verification_notes"][:30]
    return merged
