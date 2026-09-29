import asyncio
import os
import signal
import sys
import time
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from redis.asyncio import Redis

from tests.tracking.conftest import FINGERPRINT_SECRET, SERVICE_TOKEN
from tests.tracking.fakes import http_client
from tracking import keys
from tracking.app import create_app
from tracking.clicks import ClickCounter
from tracking.flusher import Flusher, PostgresSink
from tracking.links import LinkInput, PostgresLinkStore
from tracking.migrate import migrate

CAMPAIGN = "campaign_42"
CREATOR = "creator_7"
TARGET = "https://store.example.com/app/1?utm_source=jestr"
AUTH = {"authorization": f"Bearer {SERVICE_TOKEN}"}
BROWSER = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0", "referer": "https://www.youtube.com/watch?v=1"}


@pytest.fixture
async def database(postgres_url):
    conn = await asyncpg.connect(postgres_url)
    try:
        await conn.execute("DROP TABLE IF EXISTS click_events, click_buckets, links, schema_migrations")
        await migrate(conn)
    finally:
        await conn.close()
    pool = await asyncpg.create_pool(postgres_url, min_size=1, max_size=2)
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
def service_settings(settings, postgres_url, redis_url):
    return settings.model_copy(
        update={"database_url": postgres_url, "redis_url": redis_url, "rate_limit_per_minute": 60, "count_timeout": 2.0}
    )


async def test_link_created_over_http_is_redirected_counted_flushed_and_reported(database, real_redis, service_settings, caplog):
    app = create_app(service_settings)
    async with app.router.lifespan_context(app):
        async with http_client(app) as client:
            assert (await client.get("/readyz")).json() == {"redis": "ok", "database": "ok"}

            created = await client.post(
                "/internal/links",
                json={"target_url": TARGET, "campaign_id": CAMPAIGN, "creator_id": CREATOR, "platform": "youtube"},
                headers=AUTH,
            )
            assert created.status_code == 201, created.text
            code = created.json()["code"]

            for _ in range(3):
                resp = await client.get(f"/r/{code}", headers=BROWSER)
                assert resp.status_code == 302 and resp.headers["location"] == TARGET
            async with http_client(app, peer=("198.51.100.20", 4000)) as other:
                assert (await other.get(f"/r/{code}", headers=BROWSER)).status_code == 302
            assert (await client.get(f"/r/{code}", headers={"user-agent": "Slackbot-LinkExpanding 1.0"})).status_code == 302

            assert await real_redis.xlen(keys.EVENTS_STREAM) == 4
            flusher = Flusher(real_redis, PostgresSink(database), service_settings.model_copy(update={"consumer_name": "it"}))
            await flusher.ensure_group()
            assert await flusher.flush_events_once() == 4
            assert await flusher.flush_buckets_once() == await database.fetchval("SELECT count(*) FROM click_buckets") >= 1

            link = (await client.get(f"/internal/links/{code}", headers=AUTH)).json()
            assert link["totals"] == {"raw": 4, "unique": 2}
            assert (link["campaign_id"], link["creator_id"], link["platform"]) == (CAMPAIGN, CREATOR, "youtube")

            listed = (await client.get(f"/internal/campaigns/{CAMPAIGN}/links", headers=AUTH)).json()
            assert [(row["code"], row["totals"]) for row in listed] == [(code, {"raw": 4, "unique": 2})]

            since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
            referers = (await client.get(f"/internal/campaigns/{CAMPAIGN}/referers", params={"from": since}, headers=AUTH)).json()
            assert referers == [{"host": "www.youtube.com", "clicks": 4}]
            series = (
                await client.get(f"/internal/campaigns/{CAMPAIGN}/stats", params={"from": since, "group_by": "creator"}, headers=AUTH)
            ).json()
            assert {p["group"] for p in series["points"]} == {CREATOR}
            assert sum(p["raw"] for p in series["points"]) == 4 and sum(p["unique"] for p in series["points"]) == 2

            assert (await client.delete(f"/internal/links/{code}", headers=AUTH)).status_code == 204
            assert (await client.get(f"/r/{code}", headers=BROWSER)).status_code == 404
            assert await real_redis.xlen(keys.EVENTS_STREAM) == 4
            assert 0 < await real_redis.ttl(keys.link(code)) <= service_settings.link_cache_ttl

            for _ in range(2):
                assert (await client.get("/r/never-issued", headers=BROWSER)).status_code == 404
            assert await real_redis.get(keys.link("never-issued")) == "-"
            assert 0 < await real_redis.ttl(keys.link("never-issued")) <= service_settings.negative_cache_ttl
            [budget] = await real_redis.keys("trk:miss:*")
            assert await real_redis.get(budget) == "1"
            assert "unreadable" not in caplog.text

    async with http_client(app) as client:
        assert (await client.get("/readyz")).json()["database"] == "fail"


