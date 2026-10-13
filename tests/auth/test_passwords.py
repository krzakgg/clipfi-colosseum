"""waggi_shared.passwords (argon2-cffi) — hashing, verification, passlib compat.

Lives in auth's suite because auth is the identity service and owns every
hash-producing flow; there is no separate shared test tree.
"""

from __future__ import annotations

from argon2 import PasswordHasher

from waggi_shared.passwords import hash_password, needs_rehash, verify_password

# Genuine output of passlib 1.7.4 (`CryptContext(schemes=["argon2"])`, the
# exact setup this codebase used until Aug 2026) for the password below.
# Regression guard: argon2-cffi must keep reading passlib's format so hashes
# written before the migration stay verifiable (no data migration exists).
_PASSLIB_HASH = "$argon2id$v=19$m=65536,t=3,p=4$I2Ts3dt7L6V07p2Tci6FEA$ZLaEEIzQBMDNiJS0Wr9OD5EK/8eNDJmIamvnJvlkD8g"
_PASSLIB_PASSWORD = "passlib-era-passw0rd"


def test_hash_and_verify_roundtrip() -> None:
    h = hash_password("s3cret-password")
    assert h.startswith("$argon2id$")
    assert verify_password("s3cret-password", h) is True
    assert verify_password("wrong", h) is False


def test_verify_password_none_hash() -> None:
    """SSO-only users have password_hash = NULL -> verify must fail, not raise."""
    assert verify_password("x", None) is False


def test_verify_password_empty_hash() -> None:
    assert verify_password("x", "") is False


def test_verify_password_malformed_hash() -> None:
    """A corrupt stored value must not 500 the login path."""
    assert verify_password("x", "not-a-hash") is False


def test_verify_passlib_generated_hash() -> None:
    assert verify_password(_PASSLIB_PASSWORD, _PASSLIB_HASH) is True
    assert verify_password("wrong", _PASSLIB_HASH) is False


def test_needs_rehash_flags_weak_params() -> None:
    """Hashes with weaker parameters than current defaults are flagged for upgrade."""
    weak = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1).hash("pw")
    assert needs_rehash(weak) is True
    assert needs_rehash(hash_password("pw")) is False


def test_needs_rehash_passlib_hash_current_params() -> None:
    """passlib delegating to argon2-cffi 23.x defaults already matches -> no rehash needed."""
    assert needs_rehash(_PASSLIB_HASH) is False
