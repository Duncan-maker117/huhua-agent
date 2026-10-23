"""来自用户授权导出的 2026-10-17 真实对话，已确认无个人联系方式。

前四轮逐字回放；旧 UI 操作仅留作来源，不作为新流程消息发送。
经历名经用户确认；2025.09 开始来自用户另一次对话。其余答案限于下列原话。
独立于原五人物及合成 aipm；复用 c2 的维度识别、选项归一和成稿证明。
"""
from copy import deepcopy
from difflib import SequenceMatcher
from importlib import import_module
import re

from app.services.ask_user import question_dimension
from app.services.fact_guard import extract_numbers

c2 = import_module('evaluation.persona-ux.aipm')
ORIGINAL_MESSAGES = [
    '我想从零开始聊自己的经历。',
    '我想投最近很火的ai产品相关工作，我对这个感兴趣',
    '我现在是大四学生 最近都在准备我的ai产品项目 还有学习ai相关的技术',
    '解决了普通简历工具一个一个填空非常繁琐\n甚至要用户自己用ai工具复制粘体优化过的经历\n\nai工具生成的简历格式无法微调经常给你一个pdf用户无法编辑 甚至ai工具总是不知道简历的结构应该怎么样才好\n\n我觉得所有人都有这样的需求，提示词原型都是我，这是我的个人开发项目\n\n现在已经能跑了整个流程已经打通了  但是出的简历和使用过程中的效果可能差点意思\n\n所以还在优化但是已经上线了可以正常使用\n也接入了mcp可以使用用户自己的ai来使用这样的一个工具',
    '写法：问题-决策-结果', '写法：问题-决策-结果', '按推荐写', '不知道', '10',
    '我想继续补充「项目（待补名称）」的细节。',
]
FIRST_TURNS = ORIGINAL_MESSAGES[:4]
INTAKE = {'kind': 'experiences', 'items': [{'name': '胡话简历', 'type': '项目',
          'start': '2025-09', 'end': '至今', 'role': '个人开发',
          'summary': '所以还在优化但是已经上线了可以正常使用'}]}
VALUES = {
    'problem': ['普通简历工具一个一个填空非常繁琐', '需要把 AI 优化过的经历复制粘贴',
                'AI 生成的 PDF 无法编辑微调', 'AI 不懂简历结构'],
    'my_work': ['提示词原型都是我', '这是我的个人开发项目'],
    'status': ['整个流程已经打通了', '已经上线了可以正常使用', '效果仍在优化'],
    'decision': '接入 MCP，用户可以用自己的 AI 使用这个工具',
    'adoption': '10 人',
}
MAX_COMMON_SUBSTRING = c2.MAX_COMMON_SUBSTRING
MAX_ROUNDS = c2.MAX_ROUNDS
delivered = c2.delivered


def _adoption_option(option):
    """Only a bare user-count bucket may stand for 10; never pick extra claims."""
    text = re.sub(r'\s+', '', option)
    if re.fullmatch(r'(?:使用人数[：:]?|用户数[：:]?)?10人', text):
        return True
    match = re.fullmatch(r'(\d+)[-–—~～至](\d+)人', text)
    return bool(match and int(match[1]) <= 10 <= int(match[2]))


def answer(question):
    # Same c2 dimension/normalized-exact-option rule, with this isolated bank.
    dimension = question_dimension(question['id'], question['prompt'])
    value = c2.question_value(question, VALUES, INTAKE)
    values = value if isinstance(value, list) else [value] if value else []
    if question['kind'] != 'text':
        selected = []
        for value in values:
            match = next((o for o in question.get('options', [])
                          if c2._normalized(o) == c2._normalized(value)
                          or dimension == 'adoption' and _adoption_option(o)), None)
            if match:
                selected.append(match)
            elif question.get('allow_other'):
                selected.append(value)
        values = selected
    if question['kind'] == 'single':
        values = values[0] if values else ''
    elif question['kind'] == 'text':
        values = '；'.join(values)
    return {'id': question['id'], 'value': values or '', 'unknown': not bool(values)}