async def test_redirects_keep_working_while_redis_is_down(database, service_settings, caplog):
    link = await PostgresLinkStore(database).upsert(
        "live-code", LinkInput(target_url=TARGET, campaign_id=CAMPAIGN, creator_id=CREATOR)
    )
    settings = service_settings.model_copy(update={"redis_url": "redis://127.0.0.1:1/0", "count_timeout": 0.25})
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with http_client(app) as client:
            resp = await client.get("/r/live-code", headers=BROWSER)
            assert resp.status_code == 302 and resp.headers["location"] == link.target_url
            assert (await client.get("/r/missing-code", headers=BROWSER)).status_code == 404

            ready = await client.get("/readyz")
            assert ready.status_code == 503 and ready.json() == {"redis": "fail", "database": "ok"}
    assert f"click not counted for link {link.id}" in caplog.text


async def test_app_refuses_to_start_without_its_database(settings):
    app = create_app(settings.model_copy(update={"database_url": "postgresql://nobody:nothing@127.0.0.1:1/none"}))
    with pytest.raises(OSError):
        async with app.router.lifespan_context(app):
            pass


async def test_flusher_run_moves_live_clicks_into_postgres_until_stopped(database, real_redis, service_settings):
    app = create_app(service_settings)
    settings = service_settings.model_copy(
        update={"consumer_name": "it-run", "events_block_ms": 100, "flush_interval": 0.05, "bucket_close_grace": 60}
    )
    stop = asyncio.Event()
    async with app.router.lifespan_context(app):
        async with http_client(app) as client:
            created = await client.post(
                "/internal/links",
                json={"target_url": TARGET, "campaign_id": CAMPAIGN, "creator_id": CREATOR},
                headers=AUTH,
            )
            code = created.json()["code"]
            run = asyncio.create_task(Flusher(real_redis, PostgresSink(database), settings).run(stop))
            try:
                for peer in ("203.0.113.1", "203.0.113.2", "203.0.113.2"):
                    async with http_client(app, peer=(peer, 1000)) as visitor:
                        assert (await visitor.get(f"/r/{code}", headers=BROWSER)).status_code == 302

                async def persisted() -> tuple[int, int]:
                    return await database.fetchrow(
                        "SELECT (SELECT count(*) FROM click_events), (SELECT coalesce(sum(raw_clicks), 0) FROM click_buckets)"
                    )

                for _ in range(100):
                    if tuple(await persisted()) == (3, 3):
                        break
                    await asyncio.sleep(0.05)
                assert tuple(await persisted()) == (3, 3)
            finally:
                stop.set()
                await asyncio.wait_for(run, timeout=5)

    pending = await real_redis.xpending(keys.EVENTS_STREAM, keys.EVENTS_GROUP)
    assert pending["pending"] == 0
    assert await database.fetchval("SELECT count(*) FROM click_events WHERE is_unique") == 2


def process_env(**values: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("TRACKING_")}
    env.update(TRACKING_SERVICE_TOKEN=SERVICE_TOKEN, TRACKING_FINGERPRINT_SECRET=FINGERPRINT_SECRET, **values)
    return env


async def run_module(module: str, env: dict[str, str], cwd) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", module, env=env, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    output, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    return proc.returncode, output.decode()


