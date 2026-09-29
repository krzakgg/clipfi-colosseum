from datetime import UTC, datetime, timedelta

import pytest

from tests.tracking.conftest import FINGERPRINT_SECRET, make_link
from tracking import keys
from tracking.clicks import ClickCounter
from tracking.flusher import _FIRST_MINUTE, _LAST_MINUTE, BucketRow, ClickEvent, Flusher, parse_bucket, parse_event

MAX_BIGINT = 2**63 - 1
MAX_INT = 2**31 - 1


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[ClickEvent] = []
        self.buckets: list[list[BucketRow]] = []
        self.prunes: list[tuple[datetime, int]] = []
        self.fail_events = 0
        self.fail_buckets = 0
        self.fail_prunes = 0
        self.prune_results: list[int] = []

    async def write_events(self, events):
        if self.fail_events:
            self.fail_events -= 1
            raise ConnectionError("postgres down")
        self.events.extend(events)

    async def write_buckets(self, rows):
        if self.fail_buckets:
            self.fail_buckets -= 1
            raise ConnectionError("postgres down")
        self.buckets.append(list(rows))

    async def prune_events(self, older_than, limit):
        self.prunes.append((older_than, limit))
        if self.fail_prunes:
            self.fail_prunes -= 1
            raise ConnectionError("postgres down")
        return self.prune_results.pop(0) if self.prune_results else 0


@pytest.fixture
def sink():
    return RecordingSink()


@pytest.fixture
def counter(redis):
    return ClickCounter(redis, secret=FINGERPRINT_SECRET.encode(), rate_limit_per_minute=100, max_unique_per_ip_per_day=100, bucket_ttl=3600, stream_maxlen=1000)


@pytest.fixture
def clock(now):
    state = {"now": now}

    def read():
        return state["now"]

    read.set = lambda value: state.__setitem__("now", value)
    return read


@pytest.fixture
async def flusher(redis, sink, settings, clock):
    settings = settings.model_copy(update={"events_batch_size": 2, "consumer_name": "test-1", "pending_claim_idle_ms": 1000})
    flusher = Flusher(redis, sink, settings, clock=clock)
    await flusher.ensure_group()
    return flusher


async def pending(redis) -> int:
    return (await redis.xpending(keys.EVENTS_STREAM, keys.EVENTS_GROUP))["pending"]


def test_parse_event():
    occurred_at = datetime(2026, 9, 21, 12, 34, 56, 123000, tzinfo=UTC)
    millis = str(int(occurred_at.timestamp() * 1000))
    event = parse_event("1758458096000-0", {"l": "7", "t": millis, "u": "1", "v": "ab" * 16, "r": ""})
    assert event == ClickEvent(
        id="1758458096000-0",
        link_id=7,
        occurred_at=occurred_at,
        is_unique=True,
        visitor_hash="ab" * 16,
        referer_host=None,
    )


def test_parse_event_rejects_garbage():
    with pytest.raises((KeyError, ValueError)):
        parse_event("1-0", {"l": "x"})


def test_parse_bucket_groups_fields_per_link():
    minute = 29307634
    rows = parse_bucket(minute, {"7:r": "3", "7:u": "2", "9:r": "1"})
    assert rows == [
        BucketRow(link_id=7, bucket_start=datetime.fromtimestamp(minute * 60, tz=UTC), raw=3, unique=2),
        BucketRow(link_id=9, bucket_start=datetime.fromtimestamp(minute * 60, tz=UTC), raw=1, unique=0),
    ]
    assert parse_bucket(minute, {}) == []


async def test_events_are_persisted_in_batches_and_acked(redis, counter, flusher, sink, now):
    for i in range(3):
        await counter.record(make_link(), ip=f"203.0.113.{i}", user_agent="UA", referer_host="kick.com", now=now)

    assert await flusher.flush_events_once() == 2
    assert await flusher.flush_events_once() == 1
    assert await flusher.flush_events_once() == 0
    assert [e.link_id for e in sink.events] == [7, 7, 7]
    assert all(e.is_unique and e.referer_host == "kick.com" and e.occurred_at == now for e in sink.events)
    assert await pending(redis) == 0
    await flusher.ensure_group()  # idempotent: BUSYGROUP is swallowed


