"""Tests for waggi_auth.security.keys: RSA keypair lifecycle + JWKS document."""

from __future__ import annotations

import base64

import jwt

from waggi_auth.config import settings
from waggi_auth.security import keys
from waggi_auth.security.keys import (
    _ensure_keypair,
    get_private_key,
    get_public_key,
    jwks_document,
)


def _b64u_decode(value: str) -> int:
    padding = "=" * (-len(value) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(value + padding), "big")


# --- RSA keypair -----------------------------------------------------------


async def test_keypair_generated_and_persisted(tmp_path) -> None:
    """Keys land on disk (private 0600) and reload to the same key material."""
    keys._ensure_keypair.cache_clear()
    keys.get_private_key.cache_clear()
    keys.get_public_key.cache_clear()
    try:
        # First access (keys may already exist from conftest's tmpdir): verify
        # persisted + reloadable instead of regenerating.
        private = get_private_key()
        priv_path = settings.jwt_private_key_path
        pub_path = settings.jwt_public_key_path
        assert priv_path and pub_path

        numbers_before = private.public_key().public_numbers()

        # Reload from disk through a fresh cache -> same key.
        keys._ensure_keypair.cache_clear()
        keys.get_private_key.cache_clear()
        keys.get_public_key.cache_clear()
        reloaded = get_private_key()
        assert reloaded.public_key().public_numbers() == numbers_before
    finally:
        keys._ensure_keypair.cache_clear()
        keys.get_private_key.cache_clear()
        keys.get_public_key.cache_clear()


async def test_generate_keypair_writes_files(monkeypatch, tmp_path) -> None:
    """Cold start: no key files -> generate, persist, chmod 0600."""
    priv = tmp_path / "auth_private.pem"
    pub = tmp_path / "auth_public.pem"
    monkeypatch.setattr(settings, "jwt_private_key_path", str(priv))
    monkeypatch.setattr(settings, "jwt_public_key_path", str(pub))
    keys._ensure_keypair.cache_clear()
    keys.get_private_key.cache_clear()
    keys.get_public_key.cache_clear()
    try:
        private, public = _ensure_keypair()
        assert priv.exists() and pub.exists()
        assert priv.stat().st_mode & 0o777 == 0o600
        assert private.public_key().public_numbers() == public.public_numbers()
    finally:
        keys._ensure_keypair.cache_clear()
        keys.get_private_key.cache_clear()
        keys.get_public_key.cache_clear()


# --- JWKS --------------------------------------------------------------------


async def test_jwks_document_shape() -> None:
    doc = jwks_document()
    assert set(doc) == {"keys"}
    (key,) = doc["keys"]
    assert key["kid"] == settings.jwt_key_id
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert key["use"] == "sig"
    numbers = get_public_key().public_numbers()
    assert _b64u_decode(key["n"]) == numbers.n
    assert _b64u_decode(key["e"]) == numbers.e
    # The JWK is consumable by PyJWT (this is what admin/bookings do).
    parsed = jwt.PyJWK.from_dict(key)
    assert parsed.key
