from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    opensearch_url: str = "http://localhost:9200"
    postgres_dsn: str = "postgresql://postgres:postgres@localhost:5433/postgres"
    postgres_read_dsn: str = ""
    redis_url: str = "redis://localhost:6379"
    log_level: str = "INFO"
    dashboard_refresh_interval: int = 120
    timeline_refresh_interval: int = 120

    model_config = {"env_prefix": "", "case_sensitive": False}


@lru_cache
def get_settings() -> Settings:
    return Settings()
