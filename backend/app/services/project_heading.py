"""标题定位与正文使用同一事实边界；名称和年月始终使用确认字段。"""
import re

from app.services.fact_guard import guard_bullets
from app.services.resume_versions import text_hash
from app.services.writer_diagnostics import attempt, delivered, failure, line_trace, verdict_failures


def fallback_positioning(item_id: str, facts: dict) -> dict | None:
    """Only sourced audience/category; no inferred outcomes or product features."""
    from app.services.labeled_writer import rule_slot
    evidence = [f for f in facts.values() if f.get('item_id') == item_id
                and f.get('status', 'active') == 'active' and not f.get('field')
                and rule_slot(f) in {'问题', '现状', '标题性质', '决策'}]
    audience = next(((word, f['id']) for word in ('学生', '用户') for f in evidence
                     if word in f['text']), None)
    category = next(((word, f['id']) for word in ('AI简历助手', '简历助手', '简历工具') for f in evidence
                     if word in re.sub(r'\s+', '', f['text'])), None)
    if category is None:
        # A literal resume function supports its neutral category, not an AI
        # capability just because a competitor pain mentions AI.
        category = next((('简历工具', f['id']) for f in evidence
                         if re.search(r'写简历|撰写简历|生成.{0,4}简历|简历.{0,8}生成', f['text'])), None)
    if not audience or not category:
        return None
    return {'id': 'heading:' + item_id, 'item_id': item_id,
            'text': f'面向{audience[0]}的{category[0]}',
            'fact_ids': list(dict.fromkeys([audience[1], category[1]]))}


async def _check_heading(row, facts, model):
    if not row['text'] or len(row['text']) > 40 or re.search(r'待补|[\n；;]', row['text']):
        return {'verdict': 'fail', 'failures': [failure('empty_or_invalid_positioning')]}
    checks = await guard_bullets([{**row, 'claim_kind': 'positioning'}], list(facts.values()),
                                llm=model, run_name='project_heading')
    verdict = checks[0]
    return {**verdict, 'failures': verdict_failures(verdict)}


async def apply_project_headings(writers, indexed_output, items, facts, meta, model, *,
                                 call=None, writer_model=None, role_family='', diagnostic=None):
    for item_id, written in writers.items():
        if written.section != "projects" or item_id not in indexed_output:
            continue
        item = indexed_output[item_id][1]
        source = items[item_id][1]
        corpus = "\n".join(f.get("source_quote") or f["text"] for f in source.get("facts", []))
        # 不从目标岗位推断身份，也不把团队中的独立动作推断成个人项目。
        personal = (source.get('role') in {'个人开发', '独立开发'}
                    or re.search(r"个人(?:开发)?项目|独立开发者|我一个人|自己一个人", corpus))
        nature = ("个人项目" if personal and not re.search(r"团队|小组|队友", corpus)
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
        row = {'id': 'heading:' + item_id, 'item_id': item_id, 'text': text, 'fact_ids': refs}
        own = [f for f in facts.values() if f.get('item_id') == item_id and f.get('status', 'active') == 'active']
        trace = line_trace(diagnostic if diagnostic is not None else {}, item_id, 'positioning', [f['id'] for f in own])
        verdict = await _check_heading(row, facts, model)
        attempt(trace, 'model', text, refs, verdict)
        handling = 'model'
        if verdict['verdict'] != 'pass' and call is not None:
            from app.schemas.writer import RepairOutput
            trace['retry_count'] = 1
            try:
                output = await call(writer_model, RepairOutput,
                    {'id': row['id'], 'facts': own, 'previous_attempt': trace['attempts'][-1],
                     'failures': verdict['failures']},
                    '修复本项目的产品定位：只根据事实写“面向 X 的 Y”式短语，40字以内；'
                    '不添加身份、功能或成果。返回 RepairOutput.bullets 恰好一项，id 原样，fact_ids 引用支持定位的事实。',
                    role_family, run_name='writer_positioning_repair')
                proposals = [b for b in output.bullets if b.id == row['id']]
                proposal = proposals[0] if len(proposals) == 1 else None
                row = {**row, 'text': proposal.text if proposal else '', 'fact_ids': proposal.fact_ids if proposal else []}
                verdict = await _check_heading(row, facts, model)
                attempt(trace, 'retry', row['text'], row['fact_ids'], verdict)
                handling = 'retry'
            except Exception as error:
                attempt(trace, 'retry', '', [], {'verdict': 'fail', 'failures': [
                    failure('repair_unavailable', error_type=type(error).__name__)]})
            if verdict['verdict'] != 'pass':
                fallback = fallback_positioning(item_id, facts)
                if fallback:
                    row = fallback
                    verdict = {'verdict': 'pass', 'failures': [], 'method': 'sourced_audience_and_category'}
                    attempt(trace, 'deterministic_fallback', row['text'], row['fact_ids'], verdict)
                    handling = 'deterministic_fallback'
        if verdict["verdict"] == "pass":
            item["positioning"] = row["text"]
            meta.setdefault("project_headings", {})[row["item_id"]] = {
                "fact_ids": row["fact_ids"], "text_hash": text_hash(row["text"])}
            delivered(trace, row, handling)
        else:
            item.pop("positioning", None)
            meta.setdefault("project_headings", {}).pop(row["item_id"], None)
            trace['final_handling'] = 'empty_insufficient_evidence'
