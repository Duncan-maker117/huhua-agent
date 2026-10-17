import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from langchain_openai import ChatOpenAI
from pydantic import ValidationError


from app.agents.resume_graph import _serialize_to_resume_data, get_graph, stream_agent
from app.config import get_settings
from app.schemas.chat import ChatRequest, ReadJobURL, ReadPublicURL, SearchJobContext
from app.services.web_tool_intent import infer_web_tool
from app.services.file_extractor import (
    FileLimitError,
    SUPPORTED_EXT,
    UnsupportedFileError,
    extract_text,
)
from app.services.image_ocr import (
    IMAGE_EXT,
    ImageFormatError,
    ImageRecognitionError,
    NoImageTextError,
    recognize_jd_image,
)
from app.services.conversation_store import create_conversation, remove_conversation, touch_conversation
from app.services.account_service import resolve_owner
from app.services.access_control import authorize_session
from app.services.error_codes import (
    HISTORY_UNAVAILABLE, MESSAGES, SESSION_ENDED, TIMEOUT, classify_error, error_log_fields,
)
from app.services.runtime_limits import model_slot, reserve_turn
from app.services.profile_bridge import protect_data, protect_state, prepare_graph_context
from app.services.canonical_resume import current_canonical
from app.services.resume_workspace import build_workspace
from app.services.session_store import (
    delete_resume_session,
    ensure_resume_session,
    load_resume_session,
    resume_data_has_content,
    session_can_read_checkpoint,
    session_is_blocked,
    session_lock,
)
from app.tools.docx_exporter import resume_to_docx
from app.tools.docx_template_filler import TEMPLATE_DIR, list_templates
from app.tools.resume_data_docx import resume_data_to_docx
from app.services.chat_turns import ChatTurn, active_turns, current_turn

logger = logging.getLogger(__name__)

_active_streams: set[asyncio.Task] = set()


async def _complete_on_disconnect(source, turn: ChatTurn | None = None):
    """The producer owns the session lock through commit, even after SSE closes."""
    queue = asyncio.Queue()
    disconnected = False
    end = object()

    async def produce():
        token = current_turn.set(turn)
        try:
            if turn:
                turn.task = asyncio.current_task()
                turn.check()
            async for event in source:
                if not disconnected:
                    queue.put_nowait(event)
        except asyncio.CancelledError:
            if turn and turn.cancelled and not disconnected:
                queue.put_nowait('data: {"type":"cancelled","message":"已中断，本轮未修改简历"}\n\n')
                queue.put_nowait('data: [DONE]\n\n')
            elif not turn or not turn.cancelled:
                raise
        except Exception as error:
            if turn and turn.cancelled:
                turn.cleanup_failed = True
            if not disconnected:
                queue.put_nowait(error)
        finally:
            try:
                await source.aclose()
            except Exception:
                if turn:
                    turn.cleanup_failed = True
                raise
            finally:
                if turn:
                    active_turns.pop((turn.session_id, turn.turn_id), None)
                    turn.done.set()
                current_turn.reset(token)
                queue.put_nowait(end)

    task = asyncio.create_task(produce())
    _active_streams.add(task)
    task.add_done_callback(_active_streams.discard)
    try:
        while (event := await queue.get()) is not end:
            if isinstance(event, Exception):
                raise event
            yield event
    finally:
        disconnected = True
        while not queue.empty():
            queue.get_nowait()


router = APIRouter()
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 64 * 1024
MAX_CHAT_BODY_BYTES = 128 * 1024
MAX_CHAT_MESSAGES = 30
MAX_CHAT_MESSAGE_CHARS = 10_000
MAX_CHAT_TOTAL_CHARS = 60_000
_extract_slots = asyncio.Semaphore(2)
_image_slots = asyncio.Semaphore(2)
_web_slots = None
_web_loop = None


@router.get("/tools")
async def available_web_tools():
    """Public capability flags, never credentials or provider configuration."""
    return {"read_url": True, "read_public_url": True, "search": bool(get_settings().TAVILY_API_KEY.strip())}


