"""Tests for the Redis-backed WebAuthn challenge store."""

from __future__ import annotations

import uuid
from datetime import timedelta

from waggi_auth.stores import challenges


async def test_challenge_roundtrip_single_use(fake_redis) -> None:
    uid = uuid.uuid4()
    entry = challenges.PendingChallenge(kind="register", user_id=uid, challenge=b"x" * 32, rp_id="localhost")
    await challenges.store("handle-1", entry, ttl=timedelta(minutes=5))

    popped = await challenges.pop("handle-1", "register", uid)
    assert popped is not None
    assert popped.kind == "register"
    assert popped.user_id == uid
    assert popped.challenge == b"x" * 32
    assert popped.rp_id == "localhost"

    # GETDEL: consumed on first pop.
    assert await challenges.pop("handle-1", "register", uid) is None


async def test_challenge_ttl_set(fake_redis) -> None:
    entry = challenges.PendingChallenge(kind="login", user_id=None, challenge=b"y" * 32, rp_id="localhost")
    await challenges.store("handle-2", entry, ttl=timedelta(minutes=5))
    ttl = await fake_redis.ttl("waggi:passkey-challenge:handle-2")
    assert 0 < ttl <= 300


async def test_challenge_kind_mismatch_rejected(fake_redis) -> None:
    uid = uuid.uuid4()
    entry = challenges.PendingChallenge(kind="register", user_id=uid, challenge=b"z" * 32, rp_id="localhost")
    await challenges.store("handle-3", entry, ttl=timedelta(minutes=5))
    assert await challenges.pop("handle-3", "login", uid) is None


async def test_challenge_user_mismatch_rejected(fake_redis) -> None:
    uid = uuid.uuid4()
    entry = challenges.PendingChallenge(kind="register", user_id=uid, challenge=b"a" * 32, rp_id="localhost")
    await challenges.store("handle-4", entry, ttl=timedelta(minutes=5))
    assert await challenges.pop("handle-4", "register", uuid.uuid4()) is None


async def test_challenge_login_has_no_user(fake_redis) -> None:
    entry = challenges.PendingChallenge(kind="login", user_id=None, challenge=b"b" * 32, rp_id="localhost")
    await challenges.store("handle-5", entry, ttl=timedelta(minutes=5))
    popped = await challenges.pop("handle-5", "login", None)
    assert popped is not None and popped.user_id is None


async def test_challenge_unknown_handle(fake_redis) -> None:
    assert await challenges.pop("nope", "register", None) is None


async def test_challenge_corrupt_payload(fake_redis, monkeypatch) -> None:
    monkeypatch.setattr(challenges, "redis_client", lambda url: fake_redis)
    await fake_redis.set("waggi:passkey-challenge:handle-6", "not-json{")
    assert await challenges.pop("handle-6", "register", None) is None

    # missing keys / wrong types
    await fake_redis.set("waggi:passkey-challenge:handle-7", '{"kind": "register"}')
    assert await challenges.pop("handle-7", "register", None) is None
