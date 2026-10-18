"""Opt-in local replay server; instrumentation is never imported by production."""
import argparse
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
COUNTS = ContextVar("persona_model_counts", default=None)
CALL_SCOPE = "httpx_chat_completions_responses_attempts"


def inspect_request(request):
    if request.method != "POST" or not request.url.path.rstrip("/").endswith(("/chat/completions", "/responses")):
        return
    from app.services.model_privacy import ContactRedactor
    counts = COUNTS.get()
    # Inspect decoded JSON, including reasoning/tool arguments. Never retain it.
    body = json.dumps(json.loads(request.content), ensure_ascii=False)
    if ContactRedactor().redact(body) != body:
        if counts is not None:
            counts["privacy_blocks"] += 1
        raise ValueError("contacts_in_model_request")
    if counts is not None:
        counts["model_calls"] += 1


@contextmanager
def model_meter():
    import httpx
    async_send, sync_send = httpx.AsyncClient.send, httpx.Client.send

    async def counted_async(client, request, *args, **kwargs):
        inspect_request(request)
        return await async_send(client, request, *args, **kwargs)

    def counted_sync(client, request, *args, **kwargs):
        inspect_request(request)
        return sync_send(client, request, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "send", counted_async), patch.object(httpx.Client, "send", counted_sync):
        yield


class ReplayApp:
    def __init__(self, app, agent_mode):
        self.app = app
        self.agent_mode = agent_mode

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["path"] == "/_evaluation/config":
            payload = json.dumps({"schema_version": 1, "agent_mode": self.agent_mode,
                                  "model_call_scope": CALL_SCOPE}).encode()
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": payload})
            return
        if scope["path"] != "/api/chat/stream" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        counts = {"model_calls": 0, "privacy_blocks": 0}
        token = COUNTS.set(counts)
        started, pending, emitted, streaming = time.monotonic(), b"", False, False

        async def emit_metrics():
            nonlocal emitted
            metrics = {"type": "evaluation_metrics", "agent_mode": self.agent_mode,
                       "model_call_scope": CALL_SCOPE, **counts,
                       "server_seconds": round(time.monotonic() - started, 4)}
            await send({"type": "http.response.body", "more_body": True,
                        "body": b"data: " + json.dumps(metrics).encode() + b"\n\n"})
            emitted = True

        async def measured_send(message):
            nonlocal pending, emitted, streaming
            if message["type"] == "http.response.start":
                streaming = any(k.lower() == b"content-type" and b"text/event-stream" in v
                                for k, v in message.get("headers", []))
                await send(message)
                return
            if not streaming or message["type"] != "http.response.body":
                await send(message)
                return
            pending += message.get("body", b"")
            # Frame buffering also handles a [DONE] split over ASGI chunks.
            while b"\n\n" in pending or b"\r\n\r\n" in pending:
                separator = b"\r\n\r\n" if b"\r\n\r\n" in pending and (
                    b"\n\n" not in pending or pending.index(b"\r\n\r\n") < pending.index(b"\n\n")) else b"\n\n"
                frame, pending = pending.split(separator, 1)
                if b"data: [DONE]" in frame and not emitted:
                    await emit_metrics()
                await send({"type": "http.response.body", "body": frame + separator, "more_body": True})
            if not message.get("more_body", False):
                if not emitted:
                    await emit_metrics()  # Keep failure costs without inventing [DONE].
                await send({"type": "http.response.body", "body": pending, "more_body": False})
                pending = b""

        try:
            await self.app(scope, receive, measured_send)
        finally:
            COUNTS.reset(token)


def configured_mode(settings, requested):
    actual = getattr(settings, "AGENT_MODE", "off")
    if actual != requested:
        raise ValueError("Server AGENT_MODE differs; merge P1b before loop replay")
    return actual


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-mode", choices=("off", "loop"), required=True)
    parser.add_argument("--port", type=int, default=8847)
    parser.add_argument("--data-dir", type=Path, required=True, help="New isolated directory; refuses reuse")
    args = parser.parse_args(argv)
    if args.port in {8833, 8834} or not 1024 <= args.port <= 65535:
        parser.error("Use a dedicated replay port, excluding 8833/8834")
    directory = args.data_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    os.environ.update({"AGENT_MODE": args.agent_mode, "APP_ENV": "local",
                       "DATABASE_URL": "sqlite:///" + str(directory / "application.sqlite3"),
                       "CHECKPOINT_DB_PATH": str(directory / "checkpoints.sqlite3"),
                       "ALLOW_INSECURE_LOCAL_STORAGE": "true", "REQUIRE_ACCOUNT": "false",
                       "AUTH_COOKIE_SECURE": "false", "ENABLE_RAG": "false"})
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import get_settings
    mode = configured_mode(get_settings(), args.agent_mode)
    import uvicorn
    with model_meter():
        from main import app
        uvicorn.run(ReplayApp(app, mode), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
