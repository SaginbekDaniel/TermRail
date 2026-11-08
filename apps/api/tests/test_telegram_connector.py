"""Telegram connector: webhook security, idempotency, ownership linking, chat permissions, revocation,
privacy and tenant isolation (spec v2 G2/G5)."""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import (
    TelegramBusinessConnection,
    TelegramChatCandidate,
    TelegramMessage,
    TelegramUpdateReceipt,
)
from app.db.session import get_sessionmaker
from app.llm.factory import set_provider_override
from app.llm.fake import FakeLLMProvider
from tests.conftest import Actor, approved_baseline, create_project, run_jobs
from tests.telegram_helpers import CLIENT_TG, OWNER_TG, TG, Clock, link, monitored_project, nonce_from, settle


async def _count(model, *where) -> int:  # type: ignore[no-untyped-def]
    async with get_sessionmaker()() as s:
        return int(await s.scalar(select(func.count()).select_from(model).where(*where)) or 0)


# ---------------------------------------------------------------- webhook security
async def test_webhook_requires_secret(client) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    assert (await tg.send(TG.connection(), secret=None)).status_code == 401
    assert (await tg.send(TG.connection(), secret="wrong" * 10)).status_code == 401
    assert await _count(TelegramUpdateReceipt) == 0  # nothing recorded for unauthenticated calls


async def test_webhook_hidden_when_disabled(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "telegram_enabled", False)
    r = await TG(client).send(TG.connection())
    assert r.status_code == 404


async def test_webhook_rejects_oversized_and_malformed(client) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    big = {"update_id": 1, "message": {"text": "x" * (300 * 1024)}}
    assert (await tg.send(big)).status_code == 413
    r = await client.post(
        "/integrations/telegram/webhook",
        content=b"{not json",
        headers={"X-Telegram-Bot-Api-Secret-Token": get_settings().telegram_webhook_secret},
    )
    assert r.status_code == 400
    # A well-formed but unknown shape is acknowledged (no infinite redelivery) and ignored.
    assert (await tg.send({"update_id": "nope"})).json()["outcome"] == "IGNORED_UNPARSEABLE"


