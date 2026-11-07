"""Durable job queue: lease recovery after a worker crash, retry with backoff, dead-letter."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.db.models import Job
from app.db.session import get_sessionmaker
from app.jobs import queue
from tests.conftest import Actor


async def _job(actor: Actor, kind: str = "noop_test") -> uuid.UUID:
    async with get_sessionmaker()() as s:
        job = await queue.enqueue(s, kind=kind, workspace_id=uuid.UUID(actor.workspace_id), payload={},
                                  idempotency_key=f"k-{uuid.uuid4()}")
        await s.commit()
        return job.id


async def test_enqueue_is_idempotent(alice: Actor) -> None:
    async with get_sessionmaker()() as s:
        a = await queue.enqueue(s, kind="x", workspace_id=uuid.UUID(alice.workspace_id), payload={}, idempotency_key="same")
        b = await queue.enqueue(s, kind="x", workspace_id=uuid.UUID(alice.workspace_id), payload={}, idempotency_key="same")
        await s.commit()
    assert a.id == b.id


async def test_crashed_worker_lease_is_reclaimed(alice: Actor) -> None:
    job_id = await _job(alice)
    async with get_sessionmaker()() as s:
        claimed = await queue.claim(s, "worker-a", ["noop_test"])
        assert claimed is not None and claimed.id == job_id and claimed.lease_owner == "worker-a"
        assert await queue.claim(s, "worker-b", ["noop_test"]) is None  # leased: invisible to others
        # worker-a dies; its lease expires.
        claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
        again = await queue.claim(s, "worker-b", ["noop_test"])
    assert again is not None and again.id == job_id and again.lease_owner == "worker-b" and again.attempts == 2


async def test_retry_with_backoff_then_dead_letter(alice: Actor) -> None:
    job_id = await _job(alice)
    async with get_sessionmaker()() as s:
        job = await s.get(Job, job_id)
        assert job is not None
        job.max_attempts = 2
        job.attempts = 1
        assert await queue.mark_failed(s, job, code="AI_PROVIDER_UNAVAILABLE", message="503", retryable=True)
        assert job.status == "QUEUED" and job.next_run_at > datetime.now(UTC)
        job.attempts = 2
        assert not await queue.mark_failed(s, job, code="AI_PROVIDER_UNAVAILABLE", message="503", retryable=True)
        assert job.status == "FAILED" and job.last_error_code == "AI_PROVIDER_UNAVAILABLE"
        await s.commit()


async def test_non_retryable_error_fails_immediately(alice: Actor) -> None:
    job_id = await _job(alice)
    async with get_sessionmaker()() as s:
        job = await s.get(Job, job_id)
        assert job is not None
        job.attempts = 1
        assert not await queue.mark_failed(s, job, code="AI_PROVIDER_NOT_CONFIGURED", message="no key", retryable=False)
        assert job.status == "FAILED"
