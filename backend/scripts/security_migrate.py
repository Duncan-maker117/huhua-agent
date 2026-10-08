"""Offline security operations. Every data path is explicit; never edit source DBs.

Examples (run with configured environment keys, never put secrets in arguments):
  python backend/scripts/security_migrate.py check-keys
  python backend/scripts/security_migrate.py backup --source copy.sqlite3 --destination backup.encrypted
  python backend/scripts/security_migrate.py privacy-export --source latest-app.sqlite3 --destination privacy.encrypted
  python backend/scripts/security_migrate.py restore --source backup.encrypted --destination restored.sqlite3 \
    --privacy-state privacy.encrypted --privacy-sha256 INDEPENDENTLY_TRUSTED_LATEST_SHA256
  python backend/scripts/security_migrate.py checkpoint-migrate --source copied-checkpoints.sqlite3 \
    --destination migrated-checkpoints.sqlite3 --owner-map storage-owners.json

Owner-map JSON maps thread IDs to immutable storage owners. Checkpoint migration
also rotates encrypted records to the active key. Application DB schema/content
migration is separate. Stop writes and validate paired application/checkpoint
copies before cutover. This command does not cut over a running service.
"""

import argparse
import asyncio
from contextlib import closing
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.services.data_crypto import crypto_from_settings
from app.services.secure_checkpoint import PAYLOAD_CHANNEL, SecureCheckpointSaver
from scripts.privacy_restore import (
    PRIVATE_CONTEXT, apply_privacy_recovery, load_trusted_privacy, privacy_baseline,
    snapshot_privacy, storage_kind,
)


BACKUP_CONTEXT = {"owner": "operations", "record": "sqlite-backup", "field": "backup"}


def _new_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL is essential: a typo must never replace an existing database.
    return os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb")


def _sqlite_snapshot(source: Path):
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src, closing(sqlite3.connect(":memory:")) as snapshot:
        src.backup(snapshot)
        content = snapshot.serialize()
        # backup() has already merged committed WAL pages into this standalone
        # snapshot, but serialize() can retain the WAL read/write header flags.
        # deserialize() cannot open WAL-backed memory databases (SQLITE_CANTOPEN).
        # Normalize only the copied image as documented by SQLite; never change
        # the source journal mode or create a plaintext on-disk intermediate.
        # https://www.sqlite.org/c3ref/deserialize.html
        return content[:18] + b"\x01\x01" + content[20:]


def privacy_export(source: Path, destination: Path, crypto):
    if not crypto.enabled:
        raise ValueError("Privacy export requires encryption keys")
    with closing(sqlite3.connect(":memory:")) as db:
        db.deserialize(_sqlite_snapshot(source))
        state = snapshot_privacy(db, crypto)
    payload = {"format": "huhua-privacy-state-v1", "state": crypto.encrypt_json(state, **PRIVATE_CONTEXT)}
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    with _new_file(destination) as handle:
        handle.write(encoded)
    return {"privacy_exported": True, "trusted_sha256": hashlib.sha256(encoded).hexdigest(),
            "created_at": state["created_at"], "must_pin_digest_independently": True,
            "automatic_latest_proof": False}


def backup(source: Path, destination: Path, crypto, *, application_state: Path | None = None):
    if not crypto.enabled:
        raise ValueError("Encrypted backups require data keys")
    content = _sqlite_snapshot(source)
    with closing(sqlite3.connect(":memory:")) as db:
        db.deserialize(content)
        kind = storage_kind(db)
        baseline = privacy_baseline(db) if kind == "application" else None
    if kind == "checkpoint" and application_state is not None:
        with closing(sqlite3.connect(":memory:")) as db:
            db.deserialize(_sqlite_snapshot(application_state))
            baseline = privacy_baseline(db)
    checksum = hashlib.sha256(content).hexdigest()
    payload = {"format": "huhua-sqlite-backup-v2", "sha256": checksum,
               "database": crypto.encrypt_bytes(content, **BACKUP_CONTEXT)}
    # Bind the backup's routing/privacy baseline to the exact database bytes;
    # metadata copied from another valid backup must not bypass deletion replay.
    metadata = {"created_at": datetime.now(UTC).isoformat(), "privacy_baseline": baseline}
    payload["metadata"] = crypto.encrypt_json(metadata, owner="operations", record="sqlite-backup:" + checksum, field="metadata")
    with _new_file(destination) as handle:
        handle.write(json.dumps(payload, separators=(",", ":")).encode())
    return {"backup_created": True, "key_id": crypto.active_key, "storage_kind": kind,
            "privacy_baseline_attached": bool(baseline)}


