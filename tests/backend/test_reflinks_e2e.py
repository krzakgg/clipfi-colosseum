from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import asyncpg
import httpx
import pytest

from tests.backend.conftest import (
    FINGERPRINT_SECRET,
    REDIRECT_BASE,
    SERVICE_TOKEN,
    TRACKING_DATABASE,
    WAGGI_DATABASE,
    postgres_url,
)

POSTGRES_URL = postgres_url()
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="no PostgreSQL: Docker is not running and WAGGI_TEST_POSTGRES_URL is not set")
tracking = pytest.importorskip("tracking")

BROWSER = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/130.0"}
SHOP = "https://shop.example.com/game"


@dataclass
class TrackingStack:
    app: object
    redis: object
    pool: asyncpg.Pool
    settings: object

    def public(self, peer: str = "203.0.113.9") -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=self.app, client=(peer, 40000))
        return httpx.AsyncClient(transport=transport, base_url="http://localhost:8080")

    def internal(self) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=self.app)
        return httpx.AsyncClient(
            transport=transport, base_url="http://api-internal", headers={"authorization": f"Bearer {SERVICE_TOKEN}"}
        )

    async def flush(self) -> None:
        from tracking.flusher import Flusher, PostgresSink

        flusher = Flusher(self.redis, PostgresSink(self.pool), self.settings)
        await flusher.ensure_group()
        await flusher.flush_events_once()
        await flusher.flush_buckets_once()


@pytest.fixture(scope="session")
async def databases():
    admin = await asyncpg.connect(f"{POSTGRES_URL}/postgres")
    try:
        for name in (WAGGI_DATABASE, TRACKING_DATABASE):
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()


@pytest.fixture(scope="session")
async def tracking_stack(databases, redis_url):
    from redis.asyncio import Redis

    from tracking.app import create_app
    from tracking.clicks import ClickCounter
    from tracking.config import Settings
    from tracking.deps import Deps
    from tracking.links import CachedLinkStore, PostgresLinkStore
    from tracking.migrate import migrate
    from tracking.stats import PostgresStats

    database_url = f"{POSTGRES_URL}/{TRACKING_DATABASE}"
    connection = await asyncpg.connect(database_url)
    try:
        await migrate(connection)
    finally:
        await connection.close()

    settings = Settings(
        database_url=database_url, service_token=SERVICE_TOKEN, fingerprint_secret=FINGERPRINT_SECRET, _env_file=None
    )
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=4)
    redis = Redis.from_url(redis_url, decode_responses=True)
    await redis.flushdb()

    async def ready() -> None:
        return None

    app = create_app(settings)
    app.state.deps = Deps(
        links=CachedLinkStore(
            PostgresLinkStore(pool),
            redis,
            positive_ttl=settings.link_cache_ttl,
            negative_ttl=settings.negative_cache_ttl,
            miss_limit_per_minute=settings.miss_limit_per_minute,
        ),
        counter=ClickCounter(
            redis,
            secret=FINGERPRINT_SECRET.encode(),
            rate_limit_per_minute=settings.rate_limit_per_minute,
            max_unique_per_ip_per_day=settings.max_unique_per_ip_per_day,
            bucket_ttl=settings.bucket_ttl,
            stream_maxlen=settings.stream_maxlen,
        ),
        stats=PostgresStats(pool),
        check_redis=ready,
        check_database=ready,
        close=ready,
    )
    yield TrackingStack(app=app, redis=redis, pool=pool, settings=settings)
    await pool.close()
    await redis.aclose()


@pytest.fixture(scope="session")
async def waggi_app(databases, tracking_stack):
    import database
    import main
    from tracking_client import TrackingClient

    async with database.engine.begin() as connection:
        await connection.run_sync(database.Base.metadata.create_all)
    main.app.state.tracking = TrackingClient(
        "http://api-internal", SERVICE_TOKEN, REDIRECT_BASE, transport=httpx.ASGITransport(app=tracking_stack.app)
    )
    yield main.app
    await main.app.state.tracking.aclose()
    await database.engine.dispose()


@pytest.fixture(autouse=True)
async def clean(waggi_app, tracking_stack):
    from sqlalchemy import text

    import database

    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE campaign_ref_links, submissions, campaign_applications, campaigns, creators, companies "
                "RESTART IDENTITY CASCADE"
            )
        )
    await tracking_stack.pool.execute("TRUNCATE click_events, click_buckets, links RESTART IDENTITY CASCADE")
    await tracking_stack.redis.flushdb()


