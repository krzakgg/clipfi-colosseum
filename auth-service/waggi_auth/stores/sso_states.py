"""Redis-backed SSO state store (OAuth login flow).

Two single-use entry types, both consumed via GETDEL:

- Pending state: created at /authorize (login) or POST /link/{provider}
  (identity linking), consumed at the provider callback. Binds the OAuth
  `state` param to the nonce, the redirect_uri it was issued for, the frontend
  origin to return the browser to — and, for link states, the initiating
  user_id (server-side attribution; never client-supplied).
- Login handle: created by the callback after a successful provider
  verification, consumed by POST /complete (which issues tokens). Keeps
  session tokens out of URLs entirely.

Connection lifecycle is owned by waggi_shared; this module owns keys,
serialization and TTLs (same pattern as stores/challenges.py).
"""

from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

import redis.asyncio as aioredis

from waggi_auth.config import settings
from waggi_shared.redis import redis_client

_STATE_PREFIX = "waggi:sso-state:"
_LOGIN_PREFIX = "waggi:sso-login:"

STATE_TTL = timedelta(minutes=10)
LOGIN_TTL = timedelta(minutes=2)


@dataclass(frozen=True)
class PendingSsoState:
    provider: str
    nonce: str
    redirect_uri: str  # provider -> backend callback URL (must match at exchange)
    return_to: str  # backend -> frontend finish route (absolute URL)
    purpose: str = "login"  # "login" | "link" (identity linking ceremony)
    user_id: uuid.UUID | None = None  # initiating user; required for purpose="link"


def _redis() -> aioredis.Redis:
    return redis_client(settings.redis_url)


def _new_token() -> str:
    return secrets.token_urlsafe(32)


async def store_state(entry: PendingSsoState) -> str:
    """Persist a pending OAuth state; return the opaque `state` token."""
    if entry.purpose == "link" and entry.user_id is None:
        raise ValueError("link states must carry the initiating user_id")
    state = _new_token()
    payload = json.dumps(
        {
            "provider": entry.provider,
            "nonce": entry.nonce,
            "redirect_uri": entry.redirect_uri,
            "return_to": entry.return_to,
            "purpose": entry.purpose,
            "user_id": str(entry.user_id) if entry.user_id is not None else None,
        }
    )
    await _redis().set(_STATE_PREFIX + state, payload, ex=STATE_TTL)
    return state


async def pop_state(state: str) -> PendingSsoState | None:
    """Atomically consume a pending state. None if unknown/expired/corrupt."""
    raw = await _redis().getdel(_STATE_PREFIX + state)
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
        user_id: uuid.UUID | None = None
        raw_user_id = payload.get("user_id")
        if raw_user_id:
            # A corrupt user_id (non-UUID) raises ValueError below -> the whole
            # entry is treated as corrupt (pop_state -> None); a link callback
            # then rejects it exactly like any other bad state.
            user_id = uuid.UUID(str(raw_user_id))
        return PendingSsoState(
            provider=str(payload["provider"]),
            nonce=str(payload["nonce"]),
            redirect_uri=str(payload["redirect_uri"]),
            return_to=str(payload["return_to"]),
            purpose=str(payload.get("purpose", "login")),
            user_id=user_id,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


async def store_login(user_id: uuid.UUID) -> str:
    """Persist a pending SSO login; return the one-time handle for /complete."""
    handle = _new_token()
    await _redis().set(_LOGIN_PREFIX + handle, json.dumps({"user_id": str(user_id)}), ex=LOGIN_TTL)
    return handle


async def pop_login(handle: str) -> uuid.UUID | None:
    """Atomically consume a login handle. None if unknown/expired/corrupt."""
    raw = await _redis().getdel(_LOGIN_PREFIX + handle)
    if raw is None:
        return None
    try:
        return uuid.UUID(json.loads(raw)["user_id"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


__all__ = ["LOGIN_TTL", "STATE_TTL", "PendingSsoState", "pop_login", "pop_state", "store_login", "store_state"]
