"""Shared candidate contract for MCP and pasted AI memory exports."""

from pydantic import BaseModel, ConfigDict, Field

from app.agents.profile_archivist import Category, FactField


class FactCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    category: Category
    subject: str = Field(min_length=1, max_length=160)
    field: FactField
    value: str = Field(min_length=1, max_length=4000)
    evidence: str = Field(min_length=1, max_length=4000)