async def test_the_migrate_command_uses_the_owner_account_and_is_idempotent(postgres_url, tmp_path):
    conn = await asyncpg.connect(postgres_url)
    try:
        await conn.execute("DROP TABLE IF EXISTS click_events, click_buckets, links, schema_migrations")
    finally:
        await conn.close()
    env = process_env(
        TRACKING_DATABASE_URL="postgresql://nobody:nothing@127.0.0.1:1/none", TRACKING_MIGRATE_DATABASE_URL=postgres_url
    )

    code, output = await run_module("tracking.migrate", env, tmp_path)
    assert code == 0, output
    assert "applied 3 migration(s): 0001_init.sql, 0002_app_role.sql, 0003_opaque_ids.sql" in output
    code, output = await run_module("tracking.migrate", env, tmp_path)
    assert code == 0, output
    assert "applied 0 migration(s): none" in output


async def test_the_flusher_process_moves_clicks_and_stops_cleanly(database, real_redis, postgres_url, redis_url, tmp_path):
    link = await PostgresLinkStore(database).upsert("proc-code", LinkInput(target_url=TARGET, campaign_id=CAMPAIGN, creator_id=CREATOR))
    counter = ClickCounter(
        real_redis, secret=FINGERPRINT_SECRET.encode(), rate_limit_per_minute=60, max_unique_per_ip_per_day=3,
        bucket_ttl=3600, stream_maxlen=1000,
    )
    await counter.record(link, ip="203.0.113.1", user_agent="UA", referer_host=None, now=datetime.now(UTC))

    env = process_env(
        TRACKING_DATABASE_URL=postgres_url, TRACKING_REDIS_URL=redis_url, TRACKING_EVENTS_BLOCK_MS="100",
        TRACKING_FLUSH_INTERVAL="0.1", TRACKING_CONSUMER_NAME="proc-test",
    )
    kwargs = {"creationflags": 0x00000200} if sys.platform == "win32" else {}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tracking.flusher", env=env, cwd=tmp_path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **kwargs,
    )
    try:
        for _ in range(200):
            if await database.fetchval("SELECT count(*) FROM click_events") and await database.fetchval("SELECT count(*) FROM click_buckets"):
                break
            await asyncio.sleep(0.05)
        assert await database.fetchval("SELECT count(*) FROM click_events") == 1
        assert await database.fetchval("SELECT sum(raw_clicks) FROM click_buckets") == 1
    finally:
        proc.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGTERM)
        output, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
    if sys.platform != "win32":
        assert proc.returncode == 0, output.decode()
        assert "flusher stopped" in output.decode()


async def test_an_idle_flusher_waits_on_redis_instead_of_spinning(real_redis, service_settings, monkeypatch):
    calls = 0
    read = real_redis.xreadgroup

    async def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await read(*args, **kwargs)

    monkeypatch.setattr(real_redis, "xreadgroup", counted)
    settings = service_settings.model_copy(update={"consumer_name": "idle", "events_block_ms": 200, "events_retention_days": 0})
    stop = asyncio.Event()
    task = asyncio.create_task(Flusher(real_redis, PostgresSink(None), settings).run(stop))
    await asyncio.sleep(1.0)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert 2 <= calls <= 10


async def test_a_redis_that_stops_answering_cannot_stall_redirects(database, service_settings, caplog):
    async def swallow(reader, writer):
        await reader.read()

    server = await asyncio.start_server(swallow, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    link = await PostgresLinkStore(database).upsert(
        "stall-code", LinkInput(target_url=TARGET, campaign_id=CAMPAIGN, creator_id=CREATOR)
    )
    app = create_app(service_settings.model_copy(update={"redis_url": f"redis://127.0.0.1:{port}/0", "count_timeout": 0.25}))
    try:
        async with app.router.lifespan_context(app):
            async with http_client(app) as client:
                started = time.perf_counter()
                resp = await asyncio.wait_for(client.get("/r/stall-code", headers=BROWSER), timeout=10)
                assert resp.status_code == 302 and resp.headers["location"] == link.target_url
                assert time.perf_counter() - started < 3
    finally:
        server.close()
    assert f"click not counted for link {link.id}" in caplog.text
