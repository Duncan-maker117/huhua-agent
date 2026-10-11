"""Resume page constraints, heuristic writer budget and actual PDF measurements.

This module changes only a copied投递文稿. It never writes collected_info or
claims a one-page result from line estimates. The caller must render after
each change and stop after at most MAX_COMPRESSION_ROUNDS writer attempts.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[3]
CAPACITY_PATH = ROOT / "data" / "jianlimoban" / "capacity.json"
DEFAULT_TEMPLATE_ID = "t001-jianyue"
MAX_COMPRESSION_ROUNDS = 2
EXPERIENCE_SECTIONS = ("work_experience", "projects", "open_source")


def resume_data_hash(resume_data: Mapping[str, Any]) -> str:
    """Bind a page measurement to the exact structured document rendered."""
    encoded = json.dumps(resume_data, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _capacity_data() -> dict[str, Any]:
    return json.loads(CAPACITY_PATH.read_text(encoding="utf-8"))


def load_template_capacity(template_id: str) -> dict[str, Any]:
    """Return one template's estimated line budget, never a rendered verdict."""
    rows = _capacity_data()["templates"]
    if template_id not in rows:
        raise ValueError("Unknown resume template capacity")
    row = rows[template_id]
    if (sum(row["section_lines"].values()) != row["one_page_body_lines"]
            or row["chars_per_line"] <= 0):
        raise ValueError("Invalid resume template capacity")
    return deepcopy(row)


