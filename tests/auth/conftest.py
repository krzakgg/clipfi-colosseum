"""Shared fixtures for the auth-service test suite.

Runs against a REAL local Postgres (dedicated `waggi_auth_test` database, `auth`
schema recreated per session) — CITEXT / ARRAY / ENUM / FK semantics are part
of what these tests verify. Redis is faked with fakeredis (challenges, SSO
state, MFA single-use gates); rate limiting runs on `limits`' in-memory
storage so every test starts with clean counters.
"""

from __future__ import annotations

import hashlib
import os
import secrets as py_secrets
import tempfile
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from functools import lru_cache
from typing import Any

import pytest

# --- Environment bootstrap: MUST run before any waggi_* import ------------
# (pydantic-settings: real env vars beat .env files, so these win everywhere.)

_DB_PORT = os.environ.get("WAGGI_DB_PORT", "5432")
TEST_DATABASE_URL = os.environ.get(
    "WAGGI_TEST_DATABASE_URL",
    f"postgresql+asyncpg://waggi_auth:waggi_auth@localhost:{_DB_PORT}/waggi_auth_test",
)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "dev"
_TMPDIR = tempfile.mkdtemp(prefix="waggi-auth-tests-")
os.environ["JWT_PRIVATE_KEY_PATH"] = os.path.join(_TMPDIR, "auth_private.pem")
os.environ["JWT_PUBLIC_KEY_PATH"] = os.path.join(_TMPDIR, "auth_public.pem")

from cryptography.fernet import Fernet  # noqa: E402

os.environ["TOTP_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["MFA_TOKEN_SECRET"] = "test-mfa-secret-" + py_secrets.token_hex(16)
# Pin the CORS allowlist — the app-shell CORS tests assert against it (a root
# .env would otherwise leak whatever the developer configured).
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
# Google configured so `get_provider_client("google")` works in tests; state
# per test via monkeypatched settings attributes.
os.environ["GOOGLE_CLIENT_ID"] = "test-google-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-google-client-secret"

# --- App imports (after env) ----------------------------------------------

import fakeredis.aioredis  # noqa: E402
import pyotp  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from limits.aio.storage import MemoryStorage  # noqa: E402
from limits.aio.strategies import FixedWindowRateLimiter  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from waggi_auth import rate_limit  # noqa: E402
from waggi_auth.dependencies import _engine  # noqa: E402
from waggi_auth.main import create_app  # noqa: E402
from waggi_auth.models import AccountType, Base, User  # noqa: E402
from waggi_auth.security.signing import create_access_token  # noqa: E402
from waggi_auth.security.totp import encrypt_totp_secret  # noqa: E402
from waggi_auth.stores import challenges, mfa, sso_states  # noqa: E402
from waggi_shared.passwords import hash_password  # noqa: E402

PASSWORD = "Password123!"


@lru_cache(maxsize=8)
def _cached_hash(password: str) -> str:
    """Share argon2 hashes for repeated test passwords (hashing is ~100ms)."""
    return hash_password(password)


# --- Database (session-scoped) --------------------------------------------


@pytest.fixture(scope="session", autouse=True)
async def _test_database() -> AsyncGenerator[None]:
    url = make_url(TEST_DATABASE_URL)
    assert url.database and url.database != "waggi_auth", "refusing to run against the dev database"

    # Create the test database if needed (AUTOCOMMIT; CREATE DATABASE cannot
    # run inside a transaction).
    server_engine = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with server_engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    except Exception as exc:
        if "already exists" not in str(exc).lower():
            pytest.exit(
                f"Cannot reach Postgres for auth tests ({exc}).\n"
                "Start it (docker compose up -d postgres in auth-service, or point "
                "WAGGI_TEST_DATABASE_URL at a local Postgres)",
                returncode=1,
            )
    finally:
        await server_engine.dispose()

    # Fresh `auth` schema + all tables. DDL runs with search_path auth,public
    # (same as alembic env.py): citext installs into public, unqualified table
    # names land in auth.
    ddl_engine = create_async_engine(TEST_DATABASE_URL, connect_args={"server_settings": {"search_path": "auth,public"}})
    async with ddl_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS auth CASCADE"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public"))
        await conn.execute(text("CREATE SCHEMA auth"))
        await conn.run_sync(Base.metadata.create_all)
    await ddl_engine.dispose()

    yield
    await _engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_users() -> AsyncGenerator[None]:
    """Empty all user tables between tests (FK cascades take the children)."""
    yield
    Session = async_sessionmaker(_engine, expire_on_commit=False)
    async with Session() as session:
        await session.execute(text("DELETE FROM auth.users"))
        await session.commit()


