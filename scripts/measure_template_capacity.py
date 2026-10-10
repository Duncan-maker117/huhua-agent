"""用真实 PDF 渲染测量每个模板一页的容量，写入 data/jianlimoban/capacity.json。

用法：DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/measure_template_capacity.py
定义：
- chars_per_line：项目 bullet 里连续全角汉字不换行的最大个数。
- one_page_body_lines：典型结构（页眉 + 教育 1 条 + 实习 1 条 + 项目若干 + 技能 5 组 + 证书 3 条 + 1 行总结）
  填满一页时，页眉以下的文字行数（含栏目标题与条目标题行）。
- section_lines：上述满页状态下各栏目占的行数（含栏目标题），合计等于 one_page_body_lines。
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.renderer import TEMPLATES  # noqa: E402
from app.services.resume_pdf import render_resume_pdf  # noqa: E402

TITLES = {"education": "教育背景", "work_experience": "实习经历", "projects": "项目经历",
          "skills": "技能", "certificates": "证书", "self_evaluation": "自我评价"}
HEADER_LINES = 2


def _resume(projects, cpl, extra_short=0, bullet_chars=None):
    long_text = "测" * (bullet_chars or max(cpl * 2 - 3, 2))
    items = [{"item_id": f"p{i}", "name": f"虚构项目{i}", "role": "负责人", "start_date": "2026.1",
              "end_date": "2026.3", "polished_bullets": [long_text, long_text]} for i in range(projects)]
    if extra_short:
        items.append({"item_id": "px", "name": "虚构收尾项目", "role": "成员", "start_date": "2026.4",
                      "end_date": "2026.5", "polished_bullets": ["短" * (cpl // 2)] * extra_short})
    return {
        "basic_info": {"name": "虚构人", "objective": "虚构岗位", "phone": "13800000000",
                       "email": "demo@example.test", "location": "虚构市"},
        "education": [{"item_id": "e1", "school": "虚构大学", "degree": "本科", "major": "虚构专业",
                       "start_date": "2023.9", "end_date": "2027.6"}],
        "work_experience": [{"item_id": "w1", "company": "虚构公司", "title": "实习生", "start_date": "2026.1",
                             "end_date": "2026.3", "bullets": [long_text, long_text]}],
        "projects": items,
        "skills": [], "skill_groups": {f"组{i}": ["甲", "乙", "丙"] for i in range(5)},
        "certificates": ["证书一", "证书二", "证书三"],
        "self_evaluation": "短" * (cpl // 2),
        "sections": [{"id": k, "kind": k, "title": v, "content": ""} for k, v in TITLES.items()],
    }


def _pdf_lines(data, template_id):
    import pdfplumber
    raw = render_resume_pdf(template_id, data)
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        pages = len(pdf.pages)
        rows = []
        for word in pdf.pages[0].extract_words():
            if not rows or abs(rows[-1][0] - word["top"]) > 3:
                rows.append([word["top"], word["text"]])
            else:
                rows[-1][1] += word["text"]
    return pages, [text for _, text in sorted(rows)]


def chars_per_line(template_id):
    best = 0
    for n in range(14, 60):
        data = _resume(0, 20)
        data["work_experience"][0]["bullets"] = ["测" * n]
        pages, lines = _pdf_lines(data, template_id)
        joined = [line for line in lines if "测" in line]
        if len(joined) == 1:
            best = n
        else:
            break
    return best


def measure(template_id):
    cpl = chars_per_line(template_id)
    projects = 0
    while _pdf_lines(_resume(projects + 1, cpl), template_id)[0] == 1:
        projects += 1
    short = 0
    while _pdf_lines(_resume(projects, cpl, short + 1), template_id)[0] == 1:
        short += 1
    pages, lines = _pdf_lines(_resume(projects, cpl, short), template_id)
    assert pages == 1
    body = lines[HEADER_LINES:]
    sections, current = {}, None
    reverse = {title: kind for kind, title in TITLES.items()}
    for line in body:
        if line in reverse:
            current = reverse[line]
            sections[current] = 0
        if current:
            sections[current] += 1
    # 技能栏标题在模板里是自定义 title；这里栏目 id 与 title 一致，缺失时并入上一栏
    total = len(body)
    if sum(sections.values()) != total:
        sections["projects"] += total - sum(sections.values())
    return {"one_page_body_lines": total, "chars_per_line": cpl,
            "section_lines": {k: sections.get(k, 0) for k in TITLES}}


def main():
    rows = {template["id"]: measure(template["id"]) for template in TEMPLATES}
    out = {"version": 2, "status": "measured_by_pdf_render_requires_final_render_check",
           "line_definition": __doc__.strip(), "templates": rows}
    path = ROOT / "data" / "jianlimoban" / "capacity.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
