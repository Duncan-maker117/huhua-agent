"""将本地岗位手册投影为外部助手可读的写作约定，不读取用户数据。"""

from pathlib import Path
import re


PLAYBOOKS = Path(__file__).resolve().parents[1] / 'agents/skills/role-playbooks'
ROLES = {'ai-pm', 'product-manager', 'backend', 'frontend', 'algorithm',
         'data-analyst', 'operations', 'design', 'general'}
ALIASES = {'ai_pm': 'ai-pm', 'pm': 'product-manager', 'ops': 'operations',
           'data': 'data-analyst', 'other': 'general'}
LABEL_MEANINGS = {
    '问题': '用户或业务遇到的具体问题，以及本人发现问题的依据。',
    '决策': '本人选择的方案、方法和取舍；没有事实依据不补写决策原因。',
    '迭代': '真实反馈、测试或失败后，本人做过的调整及已确认结果。',
    '现状': '已确认的交付和使用状态，区分本地 Demo、内测与正式上线。',
    '技术': '实际使用的工具、技术和对应动作，不把框架能力写成自研。',
    '场景': '经历服务的对象、任务或已确认的问题。',
    '行动': '本人实际完成的动作、方法和交付物，保留参与程度。',
    '产出': '可核对的作品或结果；数字、时间范围及环境均须有事实支持。',
}


def normalize_role(role):
    value = role.strip().lower()
    value = ALIASES.get(value, value)
    if value in ROLES:
        return value
    # 只做可维护的岗位词映射，不调用模型，也不把输入拼进文件路径。
    for pattern, target in (
        (r'(?:ai|大模型|aigc|agent|人工智能).*产品', 'ai-pm'),
        (r'产品(?:经理|助理|专员)|策略产品', 'product-manager'),
        (r'后端|服务端|平台开发|(?:java|go|python|c\+\+).*开发', 'backend'),
        (r'前端|web开发|小程序开发', 'frontend'),
        (r'算法|机器学习|nlp|计算机视觉', 'algorithm'),
        (r'数据分析|商业分析|数据运营', 'data-analyst'),
        (r'运营|增长|新媒体', 'operations'),
        (r'设计|用户研究', 'design'),
    ):
        if re.search(pattern, value):
            return target
    return 'general'


def _section(text, heading):
    match = re.search(r'^## ' + re.escape(heading) + r'[^\n]*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    return match[1].strip() if match else ''


def writing_guide(role='general'):
    resolved = normalize_role(role)
    text = (PLAYBOOKS / f'{resolved}.md').read_text(encoding='utf-8')
    structure_text = _section(text, '成稿结构')
    fields = dict(re.findall(r'^- (\w+): (.+)$', structure_text, re.M))
    labels = [word.strip() for word in fields.get('labels', '场景, 行动, 产出').split(',')]
    optional = [word.strip() for word in fields.get('optional_labels', '').split(',') if word.strip()]
    structure = {
        'bullet_style': fields.get('bullet_style', 'labeled'),
        'title': [word.strip() for word in fields.get('title', 'name | positioning | project_type | period').split('|')],
        'labels': labels, 'optional_labels': optional,
        'label_meanings': {label: LABEL_MEANINGS[label] for label in labels + optional},
        'rows': fields.get('rows', '2-4'),
        'source': f'role-playbooks/{resolved}.md#成稿结构' if fields else 'mcp_common_structure',
        'guidance': structure_text or '本岗位手册尚无机器可读成稿结构，使用 MCP 通用标签结构；无素材的标签省略，不编造因果、数字或成果。',
    }
    bullets = (['问题：虚构练习中发现纸月资料检索不便，记录查询步骤。',
                '决策：为虚构资料设计目录原型，保留人工查阅入口。',
                '迭代：依据虚构试用记录调整目录名称；当前仅为课程原型。']
               if resolved == 'ai-pm' else
               ['场景：虚构课程需要整理纸月资料目录。',
                '行动：整理虚构资料并制作目录原型。',
                '产出：交付虚构课程演示稿，尚未上线。'])
    return {
        'role': resolved, 'source': f'role-playbooks/{resolved}.md',
        'screening_criteria': _section(text, '筛选者看什么') or _section(text, '通用判断'),
        'structure': structure,
        'expression_rules': ['事实不增，表达自由；可重组和概括已确认事实。',
                             '不写无证据形容词，不升级职责、参与程度、环境或上线状态。',
                             '数字必须来自档案事实，保留时间范围、分母及测试环境。',
                             '每个事实性字段引用 fact_ids；缺少素材的标签省略。'],
        'role_expression': _section(text, '表达'),
        'example_notice': '以下名称、日期与内容全部虚构，只演示格式，绝不能移入用户简历或作为事实来源。',
        # 整个对象可以直接通过 MCPResume 校验，标签保留在字符串正文中。
        'example_resume': {'projects': [{
            'name': '纸月资料目录（虚构示例）', 'positioning': '虚构课程资料检索原型',
            'project_type': '课程项目（虚构）', 'start_date': '2025.03', 'end_date': '2025.04',
            'polished_bullets': bullets,
        }]},
    }
