"""Redis-backed WebAuthn challenge store.

Ceremony challenges (registration + login) live in Redis instead of process
memory so that ANY worker of the auth service can complete a ceremony started
by another worker (`uvicorn --workers N`, multiple instances behind a proxy).

Semantics:
- `store`: SETEX — single write with a hard TTL; expired challenges vanish
  without any cleanup job.
- `pop`: GETDEL — atomic single-use consume; a handle can never be replayed,
  even under concurrency.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import timedelta

import redis.asyncio as aioredis
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from waggi_auth.config import settings
from waggi_shared.redis import redis_client

_KEY_PREFIX = "waggi:passkey-challenge:"


@dataclass(frozen=True)
class PendingChallenge:
    """A stored ceremony challenge, bound to the rp_id it was issued for."""

    kind: str  # "register" | "login"
    user_id: uuid.UUID | None  # None for login (user resolved at finish)
    challenge: bytes
    rp_id: str


def _redis() -> aioredis.Redis:
    """The shared Redis client (connection lifecycle owned by waggi_shared)."""
    return redis_client(settings.redis_url)


def _key(handle: str) -> str:
    return f"{_KEY_PREFIX}{handle}"


async def store(handle: str, entry: PendingChallenge, ttl: timedelta) -> None:
    payload = json.dumps(
        {
            "kind": entry.kind,
            "user_id": str(entry.user_id) if entry.user_id is not None else None,
            "challenge": bytes_to_base64url(entry.challenge),
            "rp_id": entry.rp_id,
        }
    )
    await _redis().set(_key(handle), payload, ex=ttl)


async def pop(handle: str, kind: str, user_id: uuid.UUID | None) -> PendingChallenge | None:
    """Atomically consume a pending challenge. None if unknown/expired/mismatched."""
    raw = await _redis().getdel(_key(handle))
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
        stored_kind = payload["kind"]
        stored_user = payload["user_id"]
        stored_rp_id = payload["rp_id"]
        challenge = base64url_to_bytes(payload["challenge"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    if stored_kind != kind:
        return None
    if user_id is not None and stored_user != str(user_id):
        return None
    return PendingChallenge(
        kind=stored_kind,
        user_id=uuid.UUID(stored_user) if stored_user is not None else None,
        challenge=challenge,
        rp_id=stored_rp_id,
    )


__all__ = ["PendingChallenge", "pop", "store"]
