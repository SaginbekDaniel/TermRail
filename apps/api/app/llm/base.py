"""Provider-agnostic LLM interface. The model is an untrusted component: callers must validate
everything it returns (schema, evidence references, policy) before persisting anything."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    code = "AI_ERROR"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, retryable: bool | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if retryable is not None:
            self.retryable = retryable


class LLMNotConfigured(LLMError):
    code = "AI_PROVIDER_NOT_CONFIGURED"
    retryable = False


class LLMUnavailable(LLMError):
    code = "AI_PROVIDER_UNAVAILABLE"
    retryable = True


class LLMInvalidOutput(LLMError):
    code = "AI_INVALID_OUTPUT"
    retryable = True


@dataclass
class LLMResult:
    data: dict[str, Any]
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str
    model: str

    async def generate_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> LLMResult:
        """Return a JSON object matching `schema`.

        `context` carries the same structured data that was rendered into `user`; real providers
        ignore it (they only see the prompt). It exists so the test-only fake provider can behave
        deterministically without parsing prompt text.
        """
        ...
