"""Strict model contracts for JD match planning and sourced resume writing."""

from contextvars import ContextVar
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, model_validator


LABELED_SEMANTICS = """labeled 标签按事实含义选用，缺少素材就省略：
问题 = 谁在什么场景遇到什么痛点、现有方案有什么不足，可带一句产品定位。
决策（含关键决策/设计）= 产品或方案层面的取舍、设计选择；如“先体验后登录”“检索结果作为候选池再让模型编排”。
独立完成、全流程、用了哪些工具/API 都不是决策；本人独立完成归标题性质（个人项目/独立开发），不得单独放现状行。
迭代 = 发现什么问题 → 改了什么 → 如何验证（评测/回归/对比）；只写已有环节，不补原因或结果；有数字的评测证据优先放这里。
技术 / 现状 = 技术栈、上线状态、可访问性、使用人数等，保留数字的单位与对象。
"""
LABELED_SELECTION = """仅在 labeled 写法中：带数字或可验证的评测/验证证据、上线状态和可访问性是高价值事实；
有空余行数时不得被泛泛描述挤掉；行数达到上限时先合并相关事实，仍须舍弃则舍弃信息量最低的句子。
单个选项短语改写成动作只能使用该短语的意思，不能补出原因或结果；只有选项词拼接、信息量低的一行可并入其他行或省略，不单独凑数。
"""


class WriterSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FactSlot(WriterSchema):
    fact_id: str
    slot: Literal['问题', '决策', '迭代', '技术', '现状', '标题性质', '不用']


class FactSlots(WriterSchema):
    assignments: list[FactSlot]


class RequirementMatch(WriterSchema):
    req_id: str
    status: Literal["direct", "transferable", "gap"]
    fact_ids: list[str] = Field(default_factory=list)
    angle: str = ""


class ExperiencePlan(WriterSchema):
    item_id: str
    treatment: Literal["lead", "keep", "brief", "backup"]
    reason: str = ""
    target_bullets: int = Field(default=1, ge=0, le=4)


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
    bullet_style: Literal['labeled', 'plain'] | None = None
    requirements: list[RequirementMatch] = Field(default_factory=list)
    experience_plan: list[ExperiencePlan] = Field(default_factory=list)
    section_order: list[str] = Field(default_factory=list)
    summary_angle: str = ""
    questions: list[PlannedQuestion] = Field(default_factory=list)


class RecommendedPlan(MatchPlan):
    label: str = "主线叙事型"
    positioning: str = Field(default="", description="必填：由已有事实支持的概括定位；仅缺乏支持时为空")
    thesis: str = ""
    profile_statement: str = Field(default="", description="由 thesis 改写的个人定位，2–3句且不超过90字；只使用 active facts")


class AlternativePlan(WriterSchema):
    label: str
    positioning: str = Field(default="", description="必填：由已有事实支持的概括定位；仅缺乏支持时为空")
    thesis: str = ""
    profile_statement: str = Field(default="", description="将写进简历的个人定位，2–3句且不超过90字")
    bullet_style: Literal['labeled', 'plain'] | None = None
    section_order: list[str] = Field(default_factory=list)
    # Only differences from recommended; selection merges them by item_id.
    experience_plan: list[ExperiencePlan] = Field(default_factory=list)


class StructurePlan(WriterSchema):
    recommended: RecommendedPlan
    alternatives: list[AlternativePlan] = Field(default_factory=list, max_length=2)


class WrittenTitle(WriterSchema):
    name: str = ""
    role: str = Field(default="", description="本人已确认的角色；独立完成类事实用于标题性质（个人项目/独立开发），不占决策行")
    positioning: str = Field(default="", description="由本经历事实概括的一句产品定位，须引用 fact_ids，不照抄岗位目标")
    fact_ids: list[str] = Field(default_factory=list)


class WrittenBullet(WriterSchema):
    text: str = Field(description="plain 沿用无标签简历动作写法。\n" + LABELED_SEMANTICS)
    fact_ids: list[str] = Field(default_factory=list)
    req_ids: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    needs_metric: bool = False
    metric_question: str = ""


class WrittenItem(WriterSchema):
    item_id: str
    section: Literal["projects", "work_experience", "campus", "open_source", "awards"]
    title: WrittenTitle = Field(default_factory=WrittenTitle)
    bullets: list[WrittenBullet] = Field(default_factory=list, description=LABELED_SELECTION)


class OmittedItem(WriterSchema):
    item_id: str
    reason: str = ""


class WriterDraft(WriterSchema):
    @model_validator(mode="before")
    @classmethod
    def reject_misplaced_item(cls, data: Any) -> Any:
        # Leniency may drop commentary, never an entire WrittenItem passed as
        # the root object. Reject before extra="ignore" erases its evidence.
        if isinstance(data, dict) and "items" not in data and {"item_id", "section", "bullets"} <= data.keys():
            raise ValueError("WrittenItem must be inside WriterDraft.items")
        return data

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
    bullets: list[LenientWrittenBullet] = Field(default_factory=list, description=LABELED_SELECTION)


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
