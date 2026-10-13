"""Tests for the limits-based rate limiter (in-memory storage)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from limits import RateLimitItemPerSecond
from limits.aio.storage import MemoryStorage
from limits.aio.strategies import FixedWindowRateLimiter
from limits.errors import StorageError

from waggi_auth import rate_limit
from waggi_auth.config import settings
from waggi_auth.rate_limit import TooManyRequestsError


def _fresh_strategy() -> None:
    rate_limit._strategy = FixedWindowRateLimiter(MemoryStorage())


async def test_enforce_login_under_limit_passes() -> None:
    _fresh_strategy()
    for _ in range(10):
        await rate_limit.enforce_login("user@example.com", "1.1.1.1")


async def test_enforce_login_over_limit_raises_429() -> None:
    _fresh_strategy()
    for _ in range(10):
        await rate_limit.enforce_login("user@example.com", "1.1.1.1")
    with pytest.raises(TooManyRequestsError) as excinfo:
        await rate_limit.enforce_login("user@example.com", "1.1.1.1")
    assert excinfo.value.status_code == 429
    assert excinfo.value.extensions["retry_after"] >= 1


async def test_login_keys_are_per_email() -> None:
    _fresh_strategy()
    for _ in range(10):
        await rate_limit.enforce_login("a@example.com", "1.1.1.1")
    await rate_limit.enforce_login("b@example.com", "1.1.1.1")  # independent email bucket


async def test_login_ip_limit_blocks_spraying() -> None:
    """Rotating emails from ONE IP (password spraying) trips the per-IP bucket."""
    _fresh_strategy()
    for i in range(30):
        await rate_limit.enforce_login(f"victim{i}@example.com", "9.9.9.9")
    with pytest.raises(TooManyRequestsError):
        await rate_limit.enforce_login("next@example.com", "9.9.9.9")
    # A different IP is unaffected (NAT/office shared-IP threshold is per IP).
    await rate_limit.enforce_login("other@example.com", "8.8.8.8")


async def test_login_key_normalizes_email() -> None:
    _fresh_strategy()
    for _ in range(10):
        await rate_limit.enforce_login("A@Example.COM ", "1.1.1.1")
    with pytest.raises(TooManyRequestsError):
        await rate_limit.enforce_login("a@example.com", "2.2.2.2")  # same email bucket


async def test_window_reset_after_expiry() -> None:
    _fresh_strategy()
    item = RateLimitItemPerSecond(1, namespace="waggi:rl:test-window")
    await rate_limit._enforce(item, "k")
    with pytest.raises(TooManyRequestsError):
        await rate_limit._enforce(item, "k")
    await asyncio.sleep(1.1)
    await rate_limit._enforce(item, "k")  # window rolled


async def test_fail_open_on_storage_error(monkeypatch) -> None:
    class BrokenStrategy:
        async def hit(self, *a, **k):
            raise StorageError("redis down")

        async def get_window_stats(self, *a, **k):
            raise StorageError("redis down")

    monkeypatch.setattr(rate_limit, "_strategy", BrokenStrategy())
    await rate_limit.enforce_login("x@example.com", "9.9.9.9")  # allowed through (fail-open)
    await rate_limit.enforce_totp_verify(uuid.uuid4())


async def test_stats_error_falls_back_to_default_retry_after(monkeypatch) -> None:
    class HalfBrokenStrategy:
        def __init__(self):
            self.inner = FixedWindowRateLimiter(MemoryStorage())
            self.calls = 0

        async def hit(self, item, *ids):
            self.calls += 1
            allowed = await self.inner.hit(item, *ids)
            if self.calls >= 3:  # enforce_login hits twice (email + IP); trip on the 2nd call
                return False
            return allowed

        async def get_window_stats(self, *a, **k):
            raise StorageError("stats unavailable")

    monkeypatch.setattr(rate_limit, "_strategy", HalfBrokenStrategy())
    await rate_limit.enforce_login("y@example.com", "9.9.9.9")
    with pytest.raises(TooManyRequestsError) as excinfo:
        await rate_limit.enforce_login("y@example.com", "9.9.9.9")
    assert excinfo.value.extensions["retry_after"] == 60  # fallback default


async def test_per_user_enforcers_use_distinct_keys() -> None:
    _fresh_strategy()
    uid = uuid.uuid4()
    for _ in range(10):
        await rate_limit.enforce_totp_verify(uid)
    with pytest.raises(TooManyRequestsError):
        await rate_limit.enforce_totp_verify(uid)
    # disable has its own bucket
    await rate_limit.enforce_totp_disable(uid)


async def test_step_up_limit_is_shared_across_mutation_endpoints() -> None:
    """One shared per-user bucket: exhausting it via one endpoint blocks the
    others too (the password can't be brute-forced through a sibling route)."""
    _fresh_strategy()
    uid = uuid.uuid4()
    for _ in range(10):
        await rate_limit.enforce_step_up(uid)
    with pytest.raises(TooManyRequestsError):
        await rate_limit.enforce_step_up(uid)
    # another user is unaffected
    await rate_limit.enforce_step_up(uuid.uuid4())


async def test_sso_authorize_limit_per_ip() -> None:
    _fresh_strategy()
    for _ in range(20):
        await rate_limit.enforce_sso_authorize("4.4.4.4")
    with pytest.raises(TooManyRequestsError):
        await rate_limit.enforce_sso_authorize("4.4.4.4")
    await rate_limit.enforce_sso_authorize("5.5.5.5")  # other IP unaffected


async def test_passkey_begin_limit_per_ip() -> None:
    _fresh_strategy()
    for _ in range(30):
        await rate_limit.enforce_passkey_begin("6.6.6.6")
    with pytest.raises(TooManyRequestsError):
        await rate_limit.enforce_passkey_begin("6.6.6.6")
    await rate_limit.enforce_passkey_begin("7.7.7.7")  # other IP unaffected


async def test_password_reset_limits_both_dimensions() -> None:
    _fresh_strategy()
    # per-email limit (5/hour) trips before per-IP (20/hour)
    for _ in range(5):
        await rate_limit.enforce_password_reset_request("z@example.com", "1.2.3.4")
    with pytest.raises(TooManyRequestsError):
        await rate_limit.enforce_password_reset_request("z@example.com", "1.2.3.4")


async def test_password_reset_ip_limit() -> None:
    _fresh_strategy()
    for i in range(20):
        await rate_limit.enforce_password_reset_request(f"user{i}@example.com", "9.9.9.9")
    with pytest.raises(TooManyRequestsError):
        await rate_limit.enforce_password_reset_request("another@example.com", "9.9.9.9")


async def test_limiter_builds_lazily_and_caches(monkeypatch) -> None:
    """The real strategy is built once from settings.redis_url (lazy: no
    connection is made at construction)."""
    from limits.aio.strategies import FixedWindowRateLimiter as AsyncFixedWindowRateLimiter

    monkeypatch.setattr(rate_limit, "_strategy", None)
    monkeypatch.setattr(settings, "redis_url", "async+redis://localhost:6399/9")
    try:
        strategy = rate_limit._limiter()
        assert isinstance(strategy, AsyncFixedWindowRateLimiter)
        assert rate_limit._limiter() is strategy  # cached singleton
    finally:
        monkeypatch.setattr(rate_limit, "_strategy", None)  # don't leak into other tests


async def test_limiter_prefixes_plain_redis_url(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit, "_strategy", None)
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6399/9")
    try:
        rate_limit._limiter()  # builds from async+redis://... without connecting
    finally:
        monkeypatch.setattr(rate_limit, "_strategy", None)
