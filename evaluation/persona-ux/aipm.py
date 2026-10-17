"""第六人物：合成占位，尚非用户真实对话；拿到真实记录后替换本文件输入。

独立于五人物 fixtures/checks。最长公共子串阈值 24 个字符：保留工具名、
数量与必要短语（Cursor / Claude Code 组合已有 21 字符），同时阻止直接复制完整口述句；仅检查正文，不惩罚标题中的原名称。
"""
from copy import deepcopy
from difflib import SequenceMatcher
import re

FIRST = '我想投AI产品经理实习。我自己做了一个AI简历助手，叫胡话简历，从需求到开发都是我一个人做的，现在已经上线了，能通过对话帮学生挖经历写简历。'
INTAKE = {'kind': 'experiences', 'items': [{'name': '胡话简历', 'type': '项目',
          'start': '2026-08', 'end': '至今', 'role': '独立开发者', 'summary': '现在已经上线了'}]}
VALUES = {
    'tech_stack': ['Cursor / Claude Code 等 AI 编程工具', '直接调用大模型 API'],
    'evaluation': ['对比过不同提示词或方案', '做了五个虚拟求职者的对话回放，用71条断言自动检查成稿'],
    'iteration': '换模型或调参数', 'status': '公网可访问的链接',
    'links': '公网可访问的链接',
    'decision': '先让学生通过对话补充经历，再根据已确认事实成稿',
    'problem': '学生难以梳理自己的经历，需要通过对话挖掘可写进简历的事实',
    'my_work': '独立完成需求梳理、开发和上线',
    'adoption': None,
}
# 载荷里保留结构化字段；turn_id、item_id 必须绑定运行中实际卡片。
FIXTURE = {'role': '合成 AI 产品实习人物，待真实对话替换',
           'initial': FIRST,
           'experiences': {'message': '经历清单：胡话简历，项目，2026-08 至今，独立开发者，现在已经上线了', 'intake': INTAKE},
           'answers_1': {'answers': {'items': [{'id': key, 'value': value} for key, value in VALUES.items()]}},
           'answers_2': {'answers': {'items': [{'id': key, 'value': value} for key, value in VALUES.items()]}},
           'basics': {'message': '跳过基本信息，继续。', 'intake': {'kind': 'basics', 'skipped': True}}}
MAX_COMMON_SUBSTRING = 24
MAX_ROUNDS = 6


def _answer(question):
    from app.services.ask_user import question_dimension
    dimension = question_dimension(question['id'], question['prompt'])
    value = VALUES.get(dimension)
    values = value if isinstance(value, list) else [value] if value else []
    if question['kind'] != 'text':
        selected = []
        for answer in values:
            # Only select an option that expresses the supplied synthetic fact;
            # topic similarity alone must not select a contradictory option.
            match = next((option for option in question.get('options', [])
                          if _normalized(option) == _normalized(answer)), None)
            if match:
                selected.append(match)
            elif question.get('allow_other'):
                selected.append(answer)  # API representation of “其他” + free text.
        values = selected
    if question['kind'] == 'single':
        values = values[0] if values else ''
    elif question['kind'] == 'text':
        values = '；'.join(values)
    return {'id': question['id'], 'value': values or '', 'unknown': not bool(values)}


def _normalized(text):
    text = re.sub(r'更换|换了', '换', text)
    text = re.sub(r'调参数|调整参数|调节参数', '调参', text)
    text = re.sub(r'对比过|比较过|比较', '对比', text)
    return re.sub(r'[\W_]|(?:等|已经|了)', '', text.casefold())


def delivered(turn):
    """Preview revisions and a selected plan alone do not prove writer delivery."""
    from app.services.resume_versions import text_hash
    meta = ((turn.get('workspace') or {}).get('tailor') or {}).get('resume_meta') or {}
    written = (meta.get('writer_diagnostic') or {}).get('status') in {'model_completed', 'model_fallback'}
    if turn.get('stage') not in {'EVALUATING', 'EXPORT'} or not turn.get('revision'):
        return False
    if not (written or meta.get('confirmed_plan') or turn.get('confirmed_plan')):
        return False
    return any(bullets and len(bullets) == len(records) and all(
        r.get('fact_ids') and r.get('text_hash') == text_hash(b) for b, r in zip(bullets, records))
        for project in turn.get('resume_data', {}).get('projects', [])
        if project.get('name') == '胡话简历' and not project.get('hidden')
        for bullets in [project.get('polished_bullets') or []]
        for records in [(meta.get('bullets') or {}).get(project.get('item_id'), [])])


