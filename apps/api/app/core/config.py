"""Application settings, loaded from environment variables (never from git)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(API_ROOT / ".env"), str(API_ROOT.parents[1] / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+asyncpg://termrail:termrail@localhost:5432/termrail"

    # --- Auth -------------------------------------------------------------
    # "local": email/password accounts stored in PostgreSQL, HS256 JWTs issued by this API.
    # "supabase": verify Supabase Auth JWTs (RS256/ES256) against SUPABASE_JWKS_URL.
    auth_provider: Literal["local", "supabase"] = "local"
    jwt_secret: str = Field(default="", repr=False)
    jwt_ttl_minutes: int = 12 * 60
    supabase_url: str = ""
    supabase_jwks_url: str = ""
    supabase_jwt_audience: str = "authenticated"

    # --- Storage ----------------------------------------------------------
    storage_dir: str = str(API_ROOT / "var" / "storage")
    max_upload_bytes: int = 15 * 1024 * 1024
    max_document_pages: int = 200

    # --- AI ---------------------------------------------------------------
    ai_provider: Literal["gemini", "openai", "fake", "none"] = "gemini"
    ai_model: str = ""
    ai_fallback_models: str = ""  # comma separated, tried in order on overload
    gemini_api_key: str = Field(default="", repr=False)
    openai_api_key: str = Field(default="", repr=False)
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    openai_base_url: str = "https://api.openai.com/v1"
    ai_timeout_seconds: float = 120.0
    ai_max_retries: int = 3
    ai_max_input_chars: int = 48_000
    ai_max_tokens_per_request: int = 16_000
    ai_concurrency: int = 4
    ai_reasoning_effort: str = "low"  # passed to providers that support it; empty to omit

    # --- Jobs / worker ----------------------------------------------------
    job_lease_seconds: int = 300
    job_poll_interval_seconds: float = 1.0
    run_worker_in_process: bool = False

    # --- Web --------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    allow_external_send: bool = False  # P0: there is no external send at all.

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        if self.ai_provider == "fake" and self.app_env != "test":
            raise ValueError("AI_PROVIDER=fake is only allowed when APP_ENV=test")
        if self.auth_provider == "local" and not self.jwt_secret:
            if self.app_env in ("staging", "production"):
                raise ValueError("JWT_SECRET is required outside development/test")
        if self.auth_provider == "supabase" and not self.supabase_jwks_url:
            raise ValueError("SUPABASE_JWKS_URL is required when AUTH_PROVIDER=supabase")
        if self.allow_external_send:
            raise ValueError("ALLOW_EXTERNAL_SEND must stay false in P0 (no outbox implemented)")
        return self

    @property
    def effective_jwt_secret(self) -> str:
        # Development convenience only; staging/production refuse to start without a secret.
        return self.jwt_secret or "dev-only-insecure-secret-change-me-0123456789"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def resolved_ai_model(self) -> str:
        if self.ai_model:
            return self.ai_model
        # OpenAI has no default on purpose: pick and pin a model explicitly via AI_MODEL.
        return {"gemini": "gemini-3.5-flash", "fake": "fake-test-model"}.get(self.ai_provider, "")

    @property
    def fallback_model_list(self) -> list[str]:
        return [m.strip() for m in self.ai_fallback_models.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
