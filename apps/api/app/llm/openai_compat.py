"""Adapter for any OpenAI-compatible Chat Completions endpoint with JSON-schema structured output.

Used for Google Gemini (generativelanguage.googleapis.com/v1beta/openai) and OpenAI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any

import httpx

from app.llm.base import LLMInvalidOutput, LLMNotConfigured, LLMResult, LLMUnavailable

log = logging.getLogger("scopelock.llm")

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    if isinstance(body, list) and body:
        body = body[0]
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message", ""))[:300]
    return str(body)[:300]


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        fallback_models: list[str] | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
        reasoning_effort: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise LLMNotConfigured(f"{name}: API key is not set")
        if not model:
            raise LLMNotConfigured(f"{name}: AI_MODEL is not set")
        self.name = name
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._models = [model, *[m for m in (fallback_models or []) if m != model]]
        self._timeout = timeout
        self._max_retries = max_retries
        self._reasoning_effort = reasoning_effort
        self._transport = transport

    async def generate_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> LLMResult:
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for model in self._models:
                try:
                    return await self._call_with_retries(client, model, task, system, user, schema)
                except LLMUnavailable as exc:
                    last_error = exc
                    log.warning("llm_model_unavailable", extra={"provider": self.name, "model": model, "task": task})
                    continue
        assert last_error is not None
        raise last_error

    async def _call_with_retries(
        self,
        client: httpx.AsyncClient,
        model: str,
        task: str,
        system: str,
        user: str,
        schema: dict[str, Any],
    ) -> LLMResult:
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": task, "strict": True, "schema": schema},
            },
        }
        if self._reasoning_effort:
            body["reasoning_effort"] = self._reasoning_effort
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        attempt = 0
        while True:
            attempt += 1
            try:
                resp = await client.post(f"{self._base_url}/chat/completions", json=body, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt > self._max_retries:
                    raise LLMUnavailable(f"{self.name} request failed: {type(exc).__name__}") from exc
                await asyncio.sleep(self._backoff(attempt))
                continue

            if resp.status_code in (401, 403):
                raise LLMNotConfigured(
                    f"{self.name} rejected the credentials ({resp.status_code})", code="AI_PROVIDER_AUTH_FAILED"
                )
            if resp.status_code == 404:
                # Unknown/retired model: try the next fallback model.
                raise LLMUnavailable(f"{self.name} model '{model}' is not available: {_error_message(resp)}")
            if resp.status_code in RETRYABLE_STATUS:
                if attempt > self._max_retries:
                    raise LLMUnavailable(f"{self.name} unavailable ({resp.status_code}): {_error_message(resp)}")
                await asyncio.sleep(self._backoff(attempt))
                continue
            if resp.status_code >= 400:
                raise LLMInvalidOutput(
                    f"{self.name} rejected the request ({resp.status_code}): {_error_message(resp)}",
                    retryable=False,
                    code="AI_REQUEST_REJECTED",
                )

            payload = resp.json()
            try:
                choice = payload["choices"][0]
                content = choice["message"]["content"]
                data = json.loads(content)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                if attempt > self._max_retries:
                    raise LLMInvalidOutput(f"{self.name} returned non-JSON output") from exc
                continue
            if not isinstance(data, dict):
                raise LLMInvalidOutput(f"{self.name} returned a non-object JSON value")
            usage_raw = payload.get("usage") or {}
            usage = {
                k: int(v)
                for k, v in usage_raw.items()
                if k in ("prompt_tokens", "completion_tokens", "total_tokens") and isinstance(v, int)
            }
            log.info(
                "llm_call",
                extra={"provider": self.name, "model": model, "task": task, "attempt": attempt, **usage},
            )
            return LLMResult(data=data, provider=self.name, model=model, usage=usage)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(20.0, 1.5 * 2 ** (attempt - 1)) + random.uniform(0, 0.75)  # noqa: S311 - jitter, not crypto
