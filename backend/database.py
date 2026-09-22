from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# Zastąp odpowiednimi poświadczeniami bazy danych z docker-compose
DATABASE_URL = "postgresql+asyncpg://postgres:postgres_password@postgres_db:5432/postgres"

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session