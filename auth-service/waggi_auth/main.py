"""Auth service FastAPI application."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from waggi_auth.config import settings
from waggi_auth.dependencies import _engine
from waggi_auth.routers.jwks import router as jwks_router
from waggi_auth.routers.mfa import router as mfa_router
from waggi_auth.routers.passkeys import router as passkeys_router
from waggi_auth.routers.password import router as password_router
from waggi_auth.routers.profile import router as profile_router
from waggi_auth.routers.session import router as session_router
from waggi_auth.routers.sso import router as sso_router
from waggi_shared.access_log import install_health_probe_filter
from waggi_shared.errors import install_error_handlers
from waggi_shared.redis import aclose_all


def create_app() -> FastAPI:
    settings.validate_for_environment()

    # Docker healthchecks probe /health (deploy.sh also /ready) every 15s —
    # keep those probe requests out of the uvicorn access log (log spam).
    install_health_probe_filter()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        yield
        await aclose_all()

    app = FastAPI(
        title="Waggi Auth",
        description="Identity source of truth for Waggi.",
        version="1.0.0",
        lifespan=lifespan,
    )

    install_error_handlers(app)

    # The SPA is served on app.waggi.local and calls the API on
    # api.waggi.local — CORS with an explicit origin allowlist. No
    # credentials: auth is Bearer-header based (no cookies anywhere), so
    # browsers neither need nor get Access-Control-Allow-Credentials.
    # Added last → outermost middleware, so error responses carry the
    # CORS headers too (the SPA must be able to READ problem+json bodies).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(jwks_router)
    # /api/v1/auth routers split by concern; order keeps the historical
    # OpenAPI path order (session -> profile -> password -> mfa...).
    app.include_router(session_router)
    app.include_router(profile_router)
    app.include_router(password_router)
    app.include_router(mfa_router)
    app.include_router(passkeys_router)
    app.include_router(sso_router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "auth"}

    @app.get("/ready", tags=["meta"])
    async def ready() -> dict[str, str]:
        # Probe the DB connection (search_path = auth schema).
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready", "service": "auth"}

    return app


app = create_app()
