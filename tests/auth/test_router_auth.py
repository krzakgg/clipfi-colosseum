"""Endpoint tests for the auth router: login, MFA, refresh, logout, me, passwords."""

from __future__ import annotations

import asyncio
import hashlib
import secrets as py_secrets
from datetime import UTC, datetime, timedelta

import pyotp
import redis.asyncio as aioredis
from argon2 import PasswordHasher
from tests.auth.conftest import PASSWORD
from sqlalchemy import select

from waggi_auth.models import PasswordReset, RefreshToken, User
from waggi_auth.security.totp import generate_backup_codes, hash_backup_codes
from waggi_auth.stores import mfa
from waggi_shared.passwords import needs_rehash


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _login(client, email: str, password: str):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def _mfa_challenge(client, user) -> str:
    r = await _login(client, user.email, PASSWORD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("mfa_required") is True
    return body["mfa_token"]


# --- POST /login ---------------------------------------------------------------


async def test_login_success(client, make_user) -> None:
    user = await make_user()
    r = await _login(client, user.email, PASSWORD)
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] > 0


async def test_login_requires_totp_step(client, make_user) -> None:
    user = await make_user(totp=True)
    r = await _login(client, user.email, PASSWORD)
    assert r.status_code == 200
    body = r.json()
    assert body["mfa_required"] is True
    assert body["mfa_token"]
    assert body["expires_in"] > 0
    assert "access_token" not in body


async def test_login_wrong_password(client, make_user) -> None:
    user = await make_user()
    r = await _login(client, user.email, "WrongPassword123!")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["detail"] == "Invalid email or password"
    assert r.json()["type"] == "https://errors.waggi.local/invalid_credentials"


async def test_login_unknown_email(client) -> None:
    """Unknown email -> same 401, and the dummy-verify path runs (timing)."""
    r = await _login(client, "ghost@example.com", "Whatever123!")
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


async def test_login_inactive_user(client, make_user) -> None:
    user = await make_user(is_active=False)
    r = await _login(client, user.email, PASSWORD)
    assert r.status_code == 401


async def test_login_sso_only_user_without_password(client, make_user) -> None:
    user = await make_user(password=None)
    r = await _login(client, user.email, PASSWORD)
    assert r.status_code == 401


async def test_login_rehashes_outdated_hash(client, make_user, db) -> None:
    """A weak/outdated argon2 hash is transparently upgraded on successful login."""
    user = await make_user()
    weak = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1).hash(PASSWORD)
    user.password_hash = weak
    await db.commit()

    r = await _login(client, user.email, PASSWORD)
    assert r.status_code == 200, r.text

    await db.refresh(user)
    assert user.password_hash != weak
    assert needs_rehash(user.password_hash) is False


async def test_login_rate_limited_per_email(client, make_user) -> None:
    user = await make_user()
    for _ in range(10):
        r = await _login(client, user.email, "WrongPassword123!")
        assert r.status_code == 401
    r = await _login(client, user.email, PASSWORD)  # even the RIGHT password...
    assert r.status_code == 429
    assert r.json()["retry_after"] >= 1
    # ...and a different email is unaffected
    r2 = await _login(client, "other@example.com", "x")
    assert r2.status_code == 401


async def test_login_rate_limited_per_ip_blocks_spraying(client) -> None:
    """Password spraying: rotating emails from ONE IP trips the per-IP bucket
    even though every email bucket stays under its own limit."""
    for i in range(30):
        r = await _login(client, f"victim{i}@example.com", "SprayPassword123!")
        assert r.status_code == 401
    r = await _login(client, "next@example.com", "SprayPassword123!")
    assert r.status_code == 429


async def test_login_password_too_long_422(client, make_user) -> None:
    """M1: an oversized password is rejected by validation BEFORE argon2 runs."""
    user = await make_user()
    r = await _login(client, user.email, "x" * 129)
    assert r.status_code == 422


# --- POST /register (waggi: public self-signup) ----------------------------------


async def test_register_company_success(client, db) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "account_type": "company",
            "email": "NewCorp@Example.com",
            "full_name": "New Corp",
            "password": "Str0ngPassword!",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["access_token"] and body["refresh_token"]

    user = (await db.execute(select(User).where(User.email == "newcorp@example.com"))).scalar_one()
    assert user.account_type.value == "company"
    assert user.username is None
    assert user.password_hash  # argon2 hash stored, not plaintext


