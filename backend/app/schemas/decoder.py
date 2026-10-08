from typing import Literal

from pydantic import BaseModel, Field, model_validator
from datetime import datetime


class DecoderRequest(BaseModel):
    jd_text: str
    user_id: str | None = None


class DecodedItem(BaseModel):
    keyword: str
    surface_meaning: str
    real_meaning: str


class KeywordCloud(BaseModel):
    core_keywords: list[str] = []
    secondary_keywords: list[str] = []
    industry_keywords: list[str] = []


class ResumeStrategy(BaseModel):
    must_highlight: list[str] = []
    recommended_format: str = ""
    keyword_density_targets: list[str] = []


class RequirementEvidence(BaseModel):
    text: str
    category: str
    source_quote: str
    verification_question: str = ""


RoleFamily = Literal[
    "ai_pm", "pm", "backend", "frontend", "algorithm", "data", "ops", "design", "other"
]
Seniority = Literal["intern", "campus", "experienced", "unknown"]


class RoleSignal(BaseModel):
    id: str = Field(pattern=r"^s[1-9][0-9]*$")
    signal: str = Field(min_length=1)
    why: str = ""
    evidence_looks_like: str = ""
    jd_quotes: list[str] = Field(default_factory=list)
    source: Literal["jd", "direction"] = "jd"

    @model_validator(mode="after")
    def check_source(self):
        if self.source == "jd" and (
            not self.jd_quotes or any(not quote.strip() for quote in self.jd_quotes)
        ):
            raise ValueError("JD signals need nonempty source quotes")
        if self.source == "direction" and self.jd_quotes:
            raise ValueError("Direction guidance must not claim JD quotes")
        return self


class RoleRequirement(BaseModel):
    id: str = Field(pattern=r"^r[1-9][0-9]*$")
    text: str = Field(min_length=1)
    weight: Literal["must", "plus"] = "must"
    jd_quote: str = ""
    source: Literal["jd", "direction"] = "jd"

    @model_validator(mode="after")
    def check_source(self):
        if self.source == "jd" and not self.jd_quote.strip():
            raise ValueError("JD requirements need a nonempty source quote")
        if self.source == "direction" and self.jd_quote:
            raise ValueError("Direction guidance must not claim a JD quote")
        return self


class RoleProfile(BaseModel):
    """Recruiter requirements and methods, never candidate experience facts."""

    source: Literal["jd", "direction"] = "jd"
    role_family: RoleFamily = "other"
    seniority: Seniority = "unknown"
    core_signals: list[RoleSignal] = Field(default_factory=list)
    requirements: list[RoleRequirement] = Field(default_factory=list)
    jd_language: list[str] = Field(default_factory=list)


class JdInfo(BaseModel):
    role_profile: RoleProfile = Field(default_factory=RoleProfile)
    job_title: str = ""
    company: str = ""
    industry: str = ""
    experience_years: str = ""
    education: str = ""
    required_skills: list[str] = []
    key_responsibilities: list[str] = []
    preferred_qualities: list[str] = []
    salary_range: str = ""
    hard_requirements: list[str] = []
    keyword_cloud: KeywordCloud = KeywordCloud()
    resume_strategy: ResumeStrategy = ResumeStrategy()
    requirement_evidence: list[RequirementEvidence] = []


class DecoderResponse(BaseModel):
    id: str
    decoded_items: list[DecodedItem]
    summary: str
    jd_info: JdInfo | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
