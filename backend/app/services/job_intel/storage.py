"""按日期缓存公开资料；原子预留会话/每日额度，失败尝试也占护栏。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Column, Integer, JSON, String, select, update
from sqlalchemy.exc import IntegrityError

from app.database import Base, SessionLocal


class IntelCache(Base):
    __tablename__ = "job_intel_cache"
    kind = Column(String(20), primary_key=True)
    normalized_key = Column(String(64), primary_key=True)
    day = Column(String(10), primary_key=True)
    payload = Column(JSON, nullable=False)


class IntelUsage(Base):
    __tablename__ = "job_intel_usage"
    scope = Column(String(128), primary_key=True)
    kind = Column(String(20), primary_key=True)
    day = Column(String(10), primary_key=True)
    calls = Column(Integer, nullable=False, default=0)


def today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def normalized_key(value: str) -> str:
    # URL 路径区分大小写，由调用层规范化；公司/方向先折叠空白和大小写。
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, sessions=None):
        self.sessions = sessions or SessionLocal

    def get(self, kind, key, days):
        now = today()
        with self.sessions() as db:
            row = db.execute(
                select(IntelCache)
                .where(
                    IntelCache.kind == kind,
                    IntelCache.normalized_key == normalized_key(key),
                    IntelCache.day > (now - timedelta(days=days)).isoformat(),
                    IntelCache.day <= now.isoformat(),
                )
                .order_by(IntelCache.day.desc())
                .limit(1)
            ).scalar_one_or_none()
            return row.payload if row else None

    def put(self, kind, key, payload):
        with self.sessions() as db:
            db.merge(
                IntelCache(
                    kind=kind,
                    normalized_key=normalized_key(key),
                    day=today().isoformat(),
                    payload=payload,
                )
            )
            db.commit()

    def reserve(self, scope, kind, limit, *, daily=False):
        day = today().isoformat() if daily else "session"
        scope = normalized_key(scope)
        with self.sessions() as db:
            if db.get(IntelUsage, (scope, kind, day)) is None:
                db.add(IntelUsage(scope=scope, kind=kind, day=day, calls=0))
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
            result = db.execute(
                update(IntelUsage)
                .where(
                    IntelUsage.scope == scope,
                    IntelUsage.kind == kind,
                    IntelUsage.day == day,
                    IntelUsage.calls < max(0, limit),
                )
                .values(calls=IntelUsage.calls + 1)
            )
            db.commit()
            return bool(result.rowcount)
