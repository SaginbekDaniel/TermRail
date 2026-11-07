from __future__ import annotations

from collections.abc import Callable

from app.core.config import Settings, get_settings
from app.llm.base import LLMNotConfigured, LLMProvider
from app.llm.openai_compat import OpenAICompatibleProvider

# Tests can install an override (e.g. a FakeLLMProvider instance) here.
_override: Callable[[], LLMProvider] | None = None


def set_provider_override(factory: Callable[[], LLMProvider] | None) -> None:
    global _override
    _override = factory


def get_llm(settings: Settings | None = None) -> LLMProvider:
    """Build the configured provider or raise LLMNotConfigured (never a silent fallback)."""
    if _override is not None:
        return _override()
    settings = settings or get_settings()
    if settings.ai_provider == "none":
        raise LLMNotConfigured("AI is disabled (AI_PROVIDER=none)")
    if settings.ai_provider == "fake":
        from app.llm.fake import FakeLLMProvider

        return FakeLLMProvider()
    if settings.ai_provider == "gemini":
        return OpenAICompatibleProvider(
            name="gemini",
            base_url=settings.gemini_base_url,
            api_key=settings.gemini_api_key,
            model=settings.resolved_ai_model,
            fallback_models=settings.fallback_model_list,
            timeout=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            reasoning_effort=settings.ai_reasoning_effort or None,
        )
    if settings.ai_provider == "openai":
        return OpenAICompatibleProvider(
            name="openai",
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            model=settings.resolved_ai_model,
            fallback_models=settings.fallback_model_list,
            timeout=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            reasoning_effort=settings.ai_reasoning_effort or None,
        )
    raise LLMNotConfigured(f"Unknown AI provider {settings.ai_provider}")


def describe_ai(settings: Settings | None = None) -> dict[str, object]:
    """Non-secret description of the AI connection for the Settings screen."""
    settings = settings or get_settings()
    try:
        provider = get_llm(settings)
        return {"provider": provider.name, "model": provider.model, "configured": True, "error": None}
    except LLMNotConfigured as exc:
        return {
            "provider": settings.ai_provider,
            "model": settings.resolved_ai_model or None,
            "configured": False,
            "error": exc.code,
        }
