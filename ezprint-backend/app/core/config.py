"""Centralized runtime configuration loaded from environment variables."""
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    env: str = "dev"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8000"
    cors_allow_origins: List[str] = Field(default_factory=lambda: ["*"])

    # Auth
    jwt_secret: str = "change-me"
    jwt_alg: str = "HS256"
    jwt_access_ttl_minutes: int = 60
    jwt_refresh_ttl_days: int = 7
    agent_session_ttl_hours: int = 24
    upload_token_ttl_minutes: int = 30

    # Database
    database_url: str = "postgresql+psycopg2://ezprint:ezprint@localhost:5432/ezprint"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MinIO / S3
    s3_endpoint: str = "http://localhost:9000"
    s3_public_endpoint: str = "http://localhost:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket_name: str = "ezprint"
    s3_region: str = "us-east-1"
    # MinIO root credentials — used only for admin ops (CORS, bucket policies).
    # Leave empty to skip and fall back to s3_access_key.
    minio_root_user: str = ""
    minio_root_password: str = ""

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            if v.strip() == "*":
                return ["*"]
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_prod(self) -> bool:
        return self.env.lower() in {"prod", "production"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
