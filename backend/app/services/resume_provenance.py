"""Server-owned fact bindings for explicitly imported résumé items.

Only opaque item IDs travel with the editable document. Fact references live in
the existing encrypted job payload and cannot be removed by a client rewrite.
No function here commits: bindings and the canonical document share a transaction.
"""

import copy
import json

from fastapi import HTTPException
from sqlalchemy import select

from app.models.profile import ProfileFact, ProfileJobVersion, new_id


COLLECTIONS = ("education", "work_experience", "projects")
PAYLOAD_KEY = "projection_v1"


def _conflict():
    return HTTPException(409, "经历来源标识已变化或缺失，请载入当前版本后重试")


def _job(db, account_id, session_id):
    return db.scalar(select(ProfileJobVersion).where(
        ProfileJobVersion.account_id == account_id, ProfileJobVersion.session_id == session_id,
    ))


def _payload(row):
    from app.services.profile_service import _open
    return _open(row) if row is not None else {"name": "当前简历", "fact_refs": [], "outdated_refs": []}


def _write_payload(db, account_id, session_id, row, payload):
    from app.services.profile_service import _seal
    if row is None:
        row = ProfileJobVersion(id=new_id(), account_id=account_id, session_id=session_id,
                                revision=1, stale=False)
        db.add(row)
    else:
        row.revision += 1
    row.payload = _seal(row, payload)
    db.flush()


def _item_index(data):
    result = {}
    for collection in COLLECTIONS:
        for item in data.get(collection) or []:
            item_id = item.get("item_id")
            if not item_id:
                continue
            if item_id in result:
                raise _conflict()
            result[item_id] = (collection, item)
    return result


def _content_signature(collection, item):
    """Exact substantive content, excluding only display identity and empty defaults."""
    fields = {"projects": ("role", "start_date", "end_date", "description", "polished_bullets"),
              "education": ("degree", "major", "start_date", "end_date", "highlights"),
              "work_experience": ("title", "start_date", "end_date", "bullets")}[collection]
    content = {key: item[key] for key in fields if item.get(key) not in (None, "", [])}
    # An identity-only item has no independent payload to compare.
    return json.dumps(content, ensure_ascii=False, sort_keys=True) if content else None


def register_fact_items(db, account_id, session_id, collected_info, proposed):
    """Register server-created identities from extractor state, never editor input."""
    authoritative = _item_index(collected_info)
    candidates = _item_index(proposed)
    row = _job(db, account_id, session_id)
    payload = _payload(row)
    projection = copy.deepcopy(payload.get(PAYLOAD_KEY) or {"items": {}})
    known = projection.setdefault("items", {})
    additions = {key: collection for key, (collection, _) in candidates.items()
                 if key not in known and key in authoritative and authoritative[key][0] == collection}
    if not additions:
        return
    # Even a trusted extractor cannot move another session's opaque identities.
    for other in db.scalars(select(ProfileJobVersion).where(ProfileJobVersion.session_id != session_id)).all():
        if set(additions) & set(_payload(other).get(PAYLOAD_KEY, {}).get("items", {})):
            raise _conflict()
    for item_id, collection in additions.items():
        known[item_id] = {"collection": collection, "fields": {}}
    payload[PAYLOAD_KEY] = projection
    _write_payload(db, account_id, session_id, row, payload)


def validate_item_ids(db, account_id, session_id, current, proposed, *, removed_item_ids=(), bindings=()):
    """Require identities on existing bound items; new unbound items stay usable."""
    current_items = _item_index(current)
    proposed_items = _item_index(proposed)
    row = _job(db, account_id, session_id)
    known = _payload(row).get(PAYLOAD_KEY, {}).get("items", {})
    new_items = {entry["item_id"]: entry["collection"] for entry in bindings}
    removed = set(removed_item_ids)
    if len(removed) != len(removed_item_ids) or removed - set(current_items):
        raise _conflict()
    if removed & set(proposed_items):
        raise _conflict()
    if set(current_items) - set(proposed_items) - removed:
        raise _conflict()
    # A removed identity must not be replaced in this same request by the exact
    # same body without its ID (a display rename is not a new experience). This
    # deliberately does not guess whether differently authored new prose is a
    # paraphrase, nor prohibit ordinary delete-plus-add edits.
    for item_id in removed:
        collection, original = current_items[item_id]
        signature = _content_signature(collection, original)
        if signature and any(not item.get("item_id") and _content_signature(collection, item) == signature
                             for item in proposed.get(collection) or []):
            raise _conflict()
    for item_id, (collection, _) in proposed_items.items():
        registered = known.get(item_id)
        if registered is None:
            if new_items.get(item_id) != collection:
                raise _conflict()
        elif registered.get("removed") or registered.get("collection") != collection:
            raise _conflict()
    # The committed source itself must also still belong to this session's map.
    if any(item_id not in known for item_id in current_items):
        raise _conflict()