@pytest.fixture
async def api(waggi_app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=waggi_app), base_url="http://waggi") as client:
        yield client


@dataclass
class World:
    company: dict
    creator: dict
    campaign: dict


async def build_world(api, **campaign_fields) -> World:
    company = (await api.post("/api/companies", json={"name": "Acme", "email": "acme@example.com", "password": "acme-pass-1"})).json()
    creator = (await api.post("/api/creators", json={"username": "streamer", "email": "s@example.com", "password": "streamer-pass"})).json()
    response = await api.post(
        "/api/campaigns",
        json={"company_id": company["id"], "title": "Launch", "total_budget": "1000.00", "payout_per_click": "0.50", **campaign_fields},
    )
    assert response.status_code == 201, response.text
    return World(company=company, creator=creator, campaign=response.json())


async def accept_creator(api, world: World) -> None:
    application = (await api.post("/api/applications", json={"campaign_id": world.campaign["id"], "creator_id": world.creator["id"]})).json()
    response = await api.patch(
        f"/api/applications/{application['id']}/status", json={"status": "accepted", "company_id": world.company["id"]}
    )
    assert response.status_code == 200, response.text


async def create_reflink(api, world: World, url: str = SHOP) -> httpx.Response:
    return await api.post(
        "/api/reflinks",
        json={"campaign_id": world.campaign["id"], "creator_id": world.creator["id"], "company_id": world.company["id"], "url": url},
    )


async def test_clicks_flow_from_the_tracking_service_to_the_campaign_dashboard(api, tracking_stack):
    world = await build_world(api)
    await accept_creator(api, world)

    created = await create_reflink(api, world)
    assert created.status_code == 201, created.text
    link = created.json()
    assert link["public_url"] == f"{REDIRECT_BASE}/{link['code']}"
    assert (link["clicks_count"], link["raw_clicks"], link["click_payout"]) == (0, 0, "0.00")

    async with tracking_stack.public() as visitor:
        for _ in range(3):
            redirect = await visitor.get(f"/r/{link['code']}", headers=BROWSER)
            assert (redirect.status_code, redirect.headers["location"]) == (302, SHOP)
        await visitor.get(f"/r/{link['code']}", headers={"user-agent": "Discordbot/2.0"})
    async with tracking_stack.public(peer="198.51.100.4") as other_visitor:
        await other_visitor.get(f"/r/{link['code']}", headers=BROWSER)
    await tracking_stack.flush()

    listed = await api.get(f"/api/reflinks/campaign/{world.campaign['id']}", params={"company_id": world.company["id"]})
    assert listed.status_code == 200
    [row] = listed.json()
    assert (row["code"], row["clicks_count"], row["raw_clicks"], row["click_payout"]) == (link["code"], 2, 4, "1.00")

    single = (await api.get(f"/api/reflinks/{link['code']}")).json()
    assert (single["clicks_count"], single["raw_clicks"]) == (2, 4)


async def test_the_campaign_service_no_longer_redirects_or_counts_itself(api):
    world = await build_world(api)
    await accept_creator(api, world)
    link = (await create_reflink(api, world)).json()
    assert (await api.get(f"/r/{link['code']}", headers=BROWSER)).status_code == 404


async def test_reflinks_only_for_creators_accepted_into_the_campaign(api):
    world = await build_world(api)
    response = await create_reflink(api, world)
    assert response.status_code == 409
    await api.post("/api/applications", json={"campaign_id": world.campaign["id"], "creator_id": world.creator["id"]})
    assert (await create_reflink(api, world)).status_code == 409


async def test_target_urls_tracking_refuses_are_reported_as_validation_errors(api, tracking_stack):
    world = await build_world(api)
    await accept_creator(api, world)
    response = await create_reflink(api, world, url="https://user:secret@shop.example.com/")
    assert response.status_code == 422
    assert "credentials" in response.text
    assert (await api.get(f"/api/reflinks/campaign/{world.campaign['id']}", params={"company_id": world.company["id"]})).json() == []
    assert await tracking_stack.pool.fetchval("SELECT count(*) FROM links") == 0


