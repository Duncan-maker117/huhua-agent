"""HTML 简历渲染 API：列模板 / 渲染 / 取样例数据 / 取当前 session 数据 / 导出 DOCX。"""

import io
import json
import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agents.resume_graph import _serialize_to_resume_data, get_graph
from app.config import get_settings
from app.database import SessionLocal
from app.schemas.editor import ResumeData
from app.services.jev_match import (
    build_jev_payload,
    build_match_context,
    call_jev,
    score_jev_response,
)
from app.services.renderer import list_templates, render_resume
from app.services.resume_pdf import render_resume_pdf
from app.services.resume_review import review_resume
from app.services.resume_workspace import build_workspace
from app.services.canonical_resume import (
    InvalidResumeSession,
    ResumeRevisionConflict,
    ResumeSaveUnavailable,
    assert_active_resume_session,
    canonical_has_content,
    current_canonical,
    resume_revision,
    save_canonical_resume,
)
from app.services.session_store import (
    load_resume_session,
    resume_data_has_content,
    session_can_read_checkpoint,
    session_lock,
)
from app.tools.resume_data_docx import resume_data_to_docx
from app.services.access_control import authorize_session
from app.services.profile_bridge import protect_data, protect_state

router = APIRouter()
logger = logging.getLogger(__name__)


class MatchRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)


class SaveResumeRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    expected_revision: str = Field(min_length=64, max_length=64)
    resume_data: ResumeData
    archive_facts: bool = False
    removed_item_ids: list[str] = Field(default_factory=list, max_length=300)

ROOT = Path(__file__).resolve().parents[3]
# 模板预览用中性占位数据（不含任何真实用户信息）
SAMPLE_PATH = ROOT / "data" / "sample_resume.json"


def _llm_for_graph() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(
        model=s.LLM_MODEL,
        # Constructing the graph for database reads/writes makes no model call.
        api_key=s.LLM_API_KEY or "database-only",
        base_url=s.LLM_BASE_URL,
        temperature=s.LLM_CHAT_TEMPERATURE,
        max_tokens=s.LLM_MAX_TOKENS,
        streaming=True,
    )


@router.get("/templates")
async def templates():
    return {"templates": list_templates()}


@router.get("/sample")
async def sample():
    if not SAMPLE_PATH.exists():
        raise HTTPException(status_code=404, detail="样例数据不存在")
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


@router.get("/current")
async def current_resume(request: Request, session_id: str = Query(..., description="聊天 session_id")):
    """读聊天 session 当前产出的 ResumeData，内存没有时回退到 SQLite 持久化数据。"""
    authorize_session(request, session_id)
    async with session_lock(session_id):
        return await _current_resume(request, session_id)


async def _current_resume(request: Request, session_id: str):
    owner = authorize_session(request, session_id)
    if not session_can_read_checkpoint(session_id):
        try:
            assert_active_resume_session(session_id)
        except InvalidResumeSession:
            return {"has_data": False, "has_jd": False, "match_enabled": False, "data": None, "stage": "", "revision": None, "can_save": False}
        except ResumeSaveUnavailable:
            raise HTTPException(503, detail={"code": "read_unavailable", "message": "暂时无法读取会话，请保留草稿并稍后重试。"})
    config = {"configurable": {"thread_id": session_id}}
    rd: dict = {}
    stage = ""
    has_jd = False
    stored = load_resume_session(session_id)
    try:
        graph = get_graph(_llm_for_graph())
        state = await graph.aget_state(config)
    except Exception:
        state = None
        graph_error = True
    else:
        graph_error = False

    vals = protect_state(owner, (state.values if state else {}) or {})
    if vals:
        stage = vals.get("stage") or "JD_INPUT"
        has_jd = bool(vals.get("jd_info") or vals.get("jd_text"))
    rd = current_canonical(vals, stored, _serialize_to_resume_data)
    rd = protect_data(owner, rd)
    if not stage and stored:
        stage = stored.get("stage") or ""

    revision = resume_revision(rd)
    missing_context = not vals and bool(stored and (
        stored.get("resume_data") or stored.get("stage") not in ("", "JD_INPUT")
    ))
    can_save = not graph_error and not missing_context
    workspace = build_workspace(vals, rd)
    if not canonical_has_content(rd):
        if graph_error and not stored:
            raise HTTPException(
                status_code=503, detail="暂时无法读取简历，请稍后重试"
            )
        return {"has_data": False, "has_jd": has_jd, "match_enabled": False, "data": None, "stage": stage, "revision": revision, "can_save": can_save, "workspace": workspace}
    return {"has_data": True, "has_jd": has_jd, "match_enabled": bool(get_settings().JEV_API_KEY), "data": rd, "stage": stage, "revision": revision, "can_save": can_save, "workspace": workspace}


