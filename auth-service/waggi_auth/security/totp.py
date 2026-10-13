"""TOTP 2FA helpers: secret encryption at rest, code verification, backup codes.

One home for everything TOTP-related so the login step (`routers/session.py`)
and 2FA management (`routers/mfa.py`) share the exact same logic:

- TOTP secrets are stored Fernet-encrypted (`TOTP_ENCRYPTION_KEY`).
- Code verification uses `valid_window=1` (accepts prev/current/next 30s step).
- Backup codes are `XXXX-XXXX`: 8 chars from a 31-symbol unambiguous alphabet
  (no 0/O/1/I/L) ≈ 40 bits. That alone would be brute-forceable from a DB
  dump, so codes are hashed with HMAC-SHA256 peppered by a server-side secret
  (derived from `MFA_TOKEN_SECRET`) — a leaked DB without the app secret is
  not enough to mount an offline attack. Codes of the LEGACY format (hex
  alphabet, unsalted sha256) still verify until regenerated; `match_backup_code`
  accepts both and returns the stored hash actually matched.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

import pyotp
from cryptography.fernet import Fernet

from waggi_auth.config import settings
from waggi_auth.models import User

# Number of one-time backup codes generated at enable time / regeneration.
BACKUP_CODE_COUNT = 8

# 31 unambiguous symbols (no 0/O, 1/I/L) — 8 chars ≈ 40 bits of entropy.
_BACKUP_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

# Domain-separated pepper derivation label (never use a raw secret for two purposes).
_PEPPER_LABEL = b"waggi:backup-code-pepper"


# --- TOTP secret encryption at rest (Fernet) -------------------------------


def _fernet() -> Fernet:
    key = settings.totp_encryption_key
    if not key:
        raise RuntimeError("totp_encryption_key is not set; cannot manage TOTP secrets")
    return Fernet(key.encode())


def encrypt_totp_secret(plain: str) -> str:
    """Encrypt a TOTP secret for storage. Returns the Fernet token string."""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_totp_secret(token: str) -> str:
    """Decrypt a stored TOTP secret back to the plaintext base32 secret."""
    return _fernet().decrypt(token.encode()).decode()


# --- Code verification ------------------------------------------------------


def verify_totp_for_user(user: User, code: str) -> bool:
    """Verify a 6-digit TOTP code against the user's stored (encrypted) secret."""
    if not user.totp_secret:
        return False
    secret = decrypt_totp_secret(user.totp_secret)
    return pyotp.TOTP(secret).verify(code, valid_window=1)


# --- Backup codes ------------------------------------------------------------


def generate_backup_codes() -> list[str]:
    """Generate human-friendly one-time backup codes (`XXXX-XXXX`).

    8 chars from the 31-symbol unambiguous alphabet (~40 bits). The stored
    hash is HMAC-peppered (see `hash_backup_code`), so the sub-64-bit entropy
    is NOT offline-brute-forceable from a DB dump alone.
    """
    codes: list[str] = []
    for _ in range(BACKUP_CODE_COUNT):
        raw = "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(8))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def _pepper() -> bytes:
    """Server-side pepper for backup-code hashing, derived from MFA_TOKEN_SECRET."""
    return hmac.new(settings.mfa_token_secret.encode(), _PEPPER_LABEL, hashlib.sha256).digest()


def hash_backup_code(code: str) -> str:
    """Hash ONE backup code (peppered HMAC-SHA256) for storage at generation time."""
    return hmac.new(_pepper(), code.encode(), hashlib.sha256).hexdigest()


def _legacy_hash_backup_code(code: str) -> str:
    """Pre-pepper format (unsalted sha256) — verification-only, for old codes."""
    return hashlib.sha256(code.encode()).hexdigest()


def match_backup_code(stored_hashes: list[str], code: str) -> str | None:
    """Match a submitted code against the stored hashes; return the matched hash.

    Accepts current peppered hashes and legacy unsalted-sha256 hashes (codes
    issued before the pepper). Returning the STORED hash lets callers redeem
    atomically (array_remove) regardless of which format matched. None = no
    match.
    """
    peppered = hash_backup_code(code)
    if peppered in stored_hashes:
        return peppered
    legacy = _legacy_hash_backup_code(code)
    if legacy in stored_hashes:
        return legacy
    return None


def hash_backup_codes(codes: list[str]) -> list[str]:
    """Hash backup codes for storage. Plaintext is returned to the user once."""
    return [hash_backup_code(c) for c in codes]


__all__ = [
    "BACKUP_CODE_COUNT",
    "decrypt_totp_secret",
    "encrypt_totp_secret",
    "generate_backup_codes",
    "hash_backup_code",
    "hash_backup_codes",
    "match_backup_code",
    "verify_totp_for_user",
]
