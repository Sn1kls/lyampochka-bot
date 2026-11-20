import os

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ENV_FILE swaps the whole file, so a staging run never falls back to production values.
    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env"), env_ignore_empty=True, extra="ignore"
    )

    bot_token: SecretStr
    admin_chat_id: int | None = None
    database_url: str = "sqlite+aiosqlite:///./data/poweron.sqlite3"
    api_base: str = "https://api-poweron.toe.com.ua/api"
    voe_api_base: str = "https://api-voe-poweron.inneti.net"
    poll_interval_sec: float = 300
    contact: str = "n/a"
    log_level: str = "INFO"
    git_sha: str = "dev"
    healthcheck_url: SecretStr | None = None
    backup_password: SecretStr | None = None
    sentry_dsn: SecretStr | None = None
    sentry_environment: str = "production"
