"""Tests for the MFA single-use gates (jti blacklist + TOTP code dedup)."""

from __future__ import annotations

import uuid

import pytest
import redis.asyncio as aioredis

from waggi_auth.config import settings
from waggi_auth.stores import mfa


async def test_consume_mfa_jti_first_use_wins(fake_redis) -> None:
    assert await mfa.consume_mfa_jti("jti-1") is True
    assert await mfa.consume_mfa_jti("jti-1") is False  # replay
    assert await mfa.consume_mfa_jti("jti-2") is True  # independent


async def test_consume_mfa_jti_ttl(fake_redis) -> None:
    await mfa.consume_mfa_jti("jti-ttl")
    ttl = await fake_redis.ttl("waggi:mfa-jti:jti-ttl")
    expected = settings.mfa_token_ttl_minutes * 60 + 60
    assert 0 < ttl <= expected


async def test_consume_totp_code_first_use_wins(fake_redis) -> None:
    uid = uuid.uuid4()
    assert await mfa.consume_totp_code(uid, "123456") is True
    assert await mfa.consume_totp_code(uid, "123456") is False  # replay
    assert await mfa.consume_totp_code(uid, "654321") is True  # other code
    assert await mfa.consume_totp_code(uuid.uuid4(), "123456") is True  # other user


async def test_consume_totp_code_ttl(fake_redis) -> None:
    uid = uuid.uuid4()
    await mfa.consume_totp_code(uid, "111111")
    ttl = await fake_redis.ttl(f"waggi:totp-used:{uid}:111111")
    assert 0 < ttl <= 90


async def test_redis_errors_propagate(monkeypatch) -> None:
    """Callers translate RedisError into 503 (fail-closed) — store must raise."""

    class Boom:
        async def set(self, *a, **k):
            raise aioredis.RedisError("down")

    monkeypatch.setattr(mfa, "redis_client", lambda url: Boom())
    with pytest.raises(aioredis.RedisError):
        await mfa.consume_mfa_jti("jti-x")
    with pytest.raises(aioredis.RedisError):
        await mfa.consume_totp_code(uuid.uuid4(), "123456")
