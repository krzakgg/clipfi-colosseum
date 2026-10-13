"""Tests for the OAuth provider clients and the provider registry."""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from httpx import Response
from tests.auth.sso_sim import (
    GOOGLE_ISSUER,
    GOOGLE_JWKS_ENDPOINT,
    GOOGLE_TOKEN_ENDPOINT,
    FakeProvider,
)

from waggi_auth.config import settings
from waggi_auth.providers import get_provider_client, provider_status
from waggi_auth.providers import google as google_module
from waggi_auth.providers.apple import AppleClient
from waggi_auth.providers.base import _JWKS_CACHE_TTL, JwksCache
from waggi_auth.providers.google import GoogleClient
from waggi_shared.errors import APIError, UnauthorizedError


@pytest.fixture(autouse=True)
def _reset_google_jwks():
    google_module._JWKS._keys = {}
    google_module._JWKS._fetched_at = 0.0
    yield
    google_module._JWKS._keys = {}
    google_module._JWKS._fetched_at = 0.0


def _client() -> GoogleClient:
    return GoogleClient(settings.google_client_id, settings.google_client_secret)


# --- registry ------------------------------------------------------------------


def test_get_provider_client_unknown_404() -> None:
    with pytest.raises(APIError) as excinfo:
        get_provider_client("nope")
    assert excinfo.value.status_code == 404


