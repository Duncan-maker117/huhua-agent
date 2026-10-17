"""模型问题工具、逐题校验与会话内永久关闭；不从正文生成卡片。"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Annotated, Literal

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Slug = Annotated[str, Field(min_length=1, max_length=48, pattern=r"^[a-z][a-z0-9_-]*$")]
ShortText = Annotated[str, Field(min_length=1, max_length=80)]


class AskQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    id: Slug
    prompt: str = Field(min_length=1, max_length=40)
    kind: Literal["single", "multi", "text"]
    options: list[ShortText] = Field(default_factory=list, max_length=6)
    allow_other: bool = False
    placeholder: str = Field(default="", max_length=120)

    @model_validator(mode="after")
    def check_options(self):
        if self.kind != "text" and (len(self.options) < 2 or len(set(self.options)) != len(self.options)):
            raise ValueError("选择题需要 2–6 个不同选项")
        if self.kind == "text" and (self.options or self.allow_other):
            raise ValueError("自由文本题无需选项")
        return self


class AskUser(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    questions: list[AskQuestion] = Field(min_length=1, max_length=4)
    subject: str = Field(default="", max_length=120)


class AnswerItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: Slug
    value: str | list[str] = ""
    skipped: bool = False
    unknown: bool = False


class Answers(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    turn_id: str = Field(min_length=1, max_length=128)
    items: list[AnswerItem] = Field(min_length=1, max_length=4)


class PlanChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    option: str = Field(min_length=1, max_length=160)
    bullet_style: Literal["plain", "labeled"]


ASK_CONTRACT = """你可以调用 ask_user 提供 1–4 题补充卡，由你决定是否需要。每轮最多调用一次。
正文最多一个问句，且只收集一个问题的信息；需要问两个及以上问题时必须用 ask_user，不得用逗号、顿号或省略问号把多题塞进正文。
调用时正文只写一句过渡语，不提问、不复述题干；单个纯开放、只能自由描述的问题直接在正文问，不调用工具。
题目 id 使用稳定的短 slug，同一维度不要换 id 重问；subject 使用资料中对应经历的原名称。
single/multi 必须提供 2–6 个中性、真实可选的选项，不替用户预选，不把选项当事实。
以下关闭记录中的问题已问过、已回答或用户说不知道/跳过，永久不要再问，也不要换同义说法追问。
AI 产品岗优先问：问题定义、本人分工、关键决策、badcase 与迭代、技术栈、现状与链接。
个人开发项目没有用户数很正常，不以量化或用户规模作为出稿前提。
候选问题只供参考，不必全部问；pending_plan 存在时只提示确认方案，不调用 ask_user。"""


def can_ask_user(state: dict) -> bool:
    """与工作台共用表单判定；不让模型工具抢占本轮已展示的收集卡。"""
    from app.services.intake import deepen_context, intake_guidance

    if state.get("pending_plan") or (state.get("collected_info") or {}).get("no_more_questions"):
        return False
    # 空字典供无会话的工具适配器使用；真实/旧会话均按实际资料推断表单。
    if state and intake_guidance(state):
        return False
    if state.get("intake_stage") and state.get("intake_stage") != "ready":
        return bool(deepen_context(state).get("subject"))
    return True


def question_dimension(identifier: str = "", prompt: str = "") -> str:
    """稳定维度覆盖旧问句与模型新 slug，优先识别题干中的同义表述。"""
    text = f"{identifier} {prompt}".lower()
    for dimension, pattern in (
        ("adoption", r"adoption|user[_-]?(?:count|number|numbers)|usage|用户数|用户量|用户规模|使用人数|多少人|几个人|人数|人用过|人试过|实际使用|真实用户"),
        ("my_work", r"my_work|ownership|contribution|职责|分工|本人|你.*(?:做了|负责)|独立完成|团队协作"),
        ("problem", r"problem|pain[_-]?point|问题定义|解决谁|什么问题"),
        ("decision", r"decision|tradeoff|关键(?:产品)?决策|为什么|为何|取舍"),
        ("iteration", r"iteration|badcase|bad_case|迭代|效果不好|怎么改|失败"),
        ("evaluation", r"\beval\b|evaluation|evaluate|评测|评估|验证|怎么判断|好不好|测试集|基线"),
        ("tech_stack", r"tech[_-]?stack|technology|技术栈|哪些工具|什么技术|怎么实现|什么模型|什么框架|什么.*接口"),
        ("status", r"status|launch|上线|现状|什么状态|做到哪|跑通|原型"),
        ("links", r"links?|url|链接|网址|能访问|仓库"),
        ("dates", r"dates?|period|时间|日期|何时"),
        ("name", r"name|名称|名字"),
    ):
        if re.search(pattern, text):
            return dimension
    return identifier or re.sub(r"\W", "", prompt)


def subject_key(subject: str, state: dict) -> str:
    subject = str(subject or "").strip().casefold()
    items = [item for section in ("projects", "work_experience", "internship", "campus", "education", "open_source", "awards")
             for item in (state.get("collected_info") or {}).get(section) or [] if isinstance(item, dict)]
    for item in items:
        aliases = [str(item.get(key) or "").strip().casefold() for key in ("item_id", "name", "company", "school")]
        if subject and subject in aliases:
            return str(item.get("item_id") or subject)
    if not subject and len(items) == 1:
        return str(items[0].get("item_id") or items[0].get("name") or items[0].get("company") or "")
    return subject


def is_closed(state: dict, subject: str, identifier: str = "", prompt: str = "") -> bool:
    subject = subject_key(subject, state)
    dimension = question_dimension(identifier, prompt)
    return any((not row.get("subject") or not subject or subject_key(row["subject"], state) == subject)
               and (row.get("id") == identifier or row.get("dimension") == dimension)
               for row in state.get("closed_questions") or [])


def validate_card(arguments, state: dict, turn_id: str) -> dict:
    """封套非法时忽略调用；单题非法时只丢该题，保留其余合法题。"""
    if not can_ask_user(state):
        return {}
    from app.services.intake import deepen_context
    context = deepen_context(state) if state.get("intake_stage") and state.get("intake_stage") != "ready" else None
    try:
        raw = json.loads(arguments) if isinstance(arguments, str) else arguments
        if not isinstance(raw, dict) or set(raw) - {"subject", "questions"}:
            return {}
        if context and subject_key(raw.get("subject", ""), state) != subject_key(context["subject"], state):
            return {}
        rows = raw.get("questions")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 4:
            return {}
        valid, seen = [], set()
        previous_dimensions = set((context or {}).get("current_progress", {}).get("asked_dimensions") or [])
        selected_dimensions = set()
        for row in rows:
            try:
                question = AskQuestion.model_validate(row)
            except (ValidationError, TypeError):
                continue
            if context and question_dimension(question.id, question.prompt) not in context["remaining_dimensions"]:
                continue
            dimension = question_dimension(question.id, question.prompt)
            if context and (dimension in selected_dimensions or len(previous_dimensions | selected_dimensions | {dimension}) > 4):
                continue
            if question.id not in seen and not is_closed(state, raw.get("subject", ""), question.id, question.prompt):
                valid.append(question.model_dump())
                seen.add(question.id)
                selected_dimensions.add(dimension)
        parsed = AskUser.model_validate({**raw, "questions": valid})
    except (ValueError, TypeError):
        return {}
    return {"kind": "ask_user", "turn_id": turn_id, "title": "补充问题", **parsed.model_dump()}


def pending_card(state: dict) -> dict:
    """只恢复最近助手轮的工具结果，不复活已经跨过的旧问题卡。"""
    if state.get("pending_plan"):
        return {}
    for message in reversed(state.get("messages") or []):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage) and (card := message.additional_kwargs.get("ask_user")):
            return validate_card({"questions": card["questions"], "subject": card.get("subject", "")}, state, card["turn_id"])
    return {}


def close_answers(state: dict, text: str, answers: dict | None = None) -> list[dict]:
    from app.agents.interviewer import NO_ANSWER

    closed = deepcopy(state.get("closed_questions") or [])
    card = pending_card(state)
    selected = []
    if answers and card and answers.get("turn_id") == card["turn_id"]:
        by_id = {row["id"]: row for row in answers.get("items") or []}
        for question in card["questions"]:
            answer = by_id.get(question["id"], {"skipped": True})
            reason = "unknown" if answer.get("unknown") else "skipped" if answer.get("skipped") or not answer.get("value") else "answered"
            selected.append((question, reason))
    elif not answers and NO_ANSWER.fullmatch(text.strip()):
        if card and len(card["questions"]) == 1:
            selected = [(card["questions"][0], "unknown" if "跳过" not in text and "不答" not in text else "skipped")]
        elif not card:
            # 自由文本单题仅用于确定答案归属；绝不据此生成卡片。
            from app.services.followup_context import latest_followup
            latest = next((m.content for m in reversed(state.get("messages") or []) if isinstance(m, AIMessage)), "")
            question = latest_followup(latest)
            if question and len(re.findall(r"[？?]", latest)) <= 1:
                subject = re.search(r"[「『]([^」』]+)[」』]", question)
                card = {"subject": subject.group(1) if subject else "", "turn_id": ""}
                selected = [({"id": question_dimension(prompt=question), "prompt": question}, "unknown")]
    for question, reason in selected:
        if not is_closed({**state, "closed_questions": closed}, card.get("subject", ""), question["id"], question["prompt"]):
            closed.append({"subject": subject_key(card.get("subject", ""), state), "id": question["id"],
                           "dimension": question_dimension(question["id"], question["prompt"]),
                           "prompt": question["prompt"], "reason": reason, "turn_id": card.get("turn_id", "")})
    return closed


def question_context(state: dict, *, tools_available: bool = True) -> str:
    from app.agents.interviewer import question_candidates
    from app.services.intake import deepen_context, intake_guidance

    card = intake_guidance(state) if state else None
    budget = "本轮正文提问预算：最多 1 个问句、只问 1 件事；需要问两个及以上问题时必须用 ask_user。"
    if card:
        collecting = ("基本信息（姓名、教育、城市与可实习时间）" if card["kind"] == "intake_basics"
                      else "经历清单（名称、类型、时间、角色与简介）")
        budget = (f"本轮正文提问预算：0 个问句。本轮卡片已在收集{collecting}，"
                  "正文只写一句过渡语，不要提问；不要同时深挖经历或询问其他信息。本轮不提供 ask_user，不得调用。")
    elif state.get("pending_plan"):
        budget = "本轮正文提问预算：0 个问句。方案卡已在等待确认，正文只写一句过渡语，不要另行提问或调用 ask_user。"
    elif (state.get("collected_info") or {}).get("no_more_questions"):
        budget = "本轮正文提问预算：0 个问句。用户已要求停止追问，不要提问或调用 ask_user。"
    elif not tools_available or not can_ask_user(state):
        budget += " 本轮 ask_user 不可用，只挑一个最有价值的问题，其余留到后续轮次。"
    contract = ASK_CONTRACT + "\n以下本轮预算优先于上面的工具规则及其他阶段提示中的追问、建议和格式要求：\n" + budget
    if state.get("intake_stage") and state.get("intake_stage") != "ready":
        return contract + "\n分阶段规则优先于旧候选：\n" + json.dumps({
            "closed_questions": state.get("closed_questions") or [], **deepen_context(state),
        }, ensure_ascii=False)
    return contract + "\n" + json.dumps({
        "closed_questions": state.get("closed_questions") or [],
        "candidate_questions": question_candidates(state),
        "pending_plan": bool(state.get("pending_plan")),
    }, ensure_ascii=False)
