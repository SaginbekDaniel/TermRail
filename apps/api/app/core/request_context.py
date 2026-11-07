"""Per-request correlation id, available to logs, errors and audit events."""

from __future__ import annotations

import contextvars
import uuid

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None = None) -> str:
    rid = value or str(uuid.uuid4())
    _request_id.set(rid)
    return rid
