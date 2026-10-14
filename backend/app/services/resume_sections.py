"""Shared section order and field paths for preview and document export."""

from typing import Any
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


def visible_items(data: dict[str, Any], kind: str) -> list[tuple[int, dict[str, Any]]]:
    """Visible resume rows with their stable indices in the canonical document."""
    rows = []
    for index, item in enumerate(data.get(kind) or []):
        if not isinstance(item, dict) or item.get("hidden") is True:
            continue
        item = dict(item)
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
                "title": section["title"],
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
            "title": (data.get("experience_section_title") or title) if kind == "projects" else title,
            "content": "",
            "title_path": "/experience_section_title" if kind == "projects" else None,
            "content_path": None,
        }
        for kind, title in DEFAULT_SECTIONS
    ]
