from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import change_orders, documents, identity, projects, requests, scope, system
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.request_context import set_request_id
from app.db.session import dispose_engine

API_PREFIX = "/api/v1"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    stop = asyncio.Event()
    worker_task = None
    if settings.run_worker_in_process:
        from app.jobs.runner import run_forever

        worker_task = asyncio.create_task(run_forever(stop))
    yield
    stop.set()
    if worker_task is not None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(worker_task, timeout=10)
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    app = FastAPI(
        title="TermRail API",
        version="0.1.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Content-Hash", "Content-Disposition"],
    )

    @app.middleware("http")
    async def request_id_mw(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        incoming = request.headers.get("x-request-id")
        rid = set_request_id(incoming if incoming and len(incoming) <= 64 else None)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    install_error_handlers(app)
    for module in (system, identity, projects, documents, scope, requests, change_orders):
        app.include_router(module.router, prefix=API_PREFIX)
    return app


app = create_app()
