from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from pydantic import Field


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
    CHAT_TIMEOUT_SECONDS: float = Field(default=150.0, gt=0)
    MODEL_MAX_CONCURRENT: int = Field(default=3, gt=0)
    ACCOUNT_DAILY_TURN_LIMIT: int = Field(default=80, gt=0)
    ARCHIVE_POLL_SECONDS: float = Field(default=10.0, gt=0)
    # 数据库
    DATABASE_URL: str = f"sqlite:///{BACKEND_DIR / 'data' / 'huhua.db'}"
    CHECKPOINT_DB_PATH: str = str(BACKEND_DIR / "data" / "checkpoints.sqlite3")
    # 0 keeps conversation history until the user explicitly deletes it.
    SESSION_RETENTION_DAYS: int = 0

    # LLM
    LLM_PROVIDER: str = "openai"  # openai / deepseek
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o"
    # 结构化输出（Triage / editor / decoder / info-extractor）专用模型；
    # qwen3.6-plus 的 with_structured_output 太慢（~12s），这里切到更快的 qwen3-max
    LLM_STRUCTURED_MODEL: str = ""  # 空则回退到 LLM_MODEL
    # 空值按 API 地址选择 DeepSeek Flash / Qwen VL / OpenAI 视觉模型。
    LLM_VISION_MODEL: str = ""
    LLM_BASE_URL: str | None = None  # DeepSeek 等自定义 base_url
    LLM_TEMPERATURE: float = 0.7
    # 简历审查需要读完整份材料；此值覆盖整段公开输出流。
    LLM_REVIEW_TIMEOUT_SECONDS: float = 90.0

    # 用户主动点击岗位匹配时才调用 Jev；凭证仅由服务端环境变量读取。
    JEV_API_KEY: str = ""
    JEV_TIMEOUT_SECONDS: float = 8.0

    # Optional, server-only. Job URL reading does not require a search key.
    TAVILY_API_KEY: str = ""

    # RAG
    CHROMA_DIR: str = str(PROJECT_DIR / "data" / "chroma_db")
    RAG_TOP_K: int = 5
    ENABLE_RAG: bool = False

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
