"""Encrypted personal archive with a transactional outbox and deletion barriers.

All mutators accept a caller-owned SQLAlchemy Session and do NOT commit. The
caller can atomically save a conversation, its source and its archive event.
The worker leases events in short transactions, calls the extractor outside
the transaction and rechecks ownership/source/revisions before applying.
"""

import asyncio
import copy
import inspect
import json
import re
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import and_, exists, func, or_, select, update

from app.agents.profile_archivist import (
    ArchiveBatch, ArchiveProposal, deterministic_proposals, validate_grounding,
)
from app.models.profile import (
    PersonalProfile, ProfileArchiveEvent, ProfileConflict, ProfileFact,
    ProfileInvalidation, ProfileJobVersion, ProfileSource, new_id,
)
from app.services.account_service import blind_index
from app.services.data_crypto import CryptoConfigurationError, get_crypto


class ProfileNotFound(Exception):
    pass


class ProfileRevisionConflict(Exception):
    pass


class ProfileValidationError(ValueError):
    pass


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _dt(value):
    if not value:
        return None
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.astimezone(UTC).replace(tzinfo=None) if result.tzinfo else result


def _iso(value):
    value = _dt(value)
    return value.replace(tzinfo=UTC).isoformat() if value else None


def _seal(row, value):
    crypto = get_crypto()
    if not crypto.enabled:
        raise CryptoConfigurationError("Personal archives require encrypted storage")
    return crypto.encrypt_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_iso),
        owner=f"account:{row.account_id}", record=row.id, field="payload",
    )


def _open(row):
    return json.loads(get_crypto().decrypt_text(
        row.payload, owner=f"account:{row.account_id}", record=row.id, field="payload",
    ))


def _key(account_id, value, scope="slot"):
    return blind_index(json.dumps(value, ensure_ascii=False, separators=(",", ":")),
                       scope=f"profile:{account_id}:{scope}")


def ensure_profile(db, account_id):
    profile = db.scalar(select(PersonalProfile).where(PersonalProfile.account_id == account_id))
    if profile is None:
        profile = PersonalProfile(id=new_id(), account_id=account_id, revision=0)
        db.add(profile)
        db.flush()
    return profile


