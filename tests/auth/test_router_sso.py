"""Endpoint tests for the SSO router: authorize, callback, complete, identities."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import redis.asyncio as aioredis
import respx
from httpx import Response
from sqlalchemy import select
from tests.auth.sso_sim import (
    GOOGLE_AUTH_ENDPOINT,
    GOOGLE_JWKS_ENDPOINT,
    GOOGLE_TOKEN_ENDPOINT,
    FakeProvider,
)

from waggi_auth.config import settings
from waggi_auth.models import UserSsoLink
from waggi_auth.providers import google as google_provider
from waggi_auth.stores import sso_states

FRONTEND = settings.frontend_url.rstrip("/")
CALLBACK_PATH = "/api/v1/auth/sso/google/callback"


@pytest.fixture(autouse=True)
def _reset_google_jwks_cache():
    google_provider._JWKS._keys = {}
    google_provider._JWKS._fetched_at = 0.0
    yield
    google_provider._JWKS._keys = {}
    google_provider._JWKS._fetched_at = 0.0


def _mock_provider(provider: FakeProvider, id_token: str) -> None:
    respx.post(GOOGLE_TOKEN_ENDPOINT).mock(return_value=Response(200, json={"id_token": id_token}))
    respx.get(GOOGLE_JWKS_ENDPOINT).mock(return_value=Response(200, json=provider.jwks_document()))


async def _store_state(*, provider: str = "google", nonce: str = "n-1", return_to: str | None = None):
    return await sso_states.store_state(
        sso_states.PendingSsoState(
            provider=provider,
            nonce=nonce,
            redirect_uri=f"{FRONTEND}{CALLBACK_PATH}",
            return_to=return_to or f"{FRONTEND}/login/sso/callback",
        )
    )


async def _store_link_state(user, *, provider: str = "google", nonce: str = "n-l"):
    return await sso_states.store_state(
        sso_states.PendingSsoState(
            provider=provider,
            nonce=nonce,
            redirect_uri=f"{FRONTEND}{CALLBACK_PATH}",
            return_to=f"{FRONTEND}/account",
            purpose="link",
            user_id=user.id,
        )
    )


# --- GET /providers ---------------------------------------------------------------


async def test_list_providers(client) -> None:
    r = await client.get("/api/v1/auth/sso/providers")
    assert r.status_code == 200
    providers = {p["provider"]: p["enabled"] for p in r.json()}
    assert providers == {"google": True, "apple": False}


# --- POST /{provider}/authorize -----------------------------------------------------


async def test_authorize_builds_consent_url(client) -> None:
    r = await client.post("/api/v1/auth/sso/google/authorize", json={})
    assert r.status_code == 200
    url = r.json()["authorize_url"]
    assert url.startswith(GOOGLE_AUTH_ENDPOINT)
    assert "response_type=code" in url
    assert settings.google_client_id in url
    assert f"redirect_uri={FRONTEND}{CALLBACK_PATH}".replace("/", "%2F").replace(
        ":", "%3A"
    ) in url or f"redirect_uri={FRONTEND}{CALLBACK_PATH}" in url.replace("%2F", "/").replace("%3A", ":")
    assert "state=" in url and "nonce=" in url
    assert "scope=openid" in url


async def test_authorize_unknown_provider_404(client) -> None:
    r = await client.post("/api/v1/auth/sso/gitlab/authorize", json={})
    assert r.status_code == 404


async def test_authorize_redirect_uri_follows_api_public_url(client, monkeypatch) -> None:
    """Prod serves the API on its own origin: the OAuth redirect_uri follows
    API_PUBLIC_URL while return_to stays on the frontend origin."""
    monkeypatch.setattr(settings, "api_public_url", "https://api.waggi.local")
    r = await client.post("/api/v1/auth/sso/google/authorize", json={})
    assert r.status_code == 200
    url = r.json()["authorize_url"]
    expected = "https://api.waggi.local/api/v1/auth/sso/google/callback"
    assert f"redirect_uri={expected}".replace("/", "%2F").replace(":", "%3A") in url or f"redirect_uri={expected}" in url.replace(
        "%2F", "/"
    ).replace("%3A", ":")
    state = parse_qs(urlparse(url).query)["state"][0]
    entry = await sso_states.pop_state(state)
    assert entry is not None
    assert entry.redirect_uri == expected
    assert entry.return_to == f"{FRONTEND}/login/sso/callback"


async def test_authorize_unconfigured_provider_501(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_client_id", "")
    r = await client.post("/api/v1/auth/sso/google/authorize", json={})
    assert r.status_code == 501


async def test_authorize_trusted_origin_used_for_redirects(client) -> None:
    r = await client.post(
        "/api/v1/auth/sso/google/authorize",
        json={},
        headers={"Origin": "http://localhost:5173"},
    )
    url = r.json()["authorize_url"]
    assert "localhost%3A5173" in url  # trusted origin -> redirect_uri host


async def test_authorize_untrusted_origin_falls_back(client) -> None:
    r = await client.post("/api/v1/auth/sso/google/authorize", json={}, headers={"Origin": "http://evil.example"})
    url = r.json()["authorize_url"]
    assert "evil.example" not in url


@pytest.mark.parametrize(
    "redirect",
    ["/account", "/bookings?day=2026-08-19", None],
)
async def test_authorize_safe_redirect_passthrough(client, redirect) -> None:
    body = {"redirect": redirect} if redirect else {}
    r = await client.post("/api/v1/auth/sso/google/authorize", json=body)
    assert r.status_code == 200


@pytest.mark.parametrize("redirect", ["//evil.example", "/\\evil.example", "https://evil.example", "http://evil.example"])
async def test_authorize_unsafe_redirects_ignored(client, redirect) -> None:
    """The state's return_to must never be smuggled off-site."""
    r = await client.post("/api/v1/auth/sso/google/authorize", json={"redirect": redirect})
    assert r.status_code == 200
    # The stored state is what matters — verify via pop: redirect was ignored.
    url = r.json()["authorize_url"]
    state = url.split("state=")[1].split("&")[0]
    entry = await sso_states.pop_state(state)
    assert entry is not None
    assert "evil.example" not in entry.return_to or redirect.startswith("/")
    if redirect in ("//evil.example", "/\\evil.example", "https://evil.example", "http://evil.example"):
        assert "redirect=" not in entry.return_to


