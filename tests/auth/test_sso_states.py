"""Tests for the Redis-backed SSO state store."""

from __future__ import annotations

import uuid

import pytest

from waggi_auth.stores import sso_states


async def test_state_roundtrip_single_use(fake_redis) -> None:
    entry = sso_states.PendingSsoState(
        provider="google",
        nonce="nonce-1",
        redirect_uri="http://localhost:5173/api/v1/auth/sso/google/callback",
        return_to="http://localhost:5173/login/sso/callback",
    )
    state = await sso_states.store_state(entry)
    assert state and len(state) >= 32

    popped = await sso_states.pop_state(state)
    assert popped == entry
    assert await sso_states.pop_state(state) is None  # single use


async def test_state_ttl(fake_redis) -> None:
    await sso_states.store_state(
        sso_states.PendingSsoState(provider="google", nonce="n", redirect_uri="http://x/cb", return_to="http://x/finish")
    )
    keys = await fake_redis.keys("waggi:sso-state:*")
    assert len(keys) == 1
    ttl = await fake_redis.ttl(keys[0])
    assert 0 < ttl <= sso_states.STATE_TTL.total_seconds()


async def test_state_corrupt(fake_redis, monkeypatch) -> None:
    monkeypatch.setattr(sso_states, "redis_client", lambda url: fake_redis)
    await fake_redis.set("waggi:sso-state:abc", "{invalid json")
    assert await sso_states.pop_state("abc") is None


async def test_login_handle_roundtrip_single_use(fake_redis) -> None:
    uid = uuid.uuid4()
    handle = await sso_states.store_login(uid)
    assert handle and len(handle) >= 32
    assert await sso_states.pop_login(handle) == uid
    assert await sso_states.pop_login(handle) is None


async def test_login_handle_ttl(fake_redis) -> None:
    await sso_states.store_login(uuid.uuid4())
    keys = await fake_redis.keys("waggi:sso-login:*")
    assert len(keys) == 1
    ttl = await fake_redis.ttl(keys[0])
    assert 0 < ttl <= sso_states.LOGIN_TTL.total_seconds()


async def test_login_handle_corrupt(fake_redis, monkeypatch) -> None:
    monkeypatch.setattr(sso_states, "redis_client", lambda url: fake_redis)
    await fake_redis.set("waggi:sso-login:h", "not-json")
    assert await sso_states.pop_login("h") is None
    await fake_redis.set("waggi:sso-login:h2", '{"user_id": "not-a-uuid"}')
    assert await sso_states.pop_login("h2") is None


# --- link-purpose states (identity linking ceremony) ---------------------------


async def test_link_state_roundtrip_single_use(fake_redis) -> None:
    uid = uuid.uuid4()
    entry = sso_states.PendingSsoState(
        provider="google",
        nonce="nonce-2",
        redirect_uri="http://localhost:5173/api/v1/auth/sso/google/callback",
        return_to="http://localhost:5173/account",
        purpose="link",
        user_id=uid,
    )
    state = await sso_states.store_state(entry)
    popped = await sso_states.pop_state(state)
    assert popped == entry
    assert popped.purpose == "link"
    assert popped.user_id == uid
    assert await sso_states.pop_state(state) is None  # single use


async def test_link_state_requires_user_id(fake_redis) -> None:
    with pytest.raises(ValueError, match="user_id"):
        await sso_states.store_state(
            sso_states.PendingSsoState(
                provider="google",
                nonce="n",
                redirect_uri="http://x/cb",
                return_to="http://x/account",
                purpose="link",
            )
        )


async def test_state_missing_user_id_pops_as_none_user(fake_redis, monkeypatch) -> None:
    """A raw entry with purpose=link but no user_id survives the parse with
    user_id=None — the link callback then rejects it (state error)."""
    monkeypatch.setattr(sso_states, "redis_client", lambda url: fake_redis)
    await fake_redis.set(
        "waggi:sso-state:lk",
        '{"provider": "google", "nonce": "n", "redirect_uri": "http://x/cb", "return_to": "http://x/account", "purpose": "link"}',
    )
    entry = await sso_states.pop_state("lk")
    assert entry is not None
    assert entry.purpose == "link"
    assert entry.user_id is None


async def test_state_corrupt_user_id_is_invalid(fake_redis, monkeypatch) -> None:
    """A user_id that is not a UUID makes the WHOLE entry corrupt (None)."""
    monkeypatch.setattr(sso_states, "redis_client", lambda url: fake_redis)
    await fake_redis.set(
        "waggi:sso-state:lk2",
        '{"provider": "google", "nonce": "n", "redirect_uri": "http://x/cb", '
        '"return_to": "http://x/account", "purpose": "link", "user_id": "not-a-uuid"}',
    )
    assert await sso_states.pop_state("lk2") is None