async def _execute_web_tool(tool: ReadJobURL | ReadPublicURL | SearchJobContext) -> list[dict]:
    from app.services.web_research import WebResearchError, read_job_url, read_public_url, search_job_context

    global _web_slots, _web_loop
    loop = asyncio.get_running_loop()
    if _web_slots is None or _web_loop is not loop:
        _web_slots, _web_loop = asyncio.Semaphore(2), loop
    slots = _web_slots
    try:
        await asyncio.wait_for(slots.acquire(), timeout=1)
    except TimeoutError:
        raise HTTPException(503, "联网任务较多，请稍后再试，也可以直接粘贴 JD 正文") from None
    try:
        async with asyncio.timeout(20):
            if isinstance(tool, ReadJobURL):
                return [await read_job_url(tool.url)]
            if isinstance(tool, ReadPublicURL):
                return [await read_public_url(tool.url)]
            return await search_job_context(tool.company, tool.role)
    except WebResearchError as error:
        raise HTTPException(error.status_code, error.message) from None
    except TimeoutError:
        raise HTTPException(504, "读取网页超时，请稍后再试，或粘贴 JD 正文、上传岗位截图") from None
    finally:
        slots.release()


def _web_turn(messages: list[dict], tool, sources: list[dict]) -> tuple[list[dict], str]:
    """Server-owned tool text has a forced non-candidate graph route."""
    copied = [dict(message) for message in messages]
    if isinstance(tool, ReadJobURL):
        source = sources[0]
        scope = ("正文较长，本次仅取得前 12,000 字符，请仅依据这些材料分析。"
                 if source.get("content_truncated") is True
                 else "以下是本次提取的网页正文，不代表已读取整个网站或动态内容。")
        copied[-1]["content"] = (
            "以下是招聘网页材料，只描述招聘方要求，不是我的个人经历。\n"
            f"材料范围：{scope}\n"
            f"标题：{source['title']}\n来源：{source['url']}\n"
            f"获取时间：{source['fetched_at']}\n\n{source['content']}"
        )
        return copied, "decode_jd"
    if isinstance(tool, ReadPublicURL):
        # The user's explicit request goes to the model, not the fetch provider.
        # Sources stay separate and use the existing reference-only graph path.
        return copied, "research_job"
    # Do not send an arbitrary composer draft through the research request.
    # Candidate facts are read from this conversation's protected state only.
    copied[-1]["content"] = (
        f"请查阅公开资料并结合本次简历的已有经历给出建议。\n"
        f"公司：{tool.company or '未指定'}\n岗位：{tool.role or '未指定'}"
    )
    return copied, "research_job"


async def _extract_with_timeout(filename: str, raw: bytes) -> str:
    try:
        await asyncio.wait_for(_extract_slots.acquire(), timeout=1)
    except TimeoutError:
        raise HTTPException(status_code=503, detail="文件解析繁忙，请稍后重试")
    try:
        future = asyncio.get_running_loop().run_in_executor(
            None, extract_text, filename, raw
        )
    except Exception:
        _extract_slots.release()
        raise
    # Timed-out parsing cannot stop a running Python thread. Keep its slot
    # occupied until it actually exits so requests cannot pile up CPU work.
    future.add_done_callback(lambda _: _extract_slots.release())
    return await asyncio.wait_for(asyncio.shield(future), timeout=20)


async def _recognize_image_with_limit(filename: str, raw: bytes) -> str:
    try:
        await asyncio.wait_for(_image_slots.acquire(), timeout=1)
    except TimeoutError:
        raise HTTPException(status_code=503, detail="图片识别繁忙，请稍后重试")
    try:
        return await recognize_jd_image(filename, raw)
    finally:
        _image_slots.release()


