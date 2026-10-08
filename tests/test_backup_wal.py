"""WAL-backed offline backups retain committed data without mutating sources."""

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from test_backup_privacy_restore import create_checkpoints, create_fixture, operations, DataCrypto


class BackupWALTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="huhua-backup-wal-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.crypto = DataCrypto({"test": os.urandom(32)}, "test")

    def assert_integrity(self, connection):
        self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_snapshot_reads_committed_wal_only_and_leaves_source_unchanged(self):
        source = self.root / "wal.sqlite3"
        with closing(sqlite3.connect(source)) as writer:
            self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("CREATE TABLE contents (value TEXT)")
            writer.commit()
            writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            writer.execute("INSERT INTO contents VALUES ('COMMITTED_WAL_ONLY')")
            writer.commit()
            wal = Path(str(source) + "-wal")
            self.assertGreater(wal.stat().st_size, 0)
            # Immutable mode ignores WAL. Its empty table proves this marker is
            # not present in the main file and must be read via SQLite backup.
            with closing(sqlite3.connect(source.as_uri() + "?immutable=1", uri=True)) as disk_only:
                self.assertEqual(disk_only.execute("SELECT count(*) FROM contents").fetchone()[0], 0)
            writer.execute("INSERT INTO contents VALUES ('UNCOMMITTED_SHOULD_NOT_BACK_UP')")
            before = source.read_bytes(), wal.read_bytes()
            snapshot = operations._sqlite_snapshot(source)
            with closing(sqlite3.connect(":memory:")) as restored:
                restored.deserialize(snapshot)
                self.assert_integrity(restored)
                self.assertEqual(restored.execute("SELECT value FROM contents").fetchall(), [("COMMITTED_WAL_ONLY",)])
            self.assertEqual((source.read_bytes(), wal.read_bytes()), before)
            self.assertEqual(writer.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            writer.rollback()

    def test_wal_application_checkpoint_and_privacy_backups_round_trip_with_trust_anchor(self):
        application = self.root / "app.sqlite3"
        checkpoint = self.root / "checkpoint.sqlite3"
        create_fixture(application, self.crypto)
        create_checkpoints(checkpoint)
        with closing(sqlite3.connect(application)) as app_writer, closing(sqlite3.connect(checkpoint)) as graph_writer:
            for writer in (app_writer, graph_writer):
                self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            draft = self.crypto.encrypt_text("LATEST_WAL_RESUME", owner="account:a", record="session_a", field="resume_draft")
            app_writer.execute("UPDATE resume_sessions SET resume_draft=?,version=version+1 WHERE session_id='session_a'", (draft,))
            app_writer.commit()
            graph_writer.execute("UPDATE checkpoints SET checkpoint=? WHERE thread_id='session_a'", (b"LATEST_WAL_CHECKPOINT",))
            graph_writer.execute("INSERT INTO writes VALUES ('session_a','checkpoint_a',?)", (b"LATEST_WAL_PENDING_WRITE",))
            graph_writer.commit()
            source_paths = (application, Path(str(application) + "-wal"), checkpoint, Path(str(checkpoint) + "-wal"))
            before = {path: path.read_bytes() for path in source_paths}
            app_backup = self.root / "app.encrypted"
            checkpoint_backup = self.root / "checkpoint.encrypted"
            app_result = operations.backup(application, app_backup, self.crypto)
            graph_result = operations.backup(checkpoint, checkpoint_backup, self.crypto, application_state=application)
            self.assertEqual(app_result["storage_kind"], "application")
            self.assertEqual(graph_result["storage_kind"], "checkpoint")
            self.assertTrue(graph_result["privacy_baseline_attached"])
            privacy = self.root / "privacy.encrypted"
            privacy_result = operations.privacy_export(application, privacy, self.crypto)
            for artifact in (app_backup, checkpoint_backup, privacy):
                self.assertNotIn(b"LATEST_WAL_", artifact.read_bytes())
                self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(app_backup.read_text())["format"], "huhua-sqlite-backup-v2")
            refused = self.root / "missing-anchor.sqlite3"
            with self.assertRaises(ValueError):
                operations.restore(checkpoint_backup, refused, self.crypto)
            self.assertFalse(refused.exists())
            restored_app = self.root / "restored-app.sqlite3"
            restored_graph = self.root / "restored-checkpoint.sqlite3"
            for backup_path, destination in ((app_backup, restored_app), (checkpoint_backup, restored_graph)):
                result = operations.restore(backup_path, destination, self.crypto,
                                            privacy_state=privacy, privacy_sha256=privacy_result["trusted_sha256"])
                self.assertEqual(result["retained_conversations"], 2)
                self.assertEqual(result["discarded_conversations"], 0)
                self.assertFalse(result["cutover_performed"])
            with closing(sqlite3.connect(restored_app)) as db:
                self.assert_integrity(db)
                saved = db.execute("SELECT resume_draft FROM resume_sessions WHERE session_id='session_a'").fetchone()[0]
                self.assertEqual(self.crypto.decrypt_text(saved, owner="account:a", record="session_a", field="resume_draft"), "LATEST_WAL_RESUME")
            with closing(sqlite3.connect(restored_graph)) as db:
                self.assert_integrity(db)
                self.assertEqual(db.execute("SELECT checkpoint FROM checkpoints WHERE thread_id='session_a'").fetchone()[0], b"LATEST_WAL_CHECKPOINT")
                self.assertIn((b"LATEST_WAL_PENDING_WRITE",), db.execute("SELECT value FROM writes WHERE thread_id='session_a'").fetchall())
            self.assertEqual({path: path.read_bytes() for path in source_paths}, before)
            self.assertEqual(app_writer.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(graph_writer.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_rollback_journal_snapshot_remains_readable(self):
        source = self.root / "rollback.sqlite3"
        with closing(sqlite3.connect(source)) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode=DELETE").fetchone()[0], "delete")
            db.execute("CREATE TABLE contents (value TEXT)")
            db.execute("INSERT INTO contents VALUES ('ROLLBACK_MARKER')")
            db.commit()
        before = source.read_bytes()
        with closing(sqlite3.connect(":memory:")) as restored:
            restored.deserialize(operations._sqlite_snapshot(source))
            self.assert_integrity(restored)
            self.assertEqual(restored.execute("SELECT value FROM contents").fetchall(), [("ROLLBACK_MARKER",)])
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