def update_bindings(db, account_id, session_id, proposed, *, bindings=(), removed_item_ids=()):
    if not bindings and not removed_item_ids:
        return
    row = _job(db, account_id, session_id)
    payload = _payload(row)
    projection = copy.deepcopy(payload.get(PAYLOAD_KEY) or {"items": {}})
    items = projection.setdefault("items", {})
    proposed_items = _item_index(proposed)
    for binding in bindings:
        item_id, collection, field = (binding[key] for key in ("item_id", "collection", "field"))
        if item_id not in proposed_items or proposed_items[item_id][0] != collection:
            raise _conflict()
        fact = db.get(ProfileFact, binding["fact_id"])
        if (not fact or fact.account_id != account_id or fact.status != "active"
                or fact.revision != binding["revision"]):
            raise HTTPException(409, "档案已变化，请刷新后重新选取资料")
        item = items.setdefault(item_id, {"collection": collection, "fields": {}})
        if item.get("removed") or item.get("collection") != collection:
            raise _conflict()
        references = item.setdefault("fields", {}).setdefault(field, [])
        def still_current(ref):
            previous = db.get(ProfileFact, ref["fact_id"])
            return (ref["fact_id"] != fact.id and previous is not None
                    and previous.account_id == account_id and previous.status == "active"
                    and previous.revision == ref["revision"])
        references[:] = [ref for ref in references if still_current(ref)]
        references.append({"fact_id": fact.id, "revision": fact.revision})
    for item_id in removed_item_ids:
        if item_id not in items:
            raise _conflict()
        items[item_id]["removed"] = True
    payload[PAYLOAD_KEY] = projection
    _write_payload(db, account_id, session_id, row, payload)


def sanitize_bound_fields(db, account_id, projection):
    """Use server bindings across this account; display names never determine identity."""
    from app.services.profile_service import _open, get_projection_guard, _invalidation_applies, _PROSE_FIELDS
    item_rules = {}
    for row in db.scalars(select(ProfileJobVersion).where(ProfileJobVersion.account_id == account_id)).all():
        item_rules.update(_open(row).get(PAYLOAD_KEY, {}).get("items", {}))
    if not item_rules:
        return copy.deepcopy(projection), False
    invalidation_rules = get_projection_guard(db, account_id)["invalidations"]
    invalid = {}

    def stale(ref):
        key = (ref["fact_id"], ref["revision"])
        if key not in invalid:
            fact = db.get(ProfileFact, ref["fact_id"])
            invalid[key] = (not fact or fact.account_id != account_id or fact.status != "active"
                            or fact.revision != ref["revision"])
        return invalid[key]

    changed = False

    def walk(value, fact_store=False):
        nonlocal changed
        if isinstance(value, dict):
            result = {key: walk(item, fact_store or key == "collected_info") for key, item in value.items()}
            rule = item_rules.get(value.get("item_id"))
            if not rule:
                return result
            if rule.get("removed") and not (fact_store or "facts" in value):
                changed = True
                return None
            for field, references in rule.get("fields", {}).items():
                stale_refs = [ref for ref in references if stale(ref)]
                if not stale_refs:
                    continue
                # Imported evidence inherits only its matching slot/references.
                # A removed role must not erase this item's independent actions.
                stale_ids = {ref["fact_id"] for ref in stale_refs}
                def affected_fact(fact):
                    refs = fact.get("profile_refs") or fact.get("profile_fact_refs") or []
                    linked = {ref.get("fact_id") for ref in refs if isinstance(ref, dict)}
                    linked.add(fact.get("profile_fact_id"))
                    return (bool(linked & stale_ids) or fact.get("field") == field
                            or (field in {"description", "bullets", "polished_bullets"} and not fact.get("field")))
                existing = result.get("facts") or []
                kept = [fact for fact in existing if not affected_fact(fact)]
                if kept != existing:
                    result["facts"] = kept
                    result["raw_notes"] = []
                    if field in {"description", "bullets", "polished_bullets"}:
                        for raw_field in ("raw_description", "description"):
                            if raw_field in result:
                                result[raw_field] = ""
                    changed = True
                # Project bullets are derived from description and inherit its
                # dependency even after a user adopts a different wording.
                fields = (field, "polished_bullets") if field == "description" else (field,)
                for target in fields:
                    if result.get(target):
                        result[target] = [] if isinstance(result[target], list) else ""
                        changed = True
                # A linked responsibility/date can also have a literal copy in
                # this item's prose. Stable identity scopes the old wording to
                # this item even after its display name changes.
                stale_ids = {ref["fact_id"] for ref in stale_refs}
                rules = [entry for entry in invalidation_rules if entry["fact_id"] in stale_ids]

                def clean_copy(text):
                    nonlocal changed
                    if isinstance(text, str) and any(_invalidation_applies(
                            entry, text, fact_id=entry["fact_id"]) for entry in rules):
                        changed = True
                        return ""
                    if isinstance(text, list):
                        return [clean_copy(part) for part in text]
                    return text

                for target in _PROSE_FIELDS:
                    if target in result:
                        result[target] = clean_copy(result[target])
            return result
        if isinstance(value, list):
            return [cleaned for item in value if (cleaned := walk(item, fact_store)) is not None]
        return copy.deepcopy(value)

    return walk(projection), changed
