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

    # Auth / sessions
    session_cookie: str = "session"
    csrf_cookie: str = "csrf_token"
    session_ttl_days: int = 30
    session_touch_seconds: int = 300
    login_max_failures_before_lock: int = 10
    login_lock_minutes: int = 15
    # Rate limits: "<count>/<seconds>"
    rl_login_ip: str = "30/60"
    rl_login_email: str = "10/900"
    rl_register_ip: str = "10/3600"
    rl_mutation_user: str = "120/60"
    max_characters_per_account: int = 8
    # Seed the 1,520-template launch catalog (canonical content). Tests disable it for speed and cover it directly.
    seed_launch_catalog: bool = True
    # Four-eyes review before publishing content via the admin API (recommended on in production).
    content_review_required: bool = False

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
