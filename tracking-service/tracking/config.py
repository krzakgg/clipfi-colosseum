import logging
import os
import socket
from typing import Literal

from pydantic import Field, IPvAnyNetwork, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SECRET_LENGTH = 32


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRACKING_", env_file=".env", extra="ignore")

    database_url: str
    # owner account for migrations; the app account has no DDL rights
    migrate_database_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"

    service_token: SecretStr
    fingerprint_secret: SecretStr

    api_role: Literal["all", "public", "internal"] = "all"
    max_internal_body_bytes: int = Field(default=64 * 1024, ge=1024, le=1024 * 1024)
    max_header_bytes: int = Field(default=16 * 1024, ge=1024, le=256 * 1024)

    # number of reverse proxies in front; 0 = use the socket peer
    trusted_proxy_hops: int = Field(default=0, ge=0, le=10)
    # no default on purpose: "all private ranges" would include Docker's gateway
    trusted_proxies: list[IPvAnyNetwork] = []
    rate_limit_per_minute: int = Field(default=60, ge=1)
    max_unique_per_ip_per_day: int = Field(default=3, ge=1)
    miss_limit_per_minute: int = Field(default=60, ge=0)

    redirect_prefix: str = "/r"
    expose_docs: bool = False

    link_cache_ttl: int = Field(default=300, ge=1)
    negative_cache_ttl: int = Field(default=30, ge=1)
    count_timeout: float = Field(default=0.25, gt=0)

    bucket_ttl: int = Field(default=48 * 3600, ge=600)
    # must exceed clock skew between API and flusher hosts
    bucket_close_grace: int = Field(default=300, ge=60)
    stream_maxlen: int = Field(default=1_000_000, ge=1000)

    flush_interval: float = Field(default=5.0, gt=0)
    events_batch_size: int = Field(default=500, ge=1, le=10_000)
    events_block_ms: int = Field(default=1000, ge=100, le=10_000)
    pending_claim_idle_ms: int = Field(default=60_000, ge=1000)
    events_retention_days: int = Field(default=90, ge=0)
    consumer_name: str = Field(default_factory=lambda: f"{socket.gethostname()}-{os.getpid()}")

    log_level: str = "INFO"

    @field_validator("service_token", "fingerprint_secret")
    @classmethod
    def _secret_long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < MIN_SECRET_LENGTH:
            raise ValueError(f"must be at least {MIN_SECRET_LENGTH} characters")
        return value

    @model_validator(mode="after")
    def _proxies_named_when_trusted(self) -> "Settings":
        if self.trusted_proxy_hops and not self.trusted_proxies:
            raise ValueError("TRACKING_TRUSTED_PROXY_HOPS > 0 requires TRACKING_TRUSTED_PROXIES")
        return self

    @field_validator("redirect_prefix")
    @classmethod
    def _prefix_shape(cls, value: str) -> str:
        value = value.rstrip("/")
        if value and not value.startswith("/"):
            raise ValueError("must be empty or start with '/'")
        return value
