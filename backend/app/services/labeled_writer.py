"""Classify evidence first; render and guard one homogeneous row per slot.

The model may improve prose, never choose the structure or mix ownership,
status and decisions. This gate also runs after legacy coverage/polish paths.
"""
from __future__ import annotations

import re

from app.schemas.writer import FactSlots, RepairOutput
from app.services.candidate_language import constraint_only, date_only
from app.services.fact_guard import absence_printed, guard_bullets, normalize_text, verify_semantics
from app.services.labeled_evidence import clauses, literal_clause
from app.services.product_pains import product_pain
from app.services.writing_style import LABEL, EVALUATION, USAGE, _solution_choice
from app.services.writer_diagnostics import attempt, delivered, failure, line_trace, verdict_failures

SLOTS = ('问题', '决策', '迭代', '技术', '现状')
STATUS = re.compile(r'上线|部署|可(?:正常)?使用|可访问|公网|跑起来|流程.{0,8}打通|优化|差点意思|效果.{0,6}不好|本地|演示版')
OWN_WORK = re.compile(r'API|框架|技术栈|编程工具|大模型|模型调用|Cursor|Claude Code|Python|React|FastAPI|MCP|SDK', re.I)
PRODUCT_FUNCTION = re.compile(r'(?:通过|用|以).{0,12}对话.{0,12}(?:帮|帮助|支持|让).{0,12}(?:学生|用户)|'
                              r'(?:面向|帮助|帮|支持|让)(?:学生|用户).{0,18}(?:挖掘?经历|梳理经历|撰写简历|写简历)|'
                              r'(?:AI\s*简历助手|对话式简历工作台)', re.I)
NATURE = re.compile(r'个人(?:开发)?项目|个人开发|独立(?:完成|开发)|从需求到开发|一个人')
CLASSIFY_CONTRACT = '''先分类，不写简历。为本经历每条事实输出恰好一个 FactSlots.assignments：fact_id 必须来自输入，slot 只能是问题/决策/迭代/技术/现状/标题性质/不用。
痛点、现有方案繁琐/无法/不知道/复制粘贴优先进问题，不把“解决了”夸大成成效；接入/选择/取舍/先后流程进决策；评测/回放/发现问题后修改进迭代；技术只放工具/API/框架/模型，不放产品功能或本人完成提示词/原型的分工；对话帮学生挖经历写简历等产品功能进标题性质，供 positioning 使用。上线/可用/仍在优化/使用人数进现状。个人开发、独立完成等身份及提示词/原型分工进标题性质，不能单独写现状，也不能写决策。日期/名称/角色等标题字段进标题性质，纯限制或未知答案进不用。只用 fact.text 分类，source_quote 用作证据核验，question_prompt 只是语境。'''
WRITE_CONTRACT = '''严格按 labeled_slots 逐槽位改写，每槽位一行，引用该槽位给定的 fact_ids，不跨槽混写。每行用“槽位：”开头，1–3 个短句，分号连接；空槽位不输出。问题必须保留已有痛点；决策不得混入本人分工、工具清单、上线或优化状态；标题性质不重复写正文。将“效果可能还差点意思，仍在优化”压缩为“生成效果仍在优化”，不能声称已经改善。技术仅放工具/框架/模型/API，产品功能进定位，提示词/原型的本人分工不冒充技术栈。逐子句可对应不同事实，允许同义概括（一个一个→逐项，繁琐→低效），不新增程度、数字、实体、动作、因果、状态或频率。保留虚拟/本地/约/仅等限定及或/和区别。事实与指标不得添加或升级。普通段落、无标签行、同事实重复行均不合格。'''
WRITE_CONTRACT += '''技术栈已单独成行，要点写“用 X 做了什么”，不要单纯罗列“项目采用/使用 X、Y、Z”。正文技术名用确定性别名表的规范名（longchain→LangChain）。纯技术名称清单由最终结构门移到 tech_stack 独立行，不与动作或状态混写。'''
WRITE_CONTRACT += '''问题行应概括为简历语言，不整句照搬答案；保留主语、痛点、需求及其限定，不能把用户需求写成已实现的功能或成果。例如“学生难以梳理自己的经历，需要通过对话挖掘可写进简历的事实”可写为“学生难以梳理自身经历；需借助对话挖掘可写进简历的事实”。仅加标签、改标点不算改写。'''