def _bump(db, profile):
    expected = profile.revision
    result = db.execute(update(PersonalProfile).where(
        PersonalProfile.id == profile.id, PersonalProfile.revision == expected,
    ).values(revision=expected + 1).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise ProfileRevisionConflict("profile_revision_conflict")
    db.expire(profile, ["revision"])


def _owned(db, model, account_id, item_id):
    row = db.scalar(select(model).where(model.id == item_id, model.account_id == account_id))
    if row is None:
        raise ProfileNotFound()
    return row


def _fact_view(db, row):
    data = _open(row)
    sources = []
    for source_id in data.get("source_ids", []):
        source = db.get(ProfileSource, source_id)
        if source and source.account_id == row.account_id and not source.disabled:
            source_data = _open(source)
            sources.append({"id": source.id, "kind": source.kind, "session_id": source.session_id,
                            "recorded_at": _iso(source.recorded_at),
                            "excerpt": source_data.get("human_text", "")[:400]})
    # Temporal history is viewable to the user, but never routine model context.
    return {**data, "id": row.id, "revision": row.revision, "category": row.category,
            "status": row.status, "source_type": "user_provided", "sources": sources}


def _archive_task_view(row):
    reason = row.error_code or ""
    messages = {
        "model_unavailable": "聊天已保存，模型服务配置完成后会继续整理经历，无需反复重试。",
        "budget_exhausted": "今天的生成与整理额度已用完，额度恢复后会继续处理。",
        "archive_timeout": "这次整理超时，已保存的聊天仍在，可以稍后重试。",
        "revision_conflict": "档案刚有更新，这次整理将依据最新资料重试。",
        "archive_unavailable": "暂时无法完成整理，已保存的聊天仍在，可以稍后重试。",
    }
    message = messages.get(reason, "等待整理" if row.status == "pending" else "正在整理" if row.status == "running" else "整理尚未完成，请稍后重试。")
    return {"id": row.id, "status": row.status, "attempts": row.attempts,
            "error_code": reason, "reason_type": reason, "message": message,
            "retryable": row.status == "failed" and reason not in {"model_unavailable", "budget_exhausted"}}


def get_profile(db, account_id):
    profile = ensure_profile(db, account_id)
    facts = [_fact_view(db, row) for row in db.scalars(select(ProfileFact).where(
        ProfileFact.account_id == account_id, ProfileFact.status == "active",
    )).all()]
    conflicts = []
    for row in db.scalars(select(ProfileConflict).where(
        ProfileConflict.account_id == account_id, ProfileConflict.status == "pending",
    )).all():
        fact = db.get(ProfileFact, row.fact_id)
        if not fact or fact.status != "active" or fact.revision != row.expected_revision:
            continue
        data = _open(row)
        if not _source_enabled(db, account_id, data.get("source_id")):
            continue
        conflicts.append({**data, "id": row.id, "fact_id": row.fact_id,
                          "expected_revision": row.expected_revision, "status": row.status})
    jobs = []
    for row in db.scalars(select(ProfileJobVersion).where(ProfileJobVersion.account_id == account_id)).all():
        jobs.append({**{key: value for key, value in _open(row).items() if key != "projection_v1"}, "id": row.id, "session_id": row.session_id,
                     "revision": row.revision, "stale": row.stale})
    tasks = [_archive_task_view(row)
             for row in db.scalars(select(ProfileArchiveEvent).where(
                 ProfileArchiveEvent.account_id == account_id,
                 ProfileArchiveEvent.status.in_(["pending", "running", "failed"]),
             ).order_by(ProfileArchiveEvent.created_at.desc()).limit(50)).all()]
    # Imported histories have their own queue and retry policy. Keep its IDs
    # separate from archive tasks so clients cannot retry the wrong resource.
    from app.services.profile_bridge import ClaimedHistoryImport
    imports = {status: count for status, count in db.execute(select(
        ClaimedHistoryImport.status, func.count(),
    ).where(ClaimedHistoryImport.owner == f"account:{account_id}")
       .group_by(ClaimedHistoryImport.status)).all()}
    import_tasks = []
    for row in db.scalars(select(ClaimedHistoryImport).where(
        ClaimedHistoryImport.owner == f"account:{account_id}",
        ClaimedHistoryImport.status.in_(["pending", "running", "failed"]),
    ).limit(50)).all():
        reason = getattr(row, "error_code", "") or ("import_unavailable" if row.status == "failed" else "")
        import_tasks.append({"session_id": row.session_id, "status": row.status,
                             "attempts": getattr(row, "attempts", 0), "error_code": reason, "reason_type": reason})
    return {"profile_id": profile.id, "revision": profile.revision,
            "facts": [f for f in facts if f["category"] != "preference"],
            "preferences": [f for f in facts if f["category"] == "preference"],
            "conflicts": conflicts, "jobs": jobs,
            "import_status": {**{status: imports.get(status, 0)
                                  for status in ("pending", "running", "failed", "completed")},
                              "tasks": import_tasks},
            "archive_status": {**{status: sum(t["status"] == status for t in tasks)
                                   for status in ("pending", "running", "failed")}, "tasks": tasks}}


def _source_enabled(db, account_id, source_id):
    if not source_id:
        return True
    row = db.get(ProfileSource, source_id)
    return bool(row and row.account_id == account_id and not row.disabled)


def enqueue_archive_event(db, account_id, source_id, session_id, payload,
                          event_type="human_message", recorded_at=None):
    """Register a saved human input, in the SAME transaction as the save.

    Payload protocol: human_text, source_kind=self|manual|jd|reference|ai|unknown,
    optional collected_info_delta, confirmed_facts (manual only), subject_ids.
    source_id must be the stable persisted human message/edit ID, not run ID.
    Calling this for a client-supplied source ID before saving is not safe.
    """
    if event_type not in {"human_message", "manual_fact", "claimed_history"}:
        raise ProfileValidationError("unsupported_event_type")
    if not isinstance(payload, dict) or not isinstance(payload.get("human_text", ""), str):
        raise ProfileValidationError("invalid_source")
    if len(payload.get("human_text", "")) > 100_000:
        raise ProfileValidationError("source_too_large")
    source_kind = payload.get("source_kind", "unknown")
    if source_kind not in {"self", "manual", "jd", "reference", "ai", "unknown"}:
        raise ProfileValidationError("invalid_source_kind")
    ensure_profile(db, account_id)
    source_key = _key(account_id, str(source_id), "source")
    source = db.scalar(select(ProfileSource).where(
        ProfileSource.account_id == account_id, ProfileSource.source_key == source_key,
    ))
    if source is None:
        source = ProfileSource(id=new_id(), account_id=account_id, source_key=source_key,
                               session_id=session_id, kind=source_kind, disabled=False,
                               recorded_at=_dt(recorded_at) or _now())
        source.payload = _seal(source, {**payload, "original_source_id": str(source_id), "event_type": event_type})
        db.add(source)
        db.flush()
    elif not source.disabled:
        existing = _open(source)
        # A message ID is immutable; replay cannot smuggle different content.
        if existing.get("human_text", "") != payload.get("human_text", "") or source.kind != source_kind:
            raise ProfileValidationError("source_id_reused")
    event = db.scalar(select(ProfileArchiveEvent).where(
        ProfileArchiveEvent.account_id == account_id, ProfileArchiveEvent.source_id == source.id,
        ProfileArchiveEvent.event_type == event_type,
    ))
    if event is None:
        event = ProfileArchiveEvent(id=new_id(), account_id=account_id, source_id=source.id,
                                    event_type=event_type, attempts=0,
                                    status="skipped" if source.disabled or source.kind not in {"self", "manual"} else "pending")
        # Source is authoritative; duplicating full text in each retry is avoided.
        event.payload = _seal(event, {"source_id": source.id})
        db.add(event)
        db.flush()
    return event


def compensate_archive_events(db, account_id=None):
    """Repair a source committed by a legacy adapter before outbox registration.

    Normal saves are atomic. This bounded scan is also useful after recovery;
    it cannot invent an event from unsaved checkpoint or memory-only input.
    """
    query = select(ProfileSource).where(
        ProfileSource.disabled.is_(False),
        ~exists().where(ProfileArchiveEvent.source_id == ProfileSource.id),
    )
    if account_id:
        query = query.where(ProfileSource.account_id == account_id)
    repaired = 0
    for source in db.scalars(query.limit(500)).all():
        data = _open(source)
        event_type = data.get("event_type", "human_message")
        existing = db.scalar(select(ProfileArchiveEvent.id).where(
            ProfileArchiveEvent.source_id == source.id, ProfileArchiveEvent.event_type == event_type,
        ))
        if not existing:
            enqueue_archive_event(db, source.account_id, data["original_source_id"], source.session_id,
                                  data, event_type=event_type, recorded_at=source.recorded_at)
            repaired += 1
    return repaired


def _mark_jobs_stale(db, account_id, fact_id):
    for row in db.scalars(select(ProfileJobVersion).where(ProfileJobVersion.account_id == account_id)).all():
        if any(ref.get("fact_id") == fact_id for ref in _open(row).get("fact_refs", [])):
            row.stale = True


def _invalidate(db, row, old, reason):
    invalidation = ProfileInvalidation(id=new_id(), account_id=row.account_id, fact_id=row.id,
                                      revision=row.revision, reason=reason)
    invalidation.payload = _seal(invalidation, {
        "value": old.get("value", ""), "source_ids": old.get("source_ids", []),
        "category": row.category, "subject": old.get("subject", ""), "field": old.get("field", ""),
    })
    db.add(invalidation)
    _mark_jobs_stale(db, row.account_id, row.id)
    if reason in {"correction", "deleted"}:
        for source_id in old.get("source_ids", []):
            disable_source(db, row.account_id, source_id)


def _replace_fact(db, row, value, source_id, expected_revision, effective_at=None,
                  recorded_at=None, reason="correction"):
    if row.status != "active" or row.revision != expected_revision:
        raise ProfileRevisionConflict("fact_revision_conflict")
    old = _open(row)
    if old.get("value") == value and _dt(old.get("effective_at")) == _dt(effective_at):
        return row
    _invalidate(db, row, old, reason)
    updated = {**old, "value": value, "effective_at": _iso(effective_at),
               "recorded_at": _iso(recorded_at or _now()), "last_mentioned_at": _iso(recorded_at or _now()),
               "source_ids": [source_id] if source_id else [], "history": []}
    # Corrections are not alternate résumé facts; only valid time-based state
    # changes keep a user-visible history, and context retrieval omits it.
    if reason == "state_change":
        updated["history"] = [*old.get("history", []), {
            "value": old.get("value"), "effective_at": old.get("effective_at"),
            "until": _iso(effective_at), "status": "historical",
        }][-30:]
    result = db.execute(update(ProfileFact).where(
        ProfileFact.id == row.id, ProfileFact.account_id == row.account_id,
        ProfileFact.revision == expected_revision, ProfileFact.status == "active",
    ).values(payload=_seal(row, updated), revision=expected_revision + 1, updated_at=_now())
       .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise ProfileRevisionConflict("fact_revision_conflict")
    db.expire(row)
    for conflict in db.scalars(select(ProfileConflict).where(
        ProfileConflict.fact_id == row.id, ProfileConflict.status == "pending",
    )).all():
        conflict.status = "superseded"
        conflict.payload = _seal(conflict, {})
    return row


def _is_invalidated_value(db, account_id, fact_id, value):
    return any(_open(row).get("value") == value for row in db.scalars(select(ProfileInvalidation).where(
        ProfileInvalidation.account_id == account_id, ProfileInvalidation.fact_id == fact_id,
        ProfileInvalidation.reason.in_(["correction", "deleted"]),
    )).all())


def _apply_proposal(db, account_id, proposal, source, event_id, *, allow_restore=False):
    key = _key(account_id, [proposal.category, proposal.subject.strip(), proposal.field])
    row = db.scalar(select(ProfileFact).where(ProfileFact.account_id == account_id, ProfileFact.slot_key == key))
    timestamp = source.recorded_at
    if row is None or (row.status == "deleted" and allow_restore):
        if row is None:
            row = ProfileFact(id=new_id(), account_id=account_id, category=proposal.category,
                              slot_key=key, revision=1, status="active")
        else:
            row.status, row.revision = "active", row.revision + 1
        row.payload = _seal(row, {"subject": proposal.subject.strip(), "field": proposal.field,
                                 "value": proposal.value.strip(), "source_ids": [source.id],
                                 "recorded_at": _iso(timestamp), "last_mentioned_at": _iso(timestamp),
                                 "effective_at": _iso(proposal.effective_at), "history": []})
        db.add(row)
        db.flush()
        return "added"
    if row.status != "active" or _is_invalidated_value(db, account_id, row.id, proposal.value):
        return "blocked"
    old = _open(row)
    if old["value"] == proposal.value:
        old["source_ids"] = list(dict.fromkeys([*old.get("source_ids", []), source.id]))[-100:]
        old["last_mentioned_at"] = _iso(max(_dt(old.get("last_mentioned_at")) or timestamp, timestamp))
        row.payload = _seal(row, old)
        # Repetition changes provenance, not fact revision or verification.
        return "duplicate"
    old_effective = _dt(old.get("effective_at"))
    new_effective = _dt(proposal.effective_at)
    if old_effective and new_effective and new_effective < old_effective:
        historical = {"value": proposal.value, "effective_at": _iso(new_effective),
                      "until": _iso(old_effective), "status": "historical"}
        if historical not in old.get("history", []):
            old["history"] = [*old.get("history", []), historical][-30:]
            row.payload = _seal(row, old)
        return "historical"
    correct = proposal.operation == "correct" and proposal.expected_revision == row.revision
    state_change = proposal.operation == "state_change" and old_effective and new_effective and new_effective > old_effective
    # Delayed jobs cannot override corrections committed after that input.
    stale_input = timestamp < (_dt(old.get("recorded_at")) or timestamp)
    if (correct or state_change) and not stale_input:
        _replace_fact(db, row, proposal.value, source.id, row.revision, proposal.effective_at,
                      timestamp, "correction" if correct else "state_change")
        return "updated"
    conflict = db.scalar(select(ProfileConflict).where(
        ProfileConflict.account_id == account_id, ProfileConflict.event_id == event_id,
        ProfileConflict.fact_id == row.id,
    ))
    if conflict is None:
        conflict = ProfileConflict(id=new_id(), account_id=account_id, fact_id=row.id,
                                   event_id=event_id, expected_revision=row.revision, status="pending")
        conflict.payload = _seal(conflict, {
            "current_value": old["value"], "proposed_value": proposal.value,
            "subject": old["subject"], "field": old["field"], "source_id": source.id,
            "effective_at": _iso(proposal.effective_at),
        })
        db.add(conflict)
    return "conflict"


def add_fact(db, account_id, *, category, subject, field, value, effective_at=None):
    try:
        proposal = ArchiveProposal(category=category, subject=subject, field=field, value=value,
                                   evidence_quote=value, effective_at=effective_at,
                                   long_term_preference=category == "preference")
    except ValidationError:
        raise ProfileValidationError("invalid_fact") from None
    profile = ensure_profile(db, account_id)
    _bump(db, profile)
    event = enqueue_archive_event(db, account_id, new_id(), None,
                                  {"human_text": value, "source_kind": "manual"}, "manual_fact")
    source = _owned(db, ProfileSource, account_id, event.source_id)
    result = _apply_proposal(db, account_id, proposal, source, event.id, allow_restore=True)
    event.status, event.completed_at = "completed", _now()
    event.payload = _seal(event, {"results": [result]})
    db.flush()
    return get_profile(db, account_id)


def edit_fact(db, account_id, fact_id, *, value, expected_revision, effective_at=None):
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ProfileValidationError("invalid_value")
    row = _owned(db, ProfileFact, account_id, fact_id)
    profile = ensure_profile(db, account_id)
    _bump(db, profile)
    event = enqueue_archive_event(db, account_id, new_id(), None,
                                  {"human_text": value, "source_kind": "manual"}, "manual_fact")
    _replace_fact(db, row, value.strip(), event.source_id, expected_revision, effective_at)
    event.status, event.completed_at = "completed", _now()
    db.flush()
    return _fact_view(db, row)


def delete_fact(db, account_id, fact_id, expected_revision):
    row = _owned(db, ProfileFact, account_id, fact_id)
    if row.revision != expected_revision or row.status != "active":
        raise ProfileRevisionConflict("fact_revision_conflict")
    _bump(db, ensure_profile(db, account_id))
    old = _open(row)
    _invalidate(db, row, old, "deleted")
    # Preserve only the opaque keyed slot tombstone; no deleted fact body.
    changed = db.execute(update(ProfileFact).where(
        ProfileFact.id == fact_id, ProfileFact.account_id == account_id,
        ProfileFact.revision == expected_revision, ProfileFact.status == "active",
    ).values(revision=expected_revision + 1, status="deleted", payload=_seal(row, {}))
       .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise ProfileRevisionConflict("fact_revision_conflict")
    db.expire(row)
    for source_id in old.get("source_ids", []):
        disable_source(db, account_id, source_id)
    for conflict in db.scalars(select(ProfileConflict).where(ProfileConflict.fact_id == row.id)).all():
        conflict.status = "deleted"
        conflict.payload = _seal(conflict, {})
    db.flush()
    return {"deleted": True, "fact_id": row.id, "revision": row.revision,
            "scope": "archive_and_future_use", "original_chat_retained": True}


def disable_source(db, account_id, source_id, *, original_id=False):
    if original_id:
        source = db.scalar(select(ProfileSource).where(
            ProfileSource.account_id == account_id,
            ProfileSource.source_key == _key(account_id, str(source_id), "source"),
        ))
        if not source:
            return False
    else:
        source = _owned(db, ProfileSource, account_id, source_id)
    source.disabled = True
    # Necessary ID and prohibition survive, copied raw message does not.
    data = _open(source)
    source.payload = _seal(source, {"original_source_id": data.get("original_source_id"), "disabled": True})
    for event in db.scalars(select(ProfileArchiveEvent).where(
        ProfileArchiveEvent.account_id == account_id, ProfileArchiveEvent.source_id == source.id,
    )).all():
        event.status, event.error_code, event.lease_token = "skipped", "source_disabled", None
        event.payload = _seal(event, {})
    return True


def disable_session_sources(db, account_id, session_id):
    """Deleting a chat retains already archived facts but bars source reuse."""
    for source in db.scalars(select(ProfileSource).where(
        ProfileSource.account_id == account_id, ProfileSource.session_id == session_id,
    )).all():
        disable_source(db, account_id, source.id)


def resolve_conflict(db, account_id, conflict_id, *, choice, expected_revision, value=None):
    row = _owned(db, ProfileConflict, account_id, conflict_id)
    fact = _owned(db, ProfileFact, account_id, row.fact_id)
    _bump(db, ensure_profile(db, account_id))
    db.refresh(row)
    db.refresh(fact)
    if row.status != "pending" or row.expected_revision != expected_revision or fact.revision != expected_revision:
        raise ProfileRevisionConflict("conflict_is_stale")
    data = _open(row)
    if not _source_enabled(db, account_id, data.get("source_id")):
        raise ProfileRevisionConflict("source_disabled")
    if choice == "keep":
        row.status = "kept"
    elif choice in {"replace", "custom"}:
        selected = data["proposed_value"] if choice == "replace" else value
        if not isinstance(selected, str) or not selected.strip() or len(selected) > 4000:
            raise ProfileValidationError("invalid_value")
        source_id = data["source_id"]
        if choice == "custom":
            event = enqueue_archive_event(db, account_id, new_id(), None,
                                          {"human_text": selected, "source_kind": "manual"}, "manual_fact")
            event.status, event.completed_at = "completed", _now()
            source_id = event.source_id
        _replace_fact(db, fact, selected.strip(), source_id, expected_revision,
                      data.get("effective_at") if choice == "replace" else None)
        row.status = "resolved"
    else:
        raise ProfileValidationError("invalid_choice")
    row.payload = _seal(row, {})
    db.flush()
    return _fact_view(db, fact)


def get_profile_summary(db, account_id):
    """Only identity and counts for a welcome; never import experience content."""
    rows = db.scalars(select(ProfileFact).where(
        ProfileFact.account_id == account_id, ProfileFact.status == "active",
        ProfileFact.category != "preference",
    ).order_by(ProfileFact.updated_at.desc())).all()
    name, experiences = "", set()
    for row in rows:
        data = _open(row)
        if row.category == "basic" and data.get("field") == "name" and not name:
            name = data.get("value") or ""
        if row.category in {"project", "work", "education"} and data.get("subject"):
            experiences.add((row.category, data["subject"]))
    return {"has_facts": bool(rows), "name": name, "experience_count": len(experiences)}


def get_context(db, account_id, *, subject_ids=None, limit=30, include_contacts=False):
    """Explicit scoped import protocol; facts + provenance refs, never history.

    subject_ids are stable fact IDs selected by the caller/UI, not raw subject
    strings. Without them only basic non-contact facts and long-term preferences
    are returned. Project history requires explicit selection.
    """
    query = select(ProfileFact).where(ProfileFact.account_id == account_id, ProfileFact.status == "active")
    if subject_ids:
        query = query.where(ProfileFact.id.in_(list(subject_ids)[:100]))
    else:
        query = query.where(ProfileFact.category.in_(["basic", "preference"]))
    facts = []
    for row in db.scalars(query.order_by(ProfileFact.updated_at.desc()).limit(min(limit, 100))).all():
        data = _open(row)
        if not include_contacts and data.get("field") in {"phone", "email"}:
            continue
        facts.append({"id": row.id, "revision": row.revision, "category": row.category,
                      "subject": data["subject"], "field": data["field"], "value": data["value"],
                      "effective_at": data.get("effective_at"), "source_type": "user_provided",
                      "source_ids": data.get("source_ids", [])})
    profile = db.scalar(select(PersonalProfile).where(PersonalProfile.account_id == account_id))
    return {"profile_id": profile.id if profile else None, "revision": profile.revision if profile else 0,
            "facts": facts, "fact_refs": [{"fact_id": f["id"], "revision": f["revision"]} for f in facts]}


def _archive_context(db, account_id, payload):
    """A mentioned project can be compared without importing it into a résumé.

    This is account-scoped matching over decrypted small records, not a global
    search index. Only explicitly named subjects or selected fact IDs reach the
    extractor. Ambiguous pronouns deliberately remain a conflict/question.
    """
    selected = set(payload.get("subject_ids") or [])
    text = payload.get("human_text", "")
    rows = db.scalars(select(ProfileFact).where(ProfileFact.account_id == account_id,
                                               ProfileFact.status == "active")).all()
    for row in rows:
        data = _open(row)
        if row.category in {"basic", "preference"} or (data.get("subject") and data["subject"] in text):
            selected.add(row.id)
    return get_context(db, account_id, subject_ids=selected, limit=30)


def invalidated_references(db, account_id, references):
    invalid = []
    for ref in references[:500]:
        row = db.scalar(select(ProfileFact).where(ProfileFact.account_id == account_id,
                                                ProfileFact.id == ref.get("fact_id")))
        if not row or row.status != "active" or row.revision != ref.get("revision"):
            invalid.append(ref)
    return invalid


def context_to_collected_info(context, current=None, *, projection_bindings=None):
    """Project selected facts into the existing collected_info schema.

    Existing user edits win. Call sanitize_projection before this function so
    known-wrong old values do not occupy those slots. Returns only the collected
    dict; context.fact_refs identifies the imported source revisions for a job.
    Preferences remain prompt/UI settings and are never résumé biography.
    """
    from app.services.resume_facts import normalize_fact_store, new_fact
    result = normalize_fact_store(current or {})
    result.setdefault("basic_info", {})
    result.setdefault("education", [])
    result.setdefault("work_experience", [])
    result.setdefault("projects", [])
    result.setdefault("skills", [])

    def bind(item, collection, field, fact):
        if not item.get("item_id"):
            item["item_id"] = new_id()
        reference = {"fact_id": fact["id"], "revision": fact["revision"]}
        evidence = item.setdefault("facts", [])
        matching = next((entry for entry in evidence if entry.get("text") == fact["value"]
                         and entry.get("status", "active") == "active"), None)
        if matching is None:
            matching = new_fact(fact["value"], source="import", kind="context")
            if field not in {"description", "bullets", "polished_bullets"}:
                matching["field"] = field
            evidence.append(matching)
        references = matching.setdefault("profile_refs", [])
        if reference not in references:
            references.append(reference)
        if projection_bindings is None:
            return
        projection_bindings.append({"item_id": item["item_id"], "collection": collection,
                                    "field": field, "fact_id": fact["id"], "revision": fact["revision"]})

    for fact in context.get("facts", []):
        category, field, value = fact.get("category"), fact.get("field"), fact.get("value")
        if not isinstance(value, str) or not value:
            continue
        if category == "basic":
            if field in {"name", "phone", "email", "location", "objective"}:
                if not result["basic_info"].get(field):
                    result["basic_info"][field] = value
        elif category == "skill":
            if value not in [entry.get("name") if isinstance(entry, dict) else entry for entry in result["skills"]]:
                result["skills"].append(value)
        elif category in {"project", "work", "education"}:
            collection, identity = {"project": ("projects", "name"),
                                    "work": ("work_experience", "company"),
                                    "education": ("education", "school")}[category]
            subject = fact.get("subject", "")
            items = result[collection]
            item = next((entry for entry in items if entry.get(identity) == subject), None)
            if item is None:
                item = {identity: subject}
                items.append(item)
            plain_fields = {
                "project": {"role", "start_date", "end_date", "description"},
                "work": {"title", "start_date", "end_date"},
                "education": {"degree", "major", "start_date", "end_date"},
            }[category]
            if field in plain_fields:
                if not item.get(field):
                    item[field] = value
                    bind(item, collection, field, fact)
                elif item[field] == value:
                    # Explicitly selecting the exact same fact establishes its
                    # source, while a different manual value remains unbound.
                    bind(item, collection, field, fact)
            elif category == "work" and field in {"description", "result", "role", "deliverable"}:
                if value not in item.setdefault("bullets", []):
                    item["bullets"].append(value)
                bind(item, collection, "bullets", fact)
            elif category == "project" and field in {"result", "status", "tool", "deliverable"}:
                lines = (item.get("description") or "").splitlines()
                if value not in lines:
                    item["description"] = "\n".join([*filter(None, lines), value])
                bind(item, collection, "description", fact)
    return result


def get_projection_guard(db, account_id):
    facts = {row.id: row for row in db.scalars(select(ProfileFact).where(
        ProfileFact.account_id == account_id,
    )).all()}
    invalid = []
    for row in db.scalars(select(ProfileInvalidation).where(
        ProfileInvalidation.account_id == account_id,
    )).all():
        data = _open(row)
        fact = facts.get(row.fact_id)
        # Legacy invalidations already contain subject/field. Category remains
        # on the fact's tombstone, so no database migration or old-value guess
        # is required when loading pre-scope encrypted records.
        invalid.append({**data, "fact_id": row.fact_id, "revision": row.revision,
                        "category": data.get("category") or (fact.category if fact else None),
                        "current_value": _open(fact).get("value") if fact and fact.status == "active" else None})
    blocked = []
    for row in db.scalars(select(ProfileSource).where(ProfileSource.account_id == account_id,
                                                    ProfileSource.disabled.is_(True))).all():
        blocked.extend([row.id, _open(row).get("original_source_id")])
    subjects = [{"category": row.category, "subject": _open(row).get("subject")}
                for row in facts.values() if row.status == "active"]
    return {"blocked_source_ids": [item for item in blocked if item],
            "invalidations": invalid, "subjects": [*subjects, *invalid]}


_PROJECTION_CATEGORIES = {"basic_info": "basic", "basic": "basic", "education": "education",
                          "projects": "project", "work_experience": "work",
                          "skills": "skill", "skill_groups": "skill"}
_PROJECTION_IDENTITIES = {"project": "name", "education": "school", "work": "company"}
_PROSE_FIELDS = {"description", "bullets", "polished_bullets", "highlights", "content", "text"}


def _contains_invalid_value(text, token):
    """Literal match with ASCII token boundaries: Go is not Google; 2025 is not 20250."""
    if not token:
        return False
    left = r"(?<![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", token[0]) else ""
    right = r"(?![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", token[-1]) else ""
    return re.search(left + re.escape(token) + right, text, flags=re.IGNORECASE) is not None


def _contains_phone(text, token):
    """Match complete phone numbers across formatting and explicit CN prefixes.

    We do not infer an arbitrary country code from a numeric suffix. Mainland
    mobile numbers have an unambiguous national form; other international
    numbers retain their country code, with + and 00 treated equivalently.
    """
    compact = re.sub(r"[\s.()（）-]", "", token)
    if not re.fullmatch(r"\+?\d{7,17}", compact):
        return False
    international = compact.startswith(("+", "00"))
    digits = compact.lstrip("+")
    if digits.startswith("00"):
        digits = digits[2:]
    if not 7 <= len(digits) <= 15:
        return False
    mobile = re.fullmatch(r"(?:86)?(1[3-9]\d{9})", digits)
    if mobile:
        national = mobile.group(1)
        forms = (national, "86" + national, "0086" + national)
    else:
        forms = (digits, "00" + digits) if international else (digits,)
    separator = r"[ \t.()（）-]*"
    for form in forms:
        # ASCII boundaries protect a longer identifier containing these digits;
        # the country-code forms are matched as whole numbers, before the
        # general word matcher can reject their adjacent prefix digits.
        pattern = r"(?<![A-Za-z0-9_])\+?" + separator.join(form) + r"(?![A-Za-z0-9_])"
        if re.search(pattern, text):
            return True
    return False


def _invalidation_applies(rule, text, *, category=None, subject=None, field=None, fact_id=None):
    """Match the fact's slot before considering its literal old value."""
    token = rule.get("value", "")
    if rule.get("category") == "basic" and rule.get("field") == "phone":
        return _contains_phone(text, token)
    if not _contains_invalid_value(text, token):
        return False
    # Full contact details remain private regardless of which résumé field
    # they were copied into. Do not apply this exception to partial numbers.
    if rule.get("category") == "basic":
        if rule.get("field") == "email" and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", token):
            return True
    if fact_id:
        return (fact_id == rule["fact_id"]
                and not (text == rule.get("current_value") and text != token))
    if category and rule.get("category") and category != rule["category"]:
        return False
    if subject and rule.get("subject") and subject != rule["subject"]:
        return False
    if category:
        # A current replacement only exempts this fact's matching slot. An
        # unrelated active fact with the old value must never grant an escape.
        if text == rule.get("current_value") and text != token:
            return False
        if field in _PROSE_FIELDS or category == "skill":
            return True
        return field == rule.get("field")
    # Without a schema/provenance mapping, quarantine affected prose fragments
    # instead of removing every string in the account. A bare number/year is
    # ambiguous; require its subject or a field cue, or an exact bare value.
    if re.fullmatch(r"[\d\s./年月日—–-]+", token):
        if re.fullmatch(r"[\d\s./年月日—–至-]+", text.strip()):
            return True
        if rule.get("subject") and rule["subject"] in text:
            return True
        if rule.get("category") == "education":
            return bool(re.search(r"毕业|入学|就读|学制|教育|学历|graduat|education", text, re.IGNORECASE))
        return False
    return True


def sanitize_projection(db, account_id, projection):
    """Remove invalid facts from their slots and quarantine unlinked legacy prose.

    Return (copy, changed). No replacement is invented. Known structured slots
    are bounded by category, subject and field; opaque old prose is quarantined
    by line/sentence. Disabled source records are still excluded in full.
    """
    guard = get_projection_guard(db, account_id)
    blocked = set(guard["blocked_source_ids"])
    rules = guard["invalidations"]
    subjects = sorted(guard["subjects"], key=lambda item: len(item.get("subject") or ""), reverse=True)
    changed = False

    def clean_text(value, scope):
        nonlocal changed
        if scope.get("category") or scope.get("fact_id"):
            if any(_invalidation_applies(rule, value, **scope) for rule in rules):
                changed = True
                return ""
            return value
        # Keep surrounding independent material when an old unlinked paragraph
        # contains a forgotten fact. Newlines retain a subject heading for the
        # rendered résumé dates/bullets that follow it.
        output = []
        heading_subject = None
        heading_category = None
        for line in value.splitlines(keepends=True):
            if line.lstrip().startswith("#"):
                heading_subject = None
                heading_category = next((category for pattern, category in (
                    (r"教育|学历|education", "education"), (r"项目|projects?", "project"),
                    (r"工作|实习|work|experience", "work"), (r"技能|skills?", "skill"),
                ) if re.search(pattern, line, re.IGNORECASE)), None)
            elif (heading_category in _PROJECTION_IDENTITIES
                  and not line.lstrip().startswith(("-", "*", "•"))
                  and (" · " in line or (heading_category == "education" and re.fullmatch(
                      r"[^。！？；\n]{1,160}(?:大学|学院|学校)", line.strip())))):
                # resume_to_text puts an item's identity before ` · ` and its
                # dates/bullets on following lines. Do not infer every unlabelled
                # prose line to be a new subject: that would bypass deletion.
                heading_subject = line.split(" · ", 1)[0].strip()
            for item in subjects:
                if item.get("subject") and item["subject"] == line.strip():
                    heading_subject, heading_category = item["subject"], item.get("category")
                    break
            pieces = re.split(r"(?<=[。！？!?；;])", line)
            for piece in pieces:
                prose_scope = {"category": heading_category, "subject": heading_subject, "field": "text"}
                # A subject mentioned inside a sentence scopes that sentence
                # only. It must not contaminate a previous sentence or the next
                # paragraph, especially when two schools share the same year.
                mentioned = next((item for item in subjects if item.get("subject") and item["subject"] in piece
                                  and (not heading_category or item.get("category") == heading_category)), None)
                if mentioned:
                    prose_scope.update(category=mentioned.get("category"), subject=mentioned["subject"])
                elif not heading_category or heading_category == "education":
                    school = re.match(r"\s*([^。！？；\n]{1,160}?(?:大学|学院|学校))(?=\s|[·：:,，]|\d{4})", piece)
                    if school:
                        prose_scope.update(category="education", subject=school.group(1).strip())
                if any(_invalidation_applies(rule, piece, **prose_scope) for rule in rules):
                    changed = True
                    # Preserve separation from the next unrelated paragraph.
                    if piece.endswith("\n"):
                        output.append("\n")
                else:
                    output.append(piece)
        return "".join(output)

    def walk(value, scope=None):
        nonlocal changed
        scope = scope or {}
        if isinstance(value, dict):
            source_ids = [value.get(key) for key in ("id", "message_id", "source_id", "turn_id")]
            source_ids.extend(value.get("source_ids") or [])
            if any(isinstance(item, str) and item in blocked for item in source_ids):
                changed = True
                return None
            category = scope.get("category") or value.get("category")
            subject = value.get(_PROJECTION_IDENTITIES.get(category, "")) or value.get("subject") or scope.get("subject")
            own_scope = {**scope, "category": category, "subject": subject}
            if value.get("fact_id"):
                own_scope["fact_id"] = value["fact_id"]
            # Structured extracted facts retain profile references separately
            # from their local opaque fact ID. Stale references invalidate the
            # whole evidence record, including source_quote.
            refs = value.get("profile_refs") or value.get("profile_fact_refs") or []
            if isinstance(refs, list) and refs and invalidated_references(db, account_id, refs):
                changed = True
                return None
            if value.get("profile_fact_id"):
                linked = db.get(ProfileFact, value["profile_fact_id"])
                if not linked or linked.account_id != account_id or linked.status != "active":
                    changed = True
                    return None
            result = {}
            for key, item in value.items():
                child_scope = {**own_scope, "field": value.get("field") if key == "value" else key}
                if key in _PROJECTION_CATEGORIES:
                    child_scope = {"category": _PROJECTION_CATEGORIES[key]}
                result[key] = walk(item, child_scope)
            if "facts" in value and len(result.get("facts") or []) < len(value.get("facts") or []):
                # Unstructured notes cannot reliably identify the removed source
                # span. Remove these copies so they cannot become evidence again.
                result["raw_notes"] = []
                for raw_field in ("raw_description", "description"):
                    if raw_field in result:
                        result[raw_field] = ""
            return result
        if isinstance(value, list):
            return [cleaned for item in value if (cleaned := walk(item, scope)) is not None]
        if isinstance(value, str):
            return clean_text(value, scope)
        return copy.deepcopy(value)

    return walk(projection), changed


def save_job_version(db, account_id, *, session_id, name, fact_refs=None):
    """Caller must authorize session ownership before invoking this method."""
    if not name.strip() or len(name) > 120:
        raise ProfileValidationError("invalid_name")
    refs = fact_refs
    if refs is None:
        refs = [{"fact_id": row.id, "revision": row.revision} for row in db.scalars(select(ProfileFact).where(
            ProfileFact.account_id == account_id, ProfileFact.status == "active",
        )).all()]
    if invalidated_references(db, account_id, refs):
        raise ProfileRevisionConflict("stale_fact_references")
    _bump(db, ensure_profile(db, account_id))
    row = db.scalar(select(ProfileJobVersion).where(ProfileJobVersion.account_id == account_id,
                                                  ProfileJobVersion.session_id == session_id))
    previous_payload = _open(row) if row is not None else {}
    if row is None:
        row = ProfileJobVersion(id=new_id(), account_id=account_id, session_id=session_id, revision=1, stale=False)
        db.add(row)
    else:
        row.revision += 1
        row.stale = False
    row.payload = _seal(row, {**previous_payload, "name": name.strip(), "fact_refs": refs})
    db.flush()
    return {**_open(row), "id": row.id, "session_id": row.session_id, "revision": row.revision, "stale": row.stale}


def merge_job_version_import(db, account_id, session_id, fact_refs):
    """Merge selected imports in the caller's canonical-save transaction.

    Keep an existing name and all still-current earlier dependencies. An old
    invalid reference is moved into outdated_refs rather than silently cleared.
    Even importing a newer revision cannot by itself prove that every old résumé
    sentence was synchronized, so this helper never clears an existing warning.
    Caller must authorize session ownership; this function does not commit.
    """
    if not isinstance(fact_refs, list) or len(fact_refs) > 500:
        raise ProfileValidationError("invalid_fact_references")
    _bump(db, ensure_profile(db, account_id))
    if invalidated_references(db, account_id, fact_refs):
        raise ProfileRevisionConflict("stale_fact_references")
    row = db.scalar(select(ProfileJobVersion).where(ProfileJobVersion.account_id == account_id,
                                                  ProfileJobVersion.session_id == session_id))
    if row is None:
        row = ProfileJobVersion(id=new_id(), account_id=account_id, session_id=session_id, revision=1, stale=False)
        data = {"name": "当前简历", "fact_refs": [], "outdated_refs": []}
        db.add(row)
    else:
        data = _open(row)
        row.revision += 1
    current = {}
    outdated = {(ref["fact_id"], ref["revision"]): ref for ref in data.get("outdated_refs", [])}
    for ref in data.get("fact_refs", []):
        if invalidated_references(db, account_id, [ref]):
            outdated[(ref["fact_id"], ref["revision"])] = ref
        else:
            current[ref["fact_id"]] = ref
    for ref in fact_refs:
        current[ref["fact_id"]] = {"fact_id": ref["fact_id"], "revision": ref["revision"]}
    row.stale = bool(row.stale or outdated)
    row.payload = _seal(row, {**data, "fact_refs": list(current.values()), "outdated_refs": list(outdated.values())})
    db.flush()
    return {**_open(row), "id": row.id, "session_id": row.session_id, "revision": row.revision, "stale": row.stale}


def rename_job_version(db, account_id, job_id, *, name, expected_revision):
    row = _owned(db, ProfileJobVersion, account_id, job_id)
    if row.revision != expected_revision:
        raise ProfileRevisionConflict("job_revision_conflict")
    if not name.strip() or len(name) > 120:
        raise ProfileValidationError("invalid_name")
    _bump(db, ensure_profile(db, account_id))
    changed = db.execute(update(ProfileJobVersion).where(
        ProfileJobVersion.id == job_id, ProfileJobVersion.account_id == account_id,
        ProfileJobVersion.revision == expected_revision,
    ).values(payload=_seal(row, {**_open(row), "name": name.strip()}), revision=expected_revision + 1)
       .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise ProfileRevisionConflict("job_revision_conflict")
    db.expire(row)
    return {**_open(row), "id": row.id, "session_id": row.session_id, "revision": row.revision, "stale": row.stale}


def retry_task(db, account_id, task_id):
    row = _owned(db, ProfileArchiveEvent, account_id, task_id)
    if row.status not in {"pending", "failed"} or not _source_enabled(db, account_id, row.source_id):
        raise ProfileRevisionConflict("task_not_retryable")
    row.status, row.attempts, row.available_at, row.error_code = "pending", 0, _now(), ""
    return {"status": "pending"}


async def process_pending_events(session_factory, extractor=None, *, limit=10, timeout_seconds=45,
                                 budget_reserver=None):
    """Bounded, restart-safe worker. No real model is required in tests.

    The caller schedules periodic runs. Without an extractor, source-backed
    deterministic facts can still be saved, but free-text semantic work remains
    visibly failed/model_unavailable and is not automatically retried until an
    extractor is supplied. Explicit manual confirmed_facts can complete offline.
    """
    def eligible(now):
        conditions = [ProfileArchiveEvent.available_at <= now, ProfileArchiveEvent.attempts < 5,
                      or_(ProfileArchiveEvent.status.in_(["pending", "failed"]),
                          and_(ProfileArchiveEvent.status == "running", ProfileArchiveEvent.lease_until < now))]
        if extractor is None:
            conditions.append(ProfileArchiveEvent.error_code != "model_unavailable")
        return and_(*conditions)
    with session_factory() as db:
        ids = list(db.scalars(select(ProfileArchiveEvent.id).where(eligible(_now()))
                             .order_by(ProfileArchiveEvent.created_at).limit(limit)).all())
    outcome = {"completed": 0, "failed": 0, "skipped": 0}
    for event_id in ids:
        token = new_id()
        now = _now()
        with session_factory() as db:
            claimed = db.execute(update(ProfileArchiveEvent).where(
                ProfileArchiveEvent.id == event_id, eligible(now),
            ).values(status="running", lease_token=token, lease_until=now + timedelta(seconds=timeout_seconds + 30),
                     attempts=ProfileArchiveEvent.attempts + 1).execution_options(synchronize_session=False))
            db.commit()
            if claimed.rowcount != 1:
                continue
        try:
            with session_factory() as db:
                event = db.get(ProfileArchiveEvent, event_id)
                source = db.get(ProfileSource, event.source_id)
                if not source or source.disabled or source.kind not in {"self", "manual"}:
                    event.status, event.lease_token = "skipped", None
                    db.commit()
                    outcome["skipped"] += 1
                    continue
                payload, account_id = _open(source), event.account_id
                context = _archive_context(db, account_id, payload)
            proposals = deterministic_proposals(payload)
            if extractor is not None:
                if budget_reserver is not None:
                    reservation = budget_reserver(account_id)
                    if inspect.isawaitable(reservation):
                        await reservation
                pending = extractor(payload, context)
                answer = await asyncio.wait_for(pending, timeout_seconds) if inspect.isawaitable(pending) else pending
                batch = answer if isinstance(answer, ArchiveBatch) else ArchiveBatch.model_validate(answer)
                proposals.extend(batch.proposals)
            # Source excerpts are mandatory for every model-proposed value.
            grounded = []
            for item in proposals:
                if validate_grounding(item, payload, context):
                    grounded.append(item)
                elif item.operation == "correct":
                    # An unsupported correction label cannot silently overwrite,
                    # but a grounded conflicting fact still deserves a question.
                    tentative = item.model_copy(update={"operation": "add", "expected_revision": None})
                    if validate_grounding(tentative, payload, context):
                        grounded.append(tentative)
            unique = {(item.category, item.subject, item.field, item.value): item for item in grounded}
            confirmed = payload.get("confirmed_facts") or []
            # Free text may contain additional project details even if some
            # basic fields were extracted. Do not call the whole event complete
            # merely because the deterministic subset succeeded.
            manual_complete = (payload.get("source_kind") == "manual" and bool(confirmed)
                               and len(grounded) == len(proposals))
            waiting_model = (extractor is None and bool(payload.get("human_text", "").strip())
                             and not manual_complete)
            with session_factory() as db:
                event = db.get(ProfileArchiveEvent, event_id)
                source = db.get(ProfileSource, event.source_id)
                if event.status != "running" or event.lease_token != token:
                    outcome["skipped"] += 1
                    continue
                if not source or source.disabled or source.account_id != account_id:
                    event.status, event.lease_token = "skipped", None
                    db.commit()
                    outcome["skipped"] += 1
                    continue
                _bump(db, ensure_profile(db, account_id))
                results = [_apply_proposal(db, account_id, item, source, event.id) for item in unique.values()]
                event.status = "failed" if waiting_model else "completed"
                event.completed_at = None if waiting_model else _now()
                event.lease_token, event.error_code = None, "model_unavailable" if waiting_model else ""
                if waiting_model:
                    # No model attempt was made. Keep retries available for the
                    # first configured model and avoid an idle poll retry loop.
                    event.attempts = max(0, event.attempts - 1)
                    event.available_at = _now()
                event.payload = _seal(event, {"results": results, "discarded": len(proposals) - len(grounded),
                                             "deterministic_saved": bool(results), "waiting_model": waiting_model})
                db.commit()
                outcome["failed" if waiting_model else "completed"] += 1
        except asyncio.CancelledError:
            # Keep the lease; another process will resume after lease expiry.
            raise
        except Exception as error:
            with session_factory() as db:
                event = db.get(ProfileArchiveEvent, event_id)
                if event and event.status == "running" and event.lease_token == token:
                    event.status, event.lease_token = "failed", None
                    exhausted = getattr(error, "status_code", None) == 429
                    event.error_code = ("budget_exhausted" if exhausted
                                        else "revision_conflict" if isinstance(error, ProfileRevisionConflict)
                                        else "archive_timeout" if isinstance(error, TimeoutError)
                                        else "archive_unavailable")
                    event.available_at = ((_now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                                          if exhausted else _now() + timedelta(seconds=min(300, 2 ** event.attempts)))
                    db.commit()
            outcome["failed"] += 1
    return outcome
