from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from pydantic import AliasChoices, Field


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    APP_ENV: Literal["local", "production"] = "local"
    ALLOW_INSECURE_LOCAL_STORAGE: bool = False
    REQUIRE_ACCOUNT: bool = True
    ALLOW_GUEST_EXPERIENCE: bool = True
    GUEST_RETENTION_HOURS: int = Field(default=24, gt=0)
    GUEST_DAILY_TURN_LIMIT: int = Field(default=20, gt=0)
    DATA_ENCRYPTION_KEYS: str = "{}"
    DATA_ENCRYPTION_ACTIVE_KEY: str = ""
    ACCOUNT_SECRET: str = ""
    AUTH_COOKIE_SECURE: bool = True
    APP_ORIGIN: str = ""
    EMAIL_PROVIDER: Literal["smtp", "resend"] = "smtp"
    RESEND_API_KEY: str = ""
    RESEND_FROM: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_STARTTLS: bool = True
    # Application-wide send attempts, using UTC calendar days/months. Keep a
    # margin below the provider's free tier; zero must not mean unlimited.
    AUTH_EMAIL_DAILY_LIMIT: int = Field(default=90, gt=0)
    AUTH_EMAIL_MONTHLY_LIMIT: int = Field(default=2800, gt=0)
    CHAT_TIMEOUT_SECONDS: float = Field(default=360.0, gt=0)
    WRITE_DRAFT_TIMEOUT_SECONDS: float = Field(default=150.0, gt=0)
    MODEL_MAX_CONCURRENT: int = Field(default=3, gt=0)
    ACCOUNT_DAILY_TURN_LIMIT: int = Field(default=80, gt=0)
    ARCHIVE_POLL_SECONDS: float = Field(default=10.0, gt=0)
    PDF_CJK_FONT_DIR: str = str(PROJECT_DIR / "data" / "fonts")
    # 未安装优化字体时仍可能需要 40 秒；超时必须覆盖原字体回退。
    MCP_PREVIEW_TIMEOUT_SECONDS: float = Field(default=90.0, gt=0)
    MCP_PREVIEW_QUEUE_TIMEOUT_SECONDS: float = Field(default=300.0, gt=0)
    MCP_TEMPLATE_PREVIEW_DIR: str = str(PROJECT_DIR / "data" / "template_previews")
    # 数据库
    DATABASE_URL: str = f"sqlite:///{BACKEND_DIR / 'data' / 'huhua.db'}"
    CHECKPOINT_DB_PATH: str = str(BACKEND_DIR / "data" / "checkpoints.sqlite3")
    # 0 keeps conversation history until the user explicitly deletes it.
    SESSION_RETENTION_DAYS: int = 0

    # LLM
    LLM_PROVIDER: str = "openai"  # openai / deepseek
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o"
    # 内部提取、JD 解码与编辑模型；未指定时沿用主模型。
    LLM_STRUCTURED_MODEL: str = ""  # 空则回退到 LLM_MODEL
    # 空值按 API 地址选择 DeepSeek Flash / Qwen VL / OpenAI 视觉模型。
    LLM_VISION_MODEL: str = ""
    LLM_BASE_URL: str | None = None  # DeepSeek 等自定义 base_url
    # Keep LLM_TEMPERATURE as a legacy input alias for existing deployments.
    LLM_CHAT_TEMPERATURE: float = Field(
        default=0.7, ge=0, le=2,
        validation_alias=AliasChoices("LLM_CHAT_TEMPERATURE", "LLM_TEMPERATURE"),
    )
    # Writer uses the primary model; structured verification stays at zero.
    LLM_WRITER_TEMPERATURE: float = Field(default=0.4, ge=0, le=2)
    LLM_WRITER_MODE: Literal["one_pass", "two_pass"] = "one_pass"
    LLM_PLAN_CONFIRM: bool = True
    AGENT_MODE: Literal["off", "loop"] = "off"
    # Speed switches; benchmarked: the first three default on; edit plan reuse stays off.
    # Drop unknown keys on written bullets/items/titles and MatchPlan array elements instead of failing the call.
    LLM_WRITER_IGNORE_EXTRA_BULLET_FIELDS: bool = True
    # False (default) turns off DeepSeek thinking for fact extraction.
    LLM_EXTRACTOR_THINKING: bool = False
    # Edit rounds reuse the previous match_plan and only output the WriterDraft.
    LLM_WRITER_EDIT_REUSE_PLAN: bool = False
    # False (default) turns off DeepSeek thinking for JD decoding.
    LLM_JD_DECODER_THINKING: bool = False
    # None preserves the provider default; opt in to an explicit output limit.
    LLM_MAX_TOKENS: int | None = Field(default=None, gt=0)
    # 简历审查需要读完整份材料；此值覆盖整段公开输出流。
    LLM_REVIEW_TIMEOUT_SECONDS: float = 90.0


    # Optional, server-only. Job URL reading does not require a search key.
    TAVILY_API_KEY: str = ""
    # 岗位情报独立凭证优先；仅官方 DeepSeek 地址可复用模型凭证。
    DEEPSEEK_TOOLS_API_KEY: str = ""
    JOB_INTEL_PROVIDERS: str = "deepseek,tavily"
    JOB_INTEL_DAILY_LIMIT: int = Field(default=300, ge=0)
    JOB_INTEL_READ_LIMIT: int = Field(default=5, ge=0)
    JOB_INTEL_SAMPLE_LIMIT: int = Field(default=2, ge=0)
    JOB_INTEL_COMPANY_LIMIT: int = Field(default=3, ge=0)

    # RAG
    CHROMA_DIR: str = str(PROJECT_DIR / "data" / "chroma_db")
    RAG_TOP_K: int = 5
    ENABLE_RAG: bool = False

    @property
    def LLM_TEMPERATURE(self) -> float:
        """Compatibility accessor for existing evaluation scripts."""
        return self.LLM_CHAT_TEMPERATURE

    @property
    def chat_turn_timeout_seconds(self) -> float:
        # Older installations explicitly set CHAT_TIMEOUT_SECONDS=150. In loop
        # mode reserve one ordinary call before/after the full writer deadline.
        if self.AGENT_MODE == 'loop':
            return max(self.CHAT_TIMEOUT_SECONDS, self.WRITE_DRAFT_TIMEOUT_SECONDS + 180.0)
        return self.CHAT_TIMEOUT_SECONDS

    def validate_runtime(self):
        if self.APP_ENV == "production":
            origin = urlsplit(self.APP_ORIGIN)
            if (not self.REQUIRE_ACCOUNT or not self.AUTH_COOKIE_SECURE
                    or self.ALLOW_INSECURE_LOCAL_STORAGE):
                raise ValueError("Production requires accounts, secure cookies and encrypted storage")
            if (origin.scheme != "https" or not origin.hostname or origin.path not in ("", "/")
                    or origin.query or origin.fragment or origin.username or origin.password):
                raise ValueError("Production requires a configured HTTPS APP_ORIGIN")

    model_config = {
        "env_file": str(BACKEND_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
