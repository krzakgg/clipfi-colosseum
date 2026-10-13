"""Tests for waggi_auth.security.totp: secret encryption + code helpers."""

from __future__ import annotations

import hashlib
import re

import pytest

from waggi_auth.config import settings
from waggi_auth.security.totp import (
    BACKUP_CODE_COUNT,
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_backup_codes,
    hash_backup_code,
    hash_backup_codes,
    match_backup_code,
)


def _alphabet_regex() -> re.Pattern[str]:
    # XXXX-XXXX, 8 chars from the 31-symbol unambiguous alphabet (no 0/O/1/I/L).
    return re.compile(r"[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}")


async def test_totp_secret_encryption_roundtrip() -> None:
    secret = "JBSWY3DPEHPK3PXP"
    encrypted = encrypt_totp_secret(secret)
    assert encrypted != secret
    assert decrypt_totp_secret(encrypted) == secret


async def test_totp_encryption_requires_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "totp_encryption_key", "")
    with pytest.raises(RuntimeError, match="totp_encryption_key"):
        encrypt_totp_secret("JBSWY3DPEHPK3PXP")


def test_backup_codes_format() -> None:
    """XXXX-XXXX: 8 chars, unambiguous alphabet, all unique."""
    codes = generate_backup_codes()
    assert len(codes) == BACKUP_CODE_COUNT
    for code in codes:
        assert _alphabet_regex().fullmatch(code), code
    assert len(set(codes)) == len(codes)


def test_backup_codes_peppered_not_plain_sha256() -> None:
    """R3-L2: ~40 bits is only safe because the stored hash is peppered — a
    DB dump alone must not be enough to brute-force codes offline."""
    code = generate_backup_codes()[0]
    assert hash_backup_code(code) != hashlib.sha256(code.encode()).hexdigest()
    # deterministic (same pepper for the process)
    assert hash_backup_code(code) == hash_backup_code(code)


def test_match_backup_code_accepts_current_and_legacy() -> None:
    """Peppered codes match their stored hash; pre-pepper (unsalted sha256)
    codes keep verifying until regenerated."""
    code = "AB2C-9DEF"
    stored = hash_backup_codes([code])
    assert match_backup_code(stored, code) == hash_backup_code(code)

    legacy_stored = [hashlib.sha256(code.encode()).hexdigest()]
    assert match_backup_code(legacy_stored, code) == legacy_stored[0]


def test_match_backup_code_rejects_wrong_code() -> None:
    code = generate_backup_codes()[0]
    stored = hash_backup_codes([code])
    assert match_backup_code(stored, "WRONG-CODE") is None
    assert match_backup_code([], code) is None
