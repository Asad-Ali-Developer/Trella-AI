from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings and environment variable validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
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
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/client_insights"
    )

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

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
    return Settings()


settings = get_settings()