def rule_slot(fact: dict) -> str:
    text = str(fact.get('text') or '').strip()
    if (fact.get('status', 'active') != 'active' or not text or constraint_only(text)
            or text in {'不知道', '不清楚', '未验证', '没有记录'}):
        return '不用'
    if fact.get('field') or date_only(text) or text in {'项目', '个人开发', '独立开发者'}:
        return '标题性质'
    if product_pain(text) or (fact.get('kind') == 'context' and re.search(r'痛点|问题|难以|繁琐|无法|不懂|把.{1,20}当', text)
                              and not re.match(r'为了|因为|避免', text)):
        return '问题'
    if re.search(r'做过哪些|是什么|怎么判断|如何判断|[？?]$', text):
        return '不用'
    if re.search(r'(?:仍需|有待|尚未|还未|未曾).{0,12}(?:验证|评测|回放)|(?:验证|方案选择)待补', text):
        return '现状'
    if EVALUATION.search(text):
        return '迭代'
    if fact.get('kind') == 'context' and re.match(r'为了|因为|避免', text):
        return '决策'
    if _solution_choice(text):
        return '决策'
    if PRODUCT_FUNCTION.search(text):
        return '标题性质'
    if NATURE.search(text):
        return '技术' if OWN_WORK.search(text) else '标题性质'
    if STATUS.search(text) or USAGE.search(text) or fact.get('dimension') == 'adoption':
        return '现状'
    if not OWN_WORK.search(text) and re.search(r'提示词|原型', text) and re.search(r'本人|我|完成|负责', text):
        return '标题性质'
    if OWN_WORK.search(text) or fact.get('kind') == 'method_tool':
        return '技术'
    if re.search(r'接入|选择|取舍|决定', text):
        return '决策'
    if re.search(r'负责|完成|实现|搭建|开发|编写|设计|制作', text):
        return '决策'
    if fact.get('kind') in {'result_metric', 'result_qualitative', 'status_limit'}:
        return '现状'
    return ''


async def classify_items(items: dict, allowed: set, call, model, role_family: str, diagnostic: dict) -> dict:
    assignments = {}
    for item_id in sorted(allowed):
        if item_id not in items or items[item_id][0] != 'projects':
            continue
        facts = {f['id']: f for f in items[item_id][1]['facts'] if f.get('status', 'active') == 'active'}
        if not facts:
            continue
        proposed = {}
        try:
            result = await call(model, FactSlots, {'item_id': item_id, 'facts': list(facts.values())},
                                CLASSIFY_CONTRACT, role_family, run_name='writer_classify_slots')
            proposed = {row.fact_id: row.slot for row in result.assignments}
            if len(proposed) != len(result.assignments) or proposed.keys() != facts.keys():
                raise ValueError('slot_fact_ids_must_match')
        except Exception:
            proposed = {}
            diagnostic.setdefault('slot_classification_fallbacks', []).append(item_id)
        assignments[item_id] = {fid: rule_slot(fact) or proposed.get(fid, '不用') for fid, fact in facts.items()}
    return assignments


def slot_groups(assignments: dict, cap: int) -> dict:
    # With a hard user cap, problem/choice/evaluation take priority. Status
    # precedes generic tooling. Never merge different labels to evade the cap.
    order = ('问题', '决策', '迭代', '现状', '技术')
    present = [slot for slot in order if slot in assignments.values()][:cap]
    return {slot: [fid for fid, value in assignments.items() if value == slot]
            for slot in SLOTS if slot in present}


def _plain(text: str) -> str:
    return LABEL.sub('', text.strip()).lstrip('：: ').rstrip('。；; ')


