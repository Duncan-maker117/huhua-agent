"""Explicit, revision-checked resume edits and selected archive imports."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents.resume_graph import _serialize_to_resume_data
from app.api.resume import _llm_for_graph, get_graph
from app.database import SessionLocal
from app.services.access_control import authorize_session
from app.services.canonical_resume import InvalidResumeSession, ResumeSaveUnavailable, ResumeRevisionConflict, resume_revision, save_canonical_resume
from app.services.profile_bridge import account_id, protect_data, protect_state
from app.services.profile_service import context_to_collected_info, get_context, merge_job_version_import, ProfileRevisionConflict
from app.services.resume_versions import restore_payload, document_diff, education_correction_note
from app.services.resume_workspace import build_workspace
from app.services.session_store import load_resume_session, session_lock, SessionStorageUnavailable

router = APIRouter()


class VersionUndo(BaseModel):
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    version_id: str | None = Field(default=None, min_length=1, max_length=64)


class ProfileImport(BaseModel):
    fact_ids: list[str] = Field(min_length=1, max_length=100)


@router.post("/session/{session_id}/versions/undo")
async def undo_version(session_id: str, body: VersionUndo, request: Request):
    authorize_session(request, session_id)
    async with session_lock(session_id):
        authorize_session(request, session_id)
        try:
            stored = load_resume_session(session_id)
        except SessionStorageUnavailable:
            raise HTTPException(503, "版本暂时无法读取，请稍后重试") from None
        if stored is None:
            raise HTTPException(404, "会话不存在或已清除")
        if resume_revision(stored["resume_data"]) != body.expected_revision:
            raise HTTPException(409, "简历已变化，请载入最新版本")
        try:
            proposal = restore_payload(stored, body.version_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        try:
            saved = await save_canonical_resume(
                session_id, body.expected_revision, proposal["resume_data"],
                get_graph(_llm_for_graph()), _serialize_to_resume_data, source="restore",
                resume_meta=proposal["resume_meta"], resume_versions=proposal["resume_versions"],
            )
        except ResumeRevisionConflict:
            raise HTTPException(409, "简历已变化，请载入最新版本") from None
        except InvalidResumeSession:
            raise HTTPException(404, "会话不存在或已清除") from None
        except ResumeSaveUnavailable:
            raise HTTPException(503, "撤销保存失败，当前版本未更改，请重试") from None
        return {**saved, "version_id": proposal["version_id"],
                "diff": document_diff(stored["resume_data"], saved["data"]),
                "change_summary": ["已恢复到所选历史版本，事实资料和当前编辑要求保持不变。",
                                   *filter(None, [education_correction_note(stored.get("collected_info"))])],
                "workspace": build_workspace({**stored, "resume_meta": proposal["resume_meta"],
                                              "resume_versions": proposal["resume_versions"]}, saved["data"])}


@router.post("/session/{session_id}/profile-facts")
async def import_facts(session_id: str, body: ProfileImport, request: Request):
    owner = authorize_session(request, session_id)
    account = account_id(owner)
    if not account:
        raise HTTPException(401, "登录后才能使用个人档案")
    async with session_lock(session_id):
        graph = get_graph(_llm_for_graph())
        with SessionLocal() as db:
            context = get_context(db, account, subject_ids=body.fact_ids, limit=100, include_contacts=True)
            db.commit()
        if len(context["facts"]) != len(set(body.fact_ids)):
            raise HTTPException(409, "选中的资料已变化或不可使用，请刷新档案")
        snapshot = await graph.aget_state({"configurable": {"thread_id": session_id}})
        values = protect_state(owner, snapshot.values or {})
        stored = load_resume_session(session_id)
        stored["resume_data"] = protect_data(owner, stored["resume_data"])
        # Build a proposal in memory. No checkpoint mutation occurs until the
        # same save/rollback boundary as an ordinary editor change.
        bindings = []
        values["collected_info"] = context_to_collected_info(
            context, (stored["collected_info"] if stored.get("has_authoritative_state") else values.get("collected_info")),
            projection_bindings=bindings,
        )
        # Serialize selected facts rather than keeping a previous resume_data
        # projection which predates this explicit import.
        data = _serialize_to_resume_data({**values, "resume_data": {}})
        # Pending bindings are validated inside the canonical transaction, so a
        # newly imported correction can replace this item's stale dependency.

        def record(db, current, canonical):
            try:
                merge_job_version_import(db, account, session_id=session_id, fact_refs=context["fact_refs"])
            except ProfileRevisionConflict:
                raise HTTPException(409, "档案已变化，请刷新后重新选取资料") from None

        try:
            saved = await save_canonical_resume(session_id, resume_revision(stored["resume_data"]), data,
                                                graph, _serialize_to_resume_data, after_save=record,
                                                provenance_bindings=bindings, source="import",
                                                collected_info=values["collected_info"])
        except ResumeRevisionConflict:
            raise HTTPException(409, "简历已变化，请刷新后重新选取资料") from None
        return {**saved, "workspace": build_workspace(values, saved["data"]), "imported": len(context["facts"])}
