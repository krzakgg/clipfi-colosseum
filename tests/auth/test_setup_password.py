"""Endpoint tests for the forced password-setup gate (`must_set_password`).

While the flag is set, NO login flow issues session tokens — each returns a
single-use setup token instead (SetupRequiredResponse), exchangeable only at
POST /auth/setup-password. Covers password login, the MFA second step, the
SSO complete step, passkey login finish, and every setup-password edge case.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import redis.asyncio as aioredis
from tests.auth.conftest import PASSWORD

from waggi_auth.config import settings
from waggi_auth.models import PasswordReset, User
from waggi_auth.security.signing import create_mfa_token, create_setup_token
from waggi_auth.stores import mfa
from waggi_shared.passwords import verify_password

NEW_PASSWORD = "BrandNewPass123!"


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _login(client, email: str, password: str):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def _gated_setup_token(client, user: User) -> str:
    """Drive login to a setup token for a flagged user (no TOTP)."""
    r = await _login(client, user.email, PASSWORD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("setup_required") is True
    assert body["setup_token"]
    assert "access_token" not in body
    return body["setup_token"]


async def _setup(client, token: str, new_password: str):
    return await client.post(
        "/api/v1/auth/setup-password",
        json={"setup_token": token, "new_password": new_password},
    )


# --- gated login flows ---------------------------------------------------------


async def test_gated_login_returns_setup_challenge_not_tokens(client, make_user) -> None:
    user = await make_user(must_set_password=True)
    r = await _login(client, user.email, PASSWORD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["setup_required"] is True
    assert body["setup_token"]
    assert body["expires_in"] > 0
    assert "access_token" not in body
    assert "refresh_token" not in body


async def test_gated_totp_user_mfa_first_then_setup(client, make_user, totp_code) -> None:
    """For 2FA users the gate applies AFTER the second factor — knowing only
    the shared temp password must not reach the password change."""
    user = await make_user(totp=True, must_set_password=True)

    r = await _login(client, user.email, PASSWORD)
    assert r.json().get("mfa_required") is True  # MFA first, not setup

    r = await client.post(
        "/api/v1/auth/login/mfa",
        json={"mfa_token": r.json()["mfa_token"], "code": totp_code(user)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("setup_required") is True  # second factor cleared -> gate
    assert "access_token" not in body

    r = await _setup(client, body["setup_token"], NEW_PASSWORD)
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


async def test_gated_sso_complete_returns_setup_challenge(client, make_user) -> None:
    from waggi_auth.stores import sso_states

    user = await make_user(password=None, must_set_password=True)  # SSO-first account
    handle = await sso_states.store_login(user.id)
    r = await client.post("/api/v1/auth/sso/complete", json={"handle": handle})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("setup_required") is True
    assert "access_token" not in body


async def test_gated_passkey_login_returns_setup_challenge(client, make_user, auth_headers, db) -> None:
    user = await make_user()  # passkeys need a bearer token to register
    _, sim = await _register_passkey(client, auth_headers(user))
    user.must_set_password = True  # admin resets after registration
    await db.commit()

    r = await _login_passkey_finish(client, sim)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("setup_required") is True
    assert "access_token" not in body


async def _register_passkey(client, auth_headers, *, sim=None):
    from webauthn.helpers import base64url_to_bytes
    from webauthn_sim import SoftAuthenticator

    sim = sim or SoftAuthenticator()
    r = await client.post("/api/v1/auth/passkeys/register/begin", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    challenge = base64url_to_bytes(body["options"]["challenge"])
    credential = sim.register(challenge=challenge, rp_id="localhost", origin="http://localhost:5173")
    r = await client.post(
        "/api/v1/auth/passkeys/register/finish",
        headers=auth_headers,
        json={"handle": body["handle"], "credential": credential, "password": PASSWORD},
    )
    assert r.status_code == 201, r.text
    return r, sim


async def _login_passkey_finish(client, sim):
    from webauthn.helpers import base64url_to_bytes

    r = await client.post("/api/v1/auth/passkeys/login/begin", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200, r.text
    body = r.json()
    challenge = base64url_to_bytes(body["options"]["challenge"])
    assertion = sim.assertion(challenge=challenge, rp_id="localhost", origin="http://localhost:5173")
    return await client.post(
        "/api/v1/auth/passkeys/login/finish",
        headers={"Origin": "http://localhost:5173"},
        json={"handle": body["handle"], "credential": assertion},
    )


# --- POST /setup-password ------------------------------------------------------


async def test_setup_password_completes_login(client, make_user, db) -> None:
    user = await make_user(must_set_password=True)
    token = await _gated_setup_token(client, user)

    r = await _setup(client, token, NEW_PASSWORD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] and body["refresh_token"]

    # DB: flag cleared, new hash actually verifies the new password.
    await db.refresh(user)
    assert user.must_set_password is False
    assert verify_password(NEW_PASSWORD, user.password_hash or "")

    # The freshly issued refresh token works (issued AFTER tokens_invalid_before).
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert r.status_code == 200, r.text

    # Re-login with the chosen password now goes straight to tokens.
    r = await _login(client, user.email, NEW_PASSWORD)
    assert r.status_code == 200
    assert "access_token" in r.json()


async def test_setup_password_replay_rejected(client, make_user) -> None:
    """A token replayed AFTER success is unusable: flag cleared + password set
    -> 409 (the check ordering that matters for single use is the concurrent
    race, covered below)."""
    user = await make_user(must_set_password=True)
    token = await _gated_setup_token(client, user)
    assert (await _setup(client, token, NEW_PASSWORD)).status_code == 200
    r = await _setup(client, token, "AnotherPass123!")  # same token again
    assert r.status_code == 409
    assert r.json()["detail"] == "Password already set"


async def test_setup_password_concurrent_same_token_single_winner(client, make_user) -> None:
    """Two in-flight setups with the SAME token: exactly one wins (jti SET NX
    decides), the loser gets 401 — the shared temp password cannot be spent
    twice even under concurrency."""
    import asyncio

    user = await make_user(must_set_password=True)
    token = await _gated_setup_token(client, user)
    results = await asyncio.gather(
        _setup(client, token, NEW_PASSWORD),
        _setup(client, token, "AnotherPass123!"),
    )
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 401]
    winner = next(r for r in results if r.status_code == 200)
    assert winner.json()["access_token"]


async def test_setup_password_rejects_temp_password_reuse_without_burning_token(client, make_user) -> None:
    user = await make_user(must_set_password=True)
    token = await _gated_setup_token(client, user)
    # Reusing the TEMP password: rejected, and a typo must not burn the token.
    r = await _setup(client, token, PASSWORD)
    assert r.status_code == 422  # ValidationError (problem+json) in this codebase
    assert r.json()["detail"] == "New password must differ from the temporary one"
    r = await _setup(client, token, NEW_PASSWORD)
    assert r.status_code == 200, r.text


async def test_setup_password_passwordless_accepts_any_password(client, make_user, db) -> None:
    """SSO-first accounts have no temp hash — any valid password is fine."""
    user = await make_user(password=None, must_set_password=True)
    token, _ = create_setup_token(user_id=user.id)  # no password login possible
    r = await _setup(client, token, NEW_PASSWORD)
    assert r.status_code == 200, r.text
    await db.refresh(user)
    assert user.must_set_password is False


async def test_setup_password_bad_token_401(client) -> None:
    r = await _setup(client, "garbage", NEW_PASSWORD)
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired setup token"


async def test_setup_password_rejects_mfa_token(client) -> None:
    """Audience separation: an MFA challenge token must not open setup."""
    token, _ = create_mfa_token(user_id=uuid.uuid4())
    r = await _setup(client, token, NEW_PASSWORD)
    assert r.status_code == 401


async def test_setup_password_inactive_user_401(client, make_user, db) -> None:
    user = await make_user(must_set_password=True)
    token = await _gated_setup_token(client, user)
    user.is_active = False
    await db.commit()
    r = await _setup(client, token, NEW_PASSWORD)
    assert r.status_code == 401
    assert r.json()["detail"] == "User not found or inactive"


async def test_setup_password_already_set_409(client, make_user) -> None:
    """Stale token for a user who already completed setup (or never flagged)."""
    user = await make_user()  # flag False + real password
    token, _ = create_setup_token(user_id=user.id)
    r = await _setup(client, token, NEW_PASSWORD)
    assert r.status_code == 409
    assert r.json()["detail"] == "Password already set"


async def test_setup_password_rate_limited(client, make_user) -> None:
    """The step-up bucket (10/min/user) also guards setup-password."""
    user = await make_user()  # 409 path: burns limiter hits without a real flag
    token, _ = create_setup_token(user_id=user.id)
    for _ in range(10):
        r = await _setup(client, token, NEW_PASSWORD)
        assert r.status_code == 409
    r = await _setup(client, token, NEW_PASSWORD)
    assert r.status_code == 429


async def test_setup_password_redis_down_503(client, make_user, monkeypatch) -> None:
    user = await make_user(must_set_password=True)
    token = await _gated_setup_token(client, user)

    async def _boom(jti: str) -> bool:
        raise aioredis.RedisError("down")

    monkeypatch.setattr(mfa, "consume_setup_jti", _boom)
    r = await _setup(client, token, NEW_PASSWORD)
    assert r.status_code == 503


# --- other password paths clear the flag ---------------------------------------


async def test_change_password_clears_flag(client, make_user, auth_headers, db) -> None:
    """Mid-session admin reset: knowing the temp password satisfies the gate."""
    user = await make_user()
    user.must_set_password = True
    await db.commit()
    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 200, r.text
    await db.refresh(user)
    assert user.must_set_password is False


async def test_password_reset_confirm_clears_flag(client, make_user, db) -> None:
    user = await make_user(must_set_password=True)
    reset = PasswordReset(
        user_id=user.id,
        token_hash=_sha256("reset-token"),
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
    )
    db.add(reset)
    await db.commit()
    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "reset-token", "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 200, r.text
    await db.refresh(user)
    assert user.must_set_password is False


async def test_me_does_not_leak_flag(client, make_user, auth_headers) -> None:
    """UserOut deliberately has no must_set_password: unreachable pre-setup."""
    user = await make_user()
    r = await client.get("/api/v1/auth/me", headers=auth_headers(user))
    assert r.status_code == 200
    assert "must_set_password" not in r.json()


# --- setup-token unit checks (mirror the MFA token tests) ----------------------


def _craft(payload: dict, secret: str = settings.mfa_token_secret) -> str:
    return pyjwt.encode(payload, secret, algorithm="HS256")


def test_setup_token_roundtrip_with_unique_jti() -> None:
    from waggi_auth.security.signing import SetupTokenData, verify_setup_token

    user_id = uuid.uuid4()
    token, ttl = create_setup_token(user_id=user_id)
    assert ttl == settings.setup_token_ttl_minutes * 60
    data = verify_setup_token(token)
    assert data is not None
    assert data == SetupTokenData(user_id=user_id, jti=data.jti)
    other, _ = create_setup_token(user_id=user_id)
    other_data = verify_setup_token(other)
    assert other_data is not None and other_data.jti != data.jti


def test_setup_token_expired(monkeypatch) -> None:
    from waggi_auth.security.signing import verify_setup_token

    monkeypatch.setattr(settings, "setup_token_ttl_minutes", -1)
    token, _ = create_setup_token(user_id=uuid.uuid4())
    assert verify_setup_token(token) is None


def test_setup_token_wrong_audience() -> None:
    from waggi_auth.security.signing import verify_setup_token

    now = int(datetime.now(tz=UTC).timestamp())
    token = _craft(
        {
            "sub": str(uuid.uuid4()),
            "aud": "mfa",  # an MFA token is not a setup token
            "jti": "x",
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + 300,
        }
    )
    assert verify_setup_token(token) is None


def test_setup_token_non_uuid_sub() -> None:
    from waggi_auth.security.signing import verify_setup_token

    now = int(datetime.now(tz=UTC).timestamp())
    token = _craft(
        {
            "sub": "not-a-uuid",
            "aud": "setup_password",
            "jti": "x",
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + 300,
        }
    )
    assert verify_setup_token(token) is None


def test_mfa_token_wrong_setup_audience_rejected() -> None:
    """And the reverse: a setup token must not open /login/mfa."""
    from waggi_auth.security.signing import verify_mfa_token

    token, _ = create_setup_token(user_id=uuid.uuid4())
    assert verify_mfa_token(token) is None
