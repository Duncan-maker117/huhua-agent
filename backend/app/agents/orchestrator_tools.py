"""Tool adapters for the opt-in loop; no routing or public-reply model calls."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
import inspect
import json
import re
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.ask_user import AskUser, is_closed, question_dimension
from app.services.model_privacy import ContactRedactor
from app.services.profile_tools import ReadProfile, UseProfileItems


@dataclass
class ToolOutcome:
    result: dict
    update: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    stop: bool = False


@dataclass
class ToolContext:
    """Create once per user turn. Keep this object out of prompts/checkpoints.

    llm is the existing business ChatOpenAI (or an offline double), not the
    orchestration SDK client. emit optionally streams tool_status immediately;
    events also contains the same receipts for callers without a stream writer.
    Existing profile_runtime / _intake_saver contexts are inherited unchanged.
    """
    llm: Any = None
    structured_llm: Any = None
    turn_id: str = field(default_factory=lambda: str(uuid4()))
    emit: Callable | None = None
    company_used: bool = False
    ask_used: bool = False
    followup_available: bool = True
    automatic_tools: list[dict] = field(default_factory=list)
    profile_item_ids: set[str] = field(default_factory=set)
    recorded_sources: set[str] = field(default_factory=set)
    corrected_sources: set[str] = field(default_factory=set)
    jd_sources: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ToolSpec:
    args_model: type[BaseModel]
    description: str
    handler: Callable


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class SourceArgs(NoArgs):
    source_id: str = Field(min_length=1, max_length=128)


class CompanyArgs(NoArgs):
    name: str = Field(min_length=1, max_length=80)


class AskArgs(NoArgs):
    card: AskUser


class WriteArgs(NoArgs):
    direction: str | None = Field(default=None, min_length=1, max_length=200)
    emphasis: str | None = Field(default=None, min_length=1, max_length=1000)


class EditArgs(NoArgs):
    instruction: str = Field(min_length=1, max_length=4000)


def _safe_result(result: dict, state: dict, update: dict, tool: str) -> dict:
    from app.services.structure_plan import user_plan_text
    current = {**state, **update}
    profile = (current.get("jd_info") or {}).get("role_profile") or {}
    hidden = {"id", "item_id", "fact_id", "fact_ids", "req_id", "req_ids", "slot_id", "slot_ids",
              "coverage_fact_ids", "text_hash", "profile_refs", "sources", "turn_id", "source_id",
              "profile_statement_fact_ids", "labeled_slots", "slot_trace", "slot_lines", "edit_contract"}
    names = {}

    def collect(value):
        if isinstance(value, dict):
            label = value.get("name") or value.get("company") or value.get("school") or ""
            if value.get("item_id"):
                identifier = str(value["item_id"])
                names[identifier] = str(label or names.get(identifier) or "")
            if value.get("id"):
                names[str(value["id"])] = str(value.get("signal") or value.get("text") or "") if (
                    value.get("signal") or value.get("priority")) else ""
            for key, row in value.items():
                if key in hidden and key.endswith(("_id", "_ids")):
                    for identifier in row if isinstance(row, list) else [row]:
                        if isinstance(identifier, str):
                            names.setdefault(identifier, "")
                collect(row)
        elif isinstance(value, list):
            for row in value:
                collect(row)

    for value in (current.get("collected_info"), current.get("resume_data"), profile, result):
        collect(value)
    identifiers = sorted((key for key in names if key), key=len, reverse=True)
    pattern = re.compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(map(re.escape, identifiers)) + r")(?![A-Za-z0-9_])") if identifiers else None

    def readable(value, path=()):
        if isinstance(value, dict):
            selectable = (tool == "read_profile" and path == ("items",)
                          or path in {("followup", "questions"), ("card", "questions")})
            return {(pattern.sub(lambda match: names[match[0]], key) if pattern else key):
                    (row if selectable and key == "id"
                          else readable(row, (*path, key)))
                    for key, row in value.items() if key not in hidden or (
                        selectable and key == "id")}
        if isinstance(value, list):
            return [readable(row, path) for row in value]
        if isinstance(value, str):
            value = user_plan_text(value, profile)
            value = pattern.sub(lambda match: names[match[0]], value) if pattern else value
            return re.sub(r"(?<![A-Za-z0-9_])(?:" + "|".join(sorted(hidden)) + r")(?![A-Za-z0-9_])", "", value)
        return value

    privacy = ContactRedactor()
    # Tool data is JSON text, including objects resembling opaque media blocks.
    return json.loads(privacy.redact(json.dumps(privacy.redact(readable(result)), ensure_ascii=False)))


def _error(code: str, **details) -> ToolOutcome:
    return ToolOutcome({"status": "error", "code": code, **details})


def _source(state: dict, source_id: str) -> HumanMessage | None:
    humans = [m for m in state.get("messages") or [] if isinstance(m, HumanMessage)]
    if source_id == "current":
        return humans[-1] if humans else None
    return next((m for m in humans if m.id == source_id), None)


def _source_parts(text: str) -> tuple[str, str]:
    from app.services.candidate_material import split_mixed_material
    candidate, jd = split_mixed_material(text)
    # The legacy splitter requires education in a prefix before JD. An explicit
    # ownership label is also sufficient; an unlabelled first-person JD is not.
    if not jd and (marker := re.search(r"(?:^|\n)\s*(?:目标\s*)?JD\s*[:：]", text, re.I)):
        prefix = text[:marker.start()]
        if re.search(r"(?:^|\n)\s*(?:我的经历|本人经历|我的项目)\s*[:：]", prefix):
            return prefix, text[marker.start():]
    return candidate, jd


def _structured(ctx: ToolContext):
    from langchain_openai import ChatOpenAI
    from app.agents.resume_graph import _make_non_streaming_llm
    if ctx.structured_llm is not None:
        return ctx.structured_llm
    return _make_non_streaming_llm(ctx.llm, temperature=0) if isinstance(ctx.llm, ChatOpenAI) else ctx.llm


def _register(name, args_model, description, progress):
    def decorate(handler):
        async def run(state, args, ctx):
            try:
                parsed = args_model.model_validate(args.model_dump() if isinstance(args, BaseModel) else args)
            except (ValidationError, TypeError):
                return _error("invalid_arguments")
            events = []

            async def status(value, message):
                event = {"type": "tool_status", "tool": name, "status": value, "message": message}
                events.append(event)
                if ctx.emit:
                    sent = ctx.emit(deepcopy(event))
                    if inspect.isawaitable(sent):
                        await sent

            await status("running", progress)
            try:
                outcome = await handler(deepcopy(state), parsed, ctx)
            except Exception as exc:
                # Provider/persistence errors can echo private source text.
                outcome = _error("tool_exception", error_type=type(exc).__name__)
            outcome.result = _safe_result(outcome.result, state, outcome.update, name)
            completed = outcome.result.get("status") in {"ok", "partial", "unchanged"}
            await status("completed", "处理完成" if completed else "本次处理未完成，请查看结果")
            outcome.events = [*events, *outcome.events]
            return outcome
        TOOLS[name] = ToolSpec(args_model, description, run)
        return run
    return decorate


TOOLS: dict[str, ToolSpec] = {}


def tool_schemas() -> list[dict]:
    return [{"type": "function", "function": {"name": name, "description": spec.description,
             "parameters": spec.args_model.model_json_schema()}} for name, spec in TOOLS.items()]


async def execute_tool(name: str, state: dict, args: dict, ctx: ToolContext) -> ToolOutcome:
    spec = TOOLS.get(name)
    return await spec.handler(state, args, ctx) if spec else _error("unknown_tool")


@_register("read_profile", ReadProfile, "读取本账号的档案目录，不自动采用。", "正在读取档案…")
async def read_profile(state, args, ctx):
    from app.services.profile_tools import execute_profile_tool
    ctx.profile_item_ids.clear()
    result, update = await execute_profile_tool("read_profile", args.model_dump(), state)
    if result.get("status") == "ok":
        ctx.profile_item_ids = {item["id"] for item in result.get("items") or []}
    return ToolOutcome(result, update)


@_register("use_profile_items", UseProfileItems, "采用刚读取的本人档案条目 ID，保留原有事实来源。", "正在选用档案经历…")
async def use_profile_items(state, args, ctx):
    from app.services.profile_tools import execute_profile_tool
    if any(identifier not in ctx.profile_item_ids for identifier in args.item_ids):
        return _error("read_profile_first_or_unknown_item")
    result, update = await execute_profile_tool("use_profile_items", args.model_dump(), state)
    if result.get("status") == "ok" and result.get("imported"):
        result["message"] = "已从档案导入：" + "、".join(result["imported"]) + "。"
    return ToolOutcome(result, update)


@_register("read_jd", SourceArgs, "读取用户消息中的岗位正文或招聘链接，只传 source_id，岗位要求不是本人事实。", "正在读岗位…")
async def read_jd(state, args, ctx):
    from app.agents.decoder_chain import run_decoder_chain
    from app.agents.resume_graph import _clear_structure_plan, _jd_decode_allowed
    from app.services.resume_strategy import build_resume_strategy
    source = _source(state, args.source_id)
    if source is None or not isinstance(source.content, str):
        return _error("unknown_source")
    if ctx.llm is None and ctx.structured_llm is None:
        return _error("model_unavailable")
    candidate, jd = _source_parts(source.content)
    text, page, card = jd or source.content, None, None
    urls = re.findall(r"https?://[^\s<>\]）)]+", text)
    if not jd and not urls and not _jd_decode_allowed(text, state):
        return _error("not_job_material")
    if urls:
        if len(set(urls)) != 1:
            return _error("multiple_urls")
        from app.services.job_intel import read_job_url
        fetched = await read_job_url(urls[0].rstrip("。，,；;"), llm=_structured(ctx))
        if fetched.get("status") != "ok":
            return ToolOutcome({"status": fetched.get("status", "unavailable"),
                                "code": "job_url_not_readable", "message": fetched.get("message", "请提供岗位正文。")})
        page, card = fetched["page"], fetched["card"]
        text = page["content"]
    decoded = await run_decoder_chain(text, _structured(ctx))
    info = decoded.get("jd_info") or {}
    if not any(info.get(key) for key in ("job_title", "required_skills", "key_responsibilities", "hard_requirements")):
        return ToolOutcome({"status": "insufficient", "missing": ["明确的岗位正文"]})
    info = {**info, "decoded_items": decoded.get("decoded_items", []), "summary": decoded.get("summary", "")}
    update = {**_clear_structure_plan(state), "jd_info": info, "jd_text": text, "jd_skipped": False,
              "resume_strategy": build_resume_strategy(jd_info=info, has_jd=True)}
    # A mixed message still has a candidate part that record_facts may consume.
    if not jd or not candidate.strip():
        ctx.jd_sources.add(source.id or args.source_id)
        if source.id:
            update["non_candidate_message_ids"] = list(dict.fromkeys([*state.get("non_candidate_message_ids", []), source.id]))
    if card:
        info.update(source="job_url", url=card["url"], fetched_at=card["fetched_at"], job_card=card)
        from app.services.resume_workspace import bounded_web_sources
        update["web_sources"] = bounded_web_sources([*(state.get("web_sources") or []), {**page, "job_card": card}])
    return ToolOutcome({"status": "ok", "source_kind": "jd", "candidate_facts": False, "jd_info": info}, update)


@_register("search_company", CompanyArgs, "查询目标公司的公开资料，每轮至多一次；结果仅供参考。", "正在查询公司资料…")
async def search_company(state, args, ctx):
    from app.services.job_intel import search_company as search
    from app.services.job_intel.integration import company_tool
    if ctx.company_used:
        return ToolOutcome({"status": "limited", "code": "company_search_already_used"})
    ctx.company_used = True
    allowed = await company_tool(args.model_dump(), state)
    if isinstance(allowed, dict):
        return ToolOutcome(allowed)
    # A company name is the only search input; never send the conversation.
    if ContactRedactor().redact(args.name) != args.name:
        return _error("contacts_in_company_name")
    result = await search(args.name, llm=_structured(ctx))
    update = {"jd_info": {**(state.get("jd_info") or {}), "company": result["company"]}} if result.get("status") == "ok" else {}
    return ToolOutcome(result, update)


@_register("record_facts", SourceArgs, "从本人原始消息记录事实，只传 source_id；拒绝 JD、他人材料和模型自写正文。", "正在记录你的经历…")
async def record_facts(state, args, ctx):
    from app.agents.fact_extractor import _candidate_evidence, apply_fact_patch, extract_facts_patch
    from app.agents.resume_graph import (
        _candidate_source_allowed, _clean_unrecorded_notes, _direction_profile_update,
        _latest_previous_assistant, _merge_imported_candidate, _no_more_questions, _persist_intake,
    )
    from app.agents.turn_actions import absorb_education
    from app.services.candidate_material import parse_existing_resume
    from app.services.resume_facts import normalize_fact_store
    source = _source(state, args.source_id)
    if source is None or not isinstance(source.content, str):
        return _error("unknown_source")
    source_id = source.id or args.source_id
    text, jd = _source_parts(source.content)
    candidate = source
    if jd and source.additional_kwargs.get("career_material_type") not in {"review", "reference"}:
        candidate = source.model_copy(update={"content": text, "additional_kwargs": {
            **source.additional_kwargs, "career_material_type": "candidate"}})
    if (source_id in ctx.jd_sources or source_id in (state.get("non_candidate_message_ids") or [])
            or not _candidate_source_allowed(candidate)):
        return _error("not_candidate_material")
    if source_id in ctx.recorded_sources:
        return ToolOutcome({"status": "unchanged", "code": "source_already_recorded"})
    from app.services.fact_corrections import correction_pairs
    pairs = correction_pairs(text, state.get("collected_info"))
    if pairs and state.get("resume_data"):
        from app.agents.resume_graph import _literal_correction_update
        corrected = await _literal_correction_update(state, text, pairs)
        if "resume_data" not in corrected:
            return ToolOutcome({"status": "insufficient", "code": "correction_not_applied",
                                "message": corrected["messages"][0].content})
        intake = await _persist_intake(state, corrected["collected_info"])
        corrected.pop("messages", None)
        outcome = _document_outcome({**intake, **corrected})
        outcome.result["correction_applied"] = True
        outcome.stop = True
        ctx.recorded_sources.add(source_id)
        ctx.corrected_sources.add(source_id)
        return outcome
    text = _candidate_evidence(text)
    if not _candidate_evidence(text).strip():
        return _error("not_candidate_material")
    previous = normalize_fact_store(state.get("collected_info") or {})
    imported = parse_existing_resume(text)
    patch = {}
    if imported:
        collected = _merge_imported_candidate(previous, imported)
    else:
        if ctx.llm is None and ctx.structured_llm is None:
            return _error("model_unavailable")
        index = state["messages"].index(source)
        patch = await extract_facts_patch(text, previous, _structured(ctx), turn_id=source_id,
            metadata_context=previous.get("metadata_context"),
            previous_assistant=_latest_previous_assistant(state["messages"][:index]))
        collected = apply_fact_patch(previous, patch)
        _clean_unrecorded_notes(collected, previous, patch)
    _bind_campus_identity(collected)
    collected = absorb_education(collected, previous, text, source_id)
    if _no_more_questions({"messages": [source]}):
        collected["no_more_questions"] = True
    uncovered = list(patch.get("uncovered") or [])
    incomplete = list(patch.get("incomplete") or [])
    notes = collected.setdefault("verification_notes", [])
    notes.extend(note for note in [*[f"这句没有记下来：{s}" for s in uncovered],
                                  *[f"待补充：「{s}」后面还没说完" for s in incomplete]] if note not in notes)
    collected["verification_notes"] = notes[-30:]
    from app.schemas.facts import FACT_SECTIONS
    for section in FACT_SECTIONS:
        for item in collected.get(section) or []:
            for fact in item.get("facts") or []:
                if not fact.get("turn_id") and not any(fact.get("id") == old.get("id")
                        for row in previous.get(section) or [] for old in row.get("facts") or []):
                    fact["turn_id"] = source_id
                    for origin in fact.get("sources") or []:
                        if not origin.get("turn_id"):
                            origin["turn_id"] = source_id
    update = await _persist_intake(state, collected)
    update.update(_direction_profile_update(state, text, collected))
    ctx.recorded_sources.add(source_id)
    return ToolOutcome({"status": "partial" if uncovered or incomplete else "ok",
                        "changed": collected != previous, "collected_info": collected,
                        "uncovered": uncovered, "incomplete": incomplete,
                        "rejected_count": len(patch.get("rejected") or [])}, update)


def _bind_campus_identity(collected):
    """Rejoin a placeholder only when its role names one same-turn campus item."""
    from app.services.candidate_language import placeholder_name
    from app.services.fact_corrections import apply_experience_merges
    items = collected.get("campus") or []
    for item in items[:]:
        if not placeholder_name(item.get("name", "")):
            continue
        active = [f for f in item.get("facts") or [] if f.get("status", "active") == "active"]
        roles = [f for f in active if f.get("kind") == "role" and f.get("turn_id")]
        matches = [(other, fact) for other in items if other is not item and other.get("name")
                   and not placeholder_name(other["name"]) for fact in roles
                   if re.search(r"(?:在|于)\s*" + re.escape(other["name"]) + r"\s*(?:担任|任|做)", fact["text"])
                   and any(f.get("turn_id") == fact["turn_id"] for f in other.get("facts") or [])]
        targets = {row["item_id"] for row, _ in matches}
        if len(targets) != 1:
            continue
        target, role = matches[0]
        if any(f.get("turn_id") != role["turn_id"] for f in active):
            continue
        # Conflicting periods may be separate stints in the same organization.
        if any(item.get(key) and target.get(key) and item[key] != target[key] for key in ("start_date", "end_date")):
            continue
        apply_experience_merges(collected, [{"section": "campus", "name": target["name"],
            "target_item_id": target["item_id"], "source_item_ids": [item["item_id"]],
            "source_quote": role.get("source_quote") or role["text"], "turn_id": role["turn_id"]}])


@_register("ask_user", AskArgs, "给出必要的补充问题卡；跳过已关闭的维度，不将选项当作事实。", "正在整理补充问题…")
async def ask_user(state, args, ctx):
    if ctx.ask_used:
        return ToolOutcome({"status": "limited", "code": "question_card_already_used"})
    if state.get("pending_plan") or (state.get("collected_info") or {}).get("no_more_questions"):
        return ToolOutcome({"status": "unavailable", "code": "questions_disabled"})
    questions, seen = [], set()
    contacts = False
    for question in args.card.questions:
        contact_question = bool(re.search(r"手机|电话|邮箱|联系方式|phone|email", question.prompt + question.placeholder + question.id, re.I))
        if contact_question and (not state.get("resume_data") or not _missing_contacts(state)
                                or ((state.get("session_constraints") or {}).get("contacts_requested")
                                    and not _export_contacts_requested(state))):
            continue
        dimension = question_dimension(question.id, question.prompt)
        if dimension not in seen and not is_closed(state, args.card.subject, question.id, question.prompt):
            questions.append(question.model_dump())
            seen.add(dimension)
            contacts = contacts or contact_question
    if not questions:
        return ToolOutcome({"status": "unavailable", "code": "questions_closed"})
    card = {"kind": "ask_user", "turn_id": ctx.turn_id, "title": "补充问题",
            "subject": args.card.subject, "questions": questions}
    message = AIMessage(content="", id=str(uuid4()), additional_kwargs={"ask_user": card, "ask_user_enabled": True})
    ctx.ask_used = True
    update = {"messages": [message]}
    if contacts:
        update["session_constraints"] = {**(state.get("session_constraints") or {}), "contacts_requested": True}
    return ToolOutcome({"status": "ok", "card": card}, update,
                       [{"type": "guidance", "guidance": card}], stop=True)


def _has_experience(collected):
    from app.schemas.facts import FACT_SECTIONS
    from app.services.resume_facts import active_facts_for_writer
    active = active_facts_for_writer(collected)
    # 档案导入的事实统一为 kind=context，按档案字段判断是否属于具体做法/结果。
    profile_fields = {"description", "result", "deliverable", "tool", "summary", "pr"}
    return any(fact.get("text", "").strip() and (fact.get("kind") in {
        "action", "method_tool", "deliverable", "result_metric", "result_qualitative",
    } or (fact.get("profile_refs") and (fact.get("profile_field") or fact.get("field")) in profile_fields))
        for section in FACT_SECTIONS if section != "education" for item in active.get(section) or []
        for fact in item.get("facts") or [])


def _project_contacts(data, collected):
    basic = data.setdefault("basic_info", {})
    for key in ("phone", "email"):
        if key in (collected.get("basic_info") or {}):
            basic[key] = collected["basic_info"][key] or ""


def _project_identity(data, state):
    from app.services.candidate_language import safe_objective
    collected = state.get("collected_info") or {}
    _project_contacts(data, collected)
    basic = data.setdefault("basic_info", {})
    saved = ((state.get("resume_data") or {}).get("basic_info") or {}).get("objective")
    fact = (collected.get("basic_info") or {}).get("objective")
    jd = state.get("jd_info") or {}
    direction = jd.get("role_direction") or jd.get("job_title") or jd.get("target_role") or fact
    # Direction extraction can append a long parenthesized skills brief. The
    # heading uses its job label, not the full brief rejected by safe_objective.
    direction = safe_objective(direction) or safe_objective(re.split(r"[（(]", str(direction or ""), maxsplit=1)[0])
    # Keep a user's edited heading; otherwise the conversation direction wins.
    basic["objective"] = safe_objective(saved if saved and saved not in {fact, direction} else direction or saved or basic.get("objective"))


def _draft_followup(state, ctx):
    from app.agents.interviewer import question_candidates
    from app.services.ask_user import validate_card
    if ctx.ask_used or state.get("pending_plan") or (state.get("collected_info") or {}).get("no_more_questions"):
        return {}
    items = {item["item_id"]: item for section in ("projects", "work_experience", "campus", "open_source", "awards")
             for item in (state.get("resume_data") or {}).get(section) or [] if item.get("item_id")}
    for row in question_candidates(state):
        item = items.get((row.get("improves") or {}).get("item_id"), {})
        subject = item.get("name") or item.get("company") or ""
        prompt = row["q"].removeprefix(subject + "：")
        identifier = question_dimension("q_" + row["question_id"], prompt)
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", identifier):
            identifier = "q_" + row["question_id"]
        question = {"id": identifier, "prompt": prompt if len(prompt) <= 40 else "这段经历还有什么细节可以补充？",
                    "placeholder": prompt[:120] if len(prompt) > 40 else "", "kind": "text"}
        card = validate_card({"subject": subject[:120], "questions": [question]}, state, ctx.turn_id)
        if card:
            return {"subject": card["subject"], "questions": card["questions"]}
    return {}


async def attach_draft_followup(state, followup, ctx):
    """Use the same tool/validator even when no model decision budget remains."""
    began = perf_counter()
    outcome = await ask_user(state, {"card": followup}, ctx)
    ctx.automatic_tools.append({"name": "ask_user", "seconds": round(perf_counter() - began, 4),
                               "status": outcome.result.get("status"), "automatic": True})
    return outcome


@_register("propose_plan", NoArgs, "依据已记录事实生成结构方案卡，等待用户选择。", "正在整理简历方案…")
async def propose_plan(state, args, ctx):
    from app.agents.resume_graph import _serialize_to_resume_data
    from app.services.structure_plan import plan_guidance
    collected = state.get("collected_info") or {}
    if not _has_experience(collected):
        return ToolOutcome({"status": "insufficient", "missing": ["至少一段经历的具体做法"]})
    card = state.get("pending_plan")
    if not card:
        if ctx.llm is None:
            return _error("model_unavailable")
        card = await _structure_card(state, ctx, _serialize_to_resume_data({**state, "messages": []}), "")
    guidance = {**plan_guidance(card, collected, (state.get("jd_info") or {}).get("role_profile")), "turn_id": ctx.turn_id}
    return ToolOutcome({"status": "ok", "plan": card},
                       {"pending_plan": card, "confirmed_plan": {}, "plan_required": True, "stage": "BUILDING"},
                       [{"type": "guidance", "guidance": guidance}], stop=True)


async def _structure_card(state, ctx, base, instruction):
    from app.agents.resume_writer import run_resume_writer
    from app.agents.resume_graph import _make_writer_llm
    from app.agents.tailor_pipeline import constraints_for_turn
    from app.services.resume_workspace import bounded_web_sources
    planned = await run_resume_writer(state.get("collected_info") or {},
        (state.get("jd_info") or {}).get("role_profile") or {}, _make_writer_llm(ctx.llm),
        current_data=base, resume_meta=state.get("resume_meta") or {}, structured_llm=_structured(ctx),
        instruction=instruction, constraints=constraints_for_turn(state, instruction), mode="two_pass", phase="plan",
        planning_context={"jd_info": state.get("jd_info") or {},
                          "company_sources": bounded_web_sources(state.get("web_sources"), content_limit=1800)})
    return planned["structure_plan"]


async def _write(state, ctx, instruction, *, scope="whole", targets=(), base=None, plan_draft=False):
    from app.agents.resume_graph import _make_writer_llm, _serialize_to_resume_data
    from app.agents.tailor_pipeline import run_tailor_pipeline
    from app.config import get_settings
    if ctx.llm is None:
        return _error("model_unavailable")
    collected = state.get("collected_info") or {}
    # Legacy serialization can harvest optional fields from chat history.
    # Loop writing may use only the fact master and the saved document.
    base = deepcopy(base) if base is not None else _serialize_to_resume_data({**state, "messages": []})
    _project_identity(base, state)
    if plan_draft:
        from app.services.structure_plan import select_plan, accept_profile, edit_plan, plan_action
        from app.agents.resume_graph import _latest_human_text
        confirmed = state.get("confirmed_plan") or (state.get("resume_meta") or {}).get("confirmed_plan")
        latest = _latest_human_text(state)
        if not confirmed:
            card = state.get("pending_plan") or await _structure_card(state, ctx, base, instruction or latest)
            action, index = plan_action(latest, card)
            selected = select_plan(card, index if action == "confirm" else 0)
            if selected is None:
                return ToolOutcome({"status": "insufficient", "missing": ["有效的结构方案选择"]})
            confirmed = accept_profile(selected)
        confirmed, _ = edit_plan(confirmed, latest, collected)
        state = {**state, "confirmed_plan": confirmed, "pending_plan": {}, "plan_required": False}
    update = await run_tailor_pipeline(state, base, _make_writer_llm(ctx.llm), structured_llm=_structured(ctx),
        instruction=instruction, scope=scope, targets=targets, mode=get_settings().LLM_WRITER_MODE)
    # The writer/pipeline is not another fact intake entry point.
    update.pop("collected_info", None)
    data = update["resume_data"]
    before_projection = deepcopy(data)
    _restore_unwritten_items(state, update, scope, targets)
    _project_identity(data, state)
    if data != before_projection:
        from app.services.resume_versions import prepare_version
        from app.services.resume_capacity import measure_rendered_pages
        from app.agents.tailor_pipeline import constraints_for_turn
        update["page_check"] = await asyncio.to_thread(measure_rendered_pages, data, constraints_for_turn(state, instruction))
        update.update(prepare_version(state.get("resume_data") or {}, state.get("resume_meta") or {},
            state.get("resume_versions") or [], data, update.get("resume_meta") or {}))
        update["resume_meta"]["page_check"] = update["page_check"]
    return _document_outcome(update)


def _restore_unwritten_items(state, update, scope, targets):
    """Last loop-only delivery fallback: active own facts, never rejected prose."""
    from app.agents.resume_writer import _source_evidence, _body_fact
    from app.agents.career_prompt import writing_structure
    from app.services.labeled_writer import fallback_row, rule_slot, SLOTS
    from app.services.resume_versions import text_hash
    from app.services.fact_coverage import ensure_fact_coverage
    if scope == "bullet":
        return
    _, items, facts = _source_evidence(state.get("collected_info") or {})
    data, meta = update["resume_data"], update.setdefault("resume_meta", {})
    plan = update.get("match_plan") or state.get("confirmed_plan") or {}
    treatments = {row["item_id"]: row for row in plan.get("experience_plan") or []}
    family = ((state.get("jd_info") or {}).get("role_profile") or {}).get("role_family", "other")
    restored = []
    for iid, (section, source) in items.items():
        if scope == "item" and iid not in targets:
            continue
        selection = treatments.get(iid, {})
        if selection.get("treatment") == "backup" or selection.get("target_bullets") == 0:
            continue
        item = next((row for row in data.get(section) or [] if row.get("item_id") == iid), None)
        prior = next((row for row in (state.get("resume_data") or {}).get(section) or [] if row.get("item_id") == iid), {})
        field = "polished_bullets" if section == "projects" else "bullets"
        if item is None or item.get(field) or prior.get("hidden") or source.get("hidden"):
            continue
        own = [f["id"] for f in source["facts"] if _body_fact(f)]
        labeled = (section == "projects" and plan.get("bullet_style") == "labeled"
                   and writing_structure(family)["bullet_style"] == "labeled")
        groups = ({slot: [fid for fid in own if rule_slot(facts[fid]) == slot] for slot in SLOTS}
                  if labeled else {"plain": own})
        rows = [fallback_row(slot, ids, iid, facts, source.get("name", "")) for slot, ids in groups.items() if ids]
        rows = [row for row in rows if row["text"] and row["fact_ids"]][:selection.get("target_bullets", 4)]
        if not rows:
            continue
        for row in rows:
            if labeled:
                row["text"] = row["slot"] + "：" + row["text"]
        item[field], item["hidden"] = [row["text"] for row in rows], False
        meta.setdefault("bullets", {})[iid] = [{"fact_ids": row["fact_ids"], "coverage_fact_ids": row["fact_ids"],
                                                "text_hash": text_hash(row["text"])} for row in rows]
        name = item.get("name") or item.get("company") or iid
        notice = f"方案中保留的「{name}」未能形成通过事实校验的正文，请在核对页检查这段经历。"
        data["verification_notes"] = [n for n in data.get("verification_notes") or [] if n != notice]
        update["change_summary"] = [n for n in update.get("change_summary") or [] if n != notice]
        restored.append(iid)
    if restored:
        from app.services.resume_limits import preserve_item_limits
        preserved, metadata, fallbacks = preserve_item_limits(data, meta, state.get("collected_info") or {},
            item_ids=restored, constraints=update.get("session_constraints") or state.get("session_constraints"))
        data.clear()
        data.update(preserved)
        meta.clear()
        meta.update(metadata)
        update.setdefault("guard_fallbacks", []).extend(fallbacks)
        diagnostic = update.setdefault("writer_diagnostic", meta.get("writer_diagnostic") or {})
        diagnostic["deterministic_body_fallbacks"] = restored
        diagnostic["undelivered_items"] = [iid for iid in diagnostic.get("undelivered_items") or [] if iid not in restored]
        meta["writer_diagnostic"] = diagnostic
        meta["change_summary"] = update.get("change_summary", [])
        for holder in (update, meta):
            holder["omitted"] = [row for row in holder.get("omitted") or [] if row.get("item_id") not in restored]
        ensure_fact_coverage(data, meta, state.get("collected_info") or {})


def _document_outcome(update):
    from app.services.resume_review import resume_to_text
    data = update["resume_data"]
    update.update(stage="EVALUATING", resume_draft=resume_to_text(data))
    diagnostic = update.get("writer_diagnostic") or {}
    status = "partial" if diagnostic.get("status") == "model_fallback" else "ok" if update.get("changed") else "unchanged"
    return ToolOutcome({"status": status, "changed": bool(update.get("changed")),
        "version_id": update.get("version_id"), "resume_data": data, "page_check": update.get("page_check"),
        "change_summary": update.get("change_summary", []), "writer_diagnostic": diagnostic,
        "edit_contract": update.get("edit_contract", {}), "guard_fallbacks": update.get("guard_fallbacks", [])},
        # 写稿链路还返回 changed / writer_diagnostic 等诊断键；原图会忽略它们，这里只把状态字段交给编排合并。
        {key: value for key, value in update.items() if key in _state_fields()})


def _state_fields():
    from app.agents.resume_graph import ResumeState
    return ResumeState.__annotations__.keys()


@_register("write_draft", WriteArgs, "用已记录事实写第一稿；缺经历返回 insufficient；缺姓名或联系方式仍出稿，并在结果中给出 contacts_missing。", "正在写第一稿…")
async def write_draft(state, args, ctx):
    collected = state.get("collected_info") or {}
    if not _has_experience(collected):
        return ToolOutcome({"status": "insufficient", "missing": ["至少一段经历的具体做法"]})
    # 先写后问：缺联系方式不阻塞出稿，头部留空，由编排在出稿后一次问齐。
    missing = _missing_contacts(state)
    direction_update = {}
    current_direction = (state.get("jd_info") or {}).get("role_direction") or (state.get("jd_info") or {}).get("job_title")
    if args.direction and args.direction != current_direction:
        from app.services.role_profile import role_profile_from_direction
        from app.services.resume_strategy import build_resume_strategy
        from app.agents.resume_graph import _clear_structure_plan
        info = {"role_direction": args.direction, "role_profile": role_profile_from_direction(args.direction)}
        direction_update = {**_clear_structure_plan(state), "jd_info": info, "jd_text": "", "jd_skipped": True,
                            "jd_keywords": [args.direction],
                            "resume_strategy": build_resume_strategy(jd_info=info, jd_keywords=[args.direction], has_jd=False)}
    outcome = await _write({**state, **direction_update}, ctx, args.emphasis or "", plan_draft=True)
    if outcome.update:
        outcome.update = {**direction_update, **outcome.update, "pending_plan": {}, "plan_required": False}
        outcome.stop = True
        working = {**state, **outcome.update}
        if followup := _draft_followup(working, ctx):
            outcome.result["followup"] = followup
            outcome.stop = False
            if not ctx.followup_available:
                attached = await attach_draft_followup(working, followup, ctx)
                outcome.update.update(attached.update)
                outcome.events.extend(attached.events)
                outcome.result["followup_attached"] = attached.result.get("status") == "ok"
                outcome.stop = True
    if missing and outcome.update and (not (state.get("session_constraints") or {}).get("contacts_requested")
                                       or _export_contacts_requested(state)):
        outcome.result["contacts_missing"] = missing
        outcome.update["session_constraints"] = {**(outcome.update.get("session_constraints") or state.get("session_constraints") or {}),
                                                  "contacts_requested": True}
    return outcome


def _export_contacts_requested(state):
    from app.agents.resume_graph import _latest_human_text, _user_wants_export
    text = _latest_human_text(state)
    return bool(re.search(r"导出|下载", text) and _user_wants_export(text))


def _missing_contacts(state):
    basic = {**((state.get("resume_data") or {}).get("basic_info") or {}),
             **((state.get("collected_info") or {}).get("basic_info") or {})}
    return [key for key in ("name", "phone", "email") if not str(basic.get(key) or "").strip()]


@_register("edit_resume", EditArgs, "按编辑契约修改已有稿并保留可撤销版本；新事实须先 record_facts。", "正在修改简历…")
async def edit_resume(state, args, ctx):
    from app.agents.tailor_pipeline import infer_edit_scope
    from app.services.resume_versions import restore_payload
    from app.services.resume_review import resume_to_text
    data = state.get("resume_data")
    if not data:
        return ToolOutcome({"status": "insufficient", "missing": ["已有简历"]})
    source = _source(state, "current")
    if source and (source.id or "current") in ctx.corrected_sources:
        return ToolOutcome({"status": "unchanged", "correction_applied": True})
    from app.services.fact_corrections import correction_pairs
    if source and isinstance(source.content, str) and correction_pairs(source.content, state.get("collected_info")):
        return await record_facts(state, {"source_id": "current"}, ctx)
    if re.fullmatch(r"\s*(?:撤销|撤回|回到上一版|恢复上一版)(?:刚才的修改|这次修改|上次修改|上一版|一下)?[。！!\s]*", args.instruction):
        if not state.get("resume_versions"):
            return ToolOutcome({"status": "unavailable", "code": "no_previous_version"})
        update = restore_payload(state)
        _project_contacts(update["resume_data"], state.get("collected_info") or {})
        update.update(stage="EVALUATING", resume_draft=resume_to_text(update["resume_data"]))
        return ToolOutcome({"status": "ok", "restored": True, "version_id": update["version_id"]}, update)
    scope, targets = infer_edit_scope(data, args.instruction, state.get("collected_info"))
    if scope == "item" and not targets:
        return ToolOutcome({"status": "insufficient", "missing": ["能唯一定位的经历名称或序号"]})
    from app.agents.turn_actions import choose_edit_plan, render_operation_report
    from app.agents.resume_graph import _latest_human_text
    from app.services.edit_plan import execute_edit_plan
    facts = state.get("collected_info") or {}
    plan = choose_edit_plan(args.instruction, data, [], facts, router_failed=True)
    if plan:
        # Literal field/delete authorization comes from the user, never from
        # an orchestration model's rewritten instruction.
        executed = execute_edit_plan(data, state.get("session_constraints"), plan,
                                     collected_info=facts, instruction=_latest_human_text(state))
        if executed["collected_info"] != facts:
            return ToolOutcome({"status": "insufficient", "code": "record_facts_first",
                                "missing": ["先从用户原始消息记录或更正事实"]})
        if not executed["writer_requests"]:
            from app.agents.tailor_pipeline import apply_deterministic_update
            update = await apply_deterministic_update({**state, "resume_data": executed["data"],
                "previous_resume_data": data, "session_constraints": executed["constraints"]},
                executed["data"], _latest_human_text(state), dedupe=True)
            update["change_summary"] = render_operation_report(executed["operation_results"], data, update["resume_data"])
            update["resume_meta"]["operation_results"] = executed["operation_results"]
            outcome = _document_outcome(update)
            if any(row["status"] in {"cannot", "needs_confirmation"} for row in executed["operation_results"]):
                outcome.result["status"] = "partial" if outcome.result["changed"] else "insufficient"
            return outcome
        if executed["data"] != data or executed["constraints"] != state.get("session_constraints"):
            # Keep the original document as the version/scope baseline.
            state = {**state, "session_constraints": executed["constraints"]}
            data = executed["data"]
    return await _write(state, ctx, args.instruction, scope=scope, targets=targets, base=data)


@_register("check_layout", NoArgs, "只测量已有简历页数，不写 PDF、不改正文。", "正在检查排版…")
async def check_layout(state, args, ctx):
    from app.services.resume_capacity import resume_data_hash
    from app.services.resume_pdf import measure_resume_pdf_layout
    from app.agents.tailor_pipeline import constraints_for_turn
    if not state.get("resume_data"):
        return ToolOutcome({"status": "insufficient", "missing": ["已有简历"]})
    constraints = constraints_for_turn(state, "")
    # Measure the current density, without the automatic density selection used by writing.
    layout = await asyncio.to_thread(measure_resume_pdf_layout, constraints["template_id"],
                                     state["resume_data"], constraints["page_limit"])
    result = {**layout, "status": "rendered", "page_limit": constraints["page_limit"],
              "within_page_limit": layout["pages"] <= constraints["page_limit"],
              "template_id": constraints["template_id"], "data_hash": resume_data_hash(state["resume_data"]),
              "source": "production_render_resume_pdf"}
    return ToolOutcome({"status": "ok", "page_check": result},
                       {"page_check": result, "resume_meta": {**(state.get("resume_meta") or {}), "page_check": result}})
