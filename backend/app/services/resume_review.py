"""Candidate-facing text and concrete pre-export checks for one ResumeData."""

import re

from app.services.resume_sections import get_resume_sections, visible_items


def resume_to_text(data: dict) -> str:
    basic = data.get("basic_info") or {}
    lines = [f"# {basic.get('name') or '[待填写姓名]'}"]
    contact = " · ".join(str(basic.get(k) or "") for k in ("phone", "email", "location"))
    if contact.strip(" ·"):
        lines.append(contact.strip(" ·"))
    if basic.get("objective"):
        lines.append(f"求职意向：{basic['objective']}")
    if basic.get("availability"):
        lines.append(f"可实习时间：{basic['availability']}")
    for link in basic.get("links") or []:
        lines.append(f"{link.get('text', '')}：{link.get('url', '')}")
    for section in get_resume_sections(data):
        key = section['kind']
        heading = section['title']
        if key == 'custom':
            body = section.get('content') or ''
        elif key == 'skills':
            groups = data.get('skill_groups') or {}
            body = '\n'.join(f"{label}：{'、'.join(values)}" for label, values in groups.items()) if groups else '、'.join(data.get('skills') or [])
        elif key == 'certificates':
            body = '\n'.join(f'- {value}' for value in data.get('certificates') or [])
        elif key == 'self_evaluation':
            body = data.get('self_evaluation') or ''
        else:
            body = None
        if body is not None:
            if body.strip():
                if heading:
                    lines.append(f'\n## {heading}')
                lines.append(body)
            continue
        items = [item for _, item in visible_items(data, key)]
        if not items:
            continue
        lines.append(f"\n## {heading}")
        for item in items:
            title = item.get("company") or item.get("name") or item.get("school") or "[待填写]"
            detail = item.get("title") or item.get("role") or ' · '.join(part for part in (item.get('major'), item.get('degree'), item.get('pr'), item.get('summary'), item.get('level')) if part) or ""
            lines.append(" · ".join(part for part in (title, detail) if part))
            dates = ' — '.join(str(item.get(k) or '') for k in ('start_date', 'end_date')).strip(' —')
            if dates:
                lines.append(dates)
            if key == "awards" and item.get("date"):
                lines.append(item["date"])
            bullets = item.get("bullets") or item.get("polished_bullets") or []
            if not bullets and item.get("description"):
                bullets = [item["description"]]
            for bullet in bullets:
                lines.append(f"- {bullet}")
            if key == 'education' and item.get('highlights'):
                lines.append(item['highlights'])
            for link in item.get("links") or []:
                lines.append(f"{link.get('text', '')}：{link.get('url', '')}")
    return "\n".join(lines)


def _skill_parts(skill: str) -> list[str]:
    """Split a parenthetical JD phrase into words. The wrapper and inner tokens are each a skill."""
    parts = re.split(r"[（）()【】\[\]、，,；;/]|等", skill)
    tokens = [part.strip() for part in parts if part and part.strip() and part.strip() != "等"]
    return tokens or [skill.strip()]


def _contains_skill(text: str, skill: str) -> bool:
    """Keep ASCII skill names distinct while allowing adjacent Chinese prose."""
    if skill.isascii():
        return re.search(
            rf"(?<![a-z0-9_]){re.escape(skill.casefold())}(?![a-z0-9_])",
            text.casefold(),
        ) is not None
    return skill.casefold() in text.casefold()


def review_resume(data: dict, jd_info: dict | None = None) -> list[str]:
    """Return checks, never a hiring probability or pretend ATS score."""
    jd_info = jd_info or {}
    basic = data.get("basic_info") or {}
    checks = []
    for note in (data.get('verification_notes') or [])[:30]:
        if isinstance(note, str) and note.strip():
            checks.append('待核对：' + note)
    if not basic.get("name"):
        checks.append("补全姓名。")
    if not basic.get("phone") and not basic.get("email"):
        checks.append("补全至少一种联系方式。")
    if not (visible_items(data, "work_experience") or visible_items(data, "projects") or visible_items(data, "open_source")):
        checks.append("补充至少一段能证明能力的工作或项目经历。")
    text = resume_to_text(data)
    if re.search(r"\d+(?:[.,]\d+)?%?\*", text):
        checks.append("核实并替换带 * 的估算数字。")
    required = [s for s in jd_info.get("required_skills", []) if isinstance(s, str)]
    # A parenthetical phrase is covered when any of its real tokens is already in the draft.
    missing = []
    for skill in required:
        parts = [part for part in _skill_parts(skill) if len(part) >= 2 or part.isascii()]
        if parts and any(_contains_skill(text, part) for part in parts):
            continue
        if not _contains_skill(text, skill):
            missing.append(skill)
    if missing:
        checks.append("JD 中这些技能在简历文字里尚未出现，请核对是否有真实经历可补：" + "、".join(missing[:5]) + "。")
    if not checks:
        checks.append("基本信息与经历已填写。投递前请逐条核对事实、日期和导出文件的排版。")
    return checks