def restore(source: Path, destination: Path, crypto, *, privacy_state=None, privacy_sha256=None, discard_all_conversations=False):
    # A genuine old encrypted backup is not permission to restore facts that
    # were subsequently erased. Require an independent latest trust anchor.
    privacy, trusted_digest = load_trusted_privacy(privacy_state, privacy_sha256, crypto)
    payload = json.loads(source.read_text())
    if payload.get("format") not in {"huhua-sqlite-backup-v1", "huhua-sqlite-backup-v2"}:
        raise ValueError("Unsupported backup format")
    content = crypto.decrypt_bytes(payload["database"], **BACKUP_CONTEXT)
    if hashlib.sha256(content).hexdigest() != payload["sha256"]:
        raise ValueError("Backup checksum mismatch")
    metadata = {}
    if payload["format"] == "huhua-sqlite-backup-v2":
        metadata = crypto.decrypt_json(payload["metadata"], owner="operations", record="sqlite-backup:" + payload["sha256"], field="metadata")
        if datetime.fromisoformat(privacy["created_at"]) < datetime.fromisoformat(metadata["created_at"]):
            raise ValueError("Privacy snapshot predates the backup; obtain the trusted latest state")
    content, replay = apply_privacy_recovery(content, privacy, crypto,
                                           baseline=metadata.get("privacy_baseline"),
                                           discard_all=discard_all_conversations)
    with _new_file(destination) as handle:
        handle.write(content)
    return {"restored_to_new_file": True, "integrity": "ok", "trusted_privacy_sha256": trusted_digest,
            "source_unchanged": True, "cutover_performed": False, **replay}


async def checkpoint_migrate(source: Path, destination: Path, owners: dict, crypto):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    if not crypto.enabled:
        raise ValueError("Checkpoint migration requires data keys")
    # Clone source to memory, avoiding AsyncSqliteSaver setup/WAL changes to the
    # source. SQLite's backup API includes committed WAL pages consistently.
    import aiosqlite

    source_connection = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    memory = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        source_connection.backup(memory)
    finally:
        source_connection.close()
    connection = aiosqlite.Connection(lambda: memory, iter_chunk_size=64)
    await connection
    raw = AsyncSqliteSaver(connection)
    raw.is_setup = True
    rows = [item async for item in raw.alist(None)]
    threads = {item.config["configurable"]["thread_id"] for item in rows}
    if not all(owners.get(thread) for thread in threads):
        await connection.close()
        raise ValueError("Owner map must cover every checkpoint thread")
    secured_source = SecureCheckpointSaver(raw, crypto, owners.get)
    decoded = [secured_source._unseal_tuple(item) if PAYLOAD_CHANNEL in item.checkpoint.get("channel_values", {}) else item for item in rows]
    await connection.close()
    with _new_file(destination):
        pass
    count = 0
    try:
        async with AsyncSqliteSaver.from_conn_string(str(destination)) as target:
            await target.setup()
            secured = SecureCheckpointSaver(target, crypto, owners.get)
            for item in reversed(decoded):
                config = item.parent_config or {"configurable": {
                    "thread_id": item.config["configurable"]["thread_id"],
                    "checkpoint_ns": item.config["configurable"].get("checkpoint_ns", ""),
                }}
                new_config = await secured.aput(config, item.checkpoint, item.metadata, item.checkpoint.get("channel_versions", {}))
                by_task = {}
                for task_id, channel, value in item.pending_writes or []:
                    by_task.setdefault(task_id, []).append((channel, value))
                for task_id, writes in by_task.items():
                    await secured.aput_writes(new_config, writes, task_id)
                readback = await secured.aget_tuple(new_config)
                if readback.checkpoint != item.checkpoint or readback.metadata != item.metadata or readback.pending_writes != item.pending_writes:
                    raise ValueError("Checkpoint round-trip verification failed")
                count += 1
        with closing(sqlite3.connect(destination)) as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Migrated checkpoint integrity failed")
    except Exception:
        # Partial destination is deliberately retained for operator inspection;
        # it must never be used to replace source. No source mutation occurred.
        raise RuntimeError("Migration incomplete; discard the partial destination and retry to a new path") from None
    return {"checkpoints_verified": count, "threads": len(threads), "active_key": crypto.active_key,
            "source_unchanged": True, "cutover_performed": False}


