from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://firewatch:firewatch@localhost:5432/firewatch"
    redis_url: str = "redis://localhost:6379/0"
    rabbit_url: str = "amqp://guest:guest@localhost:5672/"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "firewatch"
    s3_region: str = "us-east-1"

    data_dir: Path = Path("DATA/fire-train-renamed/train")
    seed_limit_af: int = 0
    seed_limit_bs: int = 0

    worker_prefetch: int = 2
    cache_ttl_seconds: int = 300
    min_polygon_px: int = 1

    persistent_min_days: int = 5
    persistent_min_years: int = 3
    persistent_min_pass_share: float = 0.4
    persistent_radius_m: int = 400
    dispatch_cluster_m: float = 1500.0

    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    webhook_timeout_seconds: float = 5.0
    cors_origins: list[str] = ["*"]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
