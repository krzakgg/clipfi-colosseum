from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from redis.asyncio import Redis

from tracking.api import health, internal, public
from tracking.auth import InternalGate
from tracking.clicks import ClickCounter
from tracking.config import Settings, configure_logging
from tracking.deps import Deps
from tracking.hardening import RequestGuard
from tracking.links import CachedLinkStore, PostgresLinkStore
from tracking.stats import PostgresStats


async def build_deps(settings: Settings) -> Deps:
    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=settings.count_timeout,
        socket_connect_timeout=settings.count_timeout,
    )
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10, command_timeout=10)
    links = CachedLinkStore(
        PostgresLinkStore(pool),
        redis,
        positive_ttl=settings.link_cache_ttl,
        negative_ttl=settings.negative_cache_ttl,
        miss_limit_per_minute=settings.miss_limit_per_minute,
    )
    counter = ClickCounter(
        redis,
        secret=settings.fingerprint_secret.get_secret_value().encode(),
        rate_limit_per_minute=settings.rate_limit_per_minute,
        max_unique_per_ip_per_day=settings.max_unique_per_ip_per_day,
        bucket_ttl=settings.bucket_ttl,
        stream_maxlen=settings.stream_maxlen,
    )

    async def check_redis() -> None:
        await redis.ping()

    async def check_database() -> None:
        await pool.fetchval("SELECT 1")

    async def close() -> None:
        await pool.close()
        await redis.aclose()

    return Deps(
        links=links,
        counter=counter,
        stats=PostgresStats(pool),
        check_redis=check_redis,
        check_database=check_database,
        close=close,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level)
        owned = getattr(app.state, "deps", None) is None
        if owned:
            app.state.deps = await build_deps(settings)
        try:
            yield
        finally:
            if owned:
                await app.state.deps.close()

    app = FastAPI(
        title="Tracking Service",
        lifespan=lifespan,
        docs_url="/docs" if settings.expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.expose_docs else None,
        redirect_slashes=False,  # the slash redirect is built from the Host header
    )
    app.state.settings = settings
    app.state.service_token = settings.service_token.get_secret_value().encode()

    app.include_router(health.router)
    if settings.api_role in ("all", "internal"):
        app.include_router(internal.router)
        app.add_middleware(
            InternalGate, token=app.state.service_token, max_body=settings.max_internal_body_bytes
        )
    if settings.api_role in ("all", "public"):
        app.include_router(public.router, prefix=settings.redirect_prefix)
    # added last so it runs first
    app.add_middleware(RequestGuard, max_header_bytes=settings.max_header_bytes)
    return app


app = create_app
