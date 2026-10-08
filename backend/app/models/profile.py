"""Account-scoped archive. User content lives only in encrypted payload columns."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint

from app.database import Base


def new_id():
    return str(uuid.uuid4())


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


class PersonalProfile(Base):
    __tablename__ = "personal_profiles"
    id = Column(String, primary_key=True, default=new_id)
    account_id = Column(String, nullable=False, unique=True, index=True)
    revision = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class ProfileFact(Base):
    __tablename__ = "profile_facts"
    __table_args__ = (UniqueConstraint("account_id", "slot_key"),)
    id = Column(String, primary_key=True, default=new_id)
    account_id = Column(String, nullable=False, index=True)
    slot_key = Column(String(64), nullable=False)
    category = Column(String(24), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    status = Column(String(24), nullable=False, default="active")
    payload = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=utc_now)


class ProfileSource(Base):
    __tablename__ = "profile_sources"
    __table_args__ = (UniqueConstraint("account_id", "source_key"),)
    id = Column(String, primary_key=True, default=new_id)
    account_id = Column(String, nullable=False, index=True)
    source_key = Column(String(64), nullable=False)
    session_id = Column(String, nullable=True, index=True)
    kind = Column(String(24), nullable=False)
    disabled = Column(Boolean, nullable=False, default=False)
    payload = Column(Text, nullable=False)
    recorded_at = Column(DateTime, nullable=False, default=utc_now)


class ProfileConflict(Base):
    __tablename__ = "profile_conflicts"
    __table_args__ = (UniqueConstraint("account_id", "event_id", "fact_id"),)
    id = Column(String, primary_key=True, default=new_id)
    account_id = Column(String, nullable=False, index=True)
    fact_id = Column(String, nullable=False, index=True)
    event_id = Column(String, nullable=False)
    expected_revision = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, default="pending")
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class ProfileJobVersion(Base):
    __tablename__ = "profile_job_versions"
    __table_args__ = (UniqueConstraint("account_id", "session_id"),)
    id = Column(String, primary_key=True, default=new_id)
    account_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    stale = Column(Boolean, nullable=False, default=False)
    payload = Column(Text, nullable=False)


class ProfileArchiveEvent(Base):
    """Durable outbox: register in the transaction that saves the human input."""
    __tablename__ = "profile_archive_events"
    __table_args__ = (UniqueConstraint("account_id", "source_id", "event_type"),)
    id = Column(String, primary_key=True, default=new_id)
    account_id = Column(String, nullable=False, index=True)
    source_id = Column(String, nullable=False, index=True)
    event_type = Column(String(24), nullable=False)
    status = Column(String(24), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    error_code = Column(String(64), nullable=False, default="")
    lease_token = Column(String, nullable=True)
    lease_until = Column(DateTime, nullable=True)
    available_at = Column(DateTime, nullable=False, default=utc_now)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    completed_at = Column(DateTime, nullable=True)


class ProfileInvalidation(Base):
    """Persistent erasure/correction barrier, also consulted after backup restore.

    The encrypted value plus category/subject/field scopes old projections.
    This exclusion record is not retrievable as a fact or sent to the model.
    """
    __tablename__ = "profile_invalidations"
    id = Column(String, primary_key=True, default=new_id)
    account_id = Column(String, nullable=False, index=True)
    fact_id = Column(String, nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    reason = Column(String(24), nullable=False)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