async def test_tracking_outage_blocks_new_reflinks_but_not_the_dashboard(api, waggi_app):
    from tracking_client import TrackingClient

    world = await build_world(api)
    await accept_creator(api, world)
    await create_reflink(api, world)
    newcomer = await add_accepted_creator(api, world, "newcomer")

    def refuse(request):
        raise httpx.ConnectError("tracking is down", request=request)

    working = waggi_app.state.tracking
    waggi_app.state.tracking = TrackingClient("http://api-internal", SERVICE_TOKEN, REDIRECT_BASE, transport=httpx.MockTransport(refuse))
    try:
        assert (await create_reflink(api, newcomer)).status_code == 503
        listed = await api.get(f"/api/reflinks/campaign/{world.campaign['id']}", params={"company_id": world.company["id"]})
        assert listed.status_code == 200
        assert [(row["clicks_count"], row["click_payout"]) for row in listed.json()] == [(None, None)]
        assert (await api.delete(f"/api/campaigns/{world.campaign['id']}")).status_code == 503
        assert (await api.get(f"/api/campaigns/{world.campaign['id']}")).status_code == 200
    finally:
        waggi_app.state.tracking = working


async def test_campaign_dates_define_when_clicks_count(api, tracking_stack):
    start = datetime.now(timezone.utc) - timedelta(days=10)
    world = await build_world(api, start_date=start.isoformat(), end_date=(start + timedelta(days=30)).isoformat())
    assert world.campaign["start_date"] is not None
    await accept_creator(api, world)
    code = (await create_reflink(api, world)).json()["code"]
    async with tracking_stack.public(peer="198.51.100.30") as visitor:
        assert (await visitor.get(f"/r/{code}", headers=BROWSER)).status_code == 302
    await tracking_stack.flush()
    assert (await api.get(f"/api/reflinks/{code}")).json()["raw_clicks"] == 1

    ended = {**world.campaign, "end_date": (start + timedelta(days=5)).isoformat()}
    ended.pop("id")
    ended.pop("completed")
    response = await api.put(f"/api/campaigns/{world.campaign['id']}", json=ended)
    assert response.status_code == 200, response.text

    async with tracking_stack.internal() as internal:
        stored = (await internal.get(f"/internal/links/{code}")).json()
    assert datetime.fromisoformat(stored["ends_at"]) == start + timedelta(days=5)

    async with tracking_stack.public() as visitor:
        assert (await visitor.get(f"/r/{code}", headers=BROWSER)).status_code == 302
    await tracking_stack.flush()
    row = (await api.get(f"/api/reflinks/{code}")).json()
    assert row["raw_clicks"] == 1


async def test_deleting_a_campaign_switches_its_reflinks_off(api, tracking_stack):
    world = await build_world(api)
    await accept_creator(api, world)
    code = (await create_reflink(api, world)).json()["code"]

    assert (await api.delete(f"/api/campaigns/{world.campaign['id']}")).status_code == 204
    async with tracking_stack.public() as visitor:
        assert (await visitor.get(f"/r/{code}", headers=BROWSER)).status_code == 404


async def test_clicks_can_no_longer_be_reported_by_clients(api):
    world = await build_world(api, payout_by_content_type={"Short": "20.00"}, payout_per_views="3.00", views_unit_step=1000)
    await accept_creator(api, world)
    submission = (
        await api.post(
            "/api/submissions",
            json={
                "campaign_id": world.campaign["id"],
                "creator_id": world.creator["id"],
                "video_url": "https://youtube.com/watch?v=1",
                "platform": "youtube",
                "content_type": "Short",
            },
        )
    ).json()
    await api.patch(f"/api/submissions/{submission['id']}/review", json={"status": "approved", "company_id": world.company["id"]})

    forged = await api.patch(f"/api/submissions/{submission['id']}/metrics", json={"views_count": 0, "clicks_count": 1_000_000})
    assert forged.status_code == 422
    assert (await api.patch(f"/api/submissions/{submission['id']}/metrics", json={"views_count": -1})).status_code == 422

    measured = await api.patch(f"/api/submissions/{submission['id']}/metrics", json={"views_count": 2500})
    assert measured.status_code == 200, measured.text
    assert Decimal(measured.json()["calculated_payout"]) == Decimal("26.00")
    assert "clicks_count" not in measured.json()


class Interceptor(httpx.AsyncBaseTransport):
    def __init__(self, app, intercept) -> None:
        self._real = httpx.ASGITransport(app=app)
        self._intercept = intercept

    async def handle_async_request(self, request):
        result = await self._intercept(request)
        if isinstance(result, Exception):
            raise result
        if result is not None:
            return result
        return await self._real.handle_async_request(request)


