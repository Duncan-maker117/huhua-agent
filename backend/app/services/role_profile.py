"""Select trusted role methods and validate recruitment-only profile evidence."""

import re

from pydantic import ValidationError

from app.agents.career_prompt import ROLE_PLAYBOOKS, load_skill
from app.schemas.decoder import (
    RoleFamily,
    RoleProfile,
    RoleRequirement,
    RoleSignal,
    Seniority,
)


# Used only to select the initial handbook, without another model call. The
# decoder can refine this classification after reading the complete JD.
_ROLE_PATTERNS = (
    (
        "ai_pm",
        r"(?:ai|aigc|agent|大模型|人工智能|智能体)\s*(?:应用\s*)?产品|\bai\s+(?:product\s+manager|pm)\b",
    ),
    (
        "pm",
        r"产品(?:经理|助理|策划|运营经理)|(?:策略|b\s*端|c\s*端)产品|\bproduct\s+manager\b|\bpm\b",
    ),
    ("data", r"数据(?:分析|运营)|商业分析|\b(?:data|business)\s+analyst\b|\bbi\b"),
    ("algorithm", r"算法|机器学习|深度学习|\b(?:nlp|cv|machine\s+learning)\b"),
    ("frontend", r"前端|web\s*开发|客户端|小程序开发|\bfront[ -]?end\b"),
    (
        "backend",
        r"后端|服务端|平台开发|(?:java|go|python|c\+\+)\s*开发|\bback[ -]?end\b",
    ),
    (
        "design",
        r"(?:ui\s*[/／]?\s*ux|ui|ux|交互|视觉)\s*设计|用户研究|\b(?:ux|ui)\s+designer\b",
    ),
    ("ops", r"运营|新媒体|增长|\boperations?\b"),
)


def _classify(text: str) -> RoleFamily:
    for family, pattern in _ROLE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return family
    return "other"


def infer_role_family(text: str) -> RoleFamily:
    """Prefer a short job heading over unrelated roles mentioned in the body."""
    lines = [line.strip(" #\t") for line in text.splitlines() if line.strip()]
    for line in lines:
        if re.match(r"(?:岗位|职位|招聘职位|job\s*title)\s*[:：]", line, re.IGNORECASE):
            return _classify(line)
    for line in lines[:3]:
        if len(line) <= 80 and not re.match(
            r"(?:职责|要求|任职|工作内容|负责|需要)", line
        ):
            family = _classify(line)
            if family != "other":
                return family
    return _classify(text)


def infer_seniority(text: str) -> Seniority:
    if re.search(
        r"实习(?:生|岗|岗位)|实习(?!经历|经验)|\bintern(?:ship)?\b", text, re.IGNORECASE
    ):
        return "intern"
    if re.search(
        r"校招|校园招聘|应届|毕业生|\b(?:graduate|campus)\b", text, re.IGNORECASE
    ):
        return "campus"
    if re.search(
        r"社招|资深|高级|\b(?:senior|experienced)\b|[1-9一二三四五六七八九十]+\s*年(?:以上)?(?:相关)?(?:工作|开发|行业)?经验",
        text,
        re.IGNORECASE,
    ):
        return "experienced"
    return "unknown"


def role_playbook(family: RoleFamily) -> str:
    """Reject unknown families instead of joining an arbitrary file path."""
    return load_skill(f"role-playbooks/{ROLE_PLAYBOOKS[family]}")


def role_screening_section(family: RoleFamily) -> str:
    handbook = role_playbook(family)
    for section in re.split(r"(?m)^## ", handbook)[1:]:
        heading, _, body = section.partition("\n")
        if heading.startswith(("筛选者看什么", "通用判断")):
            return "## " + heading + "\n" + body.strip()
    return ""


def role_profile_from_direction(direction: str) -> dict:
    """Build method-based priorities, not invented employer requirements.

    Take at most the first five handbook signals (the general handbook has
    four). An empty direction produces no priorities or fabricated JD evidence.
    """
    profile = RoleProfile(
        source="direction",
        role_family=infer_role_family(direction),
        seniority=infer_seniority(direction),
    )
    if not direction.strip():
        return profile.model_dump()
    section = role_screening_section(profile.role_family)
    entries = re.findall(r"(?m)^\d+\.\s*(.+)$", section)[:5]
    for number, entry in enumerate(entries, 1):
        entry = entry.replace("**", "")
        signal, separator, detail = entry.partition("：")
        detail = detail if separator else ""
        _, evidence_marker, evidence = detail.partition("证据：")
        profile.core_signals.append(
            RoleSignal(
                id=f"s{number}",
                signal=signal,
                why="根据目标方向对应岗位手册的筛选信号；不是具体招聘方的门槛。",
                evidence_looks_like=evidence.split("弱证据：", 1)[0].strip()
                if evidence_marker
                else detail,
                source="direction",
            )
        )
        profile.requirements.append(
            RoleRequirement(
                id=f"r{number}",
                text=signal,
                source="direction",
                weight="must",
            )
        )
    return profile.model_dump()


def validate_jd_role_profile(value: object, jd_text: str) -> dict:
    """Keep only JD-backed entries, preserving valid peers of malformed entries.

    A quote match locates evidence; it does not certify semantic entailment or
    prove that the candidate meets the requirement. Direction and handbook
    content must not enter a JD profile as if the employer had stated it.
    """
    raw = value if isinstance(value, dict) else {}
    fallback = RoleProfile(
        role_family=infer_role_family(jd_text), seniority=infer_seniority(jd_text)
    )
    for field in ("role_family", "seniority"):
        try:
            setattr(
                fallback,
                field,
                getattr(
                    RoleProfile(**{field: raw.get(field, getattr(fallback, field))}),
                    field,
                ),
            )
        except (ValidationError, TypeError):
            pass
    for field, schema in (
        ("core_signals", RoleSignal),
        ("requirements", RoleRequirement),
    ):
        values = raw.get(field, [])
        if not isinstance(values, list):
            continue
        seen = set()
        for candidate in values:
            try:
                item = schema.model_validate(candidate)
            except (ValidationError, TypeError):
                continue
            quotes = item.jd_quotes if isinstance(item, RoleSignal) else [item.jd_quote]
            content = item.signal if isinstance(item, RoleSignal) else item.text
            if (
                item.source != "jd"
                or item.id in seen
                or not content.strip()
                or not quotes
                or any(not quote.strip() or quote not in jd_text for quote in quotes)
            ):
                continue
            getattr(fallback, field).append(item)
            seen.add(item.id)
    language = raw.get("jd_language", [])
    if isinstance(language, list):
        fallback.jd_language = list(
            dict.fromkeys(
                word
                for word in language
                if isinstance(word, str) and word.strip() and word in jd_text
            )
        )
    return fallback.model_dump()
