"""Persistent per-owner turn budget and bounded local model concurrency."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import Column, Integer, String, update
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import Base, SessionLocal


class DailyUsage(Base):
    __tablename__ = "daily_usage"
    owner = Column(String(128), primary_key=True)
    day = Column(String(10), primary_key=True)
    turns = Column(Integer, nullable=False, default=0)


def reserve_turn(owner):
    settings = get_settings()
    guest = bool(owner and owner.startswith("guest:"))
    limit = settings.GUEST_DAILY_TURN_LIMIT if guest else settings.ACCOUNT_DAILY_TURN_LIMIT
    day = datetime.now(UTC).date().isoformat()
    with SessionLocal() as db:
        if db.get(DailyUsage, (owner, day)) is None:
            db.add(DailyUsage(owner=owner, day=day, turns=0))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
        result = db.execute(update(DailyUsage).where(
            DailyUsage.owner == owner, DailyUsage.day == day,
            DailyUsage.turns < max(0, limit),
        ).values(turns=DailyUsage.turns + 1))
        if not result.rowcount:
            db.rollback()
            now = datetime.now(UTC)
            reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            message = ("今天的游客体验次数已用完，登录后可接着整理并保存当前简历" if guest
                       else "今天的生成次数已用完，已保存的简历仍可查看和导出")
            raise HTTPException(429, message, headers={"Retry-After": str(max(1, int((reset - now).total_seconds())))})
        db.commit()
        logging.getLogger(__name__).info("model_operation_budget_reserved day=%s limit=%d", day, limit)


_slots = None
_loop = None


@asynccontextmanager
async def model_slot():
    global _slots, _loop
    loop = asyncio.get_running_loop()
    if _slots is None or _loop is not loop:
        _slots = asyncio.Semaphore(max(1, get_settings().MODEL_MAX_CONCURRENT))
        _loop = loop
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=1)
    except TimeoutError:
        raise HTTPException(503, "生成任务较多，请稍后重试") from None
    try:
        async with asyncio.timeout(get_settings().CHAT_TIMEOUT_SECONDS):
            yield
    finally:
        _slots.release()
