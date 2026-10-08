"""Task selection contract; isolated router, no lifespan, database or live LLM."""

import sys
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api import chat  # noqa: E402
from app.schemas.chat import ChatRequest  # noqa: E402


@asynccontextmanager
async def _isolated_lock(_session_id):
    yield


class SkillRequestContractTest(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(chat.router, prefix="/api/chat")
        self.messages = [{"role": "user", "content": "这段经历怎么写？"}]

    def test_default_task_remains_auto(self):
        req = ChatRequest(messages=self.messages)
        self.assertEqual(req.task, "auto")

    def test_task_accepts_only_supported_names(self):
        for task in ("auto", "decode_jd", "rewrite_experience", "review_resume"):
            with self.subTest(task=task):
                self.assertEqual(
                    ChatRequest(messages=self.messages, task=task).task, task
                )
        for task in ("rewrite", "unknown", "", None):
            with self.subTest(task=task), self.assertRaises(ValidationError):
                ChatRequest(messages=self.messages, task=task)

    def test_invalid_task_returns_422_before_getting_model(self):
        with patch.object(chat, "_get_llm") as get_llm, TestClient(self.app) as client:
            response = client.post(
                "/api/chat/stream", json={"messages": self.messages, "task": "unknown"}
            )
        self.assertEqual(response.status_code, 422)
        get_llm.assert_not_called()

    def _submit_with_mocked_storage(self, task=None):
        llm = object()

        async def tokens(*_args, **_kwargs):
            yield "已选择任务"

        stream = Mock(side_effect=tokens)
        payload = {"messages": self.messages, "session_id": "isolated-skill-test"}
        if task is not None:
            payload["task"] = task
        with (
            patch.object(chat, "_get_llm", return_value=llm),
            patch.object(chat, "resolve_owner", return_value="unit-owner"),
            patch.object(chat, "authorize_session", return_value="unit-owner"),
            patch.object(chat, "reserve_turn"),
            patch.object(chat, "get_graph", return_value=object()),
            patch.object(chat, "prepare_graph_context", AsyncMock()),
            patch.object(chat, "session_lock", side_effect=_isolated_lock),
            patch.object(chat, "session_is_blocked", return_value=False),
            patch.object(chat, "session_can_read_checkpoint", return_value=True),
            patch.object(chat, "ensure_resume_session", return_value=True),
            patch.object(chat, "touch_conversation"),
            patch.object(chat, "load_resume_session", return_value=None),
            patch.object(chat, "stream_agent", stream),
            patch.object(
                chat,
                "_session_meta",
                AsyncMock(return_value={"type": "meta", "has_data": False}),
            ),
            TestClient(self.app) as client,
        ):
            response = client.post("/api/chat/stream", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("已选择任务", response.text)
        self.assertIn("data: [DONE]", response.text)
        return stream, llm

    def test_default_and_explicit_auto_keep_three_argument_call(self):
        for task in (None, "auto"):
            with self.subTest(task=task):
                stream, llm = self._submit_with_mocked_storage(task)
                stream.assert_called_once_with(
                    self.messages, "isolated-skill-test", llm
                )

    def test_each_explicit_task_is_forwarded_to_agent(self):
        for task in ("decode_jd", "rewrite_experience", "review_resume"):
            with self.subTest(task=task):
                stream, llm = self._submit_with_mocked_storage(task)
                stream.assert_called_once_with(
                    self.messages, "isolated-skill-test", llm, task=task
                )


if __name__ == "__main__":
    unittest.main()
