from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db.session import Database
from app.errors import install_error_handlers
from app.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.routers import (
    applications,
    auth,
    entities,
    health,
    jobs,
    memos,
    operations,
    opportunities,
    orgs,
    search,
    theses,
)
from app.services.object_store import ObjectStore
from app.services.seeding import seed_reference_data


def configure_logging(settings: Settings) -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(__import__("logging"), settings.log_level.upper(), 20)
        ),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(resolved)
        object_store = ObjectStore(resolved)
        app.state.settings = resolved
        app.state.database = database
        app.state.object_store = object_store
        if resolved.auto_create_schema:
            await database.create_schema()
        async with database.session_factory() as session:
            await seed_reference_data(session, resolved)
        yield
        await database.dispose()

    app = FastAPI(
        title="VC Brain API",
        summary="Evidence-backed venture sourcing, screening, diligence, and decisions",
        version=resolved.app_version,
        openapi_url="/api/v1/openapi.json",
        docs_url=None if resolved.env == "prod" else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "If-Match",
            "Last-Event-ID",
            "X-CSRF-Token",
            "X-Org-Id",
            "X-Request-Id",
        ],
        expose_headers=["X-Request-Id", "Idempotent-Replay", "X-RateLimit-Remaining"],
    )
    install_error_handlers(app)
    app.include_router(health.router)
    for router in (
        auth.router,
        orgs.router,
        theses.router,
        applications.router,
        opportunities.router,
        entities.router,
        search.router,
        memos.router,
        jobs.router,
        operations.router,
    ):
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