def test_get_provider_client_unconfigured_501(monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_client_id", "")
    with pytest.raises(APIError) as excinfo:
        get_provider_client("google")
    assert excinfo.value.status_code == 501


def test_provider_status(monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_client_id", "")
    status = dict(provider_status())
    assert status == {"google": False, "apple": False}


def test_provider_status_google_enabled() -> None:
    status = dict(provider_status())
    assert status["google"] is True
    assert status["apple"] is False


def test_apple_is_configured_requires_all_fields(monkeypatch) -> None:
    monkeypatch.setattr(settings, "apple_client_id", "id")
    monkeypatch.setattr(settings, "apple_team_id", "team")
    monkeypatch.setattr(settings, "apple_key_id", "key")
    assert dict(provider_status())["apple"] is False  # missing key path
    monkeypatch.setattr(settings, "apple_private_key_path", "/tmp/key.p8")
    assert dict(provider_status())["apple"] is True


# --- authorize_url ----------------------------------------------------------------


def test_google_authorize_url_params() -> None:
    url = _client().authorize_url("http://localhost:5173/cb", "state-1", "nonce-1")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    for fragment in [
        "response_type=code",
        f"client_id={settings.google_client_id}",
        "redirect_uri=http%3A%2F%2Flocalhost%3A5173%2Fcb",
        "state=state-1",
        "nonce=nonce-1",
        "scope=openid+email+profile",
    ]:
        assert fragment in url, fragment


def test_apple_authorize_url_uses_form_post() -> None:
    client = AppleClient("apple-id", "team", "key", "/tmp/k.p8")
    url = client.authorize_url("https://fe/cb", "s", "n")
    assert url.startswith("https://appleid.apple.com/auth/authorize?")
    assert "response_mode=form_post" in url
    assert "scope=name+email" in url


def test_base_client_secret_fields_default_empty() -> None:
    """The base provider sends no extra auth fields (subclasses override)."""
    from waggi_auth.providers.base import JwksCache, ProviderClient

    client = ProviderClient(
        client_id="x",
        authorize_endpoint="https://a",
        token_endpoint="https://t",
        jwks=JwksCache("https://j"),
        issuers=("https://i",),
    )
    assert client._client_secret_fields() == {}
    assert client.name == "" and client.scope == ""


# --- exchange_code -------------------------------------------------------------------


@respx.mock
async def test_exchange_network_error_502() -> None:
    import httpx

    respx.post(GOOGLE_TOKEN_ENDPOINT).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(APIError) as excinfo:
        await _client().exchange_code("code", "http://cb", "nonce")
    assert excinfo.value.status_code == 502


@respx.mock
async def test_exchange_rejected_code_401() -> None:
    respx.post(GOOGLE_TOKEN_ENDPOINT).mock(return_value=Response(401, json={"error": "bad"}))
    with pytest.raises(UnauthorizedError):
        await _client().exchange_code("code", "http://cb", "nonce")


@respx.mock
async def test_exchange_malformed_json_502() -> None:
    respx.post(GOOGLE_TOKEN_ENDPOINT).mock(return_value=Response(200, text="not json"))
    with pytest.raises(APIError) as excinfo:
        await _client().exchange_code("code", "http://cb", "nonce")
    assert excinfo.value.status_code == 502


@respx.mock
async def test_exchange_missing_id_token_502() -> None:
    respx.post(GOOGLE_TOKEN_ENDPOINT).mock(return_value=Response(200, json={"foo": 1}))
    with pytest.raises(APIError) as excinfo:
        await _client().exchange_code("code", "http://cb", "nonce")
    assert excinfo.value.status_code == 502


@respx.mock
async def test_exchange_happy_path_returns_verified_identity() -> None:
    provider = FakeProvider()
    respx.post(GOOGLE_TOKEN_ENDPOINT).mock(
        return_value=Response(200, json={"id_token": provider.id_token(subject="sub-1", nonce="n")})
    )
    respx.get(GOOGLE_JWKS_ENDPOINT).mock(return_value=Response(200, json=provider.jwks_document()))
    identity = await _client().exchange_code("code", "http://cb", "n")
    assert identity.subject == "sub-1"
    assert identity.email == "user@example.com"
    assert identity.email_verified is True
    assert identity.full_name == "Test User"


# --- _verify_id_token edge cases ---------------------------------------------------------


def _mock_jwks(provider: FakeProvider):
    return respx.get(GOOGLE_JWKS_ENDPOINT).mock(return_value=Response(200, json=provider.jwks_document()))


@respx.mock
async def _verify(provider: FakeProvider, token: str) -> None:
    """Verify `token` — caller must have mocked the JWKS endpoint."""
    client = _client()
    import httpx

    async with httpx.AsyncClient() as http:
        await client._verify_id_token(token, "expected-nonce", http)


@respx.mock
async def test_verify_unknown_kid_401() -> None:
    provider = FakeProvider(kid="real-kid")
    token = pyjwt.encode(
        {"sub": "s", "exp": int(time.time()) + 600, "iat": int(time.time()), "nonce": "n"},
        provider._key,
        algorithm="RS256",
        headers={"kid": "other-kid"},
    )
    _mock_jwks(provider)
    with pytest.raises(UnauthorizedError, match="Unknown provider signing key"):
        await _verify(provider, token)


@respx.mock
async def test_verify_key_rotation_refresh() -> None:
    """Unknown kid triggers exactly one JWKS refresh — rotation handled."""
    import httpx

    old = FakeProvider(kid="old-kid")
    route = _mock_jwks(old)  # cache primed with the OLD key set
    client = _client()
    async with httpx.AsyncClient() as http:
        await client._jwks.key_for(http, "old-kid")  # prime (1 fetch)
    assert route.call_count == 1

    # Provider rotated: the new key set now contains the token's kid.
    new = FakeProvider(kid="new-kid")
    route.mock(return_value=Response(200, json=new.jwks_document()))
    token = new.id_token(subject="rotated-sub", nonce="expected-nonce")
    async with httpx.AsyncClient() as http:
        identity = await client._verify_id_token(token, "expected-nonce", http)
    assert identity.subject == "rotated-sub"
    assert route.call_count == 2  # exactly one refresh, then verified


@respx.mock
async def test_verify_wrong_nonce_401() -> None:
    provider = FakeProvider()
    token = provider.id_token(subject="s", nonce="wrong")
    _mock_jwks(provider)
    with pytest.raises(UnauthorizedError, match="nonce"):
        await _verify(provider, token)


@respx.mock
async def test_verify_wrong_issuer_401() -> None:
    provider = FakeProvider()
    token = provider.id_token(subject="s", nonce="expected-nonce", issuer="https://evil.example")
    _mock_jwks(provider)
    with pytest.raises(UnauthorizedError, match="issuer"):
        await _verify(provider, token)


@respx.mock
async def test_verify_wrong_audience_401() -> None:
    provider = FakeProvider()
    token = provider.id_token(subject="s", nonce="expected-nonce", audience="other-app")
    _mock_jwks(provider)
    with pytest.raises(UnauthorizedError, match="verification"):
        await _verify(provider, token)


@respx.mock
async def test_verify_expired_401() -> None:
    provider = FakeProvider()
    token = provider.id_token(subject="s", nonce="expected-nonce", expires_in=-600)
    _mock_jwks(provider)
    with pytest.raises(UnauthorizedError):
        await _verify(provider, token)


@respx.mock
async def test_verify_apple_string_email_verified_normalized() -> None:
    provider = FakeProvider()
    token = provider.id_token(subject="s", nonce="expected-nonce", email_verified="true")
    respx.get(GOOGLE_JWKS_ENDPOINT).mock(return_value=Response(200, json=provider.jwks_document()))
    import httpx

    client = _client()
    async with httpx.AsyncClient() as http:
        identity = await client._verify_id_token(token, "expected-nonce", http)
    assert identity.email_verified is True


@respx.mock
async def test_verify_without_email() -> None:
    provider = FakeProvider()
    token = provider.id_token(subject="s", nonce="expected-nonce", include_email=False)
    respx.get(GOOGLE_JWKS_ENDPOINT).mock(return_value=Response(200, json=provider.jwks_document()))
    import httpx

    client = _client()
    async with httpx.AsyncClient() as http:
        identity = await client._verify_id_token(token, "expected-nonce", http)
    assert identity.email is None


@respx.mock
async def test_verify_rejects_hs256_token() -> None:
    """alg pinned to RS256 — an HS256 token must never verify."""
    now = int(time.time())
    token = pyjwt.encode(
        {"sub": "s", "exp": now + 600, "iat": now, "nonce": "expected-nonce", "iss": GOOGLE_ISSUER},
        "attacker-secret-0123456789abcdef",  # >=32 bytes: keep PyJWT's key-length warning quiet
        algorithm="HS256",
        headers={"kid": "test-kid-1", "alg": "HS256"},
    )
    provider = FakeProvider()
    _mock_jwks(provider)
    with pytest.raises(UnauthorizedError):
        await _verify(provider, token)


@respx.mock
async def test_verify_garbage_token_401() -> None:
    provider = FakeProvider()
    with pytest.raises(UnauthorizedError, match="Malformed"):
        await _verify(provider, "not-a-token")


# --- JwksCache ------------------------------------------------------------------------------


@respx.mock
async def test_jwks_cache_ttl_refresh() -> None:
    provider = FakeProvider()
    route = respx.get(GOOGLE_JWKS_ENDPOINT).mock(return_value=Response(200, json=provider.jwks_document()))
    cache = JwksCache(GOOGLE_JWKS_ENDPOINT)
    import httpx

    async with httpx.AsyncClient() as http:
        await cache.keys(http)
        await cache.keys(http)  # cached, no refetch
        assert route.call_count == 1
        # Simulate TTL expiry RELATIVE TO NOW: time.monotonic() is seconds since
        # boot and starts near 0 on a fresh VM (CI runners), so an absolute 0.0
        # would not be "> TTL ago" there and the cache would never expire.
        cache._fetched_at = time.monotonic() - _JWKS_CACHE_TTL - 1
        await cache.keys(http)
        assert route.call_count == 2


@respx.mock
async def test_jwks_cache_fetch_failure_502() -> None:
    respx.get(GOOGLE_JWKS_ENDPOINT).mock(return_value=Response(500))
    cache = JwksCache(GOOGLE_JWKS_ENDPOINT)
    import httpx

    async with httpx.AsyncClient() as http:
        with pytest.raises(APIError) as excinfo:
            await cache.keys(http)
        assert excinfo.value.status_code == 502


# --- Apple client secret ------------------------------------------------------------------------


def _write_ec_key(tmp_path) -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path = tmp_path / "apple.p8"
    path.write_bytes(pem)
    return str(path)


def test_apple_client_secret_is_valid_es256_jwt(tmp_path) -> None:
    key_path = _write_ec_key(tmp_path)
    client = AppleClient("apple-client", "TEAMID1234", "KEYID1234", key_path)
    fields = client._client_secret_fields()
    assert set(fields) == {"client_secret"}
    secret = fields["client_secret"]

    header = pyjwt.get_unverified_header(secret)
    assert header["alg"] == "ES256"
    assert header["kid"] == "KEYID1234"

    # Verify with the matching public key.
    with open(key_path, "rb") as fh:
        private = serialization.load_pem_private_key(fh.read(), password=None)
    payload = pyjwt.decode(
        secret,
        private.public_key(),
        algorithms=["ES256"],
        audience="https://appleid.apple.com",
        issuer="TEAMID1234",
        options={"require": ["exp", "iat"]},
    )
    assert payload["sub"] == "apple-client"
    assert payload["exp"] - payload["iat"] == 600


def test_apple_client_secret_missing_key_file_500(tmp_path) -> None:
    client = AppleClient("id", "team", "key", str(tmp_path / "missing.p8"))
    with pytest.raises(APIError) as excinfo:
        client._client_secret_fields()
    assert excinfo.value.status_code == 500


def test_apple_client_secret_non_ec_key_500(tmp_path) -> None:
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "rsa.pem"
    path.write_bytes(
        rsa_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    client = AppleClient("id", "team", "key", str(path))
    with pytest.raises(APIError) as excinfo:
        client._client_secret_fields()
    assert excinfo.value.status_code == 500