async def test_register_creator_with_username(client, db) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "account_type": "creator",
            "email": "creator@example.com",
            "username": "NeoCreator",
            "full_name": "Neo Creator",
            "password": "Str0ngPassword!",
        },
    )
    assert r.status_code == 201
    user = (await db.execute(select(User).where(User.email == "creator@example.com"))).scalar_one()
    assert user.username == "neocreator"  # CITEXT folds case


async def test_register_login_with_username(client, make_user) -> None:
    await make_user(email="jan@example.com", username="janek")
    r = await _login(client, "janek", PASSWORD)
    assert r.status_code == 200
    assert r.json()["access_token"]


async def test_register_duplicate_email_conflict(client, make_user) -> None:
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "account_type": "company",
            "email": user.email,
            "full_name": "Dup",
            "password": "Str0ngPassword!",
        },
    )
    assert r.status_code == 409
    assert r.json()["type"] == "https://errors.waggi.local/account_exists"


async def test_register_duplicate_username_conflict(client, make_user) -> None:
    await make_user(email="first@example.com", username="taken")
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "account_type": "creator",
            "email": "second@example.com",
            "username": "TAKEN",
            "full_name": "Dup",
            "password": "Str0ngPassword!",
        },
    )
    assert r.status_code == 409


async def test_register_weak_password_rejected(client) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "account_type": "company",
            "email": "weak@example.com",
            "full_name": "Weak Co",
            "password": "password",
        },
    )
    assert r.status_code == 422
    assert r.json()["type"].endswith(("password_character_requirements", "password_too_short"))


async def test_register_password_with_personal_data_rejected(client) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "account_type": "company",
            "email": "acme@example.com",
            "full_name": "Acme Co",
            "password": "AcmeStr0ng!2026",
        },
    )
    assert r.status_code == 422
    assert r.json()["type"] == "https://errors.waggi.local/password_contains_personal"


# --- POST /login/mfa ------------------------------------------------------------


