"""Synthetic Telegram Bot API updates delivered through the REAL webhook route and database.

These are explicitly deterministic mocks of Telegram's side only (no live Telegram account exists in CI).
"""

from __future__ import annotations

import itertools
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.clock import set_clock_override, utcnow
from tests.conftest import Actor, approved_baseline, create_project, run_jobs

SECRET = os.environ["TELEGRAM_WEBHOOK_SECRET"]
WEBHOOK = "/integrations/telegram/webhook"
OWNER_TG = 5550001
CLIENT_TG = 7770001

_update_ids = itertools.count(1000)
_message_ids = itertools.count(1)


class Clock:
    """Controlled time: tests move it instead of sleeping (e.g. through the 120 s debounce)."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=5)
        set_clock_override(self.now)

    def advance(self, seconds: float) -> datetime:
        self.now = self.now + timedelta(seconds=seconds)
        set_clock_override(self.now)
        return self.now


class TG:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def send(self, update: dict[str, Any], *, secret: str | None = SECRET) -> httpx.Response:
        headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret is not None else {}
        return await self.client.post(WEBHOOK, json=update, headers=headers)

    async def ok(self, update: dict[str, Any]) -> str:
        r = await self.send(update)
        assert r.status_code == 200, r.text
        return str(r.json()["outcome"])

    @staticmethod
    def uid() -> int:
        return next(_update_ids)

    @staticmethod
    def start(nonce: str, *, tg_user: int = OWNER_TG, username: str = "owner") -> dict[str, Any]:
        return {
            "update_id": TG.uid(),
            "message": {
                "message_id": next(_message_ids),
                "date": int(utcnow().timestamp()),
                "chat": {"id": tg_user, "type": "private", "first_name": "Owner"},
                "from": {"id": tg_user, "is_bot": False, "first_name": "Owner", "username": username},
                "text": f"/start {nonce}",
            },
        }

    @staticmethod
    def connection(conn_id: str = "bc-1", *, tg_user: int = OWNER_TG, enabled: bool = True) -> dict[str, Any]:
        return {
            "update_id": TG.uid(),
            "business_connection": {
                "id": conn_id,
                "user": {"id": tg_user, "is_bot": False, "first_name": "Owner", "username": "owner"},
                "user_chat_id": tg_user,
                "date": int(utcnow().timestamp()),
                "is_enabled": enabled,
                "rights": {"can_read_messages": True},
            },
        }

    @staticmethod
    def message(
        text: str | None,
        *,
        conn_id: str = "bc-1",
        chat_id: int = CLIENT_TG,
        from_id: int | None = None,
        message_id: int | None = None,
        edited: bool = False,
        chat_type: str = "private",
        photo: bool = False,
    ) -> dict[str, Any]:
        msg: dict[str, Any] = {
            "message_id": message_id or next(_message_ids),
            "date": int(utcnow().timestamp()),
            "business_connection_id": conn_id,
            "chat": {"id": chat_id, "type": chat_type, "first_name": "Aster", "last_name": "Client"},
            "from": {"id": from_id or chat_id, "is_bot": False, "first_name": "Aster"},
        }
        if text is not None:
            msg["caption" if photo else "text"] = text
        if photo:
            msg["photo"] = [{"file_id": "x", "file_unique_id": "y", "width": 1, "height": 1}]
        key = "edited_business_message" if edited else "business_message"
        return {"update_id": TG.uid(), key: msg}

    @staticmethod
    def deleted(message_ids: list[int], *, conn_id: str = "bc-1", chat_id: int = CLIENT_TG) -> dict[str, Any]:
        return {
            "update_id": TG.uid(),
            "deleted_business_messages": {
                "business_connection_id": conn_id,
                "chat": {"id": chat_id, "type": "private", "first_name": "Aster"},
                "message_ids": message_ids,
            },
        }


def nonce_from(deep_link: str) -> str:
    return deep_link.split("start=", 1)[1]


async def link(actor: Actor, tg: TG, *, conn_id: str = "bc-1", tg_user: int = OWNER_TG) -> dict[str, Any]:
    r = await actor.post(f"/workspaces/{actor.workspace_id}/integrations/telegram/link-intents")
    assert r.status_code == 201, r.text
    assert await tg.ok(TG.start(nonce_from(r.json()["deep_link"]), tg_user=tg_user)) == "LINK_VERIFIED"
    assert await tg.ok(TG.connection(conn_id, tg_user=tg_user)) == "LINK_CLAIMED"
    status = (await actor.get(f"/workspaces/{actor.workspace_id}/integrations/telegram/status")).json()
    assert status["state"] == "CONNECTED"
    return status


async def monitored_project(actor: Actor, tg: TG, *, chat_id: int = CLIENT_TG, conn_id: str = "bc-1") -> dict:
    """Project with an approved baseline, linked Telegram, the client chat bound and monitoring enabled."""
    p = await create_project(actor)
    await approved_baseline(actor, p["id"])
    await link(actor, tg, conn_id=conn_id)
    # The chat becomes selectable only after Telegram actually delivered something from it.
    assert await tg.ok(TG.message("Hello!", chat_id=chat_id, conn_id=conn_id)) == "METADATA_ONLY"
    r = await actor.post(f"/projects/{p['id']}/telegram/chat-binding", json={"chat_id": chat_id})
    assert r.status_code == 201, r.text
    r = await actor.patch(
        f"/projects/{p['id']}/telegram/monitoring", json={"enabled": True, "privacy_acknowledged": True}
    )
    assert r.status_code == 200 and r.json()["status"] == "MONITORING", r.text
    return p


async def settle(clock: Clock, seconds: float = 121) -> None:
    """Let the debounce window pass and run every due job (finalize -> analysis -> signals)."""
    clock.advance(seconds)
    for _ in range(4):
        if not await run_jobs():
            break
