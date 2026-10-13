"""Redis-backed rate limiting for credential endpoints.

Engine: the `limits` library (fixed-window strategy over async Redis). Counters
live in Redis, so the limits hold across workers/instances and the window math
is the library's battle-tested implementation.

This module owns only the app-specific parts:
- **key computation** — per email (login, reset request), per IP (login spray,
  MFA step, reset request, SSO authorize, passkey begins), per user id
  (2FA verify/disable, shared step-up bucket) and body-derived keys a generic
  framework limiter cannot provide;
- **the error shape** — 429 as an RFC 7807 problem+json APIError with a
  `retry_after` extension, consistent with every other auth error;
- **fail-open policy** — if Redis is unavailable the request is allowed
  through (availability over lockout for an internal tool; the outage is
  logged). Note this differs from passkey/SSO ceremonies, which hard-require
  Redis for their challenges.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import status
from limits import RateLimitItem, RateLimitItemPerHour, RateLimitItemPerMinute
from limits.aio.strategies import FixedWindowRateLimiter
from limits.errors import StorageError
from limits.storage import storage_from_string

from waggi_auth.config import settings
from waggi_shared.errors import APIError

logger = logging.getLogger(__name__)

_NAMESPACE = "waggi:rl"

_LOGIN = RateLimitItemPerMinute(10, namespace=f"{_NAMESPACE}:login")  # per email
_LOGIN_IP = RateLimitItemPerMinute(30, namespace=f"{_NAMESPACE}:login-ip")  # per IP (spray across emails)
_LOGIN_MFA = RateLimitItemPerMinute(10, namespace=f"{_NAMESPACE}:login-mfa")  # per IP
_TOTP_VERIFY = RateLimitItemPerMinute(10, namespace=f"{_NAMESPACE}:2fa-verify")  # per user
_TOTP_DISABLE = RateLimitItemPerMinute(10, namespace=f"{_NAMESPACE}:2fa-disable")  # per user
# One shared bucket for every password-checked mutation (change-password,
# 2FA setup/disable, backup regeneration, passkey registration) — the password
# itself must not be brute-forceable through any of them.
_STEP_UP = RateLimitItemPerMinute(10, namespace=f"{_NAMESPACE}:step-up")  # per user
_RESET_EMAIL = RateLimitItemPerHour(5, namespace=f"{_NAMESPACE}:pwreset-email")  # per email
_RESET_IP = RateLimitItemPerHour(20, namespace=f"{_NAMESPACE}:pwreset-ip")  # per IP
# Unauthenticated endpoints that write a Redis entry per call — cap per IP so
# they can't be used to flood Redis (entries are TTL'd 2-10 min).
_SSO_AUTHORIZE = RateLimitItemPerMinute(20, namespace=f"{_NAMESPACE}:sso-authorize")  # per IP
_PASSKEY_BEGIN = RateLimitItemPerMinute(30, namespace=f"{_NAMESPACE}:passkey-begin")  # per IP
# Public self-signup: per IP (each hit also writes a DB row + argon2 hash).
_REGISTER_IP = RateLimitItemPerHour(20, namespace=f"{_NAMESPACE}:register-ip")  # per IP

# Module-level strategy (lazily built; tests substitute an in-memory one).
_strategy: FixedWindowRateLimiter | None = None


class TooManyRequestsError(APIError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    title = "Too Many Requests"

    def __init__(self, *, retry_after: int = 60) -> None:
        super().__init__(
            detail="Too many attempts; try again later",
            code="rate_limited",
            extensions={"retry_after": retry_after},
        )


def _limiter() -> FixedWindowRateLimiter:
    global _strategy
    if _strategy is None:
        url = settings.redis_url
        if not url.startswith("async+"):
            url = f"async+{url}"
        _strategy = FixedWindowRateLimiter(storage_from_string(url))
    return _strategy


async def _enforce(item: RateLimitItem, *identifiers: str) -> None:
    """Count one hit; raise 429 when the window is exhausted. Fails open."""
    try:
        limiter = _limiter()
        allowed = await limiter.hit(item, *identifiers)
        if allowed:
            return
        retry_after = 60
        try:
            window = await limiter.get_window_stats(item, *identifiers)
            retry_after = max(1, int(window.reset_time - time.time()))
        except StorageError:
            pass
    except StorageError as exc:
        logger.warning("Rate-limit store unavailable (fail-open): %s", exc)
        return
    raise TooManyRequestsError(retry_after=retry_after)


# --- endpoint-specific enforcers (call first thing inside the endpoint) ---


async def enforce_login(email: str, client_ip: str) -> None:
    """POST /auth/login — per (normalized) email AND per IP.

    The per-email cap stops focused brute force; the per-IP cap stops password
    spraying across many accounts from one source (NAT-friendly threshold).
    """
    await _enforce(_LOGIN, email.strip().lower())
    await _enforce(_LOGIN_IP, client_ip)


async def enforce_login_mfa(client_ip: str) -> None:
    """POST /auth/login/mfa — TOTP/backup-code guessing protection per IP."""
    await _enforce(_LOGIN_MFA, client_ip)


async def enforce_totp_verify(user_id: uuid.UUID) -> None:
    """POST /auth/2fa/verify — TOTP guessing protection during enrollment."""
    await _enforce(_TOTP_VERIFY, str(user_id))


async def enforce_totp_disable(user_id: uuid.UUID) -> None:
    """POST /auth/2fa/disable — backup codes are brute-forceable otherwise."""
    await _enforce(_TOTP_DISABLE, str(user_id))


async def enforce_step_up(user_id: uuid.UUID) -> None:
    """Any password-checked mutation — shared per-user bucket so the password
    can't be brute-forced through a different endpoint after one locks."""
    await _enforce(_STEP_UP, str(user_id))


async def enforce_sso_authorize(client_ip: str) -> None:
    """POST /auth/sso/{provider}/authorize — unauthenticated, writes Redis state per call."""
    await _enforce(_SSO_AUTHORIZE, client_ip)


async def enforce_passkey_begin(client_ip: str) -> None:
    """POST /auth/passkeys/{login,register}/begin — unauthenticated Redis challenge per call."""
    await _enforce(_PASSKEY_BEGIN, client_ip)


async def enforce_password_reset_request(email: str, client_ip: str) -> None:
    """POST /auth/password-reset/request — per email AND per IP."""
    await _enforce(_RESET_EMAIL, email.strip().lower())
    await _enforce(_RESET_IP, client_ip)


async def enforce_register(client_ip: str) -> None:
    """POST /auth/register — public signup, per IP."""
    await _enforce(_REGISTER_IP, client_ip)


__all__ = [
    "TooManyRequestsError",
    "enforce_login",
    "enforce_login_mfa",
    "enforce_passkey_begin",
    "enforce_password_reset_request",
    "enforce_register",
    "enforce_sso_authorize",
    "enforce_step_up",
    "enforce_totp_disable",
    "enforce_totp_verify",
]
