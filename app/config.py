from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ProtrackLite"
    app_env: str = "development"
    secret_key: str = "change-this-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60
    refresh_token_ttl_days: int = 7
    database_url: str = "sqlite:///./protracklite.db"
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@task.omnihire.in"
    base_domain: str = "task.omnihire.in"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
