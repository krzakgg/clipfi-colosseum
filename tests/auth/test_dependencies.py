"""Tests for auth dependencies: bearer auth, account-type checks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization

from waggi_auth.config import settings
from waggi_auth.dependencies import require_account_types
from waggi_auth.models import AccountType, User
from waggi_auth.security.keys import get_private_key
from waggi_auth.security.signing import create_access_token
from waggi_shared.errors import ForbiddenError


def _sign(payload: dict) -> str:
    """Sign an arbitrary payload with the service's real private key (RS256)."""
    pem = (
        get_private_key()
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )
    return pyjwt.encode(payload, pem, algorithm="RS256", headers={"kid": settings.jwt_key_id})


async def test_me_with_valid_token(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.get("/api/v1/auth/me", headers=auth_headers(user))
    assert r.status_code == 200
    assert r.json()["email"] == user.email


async def test_me_missing_header(client) -> None:
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


async def test_me_wrong_scheme(client, make_user, auth_headers) -> None:
    user = await make_user()
    token = auth_headers(user)["Authorization"].removeprefix("Bearer ")
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Basic {token}"})
    assert r.status_code == 401


async def test_me_garbage_token(client) -> None:
    r = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


async def test_me_expired_token(client, make_user, monkeypatch) -> None:
    user = await make_user()
    monkeypatch.setattr(settings, "access_token_ttl_minutes", -1)
    token, _ = create_access_token(
        user_id=user.id, email=user.email, full_name=user.full_name, account_type=user.account_type.value
    )
    monkeypatch.setattr(settings, "access_token_ttl_minutes", 15)
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_me_wrong_issuer(client, make_user) -> None:
    user = await make_user()
    now = int(datetime.now(tz=UTC).timestamp())
    token = _sign(
        {
            "sub": str(user.id),
            "email": user.email,
            "name": user.full_name,
            "account_type": "company",
            "iss": "evil-issuer",
            "iat": now,
            "exp": now + 300,
        }
    )
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_me_hs256_algorithm_confusion_rejected(client, make_user) -> None:
    """A validly-signed HS256 token must be rejected: only RS256 is allowed."""
    user = await make_user()
    now = int(datetime.now(tz=UTC).timestamp())
    token = pyjwt.encode(
        {
            "sub": str(user.id),
            "email": user.email,
            "name": user.full_name,
            "account_type": "creator",
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + 300,
        },
        "attacker-chosen-hmac-secret-0123456789",  # >=32 bytes: no PyJWT key-length warning
        algorithm="HS256",
    )
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_me_missing_required_claims(client, make_user) -> None:
    user = await make_user()
    now = int(datetime.now(tz=UTC).timestamp())
    token = _sign({"sub": str(user.id), "iss": settings.jwt_issuer, "exp": now + 300})  # no iat
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_me_non_uuid_sub(client) -> None:
    now = int(datetime.now(tz=UTC).timestamp())
    token = _sign(
        {
            "sub": "not-a-uuid",
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + 300,
        }
    )
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_me_unknown_user(client, make_user, auth_headers, db) -> None:
    user = await make_user()
    headers = auth_headers(user)
    await db.delete(user)
    await db.commit()
    r = await client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 401


async def test_me_inactive_user(client, make_user, auth_headers, db) -> None:
    user = await make_user()
    headers = auth_headers(user)
    user.is_active = False
    await db.commit()
    r = await client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 401


# --- require_account_types (direct calls) -----------------------------------


def _fake_user(account_type: AccountType, *, totp: bool = False) -> User:
    return User(
        id=uuid.uuid4(),
        email="x@example.com",
        full_name="X",
        account_type=account_type,
        is_active=True,
        totp_enabled=totp,
    )


async def test_require_account_types_allows_matching() -> None:
    checker = require_account_types(AccountType.company, AccountType.creator)
    user = _fake_user(AccountType.company)
    assert await checker(user=user) is user


async def test_require_account_types_rejects_other() -> None:
    checker = require_account_types(AccountType.company)
    with pytest.raises(ForbiddenError):
        await checker(user=_fake_user(AccountType.creator))