async def _session_meta(session_id: str, llm: ChatOpenAI) -> dict:
    """Turn-end snapshot for the live resume canvas."""
    stage = ""
    has_data = False
    vals, rd = {}, {}
    if not session_can_read_checkpoint(session_id):
        return {
            "type": "meta",
            "session_id": session_id,
            "stage": stage,
            "has_data": has_data,
            "workspace": build_workspace({}, {}),
        }
    try:
        graph = get_graph(llm)
        state = await graph.aget_state({"configurable": {"thread_id": session_id}})
        from app.services.conversation_store import session_owner
        owner = session_owner(session_id)
        vals = protect_state(owner, (state.values if state else {}) or {})
        stage = vals.get("stage") or "JD_INPUT"
        stored = load_resume_session(session_id)
        if stored and stored.get('has_authoritative_state'):
            vals.update({key: stored.get(key) for key in ('collected_info', 'resume_meta', 'resume_versions', 'session_constraints')})
        rd = protect_data(owner, current_canonical(vals, stored, _serialize_to_resume_data))
        has_data = resume_data_has_content(rd)
    except Exception as e:
        logger.warning("session meta graph read failed: %s", type(e).__name__)
        stored = load_resume_session(session_id)
        if stored:
            from app.services.conversation_store import session_owner
            owner = session_owner(session_id)
            stage = stored.get("stage") or ""
            vals.update({key: stored.get(key) for key in ("collected_info", "resume_meta", "resume_versions", "session_constraints")})
            rd = protect_data(owner, stored.get("resume_data") or {})
            has_data = resume_data_has_content(rd)
    from app.services.resume_workspace import tailor_metadata
    return {
        "type": "meta", "session_id": session_id, "stage": stage, "has_data": has_data,
        "workspace": build_workspace(vals, rd), **tailor_metadata(vals, rd),
    }


def _get_llm() -> ChatOpenAI:
    s = get_settings()
    if not s.LLM_API_KEY:
        raise HTTPException(status_code=503, detail="服务尚未配置模型，请稍后再试")
    return ChatOpenAI(
        model=s.LLM_MODEL,
        api_key=s.LLM_API_KEY,
        base_url=s.LLM_BASE_URL,
        temperature=s.LLM_CHAT_TEMPERATURE,
        max_tokens=s.LLM_MAX_TOKENS,
        streaming=True,
    )