async def test_authorize_redis_down_503(client, monkeypatch) -> None:
    class Boom:
        async def set(self, *a, **k):
            raise aioredis.RedisError("down")

    monkeypatch.setattr(sso_states, "redis_client", lambda url: Boom())
    r = await client.post("/api/v1/auth/sso/google/authorize", json={})
    assert r.status_code == 503


@respx.mock
async def test_callback_state_pop_down_503(client, monkeypatch) -> None:
    class Boom:
        async def getdel(self, *a, **k):
            raise aioredis.RedisError("down")

    monkeypatch.setattr(sso_states, "redis_client", lambda url: Boom())
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": "s"})
    assert r.status_code == 503


@respx.mock
async def test_callback_store_login_down_503(client, make_user, monkeypatch, fake_redis) -> None:
    """Everything works until the final store_login — outage there -> 503."""
    user = await make_user()
    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="s-sub", nonce="n-x", email=user.email, email_verified=True),
    )
    state = await _store_state(nonce="n-x")

    class SetBoom:
        async def set(self, *a, **k):
            raise aioredis.RedisError("down")

        async def getdel(self, *a, **k):
            return await fake_redis.getdel(*a, **k)

    monkeypatch.setattr(sso_states, "redis_client", lambda url: SetBoom())
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert r.status_code == 503


async def test_complete_redis_down_503(client, monkeypatch) -> None:
    class Boom:
        async def getdel(self, *a, **k):
            raise aioredis.RedisError("down")

    monkeypatch.setattr(sso_states, "redis_client", lambda url: Boom())
    r = await client.post("/api/v1/auth/sso/complete", json={"handle": "x" * 32})
    assert r.status_code == 503


