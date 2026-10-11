"""Evidence-based labels and decision-reason cues shared by writer/interviewer."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

DECISION = re.compile(r'决定|选择|改为|改成|分开|加入|先.{1,30}再')
REASON = re.compile(r'为了|为了解决|避免|防止|因为|以便|目的是|原因是|为的是')
LABEL = re.compile(r'^(问题|关键决策|设计|迭代|结果|现状)[：:]\s*')
PROBLEM = r'问题|痛点|困难|错误|失败|不一致|不准|混|污染|耗时|重复|难|手动|无法|不能|不存在|把.{1,20}当|场景|需求|需要|希望'
STATUS = re.compile(r'本地|原型|演示版|模拟模型|模拟数据|已上线|已部署|闭环')


def fact_text(fact: dict) -> str:
    return str(fact.get('source_quote') or fact.get('text') or '')


def decision_without_reason(facts: list[dict]) -> bool:
    active = [f for f in facts if f.get('status', 'active') == 'active']
    return (any(f.get('kind') in {'action', 'deliverable'} and DECISION.search(fact_text(f)) for f in active)
            and not any(REASON.search(fact_text(f) + ' ' + str(f.get('text') or '')) for f in active))


def row_label(row: dict, facts: dict) -> str:
    """Pick only a category evidenced by this row, never pad missing categories."""
    text = LABEL.sub('', row.get('text') or '')
    cited = [facts[fid] for fid in row.get('fact_ids') or [] if fid in facts]
    kinds = {f.get('kind') for f in cited}
    corpus = ' '.join(fact_text(f) for f in cited)
    if kinds <= {'context'} and cited:
        if REASON.search(text + ' ' + ' '.join(str(f.get('text') or '') for f in cited)):
            return ''
        return '问题' if re.search(PROBLEM, text) else ''
    if STATUS.search(text) and STATUS.search(corpus) and (
            kinds <= {'status_limit', 'context', 'deliverable', 'result_qualitative'}
            or re.match(r'(?:完成本地|演示版使用)', text)):
        return '现状'
    if kinds & {'action', 'deliverable'} and DECISION.search(corpus) and DECISION.search(text):
        return '关键决策'
    if kinds & {'action', 'deliverable'} and re.search(r'迭代|调整|修复|改进', text):
        return '迭代'
    if kinds & {'action', 'deliverable', 'method_tool'} and re.search(r'设计|实现|开发|编写|搭建|构建|接入|解析|使用', text):
        return '设计'
    if kinds & {'result_metric', 'result_qualitative'}:
        # A sentence that describes a failure without the candidate's action is
        # the problem being solved, not an outcome.
        if not kinds & {'action', 'deliverable', 'method_tool'} and re.search(PROBLEM, text):
            return '问题'
        return '结果'
    return ''


def independent_labeled_row(row: dict, facts: dict) -> bool:
    return row_label(row, facts) in {'问题', '现状'}


def format_rows(rows: list[dict], facts: dict, style: str) -> list[dict]:
    """Presentation only: no new claim, citation or causal connection is added."""
    rows = deepcopy(rows)
    for row in rows:
        row['text'] = LABEL.sub('', row['text'])
        if style == 'labeled' and (label := row_label(row, facts)):
            row['text'] = f'{label}：{row["text"]}'
    if style == 'labeled':
        rank = {'问题': 0, '关键决策': 1, '设计': 1, '迭代': 2, '结果': 2, '现状': 2}
        rows.sort(key=lambda row: rank.get(row_label(row, facts), 1))
    return rows


def restyle_resume(data: dict, meta: dict, facts: dict, style: str) -> tuple[dict, dict]:
    data, meta = deepcopy(data), deepcopy(meta)
    for item in data.get('projects') or []:
        records = (meta.get('bullets') or {}).get(item.get('item_id')) or []
        bullets = item.get('polished_bullets') or []
        rows = []
        for index, text in enumerate(bullets):
            record = records[index] if index < len(records) else {}
            # Stale citation bindings cannot classify the current sentence.
            valid = record.get('text_hash') == hashlib.sha256(text.encode()).hexdigest()
            rows.append({'text': text, 'fact_ids': record.get('fact_ids', []) if valid else [],
                         'record': record if valid else {}})
        rows = format_rows(rows, facts, style)
        item['polished_bullets'] = [row['text'] for row in rows]
        meta.setdefault('bullets', {})[item['item_id']] = [
            {**row['record'], 'text_hash': hashlib.sha256(row['text'].encode()).hexdigest()} for row in rows]
    return data, meta
