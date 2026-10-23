"""Structured multi-intent routing for resume turns; no persistence or model setup."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.career_prompt import career_messages
from app.services.llm_compat import label_run, with_structured_output
from app.services.model_privacy import ContactRedactor


ROUTER_TIMEOUT_SECONDS = 30
EDIT_WORDS = re.compile(r"改|调|优化|突出|精简|换|删除|删掉|压缩|保留|清理|去掉|移除|不要|修正|纠正")
NEW_FACT_WORDS = re.compile(r"(?:我|本人)(?:还|也|另外)?.{0,18}(?:做过|做了|参与|负责|开发|实现|完成|获得|掌握|会)")
_GREETING = re.compile(r"(?:(?:你好|您好|哈喽|哈啰|嗨|嘿|hi|hello|hey|你在吗|在吗|在嘛|在不在|有人吗|早上好|早安|下午好|晚上好|早|午安|晚安)(?:呀|啊|呢|嘛)?)+", re.I)
_ADVICE = re.compile(r"你觉得|你认为|怎么(?:说|写|表达|改).{0,8}(?:更好|合适)|这样(?:写|说).{0,6}(?:好吗|好不好|可以吗|行吗)|哪(?:一?[个种版]|条).{0,8}(?:更好|合适)")


def is_greeting(message: str) -> bool:
    return bool(_GREETING.fullmatch(re.sub(r"[\s，,。.!！?？~～]+", "", message or "")))


def is_advice(message: str) -> bool:
    return bool(_ADVICE.search(message or ""))


def advice_contains_facts(message: str) -> bool:
    """Keep statements accompanying a question, including non-action facts."""
    text = re.sub(r'[“‘「"\'][^”’」"\']*[”’」"\']', '', message or '')
    for clause in re.split(r'[，,。；;！!？?\n]', text):
        question = _ADVICE.search(clause)
        statement = (clause[:question.start()] if question else clause).strip()
        if len(statement) >= 4 and not re.search(r'假设|如果|比如|例如|举例', statement) and not re.match(
                r'^(?:请|帮我|给我|把|将|按|修改|改写|优化|精简|删除|不要)', statement):
            return True
    return False


def explicit_edit_requested(message: str) -> bool:
    """Advice questions and past actions are not instructions to change a draft."""
    text = re.sub(r'[“‘「"\'][^”’」"\']*[”’」"\']', '', message or '')
    text = re.sub(r'(?:并且|然后|同时|以及|顺便|另外|并)(?=请|帮我|给我|直接|先|再|把|将)', '；', text)
    for clause in re.split(r'[，,。；;！!？?\n]', text):
        clause = clause.strip()
        clause = re.sub(r'^(?:另外|顺便|然后|同时|也)', '', clause).strip()
        clause = re.sub(r'^(?:能不能|可不可以|能否|可以|能)(?=帮我|给我)', '', clause)
        if re.search(r'不要|先别|暂不|不想|还不|别急|要不要|是否|能否', clause):
            continue
        if is_advice(clause) and not re.match(r'^(?:请|帮我|给我|麻烦|把|将)', clause):
            continue
        if re.search(r'^(?:请|帮我|给我|麻烦|把|将|按|直接|现在|先|再|就).{0,40}'
                     r'(?:改|调|优化|突出|精简|换|删|压缩|保留|清理|去掉|移除|写上|写进|加进)', clause):
            return True
        if re.match(r'^(?:修改|改写|改稿|调整|优化|突出|精简|换成|删除|删掉|压缩|保留|清理|去掉|移除|改成|改为|改短|改一下|写上|写进)', clause):
            return True
    return False


class RouteSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intents: list[Literal["jd", "experience", "edit", "generate", "question", "export", "review", "chat", "greeting", "advice"]] = Field(default_factory=list)
    edit: "EditRoute" = Field(default_factory=lambda: EditRoute())
    edit_plan: list["PlannedOperation"] = Field(default_factory=list)
    reason: str = ""


class EditRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["whole", "section", "item", "bullet"] = "whole"
    targets: list[str] = Field(default_factory=list)
    instruction: str = ""


class PlannedOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["delete_item", "hide_item", "set_field", "cap_bullets", "remove_section",
                "set_constraint", "clean_format", "move_item", "merge_duplicates", "rewrite", "compress", "refocus"]
    target: str = ""
    args: dict[str, Any] = Field(default_factory=dict)


RouteSchema.model_rebuild()


ROUTER_CONTRACT = """把本轮用户消息按真实意图拆成 intents 和有序 edit_plan，严格返回 RouteSchema。
纯寒暄、打招呼用 greeting；征求措辞意见、比较说法（怎么说更好、这样写好吗、你觉得呢）用 advice。
advice 不代表改稿，不得生成 edit_plan；只有同轮明确要求修改文稿才同时有 edit。新事实与 advice 可以并存。
有现稿且用户要求改、调、优化、突出、精简、换、删除等，必须有 edit；同时补充本人新事实则还要 experience。
edit_plan 中每项仅代表用户实际说出的操作，不替用户虚构目标、值或经历。目标用 item_id、明确名称、序号或 JSON pointer。
确定性操作：delete_item/hide_item/set_field/cap_bullets/remove_section/set_constraint/clean_format/move_item；用户纠正「这是开源贡献」「这个放到竞赛荣誉」用move_item，args.section为campus/open_source/awards，args.name为明确提供的仓库/奖项标题；不要改写成独立/团队职责问题。
写作操作：rewrite/compress/refocus。多项可同时存在，按用户指令顺序列出。
未能定位单个目标也要保留该项操作供执行器逐项提示，不得整体拒绝。
只用摘要识别现有条目；JD/手册/旧 assistant 文案不能当作候选人新事实。"""


def _has_draft(state: dict) -> bool:
    data = state.get("resume_data") or {}
    basic = data.get("basic_info") or {}
    return bool(data.get("projects") or data.get("work_experience") or data.get("education")
                or data.get("skills") or data.get("certificates") or data.get("campus") or data.get("open_source") or data.get("awards")
                or any(value for key, value in basic.items() if key != "objective")
                or (basic.get("objective") and data.get("sections") is not None))


def _outline(data: dict) -> list[dict]:
    result = []
    for section in ("projects", "work_experience", "education", "campus", "open_source", "awards"):
        field = "polished_bullets" if section == "projects" else "bullets" if section in {"work_experience", "campus", "open_source", "awards"} else "highlights"
        for index, item in enumerate(data.get(section) or []):
            if not isinstance(item, dict):
                continue
            bullets = item.get(field) or []
            if isinstance(bullets, str):
                bullets = [bullets]
            result.append({"section": section, "index": index, "item_id": item.get("item_id", ""),
                           "name": item.get("name") or item.get("company") or item.get("school") or "",
                           "bullets": [{"index": n, "lead": str(text)[:20]} for n, text in enumerate(bullets)],
                           "hidden": item.get("hidden") is True})
    return result


_GENERATE = re.compile(r"出一版|写一版|生成吧|直接写吧|先出稿|先给我出")


def _fallback(message: str, has_draft: bool, reason: str, data: dict | None = None,
              collected: dict | None = None) -> dict:
    if is_greeting(message) or (is_advice(message) and not explicit_edit_requested(message)):
        intents = ["greeting"] if is_greeting(message) else ["advice"]
        if intents == ["advice"] and advice_contains_facts(message):
            intents.insert(0, "experience")
        return {**RouteSchema(intents=intents, reason=reason).model_dump(), "fallback_reason": reason}
    if has_draft:
        from app.agents.tailor_pipeline import infer_edit_scope
        from app.agents.turn_actions import choose_edit_plan

        scope, targets = infer_edit_scope(data or {}, message)
        if targets:
            plan = [{"op": "rewrite", "target": target, "args": {}} for target in targets]
        else:
            scope, targets, plan = "whole", [], [{"op": "rewrite", "target": "whole", "args": {}}]
        plan = choose_edit_plan(message, data, plan, collected, router_failed=True)
        return {"intents": ["edit"], "edit": {"scope": scope, "targets": targets, "instruction": message},
                "edit_plan": plan, "reason": reason, "fallback_reason": reason}
    return {"intents": ["experience"],
            "edit": {"scope": "whole", "targets": [], "instruction": ""},
            "edit_plan": [], "reason": reason, "fallback_reason": reason}


async def _ask_router(message: str, state: dict, llm) -> dict:
    """Known dialogue bypasses the model; other calls can overlap fact extraction.

    The input never reads `collected_info`. The caller handles model failures.
    """
    from app.services.resume_layout import density_only_request, density_operations
    if _has_draft(state) and density_only_request(message):
        return RouteSchema(intents=['edit'], edit_plan=density_operations(message)).model_dump()
    if is_greeting(message) or (is_advice(message) and not explicit_edit_requested(message)):
        intents = ["greeting"] if is_greeting(message) else ["advice"]
        if intents == ["advice"] and advice_contains_facts(message):
            intents.insert(0, "experience")
        return RouteSchema(intents=intents).model_dump()
    has_draft = _has_draft(state)
    data = state.get("resume_data") or {}
    prior = next((getattr(row, "content", "") for row in reversed(state.get("messages") or [])
                  if getattr(row, "type", "") == "ai"), "")
    payload = {"message": message, "previous_assistant": str(prior)[:500],
               "has_jd": bool(state.get("jd_info") or state.get("jd_text")),
               "has_draft": has_draft, "outline": _outline(data)}
    privacy = ContactRedactor()
    messages = career_messages(None, json.dumps(payload, ensure_ascii=False), ROUTER_CONTRACT, privacy=privacy)
    response = await asyncio.wait_for(
        label_run(with_structured_output(llm, RouteSchema), "router").ainvoke(messages), ROUTER_TIMEOUT_SECONDS)
    if isinstance(response, BaseModel):
        response = response.model_dump()
    elif not isinstance(response, dict):
        response = json.loads(response.content)
    return RouteSchema.model_validate(privacy.restore(response)).model_dump()


def start_route_call(message: str, state: dict, llm) -> "asyncio.Task[dict]":
    """Speculatively start the router model call; pass the task to route_intents(prefetched=...).

    `state` must carry the same messages/jd/resume_data that route_intents will receive.
    """
    return asyncio.ensure_future(_ask_router(message, state, llm))


async def route_intents(message: str, state: dict, llm, *, prefetched=None) -> dict:
    """Route a turn without changing its fact master or creating model settings.

    The caller supplies a temperature-zero model. A timeout or malformed result
    remains actionable: known dialogue stays read-only, other turns fall back to
    draft editing or experience intake. Export/JD/upload pre-routing stays with the graph caller.
    `prefetched` is a task from start_route_call whose outcome replaces a fresh call.
    """
    has_draft = _has_draft(state)
    data = state.get("resume_data") or {}
    try:
        parsed = await (prefetched if prefetched is not None else _ask_router(message, state, llm))
    except Exception:
        parsed = _fallback(message, has_draft, "router_unavailable", data, state.get("collected_info"))
        if is_advice(message):
            if "advice" not in parsed["intents"]:
                parsed["intents"].append("advice")
            if advice_contains_facts(message) and "experience" not in parsed["intents"]:
                parsed["intents"].insert(0, "experience")
        return parsed
    intents = list(dict.fromkeys(parsed["intents"]))
    advice = is_advice(message) or "advice" in intents
    if advice and "advice" not in intents:
        intents.append("advice")
    if advice and not explicit_edit_requested(message):
        intents = [intent for intent in intents if intent not in {"edit", "generate"}]
        parsed["edit_plan"] = []
    if has_draft and EDIT_WORDS.search(message) and (not advice or explicit_edit_requested(message)) and "edit" not in intents:
        intents.append("edit")
    if (advice_contains_facts(message) if advice else NEW_FACT_WORDS.search(message)) and "experience" not in intents:
        intents.insert(0, "experience")
    if not advice and _GENERATE.search(message) and not re.search(r"不要|先别|暂不|不想|还不", message) and "generate" not in intents:
        intents.append("generate")
    if not intents:
        intents = ["edit"] if has_draft else ["experience"]
    parsed["intents"] = intents
    parsed["edit"]["instruction"] = message if "edit" in intents else ""
    parsed["fallback_reason"] = ""
    if "edit" in intents and not parsed["edit_plan"]:
        from app.agents.tailor_pipeline import infer_edit_scope

        scope, targets = infer_edit_scope(data, message)
        if scope == "item" and not targets:
            ordinal = re.search(r"第[一二两三四五六七八九十1-9]+(?:个|段)?(?:项目|经历|实习|工作)", message)
            parsed["edit_plan"] = [{"op": "rewrite", "target": ordinal[0] if ordinal else "", "args": {}}]
        else:
            parsed["edit_plan"] = [{"op": "rewrite", "target": target, "args": {}}
                                   for target in targets] if targets else [
                                       {"op": "rewrite", "target": "whole", "args": {}}]
        parsed["edit"]["scope"] = scope
        parsed["edit"]["targets"] = targets
    from app.agents.turn_actions import section_move_ops
    if has_draft and (not advice or explicit_edit_requested(message)) and section_move_ops(message, data):
        intents = [*intents, "edit"] if "edit" not in intents else intents
        parsed["intents"] = intents
    if "edit" in intents:
        from app.agents.turn_actions import choose_edit_plan

        parsed["edit_plan"] = choose_edit_plan(
            message, data, parsed["edit_plan"], state.get("collected_info"), router_failed=False)
    return parsed
