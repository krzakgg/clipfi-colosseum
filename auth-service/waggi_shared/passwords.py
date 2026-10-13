"""Password hashing for waggi services (argon2-cffi, no passlib).

Uses `argon2-cffi`'s `PasswordHasher` directly. This module replaced `passlib`
(unmaintained since 2020 — its last release; it also reads the deprecated
`argon2.__version__` attribute on every hash/verify). argon2-cffi is actively
maintained and reads/writes the same self-describing PHC string format
(`$argon2id$v=19$m=...,t=...,p=...`), so hashes written by the old passlib
pipeline remain verifiable — no data migration was needed.

Hash parameters are the argon2-cffi defaults (argon2id, t=3, m=64 MiB, p=4)
and are embedded in every stored hash string. If defaults are ever raised,
`needs_rehash()` plus auth's rehash-on-successful-login upgrade old hashes
transparently.

Consumers: auth (login, change/reset password, 2FA disable), admin (worker
creation, temp-password resets) and `scripts/seed.py` — all writing the same
`auth.users.password_hash` column.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# One shared hasher instance (config + internals are reused across calls).
_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    """Hash a password with argon2 (argon2id, library defaults). Returns the PHC string to store."""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    """Verify a password against a stored argon2 hash.

    Returns False if `hashed` is None (e.g. SSO-only users with no password)
    or malformed (a corrupt stored value) instead of raising.
    """
    if not hashed:
        return False
    try:
        _hasher.verify(hashed, plain)
    except (VerificationError, InvalidHashError):
        # VerificationError covers wrong passwords (incl. VerifyMismatchError);
        # InvalidHashError covers non-PHC garbage in the password_hash column.
        return False
    return True


def needs_rehash(hashed: str) -> bool:
    """True when `hashed` was produced with weaker/different parameters than current defaults.

    Auth's login handler re-hashes transparently on successful login, so
    passlib-era or otherwise outdated hashes upgrade lazily, one login at a
    time, with no operator action.
    """
    return _hasher.check_needs_rehash(hashed)


__all__ = ["hash_password", "needs_rehash", "verify_password"]
