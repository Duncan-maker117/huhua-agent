import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
# Import-time safety, including when this module is run independently.
_IMPORT_DIRECTORY = tempfile.TemporaryDirectory(prefix="huhua-public-import-")
os.environ.update({"APP_ENV": "local", "ALLOW_INSECURE_LOCAL_STORAGE": "true",
                   "REQUIRE_ACCOUNT": "false", "LLM_API_KEY": "", "ENABLE_RAG": "false",
                   "DATABASE_URL": f"sqlite:///{Path(_IMPORT_DIRECTORY.name) / 'unused.sqlite3'}",
                   "CHECKPOINT_DB_PATH": str(Path(_IMPORT_DIRECTORY.name) / "unused-checkpoints.sqlite3")})
from app.config import get_settings  # noqa: E402
get_settings.cache_clear()

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from app.agents.editor_chain import _numbers  # noqa: E402
from app.services.resume_review import review_resume  # noqa: E402


class PublicBetaSmokeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="huhua-public-test-")
        self.environment = patch.dict(os.environ, {
            "APP_ENV": "local", "ALLOW_INSECURE_LOCAL_STORAGE": "true", "REQUIRE_ACCOUNT": "false",
            "LLM_API_KEY": "", "ENABLE_RAG": "false", "DATA_ENCRYPTION_KEYS": "{}", "DATA_ENCRYPTION_ACTIVE_KEY": "",
            "DATABASE_URL": f"sqlite:///{Path(self.directory.name) / 'sessions.sqlite3'}",
            "CHECKPOINT_DB_PATH": str(Path(self.directory.name) / "checkpoints.sqlite3"),
        })
        self.environment.start()
        get_settings.cache_clear()
        self.engine = create_engine(get_settings().DATABASE_URL, connect_args={"check_same_thread": False})
        self.factory = sessionmaker(bind=self.engine)
        self.patches = [patch("app.database.engine", self.engine), patch("main.engine", self.engine)]
        for module in ("app.database", "main", "app.services.session_store", "app.services.conversation_store",
                       "app.services.canonical_resume", "app.services.runtime_limits", "app.services.profile_bridge"):
            self.patches.append(patch(module + ".SessionLocal", self.factory))
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()
        self.environment.stop()
        get_settings.cache_clear()
        self.directory.cleanup()

    def create(self, client):
        response = client.post("/api/chat/conversations")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(client.cookies.get("huhua_workspace"))
        return response.json()["session_id"]

    def test_pages_render_and_docx_exports(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/healthz").status_code, 200)
            self.assertEqual(client.get("/").status_code, 200)
            self.create(client)
            sample = client.get("/api/resume/sample").json()
            rendered = client.post("/api/resume/render/t001-jianyue", json=sample)
            self.assertEqual(rendered.status_code, 200)
            exported = client.post("/api/resume/export/docx/t001-jianyue", json=sample)
            self.assertEqual(exported.status_code, 200)
            self.assertGreater(len(exported.content), 10_000)

    def test_missing_model_key_fails_cleanly_and_session_can_be_deleted(self):
        with TestClient(app) as client:
            session_id = self.create(client)
            self.assertEqual(client.get("/api/resume/current?session_id=missing").status_code, 404)
            current = client.get("/api/resume/current", params={"session_id": session_id})
            self.assertEqual(current.status_code, 200, current.text)
            self.assertFalse(current.json()["has_data"])
            chat = client.post(
                "/api/chat/stream",
                json={"session_id": session_id, "messages": [{"role": "user", "content": "你好"}]},
            )
            self.assertEqual(chat.status_code, 503)
            self.assertEqual(client.delete("/api/chat/session/test-delete").status_code, 404)
            deleted = client.delete(f"/api/chat/session/{session_id}")
            self.assertEqual(deleted.json(), {"deleted": True})
            self.assertEqual(client.get("/api/resume/current", params={"session_id": session_id}).status_code, 404)

    def test_review_is_evidence_based(self):
        data = {
            "basic_info": {"name": "张三", "email": "a@example.com"},
            "projects": [{"name": "项目 A", "description": "完成 50 条测试"}],
            "skills": ["Python"],
        }
        checks = review_resume(data, {"required_skills": ["Python", "FastAPI"]})
        self.assertTrue(any("FastAPI" in item for item in checks))
        self.assertEqual(_numbers("完成 50 条测试"), {"50"})
        self.assertEqual(_numbers("提升 80%"), {"80%"})


if __name__ == "__main__":
    unittest.main()
