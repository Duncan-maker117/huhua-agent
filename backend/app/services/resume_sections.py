"""Shared section order and field paths for preview and document export."""

from typing import Any
import re
from app.services.resume_field_hygiene import display_bullets, project_role, trim_name_punctuation


DEFAULT_SECTIONS = (
    ("education", "教育背景"),
    ("work_experience", "实习经历"),
    ("projects", "项目经历"),
    ("campus", "校园经历"),
    ("open_source", "开源贡献"),
    ("awards", "竞赛荣誉"),
    ("skills", "技能证书"),
    ("certificates", "证书"),
    ("self_evaluation", "自我评价"),
)


def work_section_title(data: dict) -> str:
    rows = [item for item in data.get("work_experience") or [] if not item.get("hidden")]
    if not rows:
        return "实习经历"
    for item in rows:
        text = " ".join([str(item.get("title") or ""), *(item.get("bullets") or [])])
        if (item.get("employment_type") == "full_time" or re.search(r"全职|正式工作|毕业.{0,8}(?:工作|采购|行政)", text)
                or (item.get("employment_type") != "internship" and "实习" not in text)):
            return "工作经历"
    return "实习经历"


def employment_type(item: dict, section: str) -> str:
    text = " ".join([str(item.get("title") or item.get("role") or ""),
                     *(str(fact.get("source_quote") or fact.get("text") or "")
                       for fact in item.get("facts") or [] if fact.get("status", "active") == "active")])
    if re.search(r"(?<!不)(?<!非)(?<!不是)兼职", text):
        return "part_time"
    if re.search(r"全职|正式工作|毕业.{0,8}(?:工作|采购|行政)", text):
        return "full_time"
    return item.get("employment_type") or ("internship" if section == "internship" or "实习" in text else "full_time")


def visible_items(data: dict[str, Any], kind: str) -> list[tuple[int, dict[str, Any]]]:
    """Visible resume rows with their stable indices in the canonical document."""
    rows = []
    for index, item in enumerate(data.get(kind) or []):
        if not isinstance(item, dict) or item.get("hidden") is True:
            continue
        item = dict(item)
        if kind == "education":
            from app.services.education_fields import clean_education_item
            item = clean_education_item(item)
        from app.services.candidate_language import PLACEHOLDER_NAMES, placeholder_name
        for field in ("name", "company", "school"):
            if placeholder_name(item.get(field, "")):
                item[field] = "[待补]"
        # Descriptive pending labels are intake UI only, never resume prose.
        for field in ("role", "title", "description", "summary", "highlights", "bullets", "polished_bullets"):
            value = item.get(field)
            def clean(text):
                for label in PLACEHOLDER_NAMES.values():
                    text = text.replace(label, "")
                return text.strip()
            if isinstance(value, str):
                item[field] = clean(value)
            elif isinstance(value, list):
                item[field] = [clean(text) if isinstance(text, str) else text for text in value]
        if kind == "projects":
            item["role"] = project_role(item.get("role") or "")
        if kind == "awards":
            item["name"] = trim_name_punctuation(item.get("name"))
        if kind in {"campus", "open_source", "awards"}:
            item["_display_bullets"] = display_bullets(item, kind)
        rows.append((index, item))
    return rows


def get_resume_sections(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep explicit metadata intact; missing/None metadata uses legacy defaults.

    Builtin bodies stay in their original fields. Removing a section therefore
    changes visibility without losing the user's source content.
    """
    sections = data.get("sections")
    if sections is not None:
        return [
            {
                "id": section["id"],
                "kind": section["kind"],
                "title": (work_section_title(data) if section["kind"] == "work_experience"
                          and section["title"] in {"实习经历", "工作/实习经历"} else section["title"]),
                "content": section.get("content", ""),
                "title_path": f"/sections/{index}/title",
                "content_path": f"/sections/{index}/content" if section["kind"] == "custom" else None,
            }
            for index, section in enumerate(sections)
        ]
    return [
        {
            "id": kind,
            "kind": kind,
            "title": ((data.get("experience_section_title") or title) if kind == "projects" else
                      work_section_title(data) if kind == "work_experience" else title),
            "content": "",
            "title_path": "/experience_section_title" if kind == "projects" else None,
            "content_path": None,
        }
        for kind, title in DEFAULT_SECTIONS
    ]