async def test_same_update_delivered_five_times_is_processed_once(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    await monitored_project(alice, tg)
    upd = TG.message("Please add card payments")
    outcomes = [await tg.ok(upd) for _ in range(5)]
    assert outcomes[0] == "MESSAGE_STORED" and set(outcomes[1:]) == {"DUPLICATE_UPDATE"}
    assert await _count(TelegramUpdateReceipt, TelegramUpdateReceipt.update_id == upd["update_id"]) == 1
    assert await _count(TelegramMessage) == 1
    # Same Telegram message under a new update_id (e.g. replay) is still stored once.
    upd2 = TG.message("Please add card payments", message_id=upd["business_message"]["message_id"])
    assert await tg.ok(upd2) == "DUPLICATE_MESSAGE"
    assert await _count(TelegramMessage) == 1


# ---------------------------------------------------------------- ownership linking
async def test_link_intent_is_single_use_and_expires(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    clock = Clock()
    nonce = nonce_from(
        (await alice.post(f"/workspaces/{alice.workspace_id}/integrations/telegram/link-intents")).json()["deep_link"]
    )
    clock.advance(601)  # TTL is 10 minutes
    assert await tg.ok(TG.start(nonce)) == "LINK_EXPIRED"
    assert await tg.ok(TG.start(nonce)) == "LINK_NONCE_ALREADY_USED"

    nonce2 = nonce_from(
        (await alice.post(f"/workspaces/{alice.workspace_id}/integrations/telegram/link-intents")).json()["deep_link"]
    )
    assert await tg.ok(TG.start(nonce2)) == "LINK_VERIFIED"
    assert await tg.ok(TG.start(nonce2, tg_user=999)) == "LINK_NONCE_ALREADY_USED"  # cannot be re-claimed
    assert await tg.ok(TG.start("forgedNonce123456")) == "LINK_UNKNOWN_NONCE"


async def test_wrong_telegram_user_cannot_claim(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    nonce = nonce_from(
        (await alice.post(f"/workspaces/{alice.workspace_id}/integrations/telegram/link-intents")).json()["deep_link"]
    )
    assert await tg.ok(TG.start(nonce, tg_user=OWNER_TG)) == "LINK_VERIFIED"
    # Someone else connects the bot to THEIR Telegram Business account: not claimable by Alice.
    assert await tg.ok(TG.connection("bc-other", tg_user=4242)) == "CONNECTION_UNCLAIMED"
    status = (await alice.get(f"/workspaces/{alice.workspace_id}/integrations/telegram/status")).json()
    assert status["state"] == "LINK_PENDING" and status["connection"] is None
    # Messages on an unclaimed connection are not stored, not even metadata.
    assert await tg.ok(TG.message("hi there, add CRM", conn_id="bc-other")) == "IGNORED_CONNECTION_INACTIVE"
    assert await _count(TelegramChatCandidate) == 0


async def test_connection_before_handshake_is_claimed_later(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    assert await tg.ok(TG.connection("bc-early")) == "CONNECTION_UNCLAIMED"
    nonce = nonce_from(
        (await alice.post(f"/workspaces/{alice.workspace_id}/integrations/telegram/link-intents")).json()["deep_link"]
    )
    assert await tg.ok(TG.start(nonce)) == "LINK_CLAIMED"
    status = (await alice.get(f"/workspaces/{alice.workspace_id}/integrations/telegram/status")).json()
    assert status["state"] == "CONNECTED" and status["connection"]["telegram_username"] == "owner"
    assert status["connection"]["rights"] == ["can_read_messages"]


async def test_connection_cannot_be_claimed_by_another_workspace(client, alice: Actor, bob: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    await link(alice, tg)
    # Bob proves the SAME Telegram account (e.g. shared phone) - the live connection stays with Alice.
    nonce = nonce_from(
        (await bob.post(f"/workspaces/{bob.workspace_id}/integrations/telegram/link-intents")).json()["deep_link"]
    )
    assert await tg.ok(TG.start(nonce)) == "LINK_VERIFIED"
    assert await tg.ok(TG.connection("bc-1")) == "CONNECTION_UPDATED"
    assert (await bob.get(f"/workspaces/{bob.workspace_id}/integrations/telegram/status")).json()["connection"] is None
    async with get_sessionmaker()() as s:
        conn = await s.scalar(select(TelegramBusinessConnection))
        assert conn is not None and str(conn.workspace_id) == alice.workspace_id


async def test_disconnected_connection_moves_to_new_workspace_without_history(client, alice: Actor, bob: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    await monitored_project(alice, tg)
    await tg.ok(TG.message("Please add card payments"))
    assert (await alice.post(f"/workspaces/{alice.workspace_id}/integrations/telegram/disconnect")).status_code == 204
    nonce = nonce_from(
        (await bob.post(f"/workspaces/{bob.workspace_id}/integrations/telegram/link-intents")).json()["deep_link"]
    )
    assert await tg.ok(TG.start(nonce)) == "LINK_CLAIMED"
    assert (await bob.get(f"/workspaces/{bob.workspace_id}/integrations/telegram/status")).json()["state"] == "CONNECTED"
    # Bob sees no chats from Alice's era until Telegram delivers something new.
    assert (await bob.get(f"/workspaces/{bob.workspace_id}/integrations/telegram/eligible-chats")).json() == []
    assert await _count(TelegramBusinessConnection) == 2  # Alice's history row archived, not re-parented


async def test_only_managers_can_link(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import make_actor

    viewer = await make_actor(client, "vera")
    r = await alice.post(f"/workspaces/{alice.workspace_id}/members", json={"email": viewer.email, "role": "VIEWER"})
    assert r.status_code in (200, 201), r.text
    r = await viewer.post(f"/workspaces/{alice.workspace_id}/integrations/telegram/link-intents")
    assert r.status_code == 403


# ---------------------------------------------------------------- chat permissions + privacy
async def test_unselected_chat_is_never_stored_or_analysed(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    clock = Clock()
    fake = FakeLLMProvider()
    set_provider_override(lambda: fake)
    await monitored_project(alice, tg)
    calls_before = len(fake.calls)
    other_chat = 8880001
    out = await tg.ok(TG.message("Please add a CRM integration and card payments", chat_id=other_chat))
    assert out == "METADATA_ONLY"
    await settle(clock)
    assert await _count(TelegramMessage, TelegramMessage.chat_id == other_chat) == 0
    assert len(fake.calls) == calls_before  # no AI request for an unselected chat
    chats = (await alice.get(f"/workspaces/{alice.workspace_id}/integrations/telegram/eligible-chats")).json()
    assert {c["chat_id"] for c in chats} == {CLIENT_TG, other_chat}  # metadata only, for the picker


async def test_chat_id_cannot_be_guessed_into_monitoring(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    p = await create_project(alice)
    await link(alice, tg)
    r = await alice.post(f"/projects/{p['id']}/telegram/chat-binding", json={"chat_id": 123456789})
    assert r.status_code == 404 and r.json()["error"]["code"] == "CHAT_NOT_ELIGIBLE"


async def test_monitoring_requires_baseline_and_consent(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    p = await create_project(alice)
    await link(alice, tg)
    await tg.ok(TG.message("Hello"))
    assert (await alice.post(f"/projects/{p['id']}/telegram/chat-binding", json={"chat_id": CLIENT_TG})).status_code == 201
    st = (await alice.get(f"/projects/{p['id']}/telegram/chat-binding")).json()
    assert st["status"] == "NEEDS_BASELINE"
    r = await alice.patch(f"/projects/{p['id']}/telegram/monitoring", json={"enabled": True, "privacy_acknowledged": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "BASELINE_REQUIRED"
    await approved_baseline(alice, p["id"])
    r = await alice.patch(f"/projects/{p['id']}/telegram/monitoring", json={"enabled": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CONSENT_REQUIRED"
    r = await alice.patch(f"/projects/{p['id']}/telegram/monitoring", json={"enabled": True, "privacy_acknowledged": True})
    assert r.status_code == 200 and r.json()["status"] == "MONITORING"
    assert r.json()["settings"]["auto_send_messages"] is False and r.json()["settings"]["drafts_only"] is True


async def test_one_chat_one_project(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    p1 = await monitored_project(alice, tg)
    p2 = await create_project(alice, title="Second site")
    r = await alice.post(f"/projects/{p2['id']}/telegram/chat-binding", json={"chat_id": CLIENT_TG})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CHAT_ALREADY_BOUND"
    await tg.ok(TG.message("Hello", chat_id=CLIENT_TG + 1))
    r = await alice.post(f"/projects/{p1['id']}/telegram/chat-binding", json={"chat_id": CLIENT_TG + 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PROJECT_ALREADY_BOUND"


async def test_message_bodies_are_encrypted_at_rest_and_never_logged(client, alice: Actor, caplog) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    await monitored_project(alice, tg)
    secret_text = "Please add card payments for VIP-ORDER-7731"
    with caplog.at_level(logging.DEBUG):
        assert await tg.ok(TG.message(secret_text)) == "MESSAGE_STORED"
    assert "VIP-ORDER-7731" not in caplog.text
    async with get_sessionmaker()() as s:
        m = await s.scalar(select(TelegramMessage))
        assert m is not None and m.text_ciphertext is not None
        assert b"VIP-ORDER-7731" not in bytes(m.text_ciphertext)


async def test_media_is_not_downloaded_or_analysed(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    await monitored_project(alice, tg)
    assert await tg.ok(TG.message(None, photo=True)) == "MESSAGE_MEDIA_ONLY"
    async with get_sessionmaker()() as s:
        m = await s.scalar(select(TelegramMessage))
        assert m is not None and m.has_unsupported_media and m.text_ciphertext is None


async def test_group_chats_are_ignored(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    await link(alice, tg)
    assert await tg.ok(TG.message("Add CRM", chat_id=-100123, chat_type="supergroup")) == "IGNORED_CHAT_TYPE"
    assert await _count(TelegramChatCandidate) == 0


# ---------------------------------------------------------------- revocation
async def test_revocation_stops_ingestion_and_purges_buffer(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    clock = Clock()
    p = await monitored_project(alice, tg)
    await tg.ok(TG.message("Please add card payments"))
    assert await tg.ok(TG.connection("bc-1", enabled=False)) == "CONNECTION_REVOKED"
    status = (await alice.get(f"/workspaces/{alice.workspace_id}/integrations/telegram/status")).json()
    assert status["state"] == "ACCESS_REVOKED"
    b = (await alice.get(f"/projects/{p['id']}/telegram/chat-binding")).json()
    assert b["status"] == "PAUSED" and not b["monitoring_enabled"] and b["last_batch"]["state"] == "CANCELLED"
    async with get_sessionmaker()() as s:
        assert (await s.scalar(select(TelegramMessage))).text_ciphertext is None  # type: ignore[union-attr]
    assert await tg.ok(TG.message("Please add a personal account")) == "IGNORED_CONNECTION_INACTIVE"
    await settle(clock)
    assert (await alice.get(f"/projects/{p['id']}/requests")).json() == []
    # Re-enabling in Telegram restores the connection but monitoring must be re-enabled by a person.
    assert await tg.ok(TG.connection("bc-1", enabled=True)) == "CONNECTION_RESTORED"
    b = (await alice.get(f"/projects/{p['id']}/telegram/chat-binding")).json()
    assert b["status"] == "READY"


async def test_disconnect_closes_bindings(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    p = await monitored_project(alice, tg)
    assert (await alice.post(f"/workspaces/{alice.workspace_id}/integrations/telegram/disconnect")).status_code == 204
    assert (await alice.get(f"/projects/{p['id']}/telegram/chat-binding")).json()["status"] == "UNBOUND"
    assert await tg.ok(TG.message("Please add card payments")) == "IGNORED_CONNECTION_INACTIVE"


# ---------------------------------------------------------------- tenant isolation
async def test_cross_tenant_access_is_404(client, alice: Actor, bob: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    clock = Clock()
    p = await monitored_project(alice, tg)
    await tg.ok(TG.message("Please add card payments"))
    await settle(clock)
    sig = (await alice.get(f"/projects/{p['id']}/commercial-signals")).json()[0]
    assert (await bob.get(f"/projects/{p['id']}/telegram/chat-binding")).status_code == 404
    assert (await bob.get(f"/projects/{p['id']}/commercial-signals")).status_code == 404
    assert (await bob.get(f"/commercial-signals/{sig['id']}")).status_code == 404
    r = await bob.post(f"/commercial-signals/{sig['id']}/dismiss", json={"expected_version": sig["version"], "reason": "x" * 5})
    assert r.status_code == 404
    assert (await bob.get(f"/workspaces/{alice.workspace_id}/integrations/telegram/status")).status_code == 404
    bp = await create_project(bob)
    r = await bob.post(f"/projects/{bp['id']}/telegram/chat-binding", json={"chat_id": CLIENT_TG})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TELEGRAM_NOT_CONNECTED"


async def test_db_rejects_cross_tenant_binding(alice: Actor, bob: Actor, client) -> None:  # type: ignore[no-untyped-def]
    """Defence in depth: even a buggy service cannot attach Bob's project to Alice's connection."""
    import uuid

    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.db.models import TelegramChatBinding

    tg = TG(client)
    await link(alice, tg)
    bp = await create_project(bob)
    async with get_sessionmaker()() as s:
        conn = await s.scalar(select(TelegramBusinessConnection))
        assert conn is not None
        s.add(
            TelegramChatBinding(
                workspace_id=uuid.UUID(alice.workspace_id),
                project_id=uuid.UUID(bp["id"]),
                connection_id=conn.id,
                chat_id=CLIENT_TG,
                created_by=conn.linked_by,
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_no_ai_and_no_jobs_for_greeting_only_chat(client, alice: Actor) -> None:  # type: ignore[no-untyped-def]
    tg = TG(client)
    clock = Clock()
    fake = FakeLLMProvider()
    set_provider_override(lambda: fake)
    p = await monitored_project(alice, tg)
    n = len(fake.calls)
    await tg.ok(TG.message("Привет, как дела?"))
    await tg.ok(TG.message("Спасибо!"))
    await settle(clock)
    assert len(fake.calls) == n
    assert (await alice.get(f"/projects/{p['id']}/requests")).json() == []
    b = (await alice.get(f"/projects/{p['id']}/telegram/chat-binding")).json()
    assert b["last_batch"]["state"] == "NO_ACTION" and b["last_batch"]["outcome"] == "NO_CANDIDATES"
    assert await run_jobs() == 0
