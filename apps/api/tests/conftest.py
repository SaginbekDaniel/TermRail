"""Test harness: real PostgreSQL (termrail_test), real migrations, real storage on a temp dir.

The only substitute is the AI provider: APP_ENV=test enables the deterministic FakeLLMProvider.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

os.environ["APP_ENV"] = "test"
os.environ["AI_PROVIDER"] = "fake"
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 32
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://termrail:termrail@localhost:5432/termrail_test"
)
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="termrail-test-")
os.environ["RUN_WORKER_IN_PROCESS"] = "false"
# Telegram connector in test mode: a fictional bot; nothing ever reaches api.telegram.org.
os.environ["TELEGRAM_ENABLED"] = "true"
os.environ["TELEGRAM_BOT_TOKEN"] = "7000000001:TEST-ONLY-NOT-A-REAL-TOKEN"
os.environ["TELEGRAM_BOT_USERNAME"] = "termrail_test_bot"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "test_webhook_secret_" + "s" * 24
os.environ["TELEGRAM_DATA_KEY"] = "8l8zXxgCJ5I3o1Rk3hW8lD3cUeUqk1b8JZy0w7N7a0Y="

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.clock import set_clock_override
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.jobs.runner import drain
from app.llm.factory import set_provider_override
from app.main import create_app

API_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = API_ROOT.parents[1] / "fixtures"

TABLES = [
    "signal_message_evidence", "commercial_signals", "telegram_batch_messages", "telegram_messages",
    "telegram_batches", "telegram_chat_bindings", "telegram_chat_candidates", "telegram_update_receipts",
    "telegram_link_intents", "telegram_business_connections",
    "change_order_exports", "approvals", "change_order_revisions", "change_orders", "estimate_lines", "estimates",
    "rate_cards", "finding_reviews", "finding_evidence", "findings", "analysis_runs", "request_items", "requests",
    "scope_evidence", "scope_items", "baseline_documents", "scope_baselines", "source_spans", "document_versions",
    "files", "jobs", "audit_events", "projects", "memberships", "workspaces", "users",
]


@pytest.fixture(scope="session", autouse=True)
async def _database() -> AsyncIterator[None]:
    url = get_settings().database_url
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = url
    # Alembic's env uses asyncio.run, so run it in a worker thread outside this event loop.
    import asyncio

    await asyncio.to_thread(command.upgrade, cfg, "head")
    yield


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    async with get_sessionmaker()() as s:
        await s.execute(text("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE"))
        await s.commit()
    set_provider_override(None)
    set_clock_override(None)
    yield
    set_provider_override(None)
    set_clock_override(None)


@pytest.fixture(scope="session")
def app():  # type: ignore[no-untyped-def]
    return create_app()


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        yield c


class Actor:
    """A signed-in user with their own workspace."""

    def __init__(self, client: httpx.AsyncClient, token: str, workspace_id: str, email: str) -> None:
        self.client = client
        self.token = token
        self.workspace_id = workspace_id
        self.email = email

    @property
    def h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def get(self, url: str, **kw):  # type: ignore[no-untyped-def]
        return await self.client.get(url, headers={**self.h, **kw.pop("headers", {})}, **kw)

    async def post(self, url: str, **kw):  # type: ignore[no-untyped-def]
        return await self.client.post(url, headers={**self.h, **kw.pop("headers", {})}, **kw)

    async def put(self, url: str, **kw):  # type: ignore[no-untyped-def]
        return await self.client.put(url, headers={**self.h, **kw.pop("headers", {})}, **kw)

    async def patch(self, url: str, **kw):  # type: ignore[no-untyped-def]
        return await self.client.patch(url, headers={**self.h, **kw.pop("headers", {})}, **kw)


async def make_actor(client: httpx.AsyncClient, name: str = "alice", workspace: str | None = None) -> Actor:
    email = f"{name}-{uuid.uuid4().hex[:6]}@example.com"
    r = await client.post("/auth/register", json={"email": email, "password": "correct horse battery", "display_name": name})
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    r = await client.post("/workspaces", json={"name": workspace or f"{name} studio"},
                          headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text
    return Actor(client, token, r.json()["id"], email)


@pytest.fixture
async def alice(client: httpx.AsyncClient) -> Actor:
    return await make_actor(client, "alice")


@pytest.fixture
async def bob(client: httpx.AsyncClient) -> Actor:
    return await make_actor(client, "bob")


async def create_project(actor: Actor, **overrides: object) -> dict:
    body = {"workspace_id": actor.workspace_id, "title": "Corporate website", "client_name": "Aster Logistics",
            "currency": "KZT", "budget": "1000000"}
    body.update(overrides)  # type: ignore[arg-type]
    r = await actor.post("/projects", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def upload(actor: Actor, project_id: str, fixture: str = "scope_contract.pdf") -> dict:
    data = (FIXTURES / fixture).read_bytes()
    r = await actor.post(f"/projects/{project_id}/documents", files={"file": (fixture, data)})
    assert r.status_code in (200, 201), r.text
    return r.json()["document"]


async def run_jobs() -> int:
    return await drain()


async def approved_baseline(actor: Actor, project_id: str) -> dict:
    """Upload the synthetic contract, extract candidates, accept them and approve the baseline."""
    await upload(actor, project_id)
    await run_jobs()
    r = await actor.post(f"/projects/{project_id}/scope/extract", json={})
    assert r.status_code == 202, r.text
    await run_jobs()
    state = (await actor.get(f"/projects/{project_id}/scope")).json()
    draft = state["draft"]
    assert draft["items"], "fake extractor produced no items"
    items = [
        {"id": i["id"], "title": i["title"], "description": i["description"], "inclusion_type": i["inclusion_type"],
         "acceptance_criteria": i["acceptance_criteria"], "source_span_ids": [e["span_id"] for e in i["evidence"]],
         "accepted": True}
        for i in draft["items"]
    ]
    r = await actor.put(f"/projects/{project_id}/scope/draft",
                        json={"expected_revision": draft["draft_revision"], "items": items})
    assert r.status_code == 200, r.text
    r = await actor.post(f"/projects/{project_id}/scope/approve",
                         json={"expected_revision": r.json()["draft_revision"], "note": "checked against contract"})
    assert r.status_code == 200, r.text
    return r.json()
