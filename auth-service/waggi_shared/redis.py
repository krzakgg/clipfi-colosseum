"""Shared async Redis client lifecycle.

Owns ONLY the connection: per-URL client singletons (`from_url` pools
connections internally) + a shutdown hook. Serialization, key naming and TTL
semantics stay with each consumer (e.g. the auth service's WebAuthn challenge
store and SSO state store).

Config stays per-service (self-contained Settings classes) — callers pass the
URL explicitly; this module never reads settings.
"""

from __future__ import annotations

import redis.asyncio as aioredis

# One client (with its own connection pool) per URL.
_clients: dict[str, aioredis.Redis] = {}


def redis_client(url: str) -> aioredis.Redis:
    """Return the shared async Redis client for `url`, creating it on first use.

    Connections are lazy: nothing dials until the first command, so services
    that never touch Redis pay no runtime cost.
    """
    client = _clients.get(url)
    if client is None:
        client = aioredis.from_url(url)
        _clients[url] = client
    return client


async def aclose_all() -> None:
    """Close every cached client (app shutdown). Safe to call repeatedly."""
    for client in _clients.values():
        await client.aclose()
    _clients.clear()


__all__ = ["aclose_all", "redis_client"]


__all__ = ["aclose_all", "redis_client"]