@router.put("/current")
async def save_current_resume(req: SaveResumeRequest, request: Request):
    """Persist explicit form edits without starting a model run or a new session."""
    owner = authorize_session(request, req.session_id)
    if req.archive_facts:
        _require_export_account(request)
    protect_data(owner, req.resume_data.model_dump(), reject=True)
    async with session_lock(req.session_id):
        authorize_session(request, req.session_id)
        try:
            assert_active_resume_session(req.session_id)
            graph = get_graph(_llm_for_graph())
            return await save_canonical_resume(
                req.session_id, req.expected_revision, req.resume_data.model_dump(),
                graph, _serialize_to_resume_data,
                archive_facts=req.archive_facts,
                removed_item_ids=req.removed_item_ids,
            )
        except InvalidResumeSession:
            raise HTTPException(404, detail={"code": "invalid_session", "message": "会话不存在或已清除，当前草稿未保存。"})
        except ResumeRevisionConflict as error:
            raise HTTPException(409, detail={"code": "revision_conflict", "message": "聊天或另一个编辑页已更新简历，请保留草稿后载入最新内容。", "revision": error.revision})
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, detail={"code": "save_unavailable", "message": "保存失败，当前草稿仍在本页，请重试或下载备份。"})


@router.post("/match")
async def match_resume(req: MatchRequest, request: Request):
    """User-triggered, privacy-minimized Jev JD coverage check."""
    authorize_session(request, req.session_id)
    async with session_lock(req.session_id):
        return await _match_resume(req, request)


async def _match_resume(req: MatchRequest, request: Request):
    owner = authorize_session(request, req.session_id)
    from app.services.runtime_limits import reserve_turn
    reserve_turn(owner)
    empty = {"score": None, "requirements": [], "checks": []}
    if not session_can_read_checkpoint(req.session_id):
        return {**empty, "status": "no_resume", "message": "当前会话没有可核对的简历。"}

    stored = load_resume_session(req.session_id)
    resume_data = protect_data(owner, (stored or {}).get("resume_data") or {})
    jd_info: dict = {}
    jd_text = ""
    graph_failed = False
    settings = get_settings()
    if settings.LLM_API_KEY:
        try:
            graph = get_graph(_llm_for_graph())
            state = await graph.aget_state(
                {"configurable": {"thread_id": req.session_id}}
            )
            vals = protect_state(owner, (state.values if state else {}) or {})
            if not resume_data_has_content(resume_data):
                resume_data = vals.get("resume_data") or {}
                if not resume_data_has_content(resume_data) and vals:
                    resume_data = _serialize_to_resume_data(vals)
            jd_info = vals.get("jd_info") or {}
            jd_text = vals.get("jd_text") or ""
        except Exception:
            graph_failed = True

    if not resume_data_has_content(resume_data):
        return {**empty, "status": "no_resume", "message": "当前会话没有可核对的简历。"}

    checks = review_resume(resume_data, jd_info)
    fallback = {**empty, "checks": checks}
    if not jd_text:
        status = "unavailable" if graph_failed else "no_jd"
        message = "暂时无法读取岗位要求，请稍后重试。" if graph_failed else "当前会话没有可核对的 JD。"
        return {**fallback, "status": status, "message": message}
    if not settings.JEV_API_KEY:
        return {**fallback, "status": "unavailable", "message": "岗位匹配参考功能尚未配置。"}

    context = build_match_context(resume_data, jd_info, jd_text)
    requirements = context["requirements"]
    recognized = context["outbound_state"]["requirements"]
    evidence = context["outbound_state"]["evidence"]
    if not requirements or not recognized or not evidence:
        return {
            **fallback,
            "status": "insufficient",
            "requirements": [
                {"id": row["id"], "text": row["text"], "category": row["category"],
                 "weight": row["weight"], "level": "unscored", "evidence_id": None,
                 "evidence_text": None}
                for row in requirements
            ],
            "message": "JD 或简历中可识别的能力信息不足，暂时不给参考分。",
        }
    try:
        response = await call_jev(
            build_jev_payload(context), settings.JEV_API_KEY, settings.JEV_TIMEOUT_SECONDS
        )
        result = score_jev_response(context, response)
    except Exception:
        return {
            **fallback,
            "status": "unavailable",
            "message": "岗位匹配暂时不可用，请稍后重试。",
        }
    return {**result, "checks": checks}