@router.post("/stream")
async def chat_stream(request: Request):
    content_length = request.headers.get("content-length")
    if (
        content_length
        and content_length.isdigit()
        and int(content_length) > MAX_CHAT_BODY_BYTES
    ):
        raise HTTPException(status_code=413, detail="对话内容过长，请缩短后重试")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_CHAT_BODY_BYTES:
            raise HTTPException(status_code=413, detail="对话内容过长，请缩短后重试")
        body.extend(chunk)
    try:
        req = ChatRequest.model_validate_json(bytes(body))
    except ValidationError:
        raise HTTPException(status_code=422, detail="对话内容格式无效")
    if (
        not req.messages
        or len(req.messages) > MAX_CHAT_MESSAGES
        or any(len(m.content) > MAX_CHAT_MESSAGE_CHARS for m in req.messages)
        or sum(len(m.content) for m in req.messages) > MAX_CHAT_TOTAL_CHARS
        or req.messages[-1].role != "user"
        or (req.session_id is not None and len(req.session_id) > 128)
    ):
        raise HTTPException(status_code=413, detail="对话内容过长或格式无效，请精简后重试")
    cookie_response = Response()
    owner = resolve_owner(request, cookie_response, allow_guest=True)
    if req.session_id:
        authorize_session(request, req.session_id)
    if req.web_tool is None and req.task == "auto":
        inferred = infer_web_tool(req.messages[-1].content)
        if inferred:
            req.web_tool = (ReadPublicURL.model_validate(inferred)
                            if inferred["action"] == "read_public_url"
                            else ReadJobURL.model_validate(inferred))
    if isinstance(req.web_tool, SearchJobContext) and not get_settings().TAVILY_API_KEY.strip():
        raise HTTPException(503, "公司/岗位搜索尚未开通；可以先粘贴招聘链接、JD 正文或上传岗位截图")
    llm = _get_llm()
    messages = [m.model_dump() for m in req.messages]
    session_id = req.session_id or create_conversation(owner)["session_id"]
    reserve_turn(owner)
    turn_id = req.turn_id or uuid.uuid4().hex
    if (session_id, turn_id) in active_turns:
        raise HTTPException(409, '本轮请求正在处理')
    turn = ChatTurn(session_id, turn_id, owner)
    active_turns[(session_id, turn_id)] = turn

    async def generate():
        async with session_lock(session_id):
            try:
                # Login may have claimed this guest session while the request
                # waited for a previous turn. Check the capability again.
                authorize_session(request, session_id)
                if session_is_blocked(session_id):
                    yield f"data: {json.dumps({'error': MESSAGES[SESSION_ENDED], 'code': SESSION_ENDED}, ensure_ascii=False)}\n\n"
                else:
                    # A checkpoint with no current session row is an orphan
                    # from an old/deleted run. Never continue from its state.
                    if not session_can_read_checkpoint(session_id):
                        old_state = await get_graph(llm).aget_state(
                            {"configurable": {"thread_id": session_id}}
                        )
                        if old_state and old_state.values:
                            yield f"data: {json.dumps({'error': MESSAGES[SESSION_ENDED], 'code': SESSION_ENDED}, ensure_ascii=False)}\n\n"
                            yield "data: [DONE]\n\n"
                            return
                    if not ensure_resume_session(session_id):
                        yield f"data: {json.dumps({'error': MESSAGES[SESSION_ENDED], 'code': SESSION_ENDED}, ensure_ascii=False)}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    persisted = load_resume_session(session_id)
                    if persisted and (
                        persisted["stage"] != "JD_INPUT"
                        or persisted["has_data"]
                        or persisted["resume_draft"]
                    ):
                        snapshot = await get_graph(llm).aget_state(
                            {"configurable": {"thread_id": session_id}}
                        )
                        if not snapshot or not snapshot.values:
                            yield f"data: {json.dumps({'error': MESSAGES[HISTORY_UNAVAILABLE], 'code': HISTORY_UNAVAILABLE}, ensure_ascii=False)}\n\n"
                            yield "data: [DONE]\n\n"
                            return
                    touch_conversation(session_id, messages[-1]["content"], owner)
                    if req.web_tool is not None:
                        # Keep the existing privacy/canonical repair guards,
                        # without importing unrelated long-term profile facts.
                        await prepare_graph_context(owner, session_id, get_graph(llm), context={"facts": [], "fact_refs": []})
                        tool = req.web_tool
                        status_message = {"read_url": "正在读取招聘网页…", "read_public_url": "正在读取公开主页或仓库资料…", "search": "正在查询公司和岗位公开资料…"}[tool.action]
                        yield f"data: {json.dumps({'type': 'tool_status', 'tool': tool.action, 'status': 'running', 'message': status_message}, ensure_ascii=False)}\n\n"
                        sources = await _execute_web_tool(tool)
                        if not sources:
                            raise HTTPException(404, "暂未找到可用的公开资料，请换用更准确的公司/岗位名，或粘贴 JD 正文")
                        yield f"data: {json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"
                        yield f"data: {json.dumps({'type': 'tool_status', 'tool': tool.action, 'status': 'completed', 'message': '已读取公开资料，正在结合当前材料分析…'}, ensure_ascii=False)}\n\n"
                        tool_messages, tool_task = _web_turn(messages, tool, sources)
                        stream = stream_agent(tool_messages, session_id, llm, task=tool_task, web_sources=sources)
                    else:
                        await prepare_graph_context(owner, session_id, get_graph(llm))
                    # Keep automatic requests compatible with existing callers;
                    # an explicit task applies only to this submitted turn.
                        choices = {}
                        if req.answers is not None:
                            choices['answers'] = req.answers.model_dump()
                        if req.plan_choice is not None:
                            choices['plan_choice'] = req.plan_choice.model_dump()
                        if req.task != "auto":
                            choices['task'] = req.task
                        stream = stream_agent(messages, session_id, llm, **choices)

                    generation_started = time.monotonic()
                    async with model_slot():
                        async for token in stream:
                            yield f"data: {json.dumps({'content': token}, ensure_ascii=False)}\n\n"
                    logger.info("chat_turn_result status=completed saved=true duration_ms=%d", int((time.monotonic() - generation_started) * 1000))
                    yield f"data: {json.dumps(await _session_meta(session_id, llm), ensure_ascii=False)}\n\n"
            except TimeoutError:
                logger.warning("chat_turn_result status=timeout saved=unknown code=%s", TIMEOUT)
                yield f"data: {json.dumps({'error': MESSAGES[TIMEOUT], 'code': TIMEOUT}, ensure_ascii=False)}\n\n"
            except HTTPException as error:
                logger.warning("chat_turn_result status=unavailable code=%d", error.status_code)
                yield f"data: {json.dumps({'error': error.detail}, ensure_ascii=False)}\n\n"
            except Exception as error:
                code, message = classify_error(error)
                _, error_type, status_code = error_log_fields(error)
                logger.error("chat_turn_result status=error code=%s error_type=%s status_code=%s",
                             code, error_type, status_code)
                yield f"data: {json.dumps({'error': message, 'code': code}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        _complete_on_disconnect(generate(), turn),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Chat-Turn-Id": turn_id, **(
            {"Set-Cookie": cookie_response.headers["set-cookie"]} if "set-cookie" in cookie_response.headers else {}
        )},
    )


