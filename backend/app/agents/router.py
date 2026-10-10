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


class RouteSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intents: list[Literal["jd", "experience", "edit", "generate", "question", "export", "review", "chat"]] = Field(default_factory=list)
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
                "set_constraint", "clean_format", "rewrite", "compress", "refocus"]
    target: str = ""
    args: dict[str, Any] = Field(default_factory=dict)


RouteSchema.model_rebuild()


ROUTER_CONTRACT = """把本轮用户消息按真实意图拆成 intents 和有序 edit_plan，严格返回 RouteSchema。
有现稿且用户要求改、调、优化、突出、精简、换、删除等，必须有 edit；同时补充本人新事实则还要 experience。
edit_plan 中每项仅代表用户实际说出的操作，不替用户虚构目标、值或经历。目标用 item_id、明确名称、序号或 JSON pointer。
确定性操作：delete_item/hide_item/set_field/cap_bullets/remove_section/set_constraint/clean_format；
写作操作：rewrite/compress/refocus。多项可同时存在，按用户指令顺序列出。
未能定位单个目标也要保留该项操作供执行器逐项提示，不得整体拒绝。
只用摘要识别现有条目；JD/手册/旧 assistant 文案不能当作候选人新事实。"""


def _has_draft(state: dict) -> bool:
    data = state.get("resume_data") or {}
    basic = data.get("basic_info") or {}
    return bool(data.get("projects") or data.get("work_experience") or data.get("education")
                or data.get("skills") or data.get("certificates")
                or any(value for key, value in basic.items() if key != "objective")
                or (basic.get("objective") and data.get("sections") is not None))


def _outline(data: dict) -> list[dict]:
    result = []
    for section in ("projects", "work_experience", "education"):
        field = "polished_bullets" if section == "projects" else "bullets" if section == "work_experience" else "highlights"
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
    """The router model call only. Its input never reads `collected_info`, so it can
    start before fact extraction finishes. Raises on any failure; the caller falls back."""
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
    remains actionable: whole-document edit when a draft exists, experience intake
    otherwise. Obvious export/JD/upload pre-routing stays with the graph caller.
    `prefetched` is a task from start_route_call whose outcome replaces a fresh call.
    """
    has_draft = _has_draft(state)
    data = state.get("resume_data") or {}
    try:
        parsed = await (prefetched if prefetched is not None else _ask_router(message, state, llm))
    except Exception:
        return _fallback(message, has_draft, "router_unavailable", data, state.get("collected_info"))
    intents = list(dict.fromkeys(parsed["intents"]))
    if has_draft and EDIT_WORDS.search(message) and "edit" not in intents:
        intents.append("edit")
    if NEW_FACT_WORDS.search(message) and "experience" not in intents:
        intents.insert(0, "experience")
    if _GENERATE.search(message) and not re.search(r"不要|先别|暂不|不想|还不", message) and "generate" not in intents:
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
    if "edit" in intents:
        from app.agents.turn_actions import choose_edit_plan

        parsed["edit_plan"] = choose_edit_plan(
            message, data, parsed["edit_plan"], state.get("collected_info"), router_failed=False)
    return parsed