def _output_payload(request, data, *, session_id=None, removed_item_ids=(), committed=False):
    from app.services.account_service import resolve_owner
    from app.services.resume_provenance import validate_item_ids
    owner = resolve_owner(request, allow_guest=True) or ""
    if session_id:
        owner = authorize_session(request, session_id)
        stored = load_resume_session(session_id)
        if stored is None:
            raise HTTPException(404, "会话不存在")
        current = protect_data(owner, stored["resume_data"])
        if committed:
            return current
        proposed = data.model_dump()
        if owner.startswith("account:"):
            with SessionLocal() as db:
                validate_item_ids(db, owner.split(":", 1)[1], session_id, current, proposed,
                                  removed_item_ids=removed_item_ids)
        return protect_data(owner, proposed, reject=True)
    # Stateless arbitrary-body rendering remains available only to the explicit
    # unauthenticated local compatibility mode. Account documents must carry a
    # session, otherwise stripping item IDs could hide their server bindings.
    settings = get_settings()
    legacy_local = (getattr(settings, "APP_ENV", "local") == "local"
                    and not getattr(settings, "REQUIRE_ACCOUNT", True)
                    and not owner.startswith("account:"))
    payload = data.model_dump()
    if not legacy_local:
        if not SAMPLE_PATH.exists():
            raise HTTPException(409, "个人简历预览和导出需要当前会话，请从简历编辑页操作")
        sample = ResumeData.model_validate(json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))).model_dump()
        if payload != sample:
            raise HTTPException(409, "个人简历预览和导出需要当前会话，请从简历编辑页操作")
        return sample
    return protect_data(owner, payload, reject=True)


@router.post("/render/{template_id}", response_class=HTMLResponse)
async def render(template_id: str, data: ResumeData, request: Request, interactive: bool = Query(False),
                 session_id: str | None = Query(None, min_length=1, max_length=128),
                 removed_item_ids: list[str] = Query(default=[]), export: bool = Query(False)):
    if export:
        _require_export_account(request)
        interactive = False
    if session_id:
        authorize_session(request, session_id)
        async with session_lock(session_id):
            return _render_payload(template_id, data, request, interactive, session_id, removed_item_ids)
    return _render_payload(template_id, data, request, interactive, session_id, removed_item_ids)


def _render_payload(template_id, data, request, interactive, session_id, removed_item_ids):
    payload = _output_payload(request, data, session_id=session_id, removed_item_ids=removed_item_ids,
                              committed=not interactive)
    try:
        html = render_resume(template_id, payload, interactive=interactive)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return HTMLResponse(content=html)


def _require_export_account(request):
    """Only the explicit old local test mode permits anonymous downloads."""
    settings = get_settings()
    if settings.APP_ENV == "local" and not settings.REQUIRE_ACCOUNT:
        return
    from app.services.account_service import require_account
    require_account(request)


@router.post("/export/docx/{template_id}")
async def export_docx(template_id: str, data: ResumeData, request: Request,
                      session_id: str | None = Query(None, min_length=1, max_length=128)):
    """把 ResumeData 导出为通用 Word 文件。template_id 仅用于文件名。"""
    _require_export_account(request)
    if session_id:
        authorize_session(request, session_id)
        async with session_lock(session_id):
            return _export_docx_payload(template_id, data, request, session_id)
    return _export_docx_payload(template_id, data, request, session_id)


@router.post("/export/pdf/{template_id}")
async def export_pdf(template_id: str, data: ResumeData, request: Request,
                     session_id: str | None = Query(None, min_length=1, max_length=128)):
    """Return PDF bytes from the authorized saved resume, never arbitrary HTML."""
    _require_export_account(request)
    if template_id not in {template["id"] for template in list_templates()}:
        raise HTTPException(404, "模板不存在")
    if session_id:
        authorize_session(request, session_id)
        async with session_lock(session_id):
            payload = _output_payload(request, data, session_id=session_id, committed=True)
    else:
        payload = _output_payload(request, data, committed=True)
    try:
        pdf_bytes = await run_in_threadpool(render_resume_pdf, template_id, payload)
    except Exception:
        # Renderer exceptions may contain document text; do not log them.
        logger.error("resume_pdf_export_failed")
        raise HTTPException(503, detail={"code": "pdf_export_unavailable", "message": "PDF 生成失败，已保存的简历仍在。请重试，或先导出 Word。"}) from None
    if not pdf_bytes.startswith(b"%PDF-"):
        raise HTTPException(503, detail="PDF 生成结果异常，请重试或先导出 Word。")
    name = (payload.get("basic_info") or {}).get("name") or "简历"
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=resume.pdf; filename*=UTF-8''{quote(name + '-简历.pdf', safe='')}",
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    })


def _export_docx_payload(template_id, data, request, session_id):
    payload = _output_payload(request, data, session_id=session_id, committed=True)
    try:
        docx_bytes = resume_data_to_docx(payload)
    except Exception:
        logger.error("resume_docx_export_failed")
        raise HTTPException(503, detail="Word 生成失败，已保存的简历仍在。请稍后重试。") from None
    name = (payload.get("basic_info") or {}).get("name") or "简历"
    filename = f"{name}-通用Word.docx"
    # Content-Disposition 用 filename* 支持中文
    disposition = f"attachment; filename=resume.docx; filename*=UTF-8''{quote(filename, safe='')}"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": disposition, "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
