from datetime import UTC, datetime, timedelta

import pytest

from tests.tracking.conftest import FINGERPRINT_SECRET, make_link
from tracking import keys
from tracking.clicks import ClickCounter, seconds_until_utc_midnight


@pytest.fixture
def counter(redis):
    return ClickCounter(
        redis,
        secret=FINGERPRINT_SECRET.encode(),
        rate_limit_per_minute=3,
        max_unique_per_ip_per_day=2,
        bucket_ttl=3600,
        stream_maxlen=1000,
    )


async def click(counter, now, ip="203.0.113.5", ua="Mozilla/5.0", link=None, referer="www.youtube.com"):
    return await counter.record(link or make_link(), ip=ip, user_agent=ua, referer_host=referer, now=now)


async def test_first_click_is_unique_then_repeat(redis, counter, now):
    assert await click(counter, now) == "unique"
    assert await click(counter, now + timedelta(seconds=1)) == "repeat"

    minute = int(now.timestamp()) // 60
    assert await redis.hgetall(keys.bucket(minute)) == {"7:r": "2", "7:u": "1"}
    assert await redis.zrange(keys.BUCKET_INDEX, 0, -1, withscores=True) == [(str(minute), float(minute))]
    assert 0 < await redis.ttl(keys.bucket(minute)) <= 3600

    events = await redis.xrange(keys.EVENTS_STREAM)
    assert len(events) == 2
    first = events[0][1]
    assert first["l"] == "7" and first["u"] == "1" and first["r"] == "www.youtube.com"
    assert first["t"] == str(int(now.timestamp() * 1000))
    assert len(first["v"]) == 32
    assert events[1][1]["u"] == "0"


async def test_dedup_is_per_link_per_visitor_per_day(redis, counter, now):
    assert await click(counter, now) == "unique"
    assert await click(counter, now, link=make_link(id=8)) == "unique"
    assert await click(counter, now + timedelta(seconds=5)) == "repeat"
    await redis.delete(*await redis.keys("trk:rl:*"))
    assert await click(counter, now, ua="Other/1.0") == "unique"

    await redis.delete(*await redis.keys("trk:rl:*"), *await redis.keys("trk:ipu:*"))
    next_day = now + timedelta(days=1)
    assert await click(counter, next_day) == "unique"
    assert await click(counter, next_day) == "repeat"
    hashes = [fields["v"] for _, fields in await redis.xrange(keys.EVENTS_STREAM)]
    assert hashes[0] == hashes[1] == hashes[2] != hashes[4] == hashes[5]


async def test_per_visitor_and_per_address_state_expires_at_utc_midnight(redis, counter, now):
    await click(counter, now)
    for pattern in ("trk:dd:*", "trk:ipu:*"):
        [key] = await redis.keys(pattern)
        assert abs(await redis.ttl(key) - seconds_until_utc_midnight(now)) <= 1


async def test_rate_limit_window_is_one_minute_from_the_first_hit(redis, counter, now):
    await click(counter, now)
    [key] = await redis.keys("trk:rl:*")
    assert 55 <= await redis.ttl(key) <= 60
    await redis.expire(key, 10)
    await click(counter, now, ua="UA/2")
    assert await redis.ttl(key) <= 10


async def test_rate_limit_stops_counting_but_is_per_ip(redis, counter, now):
    for _ in range(3):
        await click(counter, now, ua=f"UA/{_}")
    assert await click(counter, now, ua="UA/x") == "ratelimited"
    assert await click(counter, now, ip="198.51.100.9") == "unique"

    minute = int(now.timestamp()) // 60
    assert await redis.hget(keys.bucket(minute), "7:r") == "4"
    assert len(await redis.xrange(keys.EVENTS_STREAM)) == 4


async def test_ipv6_rotation_within_slash_64_shares_dedup_and_rate_limit(counter, now):
    assert await click(counter, now, ip="2001:db8:1:2::1") == "unique"
    assert await click(counter, now, ip="2001:db8:1:2:ffff::9") == "repeat"


async def test_clicks_land_in_their_own_minute_bucket(redis, counter, now):
    await click(counter, now)
    await click(counter, now + timedelta(minutes=1), ua="UA/2")
    minutes = await redis.zrange(keys.BUCKET_INDEX, 0, -1)
    assert minutes == [str(int(now.timestamp()) // 60), str(int(now.timestamp()) // 60 + 1)]


def test_seconds_until_utc_midnight():
    assert seconds_until_utc_midnight(datetime(2026, 9, 21, 23, 59, 30, tzinfo=UTC)) == 30
    assert seconds_until_utc_midnight(datetime(2026, 9, 21, 0, 0, 0, tzinfo=UTC)) == 86400
    warsaw = datetime(2026, 9, 22, 1, 59, 30, tzinfo=UTC).astimezone()  # any tz, same instant
    assert seconds_until_utc_midnight(warsaw) == 86400 - 2 * 3600 + 30
    assert seconds_until_utc_midnight(datetime(2026, 9, 21, 23, 59, 59, 999_999, tzinfo=UTC)) == 1
    assert seconds_until_utc_midnight(datetime(2026, 9, 21, 12, 0, 0, 500_000, tzinfo=UTC)) == 43199


async def test_ip_unique_cap_stops_user_agent_rotation(redis, counter, now):
    assert await click(counter, now, ua="UA/1") == "unique"
    assert await click(counter, now, ua="UA/2") == "unique"
    assert await click(counter, now, ua="UA/3") == "repeat"
    minute = int(now.timestamp()) // 60
    assert await redis.hgetall(keys.bucket(minute)) == {"7:r": "3", "7:u": "2"}
    assert [e[1]["u"] for e in await redis.xrange(keys.EVENTS_STREAM)] == ["1", "1", "0"]
    assert await click(counter, now, ua="UA/3", link=make_link(id=8)) == "ratelimited"
    await redis.delete(*await redis.keys("trk:rl:*"))  # fakeredis clock does not advance with `now`
    assert await click(counter, now + timedelta(minutes=1), ua="UA/3", link=make_link(id=8)) == "unique"