def application_migrate(source: Path, destination: Path, owners: dict, crypto):
    """Rebuild in a fresh file, encrypting before insertion (no plaintext pages).

    Unsupported historical standalone wrapper/decode/user rows intentionally stop
    the migration instead of copying private plaintext or silently discarding it.
    """
    from sqlalchemy import create_engine
    from app.database import Base
    from app.models import account, models, profile  # noqa: F401 — register tables
    from app.models import legacy_suggestions  # noqa: F401
    from app.services import profile_bridge, runtime_limits  # noqa: F401 — register tables
    from app.services.schema_migrations import migrate_schema

    if not crypto.enabled:
        raise ValueError("Application migration requires encryption keys")
    source_engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True))
    # Reflect only against read-only source; no schema mutation or default DB.
    from sqlalchemy import MetaData, select
    source_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)
    try:
        with source_engine.connect() as connection:
            source_rows = {table.name: [dict(row._mapping) for row in connection.execute(select(table))]
                           for table in source_metadata.sorted_tables}
    finally:
        source_engine.dispose()
    for name in ("users", "wrapper_records", "decode_records"):
        if source_rows.get(name):
            raise ValueError("Historical standalone records need a separately reviewed owner migration")
    unknown = set(source_rows) - set(Base.metadata.tables)
    if any(source_rows[name] for name in unknown):
        raise ValueError("Source has unknown populated tables; explicit migration policy required")
    conversation_owners = {row["session_id"]: row["owner_hash"] for row in source_rows.get("conversations", [])}
    counts = {}
    prepared = {}

    def text_value(value, *, owner, record, field):
        value = value if value is not None else ""
        plain = crypto.decrypt_text(value, owner=owner, record=record, field=field) if crypto.is_encrypted(value) else value
        if not isinstance(plain, str):
            raise ValueError("Expected text field")
        return crypto.encrypt_text(plain, owner=owner, record=record, field=field)

    for table in Base.metadata.sorted_tables:
        rows = []
        for original in source_rows.get(table.name, []):
            row = dict(original)
            if table.name == "resume_sessions":
                session_id = row["session_id"]
                owner = row.get("owner_key") or conversation_owners.get(session_id) or owners.get(session_id)
                if not owner:
                    raise ValueError("Every legacy resume must have a verified storage owner")
                row["owner_key"] = owner
                row["version"] = row.get("version") or 1
                value = row.get("resume_data") or {}
                if isinstance(value, str):
                    value = json.loads(value)
                if value is None:
                    value = {}
                if crypto.is_encrypted(value):
                    value = crypto.decrypt_json(value, owner=owner, record=session_id, field="resume_data")
                if not isinstance(value, dict):
                    raise ValueError("Resume JSON must be an object")
                row["resume_data"] = crypto.encrypt_json(value, owner=owner, record=session_id, field="resume_data")
                row["resume_draft"] = text_value(row.get("resume_draft"), owner=owner, record=session_id, field="resume_draft")
                state = row.get("resume_state") or {}
                if isinstance(state, str):
                    state = json.loads(state)
                if crypto.is_encrypted(state):
                    state = crypto.decrypt_json(state, owner=owner, record=session_id, field="resume_state")
                if not isinstance(state, dict):
                    raise ValueError("Resume state JSON must be an object")
                row["resume_state"] = crypto.encrypt_json(state, owner=owner, record=session_id, field="resume_state")
            elif table.name == "conversations":
                row["title"] = text_value(row.get("title") or "新对话", owner=row["owner_hash"], record=row["session_id"], field="title")
            elif table.name == "accounts":
                row["email_ciphertext"] = text_value(row["email_ciphertext"], owner="account:" + row["id"], record=row["id"], field="email")
            elif table.name == "resume_suggestions":
                value = row.get("payload") or {}
                if isinstance(value, str):
                    value = json.loads(value)
                if crypto.is_encrypted(value):
                    value = crypto.decrypt_json(value, owner=row["owner"], record=row["id"], field="suggestion")
                row["payload"] = crypto.encrypt_json(value, owner=row["owner"], record=row["id"], field="suggestion")
            elif table.name.startswith("profile_") and "payload" in row:
                row["payload"] = text_value(row["payload"], owner="account:" + row["account_id"], record=row["id"], field="payload")
            rows.append(row)
        prepared[table.name] = rows
    # No destination is created until all existing ciphertext authenticates and
    # ownership/schema policy passes. The destination receives ciphertext only.
    with _new_file(destination):
        pass
    engine = create_engine(f"sqlite:///{destination}")
    try:
        migrate_schema(engine, allow_legacy=True)
        with engine.begin() as connection:
            # Schema bootstrap now records its own supported version. Preserve
            # that row even when the legacy source has no version table, and
            # avoid inserting a duplicate component key during rotation.
            schema_table = Base.metadata.tables.get("schema_versions")
            if schema_table is not None:
                bootstrap = [dict(row._mapping) for row in connection.execute(select(schema_table))]
                existing = {row["component"]: row for row in prepared["schema_versions"]}
                for row in bootstrap:
                    old = existing.get(row["component"])
                    known_upgrade = (row["component"] == "product_profile" and old is not None
                                     and old["version"] == 1 and row["version"] == 2)
                    if old is not None and old["version"] != row["version"] and not known_upgrade:
                        raise ValueError("Unsupported source schema version")
                    existing[row["component"]] = row
                prepared["schema_versions"] = list(existing.values())
                connection.execute(schema_table.delete())
            for table in Base.metadata.sorted_tables:
                rows = prepared[table.name]
                if rows:
                    connection.execute(table.insert(), rows)
                counts[table.name] = len(rows)
        with engine.connect() as connection:
            for table in Base.metadata.sorted_tables:
                readback = [dict(row._mapping) for row in connection.execute(select(table))]
                if len(readback) != counts[table.name]:
                    raise ValueError("Application row-count verification failed")
                # Compare every persisted cell; defaults only fill newly added columns.
                by_key = {tuple(row[column.name] for column in table.primary_key): row for row in readback}
                for row in prepared[table.name]:
                    actual = by_key[tuple(row[column.name] for column in table.primary_key)]
                    if any(actual.get(name) != value for name, value in row.items()):
                        raise ValueError("Application content verification failed")
        with closing(sqlite3.connect(destination)) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Application integrity check failed")
    except Exception:
        raise RuntimeError("Application migration incomplete; discard the partial destination and retry to a new path") from None
    finally:
        engine.dispose()
    return {"tables_verified": counts, "active_key": crypto.active_key, "source_unchanged": True, "cutover_performed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["check-keys", "backup", "privacy-export", "restore", "checkpoint-migrate", "application-migrate"])
    parser.add_argument("--source", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--owner-map", type=Path)
    parser.add_argument("--application-state", type=Path, help="Paired application copy for checkpoint backup privacy baseline")
    parser.add_argument("--privacy-state", type=Path, help="Latest independently held encrypted privacy state")
    parser.add_argument("--privacy-sha256", help="Latest trusted digest from a separate controlled location")
    parser.add_argument("--discard-all-conversations", action="store_true", help="Conservatively discard all old chat/checkpoint content")
    args = parser.parse_args()
    # Explicit environment only: avoid reading developer .env/model credentials.
    settings = Settings(_env_file=None)
    crypto = crypto_from_settings(settings)
    # Any lazily imported ORM modules must use the same environment-only
    # settings; importing database.py must not read backend/.env implicitly.
    import app.config

    app.config.get_settings = lambda: settings
    if args.command == "check-keys":
        if not crypto.enabled:
            raise ValueError("Secure operations require configured encryption keys")
        marker = os.urandom(32)
        encrypted = crypto.encrypt_bytes(marker, **BACKUP_CONTEXT)
        assert crypto.decrypt_bytes(encrypted, **BACKUP_CONTEXT) == marker
        result = {"keyring_valid": True, "active_key": crypto.active_key, "retained_key_ids": sorted(crypto.keys)}
    else:
        if not args.source or not args.destination or not args.source.is_file():
            parser.error("--source existing-file and --destination new-file are required")
        if args.destination.exists() or args.destination.resolve() == args.source.resolve():
            parser.error("Destination must be a new file distinct from source")
        if args.command == "backup":
            result = backup(args.source, args.destination, crypto, application_state=args.application_state)
        elif args.command == "privacy-export":
            result = privacy_export(args.source, args.destination, crypto)
        elif args.command == "restore":
            result = restore(args.source, args.destination, crypto, privacy_state=args.privacy_state,
                             privacy_sha256=args.privacy_sha256, discard_all_conversations=args.discard_all_conversations)
        elif args.command == "checkpoint-migrate":
            if not args.owner_map:
                parser.error("--owner-map is required")
            result = asyncio.run(checkpoint_migrate(args.source, args.destination, json.loads(args.owner_map.read_text()), crypto))
        else:
            result = application_migrate(args.source, args.destination,
                                         json.loads(args.owner_map.read_text()) if args.owner_map else {}, crypto)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not log encrypted payloads, keys, source records or traceback locals.
        print(f"Security operation failed ({type(exc).__name__}); source was not modified", file=sys.stderr)
        raise SystemExit(1) from None