def normalize_session_constraints(
    current: Mapping[str, Any] | None = None,
    *,
    seniority: str = "unknown",
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge durable constraints; an absent override cannot erase an earlier choice."""
    result = dict(current or {})
    result.setdefault("page_limit", 2 if seniority == "experienced" else 1)
    result.setdefault("language", "zh-CN")
    result.setdefault("template_id", DEFAULT_TEMPLATE_ID)
    result.update(overrides or {})
    page_limit = result["page_limit"]
    if type(page_limit) is not int or page_limit not in (1, 2):
        raise ValueError("page_limit must be 1 or 2")
    language = result["language"]
    if not isinstance(language, str) or not language.strip() or len(language) > 32:
        raise ValueError("language must be a nonempty short string")
    result["language"] = language.strip()
    load_template_capacity(result["template_id"])
    return result


def writer_capacity_budget(constraints: Mapping[str, Any]) -> dict[str, Any]:
    """An approximate prompt budget; caller must still verify the exported PDF."""
    normalized = normalize_session_constraints(constraints)
    row = load_template_capacity(normalized["template_id"])
    pages = normalized["page_limit"]
    chars_per_line = row["chars_per_line"]
    return {
        "status": "heuristic_not_rendered",
        "template_id": normalized["template_id"],
        "page_limit": pages,
        "body_lines": row["one_page_body_lines"] * pages,
        "section_lines": {key: value * pages for key, value in row["section_lines"].items()},
        "chars_per_line": chars_per_line,
        "max_bullet_lines": 2,
        "max_bullet_chars_estimate": min(chars_per_line * 2, 60),
        "bullet_caps": {"lead": 3, "keep": 2, "brief": 1},
        "max_compression_rounds": MAX_COMPRESSION_ROUNDS,
    }


def measure_rendered_pages(
    resume_data: dict[str, Any],
    constraints: Mapping[str, Any],
    *,
    pdf_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Count pages in a production-rendered PDF, with failure left unknown.

    Supplied PDF bytes must have been produced for this exact resume version by
    the caller. Omitting them calls the production renderer directly.
    """
    normalized = normalize_session_constraints(constraints)
    result = {"status": "render_error", "pages": None, "page_limit": normalized["page_limit"],
              "within_page_limit": None, "template_id": normalized["template_id"],
              "data_hash": resume_data_hash(resume_data),
              "source": "production_render_resume_pdf" if pdf_bytes is None else "caller_supplied_pdf_bytes"}
    try:
        if pdf_bytes is None:
            from app.services.resume_pdf import measure_resume_pdf_layout

            layout = measure_resume_pdf_layout(normalized["template_id"], resume_data, normalized['page_limit'])
            result.update(layout)
            pages = layout['pages']
        else:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages = len(pdf.pages)
                overflow_pages = pdf.pages[normalized['page_limit']:]
                heights = [max((char['bottom'] for char in page.chars), default=0)
                           - min((char['top'] for char in page.chars), default=0) for page in overflow_pages]
                if overflow_pages and any(page.chars for page in overflow_pages):
                    result.update(overflow_height_px=round(sum(heights) * 96 / 72, 2),
                                  overflow_page_ratio=round(sum(height / page.height for height, page
                                                               in zip(heights, overflow_pages)), 4),
                                  overflow_lines=sum(len({round(char['top'], 0) for char in page.chars})
                                                     for page in overflow_pages))
        if pages < 1:
            raise ValueError("Rendered PDF has no pages")
        result.update(status="rendered", pages=pages, within_page_limit=pages <= normalized["page_limit"])
    except Exception as exc:
        result["error_type"] = type(exc).__name__
    return result


def small_page_overflow(measurement: Mapping[str, Any] | None) -> bool:
    page = measurement or {}
    ratio = page.get('overflow_page_ratio')
    return (page.get('within_page_limit') is False
            and page.get('pages') == page.get('page_limit', 1) + 1
            and isinstance(ratio, (int, float)) and 0 < ratio < 0.15)


def revalidate_committed_page_check(resume_data: dict[str, Any], resume_meta: dict[str, Any],
                                    constraints: Mapping[str, Any] | None,
                                    *, content_changed: bool = False,
                                    pre_sanitization_hash: str = "") -> dict[str, Any]:
    """Render the exact committed draft, tracking sanitization separately from fit."""
    result = deepcopy(resume_meta or {})
    previous = result.get("page_check")
    if not isinstance(previous, dict) or not previous:
        return result
    effective = dict(constraints or {})
    for field in ("page_limit", "template_id"):
        if field not in effective and previous.get(field) is not None:
            effective[field] = previous[field]
    if (previous.get("status") == "rendered" and previous.get("data_hash") == resume_data_hash(resume_data)
            and all(previous.get(field) == effective.get(field) for field in ("page_limit", "template_id"))
            and not content_changed):
        return result
    measured = measure_rendered_pages(resume_data, effective)
    if content_changed:
        measured["content_integrity"] = "changed_by_fact_sanitizer"
        measured["compression_success"] = False
        measured["pre_sanitization_data_hash"] = pre_sanitization_hash
    result["page_check"] = measured
    return result


def _visible_bullets(resume_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for section in EXPERIENCE_SECTIONS:
        for index, item in enumerate(resume_data.get(section) or []):
            if not isinstance(item, dict) or item.get("hidden") is True:
                continue
            field = "polished_bullets" if section == "projects" else "bullets"
            for bullet_index, text in enumerate(item.get(field) or []):
                if isinstance(text, str) and text.strip():
                    rows.append({"path": f"/{section}/{index}/{field}/{bullet_index}",
                                 "characters": len(text), "text": text})
    return rows


def plan_compression(
    resume_data: dict[str, Any],
    match_plan: Mapping[str, Any] | None,
    *,
    round_number: int = 1,
    constraints: Mapping[str, Any] | None = None,
    allow_hiding: bool = True,
    page_check: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Rank reversible document actions; shortening remains a writer request.

    The caller invokes this only after a measured overflow, applies actions in
    order, and rerenders. No action claims the result fits a page.
    """
    if type(round_number) is not int or not 1 <= round_number <= MAX_COMPRESSION_ROUNDS:
        raise ValueError("Compression round exceeds the two-round limit")
    plan = match_plan or {}
    small_overflow = small_page_overflow(page_check)
    treatments = {row.get("item_id"): row.get("treatment") for row in plan.get("experience_plan", [])
                  if isinstance(row, dict) and row.get("item_id")}
    actions: list[dict[str, Any]] = []
    for section in EXPERIENCE_SECTIONS:
        for index, item in enumerate(resume_data.get(section) or []):
            if not isinstance(item, dict) or item.get("hidden") is True:
                continue
            item_id = item.get("item_id")
            if allow_hiding and not small_overflow and treatments.get(item_id) == "brief":
                actions.append({"op": "hide_item", "target": f"/{section}/{index}",
                                "item_id": item_id, "reason": "brief_to_backup", "writer_required": False})
    for section in EXPERIENCE_SECTIONS:
        for index, item in enumerate(resume_data.get(section) or []):
            if not isinstance(item, dict) or item.get("hidden") is True:
                continue
            item_id = item.get("item_id")
            if treatments.get(item_id) != "keep" and not small_overflow:
                continue
            field = "polished_bullets" if section == "projects" else "bullets"
            if len(item.get(field) or []) > 1:
                actions.append({"op": "merge_bullets", "target": f"/{section}/{index}/{field}",
                                "item_id": item_id, "max_bullets": 1,
                                "reason": "keep_merge_one_bullet", "writer_required": True})
    # Rank the writer request against the document *after* earlier reversible
    # actions; otherwise it may target a bullet we just hid or trimmed.
    projected = apply_deterministic_compression(resume_data, actions)
    bullets = _visible_bullets(projected)
    for longest in sorted(bullets, key=lambda row: row['characters'], reverse=True)[:2 if small_overflow else 1]:
        chars_per_line = writer_capacity_budget(constraints or {})["chars_per_line"]
        actions.append({"op": "shorten_bullet", "target": longest["path"],
                        "current_chars": longest["characters"],
                        "target_max_chars_estimate": max(1, min(longest["characters"] - 1, chars_per_line * 2)),
                        "reason": "longest_bullet", "writer_required": True})
    sections = resume_data.get("sections")
    visible_self_evaluation = sections is None or any(
        isinstance(section, dict) and section.get("kind") == "self_evaluation" for section in sections)
    if visible_self_evaluation and resume_data.get("self_evaluation"):
        actions.append({"op": "clear_self_evaluation", "target": "/self_evaluation",
                        "reason": "last_resort_summary_removal", "writer_required": False})
    return actions


def apply_deterministic_compression(
    resume_data: dict[str, Any], actions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply the deterministic prefix to a copy; stop before a writer action.

    This prevents clearing a summary before the requested bullet rewrite has
    had a chance to fit. The caller may later pass the remaining actions.
    """
    result = deepcopy(resume_data)
    for action in actions:
        op = action.get("op")
        if action.get("writer_required") or op in {"shorten_bullet", "merge_bullets"}:
            break
        if op == "clear_self_evaluation":
            result["self_evaluation"] = ""
            continue
        if op not in {"hide_item", "cap_bullets"}:
            raise ValueError("Unsupported compression action")
        parts = str(action.get("target") or "").split("/")
        if (len(parts) < 3 or parts[0] != "" or parts[1] not in EXPERIENCE_SECTIONS
                or not parts[2].isdigit()):
            raise ValueError("Invalid compression target")
        section, index = parts[1], int(parts[2])
        if index >= len(result.get(section) or []):
            raise ValueError("Compression target index is out of range")
        item = result[section][index]
        if item.get("item_id") != action.get("item_id"):
            raise ValueError("Compression target no longer matches item_id")
        if op == "hide_item":
            if len(parts) != 3:
                raise ValueError("Invalid hide_item target")
            item["hidden"] = True
        else:
            field = "polished_bullets" if section == "projects" else "bullets"
            if len(parts) != 4 or parts[3] != field or action.get("max_bullets") != 1:
                raise ValueError("Invalid cap_bullets target")
            item[field] = list(item.get(field) or [])[:1]
    return result
