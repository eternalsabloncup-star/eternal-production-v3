"""Accurate read-only gateway settings. Never load ERP V1 secrets."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env",),
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "ETERNAL Accurate Read Gateway"
    app_env: str = Field(default="development", alias="GATEWAY_APP_ENV")
    # M2M token that Production V3 presents (V3_ACCURATE_READ_GATEWAY_TOKEN).
    gateway_m2m_token: str = Field(default="", alias="GATEWAY_M2M_TOKEN")
    # Upstream Accurate Online API Token 1.0.3 (required for live mode).
    accurate_api_token: str = Field(default="", alias="ACCURATE_API_TOKEN")
    accurate_signature_secret: str = Field(
        default="", alias="ACCURATE_SIGNATURE_SECRET"
    )
    # When set: api-token.do database.id must be present and equal (fail closed).
    accurate_database_id: str = Field(default="", alias="ACCURATE_DATABASE_ID")
    accurate_account_base: str = Field(
        default="https://account.accurate.id", alias="ACCURATE_ACCOUNT_BASE"
    )
    # fixture | live — fixture never claims Accurate live verification.
    gateway_mode: str = Field(default="fixture", alias="GATEWAY_MODE")
    listen_host: str = Field(default="127.0.0.1", alias="GATEWAY_HOST")
    listen_port: int = Field(default=8091, alias="GATEWAY_PORT")


@lru_cache
def get_settings() -> GatewaySettings:
    return GatewaySettings()