def submission(workspace, reply=''):
    guidance = workspace.get('guidance') or {}
    kind = guidance.get('kind')
    if kind == 'ask_user':
        items = [answer(q) for q in guidance['questions']]
        lines = [q['prompt'].rstrip('？?') + '：' +
                 ('、'.join(a['value']) if isinstance(a['value'], list) else a['value'] or '不知道')
                 for q, a in zip(guidance['questions'], items)]
        return 'answers', '关于「胡话简历」：' + '；'.join(lines), {
            'answers': {'turn_id': guidance['turn_id'], 'items': items}}
    if kind == 'intake_experiences':
        intake = deepcopy(INTAKE)
        candidates = guidance.get('items') or []
        target = next((p for p in candidates if p.get('name') == '胡话简历'), None)
        # The real four inputs do not name the project; bind the sole pending
        # placeholder instead of creating a second project on form submission.
        if target is None and len(candidates) == 1:
            target = candidates[0]
        if target and target.get('item_id'):
            intake['items'][0]['item_id'] = target['item_id']
        return 'experiences', '经历清单：胡话简历，项目，2025-09 至今，个人开发；' + INTAKE['items'][0]['summary'], {'intake': intake}
    if kind == 'intake_basics':
        return 'basics', '跳过基本信息，继续。', {'intake': {'kind': 'basics', 'skipped': True}}
    if kind == 'structure_plan':
        option = next((o.get('value') for o in guidance.get('options', []) if o.get('label') == '按推荐写'), None)
        if not option:
            raise ValueError('Pending plan has no recommended confirmation option')
        return 'plan_confirm', option, {'kind': 'confirmation'}
    return 'free_answer', c2.free_text_answer(reply, VALUES), {}


def replay(client, *, agent_mode=None):
    for index, text in enumerate(FIRST_TURNS, 1):
        turn = client.turn(f'initial_{index}', text)
        yield turn
        if turn.get('status') != 'ok':
            return
    counts = {}
    for round_index in range(MAX_ROUNDS + 1):
        if turn.get('status') != 'ok' or (delivered(turn) and (
                agent_mode != 'loop' or not c2.pending_followup(turn))):
            return
        if round_index == MAX_ROUNDS:
            turn = client.turn('depth_limit_direct', '直接写')
            turn['depth_limit_exceeded'] = True
            yield turn
            return
        action, text, payload = submission(turn.get('workspace') or {}, turn.get('reply', ''))
        if action == 'plan_confirm':
            payload['trigger_action'] = turn['action']
        counts[action] = counts.get(action, 0) + 1
        if counts[action] > 1 or action == 'answers':
            action += '_' + str(counts[action])
        turn = client.turn(action, text, **payload)
        yield turn


def _answer_audit(turns):
    closed, repeated = set(), []
    adoption = False
    for previous, turn in zip(turns, turns[1:]):
        card = (previous.get('workspace') or {}).get('guidance') or {}
        payload = turn.get('answers') or {}
        if card.get('kind') == 'ask_user' and payload.get('turn_id') == card.get('turn_id'):
            questions = {q['id']: q for q in card.get('questions', [])}
            for a in payload.get('items', []):
                q = questions.get(a.get('id'))
                if not q:
                    continue
                dimension = question_dimension(q['id'], q['prompt'])
                if a.get('unknown') or a.get('skipped'):
                    closed.add(dimension)
                elif dimension == 'adoption' and a.get('value') == answer(q)['value']:
                    adoption = bool(a.get('value'))
        elif card.get('kind') not in {'intake_basics', 'intake_experiences', 'structure_plan'}:
            from app.services.followup_context import latest_followup
            question = latest_followup(previous.get('reply', ''))
            dimension = question_dimension('', question) if question else ''
            if dimension and turn.get('input') == '不知道':
                closed.add(dimension)
            elif dimension == 'adoption' and turn.get('input') == VALUES['adoption']:
                adoption = True
        # This fixture has one experience: name/id aliases refer to it alike.
        for q in ((turn.get('workspace') or {}).get('guidance') or {}).get('questions', []):
            dimension = question_dimension(q['id'], q['prompt'])
            if dimension in closed:
                repeated.append(dimension)
        if not (turn.get('workspace') or {}).get('guidance'):
            from app.services.followup_context import latest_followup
            question = latest_followup(turn.get('reply', ''))
            if question and question_dimension('', question) in closed:
                repeated.append(question_dimension('', question))
    return adoption, repeated


