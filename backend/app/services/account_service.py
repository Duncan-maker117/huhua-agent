"""Email OTP authentication; all mutation counters and sessions are durable.

The injectable transport is only for tests. Production responses and logs never
contain a login code. A stable ACCOUNT_SECRET is separate from rotating data keys.
"""

import base64
import hashlib
import hmac
import math
import re
import secrets
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.models.account import Account, AccountSession, AuthRateBucket, LoginChallenge
from app.services.data_crypto import CryptoConfigurationError, DataCrypto, crypto_from_settings

ACCOUNT_COOKIE = "huhua_account"
SESSION_SECONDS = 30 * 24 * 3600
CODE_SECONDS = 10 * 60
CODE_ATTEMPTS = 5
EMAIL_PATTERN = re.compile(r"^[^\s@]{1,64}@[^\s@.]+(?:\.[^\s@.]+)+$")
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,128}$")
OTP_SUBJECT = "胡话简历登录验证码"


def _otp_body(code: str) -> str:
    return f"你的登录验证码是 {code}，10 分钟内有效。如非本人操作，请忽略。"


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_naive(value: datetime) -> datetime:
    """The database stores UTC-naive timestamps, including injected clocks."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None)


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
        raise HTTPException(422, "请输入有效邮箱")
    return email


def _secret(settings) -> bytes:
    try:
        value = base64.b64decode(getattr(settings, "ACCOUNT_SECRET", ""), altchars=b"-_", validate=True)
        if len(value) < 32:
            raise ValueError("Secret too short")
        return value
    except (TypeError, ValueError) as exc:
        raise CryptoConfigurationError("ACCOUNT_SECRET must be a stable, separately backed-up 32-byte secret") from exc


def _digest(secret: bytes, value: str, scope: str) -> str:
    return hmac.new(secret, (scope + "\x00" + value).encode(), hashlib.sha256).hexdigest()


def blind_index(value: str, *, scope: str) -> str:
    from app.config import get_settings

    return _digest(_secret(get_settings()), value, scope)


@dataclass(frozen=True)
class AccountPrincipal:
    id: str
    email: str

    @property
    def owner(self):
        return "account:" + self.id


class SMTPTransport:
    def __init__(self, settings):
        self.settings = settings

    def configuration_status(self) -> dict:
        """Safe configuration diagnostics; never expose any configured value.

        This verifies configuration presence only, not provider authorization,
        sender-domain verification or inbox delivery.
        """
        missing = [name for name in ("SMTP_HOST", "SMTP_FROM", "SMTP_USERNAME", "SMTP_PASSWORD")
                   if not str(getattr(self.settings, name, "") or "").strip()]
        invalid = []
        if not getattr(self.settings, "SMTP_STARTTLS", True):
            invalid.append("SMTP_STARTTLS")
        port = getattr(self.settings, "SMTP_PORT", 587)
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            invalid.append("SMTP_PORT")
        return {"available": not missing and not invalid, "missing": missing,
                "invalid": invalid, "transport": "smtp_starttls", "provider": "smtp"}

    def available(self) -> bool:
        return self.configuration_status()["available"]

    def send(self, email: str, code: str):
        settings = self.settings
        if not self.available():
            raise HTTPException(503, "邮箱登录尚未配置，请联系服务维护者")
        if not getattr(settings, "SMTP_STARTTLS", True):
            raise HTTPException(503, "邮件传输必须启用 TLS")
        message = EmailMessage()
        message["From"] = settings.SMTP_FROM
        message["To"] = email
        message["Subject"] = OTP_SUBJECT
        message.set_content(_otp_body(code))
        try:
            with smtplib.SMTP(settings.SMTP_HOST, getattr(settings, "SMTP_PORT", 587), timeout=10) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                refused = smtp.send_message(message)
                if refused:
                    raise smtplib.SMTPException("Recipient not accepted")
        except (OSError, smtplib.SMTPException) as exc:
            # No SMTP exception details: recipients, credentials or codes can be embedded.
            raise HTTPException(503, "验证码暂时发送失败，请稍后重试") from exc


class ResendTransport:
    """Fixed HTTPS delivery endpoint; never follows redirects or retries mail."""

    def __init__(self, settings):
        self.settings = settings

    def configuration_status(self) -> dict:
        missing = [name for name in ("RESEND_API_KEY", "RESEND_FROM")
                   if not str(getattr(self.settings, name, "") or "").strip()]
        return {"available": not missing, "missing": missing, "invalid": [],
                "transport": "resend_https", "provider": "resend"}

    def available(self) -> bool:
        return self.configuration_status()["available"]

    def send(self, email: str, code: str):
        if not self.available():
            raise HTTPException(503, "邮箱登录尚未配置，请联系服务维护者")
        try:
            # A fresh client keeps credentials scoped to this request. The fixed
            # host and disabled redirects prevent forwarding them to another URL.
            with httpx.Client(verify=True, timeout=10.0, follow_redirects=False) as client:
                response = client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": "Bearer " + self.settings.RESEND_API_KEY,
                             "Content-Type": "application/json"},
                    json={"from": self.settings.RESEND_FROM, "to": [email],
                          "subject": OTP_SUBJECT, "text": _otp_body(code)},
                )
            if not 200 <= response.status_code < 300:
                raise ValueError("Mail provider did not accept request")
            payload = response.json()
            identifier = payload.get("id") if isinstance(payload, dict) else None
            if not isinstance(identifier, str) or not identifier.strip():
                raise ValueError("Missing mail provider ID")
            # Resend's accepted-send contract returns a UUID. An HTML error page
            # or malformed 2xx response must never masquerade as delivery.
            uuid.UUID(identifier)
        except (httpx.HTTPError, ValueError, TypeError):
            # Raw provider responses and exception strings may contain recipient
            # addresses, API keys or message bodies. Do not attach or log them.
            raise HTTPException(503, "验证码暂时发送失败，请稍后重试") from None


class AccountService:
    def __init__(self, session_factory, settings, *, crypto: DataCrypto | None = None, transport=None, clock=_now):
        self.session_factory = session_factory
        self.settings = settings
        self.crypto = crypto or crypto_from_settings(settings)
        self.secret = _secret(settings)
        if not self.crypto.enabled:
            raise CryptoConfigurationError("Accounts require encrypted storage, even in local mode")
        self._mail_limit("AUTH_EMAIL_DAILY_LIMIT", 90)
        self._mail_limit("AUTH_EMAIL_MONTHLY_LIMIT", 2800)
        if transport is not None:
            self.transport = transport
        elif getattr(settings, "EMAIL_PROVIDER", "smtp") == "resend":
            self.transport = ResendTransport(settings)
        elif getattr(settings, "EMAIL_PROVIDER", "smtp") == "smtp":
            self.transport = SMTPTransport(settings)
        else:
            raise CryptoConfigurationError("EMAIL_PROVIDER must be smtp or resend")
        self.clock = clock

    def mail_configuration_status(self) -> dict:
        status_fn = getattr(self.transport, "configuration_status", None)
        status = status_fn() if status_fn else {"available": self.transport.available(), "missing": [], "invalid": []}
        return {**status, "daily_limit": self._mail_limit("AUTH_EMAIL_DAILY_LIMIT", 90),
                "monthly_limit": self._mail_limit("AUTH_EMAIL_MONTHLY_LIMIT", 2800),
                "quota_timezone": "UTC", "counts": "send_attempts"}

    def _mail_limit(self, name: str, default: int) -> int:
        # Runtime guard also protects injected settings and config loaders that
        # do not instantiate the Pydantic Settings class.
        value = getattr(self.settings, name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise CryptoConfigurationError(f"{name} must be a positive integer")
        return value

    def email_index(self, email: str) -> str:
        return _digest(self.secret, normalize_email(email), "account-email")

    def _rate(self, db, *, scope: str, identity: str, seconds: int, limit: int):
        now = _utc_naive(self.clock())
        window = int(now.replace(tzinfo=timezone.utc).timestamp()) // seconds
        key = _digest(self.secret, f"{identity}:{window}", "rate:" + scope)
        # A savepoint contains an insert collision; the following conditional
        # increment is atomic across processes, unlike a Python lock.
        try:
            with db.begin_nested():
                db.execute(insert(AuthRateBucket).values(bucket_key=key, count=0, expires_at=now + timedelta(seconds=seconds * 2)))
        except IntegrityError:
            pass
        result = db.execute(update(AuthRateBucket).where(
            AuthRateBucket.bucket_key == key, AuthRateBucket.count < limit
        ).values(count=AuthRateBucket.count + 1))
        if result.rowcount != 1:
            raise HTTPException(429, "尝试过于频繁，请稍后重试")

    def _reserve_mail_budget(self, db, now: datetime):
        """Reserve both durable global limits before contacting the provider.

        Distinct UTC calendar identifiers avoid fixed-30-day month drift. The
        caller commits this alongside OTP/rate limits. Provider failure deliberately
        does not refund the reservation: provider acceptance may be ambiguous.
        """
        day_end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        month_end = (now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                     if now.month == 12 else
                     now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0))
        windows = (
            ("day", now.strftime("%Y-%m-%d"), day_end, self._mail_limit("AUTH_EMAIL_DAILY_LIMIT", 90), "本日"),
            ("month", now.strftime("%Y-%m"), month_end, self._mail_limit("AUTH_EMAIL_MONTHLY_LIMIT", 2800), "本月"),
        )
        # Derive an independent, domain-separated key without another deployed
        # secret. Neither provider credentials nor raw IP/email enter this key.
        budget_secret = hmac.new(self.secret, b"huhua:email-send-budget:v1", hashlib.sha256).digest()
        for period, window, reset_at, limit, label in windows:
            key = _digest(budget_secret, window, "send-attempts:" + period)
            try:
                with db.begin_nested():
                    db.execute(insert(AuthRateBucket).values(bucket_key=key, count=0, expires_at=reset_at))
            except IntegrityError:
                pass
            result = db.execute(update(AuthRateBucket).where(
                AuthRateBucket.bucket_key == key, AuthRateBucket.count < limit
            ).values(count=AuthRateBucket.count + 1))
            if result.rowcount != 1:
                retry_after = max(1, math.ceil((reset_at - now).total_seconds()))
                raise HTTPException(429,
                    f"{label}验证码邮件额度已用完，请在 {reset_at:%Y-%m-%d %H:%M:%S} UTC 后重试",
                    headers={"Retry-After": str(retry_after),
                             "X-RateLimit-Reset": str(int(reset_at.replace(tzinfo=timezone.utc).timestamp()))})

    def start(self, email: str, *, client_ip: str):
        email = normalize_email(email)
        if not self.transport.available():
            raise HTTPException(503, "邮箱登录尚未配置，请联系服务维护者")
        now = _utc_naive(self.clock())
        index = self.email_index(email)
        challenge_id = str(uuid.uuid4())
        code = f"{secrets.randbelow(1_000_000):06d}"
        code_hash = _digest(self.secret, code, "otp:" + challenge_id)
        with self.session_factory() as db:
            self._rate(db, scope="start-email-minute", identity=index, seconds=60, limit=1)
            self._rate(db, scope="start-email-hour", identity=index, seconds=3600, limit=5)
            self._rate(db, scope="start-ip-hour", identity=client_ip, seconds=3600, limit=20)
            self._reserve_mail_budget(db, now)
            db.execute(delete(LoginChallenge).where(LoginChallenge.email_index == index))
            db.add(LoginChallenge(email_index=index, challenge_id=challenge_id, code_hash=code_hash,
                                  created_at=now, expires_at=now + timedelta(seconds=CODE_SECONDS), attempts=0))
            db.execute(delete(AuthRateBucket).where(AuthRateBucket.expires_at < now))
            db.commit()
        try:
            self.transport.send(email, code)
        except Exception:
            with self.session_factory() as db:
                db.execute(delete(LoginChallenge).where(LoginChallenge.email_index == index, LoginChallenge.challenge_id == challenge_id))
                db.commit()
            raise
        # "sent" is retained for existing clients and means submitted to the provider,
        # not confirmed delivery to a recipient's mailbox.
        return {"sent": True, "delivery_status": "provider_accepted",
                "message": "验证码已提交邮件服务，请检查收件箱或垃圾邮件。",
                "expires_in": CODE_SECONDS, "retry_after": 60}

    def verify(self, email: str, code: str, *, client_ip: str) -> tuple[AccountPrincipal, str]:
        email = normalize_email(email)
        index = self.email_index(email)
        now = _utc_naive(self.clock())
        invalid = HTTPException(400, "验证码无效或已过期，请重新获取")
        with self.session_factory() as db:
            self._rate(db, scope="verify-ip-hour", identity=client_ip, seconds=3600, limit=60)
            challenge = db.get(LoginChallenge, index)
            if not challenge or challenge.used_at or challenge.expires_at <= now or challenge.attempts >= CODE_ATTEMPTS:
                db.commit()
                raise invalid
            matches = bool(re.fullmatch(r"\d{6}", code)) and hmac.compare_digest(
                challenge.code_hash, _digest(self.secret, code, "otp:" + challenge.challenge_id)
            )
            # Optimistic attempt/consumption CAS prevents two successes/replays
            # and prevents simultaneous bad guesses escaping the attempt cap.
            values = {"attempts": LoginChallenge.attempts + 1}
            if matches:
                values["used_at"] = now
            result = db.execute(update(LoginChallenge).where(
                LoginChallenge.email_index == index, LoginChallenge.challenge_id == challenge.challenge_id,
                LoginChallenge.attempts == challenge.attempts, LoginChallenge.used_at.is_(None),
                LoginChallenge.expires_at > now,
            ).values(**values))
            if result.rowcount != 1 or not matches:
                db.commit()
                raise invalid
            account = db.execute(select(Account).where(Account.email_index == index)).scalar_one_or_none()
            if account is None:
                account_id = str(uuid.uuid4())
                account = Account(id=account_id, email_index=index, email_ciphertext=self.crypto.encrypt_text(
                    email, owner="account:" + account_id, record=account_id, field="email"))
                db.add(account)
                db.flush()
            token = secrets.token_urlsafe(32)
            db.add(AccountSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), account_id=account.id,
                                  created_at=now, expires_at=now + timedelta(seconds=SESSION_SECONDS)))
            db.execute(delete(AccountSession).where(AccountSession.expires_at < now))
            db.commit()
            return AccountPrincipal(account.id, email), token

    def authenticate(self, token: str) -> AccountPrincipal | None:
        if not TOKEN_PATTERN.fullmatch(token):
            return None
        with self.session_factory() as db:
            session = db.get(AccountSession, hashlib.sha256(token.encode()).hexdigest())
            if not session or session.expires_at <= _utc_naive(self.clock()):
                return None
            account = db.get(Account, session.account_id)
            if not account:
                return None
            email = self.crypto.decrypt_text(account.email_ciphertext, owner="account:" + account.id, record=account.id, field="email")
            return AccountPrincipal(account.id, email)

    def logout(self, token: str):
        with self.session_factory() as db:
            db.execute(delete(AccountSession).where(AccountSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
            db.commit()


def get_account_service() -> AccountService:
    from app.config import get_settings
    from app.database import SessionLocal

    return AccountService(SessionLocal, get_settings())


def _service(request):
    return getattr(request.app.state, "account_service", None) or get_account_service()


def optional_account(request) -> AccountPrincipal | None:
    token = request.cookies.get(ACCOUNT_COOKIE, "")
    if not token:
        return None
    try:
        return _service(request).authenticate(token)
    except CryptoConfigurationError:
        raise HTTPException(503, "账号安全配置不可用") from None


def require_account(request) -> AccountPrincipal:
    principal = optional_account(request)
    if principal is None:
        raise HTTPException(401, "请先登录")
    return principal


def resolve_owner(request, response=None, *, allow_guest=False) -> str | None:
    principal = optional_account(request)
    if principal:
        return principal.owner
    from app.config import get_settings

    settings = get_settings()
    from app.services.conversation_store import workspace_identity
    if getattr(settings, "APP_ENV", "local").lower() == "local" and not getattr(settings, "REQUIRE_ACCOUNT", True):
        return workspace_identity(request, response)
    if allow_guest and getattr(settings, "ALLOW_GUEST_EXPERIENCE", True):
        from app.services.conversation_store import guest_identity
        return guest_identity(request, response)
    raise HTTPException(401, "请先登录")


def _origin(value: str) -> tuple[str, str, int] | None:
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
        return parts.scheme, parts.hostname.lower(), parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None


def assert_same_origin(request):
    """Browser cookie writes require a matching Origin; CLI may omit it locally.

    Reverse-proxy deployments must configure APP_ORIGIN instead of trusting a
    caller-supplied Host or forwarded header as the production CSRF boundary.
    """
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    from app.config import get_settings

    settings = get_settings()
    production = getattr(settings, "APP_ENV", "local").lower() != "local"
    expected = getattr(settings, "APP_ORIGIN", "")
    if production and (not expected or not expected.startswith("https://")):
        raise HTTPException(503, "服务来源安全配置不可用")
    origin = request.headers.get("origin", "")
    fetch_site = request.headers.get("sec-fetch-site", "")
    if fetch_site in {"cross-site", "same-site"}:
        raise HTTPException(403, "请求来源不受信任")
    if origin:
        if _origin(origin) is None or _origin(origin) != _origin(expected or str(request.base_url)):
            raise HTTPException(403, "请求来源不受信任")
    elif production or fetch_site:
        # Real browsers send Origin for state-changing fetch. Lack of Origin
        # is only tolerated by explicit local tooling, never in production.
        raise HTTPException(403, "缺少请求来源")


def set_session_cookie(request, response, token: str):
    settings = _service(request).settings
    secure = getattr(settings, "AUTH_COOKIE_SECURE", True)
    if getattr(settings, "APP_ENV", "local").lower() != "local" and not secure:
        raise HTTPException(503, "生产账号会话必须使用安全 Cookie")
    response.set_cookie(ACCOUNT_COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=secure, samesite="lax", path="/")
