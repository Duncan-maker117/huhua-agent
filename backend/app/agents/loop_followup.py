"""Loop-only question budget and public receipt guards; no model decisions."""
import re

from langchain_core.messages import AIMessage, HumanMessage

from app.services.followup_context import latest_followup
from app.services.intake import MAX_FOLLOWUP_ROUNDS


def question_rounds(state):
    rounds, asked = 0, False
    for message in state.get("messages") or []:
        if isinstance(message, HumanMessage):
            rounds += int(asked)
            asked = False
        elif isinstance(message, AIMessage):
            asked = asked or bool(message.additional_kwargs.get("ask_user") or latest_followup(message.content))
    return rounds + int(asked)


def questions_allowed(state):
    return (question_rounds(state) < MAX_FOLLOWUP_ROUNDS
            and not (state.get("session_constraints") or {}).get("questions_finished")
            and not (state.get("collected_info") or {}).get("no_more_questions"))


def answers_unknown(message):
    from app.agents.interviewer import NO_ANSWER
    items = message.additional_kwargs["answers"].get("items") or []
    for item in items:
        if item.get("unknown") or item.get("skipped"):
            continue
        values = item.get("value") or []
        values = values if isinstance(values, list) else [values]
        if any(v.strip() and not NO_ANSWER.fullmatch(v.strip()) and v.strip() not in {"不确定", "未知"} for v in values):
            return False
    return bool(items)


def contact_request(text):
    # A phone used as a camera is experience evidence, not a contact field.
    text = re.sub(r"手机(?:拍摄|拍照|剪辑|录制)", "拍摄工具", text)
    for clause in re.split(r"[，,]|但是|不过|但", text):
        if not re.search(r"手机|电话|邮箱|联系方式|\b(?:phone|email)\b", clause, re.I):
            continue
        if re.search(r"不用|无需|不必|不要|不再|留空|已(?:经)?(?:收到|提供|补齐|记下|记录)", clause):
            continue
        if re.search(r"[？?]|请|补|提供|还差|还缺|缺少|空着|方便|告诉我|发给|发我|填写", clause):
            return True
    return False


def public_clause(text, state, *, has_card=False):
    # Contact requests are emitted once by code after a successful draft/card.
    if contact_request(text):
        return ""
    if (has_card or not questions_allowed(state)) and latest_followup(text):
        return ""
    from app.services.ask_user import is_closed
    question = latest_followup(text)
    if question and is_closed(state, "", prompt=question):
        return ""
    return text


def answer_receipt(before, after, message, *, updated, has_card):
    from app.schemas.facts import FACT_SECTIONS
    facts = [fact for section in FACT_SECTIONS for item in (after.get("collected_info") or {}).get(section) or []
             for fact in item.get("facts") or [] if fact.get("turn_id") == message.id]
    if facts:
        names = {"name": "经历名称", "company": "公司名称", "school": "学校名称", "role": "角色", "title": "角色",
                 "start_date": "开始时间", "end_date": "结束时间", "problem": "问题背景", "my_work": "本人分工",
                 "decision": "关键决策", "iteration": "迭代做法", "evaluation": "评测方式", "adoption": "使用情况",
                 "status": "当前状态", "tech_stack": "技术工具", "links": "项目链接"}
        labels = list(dict.fromkeys(names.get(fact.get("field") or fact.get("dimension"), "补充信息") for fact in facts))
        recorded = "已记下：" + "、".join(labels) + "。"
    elif message.additional_kwargs.get("answer_card", {}).get("turn_id") != message.additional_kwargs["answers"].get("turn_id"):
        recorded = "这张问题卡已失效，本轮没有写入答案。"
    else:
        recorded = "已处理本轮回答；不知道或跳过的维度已关闭，没有新增可采用的事实。"
    draft = "稿子已更新。" if updated else "稿子未更新。" if before.get("resume_data") else "本轮尚未生成稿子。"
    next_step = "可填写本轮补充卡。" if has_card else "下一步在右侧查看现有稿子。" if after.get("resume_data") else "可继续提供一段真实经历。"
    return recorded + draft + next_step
