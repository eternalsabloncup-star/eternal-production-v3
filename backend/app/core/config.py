"""Environment-based application configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILES = (
    str(_REPO_ROOT / ".env"),
    ".env",
)


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ETERNAL PRODUCTION V3"
    app_env: str = Field(default="development", alias="APP_ENV")
    app_debug: bool = Field(default=False, alias="APP_DEBUG")
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")

    database_url: str = Field(
        default="postgresql+asyncpg://epv3_dev:change_me@127.0.0.1:5432/eternal_production_v3_dev",
        alias="DATABASE_URL",
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg2://epv3_dev:change_me@127.0.0.1:5432/eternal_production_v3_dev",
        alias="DATABASE_URL_SYNC",
    )
    database_echo: bool = Field(default=False, alias="DATABASE_ECHO")

    cors_origins: str = Field(
        default="http://localhost:5173",
        alias="CORS_ORIGINS",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
