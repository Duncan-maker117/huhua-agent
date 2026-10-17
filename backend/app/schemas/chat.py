from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.ask_user import Answers, PlanChoice


class Message(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ReadJobURL(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["read_url"]
    url: str = Field(min_length=1, max_length=2048)


class ReadPublicURL(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["read_public_url"]
    url: str = Field(min_length=1, max_length=2048)


class SearchJobContext(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["search"]
    company: str = Field(default="", max_length=80)
    role: str = Field(default="", max_length=80)

    @model_validator(mode="after")
    def require_public_terms(self):
        if not (self.company or self.role):
            raise ValueError("请填写公司名或岗位名")
        return self



class ChatRequest(BaseModel):
    answers: Answers | None = None
    plan_choice: PlanChoice | None = None
    messages: list[Message]
    session_id: str | None = None
    turn_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    task: Literal["auto", "decode_jd", "rewrite_experience", "review_resume"] = "auto"
    # Only the server can populate research sources. Clients select one bounded
    # operation; they cannot submit fabricated tool results or model prompts.
    web_tool: Annotated[ReadJobURL | ReadPublicURL | SearchJobContext, Field(discriminator="action")] | None = None