def intercepting_tracking(tracking_stack, intercept):
    from tracking_client import TrackingClient

    return TrackingClient(
        "http://api-internal", SERVICE_TOKEN, REDIRECT_BASE, transport=Interceptor(tracking_stack.app, intercept)
    )


@pytest.fixture
def swap_tracking(waggi_app):
    working = waggi_app.state.tracking

    def swap(client):
        waggi_app.state.tracking = client

    yield swap
    waggi_app.state.tracking = working


def campaign_body(world: World, **changes) -> dict:
    body = {**world.campaign, **changes}
    body.pop("id")
    body.pop("completed")
    return body


async def stored_link(tracking_stack, code: str) -> dict:
    async with tracking_stack.internal() as internal:
        return (await internal.get(f"/internal/links/{code}")).json()


async def add_accepted_creator(api, world: World, name: str) -> World:
    creator = (
        await api.post("/api/creators", json={"username": name, "email": f"{name}@example.com", "password": "creator-pass"})
    ).json()
    other = World(company=world.company, creator=creator, campaign=world.campaign)
    await accept_creator(api, other)
    return other


def failing_on(method: str, occurrence: int):
    calls = {"n": 0}

    async def intercept(request):
        if request.method == method:
            calls["n"] += 1
            if calls["n"] == occurrence:
                return httpx.ConnectError("tracking went away", request=request)
        return None

    return intercept


async def test_date_change_during_an_outage_is_503_and_changes_nothing(api, tracking_stack, swap_tracking):
    start = datetime.now(timezone.utc) - timedelta(days=1)
    world = await build_world(api, start_date=start.isoformat(), end_date=(start + timedelta(days=30)).isoformat())
    await accept_creator(api, world)
    code = (await create_reflink(api, world)).json()["code"]
    before = await stored_link(tracking_stack, code)

    swap_tracking(intercepting_tracking(tracking_stack, failing_on("PUT", 1)))
    response = await api.put(
        f"/api/campaigns/{world.campaign['id']}", json=campaign_body(world, end_date=(start + timedelta(days=2)).isoformat())
    )

    assert response.status_code == 503
    assert (await api.get(f"/api/campaigns/{world.campaign['id']}")).json()["end_date"] == world.campaign["end_date"]
    assert (await stored_link(tracking_stack, code))["ends_at"] == before["ends_at"]


async def test_a_partly_failed_date_change_is_undone_in_tracking(api, tracking_stack, swap_tracking):
    start = datetime.now(timezone.utc) - timedelta(days=1)
    world = await build_world(api, start_date=start.isoformat(), end_date=(start + timedelta(days=30)).isoformat())
    await accept_creator(api, world)
    other = await add_accepted_creator(api, world, "second")
    codes = [(await create_reflink(api, w)).json()["code"] for w in (world, other)]
    before = {code: (await stored_link(tracking_stack, code))["ends_at"] for code in codes}

    swap_tracking(intercepting_tracking(tracking_stack, failing_on("PUT", 2)))
    response = await api.put(
        f"/api/campaigns/{world.campaign['id']}", json=campaign_body(world, end_date=(start + timedelta(days=2)).isoformat())
    )

    assert response.status_code == 503
    assert {code: (await stored_link(tracking_stack, code))["ends_at"] for code in codes} == before


async def test_a_partly_failed_delete_leaves_every_reflink_working(api, tracking_stack, swap_tracking):
    world = await build_world(api)
    await accept_creator(api, world)
    other = await add_accepted_creator(api, world, "second")
    codes = [(await create_reflink(api, w)).json()["code"] for w in (world, other)]

    swap_tracking(intercepting_tracking(tracking_stack, failing_on("DELETE", 2)))
    assert (await api.delete(f"/api/campaigns/{world.campaign['id']}")).status_code == 503

    assert (await api.get(f"/api/campaigns/{world.campaign['id']}")).status_code == 200
    async with tracking_stack.public() as visitor:
        for code in codes:
            assert (await visitor.get(f"/r/{code}", headers=BROWSER)).status_code == 302


