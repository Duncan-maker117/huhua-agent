"""标题定位与正文使用同一事实边界；名称和年月始终使用确认字段。"""
import re

from app.services.fact_guard import guard_bullets
from app.services.resume_versions import text_hash


async def apply_project_headings(writers, indexed_output, items, facts, meta, model):
    candidates = []
    for item_id, written in writers.items():
        if written.section != "projects" or item_id not in indexed_output:
            continue
        item = indexed_output[item_id][1]
        source = items[item_id][1]
        corpus = "\n".join(f.get("source_quote") or f["text"] for f in source.get("facts", []))
        # 不从目标岗位推断身份，也不把团队中的独立动作推断成个人项目。
        nature = ("个人项目" if re.search(r"个人项目|独立开发者|我一个人|自己一个人", corpus) and not re.search(r"团队|小组|队友", corpus)
                  else "课程项目" if re.search(r"课程项目|课程小组|课设", corpus) else "")
        if nature:
            item["project_type"] = nature
        name = source.get("name", "")
        if name and "待补" not in name:
            item["name"] = name
        for field in ("start_date", "end_date"):
            if source.get(field):
                item[field] = source[field]
        title = written.title
        text, refs = title.positioning.strip(), title.fact_ids
        if not text and item.get("positioning"):
            record = meta.get("project_headings", {}).get(item_id, {})
            if record.get("text_hash") == text_hash(item["positioning"]):
                text, refs = item["positioning"], record.get("fact_ids", [])
        if text and len(text) <= 40 and not re.search(r"待补|[\n；;]", text):
            candidates.append({"id": "heading:" + item_id, "item_id": item_id,
                               "text": text, "fact_ids": refs})
    checked = await guard_bullets(candidates, list(facts.values()), llm=model, run_name="project_heading")
    for row, verdict in zip(candidates, checked):
        item = indexed_output[row["item_id"]][1]
        if verdict["verdict"] == "pass":
            item["positioning"] = row["text"]
            meta.setdefault("project_headings", {})[row["item_id"]] = {
                "fact_ids": row["fact_ids"], "text_hash": text_hash(row["text"])}
        else:
            item.pop("positioning", None)
            meta.setdefault("project_headings", {}).pop(row["item_id"], None)
