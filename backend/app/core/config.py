"""Application configuration.

Every tunable lives here and is sourced from the environment. Nothing in this module
carries a working credential default, and `validate_for_environment()` refuses to start a
production process that is configured like a development one.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ─────────────────────────────────────────
    app_env: Environment = "development"
    app_name: str = "AI Motor Insurance Claim Assessment"
    log_level: str = "INFO"
    api_port: int = 8000
    api_v1_prefix: str = "/api/v1"

    # ── Database ────────────────────────────────────────────
    database_url: str = "sqlite+pysqlite:///./insurance.db"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # ── Security ────────────────────────────────────────────
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    cors_origins: str = "http://localhost:3000"
    rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 10

    # ── Redis / Celery ──────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── Object storage ──────────────────────────────────────
    storage_endpoint: str = "http://localhost:9000"
    storage_public_endpoint: str = "http://localhost:9000"
    storage_access_key: str = ""
    storage_secret_key: str = ""
    storage_bucket: str = "claim-images"
    storage_region: str = "us-east-1"
    storage_presign_ttl_seconds: int = 900
    storage_backend: str = "filesystem"
    storage_local_path: str = ""

    # ── AI providers ────────────────────────────────────────
    ai_provider: str = "mock"
    vision_provider: str = "mock"
    ai_fallback_chain: str = ""
    ai_request_timeout_seconds: int = 60
    ai_max_retries: int = 2

    gemini_api_key: str = ""
    gemini_text_model: str = "gemini-2.5-flash"
    gemini_vision_model: str = "gemini-2.5-flash"

    openrouter_api_key: str = ""
    openrouter_text_model: str = "google/gemini-2.5-flash"
    openrouter_vision_model: str = "google/gemini-2.5-flash"

    deepseek_api_key: str = ""
    deepseek_text_model: str = "deepseek-chat"

    # ── Market research ─────────────────────────────────────
    market_research_enabled: bool = True
    market_country: str = "LK"
    market_currency: str = "LKR"
    search_provider: str = "none"
    serper_api_key: str = ""
    tavily_api_key: str = ""
    brave_api_key: str = ""
    scraper_user_agent: str = "AIClaimAssessBot/1.0"
    scraper_timeout_seconds: int = 20
    scraper_cache_ttl_hours: int = 24
    scraper_respect_robots: bool = True
    scraper_max_pages_per_query: int = 5

    # ── Estimation defaults ─────────────────────────────────
    labour_rate_per_hour: float = 2500
    paint_rate_per_panel: float = 12000
    materials_percent_of_parts: float = 0.05
    estimate_range_spread: float = 0.15

    # ── Manual review thresholds ────────────────────────────
    review_min_vehicle: float = 0.70
    review_min_damage: float = 0.65
    review_min_ocr: float = 0.75
    review_min_price: float = 0.60
    review_amount_threshold: float = 500_000
    review_ratio_threshold: float = 0.30
    min_evidence_images: int = 2

    # ── Uploads ─────────────────────────────────────────────
    max_image_mb: int = 15
    max_images_per_claim: int = 20
    min_image_width: int = 640
    min_image_height: int = 480
    blur_score_threshold: float = 100.0

    # ── Maps ────────────────────────────────────────────────
    map_api_key: str = ""
    geocoding_provider: str = "nominatim"
    geocoding_api_key: str = ""

    # ── Notifications ───────────────────────────────────────
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "claims@example.com"
    sms_enabled: bool = False
    sms_provider: str = ""
    sms_api_key: str = ""
    sms_sender_id: str = ""

    allowed_image_types: tuple[str, ...] = Field(
        default=("image/jpeg", "image/jpg", "image/png", "image/webp")
    )

    # ── Derived helpers ─────────────────────────────────────

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def fallback_chain(self) -> list[str]:
        return [p.strip() for p in self.ai_fallback_chain.split(",") if p.strip()]

    @property
    def max_image_bytes(self) -> int:
        return self.max_image_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    def validate_for_environment(self) -> list[str]:
        """Return blocking misconfigurations. Empty list means safe to start."""
        problems: list[str] = []

        if not self.jwt_secret or len(self.jwt_secret) < 32:
            problems.append(
                "JWT_SECRET must be set to at least 32 characters. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )

        if not self.is_production:
            return problems

        # Everything below is production-only.
        if "mock" in (self.ai_provider, self.vision_provider):
            problems.append(
                "The mock AI provider cannot run in production; it produces fixture data, "
                "not assessments. Set AI_PROVIDER and VISION_PROVIDER to a real provider."
            )
        if not self.scraper_respect_robots:
            problems.append("SCRAPER_RESPECT_ROBOTS cannot be disabled in production.")
        if not self.storage_access_key or not self.storage_secret_key:
            problems.append("Object storage credentials are required in production.")
        if "insurance:insurance@" in self.database_url:
            problems.append("The default database password is still in use.")
        if any(o.strip() == "*" for o in self.cors_origin_list):
            problems.append("CORS_ORIGINS may not be '*' in production.")

        configured_keys = {
            "gemini": self.gemini_api_key,
            "openrouter": self.openrouter_api_key,
            "deepseek": self.deepseek_api_key,
        }
        for provider in {self.ai_provider, self.vision_provider, *self.fallback_chain}:
            if provider in configured_keys and not configured_keys[provider]:
                problems.append(f"{provider.upper()}_API_KEY is required because it is a selected provider.")

        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
