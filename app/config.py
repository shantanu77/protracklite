from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ProtrackLite"
    app_env: str = "development"
    app_timezone: str = "Asia/Kolkata"
    secret_key: str = "change-this-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 10080
    refresh_token_ttl_days: int = 7
    database_url: str = ""
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@tasks.omnihire.in"
    base_domain: str = "tasks.omnihire.in"
    openai_api_key: str = ""
    openai_backlog_model: str = "gpt-5.4-mini"
    teams_availability_webhook_url: str = ""
    dev_release_upload_dir: str = "/var/lib/protracklite/uploads/dev-releases"
    user_content_dir: str = "/var/lib/protracklite/user-content"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
