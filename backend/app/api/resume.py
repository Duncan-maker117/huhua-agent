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
from app.services.renderer import list_templates, render_resume
from app.services.resume_pdf import render_resume_pdf
from app.services.resume_workspace import build_workspace, tailor_metadata
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
    session_can_read_checkpoint,
    session_lock,
)
from app.tools.resume_data_docx import resume_data_to_docx
from app.services.access_control import authorize_session
from app.services.profile_bridge import protect_data, protect_state

router = APIRouter()
logger = logging.getLogger(__name__)


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
    """读取已提交的简历快照，允许聊天同时生成下一版。"""
    return await _current_resume(request, session_id)


async def _current_resume(request: Request, session_id: str):
    owner = authorize_session(request, session_id, edit_link=True)
    if not session_can_read_checkpoint(session_id):
        try:
            assert_active_resume_session(session_id)
        except InvalidResumeSession:
            return {"has_data": False, "has_jd": False, "data": None, "stage": "", "revision": None, "can_save": False}
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
        from app.services.job_intel.background import refresh_expired
        refreshed = await refresh_expired(graph, session_id, (state.values if state else {}) or {})
    except Exception:
        state = None
        graph_error = True
    else:
        graph_error = False

    vals = protect_state(owner, refreshed if not graph_error else {})
    if vals:
        stage = vals.get("stage") or "JD_INPUT"
        from app.services.resume_strategy import has_job_description
        has_jd = bool(has_job_description(vals.get("jd_info")) or vals.get("jd_text"))
    if stored and stored.get("has_authoritative_state"):
        vals.update({key: stored.get(key) for key in ("collected_info", "resume_meta", "resume_versions", "session_constraints")})
    rd = current_canonical(vals, stored, _serialize_to_resume_data)
    rd = protect_data(owner, rd)
    if not stage and stored:
        stage = stored.get("stage") or ""

    revision = resume_revision(rd)
    missing_context = not vals and bool(stored and (
        stored.get("resume_data") or stored.get("stage") not in ("", "JD_INPUT")
    ))
    can_save = not graph_error and not missing_context
    from app.services.profile_bridge import intake_profile_state
    workspace = build_workspace({**vals, **intake_profile_state(owner)}, rd)
    if not canonical_has_content(rd):
        if graph_error and not stored:
            raise HTTPException(
                status_code=503, detail="暂时无法读取简历，请稍后重试"
            )
        return {"has_data": False, "has_jd": has_jd, "data": None, "stage": stage, "revision": revision, "can_save": can_save, "workspace": workspace, **tailor_metadata(vals, rd)}
    return {"has_data": True, "has_jd": has_jd, "data": rd, "stage": stage, "revision": revision, "can_save": can_save, "workspace": workspace, **tailor_metadata(vals, rd)}


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
        # Frontend normalization materializes section metadata. Never render the
        # supplied metadata: a successful comparison returns the server sample.
        def sample_content(value):
            return {key: item for key, item in value.items() if key != "sections"}
        if sample_content(payload) != sample_content(sample):
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
    # SQL reads provide a committed snapshot while a chat turn is still running.
    # Interactive editor drafts are validated against that snapshot, never a
    # partially generated checkpoint. Rendering must not wait for the writer.
    return await run_in_threadpool(
        _render_payload, template_id, data, request, interactive, session_id, removed_item_ids)


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
    return await run_in_threadpool(_export_docx_payload, template_id, data, request, session_id)


@router.post("/export/pdf/{template_id}")
async def export_pdf(template_id: str, data: ResumeData, request: Request,
                     session_id: str | None = Query(None, min_length=1, max_length=128)):
    """Return PDF bytes from the authorized saved resume, never arbitrary HTML."""
    _require_export_account(request)
    if template_id not in {template["id"] for template in list_templates()}:
        raise HTTPException(404, "模板不存在")
    payload = await run_in_threadpool(
        _output_payload, request, data, session_id=session_id, committed=True)
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
