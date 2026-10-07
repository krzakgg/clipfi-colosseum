from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import DeclarativeBase

from app.settings import settings


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url=None):
        self.url = url or settings.database_url_normalized
        kw = {}
        if self.url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
            if self.url.endswith("://") or ":memory:" in self.url:
                kw["poolclass"] = StaticPool
        self.engine = create_async_engine(self.url, **kw)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def create_all(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    def session(self):
        return self.session_factory()

    async def dispose(self):
        await self.engine.dispose()
