"""应用配置——所有可配置项集中在此。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db: str = "suno_api"

    pool_max_size: int = 10
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    scheduler_hour: int = 0
    scheduler_minute: int = 0

    song_request_timeout: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
