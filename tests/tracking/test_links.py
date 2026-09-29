import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from tests.tracking.conftest import make_link
from tests.tracking.fakes import MemoryLinkStore
from tracking import keys
from tracking.links import (
    CODE_RE,
    EARLIEST,
    LATEST,
    CachedLinkStore,
    LinkInput,
    bounded_utc,
    generate_code,
)

CAMPAIGN = "11111111-1111-1111-1111-111111111111"
CREATOR = "22222222-2222-2222-2222-222222222222"


def link_input(**overrides) -> LinkInput:
    data = dict(target_url="https://store.example.com/app/1", campaign_id=CAMPAIGN, creator_id=CREATOR)
    data.update(overrides)
    return LinkInput(**data)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "ftp://example.com/x",
        "//example.com/x",
        "https:///path-without-host",
        "https://user:pw@example.com/",
        "https://user@example.com/",
        "https://:pw@example.com/",
        "https://example.com/",
        "https://example.com/\r\nSet-Cookie: x=1",
        "https://example.com/a b",
        "https://example.com/" + "x" * 3000,
    ],
)
def test_unsafe_target_urls_are_rejected(url):
    with pytest.raises(ValidationError):
        link_input(target_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "https://例え.jp/ścieżka?q=ä#frag",
        "http://store.example.com/app/1",
        "HTTPS://store.example.com/app/1",
        "https://store.example.com/sale!?ref=a~b&x=(1)",
        "https://store.example.com:8443/app",
    ],
)
def test_ordinary_shop_urls_are_accepted(url):
    assert link_input(target_url=url).target_url == url


@pytest.mark.parametrize(
    "value, ok",
    [
        (EARLIEST, True),
        (EARLIEST - timedelta(microseconds=1), False),
        (LATEST - timedelta(microseconds=1), True),
        (LATEST, False),
        (datetime(2026, 9, 21, 14, 0, tzinfo=timezone(timedelta(hours=2))), True),
    ],
)
def test_timestamps_are_bounded_and_normalised_to_utc(value, ok):
    if ok:
        bounded = bounded_utc(value)
        assert bounded == value and bounded.utcoffset() == timedelta(0)
    else:
        with pytest.raises(ValueError):
            bounded_utc(value)


def test_platform_must_be_a_short_slug():
    assert link_input(platform="youtube_shorts").platform == "youtube_shorts"
    with pytest.raises(ValidationError):
        link_input(platform="YouTube Shorts")


def test_window_must_be_timezone_aware_and_ordered():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    with pytest.raises(ValidationError):
        link_input(starts_at=datetime(2026, 9, 1))
    with pytest.raises(ValidationError):
        link_input(starts_at=start, ends_at=start)
    assert link_input(starts_at=start, ends_at=start + timedelta(days=1)).ends_at > start


def test_generated_codes_match_the_public_regex_and_differ():
    codes = {generate_code() for _ in range(100)}
    assert len(codes) == 100
    assert all(CODE_RE.fullmatch(code) for code in codes)


def test_counts_at_respects_window_and_active_flag(now):
    assert make_link().counts_at(now)
    assert not make_link(active=False).counts_at(now)
    assert not make_link(starts_at=now + timedelta(minutes=1)).counts_at(now)
    assert make_link(starts_at=now).counts_at(now)
    assert not make_link(ends_at=now).counts_at(now)
    assert make_link(ends_at=now + timedelta(seconds=1)).counts_at(now)


async def test_cache_round_trips_links_and_negative_results(redis):
    inner = MemoryLinkStore()
    store = CachedLinkStore(inner, redis, positive_ttl=300, negative_ttl=30)
    start = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    created = await store.upsert("code1", link_input(starts_at=start, platform="twitch"))

    fetched = await store.get_by_code("code1")
    assert fetched == created
    assert await redis.ttl(keys.link("code1")) == 300

    # served from cache even if the inner store no longer has it
    inner._by_code.clear()
    assert await store.get_by_code("code1") == created

    assert await store.get_by_code("missing") is None
    assert await redis.get(keys.link("missing")) == "-"
    assert await redis.ttl(keys.link("missing")) == 30


async def test_writes_replace_the_cached_entry(redis):
    inner = MemoryLinkStore()
    store = CachedLinkStore(inner, redis, positive_ttl=300, negative_ttl=30)
    assert await store.get_by_code("code1") is None  # negative cached
    created = await store.insert("code1", link_input())
    assert await store.get_by_code("code1") == created

    deactivated = await store.deactivate("code1")
    assert deactivated is not None and not deactivated.active
    assert (await store.get_by_code("code1")).active is False

    updated = await store.upsert("code1", link_input(target_url="https://other.example.com/"))
    inner._by_code.clear()
    assert await store.get_by_code("code1") == updated
    assert await redis.ttl(keys.link("code1")) == 300


