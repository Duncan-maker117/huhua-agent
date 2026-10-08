from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from pathlib import Path
from app.config import get_settings


def _sqlalchemy_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


class Base(DeclarativeBase):
    pass


engine = create_engine(
    _sqlalchemy_url(get_settings().DATABASE_URL),
    connect_args=(
        {"check_same_thread": False}
        if get_settings().DATABASE_URL.startswith("sqlite")
        else {}
    ),
    hide_parameters=True,
)

SessionLocal = sessionmaker(bind=engine)


def init_db():
    """建表，启动时调用一次"""
    from app.models import models  # noqa: F401 — 确保 model 被注册
    from app.models import account, profile  # noqa: F401
    from app.models import legacy_suggestions  # noqa: F401
    from app.services import runtime_limits, profile_bridge  # noqa: F401
    from app.services.schema_migrations import require_current_schema, record_schema_version
    if engine.dialect.name == "sqlite" and engine.url.database not in (None, "", ":memory:"):
        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
    require_current_schema(engine)
    Base.metadata.create_all(bind=engine)
    record_schema_version(engine)


def get_db():
    """FastAPI 依赖：每个请求一个 session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
