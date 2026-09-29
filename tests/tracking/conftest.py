import os
import time
from datetime import UTC, datetime
from pathlib import Path

import fakeredis.aioredis
import pytest
import redis as sync_redis

from tracking.config import Settings
from tracking.links import Link

PROJECT_DIR = Path(__file__).resolve().parents[2] / "tracking-service"
SERVICE_TOKEN = "service-token-for-tests-0123456789abcdef"
FINGERPRINT_SECRET = "fingerprint-secret-for-tests-0123456789"


def start_container(image: str, port: int, env: dict[str, str] | None = None):
    from testcontainers.core.container import DockerContainer

    container = DockerContainer(image).with_exposed_ports(port)
    for key, value in (env or {}).items():
        container = container.with_env(key, value)
    try:
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker is not available for integration tests: {exc}")
    return container, container.get_container_host_ip(), int(container.get_exposed_port(port))


def wait_until(ready, what: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready():
            return
        time.sleep(0.25)
    raise TimeoutError(f"{what} did not become ready within {timeout:.0f}s")


@pytest.fixture(scope="session")
def postgres_url():
    if url := os.environ.get("TRACKING_TEST_DATABASE_URL"):
        yield url
        return
    container, host, port = start_container("postgres:16-alpine", 5432, {"POSTGRES_PASSWORD": "postgres"})
    try:
        wait_until(
            lambda: container.exec(["pg_isready", "-h", "127.0.0.1", "-U", "postgres"]).exit_code == 0,
            "PostgreSQL",
        )
        yield f"postgresql://postgres:postgres@{host}:{port}/postgres"
    finally:
        container.stop()


@pytest.fixture(scope="session")
def redis_url():
    if url := os.environ.get("TRACKING_TEST_REDIS_URL"):
        yield url
        return
    container, host, port = start_container("redis:7-alpine", 6379)

    def pong() -> bool:
        try:
            return sync_redis.Redis(host=host, port=port).ping()
        except sync_redis.ConnectionError:
            return False

    try:
        wait_until(pong, "Redis")
        yield f"redis://{host}:{port}/0"
    finally:
        container.stop()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql://unused",
        redis_url="redis://unused",
        service_token=SERVICE_TOKEN,
        fingerprint_secret=FINGERPRINT_SECRET,
        rate_limit_per_minute=5,
        _env_file=None,
    )


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.aclose()


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 9, 21, 12, 34, 56, tzinfo=UTC)


def make_link(**overrides) -> Link:
    base = dict(
        id=7,
        code="abcDEF12",
        campaign_id="11111111-1111-1111-1111-111111111111",
        creator_id="22222222-2222-2222-2222-222222222222",
        target_url="https://store.example.com/app/123?utm_source=jestr",
        platform="youtube",
        active=True,
        starts_at=None,
        ends_at=None,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return Link(**base)