async def test_resolve_user_integrity_race_returns_winner(db, make_user) -> None:
    """Concurrent auto-link: our INSERT loses the unique-constraint race; the
    re-query finds the winner's link and returns the winner's user."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from waggi_auth.dependencies import _engine
    from waggi_auth.providers.base import VerifiedIdentity
    from waggi_auth.routers.sso import _resolve_user

    user = await make_user()
    winner = await make_user(email="winner@example.com")

    inserted = {"done": False}

    class RacingSession:
        def __init__(self, real):
            self._real = real

        def add(self, *a, **k):
            return self._real.add(*a, **k)

        async def commit(self):
            if not inserted["done"]:
                inserted["done"] = True
                # The "concurrent winner" inserts the same identity first...
                Session = async_sessionmaker(_engine, expire_on_commit=False)
                async with Session() as other:
                    other.add(UserSsoLink(user_id=winner.id, provider="google", provider_subject="race-sub"))
                    await other.commit()
                # ...and OUR commit then blows up on the unique constraint.
                await self._real.rollback()
                raise IntegrityError("duplicate key", None, Exception())
            return await self._real.commit()

        def __getattr__(self, name):
            return getattr(self._real, name)

    identity = VerifiedIdentity(subject="race-sub", email=user.email, email_verified=True, full_name=None)
    result = await _resolve_user(RacingSession(db), "google", identity)
    assert result is not None and result.id == winner.id


async def test_resolve_user_integrity_race_without_winner_returns_none(db, make_user) -> None:
    from sqlalchemy.exc import IntegrityError

    from waggi_auth.providers.base import VerifiedIdentity
    from waggi_auth.routers.sso import _resolve_user

    user = await make_user()
    raised = {"done": False}

    class RacingSession:
        def __init__(self, real):
            self._real = real

        def add(self, *a, **k):
            return self._real.add(*a, **k)

        async def commit(self):
            if not raised["done"]:
                raised["done"] = True
                await self._real.rollback()
                raise IntegrityError("duplicate key", None, Exception())
            return await self._real.commit()

        def __getattr__(self, name):
            return getattr(self._real, name)

    identity = VerifiedIdentity(subject="ghost-sub", email=user.email, email_verified=True, full_name=None)
    assert await _resolve_user(RacingSession(db), "google", identity) is None


# --- GET /{provider}/callback ---------------------------------------------------------


@respx.mock
async def test_callback_happy_path_auto_links_and_redirects(client, make_user) -> None:
    user = await make_user()
    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="google-sub-1", nonce="n-1", email=user.email, email_verified=True),
    )
    state = await _store_state(nonce="n-1")

    r = await client.get(f"{CALLBACK_PATH}", params={"code": "auth-code", "state": state})
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith(f"{FRONTEND}/login/sso/callback")
    assert "handle=" in location


@respx.mock
async def test_callback_full_flow_to_completion(client, make_user, db) -> None:
    user = await make_user()
    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="google-sub-9", nonce="n-9", email=user.email, email_verified=True),
    )
    state = await _store_state(nonce="n-9")
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert r.status_code == 302
    handle = r.headers["location"].split("handle=")[1]

    link = (await db.execute(select(UserSsoLink))).scalar_one()
    assert link.provider == "google"
    assert link.provider_subject == "google-sub-9"

    r = await client.post("/api/v1/auth/sso/complete", json={"handle": handle})
    assert r.status_code == 200
    assert "access_token" in r.json()


@respx.mock
async def test_callback_existing_link_skips_auto_link(client, make_user, db) -> None:
    user = await make_user()
    db.add(UserSsoLink(user_id=user.id, provider="google", provider_subject="known-sub"))
    await db.commit()

    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="known-sub", nonce="n-2", email="changed@example.com", email_verified=True),
    )
    state = await _store_state(nonce="n-2")
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert r.status_code == 302
    assert (await db.execute(select(UserSsoLink))).scalars().all().__len__() == 1


@respx.mock
async def test_callback_unverified_email_no_account(client, make_user) -> None:
    user = await make_user()
    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="new-sub", nonce="n-3", email=user.email, email_verified=False),
    )
    state = await _store_state(nonce="n-3")
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert r.status_code == 302
    assert "error=no_account" in r.headers["location"]


@respx.mock
async def test_callback_unknown_email_no_account(client) -> None:
    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="new-sub", nonce="n-4", email="ghost@example.com", email_verified=True),
    )
    state = await _store_state(nonce="n-4")
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert "error=no_account" in r.headers["location"]


@respx.mock
async def test_callback_inactive_user_no_account(client, make_user) -> None:
    user = await make_user(is_active=False)
    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="s", nonce="n-5", email=user.email, email_verified=True),
    )
    state = await _store_state(nonce="n-5")
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert "error=no_account" in r.headers["location"]


async def test_callback_missing_params_error_redirect(client) -> None:
    r = await client.get(CALLBACK_PATH)
    assert r.status_code == 302
    assert "error=invalid_request" in r.headers["location"]


async def test_callback_provider_error_param(client) -> None:
    r = await client.get(CALLBACK_PATH, params={"error": "access_denied"})
    assert "error=denied" in r.headers["location"]


async def test_callback_bad_state_error_redirect(client) -> None:
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": "bogus"})
    assert "error=state" in r.headers["location"]


async def test_callback_oversized_form_post_413(client) -> None:
    """An oversized form body is rejected before parsing (L4: unbounded
    request.form() would burn memory/CPU; Apple's real payload is ~1 KB)."""
    r = await client.post(CALLBACK_PATH, data={"code": "x" * 70_000, "state": "s"})
    assert r.status_code == 413


async def test_callback_form_post_within_limit_parses(client) -> None:
    """A normal-sized form post still reaches state validation (not 413)."""
    r = await client.post(CALLBACK_PATH, data={"code": "c", "state": "bogus"})
    assert r.status_code == 302
    assert "error=state" in r.headers["location"]


async def test_callback_state_provider_mismatch(client, monkeypatch) -> None:
    """A state issued for google must not be consumed by apple's callback."""
    monkeypatch.setattr(settings, "apple_client_id", "test-apple-id")
    monkeypatch.setattr(settings, "apple_team_id", "TEAM123456")
    monkeypatch.setattr(settings, "apple_key_id", "KEY123456")
    monkeypatch.setattr(settings, "apple_private_key_path", "/tmp/never-read.p8")

    state = await _store_state(provider="google", nonce="n-m")
    r = await client.get("/api/v1/auth/sso/apple/callback", params={"code": "c", "state": state})
    assert r.status_code == 302
    assert "error=state" in r.headers["location"]
    # The state was consumed — replaying it at the right provider also fails.
    r = await client.get("/api/v1/auth/sso/google/callback", params={"code": "c", "state": state})
    assert "error=state" in r.headers["location"]


async def test_callback_unknown_provider_config_error(client) -> None:
    r = await client.get("/api/v1/auth/sso/notaprovider/callback", params={"code": "c", "state": "s"})
    assert "error=config" in r.headers["location"]


@respx.mock
async def test_callback_exchange_rejected_denied(client) -> None:
    respx.post(GOOGLE_TOKEN_ENDPOINT).mock(return_value=Response(400, json={"error": "invalid_grant"}))
    state = await _store_state(nonce="n-7")
    r = await client.get(CALLBACK_PATH, params={"code": "bad", "state": state})
    assert "error=denied" in r.headers["location"]


@respx.mock
async def test_callback_apple_style_form_post(client, make_user, monkeypatch, tmp_path) -> None:
    """Apple POSTs form data — the callback must accept form bodies."""
    # A real (throwaway) EC key: the client-secret JWT is generated per exchange.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key_path = tmp_path / "apple.p8"
    key_path.write_bytes(
        ec.generate_private_key(ec.SECP256R1()).private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    monkeypatch.setattr(settings, "apple_client_id", "test-apple-id")
    monkeypatch.setattr(settings, "apple_team_id", "TEAM123456")
    monkeypatch.setattr(settings, "apple_key_id", "KEY123456")
    monkeypatch.setattr(settings, "apple_private_key_path", str(key_path))

    from waggi_auth.providers import apple as apple_provider

    apple_provider._JWKS._keys = {}
    apple_provider._JWKS._fetched_at = 0.0

    user = await make_user()
    provider = FakeProvider(kid="apple-kid")
    respx.post("https://appleid.apple.com/auth/token").mock(
        return_value=Response(
            200,
            json={
                "id_token": provider.id_token(
                    subject="apple-sub-1",
                    nonce="n-a",
                    issuer="https://appleid.apple.com",
                    audience="test-apple-id",
                    email=user.email,
                    email_verified="true",  # Apple sends the STRING "true"
                )
            },
        )
    )
    respx.get("https://appleid.apple.com/auth/keys").mock(return_value=Response(200, json=provider.jwks_document()))
    state = await sso_states.store_state(
        sso_states.PendingSsoState(
            provider="apple",
            nonce="n-a",
            redirect_uri=f"{FRONTEND}/api/v1/auth/sso/apple/callback",
            return_to=f"{FRONTEND}/login/sso/callback",
        )
    )
    r = await client.post("/api/v1/auth/sso/apple/callback", data={"code": "c", "state": state})
    assert r.status_code == 302, r.text
    assert "handle=" in r.headers["location"]


# --- POST /complete --------------------------------------------------------------------


async def test_complete_unknown_handle_401(client) -> None:
    r = await client.post("/api/v1/auth/sso/complete", json={"handle": "x" * 32})
    assert r.status_code == 401


async def test_complete_inactive_user_401(client, make_user, db) -> None:
    user = await make_user()
    handle = await sso_states.store_login(user.id)
    user.is_active = False
    await db.commit()
    r = await client.post("/api/v1/auth/sso/complete", json={"handle": handle})
    assert r.status_code == 401


async def test_complete_totp_user_gets_mfa_challenge(client, make_user) -> None:
    user = await make_user(totp=True)
    handle = await sso_states.store_login(user.id)
    r = await client.post("/api/v1/auth/sso/complete", json={"handle": handle})
    assert r.status_code == 200
    assert r.json()["mfa_required"] is True


async def test_complete_handle_single_use(client, make_user) -> None:
    user = await make_user()
    handle = await sso_states.store_login(user.id)
    assert (await client.post("/api/v1/auth/sso/complete", json={"handle": handle})).status_code == 200
    assert (await client.post("/api/v1/auth/sso/complete", json={"handle": handle})).status_code == 401


# --- identity management -----------------------------------------------------------------


async def test_list_identities(client, make_user, auth_headers, db) -> None:
    user = await make_user()
    db.add(UserSsoLink(user_id=user.id, provider="google", provider_subject="s1"))
    await db.commit()
    r = await client.get("/api/v1/auth/sso/identities", headers=auth_headers(user))
    assert r.status_code == 200
    assert len(r.json()) == 1


# --- POST /link/{provider}: begin the linking ceremony --------------------------------


async def test_begin_link_unauthenticated_401(client) -> None:
    r = await client.post("/api/v1/auth/sso/link/google")
    assert r.status_code == 401


async def test_begin_link_stores_link_state(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post("/api/v1/auth/sso/link/google", headers=auth_headers(user))
    assert r.status_code == 200
    url = r.json()["authorize_url"]
    assert url.startswith(GOOGLE_AUTH_ENDPOINT)
    assert "state=" in url and "nonce=" in url
    state = url.split("state=")[1].split("&")[0]
    entry = await sso_states.pop_state(state)
    assert entry is not None
    assert entry.purpose == "link"
    assert entry.user_id == user.id
    assert entry.return_to == f"{FRONTEND}/account"
    assert entry.redirect_uri == f"{FRONTEND}{CALLBACK_PATH}"


async def test_begin_link_redirect_uri_follows_api_public_url(client, make_user, auth_headers, monkeypatch) -> None:
    """Prod serves the API on its own origin: the link flow's redirect_uri
    follows API_PUBLIC_URL too, while return_to stays on the frontend origin."""
    monkeypatch.setattr(settings, "api_public_url", "https://api.waggi.local")
    user = await make_user()
    r = await client.post("/api/v1/auth/sso/link/google", headers=auth_headers(user))
    assert r.status_code == 200
    url = r.json()["authorize_url"]
    expected = "https://api.waggi.local/api/v1/auth/sso/google/callback"
    assert f"redirect_uri={expected}".replace("/", "%2F").replace(":", "%3A") in url or (
        f"redirect_uri={expected}" in url.replace("%2F", "/").replace("%3A", ":")
    )
    state = url.split("state=")[1].split("&")[0]
    entry = await sso_states.pop_state(state)
    assert entry is not None
    assert entry.redirect_uri == expected
    assert entry.return_to == f"{FRONTEND}/account"


async def test_begin_link_unknown_provider_404(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post("/api/v1/auth/sso/link/gitlab", headers=auth_headers(user))
    assert r.status_code == 404


async def test_begin_link_unconfigured_provider_501(client, make_user, auth_headers, monkeypatch) -> None:
    user = await make_user()
    monkeypatch.setattr(settings, "google_client_id", "")
    r = await client.post("/api/v1/auth/sso/link/google", headers=auth_headers(user))
    assert r.status_code == 501


async def test_begin_link_redis_down_503(client, make_user, auth_headers, monkeypatch) -> None:
    user = await make_user()

    class Boom:
        async def set(self, *a, **k):
            raise aioredis.RedisError("down")

    monkeypatch.setattr(sso_states, "redis_client", lambda url: Boom())
    r = await client.post("/api/v1/auth/sso/link/google", headers=auth_headers(user))
    assert r.status_code == 503


# --- callback: link purpose ------------------------------------------------------------


@respx.mock
async def test_link_callback_happy_path(client, make_user, db) -> None:
    user = await make_user()
    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="link-sub-1", nonce="n-l", email=user.email, email_verified=True),
    )
    state = await _store_link_state(user)
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert r.status_code == 302
    assert r.headers["location"].startswith(f"{FRONTEND}/account")
    assert "sso_link=google" in r.headers["location"]
    link = (await db.execute(select(UserSsoLink))).scalar_one()
    assert link.user_id == user.id
    assert link.provider == "google"
    assert link.provider_subject == "link-sub-1"


@respx.mock
async def test_link_callback_email_match_is_case_insensitive(client, make_user, db) -> None:
    user = await make_user(email="Mixed@Example.com")
    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="link-sub-c", nonce="n-l", email="mixed@example.com", email_verified=True),
    )
    state = await _store_link_state(user)
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert "sso_link=google" in r.headers["location"]
    assert (await db.execute(select(UserSsoLink))).scalars().all().__len__() == 1


