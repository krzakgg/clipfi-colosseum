"""Endpoint tests for the 2FA (TOTP) router: setup, verify, disable, regenerate."""

from __future__ import annotations

import pyotp
from tests.auth.conftest import PASSWORD

from waggi_auth.security.totp import decrypt_totp_secret, hash_backup_codes


async def _enabled_user(client, make_user, auth_headers, *, backup_codes=None):
    """Run setup + verify so the user ends with TOTP enabled. Returns codes."""
    user = await make_user()
    r = await client.post("/api/v1/auth/2fa/setup", headers=auth_headers(user), json={"password": PASSWORD})
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = await client.post(
        "/api/v1/auth/2fa/verify",
        headers=auth_headers(user),
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200, r.text
    codes = r.json()["backup_codes"]
    return user, secret, codes


# --- POST /2fa/setup -------------------------------------------------------------


async def test_setup_returns_secret_and_uri(client, make_user, auth_headers, db) -> None:
    user = await make_user()
    r = await client.post("/api/v1/auth/2fa/setup", headers=auth_headers(user), json={"password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    secret = body["secret"]
    assert len(secret) == 32
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert "Waggi" in body["otpauth_uri"]
    from urllib.parse import quote

    assert quote(user.email) in body["otpauth_uri"]  # pyotp URL-encodes the name

    await db.refresh(user)
    assert user.totp_secret is not None
    assert user.totp_secret != secret  # stored encrypted
    assert decrypt_totp_secret(user.totp_secret) == secret
    assert user.totp_enabled is False  # not enabled until verified


async def test_setup_requires_auth(client) -> None:
    r = await client.post("/api/v1/auth/2fa/setup")
    assert r.status_code == 401


async def test_setup_rejects_wrong_password(client, make_user, auth_headers, db) -> None:
    """Step-up: a stolen access token must not enroll an attacker's authenticator."""
    user = await make_user()
    r = await client.post("/api/v1/auth/2fa/setup", headers=auth_headers(user), json={"password": "WrongPassword123!"})
    assert r.status_code == 422
    await db.refresh(user)
    assert user.totp_secret is None  # nothing was written


async def test_setup_requires_password_field(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post("/api/v1/auth/2fa/setup", headers=auth_headers(user))
    assert r.status_code == 422


async def test_setup_conflict_when_already_enabled(client, make_user, auth_headers) -> None:
    user, _, _ = await _enabled_user(client, make_user, auth_headers)
    r = await client.post("/api/v1/auth/2fa/setup", headers=auth_headers(user), json={"password": PASSWORD})
    assert r.status_code == 409


# --- POST /2fa/verify ---------------------------------------------------------------


async def test_verify_enables_and_returns_backup_codes(client, make_user, auth_headers, db) -> None:
    user, _secret, codes = await _enabled_user(client, make_user, auth_headers)
    await db.refresh(user)  # the app session committed; refresh our copy
    assert user.totp_enabled is True
    assert len(codes) == 8
    for code in codes:
        assert len(code) == 9 and code[4] == "-"  # XXXX-XXXX
    assert user.totp_backup_codes_hashed == hash_backup_codes(codes)


async def test_verify_rejects_wrong_code(client, make_user, auth_headers) -> None:
    user = await make_user()
    await client.post("/api/v1/auth/2fa/setup", headers=auth_headers(user), json={"password": PASSWORD})
    wrong = pyotp.TOTP(pyotp.random_base32()).now()
    r = await client.post("/api/v1/auth/2fa/verify", headers=auth_headers(user), json={"code": wrong})
    assert r.status_code == 422


async def test_verify_without_pending_setup(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post("/api/v1/auth/2fa/verify", headers=auth_headers(user), json={"code": "123456"})
    assert r.status_code == 422


async def test_verify_conflict_when_already_enabled(client, make_user, auth_headers) -> None:
    user, _, _ = await _enabled_user(client, make_user, auth_headers)
    r = await client.post(
        "/api/v1/auth/2fa/verify",
        headers=auth_headers(user),
        json={"code": pyotp.TOTP(pyotp.random_base32()).now()},
    )
    assert r.status_code == 409


async def test_verify_rejects_non_numeric_code(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post("/api/v1/auth/2fa/verify", headers=auth_headers(user), json={"code": "abcdef"})
    assert r.status_code == 422


async def test_verify_rate_limited(client, make_user, auth_headers) -> None:
    user = await make_user()
    await client.post("/api/v1/auth/2fa/setup", headers=auth_headers(user), json={"password": PASSWORD})
    wrong = pyotp.TOTP(pyotp.random_base32()).now()
    for _ in range(10):
        r = await client.post("/api/v1/auth/2fa/verify", headers=auth_headers(user), json={"code": wrong})
        assert r.status_code == 422
    r = await client.post("/api/v1/auth/2fa/verify", headers=auth_headers(user), json={"code": "123456"})
    assert r.status_code == 429


# --- POST /2fa/disable -------------------------------------------------------------


async def test_disable_with_totp_code(client, make_user, auth_headers, db) -> None:
    user, secret, _codes = await _enabled_user(client, make_user, auth_headers)
    code = pyotp.TOTP(secret).now()
    r = await client.post(
        "/api/v1/auth/2fa/disable",
        headers=auth_headers(user),
        json={"password": PASSWORD, "code": code},
    )
    assert r.status_code == 200
    await db.refresh(user)
    assert user.totp_enabled is False
    assert user.totp_secret is None
    assert user.totp_backup_codes_hashed == []


async def test_disable_with_backup_code(client, make_user, auth_headers, db) -> None:
    """Lost authenticator? A backup code + password still lets the user disable."""
    user, _secret, codes = await _enabled_user(client, make_user, auth_headers)
    r = await client.post(
        "/api/v1/auth/2fa/disable",
        headers=auth_headers(user),
        json={"password": PASSWORD, "backup_code": codes[0]},
    )
    assert r.status_code == 200
    await db.refresh(user)
    assert user.totp_enabled is False

    # ...and plain password login works again (no MFA challenge).
    r = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert r.status_code == 200
    assert "access_token" in r.json()


async def test_disable_rejects_wrong_backup_code(client, make_user, auth_headers) -> None:
    user, _, _ = await _enabled_user(client, make_user, auth_headers)
    r = await client.post(
        "/api/v1/auth/2fa/disable",
        headers=auth_headers(user),
        json={"password": PASSWORD, "backup_code": "XXXX-XXXX"},
    )
    assert r.status_code == 422


async def test_disable_rejects_wrong_password(client, make_user, auth_headers) -> None:
    user, _, _ = await _enabled_user(client, make_user, auth_headers)
    r = await client.post(
        "/api/v1/auth/2fa/disable",
        headers=auth_headers(user),
        json={"password": "WrongPassword123!", "code": "123456"},
    )
    assert r.status_code == 422


async def test_disable_rejects_wrong_code(client, make_user, auth_headers) -> None:
    user, _, _ = await _enabled_user(client, make_user, auth_headers)
    wrong = pyotp.TOTP(pyotp.random_base32()).now()
    r = await client.post(
        "/api/v1/auth/2fa/disable",
        headers=auth_headers(user),
        json={"password": PASSWORD, "code": wrong},
    )
    assert r.status_code == 422


async def test_disable_requires_a_second_factor(client, make_user, auth_headers) -> None:
    user, _, _ = await _enabled_user(client, make_user, auth_headers)
    r = await client.post("/api/v1/auth/2fa/disable", headers=auth_headers(user), json={"password": PASSWORD})
    assert r.status_code == 422


async def test_disable_password_too_long_422(client, make_user, auth_headers) -> None:
    """M1: oversized password rejected by validation before argon2 runs."""
    user, _, _ = await _enabled_user(client, make_user, auth_headers)
    r = await client.post(
        "/api/v1/auth/2fa/disable",
        headers=auth_headers(user),
        json={"password": "x" * 129, "code": "123456"},
    )
    assert r.status_code == 422


async def test_disable_conflict_when_not_enabled(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/2fa/disable",
        headers=auth_headers(user),
        json={"password": PASSWORD, "code": "123456"},
    )
    assert r.status_code == 409


async def test_disable_rate_limited(client, make_user, auth_headers) -> None:
    user, _, _ = await _enabled_user(client, make_user, auth_headers)
    body = {"password": PASSWORD, "backup_code": "XXXX-XXXX"}
    for _ in range(10):
        r = await client.post("/api/v1/auth/2fa/disable", headers=auth_headers(user), json=body)
        assert r.status_code == 422
    r = await client.post("/api/v1/auth/2fa/disable", headers=auth_headers(user), json=body)
    assert r.status_code == 429


# --- POST /2fa/backup/regenerate -----------------------------------------------------


async def test_regenerate_invalidates_old_codes(client, make_user, auth_headers, db) -> None:
    user, _, old_codes = await _enabled_user(client, make_user, auth_headers)
    r = await client.post(
        "/api/v1/auth/2fa/backup/regenerate",
        headers=auth_headers(user),
        json={"password": PASSWORD},
    )
    assert r.status_code == 200
    new_codes = r.json()["backup_codes"]
    assert len(new_codes) == 8
    assert set(new_codes).isdisjoint(old_codes)
    await db.refresh(user)
    assert user.totp_backup_codes_hashed == hash_backup_codes(new_codes)


async def test_regenerate_conflict_when_not_enabled(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/2fa/backup/regenerate",
        headers=auth_headers(user),
        json={"password": PASSWORD},
    )
    assert r.status_code == 409


async def test_regenerate_rejects_wrong_password(client, make_user, auth_headers) -> None:
    """Step-up: live backup codes must not be handed to a stolen access token."""
    user, _, _ = await _enabled_user(client, make_user, auth_headers)
    r = await client.post(
        "/api/v1/auth/2fa/backup/regenerate",
        headers=auth_headers(user),
        json={"password": "WrongPassword123!"},
    )
    assert r.status_code == 422


async def test_regenerate_rate_limited_via_step_up(client, make_user, auth_headers) -> None:
    """The shared step-up bucket rate-limits password guesses on regenerate."""
    user, _, _ = await _enabled_user(client, make_user, auth_headers)  # 1 step-up hit (setup)
    body = {"password": "WrongPassword123!"}
    for _ in range(9):  # 9 more -> bucket (10/min) exhausted
        r = await client.post("/api/v1/auth/2fa/backup/regenerate", headers=auth_headers(user), json=body)
        assert r.status_code == 422
    r = await client.post("/api/v1/auth/2fa/backup/regenerate", headers=auth_headers(user), json=body)
    assert r.status_code == 429


# --- GET /2fa (status) ---------------------------------------------------------------


async def test_status_requires_auth(client) -> None:
    r = await client.get("/api/v1/auth/2fa")
    assert r.status_code == 401


async def test_status_disabled_user(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.get("/api/v1/auth/2fa", headers=auth_headers(user))
    assert r.status_code == 200
    assert r.json() == {"totp_enabled": False, "backup_codes_remaining": 0}


async def test_status_reports_remaining_codes_and_tracks_redemption(client, make_user, auth_headers) -> None:
    """Count starts at 8 and drops as codes are redeemed through the login flow."""
    user, _, codes = await _enabled_user(client, make_user, auth_headers)

    r = await client.get("/api/v1/auth/2fa", headers=auth_headers(user))
    assert r.status_code == 200
    assert r.json() == {"totp_enabled": True, "backup_codes_remaining": 8}

    # Redeem one backup code via the MFA login step.
    login = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    r = await client.post(
        "/api/v1/auth/login/mfa",
        json={"mfa_token": login.json()["mfa_token"], "backup_code": codes[0]},
    )
    assert r.status_code == 200, r.text

    r = await client.get("/api/v1/auth/2fa", headers=auth_headers(user))
    assert r.json() == {"totp_enabled": True, "backup_codes_remaining": 7}


async def test_status_after_disable(client, make_user, auth_headers) -> None:
    user, secret, _ = await _enabled_user(client, make_user, auth_headers)
    r = await client.post(
        "/api/v1/auth/2fa/disable",
        headers=auth_headers(user),
        json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200, r.text

    r = await client.get("/api/v1/auth/2fa", headers=auth_headers(user))
    assert r.json() == {"totp_enabled": False, "backup_codes_remaining": 0}


# --- end-to-end privileged flow --------------------------------------------------------


async def test_totp_user_login_requires_mfa_then_succeeds(client, make_user, auth_headers) -> None:
    user, secret, _codes = await _enabled_user(client, make_user, auth_headers)
    r = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert r.json().get("mfa_required") is True
    mfa_token = r.json()["mfa_token"]

    r = await client.post("/api/v1/auth/login/mfa", json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200
    assert "access_token" in r.json()