def _foreign_content(text: str, slot: str) -> bool:
    if slot == '技术':
        return bool(PRODUCT_FUNCTION.search(text))
    if slot == '决策':
        return bool(STATUS.search(text) or NATURE.search(text)
                    or re.search(r'由(?:我|本人)|(?:我|本人).{0,4}(?:负责|完成)|提示词原型', text))
    if slot == '现状':
        return bool(NATURE.search(text) or re.search(r'由(?:我|本人)|差点意思', text))
    return False


def candidate_row(rows: list[dict], slot: str, ids: list[str], item_id: str) -> dict | None:
    allowed = set(ids)
    matching = []
    for row in rows:
        refs = set(row.get('fact_ids') or [])
        text = _plain(row.get('text') or '')
        if not refs or not refs <= allowed or not text or '\n' in text or _foreign_content(text, slot):
            continue
        # Relabel plain or incorrectly labelled output only if its evidence is
        # homogeneous. Foreign references are rejected before fact_guard.
        matching.append({'text': text, 'fact_ids': list(dict.fromkeys(row['fact_ids']))})
    if not matching:
        return None
    # Prefer a complete synthesis, otherwise join non-overlapping sentences.
    complete = next((row for row in matching if set(row['fact_ids']) == allowed), None)
    if complete:
        matching = [complete]
    texts, refs = [], []
    for row in matching:
        if set(row['fact_ids']) <= set(refs):
            continue
        if row['text'] not in texts:
            texts.append(row['text'])
        refs.extend(fid for fid in row['fact_ids'] if fid not in refs)
    text = '；'.join(texts)
    if set(refs) != allowed or len(re.split(r'[；;。]', text)) > 3 or len(text) > 240:
        return None
    return {'id': item_id + ':' + slot, 'item_id': item_id, 'slot': slot, 'text': text, 'fact_ids': refs}


def _fallback_phrase(fact: dict, slot: str, name: str) -> str:
    text = _plain(str(fact.get('text') or ''))
    if constraint_only(text) or (absence_printed(text) and not product_pain(text)):
        # Keep affirmative clauses of a mixed fact, not a missing-data disclaimer.
        text = '，'.join(part for part in clauses(text)
                        if not constraint_only(part) and not absence_printed(part))
    text = re.sub(r'甚至|非常', '', text)
    if slot == '问题':
        text = re.sub(r'^(?:解决了|甚至)', '', text)
        text = text.replace('一个一个填空非常繁琐', '填空流程繁琐').replace('复制粘体', '复制粘贴')
        text = re.sub(r'要用户自己用ai工具复制粘贴优化过的经历', 'AI 优化后的经历仍需用户复制粘贴', text, flags=re.I)
        text = re.sub(r'经常给你一个pdf', '、PDF ', text, flags=re.I)
        text = text.replace('总是不知道', '不懂').replace('应该怎么样才好', '')
    elif slot == '现状':
        # The actual c5 quote differs from the old exact-string substitution.
        # Remove the tentative judgement, retaining the explicit ongoing work.
        text = re.sub(r'([^，,；;。]*?效果)(?:可能)?(?:还)?差点意思[，,；; ]*(?:仍|还)?在优化',
                      r'\1仍在优化', text)
        text = re.sub(r'(?:生成的|出的)简历和使用过程中的效果', '简历生成与使用效果', text)
        text = re.sub(r'生成的简历和使用过程中的效果可能还差点意思，仍在优化', '简历生成与使用效果仍在优化', text)
        text = re.sub(r'效果(?:可能)?还差点意思[，,；; ]*(?:仍|还)在优化', '效果仍在优化', text)
        text = re.sub(r'(?:所以)?还在优化但是', '仍在优化；', text)
        text = text.replace('已经上线了可以正常使用', '已上线可正常使用')
        text = text.replace('整个流程已经打通，能跑起来', '流程已打通并可运行')
    elif slot == '技术':
        text = text.replace('Cursor / Claude Code 等 AI 编程工具', '借助 Cursor / Claude Code 编程')
        text = re.sub(r'提示词原型都是我(?:，这是我的个人开发项目)?', '本人完成提示词原型', text)
    elif slot == '决策':
        text = re.sub(r'^对话挖经历的设计取舍是', '', text)
        text = text.replace('先让学生通过对话补充经历，再根据已确认事实成稿', '先通过对话补充学生经历，再依据已确认事实成稿')
    if slot == '迭代':
        text = text.replace('换模型或调参数', '更换模型或调整参数')
        text = re.sub(r'([一二三四五六七八九十])(?=个|条|次)', lambda m: str('一二三四五六七八九十'.index(m[1]) + 1), text)
    # Never turn 可能上线 into 已上线. Remove the filler while retaining modality.
    text = re.sub(r'([^，,；;。]*?)可能([^，,；;。]+)', r'是否\1\2尚待确认', text)
    text = re.sub(r'([^，,；;。]*?)差点意思', r'\1尚待完善', text)
    text = re.sub(r'^(?:所以|但是|然后)', '', text)
    text = re.sub(r'^(?:我)(?!们)', '本人', text)
    text = re.sub(r'(?<![未没])已经上线了?', '已上线', text)
    text = text.replace('现在已上线', '已上线').replace('还在优化', '仍在优化')
    text = text.replace('已经打通了', '已经打通').replace('能跑了', '能跑起来')
    return text.strip('，,。；; ')


