"""Authenticated, account-scoped archive endpoints."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError, OperationalError

from app.agents.profile_archivist import Category, FactField
from app.database import get_db
from app.services.account_service import assert_same_origin, require_account
from app.services import profile_service as archive
from app.services.conversation_store import ConversationNotFound, assert_session_owner
from app.services.data_crypto import CryptoConfigurationError, DataDecryptionError

router = APIRouter()


class AddFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category
    subject: str = Field(min_length=1, max_length=160)
    field: FactField
    value: str = Field(min_length=1, max_length=4000)
    effective_at: datetime | None = None


class EditFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(min_length=1, max_length=4000)
    expected_revision: int = Field(ge=1)
    effective_at: datetime | None = None


class ResolveConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice: Literal["keep", "replace", "custom"]
    expected_revision: int = Field(ge=1)
    value: str | None = Field(default=None, max_length=4000)


class FactReference(BaseModel):
    fact_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)


class SaveJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    fact_refs: list[FactReference] | None = Field(default=None, max_length=500)


class RenameJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    expected_revision: int = Field(ge=1)


class ImportContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_ids: list[str] = Field(default_factory=list, max_length=100)
    include_contacts: bool = False


def _call(db, function, *args, **kwargs):
    try:
        value = function(db, *args, **kwargs)
        db.commit()
        return value
    except (archive.ProfileNotFound, ConversationNotFound):
        db.rollback()
        raise HTTPException(404, detail={"code": "not_found", "message": "资料不存在或不可访问"}) from None
    except archive.ProfileRevisionConflict:
        db.rollback()
        raise HTTPException(409, detail={"code": "revision_conflict", "message": "资料已更新，请刷新后再确认"}) from None
    except archive.ProfileValidationError:
        db.rollback()
        raise HTTPException(422, detail={"code": "invalid_archive_input", "message": "请检查填写的资料"}) from None
    except (CryptoConfigurationError, DataDecryptionError, OperationalError, IntegrityError):
        db.rollback()
        raise HTTPException(503, detail={"code": "archive_unavailable", "message": "档案暂时无法安全读取或保存，请保留输入并重试"}) from None


def _account(request):
    assert_same_origin(request)
    return require_account(request).id


@router.get("")
def profile(request: Request, db=Depends(get_db)):
    return _call(db, archive.get_profile, _account(request))


@router.post("/facts")
def add_fact(req: AddFact, request: Request, db=Depends(get_db)):
    return _call(db, archive.add_fact, _account(request), **req.model_dump())


@router.patch("/facts/{fact_id}")
def edit_fact(fact_id: str, req: EditFact, request: Request, db=Depends(get_db)):
    return _call(db, archive.edit_fact, _account(request), fact_id, **req.model_dump())


@router.delete("/facts/{fact_id}")
def delete_fact(fact_id: str, request: Request, expected_revision: int = Query(ge=1), db=Depends(get_db)):
    return _call(db, archive.delete_fact, _account(request), fact_id, expected_revision)


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(conflict_id: str, req: ResolveConflict, request: Request, db=Depends(get_db)):
    return _call(db, archive.resolve_conflict, _account(request), conflict_id, **req.model_dump())


@router.post("/tasks/{task_id}/retry")
def retry_task(task_id: str, request: Request, db=Depends(get_db)):
    return _call(db, archive.retry_task, _account(request), task_id)


@router.post("/jobs")
def save_job(req: SaveJob, request: Request, db=Depends(get_db)):
    account_id = _account(request)
    try:
        assert_session_owner(f"account:{account_id}", req.session_id)
    except ConversationNotFound:
        raise HTTPException(404, "对话不存在或不可访问") from None
    return _call(db, archive.save_job_version, account_id, **req.model_dump())


@router.patch("/jobs/{job_id}")
def rename_job(job_id: str, req: RenameJob, request: Request, db=Depends(get_db)):
    return _call(db, archive.rename_job_version, _account(request), job_id, **req.model_dump())


@router.post("/context")
def import_context(req: ImportContext, request: Request, db=Depends(get_db)):
    """Read selected facts; the chat API must pass these IDs to scoped import."""
    return _call(db, archive.get_context, _account(request), subject_ids=req.fact_ids,
                 include_contacts=req.include_contacts, limit=100)
