"""Offline privacy-state replay for application and checkpoint backups.

The trusted latest digest is supplied from an independent operator-controlled
location. Possession of an authenticated old snapshot alone is insufficient.
This module never claims to prove that the operator's anchor is truly latest.
"""

from contextlib import closing
from datetime import UTC, datetime
import hashlib
import hmac
import json
import re
import sqlite3


PRIVACY_TABLES = (
    "accounts", "personal_profiles", "profile_facts", "profile_sources",
    "profile_conflicts", "profile_job_versions", "profile_archive_events", "profile_invalidations",
)
PRIVATE_CONTEXT = {"owner": "operations", "record": "latest-privacy-state", "field": "privacy-state"}


def _identifier(value):
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", value):
        raise ValueError("Unsupported database identifier")
    return '"' + value + '"'


def _tables(db):
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _rows(db, name):
    cursor = db.execute("SELECT * FROM " + _identifier(name))
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def storage_kind(db):
    tables = _tables(db)
    if "resume_sessions" in tables and "conversations" in tables:
        return "application"
    if "checkpoints" in tables and "writes" in tables:
        return "checkpoint"
    raise ValueError("Restore only supports recognized application or checkpoint databases")


def privacy_baseline(db):
    """Only routing/version metadata; no raw personal content in the baseline."""
    if storage_kind(db) != "application":
        raise ValueError("Privacy baseline requires an application database")
    tables = _tables(db)
    facts = _rows(db, "profile_facts") if "profile_facts" in tables else []
    sources = _rows(db, "profile_sources") if "profile_sources" in tables else []
    invalidations = _rows(db, "profile_invalidations") if "profile_invalidations" in tables else []
    resumes = {row["session_id"]: row for row in _rows(db, "resume_sessions")}
    sessions = {}
    for row in _rows(db, "conversations"):
        resume = resumes.get(row["session_id"])
        if not resume or resume.get("stage") == "__DELETED__":
            continue
        sessions[row["session_id"]] = {
            "owner": row["owner_hash"], "storage_owner": resume.get("owner_key") or row["owner_hash"],
            "version": resume.get("version", 0),
            "canonical_digest": _digest([resume.get("resume_data"), resume.get("resume_draft"), resume.get("stage")]),
        }
    return {
        "version": 1,
        "accounts": sorted(row["id"] for row in _rows(db, "accounts")) if "accounts" in tables else [],
        "facts": {row["id"]: {"account": row["account_id"], "revision": row["revision"], "status": row["status"]} for row in facts},
        "disabled_sources": {row["id"]: row["account_id"] for row in sources if row["disabled"]},
        "invalidations": {row["id"]: row["account_id"] for row in invalidations},
        "sessions": sessions,
    }


def snapshot_privacy(db, crypto):
    if not set(PRIVACY_TABLES).issubset(_tables(db)):
        raise ValueError("Latest privacy source must have the complete current archive schema")
    tables = {}
    for name in PRIVACY_TABLES:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]
        indexes = [row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (name,))]
        tables[name] = {"schema": sql, "indexes": indexes, "rows": _rows(db, name)}
    state = {"version": 1, "created_at": datetime.now(UTC).isoformat(),
             "baseline": privacy_baseline(db), "tables": tables}
    validate_privacy(state, crypto)
    return state


def validate_privacy(state, crypto):
    if state.get("version") != 1 or set(state.get("tables", {})) != set(PRIVACY_TABLES):
        raise ValueError("Unsupported or incomplete privacy state")
    if state.get("baseline", {}).get("version") != 1:
        raise ValueError("Missing privacy baseline")
    for name, table in state["tables"].items():
        for row in table["rows"]:
            if name == "accounts":
                crypto.decrypt_text(row["email_ciphertext"], owner="account:" + row["id"], record=row["id"], field="email")
            elif "payload" in row:
                crypto.decrypt_text(row["payload"], owner="account:" + row["account_id"], record=row["id"], field="payload")


def load_trusted_privacy(path, expected_sha256, crypto):
    if path is None or not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("Latest privacy state and an independently trusted SHA-256 are required")
    encoded = path.read_bytes()
    digest = hashlib.sha256(encoded).hexdigest()
    if not hmac.compare_digest(digest, expected_sha256.lower()):
        raise ValueError("Privacy snapshot does not match the trusted latest digest")
    envelope = json.loads(encoded)
    if envelope.get("format") != "huhua-privacy-state-v1":
        raise ValueError("Unsupported privacy snapshot format")
    state = crypto.decrypt_json(envelope["state"], **PRIVATE_CONTEXT)
    validate_privacy(state, crypto)
    return state, digest


def allowed_sessions(old, latest, *, discard_all=False):
    if discard_all or not old or old.get("version") != 1:
        return set(), set(), "all_old_conversations_discarded_no_reliable_baseline"
    current = latest["baseline"]
    affected = set(old.get("accounts", [])) - set(current["accounts"])
    for fact_id, previous in old.get("facts", {}).items():
        present = current["facts"].get(fact_id)
        if not present or present != previous:
            affected.add(previous["account"])
    for field in ("disabled_sources", "invalidations"):
        for record_id, account in current[field].items():
            if record_id not in old.get(field, {}):
                affected.add(account)
    allowed = set()
    for session_id, previous in old.get("sessions", {}).items():
        present = current["sessions"].get(session_id)
        owner = previous.get("owner", "")
        if present == previous and (not owner.startswith("account:") or owner.split(":", 1)[1] not in affected):
            allowed.add(session_id)
    return allowed, affected, "latest_privacy_state_replayed"