def replay(client):
    """Follow actual cards until a verified draft, with a bounded intake budget."""
    turn = client.turn('initial', FIRST)
    yield turn
    counts = {}
    for round_index in range(MAX_ROUNDS + 1):
        if turn.get('status') != 'ok' or delivered(turn):
            return
        workspace = turn.get('workspace') or {}
        guidance = workspace.get('guidance') or {}
        kind = guidance.get('kind')
        if round_index == MAX_ROUNDS:
            turn = client.turn('depth_limit_direct', '直接写')
            turn['depth_limit_exceeded'] = True
            yield turn
            return
        if kind == 'structure_plan':
            option = next((o['value'] for o in guidance.get('options', []) if o.get('label') == '按推荐写'), None)
            if not option:
                raise ValueError('Pending plan has no recommended confirmation option')
            action, text, extra = 'plan_confirm', option, {'kind': 'confirmation', 'trigger_action': turn['action']}
        else:
            action = {'ask_user': 'answers', 'intake_experiences': 'experiences', 'intake_basics': 'basics'}.get(kind, 'continue')
            step = {'ask_user': FIXTURE['answers_1'], 'intake_experiences': FIXTURE['experiences'],
                    'intake_basics': FIXTURE['basics']}.get(kind, '继续')
            text, extra = submission(step, workspace)
        counts[action] = counts.get(action, 0) + 1
        if counts[action] > 1 or action == 'answers':
            action += '_' + str(counts[action])
        turn = client.turn(action, text, **extra)
        yield turn


def submission(step, workspace):
    if isinstance(step, str):
        return step, {}
    step = deepcopy(step)
    guidance = workspace.get('guidance') or {}
    if 'answers' in step:
        if guidance.get('kind') != 'ask_user':
            return None  # 已完成深挖时不伪造新问题卡。
        items, lines = [], []
        for question in guidance['questions']:
            answer = _answer(question)
            value = answer['value']
            items.append(answer)
            lines.append(question['prompt'].rstrip('？?') + '：' + ('、'.join(value) if isinstance(value, list) else value or '不知道'))
        return '关于「胡话简历」：' + '；'.join(lines), {'answers': {'turn_id': guidance['turn_id'], 'items': items}}
    if step.get('intake', {}).get('kind') == 'experiences':
        for item in guidance.get('items', []):
            if item.get('name') == '胡话简历':
                step['intake']['items'][0]['item_id'] = item['item_id']
    if step.get('intake', {}).get('kind') == 'basics' and guidance.get('kind') != 'intake_basics':
        return None
    return step['message'], {key: step[key] for key in ('answers', 'intake') if key in step}


def submitted_values(turns):
    """Audit actual submissions, including old logs that only recorded input text."""
    values = []
    for previous, turn in zip(turns, turns[1:]):
        guidance = (previous.get('workspace') or {}).get('guidance') or {}
        if guidance.get('kind') != 'ask_user':
            continue
        answers = turn.get('answers')
        if answers:
            if answers.get('turn_id') != guidance.get('turn_id'):
                continue
            ids = {q['id'] for q in guidance.get('questions', [])}
            for answer in answers.get('items', []):
                if answer.get('id') not in ids or answer.get('unknown') or answer.get('skipped'):
                    continue
                value = answer.get('value') or []
                values.extend(value if isinstance(value, list) else re.split('[；;]', value))
        else:
            # Old artifacts preserve prompt:answer in input, not the payload.
            text = turn.get('input', '')
            prompts = [q['prompt'].rstrip('？?') + '：' for q in guidance.get('questions', [])]
            for prompt in prompts:
                if prompt not in text:
                    continue
                answer = text.split(prompt, 1)[1]
                positions = [answer.index(other) for other in prompts if other in answer]
                answer = answer[:min(positions)] if positions else answer
                values.extend(re.split('[；;、]', answer.strip('；; ')))
    return list(dict.fromkeys(v for v in values if v and v not in {'不知道', '不清楚', '未知', '跳过'}))


