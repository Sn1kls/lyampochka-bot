from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    bot_token: SecretStr
    admin_chat_id: int | None = None
    database_url: str = "sqlite+aiosqlite:///./data/poweron.sqlite3"
    api_base: str = "https://api-poweron.toe.com.ua/api"
    poll_interval_sec: float = 300
    contact: str = "n/a"
    log_level: str = "INFO"
    healthcheck_url: SecretStr | None = None
    backup_password: SecretStr | None = None
