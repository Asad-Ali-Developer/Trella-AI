from functools import lru_cache
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings and environment variable validation."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General Application
    APP_NAME: str = Field(default="client-insights-api")
    APP_ENV: str = Field(default="development")
    DEBUG: bool = Field(default=False)
    PORT: int = Field(default=8000)
    HOST: str = Field(default="0.0.0.0")
    API_V1_PREFIX: str = Field(default="/api/v1")
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "https://trella-ai-x8sb.vercel.app",
            "https://clientdeep.vercel.app",
        ]
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                import json
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return [str(origin).strip() for origin in parsed if str(origin).strip()]
                except Exception:
                    pass
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        if isinstance(v, (list, tuple, set)):
            return [str(origin).strip() for origin in v if str(origin).strip()]
        return []

    # Database
    DATABASE_URL: str = Field()
    TEST_DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5433/client_insights_test"
    )
    BENCH_DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5433/client_insights_bench"
    )
    DB_POOL_SIZE: int = Field(default=5, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0)
    DB_POOL_RECYCLE: int = Field(default=1800, ge=0)
    DB_POOL_TIMEOUT: int = Field(default=30, ge=1)
    DB_PGBOUNCER: bool = Field(default=False)

    @field_validator("DATABASE_URL", "TEST_DATABASE_URL", "BENCH_DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: str) -> str:
        if isinstance(v, str):
            if v.startswith("postgres://"):
                v = v.replace("postgres://", "postgresql+asyncpg://", 1)
            elif v.startswith("postgresql://") and not v.startswith("postgresql+asyncpg://"):
                v = v.replace("postgresql://", "postgresql+asyncpg://", 1)

            # Sanitize query parameters for asyncpg compatibility (e.g. Neon connection strings)
            parsed = urlparse(v)
            if parsed.query:
                params = parse_qs(parsed.query)
                # asyncpg does not accept 'sslmode' or 'channel_binding', but accepts 'ssl'
                if "sslmode" in params:
                    params["ssl"] = params.pop("sslmode")
                params.pop("channel_binding", None)
                new_query = urlencode(params, doseq=True)
                v = urlunparse(parsed._replace(query=new_query))
        return v

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # Transactional email (SMTP & Mailgun)
    FRONTEND_BASE_URL: str = Field(default="http://localhost:3000")
    SMTP_HOST: str = Field(default="")
    SMTP_PORT: int = Field(default=1025)
    SMTP_USERNAME: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_FROM_EMAIL: str = Field(default="no-reply@client-insights.local")
    SMTP_STARTTLS: bool = Field(default=False)
    SMTP_USE_SSL: bool = Field(default=False)
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)

    # Mailgun Settings
    MAILGUN_API_KEY: str = Field(default="")
    MAILGUN_DOMAIN: str = Field(default="")
    MAILGUN_API_BASE_URL: str = Field(default="https://api.mailgun.net/v3")
    MAILGUN_FROM_EMAIL: str = Field(default="")

    # Security & Encryption
    SECRET_KEY: str = Field(default="dev_secret_key_needs_replacement_in_production_min_32_chars")
    ENCRYPTION_KEY: str = Field(default="dGhpc19pcM1jMnJ2dGVfZXhhbXBsZV9rZXlfMTI=")
    ENCRYPTION_FALLBACK_KEYS: str = Field(
        default="",
        description="Comma-separated previous Fernet keys used to decrypt during rotation.",
    )
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=1440)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)
    AUTH_COOKIE_SECURE: bool | None = Field(default=None)
    AUTH_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = Field(default="lax")

    # Observability
    SENTRY_DSN: str = Field(default="")

    # LLM Settings
    GEMINI_API_KEY: str = Field(default="")
    GEMINI_CONTEXT_MODEL: str = Field(default="gemini-3-flash-preview")
    GEMINI_EMBEDDING_MODEL: str = Field(default="gemini-embedding-001")
    GEMINI_MAX_CONCURRENCY: int = Field(default=4, ge=1)
    GEMINI_MAX_ATTEMPTS: int = Field(default=3, ge=1)
    GEMINI_MAX_RETRIES: int = Field(default=3, ge=1)
    GEMINI_TIMEOUT_SECONDS: float = Field(default=45.0, gt=0)
    GEMINI_CONNECT_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0)
    GEMINI_RETRY_INITIAL_WAIT: float = Field(default=0.5, ge=0)
    GEMINI_RETRY_MAX_WAIT: float = Field(default=10.0, ge=0)
    GEMINI_RETRY_JITTER: float = Field(default=0.5, ge=0)
    INDEX_MAX_SUMMARIES_PER_RUN: int = Field(default=50, ge=1)
    INDEX_MAX_EMBED_PER_RUN: int = Field(default=500, ge=1)
    INDEX_LOCK_TTL_SECONDS: int = Field(default=1800, ge=1)
    RETRIEVAL_EF_SEARCH: int = Field(default=40, ge=1)
    RETRIEVAL_ITERATIVE_SCAN: Literal["off", "relaxed_order", "strict_order"] = Field(
        default="relaxed_order"
    )
    RETRIEVAL_KEYWORD_TIE_LIMIT: int = Field(
        default=0,
        ge=0,
        description="Benchmark workaround: limit keyword candidates per exact rank tie (0 = disabled).",
    )
    RETRIEVAL_KEYWORD_CANDIDATES: int = Field(
        default=300,
        ge=1,
        description="Cap keyword matching chunks before evaluating ts_rank_cd.",
    )
    RETRIEVAL_VECTOR_WEIGHT: float = Field(
        default=1.0,
        gt=0.0,
        description="Weighted RRF vector rank multiplier.",
    )
    RETRIEVAL_KEYWORD_WEIGHT: float = Field(
        default=0.5,
        ge=0.0,
        description="Weighted RRF keyword rank multiplier.",
    )

    # Trello
    TRELLO_API_BASE_URL: str = Field(default="https://api.trello.com/1")
    TRELLO_API_KEY: str = Field(default="")
    TRELLO_TOKEN_RETURN_URL: str = Field(default="http://localhost:3000/dashboard/trello/callback")
    TRELLO_TOKEN_SCOPE: str = Field(default="read")
    TRELLO_TOKEN_EXPIRATION: Literal["1hour", "1day", "30days", "never"] = Field(default="never")
    TRELLO_OAUTH_CLIENT_ID: str = Field(default="")
    TRELLO_OAUTH_CLIENT_SECRET: str = Field(default="")
    TRELLO_OAUTH_CALLBACK_URL: str = Field(
        default="http://localhost:3000/dashboard/trello/callback"
    )
    TRELLO_OAUTH_SCOPES: str = Field(
        default="read:board:trello read:organization:trello read:member:trello offline_access"
    )
    TRELLO_WEBHOOK_CALLBACK_URL: str = Field(default="")
    TRELLO_WEBHOOK_SECRET: str = Field(default="")

    # GitHub OAuth App
    GITHUB_CLIENT_ID: str = Field(default="")
    GITHUB_CLIENT_SECRET: str = Field(default="")
    GITHUB_CALLBACK_URL: str = Field(default="http://localhost:3000/dashboard/github/callback")
    GITHUB_API_BASE_URL: str = Field(default="https://api.github.com")

    # Jira (Atlassian OAuth 2.0 3LO)
    JIRA_CLIENT_ID: str = Field(default="")
    JIRA_CLIENT_SECRET: str = Field(default="")
    JIRA_CALLBACK_URL: str = Field(default="http://localhost:3000/dashboard/jira/callback")
    JIRA_SCOPES: str = Field(default="read:jira-work read:jira-user offline_access")
    JIRA_API_BASE_URL: str = Field(default="https://api.atlassian.com")
    JIRA_AUTH_URL: str = Field(default="https://auth.atlassian.com")

    # Google OAuth
    GOOGLE_CLIENT_ID: str = Field(default="")
    GOOGLE_CLIENT_SECRET: str = Field(default="")

    # Slack OAuth App
    SLACK_CLIENT_ID: str = Field(default="")
    SLACK_CLIENT_SECRET: str = Field(default="")
    SLACK_SIGNING_SECRET: str = Field(default="")
    SLACK_CALLBACK_URL: str = Field(default="http://localhost:3000/dashboard/slack/callback")
    SLACK_SCOPES: str = Field(
        default="chat:write,chat:write.public,channels:read,groups:read,im:read,mpim:read,users:read"
    )

    # Resend Email Service
    RESEND_API_KEY: str = Field(default="")

    @property
    def encryption_fallback_keys(self) -> list[str]:
        """Parse previous encryption keys used for MultiFernet rotation."""
        if not self.ENCRYPTION_FALLBACK_KEYS.strip():
            return []
        return [key.strip() for key in self.ENCRYPTION_FALLBACK_KEYS.split(",") if key.strip()]

    @property
    def auth_cookie_secure(self) -> bool:
        """Use secure cookies by default outside local development."""
        if self.AUTH_COOKIE_SECURE is not None:
            return self.AUTH_COOKIE_SECURE
        return self.APP_ENV == "production" or self.AUTH_COOKIE_SAMESITE == "none"


@lru_cache
def get_settings() -> Settings:
    """Return cached singleton instance of application settings."""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