async def wait_for_a_lock_wait() -> None:
    import asyncio

    from sqlalchemy import text

    import database

    query = text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND datname = current_database()")
    for _ in range(250):
        async with database.engine.connect() as connection:
            if await connection.scalar(query):
                return
        await asyncio.sleep(0.02)
    raise AssertionError("the concurrent request never waited for the campaign row lock")


async def test_a_reflink_created_while_the_dates_change_gets_the_new_window(api, tracking_stack, swap_tracking):
    import asyncio

    start = datetime.now(timezone.utc) - timedelta(days=1)
    world = await build_world(api, start_date=start.isoformat(), end_date=(start + timedelta(days=30)).isoformat())
    await accept_creator(api, world)
    new_end = start + timedelta(days=2)
    racing: dict = {}

    async def intercept(request):
        if request.method == "POST" and "update" not in racing:
            racing["update"] = asyncio.create_task(
                api.put(f"/api/campaigns/{world.campaign['id']}", json=campaign_body(world, end_date=new_end.isoformat()))
            )
            await wait_for_a_lock_wait()
        return None

    swap_tracking(intercepting_tracking(tracking_stack, intercept))
    created = await create_reflink(api, world)
    updated = await racing["update"]

    assert (created.status_code, updated.status_code) == (201, 200)
    assert datetime.fromisoformat((await stored_link(tracking_stack, created.json()["code"]))["ends_at"]) == new_end


async def test_target_urls_are_measured_after_normalisation(api, tracking_stack):
    world = await build_world(api)
    await accept_creator(api, world)
    response = await create_reflink(api, world, url="https://shop.example.com/" + "é" * 100)
    assert response.status_code == 422
    assert await tracking_stack.pool.fetchval("SELECT count(*) FROM links") == 0


async def test_dates_without_a_timezone_mean_utc_in_both_services(api, tracking_stack):
    world = await build_world(api)
    await accept_creator(api, world)
    code = (await create_reflink(api, world)).json()["code"]

    response = await api.put(f"/api/campaigns/{world.campaign['id']}", json=campaign_body(world, end_date="2030-10-15T00:00:00"))
    assert response.status_code == 200, response.text

    expected = datetime(2030, 10, 15, tzinfo=timezone.utc)
    assert datetime.fromisoformat(response.json()["end_date"]) == expected
    assert datetime.fromisoformat((await stored_link(tracking_stack, code))["ends_at"]) == expected


async def test_reflinks_created_before_the_integration_are_registered_by_the_backfill(api, waggi_app, tracking_stack):
    from sqlalchemy import text

    import database
    from backfill_reflinks import backfill

    world = await build_world(api)
    await accept_creator(api, world)
    async with database.engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO campaign_ref_links (campaign_id, creator_id, code, url) VALUES (:campaign, :creator, :code, :url)"),
            {"campaign": world.campaign["id"], "creator": world.creator["id"], "code": "legacyCode01", "url": SHOP},
        )

    async with tracking_stack.public() as visitor:
        assert (await visitor.get("/r/legacyCode01", headers=BROWSER)).status_code == 404

    for _ in range(2):
        assert await backfill(waggi_app.state.tracking) == 1

    async with tracking_stack.public() as visitor:
        redirect = await visitor.get("/r/legacyCode01", headers=BROWSER)
    assert (redirect.status_code, redirect.headers["location"]) == (302, SHOP)


async def test_click_payout_respects_the_budget_per_creator(api, tracking_stack):
    world = await build_world(api, budget_per_creator="0.50")
    await accept_creator(api, world)
    code = (await create_reflink(api, world)).json()["code"]
    for peer in ("203.0.113.10", "203.0.113.11", "203.0.113.12"):
        async with tracking_stack.public(peer=peer) as visitor:
            await visitor.get(f"/r/{code}", headers=BROWSER)
    await tracking_stack.flush()

    row = (await api.get(f"/api/reflinks/{code}")).json()
    assert (row["clicks_count"], row["click_payout"]) == (3, "0.50")


async def test_one_reflink_per_creator_per_campaign(api, tracking_stack):
    world = await build_world(api)
    await accept_creator(api, world)
    assert (await create_reflink(api, world)).status_code == 201
    second = await create_reflink(api, world, url="https://shop.example.com/other")
    assert second.status_code == 409
    assert await tracking_stack.pool.fetchval("SELECT count(*) FROM links") == 1


