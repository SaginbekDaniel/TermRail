from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import schemas as S
from app.api.deps import DB, CurrentUser, require_workspace
from app.core.errors import NotFound
from app.db.models import Job
from app.llm.factory import describe_ai

router = APIRouter()


@router.get("/health/live", include_in_schema=False)
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", include_in_schema=False)
async def ready(db: DB) -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        await db.execute(text("select 1"))
        version = (await db.execute(text("select version_num from alembic_version"))).scalar_one_or_none()
        checks["database"] = "ok"
        checks["migrations"] = "ok" if version else "missing"
    except Exception:  # noqa: BLE001
        checks["database"] = "unavailable"
    checks["ai"] = "configured" if describe_ai()["configured"] else "not_configured"
    ok = checks.get("database") == "ok" and checks.get("migrations") == "ok"
    return JSONResponse(
        status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded", "checks": checks}
    )


@router.get("/system/ai", response_model=S.AIStatusOut)
async def ai_status(user: CurrentUser) -> S.AIStatusOut:
    info = describe_ai()
    return S.AIStatusOut(
        provider=str(info["provider"]),
        model=info["model"],  # type: ignore[arg-type]
        configured=bool(info["configured"]),
        error=info["error"],  # type: ignore[arg-type]
        data_notice=(
            "Contract fragments and client message text are sent to this AI provider only when you run "
            "scope extraction or request analysis. No other data is sent."
        ),
    )


@router.get("/jobs/{job_id}", response_model=S.JobOut)
async def get_job(job_id: uuid.UUID, user: CurrentUser, db: DB) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise NotFound("Job not found")
    try:
        await require_workspace(db, user, job.workspace_id)
    except NotFound as exc:
        raise NotFound("Job not found") from exc
    return job
