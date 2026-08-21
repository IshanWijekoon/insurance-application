"""FastAPI application factory."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import (
    AppError,
    app_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.core.logging import configure_logging, get_logger, request_id_var

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    configure_logging()

    problems = settings.validate_for_environment()
    if problems:
        for problem in problems:
            log.error("config.invalid", problem=problem)
        raise RuntimeError(
            "Refusing to start with an unsafe configuration:\n  - " + "\n  - ".join(problems)
        )

    if not settings.is_production and "mock" in (settings.ai_provider, settings.vision_provider):
        log.warning(
            "ai.mock_provider_active",
            detail="Assessments will be generated from local fixtures, not a real model.",
        )

    try:
        from app.media.storage import get_storage

        get_storage().ensure_bucket()
    except Exception as exc:  # noqa: BLE001 — the API still serves non-image traffic
        log.error("storage.unavailable_at_startup", error=str(exc))

    relay_task = None
    try:
        import redis as redis_sync

        redis_sync.from_url(settings.redis_url, socket_connect_timeout=0.4).ping()
        from app.notifications.hub import redis_relay

        relay_task = asyncio.create_task(redis_relay())
        log.info("realtime.redis_connected")
    except Exception:
        log.warning("realtime.redis_skipped", detail="Live WebSocket updates disabled; the UI will poll.")

    log.info("app.started", env=settings.app_env, ai_provider=settings.ai_provider)
    try:
        yield
    finally:
        if relay_task is not None:
            relay_task.cancel()
        log.info("app.stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "AI-assisted motor insurance claim assessment. Every AI output in this API is a "
            "preliminary recommendation subject to authorised human review."
        ),
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/health", include_in_schema=False)
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "environment": settings.app_env})

    @app.get("/ready", include_in_schema=False)
    async def ready() -> JSONResponse:
        from sqlalchemy import text

        from app.db.session import engine

        checks: dict[str, str] = {}
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["database"] = f"error: {type(exc).__name__}"

        healthy = all(v == "ok" for v in checks.values())
        return JSONResponse({"ready": healthy, "checks": checks}, status_code=200 if healthy else 503)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