async def test_failed_batch_stays_pending_and_is_replayed(redis, counter, flusher, sink, now):
    await counter.record(make_link(), ip="203.0.113.1", user_agent="UA", referer_host=None, now=now)
    sink.fail_events = 1
    with pytest.raises(ConnectionError):
        await flusher.flush_events_once()
    assert await pending(redis) == 1 and sink.events == []

    assert await flusher.flush_events_once() == 0  # ">" only yields new entries
    assert await flusher.drain_own_pending() == 1
    assert len(sink.events) == 1 and await pending(redis) == 0


async def test_malformed_entries_are_dropped_not_retried(redis, flusher, sink, caplog):
    await redis.xadd(keys.EVENTS_STREAM, {"garbage": "1"})
    assert await flusher.flush_events_once() == 0
    assert await pending(redis) == 0
    assert "malformed click event" in caplog.text


async def test_stale_entries_of_dead_consumers_are_claimed(redis, counter, flusher, sink, settings, now):
    for i in range(3):
        await counter.record(make_link(), ip=f"203.0.113.{i}", user_agent="UA", referer_host=None, now=now)
    # another consumer reads everything and dies before acking
    await redis.xreadgroup(keys.EVENTS_GROUP, "dead-consumer", {keys.EVENTS_STREAM: ">"}, count=10)
    assert await pending(redis) == 3

    flusher._settings = flusher._settings.model_copy(update={"pending_claim_idle_ms": 1})
    import asyncio

    await asyncio.sleep(0.01)
    assert await flusher.claim_stale_once() == 3
    assert len(sink.events) == 3 and await pending(redis) == 0


async def test_buckets_are_upserted_and_closed_after_grace(redis, counter, flusher, sink, clock, now):
    earlier = now - timedelta(minutes=10)
    await counter.record(make_link(), ip="203.0.113.1", user_agent="UA", referer_host=None, now=earlier)
    await counter.record(make_link(id=9), ip="203.0.113.1", user_agent="UA", referer_host=None, now=earlier)
    await counter.record(make_link(), ip="203.0.113.1", user_agent="UA", referer_host=None, now=now)
    old_minute = int(earlier.timestamp()) // 60
    cur_minute = int(now.timestamp()) // 60

    assert await flusher.flush_buckets_once() == 3
    # third click is the same visitor on link 7 the same day: raw but not unique
    assert sink.buckets == [
        [
            BucketRow(7, datetime.fromtimestamp(old_minute * 60, tz=UTC), 1, 1),
            BucketRow(9, datetime.fromtimestamp(old_minute * 60, tz=UTC), 1, 1),
        ],
        [BucketRow(7, datetime.fromtimestamp(cur_minute * 60, tz=UTC), 1, 0)],
    ]
    assert await redis.exists(keys.bucket(old_minute)) == 0
    assert await redis.zrange(keys.BUCKET_INDEX, 0, -1) == [str(cur_minute)]

    assert await flusher.flush_buckets_once() == 1
    assert sink.buckets[-1] == [BucketRow(7, datetime.fromtimestamp(cur_minute * 60, tz=UTC), 1, 0)]

    clock.set(now + timedelta(minutes=6))
    await flusher.flush_buckets_once()
    assert await redis.zcard(keys.BUCKET_INDEX) == 0
    assert await redis.keys("trk:bkt:*") == []