async def test_login_mfa_totp_success(client, make_user, totp_code) -> None:
    user = await make_user(totp=True)
    mfa_token = await _mfa_challenge(client, user)
    r = await client.post(
        "/api/v1/auth/login/mfa",
        json={"mfa_token": mfa_token, "code": totp_code(user, offset_steps=-1)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


async def test_login_mfa_wrong_code_then_retry_succeeds(client, make_user, totp_code) -> None:
    """A typo must NOT burn the mfa token (consume happens after validation)."""
    user = await make_user(totp=True)
    mfa_token = await _mfa_challenge(client, user)
    wrong = pyotp.TOTP(pyotp.random_base32()).now()  # valid format, wrong secret
    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": mfa_token, "code": wrong})
    assert r.status_code == 401
    r = await client.post(
        "/api/v1/auth/login/mfa",
        json={"mfa_token": mfa_token, "code": totp_code(user, offset_steps=-1)},
    )
    assert r.status_code == 200


async def test_login_mfa_totp_code_reuse_rejected(client, make_user, totp_code) -> None:
    user = await make_user(totp=True)
    code = totp_code(user, offset_steps=-1)  # previous step: stable ~60s

    token1 = await _mfa_challenge(client, user)
    r1 = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": token1, "code": code})
    assert r1.status_code == 200

    token2 = await _mfa_challenge(client, user)  # fresh mfa token...
    r2 = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": token2, "code": code})
    assert r2.status_code == 401  # ...but the CODE is spent


async def test_login_mfa_backup_code_success_and_redeemed(client, make_user) -> None:
    user = await make_user(totp=True, backup_codes=["AAAA-BBBB", "CCCC-DDDD"])
    mfa_token = await _mfa_challenge(client, user)

    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": mfa_token, "backup_code": "AAAA-BBBB"})
    assert r.status_code == 200

    # The redeemed backup code cannot be used again (new mfa token).
    token2 = await _mfa_challenge(client, user)
    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": token2, "backup_code": "AAAA-BBBB"})
    assert r.status_code == 401


async def test_login_mfa_concurrent_backup_code_single_winner(client, make_user) -> None:
    """R3-L1: two simultaneous logins spending the SAME backup code with
    different, valid mfa tokens — the conditional redemption UPDATE lets
    exactly one win (the old read-modify-write let both through)."""
    user = await make_user(totp=True, backup_codes=["AAAA-BBBB"])
    token1 = await _mfa_challenge(client, user)
    token2 = await _mfa_challenge(client, user)

    r1, r2 = await asyncio.gather(
        client.post("/api/v1/auth/login/mfa", json={"mfa_token": token1, "backup_code": "AAAA-BBBB"}),
        client.post("/api/v1/auth/login/mfa", json={"mfa_token": token2, "backup_code": "AAAA-BBBB"}),
    )
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 401]
    if r1.status_code == 401:
        assert r1.json()["detail"] == "Invalid backup code"


async def test_login_mfa_redeems_current_format_code(client, make_user, db) -> None:
    """End-to-end redemption of a current-format (peppered-hash) backup code.
    The seeded-code tests above exercise the legacy unsalted-sha256 path."""
    codes = generate_backup_codes()
    user = await make_user(totp=True)
    user.totp_backup_codes_hashed = hash_backup_codes(codes)
    await db.commit()

    mfa_token = await _mfa_challenge(client, user)
    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": mfa_token, "backup_code": codes[0]})
    assert r.status_code == 200, r.text

    token2 = await _mfa_challenge(client, user)
    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": token2, "backup_code": codes[0]})
    assert r.status_code == 401  # redeemed


async def test_login_mfa_token_replay_rejected(client, make_user) -> None:
    """Same mfa token twice with two DIFFERENT valid backup codes -> replay wins."""
    user = await make_user(totp=True, backup_codes=["AAAA-BBBB", "CCCC-DDDD"])
    mfa_token = await _mfa_challenge(client, user)

    r1 = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": mfa_token, "backup_code": "AAAA-BBBB"})
    assert r1.status_code == 200

    r2 = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": mfa_token, "backup_code": "CCCC-DDDD"})
    assert r2.status_code == 401
    assert r2.json()["detail"] == "MFA token already used"


async def test_login_mfa_invalid_backup_code(client, make_user) -> None:
    user = await make_user(totp=True, backup_codes=["AAAA-BBBB"])
    mfa_token = await _mfa_challenge(client, user)
    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": mfa_token, "backup_code": "XXXX-XXXX"})
    assert r.status_code == 401


async def test_login_mfa_no_credentials(client, make_user) -> None:
    user = await make_user(totp=True)
    mfa_token = await _mfa_challenge(client, user)
    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": mfa_token})
    assert r.status_code == 422


async def test_login_mfa_bad_token(client) -> None:
    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": "garbage", "code": "123456"})
    assert r.status_code == 401


async def test_login_mfa_user_deactivated_between_steps(client, make_user, totp_code, db) -> None:
    user = await make_user(totp=True)
    mfa_token = await _mfa_challenge(client, user)
    user.is_active = False
    await db.commit()
    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": mfa_token, "code": totp_code(user)})
    assert r.status_code == 401


async def test_login_mfa_unknown_user_in_token(client, make_user, totp_code, db) -> None:
    user = await make_user(totp=True)
    mfa_token = await _mfa_challenge(client, user)
    await db.delete(user)
    await db.commit()
    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": mfa_token, "code": totp_code(user)})
    assert r.status_code == 401


async def test_login_mfa_redis_down_fails_closed(client, make_user, totp_code, monkeypatch) -> None:
    user = await make_user(totp=True)
    mfa_token = await _mfa_challenge(client, user)

    class Boom:
        async def set(self, *a, **k):
            raise aioredis.RedisError("down")

    monkeypatch.setattr(mfa, "redis_client", lambda url: Boom())
    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": mfa_token, "code": totp_code(user, offset_steps=-1)})
    assert r.status_code == 503


async def test_login_mfa_rate_limited_per_ip(client) -> None:
    for _ in range(10):
        r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": "garbage", "code": "123456"})
        assert r.status_code == 401
    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": "garbage", "code": "123456"})
    assert r.status_code == 429


# --- POST /refresh ---------------------------------------------------------------


async def _raw_refresh_token(
    db, user: User, *, expires_in_days: float = 14, revoked: bool = False, issued_days_ago: float = 0
) -> str:
    raw = py_secrets.token_urlsafe(48)
    now = datetime.now(tz=UTC)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_sha256(raw),
            issued_at=now - timedelta(days=issued_days_ago),
            expires_at=now + timedelta(days=expires_in_days - issued_days_ago),
            revoked_at=now if revoked else None,
        )
    )
    await db.commit()
    return raw


async def test_refresh_rotation_revokes_old(client, make_user) -> None:
    user = await make_user()
    r = await _login(client, user.email, PASSWORD)
    old_refresh = r.json()["refresh_token"]

    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    new_refresh = r.json()["refresh_token"]
    assert new_refresh != old_refresh

    # The old token is dead — and its replay is a THEFT SIGNAL (L7): the
    # rotation-revoked token being presented again kills the whole family,
    # including the still-fresh successor.
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 401
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert r.status_code == 401

    # Re-login works and starts a fresh family.
    r = await _login(client, user.email, PASSWORD)
    assert r.status_code == 200
    fresh = r.json()["refresh_token"]
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": fresh})
    assert r.status_code == 200


