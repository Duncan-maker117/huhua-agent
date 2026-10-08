"""Small explicit schema migration; never implicitly rewrite personal records."""

from sqlalchemy import Column, Integer, String, inspect, text
from app.database import Base


class SchemaVersion(Base):
    __tablename__ = "schema_versions"
    component = Column(String(40), primary_key=True)
    version = Column(Integer, nullable=False)


SCHEMA_VERSION = 2


def record_schema_version(engine):
    with engine.begin() as connection:
        version = connection.execute(text("SELECT version FROM schema_versions WHERE component = 'product_profile'")).scalar()
        if version is None:
            connection.execute(text("INSERT INTO schema_versions(component, version) VALUES ('product_profile', :version)"), {"version": SCHEMA_VERSION})
        elif version != SCHEMA_VERSION:
            raise RuntimeError("Unsupported product schema version; explicit migration required")


def require_current_schema(engine):
    inspector = inspect(engine)
    if "schema_versions" in inspector.get_table_names():
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version FROM schema_versions WHERE component = 'product_profile'")).scalar()
            if version is not None and version != SCHEMA_VERSION:
                raise RuntimeError("Unsupported product schema version; explicit migration required")
    if "resume_sessions" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("resume_sessions")}
        if not {"owner_key", "version", "resume_state"}.issubset(columns):
            raise RuntimeError("Legacy database requires an explicit offline security migration; no startup writes were performed")
    if "conversations" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("conversations")}
        if "version" not in columns:
            raise RuntimeError("Conversation ownership requires an explicit offline schema migration")


def migrate_schema(engine, *, allow_legacy=False):
    """Called only on an explicitly selected migration copy, never at startup."""
    if not allow_legacy:
        require_current_schema(engine)
        return
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if "schema_versions" in tables:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version FROM schema_versions WHERE component = 'product_profile'")).scalar()
            if version not in (None, 1, SCHEMA_VERSION):
                raise RuntimeError("Unsupported product schema version; migration aborted before writes")
    if "resume_sessions" in tables:
        columns = {column["name"] for column in inspector.get_columns("resume_sessions")}
        with engine.begin() as connection:
            if "resume_state" not in columns:
                connection.execute(text("ALTER TABLE resume_sessions ADD COLUMN resume_state JSON"))
            if "owner_key" not in columns:
                connection.execute(text("ALTER TABLE resume_sessions ADD COLUMN owner_key VARCHAR(128) NOT NULL DEFAULT ''"))
            if "version" not in columns:
                connection.execute(text("ALTER TABLE resume_sessions ADD COLUMN version INTEGER NOT NULL DEFAULT 1"))
            if engine.dialect.name == "postgresql" and "conversations" in tables:
                connection.execute(text("ALTER TABLE conversations ALTER COLUMN title TYPE TEXT"))
            if "conversations" in tables:
                if "version" not in {column["name"] for column in inspector.get_columns("conversations")}:
                    connection.execute(text("ALTER TABLE conversations ADD COLUMN version INTEGER NOT NULL DEFAULT 1"))
                connection.execute(text("UPDATE resume_sessions SET owner_key = (SELECT owner_hash FROM conversations WHERE conversations.session_id = resume_sessions.session_id) WHERE owner_key = '' AND EXISTS (SELECT 1 FROM conversations WHERE conversations.session_id = resume_sessions.session_id)"))
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("UPDATE schema_versions SET version = :version WHERE component = 'product_profile' AND version = 1"), {"version": SCHEMA_VERSION})
    record_schema_version(engine)
