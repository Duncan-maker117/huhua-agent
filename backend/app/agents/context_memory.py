"""Lossless candidate-evidence projection; only conversation scaffolding is lossy.

This is a per-call view, not a new fact store or an LLM-written summary. All
candidate statements remain either active evidence or explicitly pending source
material. A statement's kind never controls whether it survives compression.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.schemas.facts import FACT_LABELS, FACT_SECTIONS
from app.services.error_codes import ChatTurnError
from app.services.model_privacy import ContactRedactor


class ContextSettings(BaseSettings):
    # This is the INPUT allowance. Deployments must reserve output tokens too.
    model_config = SettingsConfigDict(extra="ignore", env_file=str(Path(__file__).resolve().parents[2] / ".env"),
                                      env_file_encoding="utf-8")
    CONTEXT_MAX_INPUT_TOKENS: int = Field(default=64000, ge=1024)


class ContextBudgetExceeded(ChatTurnError):
    def __init__(self):
        super().__init__("E-CONTEXT-LIMIT", "本次资料超过安全上下文容量，已停止后续模型处理；不会通过删减经历或限制来继续。请减少本轮参考材料，或联系管理员提高上下文输入预算后重试。")


def _json_default(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Unsupported model input type: {type(value).__name__}")


def estimate_input_tokens(messages, schemas=None) -> int:
    """Conservative UTF-8 byte bound, including tools and message framing.

