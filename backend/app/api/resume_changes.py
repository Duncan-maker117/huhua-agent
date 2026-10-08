"""Explicit, revision-checked resume edits and selected archive imports."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents.resume_graph import _serialize_to_resume_data
from app.api.resume import _llm_for_graph, get_graph
from app.database import SessionLocal
from app.services.access_control import authorize_session
from app.services.canonical_resume import ResumeRevisionConflict, editor_facts, resume_revision, save_canonical_resume
from app.services.profile_bridge import account_id, protect_data, protect_state
from app.services.profile_service import context_to_collected_info, get_context, merge_job_version_import, ProfileRevisionConflict
from app.services.resume_suggestions import apply_suggestion, generate_suggestion, preview_suggestion
from app.services.resume_workspace import build_workspace
from app.services.session_store import load_resume_session, session_lock

router = APIRouter()


class SuggestionPreview(BaseModel):
    source_text: str = Field(min_length=1, max_length=4000)
    suggested_text: str = Field(min_length=1, max_length=4000)


class SuggestionGenerate(BaseModel):
    source_text: str = Field(min_length=1, max_length=4000)
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    instruction: str | None = Field(default=None, max_length=1000)


class SuggestionApply(BaseModel):
    suggestion_id: str = Field(min_length=1, max_length=64)
    expected_revision: str = Field(min_length=64, max_length=64)


class SuggestionUndo(BaseModel):
    change_id: str = Field(min_length=1, max_length=64)
    expected_revision: str = Field(min_length=64, max_length=64)


class ProfileImport(BaseModel):
    fact_ids: list[str] = Field(min_length=1, max_length=100)


@router.post("/session/{session_id}/suggestions/preview")
async def preview(session_id: str, body: SuggestionPreview, request: Request):
    owner = authorize_session(request, session_id)
    protect_data(owner, body.model_dump(), reject=True)
    async with session_lock(session_id):
        owner = authorize_session(request, session_id)
        return await preview_suggestion(owner, session_id, body.source_text, body.suggested_text, _llm_for_graph())


@router.post("/session/{session_id}/suggestions/generate")
async def generate(session_id: str, body: SuggestionGenerate, request: Request):
    owner = authorize_session(request, session_id)
    protect_data(owner, body.model_dump(), reject=True)
    async with session_lock(session_id):
        owner = authorize_session(request, session_id)
        return await generate_suggestion(owner, session_id, body.source_text, body.expected_revision,
                                         body.instruction, _llm_for_graph())


async def _apply(request, session_id, change_id, revision, undo=False):
    owner = authorize_session(request, session_id)
    async with session_lock(session_id):
        owner = authorize_session(request, session_id)
        try:
            result = await apply_suggestion(owner, session_id, change_id, revision,
                                            get_graph(_llm_for_graph()), _serialize_to_resume_data, undo=undo)
            result["workspace"] = build_workspace({}, result["data"])
            return result
        except ResumeRevisionConflict:
            raise HTTPException(409, "简历已变化，请载入最新版本") from None


@router.post("/session/{session_id}/suggestions/apply")
async def apply(session_id: str, body: SuggestionApply, request: Request):
    return await _apply(request, session_id, body.suggestion_id, body.expected_revision)


@router.post("/session/{session_id}/suggestions/undo")
async def undo(session_id: str, body: SuggestionUndo, request: Request):
    return await _apply(request, session_id, body.change_id, body.expected_revision, undo=True)


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
            context, editor_facts(stored["resume_data"], values.get("collected_info")),
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
                                                provenance_bindings=bindings)
        except ResumeRevisionConflict:
            raise HTTPException(409, "简历已变化，请刷新后重新选取资料") from None
        return {**saved, "workspace": build_workspace(values, saved["data"]), "imported": len(context["facts"])}
