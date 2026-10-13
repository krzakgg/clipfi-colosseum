"""Password-policy tests: the shared module's behavior plus enforcement at
every endpoint that SETS a password (change-password, setup-password,
password-reset/confirm).

The load-bearing property under test: a policy rejection must never burn
single-use state — the setup-token jti and the reset-token used_at are
consumed only AFTER the password passes the policy, so a user who submits
something weak can retry with the SAME token.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from tests.auth.conftest import PASSWORD

from waggi_auth.config import settings
from waggi_auth.models import PasswordReset, User
from waggi_shared.password_policy import (
    PASSWORD_MAX_LENGTH,
    password_policy_violation,
    personal_tokens,
)

# --- shared literals -----------------------------------------------------------

# Strong: satisfies every rule (length, class minimums, no personal tokens).
STRONG = "Fjord-Lantern-Quartz-9"
STRONG_ALT = "Gravel-Nebulae-Outline-3"
# Common-but-compliant: dictionary words that meet every remaining rule —
# accepted since commonality (zxcvbn) scoring was removed from the policy;
# the guard tests below pin that acceptance.
# NB: never reuse PASSWORD ("Password123!") as a *new* password in tests —
# the must_differ / temp-reuse checks fire before the policy.
COMMON_COMPLIANT = "Welcome123"  # classes OK
COMMON_COMPLIANT_ALT = "Monkey123"  # classes OK
# Contains a personal token of the default test user (user@example.com /
# "Test User" -> tokens ["test", "user"]).
PERSONAL_FOR_DEFAULT_USER = "MyUserPass-2026!"  # contains "user"

_PROBLEM_TYPE = "https://errors.waggi.local/"


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
    return body["setup_token"]


async def _create_reset(db, user: User, *, minutes_ttl: int = 30) -> str:
    raw = "reset-" + hashlib.sha256(user.id.bytes).hexdigest()[:16]
    db.add(
        PasswordReset(
            user_id=user.id,
            token_hash=_sha256(raw),
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=minutes_ttl),
        )
    )
    await db.commit()
    return raw


# --- unit: password_policy_violation -------------------------------------------


def test_strong_passphrases_pass() -> None:
    for pw in (STRONG, STRONG_ALT, "correct horse battery staple", "Trampoline-Copperhead-42!"):
        assert password_policy_violation(pw, email="jan@example.com", full_name="Jan Nowak") is None


def test_common_passwords_meeting_other_rules_pass() -> None:
    # zxcvbn scoring is gone: a dictionary word that satisfies length,
    # class minimums and the personal check is accepted — strength now
    # comes from length + composition, not commonality scoring.
    for pw in (COMMON_COMPLIANT, COMMON_COMPLIANT_ALT, "12345678", "iloveyou123!", "Password123!"):
        assert password_policy_violation(pw, email="jan@example.com", full_name="Jan Nowak") is None


def test_short_password_rejected() -> None:
    # Defensive: request schemas reject this first; the module is standalone-safe.
    assert password_policy_violation("short1", email=None, full_name=None) == "password_too_short"


def test_personal_email_local_part_rejected() -> None:
    assert (
        password_policy_violation("Kowalska2026!", email="anna.kowalska@example.com", full_name=None)
        == "password_contains_personal"
    )
    # The domain part is NOT personal ("example" here) — only the local part.
    assert password_policy_violation("Example-Fjord-Lantern-9", email="anna@example.com", full_name=None) is None


def test_personal_name_rejected() -> None:
    assert (
        password_policy_violation("anna-lantern-77!", email="x@example.com", full_name="Anna Kowalska")
        == "password_contains_personal"
    )


def test_personal_match_is_case_insensitive_and_folds_diacritics() -> None:
    # Name has diacritics, password is plain ASCII.
    assert (
        password_policy_violation("lukasz-pear-cider-4", email="x@example.com", full_name="Łukasz Zieliński")
        == "password_contains_personal"
    )
    # Password has the diacritic, name is ASCII (ł is the letter NFD cannot decompose).
    assert (
        password_policy_violation("Łukasz2026!q", email="x@example.com", full_name="Lukasz Zielinski")
        == "password_contains_personal"
    )
    # Unrelated strong passphrase with diacritics passes.
    assert password_policy_violation("Źrebak-Cedry-Porazka-7", email="x@example.com", full_name="Łukasz Zieliński") is None


def test_personal_token_reported_even_for_weak_passwords() -> None:
    # A weak password that ALSO contains a personal token reports the personal
    # code (deterministic, more actionable message).
    assert password_policy_violation("user1234", email="user@example.com", full_name=None) == "password_contains_personal"


def test_personal_tokens_extraction() -> None:
    # Email local part + name words, deduplicated, 3+ chars only.
    assert personal_tokens("jan.kowalski@example.com", "Jan Kowalski Jr") == ["jan", "kowalski"]
    # Email None / name None are both fine.
    assert personal_tokens(None, "Anna Kowalska") == ["anna", "kowalska"]
    assert personal_tokens("anna.k@example.com", None) == ["anna"]
    assert personal_tokens(None, None) == []


def test_suite_password_literals_pass_policy() -> None:
    """Guard: every literal the suite uses as a *new* password must keep
    passing the policy (checked against make_user defaults), or unrelated
    tests break mysteriously."""
    from test_setup_password import NEW_PASSWORD

    # PASSWORD is never a *new* password in passing tests (the must_differ
    # check fires first) — it is policy-compliant now, which is fine:
    assert password_policy_violation(PASSWORD, email="user@example.com", full_name="Test User") is None
    assert password_policy_violation(NEW_PASSWORD, email="user@example.com", full_name="Test User") is None
    for literal in ("BrandNew123!", "NewPassword123!", "FirstEverPass123!", "DifferentPass456!", "ChangeMe123!"):
        assert password_policy_violation(literal, email="user@example.com", full_name="Test User") is None


# --- endpoint: POST /change-password --------------------------------------------


async def test_change_password_accepts_common_but_compliant(client, make_user, auth_headers) -> None:
    # zxcvbn scoring removed: "Welcome123" meets length + class minimums
    # and carries no personal token, so the endpoint accepts it.
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": PASSWORD, "new_password": COMMON_COMPLIANT},
    )
    assert r.status_code == 200, r.text
    assert (await _login(client, user.email, COMMON_COMPLIANT)).status_code == 200


async def test_change_password_rejects_personal(client, make_user, auth_headers) -> None:
    user = await make_user()  # user@example.com / "Test User"

    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": PASSWORD, "new_password": PERSONAL_FOR_DEFAULT_USER},
    )
    assert r.status_code == 422, r.text
    assert r.json()["type"] == f"{_PROBLEM_TYPE}password_contains_personal"


async def test_change_password_accepts_strong(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": PASSWORD, "new_password": STRONG},
    )
    assert r.status_code == 200, r.text
    assert (await _login(client, user.email, STRONG)).status_code == 200


# --- endpoint: POST /setup-password ---------------------------------------------


async def test_setup_password_rejects_personal(client, make_user) -> None:
    user = await make_user(must_set_password=True)  # user@example.com / "Test User"
    token = await _gated_setup_token(client, user)

    r = await client.post(
        "/api/v1/auth/setup-password",
        json={"setup_token": token, "new_password": PERSONAL_FOR_DEFAULT_USER},
    )
    assert r.status_code == 422, r.text
    assert r.json()["type"] == f"{_PROBLEM_TYPE}password_contains_personal"


# --- endpoint: POST /password-reset/confirm -------------------------------------


async def test_reset_confirm_class_rejection_does_not_burn_token(client, make_user, db) -> None:
    """Policy rejection must precede the used_at redemption UPDATE: retry
    with the SAME reset token after a non-compliant attempt succeeds."""
    user = await make_user()
    raw = await _create_reset(db, user)

    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": "falconry-zebra-plum-77"},  # no uppercase (product default min: 1)
    )
    assert r.status_code == 422, r.text
    assert r.json()["type"] == f"{_PROBLEM_TYPE}password_character_requirements"

    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": STRONG_ALT},
    )
    assert r.status_code == 200, r.text
    assert (await _login(client, user.email, STRONG_ALT)).status_code == 200


async def test_reset_confirm_rejects_personal(client, make_user, db) -> None:
    user = await make_user()
    raw = await _create_reset(db, user)

    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw, "new_password": PERSONAL_FOR_DEFAULT_USER},
    )
    assert r.status_code == 422, r.text
    assert r.json()["type"] == f"{_PROBLEM_TYPE}password_contains_personal"


# --- too long (fixed max, schema-enforced) --------------------------------------


def _long_strong_passphrase(length: int) -> str:
    """A long, genuinely strong passphrase of exactly `length` chars.

    Upper+digit live INSIDE the first 64 chars so slices also satisfy the
    product class minimums (upper/lower/digit = 1) in endpoint tests.
    """
    base = "Fjord-Lantern-Quartz-9-Gravel-Nebulae-Trampoline-Copperhead-Marble-Sledge-Otter"
    assert len(base) >= length >= 20
    return base[:length]


def test_too_long_password_rejected_not_crash() -> None:
    """Passwords past the fixed max (64) get a clean violation code — never
    an escaping exception. The request schemas reject >64 first (same
    bound); this is the engine-level guarantee."""
    over = _long_strong_passphrase(PASSWORD_MAX_LENGTH + 1)
    assert len(over) == PASSWORD_MAX_LENGTH + 1
    assert password_policy_violation(over, email="jan@example.com", full_name="Jan Nowak") == "password_too_long"


def test_default_max_boundary() -> None:
    """The max is fixed at 64: exactly 64 passes, 65 is too long."""
    assert password_policy_violation(_long_strong_passphrase(64)) is None
    assert password_policy_violation(_long_strong_passphrase(65)) == "password_too_long"


async def test_change_password_rejects_too_long_with_clean_422(client, make_user, auth_headers, db) -> None:
    """Regression: a password past the fixed max (64) is rejected by the
    request schema itself — a clean 422, never a 500."""
    user = await make_user()
    old_hash = user.password_hash

    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": PASSWORD, "new_password": _long_strong_passphrase(65)},
    )
    assert r.status_code == 422, r.text
    # FastAPI schema validation (detail is a list), not a policy code —
    # the schema max now equals the policy max (64).
    assert isinstance(r.json()["detail"], list)

    await db.refresh(user)
    assert user.password_hash == old_hash  # nothing changed


async def test_change_password_accepts_max_length_passphrase(client, make_user, auth_headers) -> None:
    user = await make_user()
    new_pw = _long_strong_passphrase(64)  # exactly at the fixed max
    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": PASSWORD, "new_password": new_pw},
    )
    assert r.status_code == 200, r.text
    assert (await _login(client, user.email, new_pw)).status_code == 200


# --- GET /password-policy (public, config-driven) --------------------------------


async def test_password_policy_endpoint_returns_defaults(client) -> None:
    r = await client.get("/api/v1/auth/password-policy")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "min_length": 8,
        "min_uppercase": 1,
        "min_lowercase": 1,
        "min_digit": 1,
        "min_symbol": 0,
    }


async def test_password_policy_endpoint_reflects_config(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "password_min_length", 12)
    monkeypatch.setattr(settings, "password_min_uppercase", 1)
    monkeypatch.setattr(settings, "password_min_digit", 2)

    r = await client.get("/api/v1/auth/password-policy")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "min_length": 12,
        "min_uppercase": 1,
        "min_lowercase": 1,  # not monkeypatched — stays at the default
        "min_digit": 2,
        "min_symbol": 0,
    }


async def test_enforcement_uses_configured_bounds(client, make_user, auth_headers, monkeypatch) -> None:
    monkeypatch.setattr(settings, "password_min_length", 12)
    user = await make_user()

    # 10 chars >= schema min 8, but below the configured 12 → password_too_short.
    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": PASSWORD, "new_password": "Falconry-99"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["type"] == f"{_PROBLEM_TYPE}password_too_short"


def test_settings_validation_rejects_impossible_policy(monkeypatch) -> None:
    monkeypatch.setattr(settings, "password_min_length", 100)  # beyond the fixed max (64)
    with pytest.raises(RuntimeError, match="Invalid password policy config"):
        settings.validated_password_policy()

    monkeypatch.setattr(settings, "password_min_length", 8)
    monkeypatch.setattr(settings, "password_min_uppercase", -1)
    with pytest.raises(RuntimeError, match="must be >= 0"):
        settings.validated_password_policy()

    monkeypatch.setattr(settings, "password_min_uppercase", 6)
    monkeypatch.setattr(settings, "password_min_lowercase", 6)  # 12 > min_length 8: unsatisfiable
    with pytest.raises(RuntimeError, match="no password could satisfy"):
        settings.validated_password_policy()


# --- character-class minimums -----------------------------------------------------


def test_class_minimums_default_to_off() -> None:
    # Library defaults (all 0): a single-class password passes the class check.
    assert password_policy_violation("falconry-zebra-plum-77") is None


def test_class_minimums_enforced() -> None:
    assert password_policy_violation("falconry-zebra-plum-77", min_uppercase=1) == "password_character_requirements"
    assert password_policy_violation("Falconry-zebra-plum-77", min_uppercase=1) is None
    assert password_policy_violation("Falconry-zebra-plum-7", min_digit=2) == "password_character_requirements"
    assert password_policy_violation("Falconry-zebra-plum-77", min_digit=2) is None
    assert password_policy_violation("FalconryZebraPlum77", min_symbol=1) == "password_character_requirements"
    assert password_policy_violation("Falconry-zebra-plum-77", min_symbol=1) is None
    assert password_policy_violation("falconry-zebra-plum-77", min_lowercase=1) is None


def test_class_minimums_unicode_aware() -> None:
    # Polish diacritics count as cased letters, not symbols.
    assert password_policy_violation("Źrebak-cedry-porazka-7", min_uppercase=1) is None
    # No symbol anywhere (hyphen would be one).
    assert password_policy_violation("ŹrebakCedryPorazka77", min_symbol=1) == "password_character_requirements"


def test_class_check_precedes_personal_check() -> None:
    # "user1234" violates BOTH the class minimum (no uppercase) and the
    # personal check (contains "user") — the class check reports first
    # (deterministic order: length → classes → personal).
    assert (
        password_policy_violation("user1234", email="user@example.com", full_name=None, min_uppercase=1)
        == "password_character_requirements"
    )


async def test_change_password_enforces_class_minimums(client, make_user, auth_headers, monkeypatch, db) -> None:
    monkeypatch.setattr(settings, "password_min_uppercase", 1)
    user = await make_user()
    old_hash = user.password_hash

    r = await client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers(user),
        json={"current_password": PASSWORD, "new_password": "falconry-zebra-plum-77"},  # strong, no uppercase
    )
    assert r.status_code == 422, r.text
    assert r.json()["type"] == f"{_PROBLEM_TYPE}password_character_requirements"

    await db.refresh(user)
    assert user.password_hash == old_hash  # nothing changed


async def test_setup_password_class_rejection_does_not_burn_token(client, make_user, monkeypatch) -> None:
    monkeypatch.setattr(settings, "password_min_uppercase", 1)
    user = await make_user(must_set_password=True)
    token = await _gated_setup_token(client, user)

    r = await client.post(
        "/api/v1/auth/setup-password",
        json={"setup_token": token, "new_password": "falconry-zebra-plum-77"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["type"] == f"{_PROBLEM_TYPE}password_character_requirements"

    # Same token still works once the requirement is met.
    r = await client.post(
        "/api/v1/auth/setup-password",
        json={"setup_token": token, "new_password": "Falconry-zebra-plum-77"},
    )
    assert r.status_code == 200, r.text
    assert (await _login(client, user.email, "Falconry-zebra-plum-77")).status_code == 200