def _used(value, body):
    if _normalized(value) in _normalized(body):
        return True
    # Bounded aliases for this synthetic answer bank; no LLM judgement here.
    rules = [
        (r'Cursor|Claude Code', [r'Cursor|Claude Code']),
        (r'大模型\s*API', [r'API', r'调用']),
        (r'对比.*(?:提示词|方案)', [r'比较|对比', r'提示词', r'方案']),
        (r'71.*断言', [r'71\s*条?断言', r'五|5', r'回放', r'成稿']),
        (r'换模型|调参数', [r'换.*模型|调参']),
        (r'公网.*链接', [r'公网|公开访问', r'链接|访问']),
    ]
    return any(re.search(trigger, value) and all(re.search(pattern, body) for pattern in patterns)
               for trigger, patterns in rules)


def evaluate_persona(persona, turns, **kwargs):
    final = turns[-1] if turns else {}
    drafted = delivered(final)
    project = next((p for p in final.get('resume_data', {}).get('projects', []) if p.get('name') == '胡话简历'), {})
    bullets = project.get('polished_bullets') or []
    body = '\n'.join(bullets)
    labels = {b.split('：', 1)[0] for b in bullets}
    inputs = [t.get('input', '') for t in turns]
    longest = max((SequenceMatcher(None, b, text, autojunk=False).find_longest_match().size
                   for b in bullets for text in inputs), default=0)
    from app.services.ask_user import question_dimension
    dimensions = [(str((t.get('workspace', {}).get('guidance') or {}).get('subject', '')),
                   question_dimension(q['id'], q['prompt'])) for t in turns
                  for q in (t.get('workspace', {}).get('guidance') or {}).get('questions', [])]
    submitted = submitted_values(turns)
    hits = [_used(value, body) for value in submitted]
    answer_source = FIRST + '\n' + '\n'.join(submitted)
    allowed_numbers = set(re.findall(r'\d+', answer_source))
    conditions = [
        ('common.rounds_complete', bool(turns) and all(t.get('status') == 'ok' and t.get('sse_done') for t in turns) and drafted, 'writer 成稿、正文引用与每轮 SSE'),
        ('heading', project.get('name') == '胡话简历' and project.get('start_date') == '2026-08' and project.get('end_date') == '至今' and bool(project.get('positioning')), str({k:project.get(k) for k in ('name','start_date','end_date','positioning')})),
        ('labels', len(labels & {'问题', '决策', '迭代'}) >= 2 and 2 <= len(bullets) <= 4 and not any(re.search(r'^(?:问题|决策|迭代|评测|现状)：(?:问题|决策|迭代|评测|现状)：', b) for b in bullets), body),
        ('answers_used', bool(submitted) and sum(hits) >= min(3, len(submitted)), str(list(zip(submitted, hits)))),
        ('no_placeholder', '[待补]' not in str(final.get('resume_data', {})) and bool(project), body),
        ('rewritten', bool(body) and longest <= MAX_COMMON_SUBSTRING, f'最长公共子串 {longest}，阈值 {MAX_COMMON_SUBSTRING}'),
        ('no_invented_metrics', bool(body) and not re.search(r'用户数|准确率|\d+\s*[%％]', body) and set(re.findall(r'\d+', body)) <= allowed_numbers | ({'5'} if '五' in answer_source else set()), body),
        ('no_repeated_dimension', bool(dimensions) and len(dimensions) == len(set(dimensions)), str(dimensions)),
        ('depth_within_limit', not any(t.get('depth_limit_exceeded') for t in turns), f'深挖上限 {MAX_ROUNDS} 轮；越级直接写单独失败'),
    ]
    quality = {'heading', 'labels', 'answers_used', 'no_placeholder', 'rewritten', 'no_invented_metrics'}
    return [{'id': f'aipm.{key}', 'status': 'pass' if ok and (drafted or key not in quality) else 'fail',
             'evidence': [{'action': final.get('action', ''), 'path': key,
                           'excerpt': ('未取得 writer 成稿；' if not drafted and key in quality else '') + evidence}]} for key, ok, evidence in conditions]