@router.post('/session/{session_id}/cancel')
async def cancel_chat(session_id: str, request: Request, turn_id: str = Query(min_length=1, max_length=128)):
    owner = authorize_session(request, session_id)
    turn = active_turns.get((session_id, turn_id))
    if turn is None:
        return {'cancelled': False, 'status': 'finished'}
    if turn.owner != owner:
        raise HTTPException(404, '对话不存在或无权访问')
    if not turn.cancel():
        return {'cancelled': False, 'status': 'committed'}
    # A positive receipt means upstream is closed and the checkpoint repaired.
    await turn.done.wait()
    if turn.cleanup_failed:
        raise HTTPException(503, '中断后的会话恢复未完成，请刷新核对当前稿')
    return {'cancelled': True, 'message': '已中断，本轮未修改简历'}


@router.delete("/session/{session_id}")
async def delete_session(session_id: str, request: Request):
    """Delete persisted resume data and the conversation checkpoint."""
    owner = authorize_session(request, session_id)
    checkpointer = getattr(request.app.state, "checkpointer", None)
    if checkpointer is None or not hasattr(checkpointer, "adelete_thread"):
        raise HTTPException(status_code=503, detail="暂时无法删除会话，请稍后重试")
    async with session_lock(session_id):
        owner = authorize_session(request, session_id)
        try:
            if owner.startswith("account:"):
                from app.database import SessionLocal
                from app.services.profile_service import disable_session_sources
                with SessionLocal() as db:
                    disable_session_sources(db, owner.split(":", 1)[1], session_id)
                    db.commit()
            delete_resume_session(session_id)
            remove_conversation(session_id)
            await checkpointer.adelete_thread(session_id)
        except Exception:
            logger.error("session deletion failed")
            raise HTTPException(status_code=503, detail="暂时无法删除会话，请稍后重试")
    return {"deleted": True}