async def test_companies_cannot_touch_reflinks_of_someone_elses_campaign(api, tracking_stack):
    world = await build_world(api)
    await accept_creator(api, world)
    assert (await create_reflink(api, world)).status_code == 201
    intruder = (await api.post("/api/companies", json={"name": "Evil", "email": "evil@example.com", "password": "evil-pass-1"})).json()

    forged = World(company=intruder, creator=world.creator, campaign=world.campaign)
    assert (await create_reflink(api, forged)).status_code == 403
    listed = await api.get(f"/api/reflinks/campaign/{world.campaign['id']}", params={"company_id": intruder["id"]})
    assert listed.status_code == 403
    assert await tracking_stack.pool.fetchval("SELECT count(*) FROM links") == 1


async def test_unknown_campaigns_and_codes_are_404(api, tracking_stack):
    world = await build_world(api)
    ghost = World(company=world.company, creator=world.creator, campaign={**world.campaign, "id": 999_999})
    assert (await create_reflink(api, ghost)).status_code == 404
    assert (await api.get("/api/reflinks/campaign/999999", params={"company_id": world.company["id"]})).status_code == 404
    assert (await api.get("/api/reflinks/noSuchCode1")).status_code == 404
    assert await tracking_stack.pool.fetchval("SELECT count(*) FROM links") == 0


async def test_a_single_reflink_is_still_shown_while_tracking_is_down(api, swap_tracking):
    from tracking_client import TrackingClient

    world = await build_world(api)
    await accept_creator(api, world)
    code = (await create_reflink(api, world)).json()["code"]

    def refuse(request):
        raise httpx.ConnectError("tracking is down", request=request)

    swap_tracking(TrackingClient("http://api-internal", SERVICE_TOKEN, REDIRECT_BASE, transport=httpx.MockTransport(refuse)))
    response = await api.get(f"/api/reflinks/{code}")
    assert response.status_code == 200
    row = response.json()
    assert (row["code"], row["public_url"], row["url"]) == (code, f"{REDIRECT_BASE}/{code}", SHOP)
    assert (row["clicks_count"], row["raw_clicks"], row["click_payout"]) == (None, None, None)


@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_a_reflink_that_cannot_be_saved_is_switched_off_in_tracking(
    api, waggi_app, tracking_stack, swap_tracking, cleanup_fails, caplog
):
    import json

    from sqlalchemy import text

    import database

    world = await build_world(api)
    await accept_creator(api, world)
    rival = await api.post("/api/campaigns", json={"company_id": world.company["id"], "title": "Rival", "total_budget": "10.00"})
    real = httpx.ASGITransport(app=tracking_stack.app)
    issued: dict = {}

    async def intercept(request):
        if request.method == "POST":
            response = await real.handle_async_request(request)
            issued["code"] = json.loads(await response.aread())["code"]
            async with database.engine.begin() as connection:
                await connection.execute(
                    text("INSERT INTO campaign_ref_links (campaign_id, creator_id, code, url) VALUES (:campaign, :creator, :code, :url)"),
                    {"campaign": rival.json()["id"], "creator": world.creator["id"], "code": issued["code"], "url": SHOP},
                )
            return response
        if request.method == "DELETE" and cleanup_fails:
            return httpx.ConnectError("tracking went away", request=request)
        return None

    swap_tracking(intercepting_tracking(tracking_stack, intercept))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=waggi_app, raise_app_exceptions=False), base_url="http://waggi"
    ) as tolerant:
        response = await create_reflink(tolerant, world)

    assert response.status_code == 500
    assert (await stored_link(tracking_stack, issued["code"]))["active"] is cleanup_fails
    assert ("orphaned tracking link" in caplog.text) is cleanup_fails
    listed = await api.get(f"/api/reflinks/campaign/{world.campaign['id']}", params={"company_id": world.company["id"]})
    assert listed.json() == []


class LoseResponse(httpx.AsyncBaseTransport):
    def __init__(self, app, method: str) -> None:
        self._real = httpx.ASGITransport(app=app)
        self._method = method
        self.lost = 0

    async def handle_async_request(self, request):
        response = await self._real.handle_async_request(request)
        if request.method == self._method and not self.lost:
            self.lost += 1
            await response.aread()
            raise httpx.ReadTimeout("tracking applied the request but the answer never arrived", request=request)
        return response


def losing_first_answer(tracking_stack, method: str):
    from tracking_client import TrackingClient

    return TrackingClient("http://api-internal", SERVICE_TOKEN, REDIRECT_BASE, transport=LoseResponse(tracking_stack.app, method))


