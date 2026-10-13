"""Redis-backed single-use gates for the MFA login step.

Two SET-NX-EX keys, both consumed at `/login/mfa`:

- **MFA challenge tokens are single-use.** After the TOTP/backup code validates,
  the token's `jti` is blacklisted for the token TTL (+ grace). A replayed
  token is rejected even if its code is still valid — under concurrency the
  atomic SET NX guarantees exactly one winner.
- **TOTP codes are single-use per user.** The same 6-digit code cannot be
  reused with a fresh mfa token within its validity window (pyotp
  `valid_window=1` accepts prev/current/next 30s steps → 90s TTL covers it).
- **Password-setup tokens are single-use.** `/setup-password` blacklists the
  setup token's `jti` the same way, so a replayed setup token cannot set the
  password twice.

Connection lifecycle is owned by `waggi_shared.redis` (same pattern as
`stores/challenges.py` and `stores/sso_states.py`); this module owns keys and
TTLs only.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import redis.asyncio as aioredis

from waggi_auth.config import settings
from waggi_shared.redis import redis_client

_JTI_PREFIX = "waggi:mfa-jti:"
_TOTP_PREFIX = "waggi:totp-used:"
_SETUP_JTI_PREFIX = "waggi:setup-jti:"

# pyotp valid_window=1 accepts codes from the previous/current/next 30s step.
_TOTP_TTL = timedelta(seconds=90)


def _redis() -> aioredis.Redis:
    return redis_client(settings.redis_url)


async def consume_mfa_jti(jti: str) -> bool:
    """Mark an MFA token's jti as used. True on first use, False on replay."""
    ttl = timedelta(seconds=settings.mfa_token_ttl_minutes * 60 + 60)  # token TTL + grace
    return bool(await _redis().set(_JTI_PREFIX + jti, "1", nx=True, ex=ttl))


async def consume_totp_code(user_id: uuid.UUID, code: str) -> bool:
    """Mark a TOTP code used for this user. True on first use, False on reuse."""
    return bool(await _redis().set(f"{_TOTP_PREFIX}{user_id}:{code}", "1", nx=True, ex=_TOTP_TTL))


async def consume_setup_jti(jti: str) -> bool:
    """Mark a password-setup token's jti as used. True on first use, False on replay."""
    ttl = timedelta(seconds=settings.setup_token_ttl_minutes * 60 + 60)  # token TTL + grace
    return bool(await _redis().set(_SETUP_JTI_PREFIX + jti, "1", nx=True, ex=ttl))


__all__ = ["consume_mfa_jti", "consume_setup_jti", "consume_totp_code"]