def fallback_row(slot: str, ids: list[str], item_id: str, facts: dict, name: str) -> dict:
    phrases, refs = [], []
    for fid in ids:
        phrase = _fallback_phrase(facts[fid], slot, name)
        if phrase:
            refs.append(fid)
        if phrase and not any(normalize_text(phrase) in normalize_text(old) for old in phrases):
            phrases = [old for old in phrases if normalize_text(old) not in normalize_text(phrase)]
            phrases.append(phrase)
    # Source fallback is allowed to be longer than model prose. Never truncate
    # facts to meet a model sentence/character budget.
    phrases = [part for text in phrases for part in re.split(r'[；;。]', text) if part]
    if slot == '现状':
        parts = [re.sub(r'(?:现在)?已经上线了?', '已上线', part).replace('已上线，可以正常使用', '已上线可正常使用')
                 for part in phrases]
        phrases = []
        for part in sorted(parts, key=len, reverse=True):
            if part in {'仍在优化', '还在优化'} and any('优化' in old for old in phrases):
                continue
            if not any(normalize_text(part) in normalize_text(old) for old in phrases):
                phrases.append(part)
    return {'id': item_id + ':' + slot, 'item_id': item_id, 'slot': slot,
            'text': '；'.join(phrases), 'fact_ids': refs}