@respx.mock
async def test_link_callback_email_mismatch(client, make_user, db) -> None:
    """THE core rule: a verified provider email that does not equal the account
    email must NOT be linked (cross-account binding impossible)."""
    user = await make_user()
    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="link-sub-2", nonce="n-l", email="other@example.com", email_verified=True),
    )
    state = await _store_link_state(user)
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert r.status_code == 302
    assert "sso_link_error=email_mismatch" in r.headers["location"]
    assert (await db.execute(select(UserSsoLink))).scalars().all() == []


@respx.mock
async def test_link_callback_email_unverified(client, make_user, db) -> None:
    user = await make_user()
    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="link-sub-3", nonce="n-l", email=user.email, email_verified=False),
    )
    state = await _store_link_state(user)
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert "sso_link_error=email_unverified" in r.headers["location"]
    assert (await db.execute(select(UserSsoLink))).scalars().all() == []


@respx.mock
async def test_link_callback_email_missing(client, make_user, db) -> None:
    user = await make_user()
    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="link-sub-4", nonce="n-l", include_email=False),
    )
    state = await _store_link_state(user)
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert "sso_link_error=email_unverified" in r.headers["location"]
    assert (await db.execute(select(UserSsoLink))).scalars().all() == []


@respx.mock
async def test_link_callback_already_linked_to_other_user(client, make_user, db) -> None:
    user = await make_user()
    other = await make_user(email="other@example.com")
    db.add(UserSsoLink(user_id=other.id, provider="google", provider_subject="taken-sub"))
    await db.commit()

    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="taken-sub", nonce="n-l", email=user.email, email_verified=True),
    )
    state = await _store_link_state(user)
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert "sso_link_error=already_linked" in r.headers["location"]
    links = (await db.execute(select(UserSsoLink))).scalars().all()
    assert len(links) == 1 and links[0].user_id == other.id  # untouched


