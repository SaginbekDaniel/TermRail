"""Public Telegram webhook ingress (Telegram service auth, NOT bearer auth).

POST /api/v1/integrations/telegram/webhook
- 404 unless TELEGRAM_ENABLED (the route does not advertise itself on servers without the integration).
- X-Telegram-Bot-Api-Secret-Token compared in constant time; never a query-string token.
- Body size bounded before parsing; JSON validated against a typed subset of Update.
- The idempotency receipt and all effects are committed in ONE transaction before answering 2xx. Any
  database error propagates as 5xx so Telegram redelivers; a duplicate update_id is acknowledged as a no-op.
- Logs carry update id/type/outcome only: no message text, no tokens.
"""

from __future__ import annotations

import hmac
import json
import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.deps import DB
from app.core.config import get_settings
from app.core.errors import AppError, NotFound, PayloadTooLarge, TooManyRequests, Unauthorized
from app.integrations.telegram.ingress import process_update
from app.integrations.telegram.schemas import TgUpdate

log = logging.getLogger("termrail.telegram")
router = APIRouter()

SECRET_HEADER = "x-telegram-bot-api-secret-token"  # noqa: S105 - header name, not a secret
_bad_attempts: dict[str, deque[float]] = defaultdict(deque)
_BAD_WINDOW = 60.0
_BAD_MAX = 20


def _throttle_bad_secret(client: str) -> None:
    now = time.monotonic()
    q = _bad_attempts[client]
    while q and now - q[0] > _BAD_WINDOW:
        q.popleft()
    if len(q) >= _BAD_MAX:
        raise TooManyRequests("Too many invalid webhook calls")
    q.append(now)


async def _read_limited(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise PayloadTooLarge("Update too large", code="PAYLOAD_TOO_LARGE")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise PayloadTooLarge("Update too large", code="PAYLOAD_TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/integrations/telegram/webhook", include_in_schema=False)
async def telegram_webhook(request: Request, db: DB) -> JSONResponse:
    settings = get_settings()
    if not settings.telegram_enabled or settings.telegram_bot_id is None:
        raise NotFound("Not found")
    client = request.client.host if request.client else "unknown"
    provided = request.headers.get(SECRET_HEADER, "")
    if not hmac.compare_digest(provided.encode(), settings.telegram_webhook_secret.encode()):
        _throttle_bad_secret(client)
        log.warning("telegram_webhook_bad_secret")
        raise Unauthorized("Invalid webhook secret", code="INVALID_WEBHOOK_SECRET")

    raw = await _read_limited(request, settings.telegram_max_webhook_bytes)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AppError("Malformed update", code="INVALID_UPDATE", status_code=400) from exc
    try:
        update = TgUpdate.model_validate(data)
    except ValidationError:
        # Not a shape we understand. Acknowledge so Telegram does not redeliver a poison update forever.
        log.warning("telegram_update_unparseable")
        return JSONResponse({"ok": True, "outcome": "IGNORED_UNPARSEABLE"})

    outcome = await process_update(db, update, bot_id=settings.telegram_bot_id)
    await db.commit()  # durable BEFORE the 2xx acknowledgement
    log.info("telegram_update", extra={"update_id": update.update_id, "kind": update.kind, "outcome": outcome})
    return JSONResponse({"ok": True, "outcome": outcome})
