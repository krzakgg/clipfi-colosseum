import os
import time

import pytest
import redis as sync_redis

SERVICE_TOKEN = "service-token-for-tests-0123456789abcdef"
FINGERPRINT_SECRET = "fingerprint-secret-for-tests-0123456789"
REDIRECT_BASE = "http://localhost:8080/r"
WAGGI_DATABASE = "waggi_it"
TRACKING_DATABASE = "tracking_it"

_containers = []


def start_container(image: str, port: int, env: dict[str, str] | None = None):
    from testcontainers.core.container import DockerContainer

    container = DockerContainer(image).with_exposed_ports(port)
    for key, value in (env or {}).items():
        container = container.with_env(key, value)
    container.start()
    _containers.append(container)
    return container, container.get_container_host_ip(), int(container.get_exposed_port(port))


def wait_until(ready, what: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready():
            return
        time.sleep(0.25)
    raise TimeoutError(f"{what} did not become ready within {timeout:.0f}s")


def postgres_url() -> str:
    return os.environ.get("WAGGI_TEST_POSTGRES_URL", "").rstrip("/")


def _start_postgres() -> str:
    try:
        container, host, port = start_container("postgres:16-alpine", 5432, {"POSTGRES_PASSWORD": "postgres"})
    except Exception as exc:
        print(f"Docker is not available, end-to-end tests will be skipped: {exc}")
        return ""
    wait_until(
        lambda: container.exec(["pg_isready", "-h", "127.0.0.1", "-U", "postgres"]).exit_code == 0, "PostgreSQL"
    )
    return f"postgresql://postgres:postgres@{host}:{port}"


def pytest_configure(config):
    if not postgres_url():
        os.environ["WAGGI_TEST_POSTGRES_URL"] = _start_postgres()
    base = postgres_url()
    os.environ["DATABASE_URL"] = (
        f"{base.replace('postgresql://', 'postgresql+asyncpg://', 1)}/{WAGGI_DATABASE}"
        if base
        else "postgresql+asyncpg://unused@127.0.0.1:1/unused"
    )
    os.environ["TRACKING_SERVICE_TOKEN"] = SERVICE_TOKEN
    os.environ["TRACKING_REDIRECT_BASE"] = REDIRECT_BASE


def pytest_unconfigure(config):
    while _containers:
        _containers.pop().stop()


@pytest.fixture(scope="session")
def redis_url():
    if url := os.environ.get("WAGGI_TEST_REDIS_URL"):
        return url
    try:
        _, host, port = start_container("redis:7-alpine", 6379)
    except Exception as exc:
        pytest.skip(f"Docker is not available for end-to-end tests: {exc}")

    def pong() -> bool:
        try:
            return sync_redis.Redis(host=host, port=port).ping()
        except sync_redis.ConnectionError:
            return False

    wait_until(pong, "Redis")
    return f"redis://{host}:{port}/0"
