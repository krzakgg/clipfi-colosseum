"""Async SQLAlchemy database engine + session helpers.

Each service owns exactly one DB schema. `engine_for(schema)` returns an engine
with a `connect_args` server-side `search_path` set to that schema so models
never need to hard-code it.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def engine_for(database_url: str, schema: str, *, echo: bool = False) -> AsyncEngine:
    """Create an async engine whose connections use `schema` as search_path.

    Connections set `search_path` to the service's own schema on checkout so
    services only ever see their own tables, even in a shared database.
    """
    return create_async_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {"search_path": schema},
        },
    )


def sessionmaker_for(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency yielding an async session scoped to a request.

    Usage in a service::

        from waggi_shared.database import engine_for, sessionmaker_for, get_session
        engine = engine_for(settings.database_url, "booking")
        Session = sessionmaker_for(engine)

        async def get_db() -> AsyncGenerator[AsyncSession, None]:
            async for s in get_session(Session):
                yield s
    """
    async with sessionmaker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