@router.post("/upload")
async def upload_file(request: Request, response: Response, file: UploadFile = File(...)):
    """提取文档文字，或用视觉模型转写 JPG/PNG 岗位截图。"""
    from pathlib import Path as _Path

    filename = file.filename or "upload"
    ext = _Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXT | IMAGE_EXT:
        raise HTTPException(
            status_code=415,
            detail=f"暂不支持此文件类型 {ext}，目前支持：PDF / DOCX / TXT / MD / JPG / PNG",
        )
    chunks: list[bytes] = []
    size = 0
    try:
        while chunk := await file.read(UPLOAD_CHUNK_BYTES):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="文件超过 10MB 上限")
            chunks.append(chunk)
        raw = b"".join(chunks)
        if ext in IMAGE_EXT:
            reserve_turn(resolve_owner(request, response, allow_guest=True))
            async with model_slot():
                text = await _recognize_image_with_limit(filename, raw)
        else:
            text = await _extract_with_timeout(filename, raw)
    except ImageFormatError as e:
        raise HTTPException(status_code=415, detail=str(e))
    except NoImageTextError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ImageRecognitionError as e:
        if e.__cause__ is not None:
            code, message = classify_error(e)
            if code != "E-INTERNAL":
                logger.error("image_ocr_failed code=%s error_type=%s", code, error_log_fields(e)[1])
                raise HTTPException(status_code=503, detail={"code": code, "message": message})
        raise HTTPException(status_code=503, detail=str(e))
    except UnsupportedFileError as e:
        raise HTTPException(status_code=415, detail=str(e))
    except FileLimitError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except TimeoutError:
        logger.warning("file extraction timed out")
        raise HTTPException(status_code=422, detail="文件解析超时，请换一份更简短的文件")
    except HTTPException:
        raise
    except Exception:
        logger.error("file extraction failed")
        raise HTTPException(status_code=422, detail="文件解析失败，请检查文件格式")
    finally:
        await file.close()
    return {
        "filename": filename,
        "size": len(raw),
        "text": text,
        "text_length": len(text),
        "source_type": "image" if ext in IMAGE_EXT else "document",
    }


@router.get("/templates")
async def list_available_templates():
    """列出所有可用模版（供前端画廊展示，用户自取）。"""
    return {"templates": list_templates()}


@router.get("/templates/{name}")
async def download_template(name: str):
    """下载原始模版文件（未填充，用户自己复制内容进去）。"""
    # 模糊匹配：'单页001' 匹配 '单页001-简约.docx'
    candidates = [t for t in list_templates() if t == name or t.startswith(name)]
    if not candidates:
        raise HTTPException(status_code=404, detail=f"模版不存在: {name}")
    path = TEMPLATE_DIR / candidates[0]
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=candidates[0],
    )


@router.get("/export/docx")
async def export_docx(request: Request, session_id: str = Query(...)):
    """导出简约版 Word（从零生成 resume_draft 的内容）。"""
    from app.api.resume import _require_export_account
    _require_export_account(request)
    authorize_session(request, session_id)
    async with session_lock(session_id):
        authorize_session(request, session_id)
        return await _export_docx_data(session_id)


async def _export_docx_data(session_id: str):
    if not session_can_read_checkpoint(session_id):
        raise HTTPException(status_code=404, detail="简历草稿不存在，请先完成生成步骤")
    from app.api.resume import _llm_for_graph
    graph = get_graph(_llm_for_graph())
    config = {"configurable": {"thread_id": session_id}}

    try:
        state = await graph.aget_state(config)
    except Exception as e:
        logger.warning("graph state read failed: %s", type(e).__name__)
        state = None

    stored = load_resume_session(session_id)
    from app.services.conversation_store import session_owner
    owner = session_owner(session_id)
    canonical = protect_data(owner, current_canonical(
        protect_state(owner, (state.values if state else {}) or {}), stored, _serialize_to_resume_data,
    ))
    resume_draft = ""
    if resume_data_has_content(canonical):
        try:
            docx_bytes = resume_data_to_docx(canonical)
        except Exception:
            logger.error("persisted docx generation failed")
            raise HTTPException(status_code=500, detail="生成 DOCX 失败，请稍后重试")
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="resume_{session_id[:8]}.docx"'
            },
        )

    if not resume_draft:
        raise HTTPException(status_code=404, detail="简历草稿不存在，请先完成生成步骤")

    try:
        docx_bytes = resume_to_docx(resume_draft)
    except Exception:
        logger.error("docx generation failed")
        raise HTTPException(status_code=500, detail="生成 DOCX 失败，请稍后重试")

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="resume_{session_id[:8]}.docx"'
        },
    )
