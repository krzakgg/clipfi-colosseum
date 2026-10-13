"""Smoke test for the fixture wiring (kept: cheap canary for infra breakage)."""

from __future__ import annotations

from waggi_auth.models import User


async def test_smoke(client, make_user) -> None:
    user: User = await make_user()
    assert user.id

    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "auth"}

    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401
