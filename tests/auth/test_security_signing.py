"""Tests for waggi_auth.security.signing: access, refresh and MFA tokens."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization

from waggi_auth.config import settings
from waggi_auth.security.keys import get_public_key
from waggi_auth.security.signing import (
    MfaTokenData,
    create_access_token,
    create_mfa_token,
    create_refresh_token,
    hash_refresh_token,
    verify_mfa_token,
)


def _public_pem() -> str:
    return (
        get_public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


# --- Access tokens -----------------------------------------------------------


async def test_access_token_claims() -> None:
    user_id = uuid.uuid4()
    token, ttl = create_access_token(user_id=user_id, email="u@example.com", full_name="User Name", account_type="company")
    assert ttl == settings.access_token_ttl_minutes * 60
    payload = jwt.decode(token, _public_pem(), algorithms=["RS256"], issuer=settings.jwt_issuer)
    assert payload["sub"] == str(user_id)
    assert payload["email"] == "u@example.com"
    assert payload["name"] == "User Name"
    assert payload["account_type"] == "company"
    assert payload["exp"] - payload["iat"] == ttl
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "RS256"
    assert header["kid"] == settings.jwt_key_id


# --- Refresh tokens ----------------------------------------------------------


async def test_refresh_token_shape_and_hash() -> None:
    raw, token_hash, issued, expires = create_refresh_token()
    assert len(raw) >= 64  # 48 bytes urlsafe
    assert token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert issued.tzinfo
    assert expires > issued
    assert expires - issued == timedelta(days=settings.refresh_token_ttl_days)
    raw2, hash2, _, _ = create_refresh_token()
    assert raw2 != raw and hash2 != token_hash


async def test_hash_refresh_token_helper() -> None:
    assert hash_refresh_token("abc") == hashlib.sha256(b"abc").hexdigest()


# --- MFA tokens ---------------------------------------------------------------


async def test_mfa_token_roundtrip_with_unique_jti() -> None:
    user_id = uuid.uuid4()
    token, ttl = create_mfa_token(user_id=user_id)
    assert ttl == settings.mfa_token_ttl_minutes * 60
    data = verify_mfa_token(token)
    assert data == MfaTokenData(user_id=user_id, jti=data.jti if data else "")
    assert data is not None and data.user_id == user_id and data.jti
    other, _ = create_mfa_token(user_id=user_id)
    assert verify_mfa_token(other).jti != data.jti  # type: ignore[union-attr]


async def test_mfa_token_expired(monkeypatch) -> None:
    monkeypatch.setattr(settings, "mfa_token_ttl_minutes", -1)
    token, _ = create_mfa_token(user_id=uuid.uuid4())
    assert verify_mfa_token(token) is None


async def test_mfa_token_tampered() -> None:
    token, _ = create_mfa_token(user_id=uuid.uuid4())
    assert verify_mfa_token(token[:-3] + "aaa") is None


async def test_mfa_token_wrong_secret(monkeypatch) -> None:
    token, _ = create_mfa_token(user_id=uuid.uuid4())
    monkeypatch.setattr(settings, "mfa_token_secret", "a-different-secret-0123456789abcdef")
    assert verify_mfa_token(token) is None


async def test_mfa_token_wrong_audience() -> None:
    now = int(datetime.now(tz=UTC).timestamp())
    payload = {
        "sub": str(uuid.uuid4()),
        "aud": "access",
        "jti": "x",
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + 300,
    }
    token = jwt.encode(payload, settings.mfa_token_secret, algorithm="HS256")
    assert verify_mfa_token(token) is None


async def test_mfa_token_missing_claims() -> None:
    now = int(datetime.now(tz=UTC).timestamp())
    payload = {"sub": str(uuid.uuid4()), "aud": "mfa", "iss": settings.jwt_issuer, "iat": now, "exp": now + 300}
    token = jwt.encode(payload, settings.mfa_token_secret, algorithm="HS256")
    assert verify_mfa_token(token) is None  # jti required


async def test_mfa_token_missing_audience() -> None:
    now = int(datetime.now(tz=UTC).timestamp())
    payload = {
        "sub": str(uuid.uuid4()),
        "jti": "x",
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + 300,
    }
    token = jwt.encode(payload, settings.mfa_token_secret, algorithm="HS256")
    assert verify_mfa_token(token) is None  # aud required


async def test_mfa_token_non_uuid_sub() -> None:
    now = int(datetime.now(tz=UTC).timestamp())
    payload = {
        "sub": "not-a-uuid",
        "aud": "mfa",
        "jti": "x",
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + 300,
    }
    token = jwt.encode(payload, settings.mfa_token_secret, algorithm="HS256")
    assert verify_mfa_token(token) is None
