"""Retired suggestion records retained only for secure migration and deletion."""
from datetime import datetime
from sqlalchemy import Column, DateTime, String, JSON
from app.database import Base
from app.services.encrypted_models import encrypted_property, register_encrypted_model


class ResumeSuggestion(Base):
    __tablename__ = "resume_suggestions"
    id = Column(String(36), primary_key=True)
    owner = Column(String(128), nullable=False, index=True)
    session_id = Column(String(128), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")
    _payload = Column("payload", JSON, nullable=False)
    payload = encrypted_property("_payload", "suggestion", json_value=True, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    @property
    def crypto_owner(self):
        return self.owner

    @property
    def crypto_record(self):
        return self.id


register_encrypted_model(ResumeSuggestion, [("_payload", "suggestion", True, dict)])
