from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from redis.asyncio import Redis

from tests.tracking.conftest import FINGERPRINT_SECRET
from tracking.clicks import ClickCounter
from tracking.flusher import ClickEvent, Flusher, PostgresSink
from tracking.links import CachedLinkStore, LinkExists, LinkInput, PostgresLinkStore
from tracking.migrate import migrate
from tracking.stats import Granularity, GroupBy, PostgresStats, Totals

CAMPAIGN = "11111111-1111-1111-1111-111111111111"
CREATOR_A = "22222222-2222-2222-2222-222222222222"
CREATOR_B = "33333333-3333-3333-3333-333333333333"


def as_user(url: str, user: str, password: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname if parts.port is None else f"{parts.hostname}:{parts.port}"
    return urlunsplit(parts._replace(netloc=f"{user}:{password}@{host}"))


@pytest.fixture
async def pool(postgres_url):
    conn = await asyncpg.connect(postgres_url)
    try:
        await conn.execute("DROP TABLE IF EXISTS click_events, click_buckets, links, schema_migrations")
        assert await migrate(conn) == ["0001_init.sql", "0002_app_role.sql", "0003_opaque_ids.sql"]
        assert await migrate(conn) == []
    finally:
        await conn.close()
    pool = await asyncpg.create_pool(postgres_url, min_size=1, max_size=3)
    yield pool
    await pool.close()


@pytest.fixture
async def real_redis(redis_url):
    client = Redis.from_url(redis_url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def link_input():
    def make(creator=CREATOR_A, platform="youtube", **overrides):
        data = dict(target_url="https://store.example.com/app/1", campaign_id=CAMPAIGN, creator_id=creator, platform=platform)
        data.update(overrides)
        return LinkInput(**data)

    return make


async def test_link_store_round_trip(pool, real_redis, link_input):
    store = CachedLinkStore(PostgresLinkStore(pool), real_redis, positive_ttl=60, negative_ttl=5)
    start = datetime(2026, 9, 1, tzinfo=UTC)

    created = await store.insert("code-one", link_input(starts_at=start, ends_at=start + timedelta(days=30)))
    assert created.id > 0 and created.active and created.starts_at == start
    with pytest.raises(LinkExists):
        await store.insert("code-one", link_input())

    assert await store.get_by_code("code-one") == created
    assert await store.get_by_code("code-one") == created  # from cache
    assert await store.get_by_code("nope-nope") is None

    updated = await store.upsert("code-one", link_input(platform="kick"))
    assert updated.id == created.id and updated.platform == "kick" and updated.updated_at >= created.updated_at
    assert (await store.get_by_code("code-one")).platform == "kick"

    other = await store.upsert("code-two", link_input(creator=CREATOR_B))
    assert [l.code for l in await store.list_by_campaign(CAMPAIGN)] == ["code-one", "code-two"]

    deactivated = await store.deactivate("code-one")
    assert deactivated is not None and not deactivated.active
    assert (await store.get_by_code("code-one")).active is False
    assert await store.deactivate("missing-code") is None
    assert other.active


async def test_clicks_flow_from_redis_to_postgres_and_stats(pool, real_redis, settings, link_input):
    store = PostgresLinkStore(pool)
    link_a = await store.upsert("code-a", link_input())
    link_b = await store.upsert("code-b", link_input(creator=CREATOR_B, platform="twitch"))
    counter = ClickCounter(real_redis, secret=FINGERPRINT_SECRET.encode(), rate_limit_per_minute=100, max_unique_per_ip_per_day=100, bucket_ttl=3600, stream_maxlen=10_000)

    now = datetime.now(UTC).replace(second=30, microsecond=0)
    earlier = now - timedelta(minutes=10)
    await counter.record(link_a, ip="203.0.113.1", user_agent="UA", referer_host="www.youtube.com", now=earlier)
    await counter.record(link_a, ip="203.0.113.1", user_agent="UA", referer_host="www.youtube.com", now=earlier)
    await counter.record(link_a, ip="203.0.113.2", user_agent="UA", referer_host=None, now=now)
    await counter.record(link_b, ip="203.0.113.3", user_agent="UA", referer_host="www.twitch.tv", now=now)

    flusher = Flusher(real_redis, PostgresSink(pool), settings, clock=lambda: now)
    await flusher.ensure_group()
    assert await flusher.flush_events_once() == 4
    assert await flusher.flush_events_once() == 0
    assert await flusher.flush_buckets_once() == 3
    # the older minute was closed by the first flush
    assert await flusher.flush_buckets_once() == 2

    assert await pool.fetchval("SELECT count(*) FROM click_events") == 4
    assert await pool.fetchval("SELECT count(*) FROM click_buckets") == 3

    stats = PostgresStats(pool)
    assert await stats.link_totals(link_a.id) == Totals(raw=3, unique=2)
    assert await stats.link_totals(link_b.id) == Totals(raw=1, unique=1)
    assert await stats.link_totals(999_999) == Totals(raw=0, unique=0)

    series = await stats.link_series(link_a.id, earlier - timedelta(hours=1), now + timedelta(hours=1), Granularity.minute)
    assert [(p.raw, p.unique) for p in series] == [(2, 1), (1, 1)]
    assert series[0].bucket == earlier.replace(second=0)

    hourly = await stats.campaign_series(CAMPAIGN, earlier - timedelta(hours=1), now + timedelta(hours=1), Granularity.day, None)
    assert sum(p.raw for p in hourly) == 4 and sum(p.unique for p in hourly) == 3

    by_platform = await stats.campaign_series(CAMPAIGN, earlier - timedelta(hours=1), now + timedelta(hours=1), Granularity.day, GroupBy.platform)
    per_platform: dict[str, int] = {}
    for p in by_platform:  # the ten minutes may straddle midnight UTC
        per_platform[p.group] = per_platform.get(p.group, 0) + p.raw
    assert per_platform == {"youtube": 3, "twitch": 1}
    by_creator = await stats.campaign_series(CAMPAIGN, earlier - timedelta(hours=1), now + timedelta(hours=1), Granularity.day, GroupBy.creator)
    assert {p.group for p in by_creator} == {str(CREATOR_A), str(CREATOR_B)}

    links = await stats.campaign_links(CAMPAIGN)
    assert [(l.code, t.raw, t.unique) for l, t in links] == [("code-a", 3, 2), ("code-b", 1, 1)]

    referers = await stats.campaign_referers(CAMPAIGN, earlier - timedelta(hours=1), now + timedelta(hours=1), limit=10)
    # NULL sorts last
    assert [(r.host, r.clicks) for r in referers] == [("www.youtube.com", 2), ("www.twitch.tv", 1), (None, 1)]


async def test_sink_drops_only_the_offending_row(pool, real_redis, link_input, caplog):
    link = await PostgresLinkStore(pool).upsert("code-x", link_input())
    sink = PostgresSink(pool)
    now = datetime.now(UTC)
    good = ClickEvent(id="1-0", link_id=link.id, occurred_at=now, is_unique=True, visitor_hash="a" * 32, referer_host=None)
    orphan = ClickEvent(id="1-1", link_id=999_999, occurred_at=now, is_unique=True, visitor_hash="b" * 32, referer_host=None)
    await sink.write_events([good, orphan])
    assert await pool.fetchval("SELECT count(*) FROM click_events") == 1
    assert "dropping click event" in caplog.text

    assert await sink.prune_events(now + timedelta(seconds=1), 10) == 1
    assert await sink.prune_events(now + timedelta(seconds=1), 10) == 0

    old = [
        ClickEvent(id=f"2-{i}", link_id=link.id, occurred_at=now - timedelta(days=100), is_unique=False, visitor_hash="d" * 32, referer_host=None)
        for i in range(3)
    ]
    await sink.write_events([*old, good])
    assert [await sink.prune_events(now - timedelta(days=1), 2) for _ in range(3)] == [2, 1, 0]
    assert await pool.fetchval("SELECT count(*) FROM click_events") == 1


async def test_upsert_keeps_owner_and_buckets_never_decrease(pool, real_redis, link_input):
    from tracking.flusher import BucketRow
    from tracking.links import LinkOwnerMismatch

    store = PostgresLinkStore(pool)
    link = await store.upsert("code-own", link_input())
    with pytest.raises(LinkOwnerMismatch):
        await store.upsert("code-own", link_input(creator=CREATOR_B))
    assert (await store.get_by_code("code-own")).creator_id == CREATOR_A

    sink = PostgresSink(pool)
    minute = datetime(2026, 9, 21, 12, 34, tzinfo=UTC)
    await sink.write_buckets([BucketRow(link.id, minute, 50, 40)])
    await sink.write_buckets([BucketRow(link.id, minute, 1, 1)])  # a re-created bucket after a Redis loss
    await sink.write_buckets([BucketRow(link.id, minute, 60, 40)])
    assert await PostgresStats(pool).link_totals(link.id) == Totals(raw=60, unique=40)

    await sink.write_buckets([BucketRow(link.id, minute, 61, 41), BucketRow(999_999, minute, 1, 1)])
    assert await PostgresStats(pool).link_totals(link.id) == Totals(raw=61, unique=41)


async def test_sink_drops_rows_postgres_cannot_encode(pool, real_redis, link_input, caplog):
    from tracking.flusher import BucketRow

    link = await PostgresLinkStore(pool).upsert("code-big", link_input())
    minute = datetime(2026, 9, 21, 12, 34, tzinfo=UTC)
    await PostgresSink(pool).write_buckets([BucketRow(link.id, minute, 2**40, 1), BucketRow(link.id, minute.replace(minute=35), 4, 2)])
    assert await PostgresStats(pool).link_totals(link.id) == Totals(raw=4, unique=2)
    assert "dropping bucket" in caplog.text


async def test_app_role_gets_only_the_privileges_it_needs(pool, real_redis, link_input, settings, postgres_url):
    admin = await asyncpg.connect(postgres_url)
    try:
        role_exists = await admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname = 'tracking_app'")
        await admin.execute(f"{'ALTER' if role_exists else 'CREATE'} ROLE tracking_app LOGIN PASSWORD 'app-pw'")
        await admin.execute("DROP TABLE IF EXISTS click_events, click_buckets, links, schema_migrations")
        assert await migrate(admin) == ["0001_init.sql", "0002_app_role.sql", "0003_opaque_ids.sql"]
    finally:
        await admin.close()

    app_url = as_user(postgres_url, "tracking_app", "app-pw")
    app_pool = await asyncpg.create_pool(app_url, min_size=1, max_size=2)
    try:
        link = await PostgresLinkStore(app_pool).upsert("code-role", link_input())
        counter = ClickCounter(real_redis, secret=FINGERPRINT_SECRET.encode(), rate_limit_per_minute=100, max_unique_per_ip_per_day=3, bucket_ttl=3600, stream_maxlen=1000)
        now = datetime.now(UTC)
        await counter.record(link, ip="203.0.113.1", user_agent="UA", referer_host=None, now=now)
        flusher = Flusher(real_redis, PostgresSink(app_pool), settings, clock=lambda: now)
        await flusher.ensure_group()
        assert await flusher.flush_events_once() == 1
        assert await flusher.flush_buckets_once() == 1
        assert await PostgresSink(app_pool).prune_events(now + timedelta(days=1), 100) == 1
        assert await PostgresStats(app_pool).link_totals(link.id) == Totals(raw=1, unique=1)
        assert (await PostgresLinkStore(app_pool).deactivate("code-role")).active is False

        for statement in (
            "DELETE FROM links",
            "DROP TABLE click_buckets",
            "SELECT * FROM schema_migrations",
            "DELETE FROM click_buckets",
            "CREATE TABLE evil (x int)",
            "ALTER TABLE links ADD COLUMN evil int",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await app_pool.execute(statement)
    finally:
        await app_pool.close()


async def test_campaign_service_ids_are_stored_and_grouped_as_given(pool, real_redis):
    store = PostgresLinkStore(pool)
    body = dict(target_url="https://store.example.com/app/9", campaign_id="42")
    first = await store.upsert("int-id-a", LinkInput(**body, creator_id="7"))
    await store.upsert("int-id-b", LinkInput(**body, creator_id="8"))
    assert (first.campaign_id, first.creator_id) == ("42", "7")
    assert [link.code for link, _ in await PostgresStats(pool).campaign_links("42")] == ["int-id-a", "int-id-b"]
    now = datetime.now(UTC)
    series = await PostgresStats(pool).campaign_series("42", now - timedelta(days=1), now, Granularity.day, GroupBy.creator)
    assert series == []


async def test_databases_created_with_uuid_ids_are_migrated_to_opaque_ids(postgres_url):
    from importlib.resources import files

    conn = await asyncpg.connect(postgres_url)
    try:
        await conn.execute("DROP TABLE IF EXISTS click_events, click_buckets, links, schema_migrations")
        await conn.execute(
            "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        await conn.execute(files("tracking").joinpath("migrations/0001_init.sql").read_text(encoding="utf-8"))
        await conn.execute("INSERT INTO schema_migrations (version) VALUES ('0001_init.sql')")
        await conn.execute(
            "INSERT INTO links (code, campaign_id, creator_id, target_url) VALUES ($1, $2, $3, $4)",
            "old-uuid-link", CAMPAIGN, CREATOR_A, "https://store.example.com/old",
        )
        assert (await conn.fetchrow("SELECT data_type FROM information_schema.columns WHERE table_name = 'links' AND column_name = 'campaign_id'"))[0] == "uuid"

        assert await migrate(conn) == ["0002_app_role.sql", "0003_opaque_ids.sql"]
    finally:
        await conn.close()

    pool = await asyncpg.create_pool(postgres_url, min_size=1, max_size=2)
    try:
        store = PostgresLinkStore(pool)
        old = await store.get_by_code("old-uuid-link")
        assert (old.campaign_id, old.creator_id) == (CAMPAIGN, CREATOR_A)
        new = await store.upsert("int-id-link", LinkInput(target_url="https://store.example.com/new", campaign_id="42", creator_id="7"))
        assert (new.campaign_id, new.creator_id) == ("42", "7")
        with pytest.raises(asyncpg.CheckViolationError):
            await pool.execute("UPDATE links SET campaign_id = 'has space' WHERE code = 'int-id-link'")
    finally:
        await pool.close()


async def test_an_entry_trimmed_while_pending_is_acknowledged_on_real_redis(pool, real_redis, settings, link_input, caplog):
    link = await PostgresLinkStore(pool).upsert("code-trim", link_input())
    counter = ClickCounter(real_redis, secret=FINGERPRINT_SECRET.encode(), rate_limit_per_minute=100, max_unique_per_ip_per_day=100, bucket_ttl=3600, stream_maxlen=1000)
    now = datetime.now(UTC)
    for i in range(3):
        await counter.record(link, ip=f"203.0.113.{i}", user_agent="UA", referer_host=None, now=now)
    flusher = Flusher(real_redis, PostgresSink(pool), settings.model_copy(update={"consumer_name": "trim"}))
    await flusher.ensure_group()
    await real_redis.xreadgroup("pg", "trim", {"trk:events": ">"}, count=10)
    first = (await real_redis.xrange("trk:events", count=1))[0][0]
    await real_redis.xdel("trk:events", first)

    assert await flusher.drain_own_pending() == 2
    assert (await real_redis.xpending("trk:events", "pg"))["pending"] == 0
    assert await pool.fetchval("SELECT count(*) FROM click_events") == 2
    assert "malformed" not in caplog.text


async def test_concurrent_migrations_apply_each_file_exactly_once(postgres_url):
    import asyncio

    setup = await asyncpg.connect(postgres_url)
    try:
        await setup.execute("DROP TABLE IF EXISTS click_events, click_buckets, links, schema_migrations")
    finally:
        await setup.close()
    connections = [await asyncpg.connect(postgres_url) for _ in range(4)]
    try:
        results = await asyncio.gather(*(migrate(conn) for conn in connections))
    finally:
        for conn in connections:
            await conn.close()
    assert sorted(results, key=len) == [[], [], [], ["0001_init.sql", "0002_app_role.sql", "0003_opaque_ids.sql"]]