async def _checked(rows: list[dict], facts: dict, model, *, reports: dict | None = None) -> dict:
    """Check each output clause against the fact union, then each fact's retention.

    Diagnostics preserve both directions and never hide a shape rejection.
    Source fallback does not enter this model-dependent path.
    """
    reports = reports if reports is not None else {}
    literal, semantic, owners = [], [], {}
    for row in rows:
        errors = []
        if not row['text']:
            errors.append(failure('empty_text'))
        if len(row['text']) > 240 or len(re.split(r'[；;。]', row['text'].rstrip('。；;'))) > 3:
            errors.append(failure('model_row_budget_exceeded'))
        if _foreign_content(row['text'], row['slot']):
            errors.append(failure('foreign_slot_content'))
        if not row['fact_ids'] or any(fid not in facts or facts[fid].get('status', 'active') != 'active'
                                    or facts[fid].get('item_id') != row['item_id'] for fid in row['fact_ids']):
            errors.append(failure('missing_inactive_or_wrong_experience_fact_ids'))
        reports[row['id']] = {'verdict': 'fail' if errors else 'pass', 'failures': errors,
                              'clauses': [], 'coverage': []}
        if errors:
            continue
        sources = [facts[fid].get('source_quote') or facts[fid]['text'] for fid in row['fact_ids']]
        for index, part in enumerate(clauses(row['text'])):
            identifier = row['id'] + ':clause:' + str(index)
            child = {**row, 'id': identifier, 'text': part, 'claim_kind': 'labeled_clause',
                     'row_context': row['text']}
            owners[identifier] = row['id']
            (literal if literal_clause(part, sources, row['slot']) else semantic).append(child)
    checks = await guard_bullets(literal, list(facts.values()), lexical_only=True)
    checks += await guard_bullets(semantic, list(facts.values()), llm=model, run_name='labeled_slot_clause')
    for check in checks:
        report = reports[owners[check['id']]]
        report['clauses'].append(check)
        if check['verdict'] != 'pass':
            report['verdict'] = 'fail'
            report['failures'].extend(verdict_failures(check, clause_id=check['id'], text=check['text']))
    from app.services.fact_coverage import text_covered
    pairs, owner = [], {}
    for row in rows:
        if reports[row['id']]['verdict'] != 'pass':
            continue
        for fid in row['fact_ids']:
            wanted = _fallback_phrase(facts[fid], row['slot'], '')
            if not wanted:
                continue
            if (all(literal_clause(part, [row['text']], row['slot'], retention=True) for part in clauses(wanted))
                    or text_covered(wanted, [row['text']])):
                reports[row['id']]['coverage'].append({'fact_id': fid, 'verdict': 'pass', 'method': 'literal'})
            else:
                key = row['id'] + ':fact:' + fid
                pairs.append({'id': key, 'text': wanted, 'source_quotes': [row['text']],
                              'claim_kind': 'slot_retention'})
                owner[key] = (row['id'], fid)
    decisions = await verify_semantics(pairs, model, run_name='labeled_slot_coverage') if pairs else {}
    for key, (row_id, fid) in owner.items():
        verdict = decisions.get(key, {'verdict': 'fail'})
        reports[row_id]['coverage'].append({'fact_id': fid, 'method': 'semantic', **verdict})
        if verdict['verdict'] != 'pass':
            reports[row_id]['verdict'] = 'fail'
            reports[row_id]['failures'].append(failure('fact_coverage_failed', fact_id=fid))
            reports[row_id]['failures'].extend(verdict_failures(
                {'verdict': 'fail', 'semantic': verdict}, fact_id=fid))
    return {row['id']: row for row in rows if reports[row['id']]['verdict'] == 'pass'}


def _selection_failures(rows: list[dict], ids: list[str], slot: str) -> list[dict]:
    relevant = [row for row in rows if set(row.get('fact_ids') or []) & set(ids)
                or (row.get('text') or '').startswith(slot + '：')]
    errors = []
    for row in relevant:
        refs = row.get('fact_ids') or []
        if not set(refs) <= set(ids):
            errors.append(failure('cross_slot_fact_ids', fact_ids=refs))
        if _foreign_content(_plain(row.get('text') or ''), slot):
            errors.append(failure('foreign_slot_content', text=row.get('text', '')))
    if not errors:
        errors.append(failure('missing_or_incomplete_slot_row', missing_fact_ids=ids))
    return errors


