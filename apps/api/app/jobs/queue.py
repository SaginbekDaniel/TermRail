"""Postgres-backed durable job queue.

- enqueue() is idempotent on `idempotency_key` (unique constraint).
- claim() uses FOR UPDATE SKIP LOCKED and also re-claims RUNNING jobs whose lease expired,
  so a crashed worker never loses a job permanently.
- Failures are retried with exponential backoff; after max_attempts (or a non-retryable
  error) the job ends in FAILED, which acts as the dead-letter state and is visible in the UI.
- Jobs can be scheduled for later (`run_at`) and a handler can postpone itself by raising
  JobDeferred (e.g. a debounce window that moved); deferral does not consume an attempt.
- "Now" comes from app.core.clock so time-based behaviour is testable without sleeping.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import get_settings
from app.db.models import Job


async def enqueue(
    session: AsyncSession,
    *,
    kind: str,
    workspace_id: uuid.UUID,
    payload: dict[str, Any],
    idempotency_key: str,
    project_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    max_attempts: int = 3,
    run_at: datetime | None = None,
) -> Job:
    """Insert the job unless one with the same idempotency key exists; return the job either way."""
    stmt = (
        insert(Job)
        .values(
            id=uuid.uuid4(),
            kind=kind,
            workspace_id=workspace_id,
            project_id=project_id,
            payload=payload,
            idempotency_key=idempotency_key,
            created_by=created_by,
            max_attempts=max_attempts,
            status="QUEUED",
            attempts=0,
            next_run_at=run_at or utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    await session.execute(stmt)
    job = await session.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    assert job is not None
    return job


async def requeue(session: AsyncSession, job: Job) -> None:
    """Manual retry of a FAILED job (fresh attempt budget)."""
    job.status = "QUEUED"
    job.attempts = 0
    job.next_run_at = utcnow()
    job.lease_owner = None
    job.lease_expires_at = None
    job.last_error = None
    job.last_error_code = None
    job.finished_at = None


async def claim(session: AsyncSession, worker_id: str, kinds: list[str] | None = None) -> Job | None:
    lease = get_settings().job_lease_seconds
    kind_filter = "AND kind = ANY(:kinds)" if kinds else ""
    row = await session.execute(
        text(
            f"""
            UPDATE jobs SET status = 'RUNNING', attempts = attempts + 1, lease_owner = :worker,
                   lease_expires_at = :now + make_interval(secs => :lease), updated_at = now()
            WHERE id = (
                SELECT id FROM jobs
                WHERE ((status = 'QUEUED' AND next_run_at <= :now)
                    OR (status = 'RUNNING' AND lease_expires_at < :now))
                  {kind_filter}
                ORDER BY next_run_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id
            """
        ),
        {"worker": worker_id, "lease": lease, "now": utcnow(), **({"kinds": kinds} if kinds else {})},
    )
    job_id = row.scalar_one_or_none()
    await session.commit()
    if job_id is None:
        return None
    return await session.get(Job, job_id, populate_existing=True)


async def mark_succeeded(session: AsyncSession, job: Job) -> None:
    job.status = "SUCCEEDED"
    job.finished_at = utcnow()
    job.lease_owner = None
    job.lease_expires_at = None
    job.progress = None


async def mark_failed(session: AsyncSession, job: Job, *, code: str, message: str, retryable: bool) -> bool:
    """Returns True when the job will be retried, False when it is terminally FAILED."""
    job.last_error_code = code
    job.last_error = message[:2000]
    job.lease_owner = None
    job.lease_expires_at = None
    if retryable and job.attempts < job.max_attempts:
        job.status = "QUEUED"
        job.next_run_at = utcnow() + timedelta(seconds=min(300, 5 * 2 ** (job.attempts - 1)))
        return True
    job.status = "FAILED"
    job.finished_at = utcnow()
    return False


class JobDeferred(Exception):
    """Raised by a handler to run the same job again at `run_at` without consuming an attempt."""

    def __init__(self, run_at: datetime) -> None:
        super().__init__(f"deferred until {run_at.isoformat()}")
        self.run_at = run_at


def mark_deferred(job: Job, run_at: datetime) -> None:
    job.status = "QUEUED"
    job.attempts = max(0, job.attempts - 1)  # the claim counted an attempt; a deferral is not one
    job.next_run_at = run_at
    job.lease_owner = None
    job.lease_expires_at = None
