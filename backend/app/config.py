from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "VC Brain"
    app_version: str = "0.1.0"
    env: str = "dev"
    log_level: str = "INFO"
    api_base_url: str = "http://localhost:8000"
    frontend_origins: str = "http://localhost:3000"

    database_url: str = "sqlite+aiosqlite:///./vcbrain.sqlite3"
    redis_url: str = "redis://localhost:6379/0"
    auto_create_schema: bool = False
    queue_eager: bool = False

    secret_key: str = "development-secret-key-change-before-production"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "vcbrain"
    jwt_audience: str = "vcbrain-web"
    jwt_access_ttl_min: int = 15
    jwt_refresh_ttl_days: int = 14
    service_token: str = ""

    storage_backend: str = "s3"
    local_storage_path: Path = Path("./data/objects")
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "vcbrain"
    s3_secret_key: str = "change-me"
    s3_region: str = "us-east-1"
    s3_bucket_decks: str = "vcbrain-decks"
    s3_bucket_snapshots: str = "vcbrain-snapshots"
    s3_bucket_exports: str = "vcbrain-exports"
    max_upload_mb: int = 40

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model_reasoning: str = "gpt-4.1"
    openai_model_fast: str = "gpt-4.1-mini"
    openai_model_embed: str = "text-embedding-3-small"
    nvidia_nim_api_key: str = ""
    nvidia_nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model_reasoning: str = "meta/llama-3.3-70b-instruct"
    nvidia_model_embed: str = "nvidia/nv-embedqa-e5-v5"
    llm_daily_usd_budget: float = 40.0
    llm_per_opportunity_usd_cap: float = 1.50
    llm_request_timeout_s: int = 60

    tavily_api_key: str = ""
    github_token: str = ""
    contact_email: str = "team@example.com"
    user_agent: str = "VCBrain/0.1 (+https://example.com; team@example.com)"
    allow_scrape_domains: str = "devpost.com,news.ycombinator.com"
    enable_web_fallback: bool = True

    conviction_threshold: float = Field(default=72, ge=0, le=100)
    decision_sla_hours: int = Field(default=24, ge=1, le=168)
    demo_mode: bool = False

    sentry_dsn: str = ""
    otel_exporter_otlp_endpoint: str = ""
    git_sha: str = "dev"
    built_at: str = "unknown"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @property
    def scrape_domain_allowlist(self) -> set[str]:
        return {domain.strip().lower() for domain in self.allow_scrape_domains.split(",") if domain}

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.env == "prod" and len(self.secret_key.encode()) < 32:
            raise ValueError("SECRET_KEY must contain at least 32 bytes in production")
        if self.env == "prod" and self.secret_key.startswith("development-"):
            raise ValueError("Development SECRET_KEY cannot be used in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