async def test_a_date_change_whose_answer_is_lost_is_undone_in_tracking(api, tracking_stack, swap_tracking):
    start = datetime.now(timezone.utc) - timedelta(days=1)
    world = await build_world(api, start_date=start.isoformat(), end_date=(start + timedelta(days=30)).isoformat())
    await accept_creator(api, world)
    code = (await create_reflink(api, world)).json()["code"]
    before = await stored_link(tracking_stack, code)

    swap_tracking(losing_first_answer(tracking_stack, "PUT"))
    response = await api.put(
        f"/api/campaigns/{world.campaign['id']}", json=campaign_body(world, end_date=(start + timedelta(days=2)).isoformat())
    )

    assert response.status_code == 503
    assert (await api.get(f"/api/campaigns/{world.campaign['id']}")).json()["end_date"] == world.campaign["end_date"]
    assert (await stored_link(tracking_stack, code))["ends_at"] == before["ends_at"]


async def test_a_delete_whose_answer_is_lost_leaves_the_reflink_working(api, tracking_stack, swap_tracking):
    world = await build_world(api)
    await accept_creator(api, world)
    code = (await create_reflink(api, world)).json()["code"]

    swap_tracking(losing_first_answer(tracking_stack, "DELETE"))
    assert (await api.delete(f"/api/campaigns/{world.campaign['id']}")).status_code == 503

    assert (await api.get(f"/api/campaigns/{world.campaign['id']}")).status_code == 200
    assert (await stored_link(tracking_stack, code))["active"] is True
    async with tracking_stack.public() as visitor:
        assert (await visitor.get(f"/r/{code}", headers=BROWSER)).status_code == 302


async def test_a_date_change_tracking_refuses_is_a_validation_error_and_changes_nothing(api, tracking_stack):
    start = datetime.now(timezone.utc) - timedelta(days=1)
    world = await build_world(api, start_date=start.isoformat(), end_date=(start + timedelta(days=30)).isoformat())
    await accept_creator(api, world)
    other = await add_accepted_creator(api, world, "second")
    codes = [(await create_reflink(api, w)).json()["code"] for w in (world, other)]
    before = {code: await stored_link(tracking_stack, code) for code in codes}

    response = await api.put(
        f"/api/campaigns/{world.campaign['id']}", json=campaign_body(world, end_date=(start - timedelta(days=1)).isoformat())
    )

    assert response.status_code == 422
    assert "ends_at" in response.text
    assert (await api.get(f"/api/campaigns/{world.campaign['id']}")).json()["end_date"] == world.campaign["end_date"]
    for code in codes:
        after = await stored_link(tracking_stack, code)
        assert (after["starts_at"], after["ends_at"]) == (before[code]["starts_at"], before[code]["ends_at"])


async def test_campaigns_without_a_per_click_rate_pay_nothing_for_clicks(api, tracking_stack):
    world = await build_world(api, payout_per_click=None)
    await accept_creator(api, world)
    code = (await create_reflink(api, world)).json()["code"]
    async with tracking_stack.public() as visitor:
        await visitor.get(f"/r/{code}", headers=BROWSER)
    await tracking_stack.flush()

    row = (await api.get(f"/api/reflinks/{code}")).json()
    assert (row["clicks_count"], row["click_payout"]) == (1, "0.00")


async def test_the_app_starts_with_a_tracking_client_built_from_settings(databases, monkeypatch):
    from types import SimpleNamespace

    import main
    from tracking_client import TrackingClient

    built: dict = {}

    class Recorded(TrackingClient):
        def __init__(self, *args, **kwargs):
            built.update(args=args, kwargs=kwargs)
            super().__init__(*args, **kwargs)

        async def aclose(self):
            built["closed"] = True
            await super().aclose()

    monkeypatch.setattr(main, "TrackingClient", Recorded)
    app = SimpleNamespace(state=SimpleNamespace())
    async with main.lifespan(app):
        assert isinstance(app.state.tracking, Recorded)
        assert app.state.tracking.public_url("abcDEF12345") == f"{REDIRECT_BASE}/abcDEF12345"
    assert built == {
        "args": ("http://api-internal:8000", SERVICE_TOKEN, REDIRECT_BASE),
        "kwargs": {"timeout": 5.0},
        "closed": True,
    }
