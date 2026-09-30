from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Values come from environment / `.env`; secrets are never committed."""

    model_config = SettingsConfigDict(env_prefix="MMO_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    app_name: str = "Oldschool AFK Text MMO"
    database_url: str = "postgresql+asyncpg://mmo:mmo@localhost:5432/mmo"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: SecretStr = Field(default=SecretStr("dev-only-insecure-secret-change-me"))
    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"
    log_json: bool = True
    db_pool_size: int = 10
    db_echo: bool = False
    slow_query_ms: int = 250

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
