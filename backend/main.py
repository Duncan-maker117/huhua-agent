import asyncio
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.api import account, chat, conversations, profile, resume, resume_changes
from app.database import init_db, SessionLocal, engine
from app.config import get_settings
from app.agents.resume_graph import configure_checkpointer
from app.services.conversation_store import remove_conversation, checkpoint_owner, claim_browser
from app.services.account_service import assert_same_origin, get_account_service, resolve_owner
from app.services.data_crypto import get_crypto
from app.services.secure_checkpoint import SecureCheckpointSaver
from app.services.session_store import (
    list_sessions_needing_checkpoint_cleanup,
    purge_expired_resume_session,
    session_lock,
    session_needs_checkpoint_cleanup,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _preload_chromadb():
    """事件循环启动前同步预加载 ChromaDB gRPC（避免首次请求时 GIL 卡住事件循环）"""
    if not get_settings().ENABLE_RAG or not get_settings().LLM_API_KEY:
        return
    try:
        from app.rag.vector_store import get_retriever

        get_retriever(collection="jargon_dict", k=1)
        logger.info("ChromaDB preloaded successfully")
    except Exception as e:
        logger.warning("ChromaDB preload skipped: %s", type(e).__name__)


# 在模块导入时（事件循环启动前）同步执行
_preload_chromadb()


async def _cleanup_expired_sessions(checkpointer) -> None:
    retention_days = get_settings().SESSION_RETENTION_DAYS
    session_ids = list_sessions_needing_checkpoint_cleanup(retention_days)
    for session_id in session_ids:
        async with session_lock(session_id):
            if not session_needs_checkpoint_cleanup(session_id, retention_days):
                continue
            try:
                remove_conversation(session_id)
                await checkpointer.adelete_thread(session_id)
                purge_expired_resume_session(session_id, retention_days)
            except Exception:
                # Keep the row so the next pass can retry the checkpoint.
                logger.warning("session checkpoint deletion failed")


async def _periodic_cleanup(checkpointer, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=900)
        except TimeoutError:
            try:
                await _cleanup_expired_sessions(checkpointer)
            except Exception:
                logger.warning("periodic session cleanup failed")


async def _archive_loop(checkpointer):
    from app.services.profile_service import compensate_archive_events, process_pending_events
    from app.services.profile_bridge import import_claimed_history
    from app.agents.profile_archivist import make_archivist
    from app.api.resume import _llm_for_graph
    while True:
        try:
            await import_claimed_history(checkpointer)
            with SessionLocal() as db:
                compensate_archive_events(db)
                db.commit()
            if get_settings().LLM_API_KEY:
                from app.services.runtime_limits import model_slot, reserve_turn
                async with model_slot():
                    await process_pending_events(SessionLocal, extractor=make_archivist(_llm_for_graph()), limit=3,
                                                 budget_reserver=lambda account_id: reserve_turn("account:" + account_id))
            else:
                await process_pending_events(SessionLocal, extractor=None, limit=3)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("archive_worker_failed error=%s", type(error).__name__)
        await asyncio.sleep(max(1, get_settings().ARCHIVE_POLL_SECONDS))


@asynccontextmanager
async def _checkpoint_lifespan(checkpointer):
    configure_checkpointer(checkpointer)
    app.state.checkpointer = checkpointer
    try:
        await _cleanup_expired_sessions(checkpointer)
    except Exception:
        logger.warning("initial session cleanup failed")
    stop = asyncio.Event()
    cleanup_task = asyncio.create_task(_periodic_cleanup(checkpointer, stop))
    archive_task = asyncio.create_task(_archive_loop(checkpointer))
    try:
        yield
    finally:
        stop.set()
        archive_task.cancel()
        try:
            await archive_task
        except asyncio.CancelledError:
            pass
        await cleanup_task
        app.state.checkpointer = None
        configure_checkpointer(None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings().validate_runtime()
    crypto = get_crypto()
    if get_settings().REQUIRE_ACCOUNT or get_settings().ACCOUNT_SECRET:
        app.state.account_service = get_account_service()
    app.state.claim_browser = claim_browser
    init_db()
    database_url = get_settings().DATABASE_URL
    if database_url.startswith(("postgres://", "postgresql://")):
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(database_url) as saver:
            await saver.setup()
            secured = SecureCheckpointSaver(saver, crypto, checkpoint_owner) if crypto.enabled else saver
            async with _checkpoint_lifespan(secured):
                yield
    else:
        checkpoint_path = Path(get_settings().CHECKPOINT_DB_PATH)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            await saver.setup()
            secured = SecureCheckpointSaver(saver, crypto, checkpoint_owner) if crypto.enabled else saver
            async with _checkpoint_lifespan(secured):
                yield


app = FastAPI(title="胡话简历 Agent", version="1.0.0", lifespan=lifespan)

_chat_requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_all_paid_requests: deque[float] = deque()
CHAT_WINDOW_SECONDS = 600
CHAT_REQUEST_LIMIT = 80
UPLOAD_REQUEST_LIMIT = 30
GLOBAL_REQUEST_LIMIT = 120


@app.middleware("http")
async def security_headers(request: Request, call_next):
    started = time.monotonic()
    if request.url.path.startswith("/api/"):
        try:
            assert_same_origin(request)
            public = {"/api/account/me", "/api/account/login/start", "/api/account/login/verify", "/api/account/logout",
                      "/api/resume/templates", "/api/resume/sample", "/api/chat/templates", "/api/chat/tools"}
            if request.url.path not in public and not request.url.path.startswith("/api/chat/templates/"):
                # Account-only features enforce their own gate; an opaque,
                # short-lived guest can use the current-chat experience.
                resolve_owner(request, allow_guest=True)
        except Exception as error:
            from fastapi import HTTPException
            from fastapi.responses import JSONResponse
            if isinstance(error, HTTPException):
                return JSONResponse(status_code=error.status_code, content={"detail": error.detail}, headers={**(error.headers or {}), "Cache-Control": "no-store"})
            logger.warning("request_access_failed error=%s", type(error).__name__)
            return JSONResponse(status_code=503, content={"detail": "暂时无法验证访问权限，请稍后重试"}, headers={"Cache-Control": "no-store"})
    if request.url.path == "/api/chat/upload" and request.method == "POST":
        # Reject ordinary oversized multipart bodies before Starlette spools
        # them. Chunked transfer still needs an ingress body-size limit.
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > 11 * 1024 * 1024:
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=413, content={"detail": "文件超过 10MB 上限"})
    paid_path = request.url.path
    if paid_path in {"/api/chat/stream", "/api/chat/upload"} and request.method == "POST":
        # Uvicorn may rewrite request.client only for proxies it explicitly
        # trusts. Never use an arbitrary X-Forwarded-For header here.
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        key = (paid_path, client_ip)
        timestamps = _chat_requests[key]
        while timestamps and now - timestamps[0] > CHAT_WINDOW_SECONDS:
            timestamps.popleft()
        while _all_paid_requests and now - _all_paid_requests[0] > CHAT_WINDOW_SECONDS:
            _all_paid_requests.popleft()
        limit = {
            "/api/chat/stream": CHAT_REQUEST_LIMIT,
            "/api/chat/upload": UPLOAD_REQUEST_LIMIT,
        }[paid_path]
        if len(timestamps) >= limit or len(_all_paid_requests) >= GLOBAL_REQUEST_LIMIT:
            from fastapi.responses import JSONResponse

            oldest = timestamps[0] if len(timestamps) >= limit else _all_paid_requests[0]
            return JSONResponse(
                status_code=429,
                content={"detail": "请求有点频繁，请稍后再试"},
                headers={
                    "Retry-After": str(max(1, int(CHAT_WINDOW_SECONDS - (now - oldest))))
                },
            )
        timestamps.append(now)
        _all_paid_requests.append(now)
    response = await call_next(request)
    route = request.scope.get("route")
    # Route templates contain placeholders, never user-provided IDs, filenames,
    # query strings, emails or bodies. Status/latency is sufficient for ops.
    logger.info("request_result method=%s route=%s status=%d duration_ms=%d",
                request.method, getattr(route, "path", "static"), response.status_code,
                int((time.monotonic() - started) * 1000))
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path.startswith("/api/profile/") and request.method in {"PATCH", "DELETE", "POST"} and response.status_code < 300:
        from app.services.profile_bridge import purge_invalidated_copies
        from app.api.resume import _llm_for_graph
        from app.agents.resume_graph import get_graph
        try:
            await purge_invalidated_copies(resolve_owner(request), get_graph(_llm_for_graph()))
        except Exception as error:
            # Invalidation guards already block future use; cleanup is retried
            # on subsequent access. Never include private contents in logs.
            logger.warning("profile_projection_cleanup_pending error=%s", type(error).__name__)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


@app.get("/healthz")
async def healthz():
    from fastapi.responses import JSONResponse
    from sqlalchemy import text
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checkpointer = getattr(app.state, "checkpointer", None)
        if not checkpointer:
            raise RuntimeError("checkpoint unavailable")
        raw_saver = getattr(checkpointer, "inner", checkpointer)
        await asyncio.wait_for(raw_saver.aget_tuple({"configurable": {"thread_id": "__huhua_health_probe__"}}), timeout=2)
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok", "database": "ok", "checkpoint": "ok"}

app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(conversations.router, prefix="/api/chat", tags=["chat"])
app.include_router(resume.router, prefix="/api/resume", tags=["resume"])
app.include_router(account.router, prefix="/api", tags=["account"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(resume_changes.router, prefix="/api/resume", tags=["resume"])

# 静态文件（前端）
WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")
class CachedStaticFiles(StaticFiles):
    """Versioned assets (?v=...) never change under the same URL; cache them for a year."""

    async def __call__(self, scope, receive, send):
        versioned = b"v=" in scope.get("query_string", b"")

        async def send_with_cache(message):
            if message["type"] == "http.response.start" and message.get("status") == 200:
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                headers.append((b"cache-control", b"public, max-age=31536000, immutable" if versioned else b"no-cache"))
                message = {**message, "headers": headers}
            await send(message)

        await super().__call__(scope, receive, send_with_cache)


if os.path.exists(WEB_DIR):
    from starlette.middleware.gzip import GZipMiddleware
    # Compress only the static mount; streamed chat replies stay uncompressed.
    app.mount("/static", GZipMiddleware(CachedStaticFiles(directory=WEB_DIR), minimum_size=1024), name="static")

    @app.get("/")
    async def index():
        return FileResponse(os.path.join(WEB_DIR, "index.html"), headers={"Cache-Control": "no-cache"})

    @app.get("/resume")
    async def resume_page():
        return FileResponse(os.path.join(WEB_DIR, "resume.html"), headers={"Cache-Control": "no-cache"})
