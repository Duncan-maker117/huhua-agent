"""Account tables. Contact values are encrypted; lookup and session tokens hashed."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database import Base


class Account(Base):
    __tablename__ = "accounts"
    id = Column(String(36), primary_key=True)
    email_index = Column(String(64), unique=True, nullable=False, index=True)
    email_ciphertext = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AccountSession(Base):
    __tablename__ = "account_sessions"
    token_hash = Column(String(64), primary_key=True)
    account_id = Column(String(36), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)


class LoginChallenge(Base):
    __tablename__ = "account_login_challenges"
    email_index = Column(String(64), primary_key=True)
    challenge_id = Column(String(36), nullable=False)
    code_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)


class AuthRateBucket(Base):
    __tablename__ = "account_auth_rate_buckets"
    bucket_key = Column(String(64), primary_key=True)
    count = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=False, index=True)
