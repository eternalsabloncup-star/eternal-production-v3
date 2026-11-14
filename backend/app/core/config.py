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
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS",
    )

    # Dedicated V3 secrets only — never copy ERP V1 JWT_SECRET / Accurate tokens.
    v3_jwt_secret: str = Field(default="", alias="V3_JWT_SECRET")
    v3_password_pepper: str = Field(default="", alias="V3_PASSWORD_PEPPER")
    v3_workflow_authorization: str = Field(default="legacy", alias="V3_WORKFLOW_AUTHORIZATION")
    v3_settings_enabled: bool = Field(default=False, alias="V3_SETTINGS_ENABLED")
    v3_jwt_hours: int = Field(default=12, alias="V3_JWT_HOURS")
    v3_sla_working_days: int = Field(default=3, alias="V3_SLA_WORKING_DAYS")
    v3_default_shift_capacity: int = Field(default=17000, alias="V3_DEFAULT_SHIFT_CAPACITY")
    accurate_read_gateway_url: str = Field(
        default="", alias="V3_ACCURATE_READ_GATEWAY_URL"
    )
    accurate_read_gateway_token: str = Field(
        default="", alias="V3_ACCURATE_READ_GATEWAY_TOKEN"
    )
    # Bounded upstream scan for branch-scoped (non-Director) Inbox pages.
    inbox_scoped_scan_max_pages: int = Field(
        default=50, ge=1, le=200, alias="V3_INBOX_SCOPED_SCAN_MAX_PAGES"
    )
    # When true, payment receipts + SJ loading require live gateway verification.
    # Default false only so APP_ENV=test can skip; non-test always enforces via
    # accurate_evidence._enforce() even if this flag is false.
    accurate_evidence_enforce: bool = Field(
        default=False, alias="V3_ACCURATE_EVIDENCE_ENFORCE"
    )
    # Private local attachment root (POD photos/signatures). No public URLs.
    # Never point this at ERP V1 storage paths.
    attachment_root: str = Field(
        default=str(_REPO_ROOT / "backend" / "var" / "attachments"),
        alias="V3_ATTACHMENT_ROOT",
    )
    # Customer design-approval / live-tracking bearer links (local portal).
    # Default TTL documented: 72h design approval, 168h live tracking.
    # Possession of a bearer link is NOT legal identity proof.
    design_approval_token_ttl_hours: int = Field(
        default=72, alias="V3_DESIGN_APPROVAL_TOKEN_TTL_HOURS"
    )
    live_tracking_token_ttl_hours: int = Field(
        default=168, alias="V3_LIVE_TRACKING_TOKEN_TTL_HOURS"
    )
    # Optional absolute base for minted URLs (e.g. https://eternalorder.id).
    # Empty = return path-only /t/... for local isolated use; do not publish.
    customer_portal_public_base: str = Field(
        default="", alias="V3_CUSTOMER_PORTAL_PUBLIC_BASE"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
