"""Tests for the app shell: health, readiness, root JWKS, error shapes."""

from __future__ import annotations

from waggi_auth.config import settings
from waggi_auth.main import create_app


async def test_health(client) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "auth"}


async def test_ready_probes_database(client) -> None:
    r = await client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "service": "auth"}


async def test_jwks_mounted_at_root(client) -> None:
    """The trust root lives at /.well-known/jwks.json (NOT under /api/v1)."""
    r = await client.get("/.well-known/jwks.json")
    assert r.status_code == 200
    keys = r.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["kid"] == settings.jwt_key_id


async def test_api_errors_are_problem_json(client) -> None:
    r = await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["title"] == "Unauthorized"
    assert body["status"] == 401
    assert body["detail"]
    assert body["instance"] == "/api/v1/auth/login"


async def test_unexpected_errors_are_generic_500(client, monkeypatch) -> None:
    """The catch-all handler must not leak internals."""

    class BoomEngine:
        def connect(self):
            raise RuntimeError("secret-internal-detail")

    import waggi_auth.main as main_module

    monkeypatch.setattr(main_module, "_engine", BoomEngine())
    # Starlette's ServerErrorMiddleware re-raises after sending the 500, so
    # the test transport must not bubble app exceptions.
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=client._transport.app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        r = await c.get("/ready")
    assert r.status_code == 500
    body = r.json()
    assert body["title"] == "Internal Server Error"
    assert body["type"] == "https://errors.waggi.local/unexpected_error"
    assert "secret-internal-detail" not in body["detail"]
    assert "unexpected error" in body["detail"].lower()


async def test_429_is_problem_json_with_retry_after(client) -> None:
    for _ in range(10):
        await client.post("/api/v1/auth/login", json={"email": "rl@example.com", "password": "wrong12345"})
    r = await client.post("/api/v1/auth/login", json={"email": "rl@example.com", "password": "wrong12345"})
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["retry_after"] >= 1
    assert r.json()["type"] == "https://errors.waggi.local/rate_limited"


async def test_lifespan_closes_redis_connections() -> None:
    """App startup/shutdown runs the lifespan (closes shared redis clients)."""
    app = create_app()
    async with app.router.lifespan_context(app):
        pass  # startup + shutdown both ran without error


# --- CORS (the SPA calls the API cross-origin on the api host) ----------------


async def test_cors_allows_configured_origin(client) -> None:
    r = await client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_cors_ignores_unknown_origins(client) -> None:
    r = await client.get("/health", headers={"Origin": "http://evil.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


async def test_cors_preflight_authorization_header(client) -> None:
    """Preflight for the SPA's Bearer calls must pass (CORS_ORIGINS allowlist)."""
    r = await client.options(
        "/api/v1/auth/refresh",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    allowed = r.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in allowed
    assert "content-type" in allowed
    # Bearer-only auth (no cookies anywhere) → no allow-credentials.
    assert r.headers.get("access-control-allow-credentials", "false").lower() != "true"