async def test_unreadable_cache_entry_is_treated_as_a_miss(redis):
    inner = MemoryLinkStore()
    created = await inner.insert("code1", link_input())
    store = CachedLinkStore(inner, redis, positive_ttl=300, negative_ttl=30)
    await redis.set(keys.link("code1"), "{not json")
    assert await store.get_by_code("code1") == created
    inner._by_code.clear()
    assert await store.get_by_code("code1") == created


async def test_cache_falls_through_when_redis_fails(redis, monkeypatch):
    inner = MemoryLinkStore()
    created = await inner.insert("code1", link_input())
    store = CachedLinkStore(inner, redis, positive_ttl=300, negative_ttl=30)

    from redis.exceptions import ConnectionError as RedisConnectionError

    async def boom(*args, **kwargs):
        raise RedisConnectionError("down")

    monkeypatch.setattr(redis, "get", boom)
    monkeypatch.setattr(redis, "set", boom)
    assert await store.get_by_code("code1") == created


@pytest.mark.parametrize("value", ["42", "campaign_7", "0a1b-2c", "x" * 64, "11111111-1111-1111-1111-111111111111"])
def test_external_ids_are_opaque_strings(value):
    data = link_input(campaign_id=value, creator_id=value)
    assert (data.campaign_id, data.creator_id) == (value, value)


@pytest.mark.parametrize("value", ["", "a b", "x" * 65, "../1", "1;DROP", "ź", 42, None])
def test_malformed_external_ids_are_rejected(value):
    with pytest.raises(ValidationError):
        link_input(campaign_id=value)
    with pytest.raises(ValidationError):
        link_input(creator_id=value)


class StallingStore(MemoryLinkStore):
    def __init__(self) -> None:
        super().__init__()
        self.read = asyncio.Event()
        self.release = asyncio.Event()
        self.stall = False

    async def get_by_code(self, code, *, miss_budget=None):
        link = await super().get_by_code(code)
        if self.stall:
            self.stall = False
            self.read.set()
            await self.release.wait()
        return link


@pytest.mark.parametrize("change", ["deactivate", "upsert", "insert"])
async def test_a_write_racing_a_cache_fill_is_not_overwritten_by_the_stale_row(redis, change):
    inner = StallingStore()
    store = CachedLinkStore(inner, redis, positive_ttl=300, negative_ttl=30)
    if change != "insert":
        await inner.insert("code1", link_input())
    inner.stall = True
    reader = asyncio.create_task(store.get_by_code("code1"))
    await inner.read.wait()

    if change == "deactivate":
        written = await store.deactivate("code1")
    elif change == "upsert":
        written = await store.upsert("code1", link_input(target_url="https://moved.example.com/"))
    else:
        written = await store.insert("code1", link_input())
    inner.release.set()
    await reader

    inner._by_code.clear()
    assert await store.get_by_code("code1") == written


async def test_negative_entries_spare_the_database(redis):
    inner = MemoryLinkStore()
    store = CachedLinkStore(inner, redis, positive_ttl=300, negative_ttl=30)
    for _ in range(5):
        assert await store.get_by_code("missing") is None
    assert inner.lookups == 1


async def test_the_miss_budget_is_per_address_and_expires_within_a_minute(redis):
    inner = MemoryLinkStore()
    store = CachedLinkStore(inner, redis, positive_ttl=300, negative_ttl=30, miss_limit_per_minute=3)
    for i in range(3):
        assert await store.get_by_code(f"miss-{i:04d}", miss_budget="trk:miss:ip") is None
    assert inner.lookups == 3
    assert 0 < await redis.ttl("trk:miss:ip") <= 60

    assert await store.get_by_code("miss-9999", miss_budget="trk:miss:ip") is None
    assert inner.lookups == 3
    assert await store.get_by_code("miss-9999", miss_budget="trk:miss:other") is None
    assert inner.lookups == 4


async def test_a_redis_failure_in_the_miss_budget_does_not_block_real_links(redis, monkeypatch):
    from redis.exceptions import ConnectionError as RedisConnectionError

    inner = MemoryLinkStore()
    created = await inner.insert("code1", link_input())
    store = CachedLinkStore(inner, redis, positive_ttl=300, negative_ttl=30, miss_limit_per_minute=3)

    def broken_pipeline(*args, **kwargs):
        raise RedisConnectionError("down")

    monkeypatch.setattr(redis, "pipeline", broken_pipeline)
    assert await store.get_by_code("code1", miss_budget="trk:miss:ip") == created

