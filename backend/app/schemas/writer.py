"""Strict model contracts for JD match planning and sourced resume writing."""

from contextvars import ContextVar
from typing import Any, Literal, get_args, get_origin

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


class RecommendedPlan(MatchPlan):
    label: str = "主线叙事型"
    positioning: str = ""
    thesis: str = ""


class AlternativePlan(WriterSchema):
    label: str
    positioning: str = ""
    thesis: str = ""
    section_order: list[str] = Field(default_factory=list)
    # Only differences from recommended; selection merges them by item_id.
    experience_plan: list[ExperiencePlan] = Field(default_factory=list)


class StructurePlan(WriterSchema):
    recommended: RecommendedPlan
    alternatives: list[AlternativePlan] = Field(default_factory=list, max_length=2)


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
    section: Literal["projects", "work_experience", "open_source"]
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
# bullets, items, plans and the top-level outputs are dropped instead of rejected.

IGNORED_EXTRA_SINK: ContextVar[list[str] | None] = ContextVar("writer_ignored_extra_sink", default=None)
REPAIRED_FIELD_SINK: ContextVar[list[dict] | None] = ContextVar("writer_repaired_field_sink", default=None)


def _still_forbid_in_schema(schema: dict[str, Any]) -> None:
    schema["additionalProperties"] = False


class _DropsExtra:
    @model_validator(mode="before")
    @classmethod
    def _record_and_ignore_extra(cls, data: Any) -> Any:
        sink = IGNORED_EXTRA_SINK.get()
        if sink is not None and isinstance(data, dict):
            sink.extend(str(key) for key in data if key not in cls.model_fields)
        if isinstance(data, dict):
            data = dict(data)
            repaired = REPAIRED_FIELD_SINK.get()
            for name, field in cls.model_fields.items():
                if name not in data:
                    continue
                value, reason = data[name], ''
                if get_origin(field.annotation) is Literal and isinstance(value, str):
                    choices = get_args(field.annotation)
                    normalized = value.strip().casefold()
                    if normalized in choices and value != normalized:
                        value, reason = normalized, 'normalized_literal'
                for bound in field.metadata:
                    if isinstance(value, list) and (limit := getattr(bound, 'max_length', None)) is not None and len(value) > limit:
                        value, reason = value[:limit], 'truncated_list'
                    if field.annotation is int:
                        number = int(value) if isinstance(value, str) and value.strip().lstrip('+-').isdigit() else value
                        if type(number) is float and number.is_integer():
                            number = int(number)
                        if type(number) is int:
                            lower, upper = getattr(bound, 'ge', None), getattr(bound, 'le', None)
                            clamped = max(lower, number) if lower is not None else number
                            clamped = min(upper, clamped) if upper is not None else clamped
                            if clamped != number:
                                value, reason = clamped, 'clamped_range'
                if reason:
                    data[name] = value
                    if repaired is not None:
                        repaired.append({'field': name, 'reason': reason})
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


# Every level drops unknown keys: models keep adding *_note fields at new levels,
# and no unknown key is ever read into the resume.
class LenientMatchPlan(_DropsExtra, MatchPlan):
    model_config = _LENIENT
    requirements: list[LenientRequirementMatch] = Field(default_factory=list)
    experience_plan: list[LenientExperiencePlan] = Field(default_factory=list)
    questions: list[LenientPlannedQuestion] = Field(default_factory=list)


class LenientRecommendedPlan(_DropsExtra, RecommendedPlan):
    model_config = _LENIENT
    requirements: list[LenientRequirementMatch] = Field(default_factory=list)
    experience_plan: list[LenientExperiencePlan] = Field(default_factory=list)
    questions: list[LenientPlannedQuestion] = Field(default_factory=list)


class LenientAlternativePlan(_DropsExtra, AlternativePlan):
    model_config = _LENIENT
    experience_plan: list[LenientExperiencePlan] = Field(default_factory=list)


class LenientStructurePlan(_DropsExtra, StructurePlan):
    model_config = _LENIENT
    recommended: LenientRecommendedPlan
    alternatives: list[LenientAlternativePlan] = Field(default_factory=list, max_length=2)


class LenientWriterDraft(_DropsExtra, WriterDraft):
    model_config = _LENIENT
    items: list[LenientWrittenItem] = Field(default_factory=list)


class LenientOnePassOutput(_DropsExtra, OnePassOutput):
    model_config = _LENIENT
    match_plan: LenientMatchPlan
    writer: LenientWriterDraft


for _lenient, _name in ((LenientRequirementMatch, "RequirementMatch"), (LenientExperiencePlan, "ExperiencePlan"),
                        (LenientImprovementTarget, "ImprovementTarget"), (LenientPlannedQuestion, "PlannedQuestion"),
                        (LenientMatchPlan, "MatchPlan"), (LenientWrittenTitle, "WrittenTitle"), (LenientWrittenBullet, "WrittenBullet"),
                        (LenientRecommendedPlan, "RecommendedPlan"), (LenientAlternativePlan, "AlternativePlan"),
                        (LenientStructurePlan, "StructurePlan"),
                        (LenientWrittenItem, "WrittenItem"), (LenientWriterDraft, "WriterDraft"),
                        (LenientOnePassOutput, "OnePassOutput")):
    _lenient.__name__ = _lenient.__qualname__ = _name
    _lenient.model_rebuild(force=True)

LENIENT_SCHEMAS: dict[type[BaseModel], type[BaseModel]] = {
    MatchPlan: LenientMatchPlan, StructurePlan: LenientStructurePlan,
    WriterDraft: LenientWriterDraft, OnePassOutput: LenientOnePassOutput}