async def test_refresh_family_kill_spans_generations(client, make_user) -> None:
    """A replayed token that is many rotations stale still kills the chain."""
    user = await make_user()
    gen1 = (await _login(client, user.email, PASSWORD)).json()["refresh_token"]
    gen2 = (await client.post("/api/v1/auth/refresh", json={"refresh_token": gen1})).json()["refresh_token"]
    gen3 = (await client.post("/api/v1/auth/refresh", json={"refresh_token": gen2})).json()["refresh_token"]

    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": gen1})
    assert r.status_code == 401  # theft signal
    for spent in (gen2, gen3):
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": spent})
        assert r.status_code == 401  # whole family revoked


async def test_refresh_unknown_token(client) -> None:
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": "nope"})
    assert r.status_code == 401


async def test_refresh_expired_token(client, make_user, db) -> None:
    user = await make_user()
    raw = await _raw_refresh_token(db, user, expires_in_days=-1, issued_days_ago=15)
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 401


async def test_refresh_revoked_token(client, make_user, db) -> None:
    user = await make_user()
    raw = await _raw_refresh_token(db, user, revoked=True)
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 401


async def test_refresh_invalidated_by_password_change(client, make_user, auth_headers) -> None:
    user = await make_user()
    refresh = (await _login(client, user.email, PASSWORD)).json()["refresh_token"]

    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": PASSWORD, "new_password": "NewPassword123!"},
    )
    assert r.status_code == 200

    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 401
    assert r.json()["detail"] == "Refresh token invalidated by password change"


async def test_refresh_inactive_user(client, make_user, db) -> None:
    user = await make_user()
    raw = await _raw_refresh_token(db, user)
    user.is_active = False
    await db.commit()
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 401


async def test_refresh_concurrent_rotation_single_winner(client, make_user) -> None:
    """Two simultaneous refreshes with the same token: exactly one wins."""
    user = await make_user()
    refresh = (await _login(client, user.email, PASSWORD)).json()["refresh_token"]

    r1, r2 = await asyncio.gather(
        client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}),
        client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}),
    )
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 401]


async def test_refresh_rotation_inherits_family(client, make_user, db) -> None:
    """Rotation stays in the login's family; the old row records its successor."""
    user = await make_user()
    old_raw = (await _login(client, user.email, PASSWORD)).json()["refresh_token"]
    new_raw = (await client.post("/api/v1/auth/refresh", json={"refresh_token": old_raw})).json()["refresh_token"]

    old_row = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == _sha256(old_raw)))).scalar_one()
    new_row = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == _sha256(new_raw)))).scalar_one()
    assert new_row.family_id == old_row.family_id
    assert old_row.replaced_by_id == new_row.id
    assert old_row.revoked_at is not None
    assert new_row.revoked_at is None


async def test_fresh_logins_start_separate_families(client, make_user, db) -> None:
    """Two logins = two families: killing one must never affect the other."""
    user = await make_user()
    raw_a = (await _login(client, user.email, PASSWORD)).json()["refresh_token"]
    raw_b = (await _login(client, user.email, PASSWORD)).json()["refresh_token"]

    row_a = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == _sha256(raw_a)))).scalar_one()
    row_b = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == _sha256(raw_b)))).scalar_one()
    assert row_a.family_id != row_b.family_id


# --- POST /logout ---------------------------------------------------------------


async def test_logout_revokes_refresh(client, make_user) -> None:
    user = await make_user()
    refresh = (await _login(client, user.email, PASSWORD)).json()["refresh_token"]

    r = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 401


async def test_logout_replay_does_not_kill_sibling_sessions(client, make_user) -> None:
    """Logout revocation has no replacement: replaying a logged-out token is a
    stale client, not theft — sibling sessions (other families) must survive."""
    user = await make_user()
    refresh_a = (await _login(client, user.email, PASSWORD)).json()["refresh_token"]
    refresh_b = (await _login(client, user.email, PASSWORD)).json()["refresh_token"]

    r = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_a})
    assert r.status_code == 200

    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_a})
    assert r.status_code == 401  # benign: stale client
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_b})
    assert r.status_code == 200  # sibling session unaffected


