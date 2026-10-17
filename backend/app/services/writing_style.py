"""Evidence-based labels and decision-reason cues shared by writer/interviewer."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

DECISION = re.compile(r'决定|选择|改为|改成|分开|加入|先.{1,30}再|先体验后登录|'
                      r'(?:接入|开放|提供).{0,40}(?:用户|使用者|调用方).{0,30}(?:使用|调用|选择|用|操作)|'
                      r'(?:设计|采用).{0,30}(?:产品方案|交互流程|权限边界)')
REASON = re.compile(r'为了|为了解决|避免|防止|因为|以便|目的是|原因是|为的是')
LABEL = re.compile(r'^(问题与设计|问题|关键决策|决策|技术|设计|迭代|结果|现状)[：:]\s*')
PROBLEM = r'问题|痛点|困难|错误|失败|不一致|不准|混|污染|耗时|重复|繁琐|繁杂|难|手动|无法|不能|不存在|把.{1,20}当|场景|需求|需要|希望'
STATUS = re.compile(r'本地|原型|演示版|模拟模型|模拟数据|已(?:经)?上线|已部署|公网|公开访问|闭环')
EVALUATION = re.compile(r'评测|回归|验证|对比|比较|回放|断言|调整|改进|修复|更换|换模型|调参')
OWNERSHIP = re.compile(r'独立完成|独立开发|个人开发|个人项目|从需求到开发|全流程')
USAGE = re.compile(r'(?:\d+|[一二两三四五六七八九十百]+)\s*人.{0,8}(?:使用|在用|用过|试用)|(?:使用|用户|在用|试用).{0,8}\d+\s*人')


def _solution_choice(text: str) -> bool:
    # A tool list / ownership claim is not a product choice. A supported
    # purpose or tradeoff can still turn a tool integration into a decision.
    tool_only = re.search(r'工具|API|Cursor|Claude Code|技术栈', text, re.I)
    purpose = re.search(r'用户|使用者|调用方|为了|避免|放弃|而不|先.{1,30}再', text)
    return bool(DECISION.search(text) and (not tool_only or purpose))


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
    if kinds & {'action', 'deliverable', 'method_tool'} and _solution_choice(corpus) and _solution_choice(text):
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


def format_rows(rows: list[dict], facts: dict, style: str, *, role_family: str = "") -> list[dict]:
    """Presentation only: no new claim, citation or causal connection is added."""
    rows = deepcopy(rows)
    from app.agents.career_prompt import writing_structure
    structured = style == 'labeled' and writing_structure(role_family)['bullet_style'] == 'labeled'
    for row in rows:
        # A missing/stripped model label must not leave a dangling colon.
        row['text'] = LABEL.sub('', row['text'].strip()).lstrip('：: ').strip()
        label = row_label(row, facts)
        if style == 'labeled':
            cited = [facts[fid] for fid in row.get('fact_ids', []) if fid in facts]
            corpus = ' '.join(fact_text(f) for f in cited)
            if EVALUATION.search(corpus) and EVALUATION.search(row['text']):
                label = '迭代'
            elif label == '关键决策':
                label = '决策' if structured else '关键决策'
            elif (STATUS.search(row['text']) and STATUS.search(corpus)
                  or USAGE.search(row['text']) and USAGE.search(corpus)):
                label = '现状'
            elif label == '设计' or any(f.get('kind') == 'method_tool' for f in cited) and not label:
                label = '技术'
            elif OWNERSHIP.search(row['text']) and OWNERSHIP.search(corpus) and not label:
                label = '现状'
        if style == 'labeled' and label:
            row['text'] = f'{label}：{row["text"]}'
    if structured:
        # 同标签最多合并三个短句；只连接已校验表述，不补因果或删事实。
        merged = []
        for row in rows:
            label = LABEL.match(row['text'])
            clauses = len(re.split(r'[；;。]', row['text'].rstrip('。；;')))
            same = next((other for other in merged if label and other['text'].startswith(label[0])
                         and len(re.split(r'[；;。]', other['text'].rstrip('。；;'))) + clauses <= 3), None)
            if same is None:
                merged.append(row)
            else:
                same['text'] = same['text'].rstrip('。；;') + '；' + LABEL.sub('', row['text']).rstrip('。；;')
                same['fact_ids'] = list(dict.fromkeys([*same.get('fact_ids', []), *row.get('fact_ids', [])]))
                same['coverage_fact_ids'] = list(dict.fromkeys([*same.get('coverage_fact_ids', []), *row.get('coverage_fact_ids', [])]))
        rows = merged
    if style == 'labeled':
        rank = ({'问题': 0, '关键决策': 1, '决策': 1, '设计': 1, '迭代': 2, '结果': 2, '技术': 3, '现状': 4}
                if structured else {'问题': 0, '关键决策': 1, '设计': 1, '迭代': 2, '结果': 2, '现状': 2})
        rows.sort(key=lambda row: rank.get(LABEL.match(row['text'])[1] if LABEL.match(row['text']) else '', 1))
    return rows


def restyle_resume(data: dict, meta: dict, facts: dict, style: str, *, role_family: str = "") -> tuple[dict, dict]:
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
                         'coverage_fact_ids': record.get('coverage_fact_ids', []) if valid else [],
                         'record': record if valid else {}})
        rows = format_rows(rows, facts, style, role_family=role_family)
        item['polished_bullets'] = [row['text'] for row in rows]
        meta.setdefault('bullets', {})[item['item_id']] = [
            {**row['record'], 'fact_ids': row['fact_ids'], 'coverage_fact_ids': row['coverage_fact_ids'],
             'text_hash': hashlib.sha256(row['text'].encode()).hexdigest()} for row in rows]
    return data, meta
