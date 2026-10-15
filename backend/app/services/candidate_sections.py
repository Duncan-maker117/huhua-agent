"""Literal fallback for explicitly labelled contribution lists and header fields."""

import re
import uuid

from app.services.candidate_language import constraint_only, literal_item_name, safe_item_name, safe_objective
from app.services.experience_dates import parse_month_range
from app.services.resume_facts import new_fact
from app.services.resume_field_hygiene import trim_name_punctuation


SECTION_LABELS = {"学生组织": "campus", "校园经历": "campus", "社团经历": "campus", "校园活动": "campus", "开源贡献": "open_source", "开源经历": "open_source",
                  "竞赛荣誉": "awards", "竞赛和荣誉": "awards", "竞赛与荣誉": "awards"}
_COMPANY_LABELS = {"公司": "work_experience", "公司名称": "work_experience", "实习公司": "internship"}
ROLE_FIELD = re.compile(r"^(?:职务|角色|岗位)[：:][ \t]*(.+)$")
DATE_FIELD = re.compile(r"^(?:时间|课程项目时间|项目时间|工作时间|实习时间)[：:][ \t]*(.+)$")
_OTHER_SECTION = re.compile(r"^(?:基本信息|教育背景|教育经历|教育|课程项目|项目名称|项目经历|工作经历|实习经历|"
                            r"技能|专业技能|产品与技术能力|技能与工具|证书|自我评价|个人总结)\s*[：:]?")
_PR = re.compile(r"\bPR\s*#?\s*\d+|https?://github\.com/[^\s)）]+/pull/\d+", re.I)
_URL = re.compile(r"https?://[^\s,，;；)）]+", re.I)
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


def literal_links(text: str) -> list[dict]:
    rows = [{"text": m[1], "url": m[2]} for m in _MARKDOWN_LINK.finditer(text)]
    known = {row["url"] for row in rows}
    rows.extend({"text": url, "url": url} for url in _URL.findall(text) if url not in known)
    return rows


def parse_header_fields(text: str) -> dict:
    """Preserve the supplied URL/domain/handle verbatim; never invent a URL."""
    basic = {}
    for field, pattern in (
        ("name", r"(?:^|[\n，,；;。])[ \t]*(?:我的)?姓名[ \t]*(?:是|为|[：:])?[ \t]*([^\s，,；;。:：、]{1,30})"),
        ("phone", r"(?:联系电话|手机号码|手机号|电话|手机)\s*(?:是|为|[：:])?\s*(\+?\d[\d \t()-]{5,}\d)(?!\d)"),
        ("email", r"(?:电子邮箱|邮箱|email)\s*(?:是|为|[：:])?\s*([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})"),
        ("location", r"(?:所在地|居住地|城市|现居|人在)\s*(?:是|为|[：:])?\s*([\u4e00-\u9fff]{2,12})(?=[\s，,；;。]|$)"),
        ("objective", r"(?:求职意向|求职方向)[ \t]*(?:是|为|[：:])[ \t]*([^\n，,；;。]+)"),
    ):
        if match := re.search(pattern, text, re.I):
            value = match[1].strip()
            if field != "objective" or safe_objective(value):
                basic[field] = value
    links = []
    for label, value in re.findall(
            r"(GitHub|个人主页|个人网站|主页|网站)(?:\s*(?:是|为|[：:])\s*|\s+)"
            r"([^\s，,；;。]+)", text, re.I):
        value = value.strip('"“”「」')
        if value:
            links.append({"text": "GitHub" if label.lower() == "github" else label, "url": value})
    if links:
        basic["links"] = list({(row["text"], row["url"]): row for row in links}.values())
    match = re.search(r"(?:可实习时间|实习时间|可到岗时间)\s*[：:]\s*([^\n。]+)", text)
    if match:
        value = re.split(r"[；;]|(?:教育|技能|项目经历|电话|邮箱)\s*[：:]", match[1])[0].strip()
        if value:
            basic["availability"] = value
    return basic


def contribution_fields(line: str) -> dict:
    """Repository heading, optional supplied description and PR token."""
    plain = _MARKDOWN_LINK.sub(lambda m: m[1], line).replace("**", "").strip()
    plain = re.sub(r"^(?:[-*•▸]\s*|\d+[.、]\s*)", "", plain)
    plain = re.sub(r"^(?:开源贡献|开源经历)\s*[：:]\s*", "", plain)
    pr = _PR.search(line)
    prefix = plain[:_PR.search(plain).start()] if _PR.search(plain) else re.split(r"[：:｜|]", plain, maxsplit=1)[0]
    summary = re.search(r"[（(]([^）)]+)[）)]", prefix)
    name = re.split(r"[（(｜|]", prefix, maxsplit=1)[0].strip(" -—：:，,·")
    fields = {"name": name}
    if summary:
        fields["summary"] = summary[1]
    if pr:
        fields["pr"] = pr[0]
    return fields