def _replace_latest_tables(db, state):
    # Snapshot tables come from an authenticated exporter and use a fixed name
    # allowlist. No arbitrary destination or source SQL is accepted from CLI.
    for name in reversed(PRIVACY_TABLES):
        db.execute("DROP TABLE IF EXISTS " + _identifier(name))
    for name in PRIVACY_TABLES:
        table = state["tables"][name]
        db.execute(table["schema"])
        for row in table["rows"]:
            columns = list(row)
            db.execute("INSERT INTO " + _identifier(name) + " (" + ",".join(_identifier(c) for c in columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")", tuple(row[c] for c in columns))
        for sql in table.get("indexes", []):
            db.execute(sql)


def _retain_session_rows(db, name, column, allowed):
    if name not in _tables(db):
        return 0
    count = db.execute("SELECT COUNT(*) FROM " + _identifier(name)).fetchone()[0]
    db.execute("CREATE TEMP TABLE IF NOT EXISTS allowed_restore_sessions (id TEXT PRIMARY KEY)")
    db.execute("DELETE FROM allowed_restore_sessions")
    db.executemany("INSERT INTO allowed_restore_sessions VALUES (?)", [(item,) for item in sorted(allowed)])
    db.execute("DELETE FROM " + _identifier(name) + " WHERE " + _identifier(column) + " NOT IN (SELECT id FROM allowed_restore_sessions)")
    return count - db.execute("SELECT COUNT(*) FROM " + _identifier(name)).fetchone()[0]


def replay_application(db, state, allowed, crypto):
    tables = _tables(db)
    # Never copy forgotten legacy feature records as private plaintext.
    known = set(PRIVACY_TABLES) | {"resume_sessions", "conversations", "resume_suggestions", "claimed_history_imports",
                                 "account_sessions", "account_login_challenges", "account_auth_rate_buckets", "daily_usage",
                                 "schema_versions", "users", "wrapper_records", "decode_records"}
    for name in tables:
        if name.startswith("sqlite_"):
            continue
        if name not in known or name in {"users", "wrapper_records", "decode_records"}:
            if db.execute("SELECT COUNT(*) FROM " + _identifier(name)).fetchone()[0]:
                raise ValueError("Unmapped populated table requires a separately reviewed privacy restore")
    db.execute("PRAGMA foreign_keys=OFF")
    removed = {}
    for name in ("resume_suggestions", "conversations", "resume_sessions"):
        removed[name] = _retain_session_rows(db, name, "session_id", allowed)
    for name in ("account_sessions", "account_login_challenges", "claimed_history_imports"):
        if name in tables:
            removed[name] = db.execute("SELECT COUNT(*) FROM " + _identifier(name)).fetchone()[0]
            db.execute("DELETE FROM " + _identifier(name))
    _replace_latest_tables(db, state)
    # Latest archived facts survive, but raw sources from discarded conversations
    # must not feed a new extraction job after the old conversation is gone.
    disabled = set()
    for source in _rows(db, "profile_sources"):
        if source.get("session_id") and source["session_id"] not in allowed:
            context = {"owner": "account:" + source["account_id"], "record": source["id"], "field": "payload"}
            data = json.loads(crypto.decrypt_text(source["payload"], **context))
            payload = crypto.encrypt_text(json.dumps({"original_source_id": data.get("original_source_id"), "disabled": True}), **context)
            db.execute("UPDATE profile_sources SET disabled=1,payload=? WHERE id=?", (payload, source["id"]))
            disabled.add(source["id"])
    stopped_tasks = 0
    for event in _rows(db, "profile_archive_events"):
        if event["source_id"] in disabled:
            payload = crypto.encrypt_text("{}", owner="account:" + event["account_id"], record=event["id"], field="payload")
            db.execute("UPDATE profile_archive_events SET status='skipped',error_code='restore_source_discarded',lease_token=NULL,lease_until=NULL,payload=? WHERE id=?", (payload, event["id"]))
            stopped_tasks += 1
    removed["profile_job_versions"] = _retain_session_rows(db, "profile_job_versions", "session_id", allowed)
    return {"discarded_rows": removed, "disabled_sources": len(disabled), "stopped_archive_tasks": stopped_tasks,
            "latest_archive_state_replayed": True, "old_logins_revoked": True}


def replay_checkpoint(db, allowed):
    removed = {name: _retain_session_rows(db, name, "thread_id", allowed) for name in ("checkpoints", "writes")}
    return {"discarded_rows": removed, "latest_archive_state_replayed": False}


def apply_privacy_recovery(content, state, crypto, *, baseline=None, discard_all=False):
    with closing(sqlite3.connect(":memory:")) as db:
        db.deserialize(content)
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup database integrity check failed")
        kind = storage_kind(db)
        if kind == "application":
            baseline = privacy_baseline(db)
        allowed, affected, policy = allowed_sessions(baseline, state, discard_all=discard_all)
        available = {row[0] for row in db.execute("SELECT DISTINCT " + ("session_id FROM resume_sessions" if kind == "application" else "thread_id FROM checkpoints"))}
        allowed &= available
        result = replay_application(db, state, allowed, crypto) if kind == "application" else replay_checkpoint(db, allowed)
        db.commit()
        # New output cannot contain deleted rows in freelist or WAL pages.
        db.execute("VACUUM")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Privacy-replayed database integrity failed")
        return db.serialize(), {**result, "storage_kind": kind, "recovery_policy": policy,
                                "discarded_conversations": len(available - allowed), "retained_conversations": len(allowed),
                                "affected_accounts": len(affected), "latest_digest_is_operator_trust_anchor": True,
                                "automatic_latest_proof": False}
