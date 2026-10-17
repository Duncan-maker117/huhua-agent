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


def direction_focus(info: dict, direction: str) -> str:
    """Describe what to look for, never assert that the candidate has it."""
    profile = info.get("role_profile") or {}
    if (profile.get("source") == "market_sample"
            and profile.get("status") not in {"pending", "failed"}
            and profile.get("direction", direction) == direction):
        # Prefer concrete skills, then duties; one-off items are not high frequency.
        labels = []
        for field in ("skills", "responsibilities"):
            rows = [row for row in profile.get(field, []) if isinstance(row, dict)
                    and isinstance(row.get("count"), int) and row["count"] >= 2
                    and isinstance(row.get("text"), str) and row["text"].strip()]
            for row in sorted(rows, key=lambda row: -row["count"]):
                if row["text"] not in labels:
                    labels.append(row["text"])
        if labels:
            focus = " / ".join(labels[:2])
            return f"我会优先找能体现 {focus} 实战能力的经历。"
    # Reload trusted screening priorities: pending/failed market payloads are
    # not ready evidence, and role keywords themselves are not capabilities.
    signals = role_profile_from_direction(direction)["core_signals"][:2]
    spoken = {
        "技术栈与 JD 对得上": "实际用过的语言、框架或数据库",
        "自己实现了什么": "自己实现过的模块或接口",
        "技术栈匹配": "实际用过的前端技术",
        "自己负责的页面/组件/工程能力": "自己实现过的页面或组件",
        "相关性第一": "与目标岗位相关的工作",
        "本人贡献": "你在其中具体做了什么",
    }
    focus = "，以及".join(spoken.get(item["signal"], item["signal"]) for item in signals)
    return f"我会按岗位手册的筛选重点，先了解{focus}，再找对应的真实经历。"


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