# --- Fakes (function-scoped, autouse) --------------------------------------


@pytest.fixture(autouse=True)
async def fake_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[Any]:
    """One shared fakeredis for the Redis-backed stores per test."""
    fake = fakeredis.aioredis.FakeRedis()

    def _factory(url: str) -> Any:
        return fake

    monkeypatch.setattr(challenges, "redis_client", _factory)
    monkeypatch.setattr(sso_states, "redis_client", _factory)
    monkeypatch.setattr(mfa, "redis_client", _factory)
    yield fake
    await fake.aclose()


@pytest.fixture(autouse=True)
def memory_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh in-memory rate-limit counters for every test."""
    monkeypatch.setattr(rate_limit, "_strategy", FixedWindowRateLimiter(MemoryStorage()))


# --- App client + DB helpers ------------------------------------------------


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession]:
    Session = async_sessionmaker(_engine, expire_on_commit=False)
    async with Session() as session:
        yield session


_SENTINEL_PASSWORD = object()


@pytest.fixture
def make_user(db: AsyncSession) -> Callable[..., Awaitable[User]]:
    """Create a user row. Stashes `user.plain_totp_secret` for TOTP tests."""

    async def _make(
        *,
        email: str = "user@example.com",
        password: str | None = PASSWORD,
        full_name: str = "Test User",
        account_type: AccountType = AccountType.company,
        username: str | None = None,
        is_active: bool = True,
        totp: bool = False,
        backup_codes: list[str] | None = None,
        must_set_password: bool = False,
    ) -> User:
        user = User(
            email=email,
            full_name=full_name,
            account_type=account_type,
            username=username,
            is_active=is_active,
            password_hash=(_cached_hash(password) if password is not _SENTINEL_PASSWORD else None)
            if password is not None
            else None,
            must_set_password=must_set_password,
            totp_enabled=totp,
            totp_secret=None,
            totp_backup_codes_hashed=[],
        )
        if totp:
            secret = pyotp.random_base32()
            user.totp_secret = encrypt_totp_secret(secret)
            user.plain_totp_secret = secret  # type: ignore[attr-defined]
        if backup_codes:
            user.totp_backup_codes_hashed = [hashlib.sha256(code.encode()).hexdigest() for code in backup_codes]
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    return _make


@pytest.fixture
def auth_headers() -> Callable[[User], dict[str, str]]:
    """Bearer headers with a directly-minted access token (no login round-trip)."""

    def _headers(user: User) -> dict[str, str]:
        token, _ = create_access_token(
            user_id=user.id, email=user.email, full_name=user.full_name, account_type=user.account_type.value
        )
        return {"Authorization": f"Bearer {token}"}

    return _headers


@pytest.fixture
def totp_code() -> Callable[..., str]:
    """A code for the user's stashed secret. `offset_steps=-1` returns the
    previous step's code — still valid via valid_window=1 but stable for 30s,
    which makes replay/retry tests deterministic across step boundaries."""

    def _code(user: User, *, offset_steps: int = 0) -> str:
        totp = pyotp.TOTP(user.plain_totp_secret)  # type: ignore[attr-defined]
        step = int(time.time()) // 30 + offset_steps
        return totp.at(step * 30)

    return _code