def _visible_claims(data):
    base_checks = import_module('evaluation.persona-ux.checks')
    visible = deepcopy(data)
    headings = []
    for p in base_checks.visible_items(visible, 'projects'):
        if p.get('name') == '胡话简历' and p.get('start_date') in {'2025-09', '2025.09'}:
            p.pop('start_date')  # Only the separately confirmed header date.
        headings.extend(str(p.get(k) or '') for k in ('positioning', 'project_type'))
    return '\n'.join([base_checks.resume_text(visible), *headings])


def evaluate_persona(persona, turns, **kwargs):
    final = turns[-1] if turns else {}
    drafted = delivered(final)
    data = final.get('resume_data') or {}
    project = next((p for p in data.get('projects', []) if p.get('name') == '胡话简历' and not p.get('hidden')), {})
    bullets = project.get('polished_bullets') or []
    body = '\n'.join(bullets)
    labeled = [(m[1], m[2]) for b in bullets if (m := re.match(r'^([^：:]+)[：:](.*)', b))]
    labels = {label for label, _ in labeled}
    problem = '；'.join(text for label, text in labeled if label == '问题')
    pain_groups = [(r'填空|填写|填表', r'繁琐|繁杂|费事|逐项|逐个|重复'),
                   (r'复制|粘贴|粘体',), (r'PDF|pdf', r'不能|无法|不可|难以', r'编辑|微调|调整'),
                   (r'结构', r'不懂|不清楚|不理解|不知道|不合理|混乱|欠缺')]
    pains = sum(all(re.search(pattern, problem) for pattern in group) for group in pain_groups)
    adoption, repeated = _answer_audit(turns)
    claims = _visible_claims(data)
    numeric_clauses = [s for s in re.split(r'[；;。\n]', claims) if re.search(r'(?<!\d)(?:10|十)(?!\d)', s)]
    usage_ok = all(re.search(r'(?:10|十)\s*人', s) and re.search(r'使用|用户|在用|用过|试用', s)
                   and not re.search(r'付费|营收|准确|测试|回放|断言|访谈|团队|开发者|增长|新增|日活|月活', s)
                   for s in numeric_clauses)
    longest = max((SequenceMatcher(None, b, t.get('input', ''), autojunk=False).find_longest_match().size
                   for b in bullets for t in turns), default=0)
    # Header dates are authorized separately; prompt digits and old UI steps
    # do not license body metrics. Chinese quantities are checked as well.
    conditions = [
        ('common.rounds_complete', bool(turns) and all(t.get('status') == 'ok' and t.get('sse_done') for t in turns) and drafted, 'writer 成稿、正文引用/hash 与每轮 SSE'),
        ('heading', project.get('start_date') in {'2025-09', '2025.09'} and project.get('end_date') == '至今' and bool(project.get('positioning')), str({k: project.get(k) for k in ('name', 'start_date', 'end_date', 'positioning')})),
        ('labels', 2 <= len(bullets) <= 4 and len(labels & {'问题', '决策', '关键决策', '迭代', '现状'}) >= 2 and not re.search(r'^(?:问题|决策|关键决策|迭代|现状)：(?:问题|决策|迭代|现状)：', body, re.M), body),
        ('real_pains', pains >= 2, f'{pains} 个真实痛点；{problem}'),
        ('mcp_decision', any(label in {'决策', '关键决策'} and 'mcp' in text.casefold() for label, text in labeled), body),
        ('adoption_unit_and_owner', usage_ok, str(numeric_clauses)),
        ('no_placeholder', bool(project) and not re.search(r'待补|待填写', str(data)), body),
        ('rewritten', bool(body) and longest <= MAX_COMMON_SUBSTRING, f'最长公共子串 {longest}，阈值 {MAX_COMMON_SUBSTRING}'),
        ('no_invented_metrics', bool(body) and extract_numbers(claims) <= ({'10'} if adoption else set()), claims),
        ('unknown_not_reasked', not repeated, str(repeated)),
        ('depth_within_limit', not any(t.get('depth_limit_exceeded') for t in turns), f'卡片上限 {MAX_ROUNDS} 轮'),
    ]
    procedural = {'common.rounds_complete', 'unknown_not_reasked', 'depth_within_limit'}
    return [{'id': f'aipm_real.{key}', 'label': key, 'status': 'pass' if ok and (drafted or key in procedural) else 'fail',
             'evidence': [{'action': final.get('action', ''), 'field': key,
                           'excerpt': ('未取得 writer 成稿；' if not drafted and key not in procedural else '') + evidence}]}
            for key, ok, evidence in conditions]