def parse_labelled_items(text: str, *, source: str = "chat", turn_id: str = "", source_name: str = "") -> dict:
    """Every explicit list row survives even if a model only extracted its first row.

    Only labelled candidate sections are parsed. Callers exclude JD/reference
    material before invoking this helper. Wrapped lines stay with their PR.
    """
    rows = {"campus": [], "open_source": [], "awards": []}
    section = ""
    pending = []

    def flush():
        if not section or not pending:
            pending.clear()
            return
        quote = "\n".join(pending).strip()
        pending.clear()
        if not quote or re.search(r"待确认|待核实|待补|假设|虚构", quote):
            return
        plain = _MARKDOWN_LINK.sub(lambda m: m[1], quote).replace("**", "")
        body = None
        field_quotes = {}
        lines = plain.splitlines()
        structured = (len(lines) > 1 and safe_item_name(lines[0])
                      and not re.search(r'[｜|，,；;：:]', lines[0]))
        if section in {"campus", "work_experience", "internship"} and structured:
            # Field blocks are records, not a single action. Keep sentence
            # boundaries and source spans before making atomic evidence.
            name = lines[0].strip()
            fields = {"name": name}
            if section != "campus":
                fields["company"] = name
            body = []
            for line in lines[1:]:
                if role := ROLE_FIELD.fullmatch(line):
                    fields["role"] = role[1]
                    field_quotes["role"] = line
                elif date := DATE_FIELD.fullmatch(line):
                    if dates := parse_month_range(date[1]):
                        for field, value in zip(("start_date", "end_date"), dates):
                            fields[field] = value
                            field_quotes[field] = line
                    else:
                        body.append(line)  # An invalid range stays reviewable.
                else:
                    body.extend(part.strip().rstrip('；;') for part in re.findall(r"[^。；;\n]+[。；;]?", line) if part.strip())
        elif section in {"work_experience", "internship"}:
            return  # A one-line company mention is still conversational intake.
        elif section == "campus":
            name = literal_item_name(plain, "campus")
            if not name:
                return
            fields = {"name": name}
            role = re.search(r"(?:担任|[|｜])\s*([^，,。；;|｜\n]{1,16}(?:部长|干事|委员|主席|负责人))", plain)
            if role:
                fields["role"] = role[1]
        elif section == "open_source":
            fields = contribution_fields(quote)
            if not fields["name"] or (not _PR.search(quote) and not re.search(r"贡献|修复|提交|维护|实现", quote)):
                return
        else:
            level = re.search(r"Top\s*\d+|[一二三]等奖|(?:金|银|铜)奖|第[一二三四五六七八九十\d]+名", plain, re.I)
            date = re.search(r"20\d{2}(?:[.年/-]\d{1,2}(?:月)?)?", plain)
            name = plain[:level.start()].strip(" ，,·-—：:") if level else plain.strip()
            # A leading date is optional metadata, not part of the award name.
            if date and name.startswith(date[0]):
                name = name[len(date[0]):].strip(" ，,·-—：:")
            fields = {"name": trim_name_punctuation(name or plain)}
            if level:
                fields["level"] = level[0]
            if date:
                fields["date"] = date[0]
        item = {"item_id": str(uuid.uuid4()), **fields, "facts": [], "raw_notes": [quote]}
        for field, value in fields.items():
            if value and (value in plain or field in field_quotes):
                fact = new_fact(value, kind="role" if field == "role" else "context",
                                quote=field_quotes.get(field, value), source=source, turn_id=turn_id, source_name=source_name)
                fact["field"] = field
                item["facts"].append(fact)
        # Structured bodies are atomic; unstructured contribution rows retain
        # their existing literal fallback and the complete raw note.
        for clause in body if body is not None else [plain]:
            kind = "action" if section != "awards" else "result_qualitative"
            if body is not None and (constraint_only(clause) or re.search(r'没有|尚未|未上线|并非|计划', clause)):
                kind = "status_limit"
            item["facts"].append(new_fact(clause, kind=kind, quote=clause if body is not None else quote,
                                          source=source, turn_id=turn_id, source_name=source_name))
        if links := literal_links(quote):
            item["links"] = links
        rows.setdefault(section, []).append(item)

    for raw in text.splitlines():
        line = re.sub(r"^\s*#{1,6}\s*", "", raw).strip().replace("**", "")
        labels = {**SECTION_LABELS, **_COMPANY_LABELS}
        label = re.match(r"^(" + "|".join(labels) + r")(?:[ \t]*[：:][ \t]*(.*)|[ \t]*)$", line)
        if label:
            flush()
            section = labels[label[1]]
            line = label[2] or ""
        elif _OTHER_SECTION.match(line):
            flush()
            section = ""
        if not section or not line:
            continue
        parts = re.split(r"[；;]", line) if section == "awards" else [line]
        for part in parts:
            part = part.strip()
            marked = bool(re.match(r"^(?:[-*•▸]\s*|\d+[.、]\s*)", part))
            clean = re.sub(r"^(?:[-*•▸]\s*|\d+[.、]\s*)", "", part).strip()
            if not clean:
                continue
            if pending and (marked or section == "awards" or _PR.search(clean)):
                flush()
            pending.append(clean)
    flush()
    return rows