@respx.mock
async def test_link_callback_idempotent_same_user(client, make_user, db) -> None:
    user = await make_user()
    db.add(UserSsoLink(user_id=user.id, provider="google", provider_subject="same-sub"))
    await db.commit()

    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="same-sub", nonce="n-l", email=user.email, email_verified=True),
    )
    state = await _store_link_state(user)
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert "sso_link=google" in r.headers["location"]
    assert (await db.execute(select(UserSsoLink))).scalars().all().__len__() == 1


@respx.mock
async def test_link_callback_inactive_user(client, make_user) -> None:
    user = await make_user(is_active=False)
    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="link-sub-5", nonce="n-l", email=user.email, email_verified=True),
    )
    state = await _store_link_state(user)
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": state})
    assert "sso_link_error=no_account" in r.headers["location"]


@respx.mock
async def test_link_callback_state_without_user_id(client, make_user, fake_redis, monkeypatch) -> None:
    """A raw link state missing user_id (corruption) is rejected as `state`."""
    user = await make_user()
    provider = FakeProvider()
    _mock_provider(
        provider,
        provider.id_token(subject="link-sub-6", nonce="n-x", email=user.email, email_verified=True),
    )
    monkeypatch.setattr(sso_states, "redis_client", lambda url: fake_redis)
    await fake_redis.set(
        "waggi:sso-state:raw-link",
        '{"provider": "google", "nonce": "n-x", '
        f'"redirect_uri": "{FRONTEND}{CALLBACK_PATH}", '
        f'"return_to": "{FRONTEND}/account", "purpose": "link"}}',
    )
    r = await client.get(CALLBACK_PATH, params={"code": "c", "state": "raw-link"})
    assert r.status_code == 302
    assert "sso_link_error=state" in r.headers["location"]


