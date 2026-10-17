"""PAT authentication and process-local quotas/audit. Never log request bodies."""

import asyncio
import hashlib
import logging
import re
import secrets
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from threading import Lock

from fastapi import HTTPException
from sqlalchemy import select, update
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.models.account import Account, PersonalAccessToken
from app.services.account_service import AccountPrincipal, _now

logger = logging.getLogger(__name__)

SCOPES = frozenset({'profile:read', 'profile:contacts', 'profile:propose',
                    'resume:read', 'resume:write', 'resume:export'})
DEFAULT_SCOPES = sorted(SCOPES - {'profile:contacts'})
PAT_PATTERN = re.compile(r'^hh_pat_[A-Za-z0-9_-]{43}$')
TOOL_SCOPES = {
    'huhua_profile_get': 'profile:read', 'huhua_templates_list': None,
    'huhua_resume_get': 'resume:read', 'huhua_resume_measure': None,
    'huhua_resume_export': 'resume:export', 'huhua_facts_propose': 'profile:propose',
    'huhua_resume_check_facts': 'profile:read', 'huhua_resume_save': 'resume:write',
    # 提交文稿预览无需额外 scope；读取保存稿在服务层另查 resume:read。
    'huhua_writing_guide': None, 'huhua_resume_preview': None,
}


@dataclass(frozen=True)
class TokenPrincipal:
    account: AccountPrincipal
    token_id: str
    scopes: frozenset[str]


def token_view(row):
    def iso(value):
        return value.isoformat() + 'Z' if value else None
    return {key: getattr(row, key) for key in ('id', 'name', 'scopes')} | {
        key: iso(getattr(row, key)) for key in ('created_at', 'expires_at', 'last_used_at', 'revoked_at')}


class TokenService:
    def __init__(self, session_factory, *, clock=_now):
        self.session_factory, self.clock = session_factory, clock

    def create(self, account_id, name, scopes=None, expires_days=90):
        scopes = DEFAULT_SCOPES if scopes is None else scopes
        if not name.strip() or len(name) > 80 or not set(scopes) <= SCOPES or not 1 <= expires_days <= 365:
            raise HTTPException(422, '令牌名称、权限或有效期不正确')
        token = 'hh_pat_' + secrets.token_urlsafe(32)
        now = self.clock()
        with self.session_factory() as db:
            if db.get(Account, account_id) is None:
                raise HTTPException(401, '请先登录')
            row = PersonalAccessToken(id=str(uuid.uuid4()), account_id=account_id, name=name.strip(),
                                      token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                      scopes=sorted(set(scopes)), created_at=now,
                                      expires_at=now + timedelta(days=expires_days))
            db.add(row)
            db.flush()
            result = {'token': token, **token_view(row)}
            db.commit()
            return result

    def list(self, account_id):
        with self.session_factory() as db:
            return [token_view(row) for row in db.scalars(select(PersonalAccessToken).where(
                PersonalAccessToken.account_id == account_id).order_by(PersonalAccessToken.created_at.desc()))]

    def revoke(self, account_id, token_id):
        with self.session_factory() as db:
            row = db.scalar(select(PersonalAccessToken).where(PersonalAccessToken.id == token_id,
                            PersonalAccessToken.account_id == account_id))
            if row is None:
                raise HTTPException(404, '令牌不存在')
            row.revoked_at = row.revoked_at or self.clock()
            db.commit()
        return {'revoked': True}

    def authenticate(self, header):
        scheme, _, token = (header or '').partition(' ')
        if scheme.lower() != 'bearer' or not PAT_PATTERN.fullmatch(token):
            return None
        now = self.clock()
        with self.session_factory() as db:
            row = db.scalar(select(PersonalAccessToken).where(
                PersonalAccessToken.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                PersonalAccessToken.revoked_at.is_(None), PersonalAccessToken.expires_at > now))
            if row is None or db.get(Account, row.account_id) is None:
                return None
            principal = TokenPrincipal(AccountPrincipal(row.account_id, ''), row.id, frozenset(row.scopes))
            changed = db.execute(update(PersonalAccessToken).where(
                PersonalAccessToken.id == row.id, PersonalAccessToken.revoked_at.is_(None),
                PersonalAccessToken.expires_at > now).values(last_used_at=now))
            db.commit()
            return principal if changed.rowcount == 1 else None


class RateLimiter:
    """Sliding windows bound bursts too; shared by all requests in this process."""
    def __init__(self, clock=time.monotonic):
        self.clock, self.buckets, self.lock = clock, {}, Lock()

    def take(self, token_id, kind, limit, seconds, count=1):
        now = self.clock()
        with self.lock:
            # Each record has its own lifetime; inactive/revoked tokens cannot
            # accumulate unbounded minute buckets across a long-lived process.
            for key, (expires, _) in list(self.buckets.items()):
                if expires <= now:
                    del self.buckets[key]
            key = (token_id, kind)
            _, entries = self.buckets.setdefault(key, (now + seconds, deque()))
            while entries and entries[0][0] <= now - seconds:
                entries.popleft()
            if count < 1 or sum(amount for _, amount in entries) + count > limit:
                raise HTTPException(429, '调用过于频繁，请稍后重试')
            entries.append((now, count))
            self.buckets[key] = (now + seconds, entries)


class AuditLog:
    """Bounded process-local metadata only; restarts clear the recent history."""
    def __init__(self):
        self.rows, self.lock = deque(maxlen=10000), Lock()

    def record(self, token_id, tool, duration_ms, status_code):
        row = {'token_id': token_id, 'tool': tool if tool in TOOL_SCOPES else 'unknown',
               'duration_ms': duration_ms, 'status_code': status_code,
               'called_at': _now().isoformat() + 'Z'}
        with self.lock:
            self.rows.append(row)
        logger.info('mcp_call token_id=%s tool=%s duration_ms=%d status_code=%d',
                    row['token_id'], row['tool'], row['duration_ms'], row['status_code'])

    def recent(self, token_ids):
        with self.lock:
            return [dict(row) for row in reversed(self.rows) if row['token_id'] in token_ids][:50]


limiter = RateLimiter()
audit = AuditLog()


class BearerAuthMiddleware:
    def __init__(self, app, token_service, rate_limiter=limiter):
        self.app, self.tokens, self.limiter = app, token_service, rate_limiter

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        try:
            principal = await asyncio.to_thread(self.tokens.authenticate, request.headers.get('authorization'))
            if principal is None:
                raise HTTPException(401, '需要有效的个人访问令牌', headers={'WWW-Authenticate': 'Bearer'})
            self.limiter.take(principal.token_id, 'requests', 60, 60)
        except HTTPException as error:
            await JSONResponse({'detail': error.detail}, status_code=error.status_code,
                               headers={'Cache-Control': 'no-store', **(error.headers or {}),
                                        **({'Retry-After': '60'} if error.status_code == 429 else {})})(scope, receive, send)
            return
        except Exception:
            await JSONResponse({'detail': '令牌验证暂不可用'}, status_code=503)(scope, receive, send)
            return
        scope.setdefault('state', {})['mcp_principal'] = principal
        async def private_response(message):
            if message['type'] == 'http.response.start':
                message = {**message, 'headers': [
                    (key, value) for key, value in message.get('headers', []) if key.lower() != b'cache-control'
                ] + [(b'cache-control', b'private, no-store')]}
            await send(message)
        await self.app(scope, receive, private_response)
