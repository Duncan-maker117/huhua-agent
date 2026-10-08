"""Strict model contracts for JD match planning and sourced resume writing."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WriterSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RequirementMatch(WriterSchema):
    req_id: str
    status: Literal["direct", "transferable", "gap"]
    fact_ids: list[str] = Field(default_factory=list)
    angle: str = ""


class ExperiencePlan(WriterSchema):
    item_id: str
    treatment: Literal["lead", "keep", "brief", "backup"]
    reason: str = ""
    target_bullets: int = Field(default=1, ge=0, le=3)


class ImprovementTarget(WriterSchema):
    item_id: str = ""
    req_id: str = ""


class PlannedQuestion(WriterSchema):
    q: str
    why: str = ""
    improves: ImprovementTarget = Field(default_factory=ImprovementTarget)
    options: list[str] = Field(default_factory=list)
    value: int = Field(default=1, ge=1, le=5)


class MatchPlan(WriterSchema):
    requirements: list[RequirementMatch] = Field(default_factory=list)
    experience_plan: list[ExperiencePlan] = Field(default_factory=list)
    section_order: list[str] = Field(default_factory=list)
    summary_angle: str = ""
    questions: list[PlannedQuestion] = Field(default_factory=list)


class WrittenTitle(WriterSchema):
    name: str = ""
    role: str = ""


class WrittenBullet(WriterSchema):
    text: str
    fact_ids: list[str] = Field(default_factory=list)
    req_ids: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    needs_metric: bool = False
    metric_question: str = ""


class WrittenItem(WriterSchema):
    item_id: str
    section: Literal["projects", "work_experience"]
    title: WrittenTitle = Field(default_factory=WrittenTitle)
    bullets: list[WrittenBullet] = Field(default_factory=list)


class OmittedItem(WriterSchema):
    item_id: str
    reason: str = ""


class WriterDraft(WriterSchema):
    objective: str = ""
    summary: str = ""
    summary_fact_ids: list[str] = Field(default_factory=list)
    items: list[WrittenItem] = Field(default_factory=list)
    skill_groups: dict[str, list[str]] = Field(default_factory=dict)
    omitted: list[OmittedItem] = Field(default_factory=list)
    change_summary: list[str] = Field(default_factory=list)


class OnePassOutput(WriterSchema):
    match_plan: MatchPlan
    writer: WriterDraft


class RepairBullet(WriterSchema):
    id: str
    text: str
    fact_ids: list[str] = Field(default_factory=list)
    req_ids: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    needs_metric: bool = False
    metric_question: str = ""


class RepairOutput(WriterSchema):
    bullets: list[RepairBullet] = Field(default_factory=list)
