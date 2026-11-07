"""Job dispatch: claims jobs, runs handlers in their own DB session, records outcomes."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import Job
from app.db.session import get_sessionmaker
from app.domains import analysis, documents, scope
from app.jobs import queue
from app.llm.base import LLMError

log = logging.getLogger("scopelock.worker")

Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[Any]]
FailureHook = Callable[[AsyncSession, dict[str, Any], str, str, bool], Awaitable[None]]

HANDLERS: dict[str, Handler] = {
    "parse_document": documents.handle_parse_document,
    "extract_scope": scope.handle_extract_scope,
    "analyze_request": analysis.handle_analyze_request,
}
FAILURE_HOOKS: dict[str, FailureHook] = {
    "analyze_request": analysis.on_analysis_failed,
}


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


def _classify_error(exc: BaseException) -> tuple[str, str, bool]:
    if isinstance(exc, LLMError):
        return exc.code, exc.message, exc.retryable
    if isinstance(exc, AppError):
        return exc.code, exc.message, exc.retryable
    if isinstance(exc, TimeoutError):
        return "TIMEOUT", "The job timed out", True
    # Unknown errors: retry (bounded by max_attempts); the message carries no document content.
    return "INTERNAL_ERROR", f"{type(exc).__name__}", True


async def run_job(job: Job) -> None:
    handler = HANDLERS.get(job.kind)
    maker = get_sessionmaker()
    if handler is None:
        async with maker() as session:
            j = await session.get(Job, job.id)
            assert j is not None
            await queue.mark_failed(session, j, code="UNKNOWN_JOB_KIND", message=job.kind, retryable=False)
            await session.commit()
        return
    try:
        async with maker() as session:
            await handler(session, dict(job.payload))
    except Exception as exc:  # noqa: BLE001
        code, message, retryable = _classify_error(exc)
        log.warning(
            "job_failed",
            extra={
                "job_id": str(job.id),
                "kind": job.kind,
                "code": code,
                "attempt": job.attempts,
                "retryable": retryable,
            },
        )
        async with maker() as session:
            j = await session.get(Job, job.id)
            assert j is not None
            will_retry = await queue.mark_failed(session, j, code=code, message=message, retryable=retryable)
            await session.commit()
            hook = FAILURE_HOOKS.get(job.kind)
            if hook is not None:
                await hook(session, dict(job.payload), code, message, not will_retry)
        return
    async with maker() as session:
        j = await session.get(Job, job.id)
        assert j is not None
        await queue.mark_succeeded(session, j)
        await session.commit()
    log.info("job_succeeded", extra={"job_id": str(job.id), "kind": job.kind})


async def run_once(worker: str | None = None, kinds: list[str] | None = None) -> bool:
    """Claim and run a single job. Returns False when nothing was available."""
    async with get_sessionmaker()() as session:
        job = await queue.claim(session, worker or worker_id(), kinds)
    if job is None:
        return False
    await run_job(job)
    return True


async def drain(max_jobs: int = 100) -> int:
    """Run jobs until the queue is empty (used by tests and the in-process mode)."""
    count = 0
    wid = worker_id()
    while count < max_jobs and await run_once(wid):
        count += 1
    return count


async def run_forever(stop: asyncio.Event | None = None) -> None:
    settings = get_settings()
    wid = worker_id()
    concurrency = max(1, settings.ai_concurrency)
    log.info("worker_started", extra={"worker": wid, "concurrency": concurrency})

    async def loop() -> None:
        while stop is None or not stop.is_set():
            try:
                worked = await run_once(wid)
            except Exception:
                log.exception("worker_loop_error")
                worked = False
            if not worked:
                await asyncio.sleep(settings.job_poll_interval_seconds)

    await asyncio.gather(*(loop() for _ in range(concurrency)))
