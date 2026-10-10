"""Strict model contracts for JD match planning and sourced resume writing."""

from contextvars import ContextVar
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


# --- Lenient variants -------------------------------------------------------
# Same names and the same JSON schema as the strict models above (so the tool
# definition sent to the model is unchanged), but unknown keys on titles,
# bullets, items and MatchPlan array elements are dropped instead of rejected.

IGNORED_EXTRA_SINK: ContextVar[list[str] | None] = ContextVar("writer_ignored_extra_sink", default=None)


def _still_forbid_in_schema(schema: dict[str, Any]) -> None:
    schema["additionalProperties"] = False


class _DropsExtra:
    @model_validator(mode="before")
    @classmethod
    def _record_and_ignore_extra(cls, data: Any) -> Any:
        sink = IGNORED_EXTRA_SINK.get()
        if sink is not None and isinstance(data, dict):
            sink.extend(str(key) for key in data if key not in cls.model_fields)
        return data


_LENIENT = ConfigDict(extra="ignore", json_schema_extra=_still_forbid_in_schema)


class LenientWrittenTitle(_DropsExtra, WrittenTitle):
    model_config = _LENIENT


class LenientWrittenBullet(_DropsExtra, WrittenBullet):
    model_config = _LENIENT


class LenientWrittenItem(_DropsExtra, WrittenItem):
    model_config = _LENIENT
    title: LenientWrittenTitle = Field(default_factory=LenientWrittenTitle)
    bullets: list[LenientWrittenBullet] = Field(default_factory=list)


class LenientRequirementMatch(_DropsExtra, RequirementMatch):
    model_config = _LENIENT


class LenientExperiencePlan(_DropsExtra, ExperiencePlan):
    model_config = _LENIENT


class LenientImprovementTarget(_DropsExtra, ImprovementTarget):
    model_config = _LENIENT


class LenientPlannedQuestion(_DropsExtra, PlannedQuestion):
    model_config = _LENIENT
    improves: LenientImprovementTarget = Field(default_factory=LenientImprovementTarget)


# MatchPlan itself stays strict-on-extra; only its array element objects are lenient.
class LenientMatchPlan(MatchPlan):
    requirements: list[LenientRequirementMatch] = Field(default_factory=list)
    experience_plan: list[LenientExperiencePlan] = Field(default_factory=list)
    questions: list[LenientPlannedQuestion] = Field(default_factory=list)


class LenientWriterDraft(WriterDraft):
    items: list[LenientWrittenItem] = Field(default_factory=list)


class LenientOnePassOutput(OnePassOutput):
    match_plan: LenientMatchPlan
    writer: LenientWriterDraft


for _lenient, _name in ((LenientRequirementMatch, "RequirementMatch"), (LenientExperiencePlan, "ExperiencePlan"),
                        (LenientImprovementTarget, "ImprovementTarget"), (LenientPlannedQuestion, "PlannedQuestion"),
                        (LenientMatchPlan, "MatchPlan"), (LenientWrittenTitle, "WrittenTitle"), (LenientWrittenBullet, "WrittenBullet"),
                        (LenientWrittenItem, "WrittenItem"), (LenientWriterDraft, "WriterDraft"),
                        (LenientOnePassOutput, "OnePassOutput")):
    _lenient.__name__ = _lenient.__qualname__ = _name
    _lenient.model_rebuild(force=True)

LENIENT_SCHEMAS: dict[type[BaseModel], type[BaseModel]] = {
    MatchPlan: LenientMatchPlan, WriterDraft: LenientWriterDraft, OnePassOutput: LenientOnePassOutput}
