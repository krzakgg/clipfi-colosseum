from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str
    database_echo: bool = False

    tracking_internal_url: str = "http://api-internal:8000"
    tracking_redirect_base: str = "http://localhost:8080/r"
    tracking_service_token: SecretStr
    tracking_timeout: float = Field(default=5.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