async def test_bucket_flush_failure_leaves_redis_untouched(redis, counter, flusher, sink, now, monkeypatch):
    earlier = now - timedelta(minutes=10)
    await counter.record(make_link(), ip="203.0.113.1", user_agent="UA", referer_host=None, now=earlier)

    async def boom(rows):
        raise ConnectionError("postgres down")

    monkeypatch.setattr(sink, "write_buckets", boom)
    with pytest.raises(ConnectionError):
        await flusher.flush_buckets_once()
    assert await redis.zcard(keys.BUCKET_INDEX) == 1
    assert await redis.hgetall(keys.bucket(int(earlier.timestamp()) // 60)) == {"7:r": "1", "7:u": "1"}


async def test_prune_runs_until_a_short_batch(flusher, sink, now, settings):
    sink.prune_results = [10_000, 10_000, 12]
    assert await flusher.prune_once() == 20_012
    cutoff = now - timedelta(days=settings.events_retention_days)
    assert sink.prunes == [(cutoff, 10_000)] * 3


async def test_run_stops_cleanly_on_stop_event(redis, counter, flusher, sink, now):
    import asyncio

    await counter.record(make_link(), ip="203.0.113.1", user_agent="UA", referer_host=None, now=now)
    stop = asyncio.Event()
    flusher._settings = flusher._settings.model_copy(update={"events_block_ms": 100, "flush_interval": 0.05})
    task = asyncio.create_task(flusher.run(stop))
    for _ in range(50):
        await asyncio.sleep(0.02)
        if sink.events and sink.buckets:
            break
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert len(sink.events) == 1 and sink.buckets


async def test_malformed_bucket_field_is_skipped_and_the_rest_is_written(redis, counter, flusher, sink, now, caplog):
    await counter.record(make_link(), ip="203.0.113.1", user_agent="UA", referer_host=None, now=now)
    minute = int(now.timestamp()) // 60
    await redis.hset(keys.bucket(minute), mapping={"not-a-link:r": "5", "9:r": "many"})
    assert await flusher.flush_buckets_once() == 1
    assert sink.buckets == [[BucketRow(7, datetime.fromtimestamp(minute * 60, tz=UTC), 1, 1)]]
    assert "malformed bucket field" in caplog.text


async def test_garbage_in_the_bucket_index_is_dropped(redis, counter, flusher, sink, now, caplog):
    await counter.record(make_link(), ip="203.0.113.1", user_agent="UA", referer_host=None, now=now)
    await redis.zadd(keys.BUCKET_INDEX, {"garbage": 0})
    assert await flusher.flush_buckets_once() == 1
    assert "garbage" not in await redis.zrange(keys.BUCKET_INDEX, 0, -1)
    assert "malformed bucket index entry" in caplog.text


@pytest.mark.parametrize("member", [str(10**20), "-1", "99999999999"])
async def test_bucket_minutes_outside_any_sane_range_are_dropped(redis, counter, flusher, sink, now, member, caplog):
    await counter.record(make_link(), ip="203.0.113.1", user_agent="UA", referer_host=None, now=now)
    await redis.zadd(keys.BUCKET_INDEX, {member: -1})
    await redis.hset(keys.bucket(int(member)), mapping={"7:r": "1"})
    assert await flusher.flush_buckets_once() == 1
    assert member not in await redis.zrange(keys.BUCKET_INDEX, 0, -1)
    assert await redis.exists(keys.bucket(int(member))) == 0


@pytest.mark.parametrize("field,value", [("7:r", str(2**40)), (str(2**70) + ":r", "1"), ("0:r", "1"), ("7:u", "-3")])
def test_bucket_values_postgres_cannot_store_are_skipped(field, value):
    minute = 29307634
    rows = parse_bucket(minute, {field: value, "9:r": "2"})
    assert rows == [BucketRow(link_id=9, bucket_start=datetime.fromtimestamp(minute * 60, tz=UTC), raw=2, unique=0)]


@pytest.mark.parametrize(
    "fields",
    [
        {"l": "7", "t": "1" + "0" * 400, "u": "1", "v": "a" * 32, "r": ""},
        {"l": "7", "t": "-99999999999999999", "u": "1", "v": "a" * 32, "r": ""},
        {"l": str(2**70), "t": "1790000000000", "u": "1", "v": "a" * 32, "r": ""},
        {"l": "7", "t": "1790000000000", "u": "1", "v": "a" * 5000, "r": ""},
    ],
)
async def test_poisoned_stream_entries_are_dropped_and_do_not_block_the_rest(redis, counter, flusher, sink, now, fields):
    await redis.xadd(keys.EVENTS_STREAM, fields)
    await counter.record(make_link(), ip="203.0.113.1", user_agent="UA", referer_host=None, now=now)
    await flusher.flush_events_once()
    await flusher.flush_events_once()
    assert [e.link_id for e in sink.events] == [7]
    assert await pending(redis) == 0


async def test_loops_survive_a_database_outage_and_lose_nothing(redis, counter, flusher, sink, now, caplog):
    import asyncio

    await counter.record(make_link(), ip="203.0.113.1", user_agent="UA", referer_host=None, now=now)
    await counter.record(make_link(), ip="203.0.113.2", user_agent="UA", referer_host=None, now=now)
    sink.fail_events = sink.fail_buckets = sink.fail_prunes = 1
    flusher._settings = flusher._settings.model_copy(update={"events_block_ms": 100, "flush_interval": 0.05})
    stop = asyncio.Event()
    task = asyncio.create_task(flusher.run(stop))
    for _ in range(200):
        await asyncio.sleep(0.02)
        if len(sink.events) == 2 and sink.buckets:
            break
    stop.set()
    await asyncio.wait_for(task, timeout=5)

    assert sorted(e.visitor_hash for e in sink.events) == sorted({e.visitor_hash for e in sink.events})
    assert len(sink.events) == 2 and await pending(redis) == 0
    assert sink.buckets[-1] == [BucketRow(7, now.replace(second=0), 2, 2)]
    assert "event flush failed" in caplog.text
    assert "bucket flush failed" in caplog.text
    assert "event pruning failed" in caplog.text


@pytest.mark.parametrize("grace, kept_minutes", [(60, 1), (61, 2), (300, 5)])
async def test_a_bucket_stays_open_for_the_whole_grace_period(redis, counter, flusher, sink, now, grace, kept_minutes):
    flusher._settings = flusher._settings.model_copy(update={"bucket_close_grace": grace})
    now_minute = int(now.timestamp()) // 60
    for age in (kept_minutes, kept_minutes + 1):
        await counter.record(make_link(), ip=f"203.0.113.{age}", user_agent="UA", referer_host=None, now=now - timedelta(minutes=age))

    assert await flusher.flush_buckets_once() == 2
    assert await redis.zrange(keys.BUCKET_INDEX, 0, -1) == [str(now_minute - kept_minutes)]
    assert await redis.exists(keys.bucket(now_minute - kept_minutes - 1)) == 0
    assert await redis.hgetall(keys.bucket(now_minute - kept_minutes)) == {"7:r": "1", "7:u": "1"}


async def test_every_minute_in_the_index_is_flushed(redis, counter, flusher, sink, now):
    for age in range(5):
        await counter.record(make_link(), ip=f"203.0.113.{age}", user_agent="UA", referer_host=None, now=now - timedelta(minutes=age))
    assert await flusher.flush_buckets_once() == 5
    assert sorted(row.bucket_start for batch in sink.buckets for row in batch) == [
        (now - timedelta(minutes=age)).replace(second=0) for age in reversed(range(5))
    ]


async def test_events_recorded_before_the_group_existed_are_not_lost(redis, counter, sink, settings, now):
    await counter.record(make_link(), ip="203.0.113.1", user_agent="UA", referer_host=None, now=now)
    flusher = Flusher(redis, sink, settings.model_copy(update={"consumer_name": "late"}))
    await flusher.ensure_group()
    assert await flusher.flush_events_once() == 1


async def test_draining_pending_entries_reports_every_batch(redis, counter, flusher, sink, now):
    for i in range(5):
        await counter.record(make_link(), ip=f"203.0.113.{i}", user_agent="UA", referer_host=None, now=now)
    await redis.xreadgroup(keys.EVENTS_GROUP, "test-1", {keys.EVENTS_STREAM: ">"}, count=10)
    assert await pending(redis) == 5
    assert await flusher.drain_own_pending() == 5
    assert len(sink.events) == 5 and await pending(redis) == 0


async def test_an_entry_trimmed_while_pending_does_not_hide_the_ones_after_it(redis, counter, flusher, sink, now):
    for i in range(4):
        await counter.record(make_link(), ip=f"203.0.113.{i}", user_agent="UA", referer_host=None, now=now)
    await redis.xreadgroup(keys.EVENTS_GROUP, "test-1", {keys.EVENTS_STREAM: ">"}, count=10)
    ids = [entry_id for entry_id, _ in await redis.xrange(keys.EVENTS_STREAM)]
    await redis.xdel(keys.EVENTS_STREAM, ids[0])

    flusher._settings = flusher._settings.model_copy(update={"events_batch_size": 10})
    assert await flusher.drain_own_pending() == 3
    assert [event.id for event in sink.events] == ids[1:]
    assert await pending(redis) == 0


@pytest.mark.parametrize("link_id, ok", [("1", True), ("0", False), ("-1", False), (str(MAX_BIGINT), True), (str(MAX_BIGINT + 1), False)])
def test_event_link_ids_must_fit_a_positive_bigint(link_id, ok):
    fields = {"l": link_id, "t": "1790000000000", "u": "0", "v": "0f" * 16, "r": "www.youtube.com"}
    if ok:
        event = parse_event("1-0", fields)
        assert (event.link_id, event.is_unique, event.referer_host) == (int(link_id), False, "www.youtube.com")
    else:
        with pytest.raises(ValueError):
            parse_event("1-0", fields)


@pytest.mark.parametrize("visitor", ["A" * 32, "g" * 32, "a" * 31, "a" * 33, " " + "a" * 31])
def test_event_visitor_hash_must_be_lowercase_hex_of_the_right_length(visitor):
    with pytest.raises(ValueError):
        parse_event("1-0", {"l": "7", "t": "1790000000000", "u": "1", "v": visitor, "r": ""})


@pytest.mark.parametrize(
    "fields, expected",
    [
        ({"1:r": "0", "1:u": "0"}, [(1, 0, 0)]),
        ({f"{MAX_BIGINT}:r": str(MAX_INT)}, [(MAX_BIGINT, MAX_INT, 0)]),
        ({"5:u": "3"}, [(5, 0, 3)]),
        ({"5:r": str(MAX_INT + 1), "5:u": "1"}, [(5, 0, 1)]),
        ({f"{MAX_BIGINT + 1}:r": "1"}, []),
        ({"5:x": "1", "5:r:u": "1", ":r": "1"}, []),
    ],
)
def test_bucket_fields_are_accepted_exactly_up_to_the_column_limits(fields, expected):
    minute = 29307634
    rows = parse_bucket(minute, fields)
    assert [(row.link_id, row.raw, row.unique) for row in rows] == expected
    assert all(row.bucket_start == datetime.fromtimestamp(minute * 60, tz=UTC) for row in rows)


async def test_a_running_flusher_keeps_up_with_new_clicks_without_errors(redis, counter, flusher, sink, now, caplog):
    import asyncio

    flusher._settings = flusher._settings.model_copy(update={"events_block_ms": 100, "flush_interval": 0.05})
    stop = asyncio.Event()
    task = asyncio.create_task(flusher.run(stop))

    async def settle(events: int, raw: int) -> None:
        for _ in range(25):
            await asyncio.sleep(0.02)
            if len(sink.events) == events and sink.buckets and sink.buckets[-1][0].raw == raw:
                return
        raise AssertionError(f"not flushed within 0.5s: {len(sink.events)} events, buckets {sink.buckets[-1:]}")

    try:
        for i in range(1, 4):
            await counter.record(make_link(), ip=f"203.0.113.{i}", user_agent="UA", referer_host=None, now=now)
            await settle(i, i)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=5)
    assert "failed" not in caplog.text


@pytest.mark.parametrize("minute, kept", [(_FIRST_MINUTE, True), (_FIRST_MINUTE - 1, False), (_LAST_MINUTE - 1, True), (_LAST_MINUTE, False)])
async def test_bucket_minutes_are_accepted_exactly_inside_the_supported_range(redis, flusher, sink, minute, kept):
    await redis.zadd(keys.BUCKET_INDEX, {str(minute): minute})
    await redis.hset(keys.bucket(minute), mapping={"7:r": "1"})
    assert await flusher.flush_buckets_once() == (1 if kept else 0)
