"""Error code classification; openai SDK exception doubles, no network."""
import json
import logging
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch
import unittest

import httpx
import openai

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.resume_graph import stream_agent  # noqa: E402
from app.services.error_codes import ChatTurnError, MESSAGES, classify_error  # noqa: E402

import test_product_security_flow as harness  # noqa: E402
from app.api import chat  # noqa: E402

SECRET = "PRIVATE-PROVIDER-TEXT dashscope sk-secret https://api.example-vendor.com/v1"
REQUEST = httpx.Request("POST", "https://api.example-vendor.com/v1/chat/completions")


def status_error(status, body):
    response = httpx.Response(status, request=REQUEST, json=body)
    cls = {401: openai.AuthenticationError, 403: openai.PermissionDeniedError,
           429: openai.RateLimitError}.get(status, openai.APIStatusError)
    return cls(SECRET, response=response, body=body)


CASES = {
    "E-MODEL-QUOTA": [status_error(400, {"code": "Arrearage", "message": SECRET}),
                      status_error(402, {"message": SECRET}),
                      status_error(429, {"code": "insufficient_quota", "message": SECRET}),
                      status_error(400, {"type": "insufficient_balance", "message": SECRET})],
    "E-MODEL-AUTH": [status_error(401, {"message": SECRET}), status_error(403, {"message": SECRET})],
    "E-MODEL-RATE": [status_error(429, {"message": SECRET})],
    "E-MODEL-TIMEOUT": [openai.APITimeoutError(request=REQUEST), TimeoutError(SECRET)],
    "E-MODEL-NETWORK": [openai.APIConnectionError(message=SECRET, request=REQUEST)],
    "E-MODEL-UPSTREAM": [status_error(500, {"message": SECRET}), status_error(503, {"message": SECRET}),
                         status_error(400, {"message": SECRET})],
    "E-INTERNAL": [ValueError(SECRET), RuntimeError(SECRET)],
}


def wrapped(exc, depth=3):
    for _ in range(depth):
        try:
            try:
                raise exc
            except Exception as inner:
                raise RuntimeError("wrapper " + SECRET) from inner
        except RuntimeError as outer:
            exc = outer
    return exc


class ClassifyErrorTest(unittest.TestCase):
    def test_every_code_direct_and_wrapped_without_leaking(self):
        for code, errors in CASES.items():
            for error in errors:
                for candidate in (error, wrapped(error)):
                    with self.subTest(code=code, error=type(error).__name__):
                        got, message = classify_error(candidate)
                        self.assertEqual(got, code)
                        self.assertEqual(message, MESSAGES[code])
                        for leak in ("PRIVATE", "dashscope", "sk-", "http", "Arrearage", "wrapper"):
                            self.assertNotIn(leak, message)

    def test_context_chain_without_explicit_cause(self):
        try:
            try:
                raise status_error(401, {"message": SECRET})
            except Exception:
                raise RuntimeError("boom")
        except RuntimeError as error:
            self.assertEqual(classify_error(error)[0], "E-MODEL-AUTH")


class StreamAgentTest(unittest.IsolatedAsyncioTestCase):
    async def test_stream_agent_raises_coded_error_and_logs_no_body(self):
        class Graph:
            async def astream(self, *args, **kwargs):
                raise wrapped(status_error(400, {"code": "Arrearage", "message": SECRET}), 1)
                yield  # pragma: no cover

        with patch("app.agents.resume_graph.get_graph", return_value=Graph()), \
                self.assertLogs("app.agents.resume_graph", level=logging.ERROR) as logs:
            with self.assertRaises(ChatTurnError) as caught:
                async for _ in stream_agent([{"content": "你好"}], "coded-error", object()):
                    pass
        self.assertEqual(caught.exception.code, "E-MODEL-QUOTA")
        self.assertEqual(str(caught.exception), MESSAGES["E-MODEL-QUOTA"])
        logged = "\n".join(logs.output)
        self.assertIn("code=E-MODEL-QUOTA", logged)
        self.assertIn("error_type=APIStatusError", logged)
        self.assertIn("status_code=400", logged)
        for leak in ("PRIVATE", "Arrearage", "sk-secret", "example-vendor"):
            self.assertNotIn(leak, logged)


class ChatSseErrorTest(harness.ProductSecurityFlow):
    """Reuse the product harness; only the SSE error tests run here."""

    async def stream_with(self, failure):
        sid, _ = await self.fixture()

        async def tokens(*args, **kwargs):
            raise failure
            yield  # pragma: no cover

        with patch.object(chat, "_get_llm", return_value=object()), \
                patch.object(chat, "stream_agent", side_effect=tokens), \
                patch.object(chat, "reserve_turn"), \
                patch.object(chat, "_session_meta", AsyncMock(return_value={"type": "meta"})), \
                self.assertLogs("app.api.chat", level=logging.WARNING) as logs:
            response = await self.a.post("/api/chat/stream", json={
                "session_id": sid, "messages": [{"role": "user", "content": "你好"}]})
        events = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith("data: {")]
        return events, "\n".join(logs.output)

    async def test_sse_error_carries_code(self):
        for code, error in (("E-MODEL-QUOTA", wrapped(status_error(400, {"code": "Arrearage"}))),
                            ("E-MODEL-TIMEOUT", TimeoutError(SECRET)),
                            ("E-MODEL-AUTH", ChatTurnError("E-MODEL-AUTH")),
                            ("E-INTERNAL", ValueError(SECRET))):
            with self.subTest(code=code):
                events, logged = await self.stream_with(error)
                errors = [e for e in events if "error" in e]
                self.assertEqual(errors, [{"error": MESSAGES[code], "code": code}])
                self.assertIn(f"code={code}", logged)
                self.assertNotIn("PRIVATE", logged)


for _name in list(vars(harness.ProductSecurityFlow)):
    if _name.startswith("test_") and _name not in vars(ChatSseErrorTest):
        setattr(ChatSseErrorTest, _name, None)


if __name__ == "__main__":
    unittest.main()
