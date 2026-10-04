"""Central, typed configuration. Every tunable lives here and is overridable via env vars."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_INSECURE_DEFAULT_SECRET = "dev-only-insecure-secret-change-me-0123456789abcdef"


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "test", "production"] = "local"

    # --- Database -----------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://desk:desk@localhost:5432/desk"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # Upper bound on how long a transaction waits for a row lock before failing fast (-> HTTP 503).
    # Without this a stuck transaction would queue every other operator behind it indefinitely.
    db_lock_timeout_ms: int = 5_000

    # --- Auth ---------------------------------------------------------------------
    jwt_secret: str = Field(default=_INSECURE_DEFAULT_SECRET, min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "dataset-request-desk"
    jwt_audience: str = "dataset-request-desk-api"
    access_token_expire_minutes: int = 60

    # --- HTTP ---------------------------------------------------------------------
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://localhost:8080"]

    # --- Episode import -----------------------------------------------------------
    known_robots: Annotated[list[str], NoDecode] = [
        "arm-01",
        "arm-02",
        "arm-03",
        "mobile-01",
        "humanoid-01",
    ]
    # 7 bind params per row; asyncpg caps a statement at 32,767 params, so keep well under 4,681 rows.
    import_batch_size: int = Field(default=4_000, ge=1, le=4_600)
    max_import_bytes: int = 1024 * 1024 * 1024  # 1 GiB
    max_episode_duration_seconds: int = 24 * 60 * 60
    # Recordings dated further than this past "now" are rejected as impossible (clock-skew tolerance).
    import_max_future_skew_hours: int = 24

    # --- Simulated dataset export (background task) -------------------------------
    export_min_seconds: float = 2.0
    export_max_seconds: float = 5.0
    export_failure_rate: float = Field(default=0.2, ge=0.0, le=1.0)
    export_max_attempts: int = Field(default=3, ge=1, le=10)
    export_retry_backoff_seconds: float = 1.0
    # A 'running' export whose heartbeat is older than this is presumed orphaned (process crash).
    export_stale_after_seconds: int = 120

    # --- Catalog cache ------------------------------------------------------------
    catalog_cache_ttl_seconds: int = 30

    @model_validator(mode="before")
    @classmethod
    def _parse_csv_lists(cls, data: dict) -> dict:
        for key in ("cors_origins", "known_robots"):
            if key in data:
                data[key] = _split_csv(data[key])
        return data

    @model_validator(mode="after")
    def _forbid_insecure_secret_in_production(self) -> Settings:
        if self.environment == "production" and self.jwt_secret == _INSECURE_DEFAULT_SECRET:
            raise ValueError("JWT_SECRET must be set to a strong random value in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
