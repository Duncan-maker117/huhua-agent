import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Integer
from app.database import Base
from app.services.encrypted_models import encrypted_property, register_encrypted_model


def _uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String, unique=True, nullable=True)
    nickname = Column(String, nullable=True)
    industry = Column(String, default="互联网")
    created_at = Column(DateTime, default=datetime.utcnow)


class WrapperRecord(Base):
    __tablename__ = "wrapper_records"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    original_text = Column(Text, nullable=False)
    wrapped_text = Column(Text, nullable=False)
    industry = Column(String, default="互联网")
    references = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


class DecodeRecord(Base):
    __tablename__ = "decode_records"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    jd_text = Column(Text, nullable=False)
    decoded_result = Column(JSON, default=list)
    summary = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ResumeSession(Base):
    __tablename__ = "resume_sessions"

    session_id = Column(String, primary_key=True)
    owner_key = Column(String(128), default="", nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    _resume_data = Column("resume_data", JSON, nullable=False)
    _resume_draft = Column("resume_draft", Text, nullable=False)
    resume_data = encrypted_property("_resume_data", "resume_data", json_value=True, default=dict)
    resume_draft = encrypted_property("_resume_draft", "resume_draft", default="")
    stage = Column(String, default="", nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __mapper_args__ = {"version_id_col": version}

    @property
    def crypto_owner(self):
        return self.owner_key or "legacy-unowned"

    @property
    def crypto_record(self):
        return self.session_id


class Conversation(Base):
    """Browser-owned catalog; graph checkpoints remain the conversation source."""

    __tablename__ = "conversations"

    session_id = Column(String, ForeignKey("resume_sessions.session_id"), primary_key=True)
    owner_hash = Column(String(64), nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    _title = Column("title", Text, nullable=False)
    title = encrypted_property("_title", "title", default="新对话")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __mapper_args__ = {"version_id_col": version}

    @property
    def crypto_owner(self):
        return self.owner_hash

    @property
    def crypto_record(self):
        return self.session_id


register_encrypted_model(ResumeSession, [
    ("_resume_data", "resume_data", True, dict),
    ("_resume_draft", "resume_draft", False, ""),
])
register_encrypted_model(Conversation, [("_title", "title", False, "新对话")])