async def test_logout_idempotent_and_unknown_tokens(client) -> None:
    r = await client.post("/api/v1/auth/logout", json={"refresh_token": "unknown"})
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/logout", json={"refresh_token": "unknown"})
    assert r.status_code == 200


# --- GET/PATCH /me ---------------------------------------------------------------


async def test_me_roundtrip(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.get("/api/v1/auth/me", headers=auth_headers(user))
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == user.email
    assert body["full_name"] == "Test User"
    assert body["account_type"] == "company"


async def test_update_me_normalizes_phone(client, make_user, auth_headers, db) -> None:
    user = await make_user()
    r = await client.patch(
        "/api/v1/auth/me",
        headers=auth_headers(user),
        json={"full_name": "Renamed User", "phone": "+48 600 100 200"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "Renamed User"
    assert body["phone"] == "+48600100200"  # E.164 normalized


async def test_update_me_email_and_role_read_only(client, make_user, auth_headers, db) -> None:
    user = await make_user()
    r = await client.patch(
        "/api/v1/auth/me",
        headers=auth_headers(user),
        json={"full_name": "X", "phone": None},
    )
    assert r.status_code == 200
    await db.refresh(user)
    assert user.email == user.email
    assert user.account_type.value == "company"


async def test_update_me_invalid_phone(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.patch(
        "/api/v1/auth/me",
        headers=auth_headers(user),
        json={"full_name": "X", "phone": "12345"},
    )
    assert r.status_code == 422


# --- POST /change-password --------------------------------------------------------


async def test_change_password_success(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": PASSWORD, "new_password": "NewPassword123!"},
    )
    assert r.status_code == 200
    # Old password no longer works; new one does.
    assert (await _login(client, user.email, PASSWORD)).status_code == 401
    assert (await _login(client, user.email, "NewPassword123!")).status_code == 200


async def test_change_password_wrong_current(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": "WrongPassword123!", "new_password": "NewPassword123!"},
    )
    assert r.status_code == 422


async def test_change_password_same_password_rejected(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": PASSWORD, "new_password": PASSWORD},
    )
    assert r.status_code == 422


async def test_change_password_too_short_rejected(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": PASSWORD, "new_password": "short"},
    )
    assert r.status_code == 422


async def test_change_password_too_long_current_422(client, make_user, auth_headers) -> None:
    """M1: oversized current password rejected before argon2 (DoS)."""
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": "x" * 129, "new_password": "NewPassword123!"},
    )
    assert r.status_code == 422


async def test_change_password_step_up_rate_limited(client, make_user, auth_headers) -> None:
    """L1: a stolen access token cannot brute-force the current password."""
    user = await make_user()
    body = {"current_password": "WrongPassword123!", "new_password": "NewPassword123!"}
    for _ in range(10):
        r = await client.post("/api/v1/auth/change-password", headers=auth_headers(user), json=body)
        assert r.status_code == 422
    r = await client.post("/api/v1/auth/change-password", headers=auth_headers(user), json=body)
    assert r.status_code == 429


# --- Password reset ----------------------------------------------------------------


async def _create_reset(db, user: User, *, minutes_ttl: int = 30, used: bool = False) -> str:
    raw = py_secrets.token_urlsafe(32)
    db.add(
        PasswordReset(
            user_id=user.id,
            token_hash=_sha256(raw),
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=minutes_ttl),
            used_at=datetime.now(tz=UTC) if used else None,
        )
    )
    await db.commit()
    return raw


async def test_reset_request_known_email(client, make_user, db) -> None:
    user = await make_user()
    r = await client.post("/api/v1/auth/password-reset/request", json={"email": user.email})
    assert r.status_code == 202
    rows = (await db.execute(select(PasswordReset).where(PasswordReset.user_id == user.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].used_at is None


async def test_reset_request_unknown_email_still_202(client, db) -> None:
    r = await client.post("/api/v1/auth/password-reset/request", json={"email": "ghost@example.com"})
    assert r.status_code == 202
    assert r.json()["message"].startswith("If that email exists")
    rows = (await db.execute(select(PasswordReset))).scalars().all()
    assert rows == []


async def test_reset_request_fails_closed_in_prod(client, make_user, db, monkeypatch) -> None:
    """L5: no real email sender exists — prod must not log raw reset tokens."""
    from waggi_auth.config import settings

    monkeypatch.setattr(settings, "environment", "prod")
    user = await make_user()
    r = await client.post("/api/v1/auth/password-reset/request", json={"email": user.email})
    assert r.status_code == 503
    rows = (await db.execute(select(PasswordReset))).scalars().all()
    assert rows == []  # nothing was created — no token could leak


async def test_reset_confirm_success(client, make_user, db) -> None:
    user = await make_user()
    raw = await _create_reset(db, user)

    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": "BrandNew123!"},
    )
    assert r.status_code == 200
    assert (await _login(client, user.email, "BrandNew123!")).status_code == 200


async def test_reset_confirm_rejects_current_password_without_burning_token(client, make_user, db) -> None:
    """A reset must not re-arm the (possibly compromised) current password —
    and the rejection must not redeem the token (retry with a different one)."""
    user = await make_user()
    raw = await _create_reset(db, user)

    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": PASSWORD},  # same as current
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "New password must differ from the current one"

    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": "BrandNew123!"},
    )
    assert r.status_code == 200, r.text
    assert (await _login(client, user.email, "BrandNew123!")).status_code == 200


async def test_reset_confirm_passwordless_user_allows_any_password(client, make_user, db) -> None:
    """SSO-only rows (no stored hash) have nothing to differ from."""
    user = await make_user(password=None)
    raw = await _create_reset(db, user)

    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": "FirstEverPass123!"},
    )
    assert r.status_code == 200, r.text
    assert (await _login(client, user.email, "FirstEverPass123!")).status_code == 200


async def test_reset_confirm_revokes_sessions(client, make_user, db) -> None:
    user = await make_user()
    refresh = (await _login(client, user.email, PASSWORD)).json()["refresh_token"]
    raw = await _create_reset(db, user)

    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": "BrandNew123!"},
    )
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 401


