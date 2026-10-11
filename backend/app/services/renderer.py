"""HTML 简历渲染服务：Jinja2 模板 + ResumeData → HTML 字符串。"""

import re
from urllib.parse import urlsplit
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

from app.services.resume_sections import get_resume_sections, visible_items
from app.services.skill_groups import display_skill_rows
from app.services.resume_layout import layout_css_values, resume_density

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_DIR = ROOT / "data" / "jianlimoban" / "html-template"

# fits_one_page=False 的模板在选择处标注「适合两页」（用真实内容渲染超过一页时设置）。
# 当前可选模板。其余模板文件保留但不对外暴露，便于随时恢复。
TEMPLATES = [
    {"id": "t001-jianyue", "name": "简约单栏", "style": "极简 / 标准单栏", "fits_one_page": True},
    {"id": "t002-jianyue", "name": "深蓝横幅", "style": "商务单栏", "fits_one_page": True},
    {"id": "t003-shenlan", "name": "深蓝细线", "style": "清爽单栏 / 细线分区", "fits_one_page": True},
    {"id": "t004-jianyue", "name": "灰条夹页", "style": "单栏 / 顶底装饰", "fits_one_page": True},
    {"id": "t1000", "name": "浅蓝斜切", "style": "单栏 / 色块标题", "fits_one_page": True},
    {"id": "t1001", "name": "浅蓝色块", "style": "单栏 / 变体", "fits_one_page": True},
    {"id": "t1002-jianyue", "name": "淡青平行", "style": "单栏 / 平行四边形", "fits_one_page": True},
]

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "htm", "j2"]),
)
_env.filters["pointer_escape"] = lambda value: str(value).replace("~", "~0").replace("/", "~1")
_env.filters["display_skill_rows"] = display_skill_rows


def safe_link_url(value: str) -> str:
    value = str(value or "").strip()
    if re.search(r"[\s<>\"']", value):
        return ""
    if not re.match(r"https?://", value, re.I) and re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/[^\s]*)?", value):
        value = "https://" + value
    try:
        parts = urlsplit(value)
        return value if parts.scheme in {"http", "https"} and parts.hostname else ""
    except ValueError:
        return ""


_env.filters["safe_link_url"] = safe_link_url
_env.filters['link_label'] = lambda value: str(value) if len(str(value)) <= 60 else '链接'

_PHOTO_DATA_URL = re.compile(r"\Adata:image/(?:jpeg|png);base64,[A-Za-z0-9+/]+={0,2}\Z")
_MAX_PHOTO_URL_LENGTH = 7 * 1024 * 1024


def list_templates() -> list[dict[str, Any]]:
    return TEMPLATES


def render_resume(template_id: str, data: dict[str, Any], interactive: bool = False) -> str:
    filename = f"{template_id}.html.j2"
    try:
        template = _env.get_template(filename)
    except TemplateNotFound:
        raise ValueError(f"模板不存在: {template_id}")
    # 预览只允许本机上传的 JPEG/PNG data URL，避免外部图片追踪和属性注入。
    basic = dict(data.get("basic_info") or {})
    photo = basic.get("photo")
    if not isinstance(photo, str) or len(photo) > _MAX_PHOTO_URL_LENGTH or not _PHOTO_DATA_URL.fullmatch(photo):
        basic["photo"] = ""
    sections = get_resume_sections(data)
    visible = {
        kind: [{**item, "_source_index": index} for index, item in visible_items(data, kind)]
        for kind in ("education", "work_experience", "projects", "open_source", "awards")
    }
    html = template.render(**{
        **data,
        **visible,
        "basic_info": basic,
        "resume_sections": sections,
        "has_education_section": any(section["kind"] == "education" for section in sections),
        "has_grouped_skills": any((data.get("skill_groups") or {}).values()),
        "layout_density": resume_density(data),
        "layout_css": layout_css_values(template_id, data),
    })
    if interactive:
        # Only our static bridge is executable; resume values still use Jinja autoescape.
        html = html.replace("</body>", '<script src="/static/resume-preview.js"></script>\n</body>')
    return html
