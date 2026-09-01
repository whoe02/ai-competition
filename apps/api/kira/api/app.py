"""Application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from kira.agent.graph import close_checkpointer, setup_checkpointer
from kira.api.routers import (
    auth,
    briefings,
    butler,
    capture,
    categories,
    dashboard,
    day_plan,
    foresight,
    hindsight,
    goals,
    transactions,
)
from kira.config import get_settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create LangGraph's checkpoint tables, or run without durable pauses.

    They are LangGraph's schema, not ours, so they are created by an idempotent
    setup() here rather than by an Alembic migration. Against SQLite — the test
    database — there is no Postgres saver, and the in-memory one is used.
    """
    settings = get_settings()
    saver = None
    if settings.database_url.startswith("postgresql"):
        try:
            saver = await setup_checkpointer(settings.checkpointer_dsn)
        except Exception as exc:  # a demo without approvals beats no demo
            log.warning("Butler checkpointer unavailable, using in-memory: %s", exc)
    try:
        yield
    finally:
        if saver is not None:
            await close_checkpointer()


class SpaStaticFiles(StaticFiles):
    """Serve the built bundle, falling back to index.html for client routes.

    Mounted last, so registered /v1 routes resolve first. An unknown /v1 path
    still returns the API's JSON 404; other missing client routes return the
    app shell so a deep link does not break.
    """

    async def get_response(self, path: str, scope: Scope):
        if path == "v1" or path.startswith("v1/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def create_app(*, static_dir: Path | None = None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        lifespan=lifespan,
        title="Kira API",
        version="0.1.0",
        docs_url="/v1/docs",
        openapi_url="/v1/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/v1/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(transactions.router)
    app.include_router(butler.router)
    app.include_router(capture.router)
    app.include_router(categories.router)
    app.include_router(foresight.router)
    app.include_router(hindsight.router)
    app.include_router(briefings.router)
    app.include_router(day_plan.router)
    app.include_router(goals.router)

    # In the shipped image the built bundle sits beside the package. In
    # development it is absent and Vite serves the UI instead, so this is
    # conditional rather than required.
    static_dir = static_dir or Path(__file__).resolve().parents[1] / "static"
    if static_dir.is_dir():
        app.mount("/", SpaStaticFiles(directory=static_dir, html=True), name="spa")
    return app


app = create_app()