# --- _finish_link races (concurrent insert of the same provider subject) --------------


async def test_finish_link_integrity_race_same_user(db, make_user) -> None:
    """Our INSERT loses the unique-constraint race to a concurrent ceremony
    for the SAME user; the re-query makes it an idempotent success."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from waggi_auth.dependencies import _engine
    from waggi_auth.providers.base import VerifiedIdentity
    from waggi_auth.routers.sso import _finish_link

    user = await make_user()
    raced = {"done": False}

    class RacingSession:
        def __init__(self, real):
            self._real = real

        def add(self, *a, **k):
            return self._real.add(*a, **k)

        async def commit(self):
            if not raced["done"]:
                raced["done"] = True
                Session = async_sessionmaker(_engine, expire_on_commit=False)
                async with Session() as other:
                    other.add(UserSsoLink(user_id=user.id, provider="google", provider_subject="race-sub"))
                    await other.commit()
                await self._real.rollback()
                raise IntegrityError("duplicate key", None, Exception())
            return await self._real.commit()

        def __getattr__(self, name):
            return getattr(self._real, name)

    identity = VerifiedIdentity(subject="race-sub", email=user.email, email_verified=True, full_name=None)
    entry = sso_states.PendingSsoState(
        provider="google",
        nonce="n",
        redirect_uri="http://x/cb",
        return_to=f"{FRONTEND}/account",
        purpose="link",
        user_id=user.id,
    )
    res = await _finish_link(RacingSession(db), entry, "google", identity)
    assert "sso_link=google" in res.headers["location"]


async def test_finish_link_integrity_race_other_user(db, make_user) -> None:
    """The race winner linked the subject to ANOTHER user: refuse (already_linked)."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from waggi_auth.dependencies import _engine
    from waggi_auth.providers.base import VerifiedIdentity
    from waggi_auth.routers.sso import _finish_link

    user = await make_user()
    other = await make_user(email="other@example.com")
    raced = {"done": False}

    class RacingSession:
        def __init__(self, real):
            self._real = real

        def add(self, *a, **k):
            return self._real.add(*a, **k)

        async def commit(self):
            if not raced["done"]:
                raced["done"] = True
                Session = async_sessionmaker(_engine, expire_on_commit=False)
                async with Session() as other_session:
                    other_session.add(UserSsoLink(user_id=other.id, provider="google", provider_subject="race-sub"))
                    await other_session.commit()
                await self._real.rollback()
                raise IntegrityError("duplicate key", None, Exception())
            return await self._real.commit()

        def __getattr__(self, name):
            return getattr(self._real, name)

    identity = VerifiedIdentity(subject="race-sub", email=user.email, email_verified=True, full_name=None)
    entry = sso_states.PendingSsoState(
        provider="google",
        nonce="n",
        redirect_uri="http://x/cb",
        return_to=f"{FRONTEND}/account",
        purpose="link",
        user_id=user.id,
    )
    res = await _finish_link(RacingSession(db), entry, "google", identity)
    assert "sso_link_error=already_linked" in res.headers["location"]


async def test_unlink_own_identity(client, make_user, auth_headers, db) -> None:
    user = await make_user()
    link = UserSsoLink(user_id=user.id, provider="google", provider_subject="s1")
    db.add(link)
    await db.commit()

    r = await client.delete(f"/api/v1/auth/sso/link/{link.id}", headers=auth_headers(user))
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "google"
    assert (await db.execute(select(UserSsoLink))).scalars().all() == []


async def test_unlink_foreign_identity_404(client, make_user, auth_headers, db) -> None:
    owner = await make_user()
    other = await make_user(email="other@example.com")
    link = UserSsoLink(user_id=owner.id, provider="google", provider_subject="s1")
    db.add(link)
    await db.commit()
    r = await client.delete(f"/api/v1/auth/sso/link/{link.id}", headers=auth_headers(other))
    assert r.status_code == 404
