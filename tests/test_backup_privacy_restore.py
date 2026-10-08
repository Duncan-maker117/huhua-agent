"""Backup privacy replay uses synthetic encrypted records and new temporary DBs."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402
with patch("app.config.get_settings", return_value=Settings(_env_file=None, DATABASE_URL="sqlite:///:memory:", LLM_API_KEY="")):
    from app.database import Base
    from app.models import account, models, profile  # noqa: F401
    from app.services.data_crypto import DataCrypto, DataDecryptionError
    from app.services import profile_bridge, resume_suggestions, runtime_limits  # noqa: F401

spec = importlib.util.spec_from_file_location("privacy_recovery_operations", ROOT / "backend/scripts/security_migrate.py")
operations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operations)


def create_fixture(path, crypto):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with engine.begin() as db:
        for owner_id in ("a", "b"):
            owner, session, source = "account:" + owner_id, "session_" + owner_id, "source_" + owner_id
            def seal(value, record, field="payload"):
                return crypto.encrypt_text(json.dumps(value), owner=owner, record=record, field=field)
            db.execute(account.Account.__table__.insert().values(
                id=owner_id, email_index=hashlib.sha256(owner_id.encode()).hexdigest(),
                email_ciphertext=crypto.encrypt_text(f"{owner_id}@example.test", owner=owner, record=owner_id, field="email")))
            db.execute(models.ResumeSession.__table__.insert().values(
                session_id=session, owner_key=owner, version=1, stage="BUILDING",
                resume_data=crypto.encrypt_json({"basic_info": {"name": "PRIVATE_OLD_" + owner_id}}, owner=owner, record=session, field="resume_data"),
                resume_draft=crypto.encrypt_text("PRIVATE_OLD_" + owner_id, owner=owner, record=session, field="resume_draft")))
            db.execute(models.Conversation.__table__.insert().values(
                session_id=session, owner_hash=owner, version=1,
                title=crypto.encrypt_text("PRIVATE_TITLE_" + owner_id, owner=owner, record=session, field="title")))
            db.execute(profile.PersonalProfile.__table__.insert().values(id="profile_" + owner_id, account_id=owner_id, revision=1))
            db.execute(profile.ProfileFact.__table__.insert().values(
                id="fact_" + owner_id, account_id=owner_id, slot_key=hashlib.sha256(owner_id.encode()).hexdigest(),
                category="basic", revision=1, status="active",
                payload=seal({"subject": "本人", "field": "name", "value": "PRIVATE_OLD_" + owner_id, "source_ids": [source]}, "fact_" + owner_id)))
            db.execute(profile.ProfileSource.__table__.insert().values(
                id=source, account_id=owner_id, source_key=hashlib.sha256(source.encode()).hexdigest(),
                session_id=session, kind="self", disabled=False,
                payload=seal({"human_text": "PRIVATE_OLD_" + owner_id, "original_source_id": "message_" + owner_id}, source)))
            db.execute(profile.ProfileArchiveEvent.__table__.insert().values(
                id="event_" + owner_id, account_id=owner_id, source_id=source, event_type="human_message",
                status="pending", attempts=0, error_code="", payload=seal({"source_id": source}, "event_" + owner_id)))
    engine.dispose()


def create_checkpoints(path):
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE checkpoints (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT, checkpoint BLOB)")
        db.execute("CREATE TABLE writes (thread_id TEXT, checkpoint_id TEXT, value BLOB)")
        for key in ("a", "b"):
            db.execute("INSERT INTO checkpoints VALUES (?,?,?,?)", ("session_" + key, "", "checkpoint_" + key, ("PRIVATE_CHECKPOINT_" + key).encode()))
            db.execute("INSERT INTO writes VALUES (?,?,?)", ("session_" + key, "checkpoint_" + key, ("PRIVATE_WRITE_" + key).encode()))
        db.commit()


class PrivacyRestoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="huhua-privacy-restore-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.crypto = DataCrypto({"key": os.urandom(32)}, "key")
        self.app = self.root / "current.sqlite3"
        create_fixture(self.app, self.crypto)
        self.app_backup = self.root / "application.encrypted"
        operations.backup(self.app, self.app_backup, self.crypto)
        self.checkpoints = self.root / "checkpoints.sqlite3"
        create_checkpoints(self.checkpoints)
        self.checkpoint_backup = self.root / "checkpoint.encrypted"
        operations.backup(self.checkpoints, self.checkpoint_backup, self.crypto, application_state=self.app)

    def export_latest(self):
        self.privacy = self.root / "latest-privacy.encrypted"
        result = operations.privacy_export(self.app, self.privacy, self.crypto)
        self.digest = result["trusted_sha256"]
        self.assertNotIn(b"PRIVATE_OLD", self.privacy.read_bytes())
        return result

    def restore(self, backup=None, *, destination="restored.sqlite3", **kwargs):
        return operations.restore(backup or self.app_backup, self.root / destination, self.crypto,
                                  privacy_state=self.privacy, privacy_sha256=self.digest, **kwargs)

    def change_fact(self, *, delete=False):
        value = {} if delete else {"subject": "本人", "field": "name", "value": "PRIVATE_CORRECTED_a", "source_ids": []}
        sealed = self.crypto.encrypt_text(json.dumps(value), owner="account:a", record="fact_a", field="payload")
        invalid = self.crypto.encrypt_text(json.dumps({"value": "PRIVATE_OLD_a"}), owner="account:a", record="invalidation_a", field="payload")
        with closing(sqlite3.connect(self.app)) as db:
            db.execute("UPDATE profile_facts SET revision=2,status=?,payload=? WHERE id='fact_a'", ("deleted" if delete else "active", sealed))
            db.execute("INSERT INTO profile_invalidations(id,account_id,fact_id,revision,reason,payload,created_at) VALUES ('invalidation_a','a','fact_a',2,?,?,?)", ("deleted" if delete else "correction", invalid, "2026-10-04 00:00:00"))
            db.commit()

    def test_missing_or_wrong_trust_anchor_is_fail_closed_before_file_creation(self):
        self.export_latest()
        target = self.root / "refused.sqlite3"
        with self.assertRaises(ValueError):
            operations.restore(self.app_backup, target, self.crypto)
        with self.assertRaises(ValueError):
            operations.restore(self.app_backup, target, self.crypto, privacy_state=self.privacy, privacy_sha256="0" * 64)
        self.assertFalse(target.exists())
        tampered = bytearray(self.privacy.read_bytes())
        tampered[-10] ^= 1
        self.privacy.write_bytes(tampered)
        with self.assertRaises(ValueError):
            operations.restore(self.app_backup, target, self.crypto, privacy_state=self.privacy, privacy_sha256=self.digest)
        self.assertFalse(target.exists())

    def test_deleted_fact_replay_discards_only_affected_owner_history_and_stops_old_job(self):
        self.change_fact(delete=True)
        before = self.app.read_bytes()
        self.export_latest()
        result = self.restore()
        self.assertEqual(result["discarded_conversations"], 1)
        self.assertEqual(result["retained_conversations"], 1)
        self.assertEqual(result["affected_accounts"], 1)
        self.assertEqual(self.app.read_bytes(), before)
        with closing(sqlite3.connect(self.root / "restored.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT session_id FROM resume_sessions").fetchall(), [("session_b",)])
            status, payload = db.execute("SELECT status,payload FROM profile_facts WHERE id='fact_a'").fetchone()
            self.assertEqual(status, "deleted")
            self.assertEqual(json.loads(self.crypto.decrypt_text(payload, owner="account:a", record="fact_a", field="payload")), {})
            self.assertEqual(db.execute("SELECT disabled FROM profile_sources WHERE id='source_a'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT status FROM profile_archive_events WHERE id='event_a'").fetchone()[0], "skipped")
            self.assertEqual(db.execute("SELECT reason FROM profile_invalidations").fetchone()[0], "deleted")
        checkpoints = self.restore(self.checkpoint_backup, destination="restored-checkpoints.sqlite3")
        self.assertEqual(checkpoints["discarded_conversations"], 1)
        with closing(sqlite3.connect(self.root / "restored-checkpoints.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT thread_id FROM checkpoints").fetchall(), [("session_b",)])
            self.assertEqual(db.execute("SELECT thread_id FROM writes").fetchall(), [("session_b",)])
        self.assertNotIn(b"PRIVATE_CHECKPOINT_a", (self.root / "restored-checkpoints.sqlite3").read_bytes())
        self.assertNotIn(b"PRIVATE_WRITE_a", (self.root / "restored-checkpoints.sqlite3").read_bytes())

    def test_correction_and_session_deletion_replay_preserve_latest_fact(self):
        self.change_fact()
        with closing(sqlite3.connect(self.app)) as db:
            db.execute("DELETE FROM conversations WHERE session_id='session_b'")
            db.execute("DELETE FROM resume_sessions WHERE session_id='session_b'")
            db.commit()
        self.export_latest()
        result = self.restore()
        self.assertEqual(result["retained_conversations"], 0)
        with closing(sqlite3.connect(self.root / "restored.sqlite3")) as db:
            payload = db.execute("SELECT payload FROM profile_facts WHERE id='fact_a'").fetchone()[0]
            self.assertEqual(json.loads(self.crypto.decrypt_text(payload, owner="account:a", record="fact_a", field="payload"))["value"], "PRIVATE_CORRECTED_a")
        result = self.restore(self.checkpoint_backup, destination="restored-checkpoints.sqlite3")
        self.assertEqual(result["retained_conversations"], 0)

    def test_unknown_checkpoint_baseline_discards_all_with_explicit_counts(self):
        old = self.root / "checkpoint-without-baseline.encrypted"
        operations.backup(self.checkpoints, old, self.crypto)
        self.export_latest()
        result = self.restore(old)
        self.assertEqual(result["discarded_conversations"], 2)
        self.assertEqual(result["retained_conversations"], 0)
        self.assertIn("no_reliable_baseline", result["recovery_policy"])
        self.assertEqual(result["discarded_rows"], {"checkpoints": 2, "writes": 2})

    def test_changed_fact_master_alone_prevents_old_session_restore(self):
        state = self.crypto.encrypt_json({"authoritative": True, "collected_info": {"facts": []},
                                          "resume_meta": {}, "resume_versions": []},
                                         owner="account:a", record="session_a", field="resume_state")
        with closing(sqlite3.connect(self.app)) as db:
            # Same document and SQL version: digest must include the fact master.
            db.execute("UPDATE resume_sessions SET resume_state=? WHERE session_id='session_a'", (json.dumps(state),))
            db.commit()
        self.export_latest()
        result = self.restore()
        self.assertEqual(result["retained_conversations"], 1)
        with closing(sqlite3.connect(self.root / "restored.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT session_id FROM resume_sessions").fetchall(), [("session_b",)])

    def test_unchanged_accounts_retain_history_but_old_logins_are_removed(self):
        self.export_latest()
        result = self.restore()
        self.assertEqual(result["retained_conversations"], 2)
        self.assertTrue(result["old_logins_revoked"])
        result = self.restore(self.checkpoint_backup, destination="restored-checkpoints.sqlite3")
        self.assertEqual(result["retained_conversations"], 2)
        forced = self.restore(destination="discarded.sqlite3", discard_all_conversations=True)
        self.assertEqual(forced["retained_conversations"], 0)

    def test_key_loss_and_metadata_swapping_cannot_bypass_replay(self):
        self.export_latest()
        with self.assertRaises(DataDecryptionError):
            operations.restore(self.app_backup, self.root / "missing-key.sqlite3", DataCrypto({"new": os.urandom(32)}, "new"),
                               privacy_state=self.privacy, privacy_sha256=self.digest)
        checkpoint = json.loads(self.checkpoint_backup.read_text())
        checkpoint["metadata"] = json.loads(self.app_backup.read_text())["metadata"]
        swapped = self.root / "swapped.encrypted"
        swapped.write_text(json.dumps(checkpoint))
        with self.assertRaises(DataDecryptionError):
            self.restore(swapped)
        self.assertFalse((self.root / "restored.sqlite3").exists())

    def test_known_stale_snapshot_predating_backup_is_rejected(self):
        self.export_latest()
        later_backup = self.root / "later.encrypted"
        operations.backup(self.app, later_backup, self.crypto)
        with self.assertRaises(ValueError):
            self.restore(later_backup)
        self.assertFalse((self.root / "restored.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
