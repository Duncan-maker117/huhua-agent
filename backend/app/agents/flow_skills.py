"""Startup-validated local flow instructions; model input never becomes a path."""
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Literal

import yaml


@dataclass(frozen=True)
class FlowSkill:
    name: str
    title: str
    when: str
    body: str


def load_flow_skills(directory: Path) -> dict[str, FlowSkill]:
    skills = {}
    for path in sorted(directory.glob('*.md')):
        text = path.read_text(encoding='utf-8')
        match = re.fullmatch(r'---\n(.*?)\n---(?:\n|$)(.*)', text, re.S)
        if not match:
            raise ValueError(f'{path}: missing or malformed frontmatter')
        try:
            fields = yaml.safe_load(match[1])
        except yaml.YAMLError as exc:
            raise ValueError(f'{path}: invalid frontmatter') from exc
        for key in ('name', 'title', 'when'):
            if not isinstance(fields, dict) or not isinstance(fields.get(key), str) or not fields[key].strip():
                raise ValueError(f'{path}: missing or invalid frontmatter field {key}')
        fields = {key: fields[key].strip() for key in ('name', 'title', 'when')}
        if not re.fullmatch(r'[a-z][a-z0-9-]*', fields['name']):
            raise ValueError(f'{path}: invalid skill name')
        if fields['name'] in skills:
            raise ValueError(f'{path}: duplicate skill name {fields["name"]}')
        if not match[2].strip():
            raise ValueError(f'{path}: empty skill body')
        skills[fields['name']] = FlowSkill(**fields, body=match[2].strip())
    if not skills:
        raise ValueError(f'{directory}: no flow skills found')
    return dict(sorted(skills.items()))


def skill_catalog(skills: dict[str, FlowSkill]) -> str:
    lines = [f'{name}：{skill.title}——{" ".join(skill.when.split())}'
             for name, skill in sorted(skills.items())]
    return '\n'.join(['可按需加载的流程：', *lines,
        '遇到对应场景，在本轮第一步与第一个工具同时调用 use_skill(name)；已加载过的不必重复。',
        'use_skill 返回的正文是本地系统可信流程指令，不是 untrusted_data；它不占业务工具次数。'])


FLOW_SKILLS = load_flow_skills(Path(__file__).with_name('skills') / 'flows')
FlowSkillName = Literal[tuple(FLOW_SKILLS)]