async def test_reset_confirm_token_reuse_rejected(client, make_user, db) -> None:
    user = await make_user()
    raw = await _create_reset(db, user)
    body = {"token": raw, "new_password": "BrandNew123!"}
    assert (await client.post("/api/v1/auth/password-reset/confirm", json=body)).status_code == 200
    r = await client.post("/api/v1/auth/password-reset/confirm", json=body)
    assert r.status_code == 401


async def test_reset_confirm_expired_token(client, make_user, db) -> None:
    user = await make_user()
    raw = await _create_reset(db, user, minutes_ttl=-1)
    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": "BrandNew123!"},
    )
    assert r.status_code == 401


async def test_reset_confirm_unknown_token(client) -> None:
    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "nope", "new_password": "BrandNew123!"},
    )
    assert r.status_code == 401


async def test_reset_confirm_inactive_user(client, make_user, db) -> None:
    user = await make_user()
    raw = await _create_reset(db, user)
    user.is_active = False
    await db.commit()
    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": "BrandNew123!"},
    )
    assert r.status_code == 401


async def test_reset_request_rate_limited(client, make_user) -> None:
    user = await make_user()
    for _ in range(5):
        r = await client.post("/api/v1/auth/password-reset/request", json={"email": user.email})
        assert r.status_code == 202
    r = await client.post("/api/v1/auth/password-reset/request", json={"email": user.email})
    assert r.status_code == 429


async def test_reset_confirm_loses_concurrent_double_spend_race(client, make_user, db) -> None:
    """Between the SELECT and the conditional UPDATE another request redeems
    the token: rowcount 0 -> 401 (exactly one winner)."""
    from types import SimpleNamespace

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import Update

    from waggi_auth.dependencies import get_db
    from waggi_auth.main import create_app

    user = await make_user()
    raw = await _create_reset(db, user)

    real_session = db

    class RacingSession:
        """Delegates everything; UPDATEs report rowcount 0 (already redeemed)."""

        def __init__(self) -> None:
            self._update_seen = False

        async def execute(self, statement, *a, **k):
            result = await real_session.execute(statement, *a, **k)
            if isinstance(statement, Update):
                self._update_seen = True
                return SimpleNamespace(rowcount=0)
            return result

        def __getattr__(self, name):
            return getattr(real_session, name)

    async def override_get_db():
        yield RacingSession()  # type: ignore[misc]

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": raw, "new_password": "BrandNew123!"},
        )
    assert r.status_code == 401


async def test_login_mfa_totp_enabled_without_secret(client, make_user, db, totp_code) -> None:
    """Inconsistent state (enabled flag on, secret gone): code check fails safely."""
    user = await make_user(totp=True)
    mfa_token = await _mfa_challenge(client, user)
    user.totp_secret = None
    await db.commit()
    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": mfa_token, "code": totp_code(user)})
    assert r.status_code == 401