Byte-level tokenizers cannot create more text tokens than UTF-8 input bytes;
extra framing is deliberately generous. This is not a provider token count.
    """
    payload = {"messages": messages, "tools": schemas or []}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                         default=_json_default).encode("utf-8")
    return len(encoded) + 64 * len(messages) + 128 * len(schemas or []) + 256


def ensure_context_budget(messages, schemas=None, max_input_tokens=None) -> int:
    limit = ContextSettings().CONTEXT_MAX_INPUT_TOKENS if max_input_tokens is None else max_input_tokens
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1024:
        raise ValueError("Context input budget must be an integer of at least 1024")
    estimate = estimate_input_tokens(messages, schemas)
    if estimate > limit:
        raise ContextBudgetExceeded()
    return estimate


def _candidate_sources(state: dict) -> list[dict]:
    # Lazy imports: resume_graph and the tools depend on this projection.
    from app.agents.fact_extractor import _candidate_evidence
    from app.agents.orchestrator_tools import _source_parts
    from app.agents.resume_graph import _candidate_source_allowed
    excluded = set(state.get("non_candidate_message_ids") or [])
    result = []
    for index, message in enumerate(state.get("messages") or []):
        if not isinstance(message, HumanMessage) or not isinstance(message.content, str):
            continue
        source_id = message.id or f"user-{index}"
        text, jd = _source_parts(message.content)
        candidate = message
        if jd and message.additional_kwargs.get("career_material_type") not in {"review", "reference"}:
            candidate = message.model_copy(update={"content": text, "additional_kwargs": {
                **message.additional_kwargs, "career_material_type": "candidate"}})
        if source_id in excluded or not _candidate_source_allowed(candidate):
            continue
        text = _candidate_evidence(text)
        if text.strip() or message.additional_kwargs.get("answers") or message.additional_kwargs.get("intake"):
            result.append({"source_id": source_id, "index": index, "text": text})
    return result


def _provenance(fact: dict) -> list[tuple[str, str]]:
    rows = [fact, *(fact.get("sources") or [])]
    return list(dict.fromkeys((str(row.get("turn_id") or ""), row["source_quote"])
                             for row in rows if isinstance(row, dict)
                             and isinstance(row.get("source_quote"), str) and row["source_quote"].strip()))


_CLAUSE_PUNCT = " \t\r\n，,。；;！？!?"


def _revocation_sources(fact: dict) -> list[tuple[str, str]]:
    # A source quote may encompass several facts, including an unextracted
    # limitation. An invalidated extraction does NOT invalidate its whole quote.
    # Only literal complete fact clauses can be safely removed without a second
    # semantic judgment. Ambiguous originals stay pending with a conflict flag.
    text = str(fact.get("text") or fact.get("name") or "").strip(_CLAUSE_PUNCT)
    result = []
    for source_id, quote in _provenance(fact):
        if not text:
            continue
        if text == quote.strip(_CLAUSE_PUNCT):
            result.append((source_id, text))
        elif text in [part.strip() for part in re.split(r"[，,。；;！？!?\n]", quote)]:
            result.append((source_id, text))
    return result


def _revoke(text: str, quotes: list[str]) -> str:
    """Literal removal, retaining adjacent qualifiers and a visible gap marker."""
    spans = []
    for quote in quotes:
        if not quote:
            continue
        start = 0
        while (start := text.find(quote, start)) >= 0:
            spans.append((start, start + len(quote)))
            start += len(quote)
    if not spans:
        return text
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    pieces, cursor = [], 0
    for start, end in merged:
        pieces.extend((text[cursor:start], "[已撤回片段]"))
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _residual(text: str, active_quotes: list[str], revoked_quotes: list[str]) -> str:
    # Restrict removal to complete source clauses, so a faulty extracted word
    # '上线' never destroys the original '我没有上线'.
    safe_revocations = [quote for quote in revoked_quotes if any(
        match.group().strip(_CLAUSE_PUNCT) == quote.strip(_CLAUSE_PUNCT)
        for match in re.finditer(r"[^，,。；;！？!?\n]+", text))]
    # Replace bounded occurrences only, not another identical substring embedded
    # in a neighbouring negative clause.
    text = re.sub(r"[^，,。；;！？!?\n]+", lambda match: "[已撤回片段]"
                  if match.group().strip(_CLAUSE_PUNCT) in safe_revocations else match.group(), text)
    # Never remove just a matching substring: e.g. '上线' in '从未上线'.
    # Preserve punctuation and unextracted clauses exactly as the user wrote them.
    parts = re.findall(r"[^，,。；;！？!?\n]+[，,。；;！？!?\n]*|[，,。；;！？!?\n]+", text)
    kept = []
    for part in parts:
        clause = part.strip(" \t\r\n，,。；;！？!?")
        if not clause or clause == "[已撤回片段]":
            continue
        if "[已撤回片段]" not in clause and any(clause in quote for quote in active_quotes):
            continue
        kept.append(part)
    # Keep the entire surviving source when ANY clause remains uncovered. This
    # retains the subject/antecedent and ordering of qualifiers in multi-project
    # messages; isolated 'only a prototype' fragments can otherwise attach to
    # the wrong project. Duplication is preferable to a changed meaning.
    return text if kept else ""


def _versioned_facts(state: dict) -> list[dict]:
    collected = state.get("collected_info") or {}
    facts = [fact for section in FACT_SECTIONS for item in collected.get(section) or []
             if isinstance(item, dict) for fact in item.get("facts") or [] if isinstance(fact, dict)]
    facts.extend(fact for field in ("skills", "basic_info_facts") for fact in collected.get(field) or []
                 if isinstance(fact, dict))
    return facts


def _submitted_source_values(message: HumanMessage) -> list[str]:
    """Only submitted answer values/known intake fields, never question options."""
    metadata = message.additional_kwargs
    values = []
    answers, card = metadata.get("answers"), metadata.get("answer_card")
    if (isinstance(answers, dict) and isinstance(card, dict) and answers.get("turn_id")
            and answers.get("turn_id") == card.get("turn_id")):
        question_ids = {q["id"] for q in card.get("questions") or [] if isinstance(q, dict) and q.get("id")}
        for answer in answers.get("items") or []:
            if not isinstance(answer, dict) or answer.get("id") not in question_ids:
                continue
            value = answer.get("value")
            values.extend([value] if isinstance(value, str) else
                          [part for part in value if isinstance(part, str)] if isinstance(value, list) else [])
    intake = metadata.get("intake")
    if isinstance(intake, dict):
        if intake.get("kind") == "basics" and isinstance(intake.get("values"), dict):
            values.extend(intake["values"][key] for key in
                          ("name", "school", "major", "degree", "graduation", "location", "availability", "phone", "email")
                          if isinstance(intake["values"].get(key), str))
        elif intake.get("kind") == "experiences":
            for item in intake.get("items") or []:
                if isinstance(item, dict):
                    values.extend(item[key] for key in ("item_id", "name", "type", "start", "end", "role", "summary")
                                  if isinstance(item.get(key), str))
    return values


def invalidated_source_ids(state: dict) -> set[str]:
    """Sources that must not be replayed into record_facts without fresh input.

    Provenance survives even when all pending text was safely removed. For old
    unbound facts, complete literal quotes also quarantine matching historical
    messages; the latest new message is not quarantined by this heuristic.
    """
    revoked = [fact for fact in _versioned_facts(state) if fact.get("status", "active") != "active"]
    result = {source_id for fact in revoked for source_id, _ in _provenance(fact) if source_id}
    unbound = [quote for fact in revoked if not any(source_id for source_id, _ in _provenance(fact))
               for _, quote in _provenance(fact)]
    messages = state.get("messages") or []
    latest = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), None)
    for index, message in enumerate(messages):
        if index == latest or not isinstance(message, HumanMessage):
            continue
        originals = ([message.content] if isinstance(message.content, str) else []) + _submitted_source_values(message)
        if any(quote in original for quote in unbound for original in originals):
            result.add(message.id or f"user-{index}")
    return result


def _revoked_texts(state: dict) -> list[str]:
    facts = _versioned_facts(state)
    return list(dict.fromkeys(text for fact in facts if fact.get("status", "active") != "active"
                             for text in [fact.get("text") or fact.get("name"), *[quote for _, quote in _provenance(fact)]]
                             if isinstance(text, str) and text))


def _scrub_scaffolding(value, revoked: list[str]):
    # Assistant paraphrases/derived metadata are not original candidate sources:
    # removing obsolete literal claims here cannot remove user evidence.
    if isinstance(value, str):
        return _revoke(value, revoked)
    if isinstance(value, list):
        return [_scrub_scaffolding(v, revoked) for v in value]
    if isinstance(value, dict):
        return {key: _scrub_scaffolding(v, revoked) for key, v in value.items()}
    return deepcopy(value)


def _assistant_context(message, revoked=()) -> dict:
    # Structured question cards carry the subject/wording of short answers.
    result = {"role": "assistant", "content": deepcopy(message.content),
              "interpretation_only": True}
    metadata = {key: deepcopy(message.additional_kwargs[key]) for key in ("ask_user", "answer_card")
                if key in message.additional_kwargs}
    if metadata:
        result["question_metadata"] = metadata
    return _scrub_scaffolding(result, list(revoked))


def _needs_antecedent(text: str, previous) -> bool:
    if len(text) > 240:
        return False
    if previous.additional_kwargs.get("ask_user") or previous.additional_kwargs.get("answer_card"):
        return True
    if isinstance(previous.content, str) and ("？" in previous.content or "?" in previous.content):
        return True
    # This only selects interpretation scaffolding; it NEVER filters evidence.
    return bool(re.search(r"(?:第[一二三四五六七八九十\d]+个|前者|后者|这个|那个|上面|上一|刚才|就用|就选|不是那个)|^(?:对|是的|不是|没有|没做过|不知道|不清楚|都可以|都不)[。！!，,\s]*$", text))


def _legacy_source_text(text: str, state: dict, sources: list[dict]) -> str:
    """Reject legacy fragments demonstrably sourced only from external text."""
    originals = [message.content for message in state.get("messages") or []
                 if isinstance(message, HumanMessage) and isinstance(message.content, str)]
    def external_only(value):
        value = value.strip(_CLAUSE_PUNCT)
        return (value and any(value in original for original in originals)
                and not any(value in source["text"] for source in sources))
    if external_only(text):
        return ""
    return "".join(part for part in re.findall(r"[^，,。；;！？!?\n]+[，,。；;！？!?\n]*|[，,。；;！？!?\n]+", text)
                   if not external_only(part))


def _structured_pending(state, sources, active_by_source, revoked_by_source, conflicts_by_source):
    """Original submitted values, never unselected options or inferred facts.

    record_facts must inspect the canonical structured payload at source_id; its
    placeholder message content cannot reconstruct these values. Unprocessed
    payloads require review, even when they look like ordinary resume facts.
    """
    result = []
    quarantined = invalidated_source_ids(state)
    for source in sources:
        source_id = source["source_id"]
        metadata = state["messages"][source["index"]].additional_kwargs
        revoked = revoked_by_source.get(source_id, [])
        def remaining(value):
            if isinstance(value, str):
                return _residual(value, [], revoked)
            if isinstance(value, list):
                return [part for value in value if isinstance(value, str) and (part := _residual(value, [], revoked))]
            return None
        base = {"source_id": source_id, "requires_review": True,
                "read_original_structured_payload": True}
        if source_id in quarantined:
            base.update(requires_review_after_invalidation=True, invalidated_fact_ids=conflicts_by_source.get(source_id, []))
        answers, card = metadata.get("answers"), metadata.get("answer_card")
        if (isinstance(answers, dict) and isinstance(card, dict) and answers.get("turn_id")
                and answers.get("turn_id") == card.get("turn_id")):
            questions = {q["id"]: q for q in card.get("questions") or [] if isinstance(q, dict) and q.get("id")}
            for index, answer in enumerate(answers.get("items") or []):
                if not isinstance(answer, dict) or answer.get("id") not in questions:
                    continue
                question = questions[answer["id"]]
                submitted = {key: deepcopy(answer[key]) for key in ("id", "skipped", "unknown") if key in answer}
                if "value" in answer:
                    value = remaining(answer["value"])
                    if value:
                        submitted["value"] = value
                non_fact = bool(answer.get("skipped") or answer.get("unknown"))
                if "value" not in submitted and not non_fact:
                    continue
                result.append({**base, "source_kind": "structured_answer", "card_turn_id": answers["turn_id"],
                               "payload_path": f"additional_kwargs.answers.items[{index}]",
                               "subject": deepcopy(card.get("subject") or ""),
                               "question_id": answer["id"], "question_prompt": deepcopy(question.get("prompt") or ""),
                               "submitted": submitted, "non_fact_response": non_fact})
        intake = metadata.get("intake")
        if not isinstance(intake, dict) or intake.get("kind") not in {"basics", "experiences"}:
            continue
        submitted = {key: deepcopy(intake[key]) for key in ("kind", "skipped") if key in intake}
        if intake["kind"] == "basics" and isinstance(intake.get("values"), dict):
            values = {}
            for key in ("name", "school", "major", "degree", "graduation", "location", "availability", "phone", "email"):
                if key in intake["values"] and (value := remaining(intake["values"][key])):
                    values[key] = value
            if values:
                submitted["values"] = values
        elif intake["kind"] == "experiences":
            items = []
            for original in intake.get("items") or []:
                if not isinstance(original, dict):
                    continue
                values = {}
                for key in ("item_id", "name", "type", "start", "end", "role", "summary"):
                    if key in original and (value := remaining(original[key])):
                        values[key] = value
                if values:
                    items.append(values)
            if items:
                submitted["items"] = items
            if isinstance(intake.get("profile_item_ids"), list) and intake["profile_item_ids"]:
                submitted["profile_item_ids"] = deepcopy(intake["profile_item_ids"])
        if set(submitted) <= {"kind", "skipped"} and not intake.get("skipped"):
            continue
        result.append({**base, "source_kind": "intake", "payload_path": "additional_kwargs.intake",
                       "submitted": submitted, "non_fact_response": bool(intake.get("skipped"))})
    return result


def candidate_memory(state: dict, privacy: ContactRedactor) -> dict:
    """Return complete active evidence and uncovered original candidate sources.

    Pending evidence is not an assertion of truth or completion. Deleted and
    superseded facts appear only as ID/status tombstones. Canonical state is
    never normalized or changed (normalization can create random new fact IDs).
    """
    collected = state.get("collected_info") or {}
    messages = state.get("messages") or []
    sources = _candidate_sources(state)
    quarantined = invalidated_source_ids(state)
    revoked_texts = _revoked_texts(state)
    active_by_source: dict[str, list[str]] = {}
    revoked_by_source: dict[str, list[str]] = {}
    conflicts_by_source: dict[str, list[str]] = {}
    active, pending, invalidations = [], [], []
    for section in FACT_SECTIONS:
        for index, item in enumerate(collected.get(section) or []):
            if not isinstance(item, dict):
                continue
            item_id = item.get("item_id") or f"legacy:{section}:{index}"
            facts = [fact for fact in item.get("facts") or [] if isinstance(fact, dict)]
            current, revoked = [], []
            for fact_index, fact in enumerate(facts):
                status = fact.get("status", "active")
                if status == "active":
                    current.append(deepcopy(fact))
                    target = active_by_source
                else:
                    revoked.append(fact)
                    invalidations.append({"section": section, "item_id": item_id,
                                          "fact_id": fact.get("id") or f"legacy:{fact_index}", "status": status})
                    target = revoked_by_source
                provenance = _provenance(fact) if status == "active" else _revocation_sources(fact)
                for source_id, quote in provenance:
                    if source_id:
                        target.setdefault(source_id, []).append(quote)
                if status != "active":
                    for source_id, _ in _provenance(fact):
                        conflicts_by_source.setdefault(source_id, []).append(fact.get("id") or f"legacy:{fact_index}")
            # Scalars in the master are useful identity, not draft bullets.
            identity = {key: deepcopy(value) for key, value in item.items()
                        if key not in {"facts", "raw_notes", "description", "raw_description",
                                       "polished_bullets", "bullets", "highlights"}}
            for fact in revoked:
                field = fact.get("field")
                if field in identity and identity[field] in (fact.get("text"), fact.get("source_quote")):
                    identity.pop(field)
            active.append({"section": section, "item_id": item_id,
                           "subject": identity.get(FACT_LABELS[section], ""),
                           "identity": identity, "facts": current})
            # Old source-only stores have no facts. Keep their content as pending
            # evidence, never turn rendered bullets back into candidate facts.
            raw_fields = [("raw_notes", value) for value in item.get("raw_notes") or [] if isinstance(value, str)]
            for field in ("raw_description", "description"):
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    rendered = "\n".join(str(v) for v in item.get("polished_bullets") or [])
                    if value.strip() != rendered.strip():
                        raw_fields.append((field, value))
            # Legacy highlights may themselves be original education evidence.
            if not facts and item.get("highlights"):
                value = item["highlights"]
                raw_fields.extend(("highlights", v) for v in (value if isinstance(value, list) else [value]) if isinstance(v, str))
            local_active = [quote for fact in current for _, quote in _provenance(fact)]
            local_revoked = [quote for fact in revoked for _, quote in _revocation_sources(fact)]
            for field, text in raw_fields:
                # If raw note exists in a known original turn, that original is
                # projected below with exact turn-scoped coverage/invalidation.
                if any(text in source["text"] for source in sources):
                    continue
                text = _legacy_source_text(text, state, sources)
                if not text.strip():
                    continue
                remainder = _residual(text, local_active, local_revoked)
                if remainder.strip():
                    row = {"legacy_ref": f"legacy:{item_id}:{field}", "source_kind": "unverified_legacy",
                           "requires_review": True, "item_id": item_id, "field": field, "text": remainder}
                    if revoked:
                        row["requires_review_after_invalidation"] = True
                    if row not in pending:
                        pending.append(row)
    skills, basic_facts = [], []
    basic_info = deepcopy(collected.get("basic_info") or {})
    for field, section, destination in (("skills", "skills", skills), ("basic_info_facts", "basic_info", basic_facts)):
        for index, fact in enumerate(collected.get(field) or []):
            if not isinstance(fact, dict):
                destination.append(deepcopy(fact))
                continue
            status = fact.get("status", "active")
            fact_id = fact.get("id") or f"{section}:{index}"
            if status == "active":
                destination.append(deepcopy(fact))
                target, provenance = active_by_source, _provenance(fact)
            else:
                invalidations.append({"section": section, "fact_id": fact_id, "status": status})
                target, provenance = revoked_by_source, _revocation_sources(fact)
                for source_id, _ in _provenance(fact):
                    if source_id:
                        conflicts_by_source.setdefault(source_id, []).append(fact_id)
                if section == "basic_info":
                    key = fact.get("field")
                    if key in basic_info and basic_info[key] in (fact.get("text"), fact.get("source_quote")) and not any(
                            current.get("status", "active") == "active" and current.get("field") == key
                            and current.get("text") == basic_info[key]
                            for current in collected.get(field) or [] if isinstance(current, dict)):
                        basic_info.pop(key)
            for source_id, quote in provenance:
                if source_id:
                    target.setdefault(source_id, []).append(quote)
    for source in sources:
        source_id = source["source_id"]
        remainder = _residual(source["text"], active_by_source.get(source_id, []),
                              revoked_by_source.get(source_id, []))
        if not remainder.strip():
            continue
        row = {"source_id": source_id, "source_kind": "candidate_original", "text": remainder}
        if source_id in quarantined:
            row["invalidated_fact_ids"] = conflicts_by_source.get(source_id, [])
            row["requires_review_after_invalidation"] = True
        # Preserve the antecedent for every short answer, independent of whether
        # it happens to contain a recognizable negation word.
        source_metadata = messages[source["index"]].additional_kwargs
        if len(source["text"]) <= 240 and not (source_metadata.get("answers") or source_metadata.get("intake")):
            previous = next((m for m in reversed(messages[:source["index"]]) if isinstance(m, AIMessage)), None)
            if previous is not None and _needs_antecedent(source["text"], previous):
                row["antecedent"] = _assistant_context(previous, revoked_texts)
        pending.append(row)
    pending.extend(_structured_pending(state, sources, active_by_source, revoked_by_source, conflicts_by_source))
    excluded_fields = {*FACT_SECTIONS, "basic_info", "basic_info_facts", "skills", "imported_documents", "raw_notes", "metadata_context"}
    constraints = {key: deepcopy(value) for key, value in collected.items() if key not in excluded_fields}
    for key in ("verification_notes",):
        if key in constraints:
            constraints[key] = _scrub_scaffolding(constraints[key], revoked_texts)
    constraints["session_constraints"] = deepcopy(state.get("session_constraints") or {})
    constraints["closed_questions"] = deepcopy(state.get("closed_questions") or [])
    # Store-level unassigned notes and metadata can be original plans/limits.
    # They have no dependable source identity: never apply global text deletion
    # across experiences. Conflicting legacy originals require explicit review.
    for field in ("raw_notes", "metadata_context"):
        for index, value in enumerate(collected.get(field) or []):
            text = value.get("text", "") if isinstance(value, dict) else value
            if isinstance(text, str) and text.strip() and not any(text in source["text"] for source in sources):
                text = _legacy_source_text(text, state, sources)
                if not text.strip():
                    continue
                row = {"legacy_ref": f"legacy:unassigned:{field}:{index}", "source_kind": "unverified_legacy",
                       "requires_review": True, "field": field, "text": text}
                if isinstance(value, dict):
                    row["source_metadata"] = deepcopy({key: v for key, v in value.items() if key != "text"})
                if invalidations:
                    row["requires_review_after_invalidation"] = True
                pending.append(row)
    return privacy.redact({"version": 1, "active_evidence": active, "pending_evidence": pending,
                           "invalidations": invalidations, "basic_info": basic_info, "basic_info_facts": basic_facts,
                           "skills": skills, "session_constraints": constraints})


def compact_history(state: dict, privacy: ContactRedactor, recent_user_turns=3, assistant_chars=1200) -> list[dict]:
    """Recent discourse only; candidate originals live in candidate_memory.

    Latest user input is always complete, including references. Earlier user
    turns become source pointers. Old assistant prose/reference text cannot
    silently become candidate evidence or resurrect a removed fact.
    """
    messages = state.get("messages") or []
    human_indices = [i for i, message in enumerate(messages) if isinstance(message, HumanMessage)]
    if not human_indices:
        return []
    start = human_indices[-max(1, recent_user_turns)] if len(human_indices) >= max(1, recent_user_turns) else human_indices[0]
    latest = human_indices[-1]
    candidate_ids = {row["source_id"] for row in _candidate_sources(state)}
    revoked = _revoked_texts(state)
    last_assistant = next((i for i in range(latest - 1, -1, -1) if isinstance(messages[i], AIMessage)), None)
    if last_assistant is not None:
        start = min(start, last_assistant)
    result = []
    for index, message in enumerate(messages[start:], start):
        if isinstance(message, HumanMessage):
            source_id = message.id or f"user-{index}"
            if index == latest:
                content = deepcopy(message.content)
            elif source_id in candidate_ids:
                content = f"[历史候选人原话见 candidate_memory，source_id={source_id}]"
            else:
                # The actual latest reference is retained above; old external
                # prose is expendable and explicitly remains external material.
                text = message.content if isinstance(message.content, str) else "[非文本参考材料]"
                content = "[历史参考材料，不能作为候选人事实]\n" + text[:assistant_chars]
            result.append({"role": "user", "source_id": source_id, "content": content})
        elif isinstance(message, AIMessage):
            # Repeated assistant paraphrases are the highest-volume removable
            # component. Keep only questions, not potentially obsolete claims.
            content = message.content if isinstance(message.content, str) else ""
            if index == last_assistant or "?" in content or "？" in content or message.additional_kwargs:
                row = {"role": "assistant", "content": _revoke(content, revoked)[:assistant_chars], "interpretation_only": True}
                metadata = {key: deepcopy(message.additional_kwargs[key]) for key in ("ask_user", "answer_card")
                            if key in message.additional_kwargs}
                if metadata:
                    row["question_metadata"] = _scrub_scaffolding(metadata, revoked)
                result.append(row)
    return privacy.redact(result)
