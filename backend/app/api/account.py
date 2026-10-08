"""Account routes; deliberately no automatic legacy-browser claim on login."""

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.services.account_service import (
    ACCOUNT_COOKIE, _service, assert_same_origin, optional_account,
    require_account, set_session_cookie,
)
from app.services.data_crypto import CryptoConfigurationError

router = APIRouter(prefix="/account", tags=["account"])


class LoginStart(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class LoginVerify(LoginStart):
    code: str = Field(min_length=1, max_length=12)


class ClaimGuest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)


def _client_ip(request):
    # Trust only the ASGI server's validated peer/proxy configuration.
    return request.client.host if request.client else "unknown"


@router.get("/me")
async def account_me(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    from app.config import get_settings

    settings = get_settings()
    service = getattr(request.app.state, "account_service", None)
    login_available = bool(service and service.transport.available())
    principal = await run_in_threadpool(optional_account, request)
    return {"authenticated": bool(principal),
            "account": {"id": principal.id, "email": principal.email} if principal else None,
            "login_available": login_available,
            "require_account": bool(getattr(settings, "REQUIRE_ACCOUNT", True)),
            "guest_allowed": bool(getattr(settings, "ALLOW_GUEST_EXPERIENCE", True)),
            "guest_retention_hours": getattr(settings, "GUEST_RETENTION_HOURS", 24)}


@router.post("/login/start")
async def login_start(body: LoginStart, request: Request, response: Response):
    assert_same_origin(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        service = _service(request)
    except CryptoConfigurationError:
        raise HTTPException(503, "账号安全配置尚未完成") from None
    return await run_in_threadpool(service.start, body.email, client_ip=_client_ip(request))


@router.post("/login/verify")
async def login_verify(body: LoginVerify, request: Request, response: Response):
    assert_same_origin(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        service = _service(request)
    except CryptoConfigurationError:
        raise HTTPException(503, "账号安全配置尚未完成") from None
    principal, token = await run_in_threadpool(service.verify, body.email, body.code, client_ip=_client_ip(request))
    old_token = request.cookies.get(ACCOUNT_COOKIE)
    if old_token:
        await run_in_threadpool(service.logout, old_token)
    set_session_cookie(request, response, token)
    return {"authenticated": True, "account": {"id": principal.id, "email": principal.email}}


@router.post("/logout")
async def logout(request: Request, response: Response):
    assert_same_origin(request)
    token = request.cookies.get(ACCOUNT_COOKIE)
    if token:
        await run_in_threadpool(_service(request).logout, token)
    response.delete_cookie(ACCOUNT_COOKIE, path="/")
    from app.services.conversation_store import GUEST_COOKIE
    response.delete_cookie(GUEST_COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"logged_out": True}


@router.post("/claim-guest")
async def claim_guest(body: ClaimGuest, request: Request, response: Response):
    assert_same_origin(request)
    principal = require_account(request)
    from app.services.conversation_store import (
        ConversationNotFound, GUEST_COOKIE, claim_guest as transfer_guest, guest_identity,
    )
    from sqlalchemy.orm.exc import StaleDataError
    from sqlalchemy.exc import IntegrityError

    try:
        result = await transfer_guest(guest_identity(request), principal.owner, body.session_id)
    except ConversationNotFound:
        raise HTTPException(404, "临时对话不存在、已过期或无权保存") from None
    except (StaleDataError, IntegrityError):
        raise HTTPException(409, "这份临时对话已被处理，请重试查看") from None
    response.delete_cookie(GUEST_COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/claim-browser")
async def claim_browser(request: Request, response: Response):
    assert_same_origin(request)
    principal = require_account(request)
    # No client-provided session IDs. Only an original, valid browser cookie
    # identifies claimable catalog rows. The callback must rebind encryption.
    from app.services.conversation_store import workspace_identity, WORKSPACE_COOKIE

    browser_owner = workspace_identity(request)
    if not browser_owner:
        return {"claimed": 0}
    claim = getattr(request.app.state, "claim_browser", None)
    if claim is None:
        raise HTTPException(503, "历史对话迁移尚未就绪")
    from sqlalchemy.orm.exc import StaleDataError
    from sqlalchemy.exc import IntegrityError
    try:
        result = await claim(browser_owner, principal.owner)
    except (StaleDataError, IntegrityError):
        raise HTTPException(409, "这份浏览器历史已被处理，请刷新后查看") from None
    response.delete_cookie(WORKSPACE_COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    return result if isinstance(result, dict) else {"claimed": int(result or 0)}