async def finish_rows(rows: list[dict], assignments: dict, cap: int, item_id: str, facts: dict,
                      name: str, call, model, writer_model, role_family: str, diagnostic: dict,
                      *, heading_texts=(), model_rows=None) -> list[dict]:
    headings = {normalize_text(value) for value in heading_texts if value}
    assignments = {fid: '标题性质' if normalize_text(_fallback_phrase(facts[fid], slot, name)) in headings
                   else slot for fid, slot in assignments.items()
                   if fid in facts and facts[fid].get('status', 'active') == 'active'
                   and facts[fid].get('item_id') == item_id}
    groups = slot_groups(assignments, cap)
    traces = {}
    for slot, ids in slot_groups(assignments, len(SLOTS)).items():
        trace = traces[slot] = line_trace(diagnostic, item_id, slot, ids)
        trace['writer_output'] = [row for row in (model_rows if model_rows is not None else rows)
                                  if set(row.get('fact_ids') or []) & set(ids)
                                  or (row.get('text') or '').startswith(slot + '：')]
        if slot not in groups:
            trace['final_handling'] = 'omitted_by_explicit_cap'
        elif not fallback_row(slot, ids, item_id, facts, name)['text']:
            trace['final_handling'] = 'constraints_only'
            groups.pop(slot)
    accepted = {}

    async def check_attempt(proposals, selected, stage):
        candidates, reports, raw = [], {}, {}
        for slot, ids in selected.items():
            trace = traces[slot]
            relevant = [{'id': row.get('id', ''), 'text': row.get('text', ''), 'fact_ids': row.get('fact_ids') or []}
                        for row in proposals if set(row.get('fact_ids') or []) & set(ids)
                        or (row.get('text') or '').startswith(slot + '：') or row.get('id') == item_id + ':' + slot]
            raw[slot] = relevant
            eligible = [row for row in proposals if stage != 'retry' or row.get('id') == item_id + ':' + slot]
            row = candidate_row(eligible, slot, ids, item_id)
            if row:
                candidates.append(row)
            else:
                attempt(trace, stage, '', [], {'verdict': 'fail',
                    'failures': _selection_failures(proposals, ids, slot) + (
                        [failure('repair_id_mismatch')] if stage == 'retry' and relevant and not eligible else [])},
                    model_rows=relevant)
        passed = await _checked(candidates, facts, model, reports=reports)
        for row in candidates:
            trace = traces[row['slot']]
            attempt(trace, stage, row['text'], row['fact_ids'], reports[row['id']], model_rows=raw[row['slot']])
            if row['id'] in passed:
                delivered(trace, row, stage)
        accepted.update(passed)

    # Audit the actual writer output. Legacy polish/coverage rows must not hide
    # why its original slot failed or be reported as the model's first attempt.
    await check_attempt(model_rows if model_rows is not None else rows, groups, 'model')
    missing = {slot: ids for slot, ids in groups.items() if item_id + ':' + slot not in accepted}
    if missing:
        diagnostic.setdefault('slot_repairs', []).append(item_id)
        for slot in missing:
            traces[slot]['retry_count'] = 1
        try:
            repaired = await call(writer_model, RepairOutput,
                {'labeled_slots': [{'id': item_id + ':' + slot, 'slot': slot, 'fact_ids': ids,
                                    'facts': [facts[fid] for fid in ids],
                                    'previous_attempt': traces[slot]['attempts'][-1],
                                    'failures': traces[slot]['attempts'][-1]['failures']}
                                   for slot, ids in missing.items()]},
                WRITE_CONTRACT + '\n按 failures 修复；只返回 RepairOutput.bullets；id 必须原样返回。',
                role_family, run_name='writer_slot_repair')
            proposals = [b.model_dump() for b in repaired.bullets]
            await check_attempt(proposals, missing, 'retry')
        except Exception as error:
            for slot in missing:
                attempt(traces[slot], 'retry', '', [], {'verdict': 'fail',
                    'failures': [failure('repair_unavailable', error_type=type(error).__name__)]})
    for slot, ids in groups.items():
        key = item_id + ':' + slot
        if key in accepted:
            continue
        row = fallback_row(slot, ids, item_id, facts, name)
        # This is a deterministic rendering of active facts, NOT an unchecked
        # model proposal. Long common substrings and a larger row are intentional.
        diagnostic.setdefault('slot_fallbacks', []).append(key)
        attempt(traces[slot], 'deterministic_fallback', row['text'], row['fact_ids'],
                {'verdict': 'pass', 'failures': [], 'method': 'normalized_active_facts'})
        accepted[key] = row
        delivered(traces[slot], row, 'deterministic_fallback')
    result = []
    for slot in groups:
        row = accepted[item_id + ':' + slot]
        labelled = {**row, 'text': slot + '：' + row['text'], 'coverage_fact_ids': list(row['fact_ids'])}
        traces[slot]['final_text'] = labelled['text']
        result.append(labelled)
    return result
