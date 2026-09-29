import time
from datetime import UTC, datetime, timedelta

import pytest

from tests.tracking.conftest import FINGERPRINT_SECRET, SERVICE_TOKEN
from tests.tracking.fakes import MemoryLinkStore, RecordingStats, bucket_totals, build_app, http_client
from tracking import keys
from tracking.links import CachedLinkStore, LinkInput
from tracking.stats import Granularity, GroupBy, Totals

CAMPAIGN = "11111111-1111-1111-1111-111111111111"
CREATOR = "22222222-2222-2222-2222-222222222222"
BROWSER = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0"}
AUTH = {"authorization": f"Bearer {SERVICE_TOKEN}"}
TARGET = "https://store.example.com/app/1?utm_source=jestr"


@pytest.fixture
def stats():
    return RecordingStats()


@pytest.fixture
def store(redis):
    return CachedLinkStore(MemoryLinkStore(), redis, positive_ttl=300, negative_ttl=30)


@pytest.fixture
async def client(settings, redis, store, stats):
    app = build_app(settings, redis, store, stats, secret=FINGERPRINT_SECRET.encode())
    async with http_client(app) as client:
        yield client


async def create(store, code="abcDEF12", **overrides):
    data = dict(target_url=TARGET, campaign_id=CAMPAIGN, creator_id=CREATOR, platform="youtube")
    data.update(overrides)
    return await store.upsert(code, LinkInput(**data))


async def stream_len(redis) -> int:
    return len(await redis.xrange(keys.EVENTS_STREAM))


async def test_redirect_counts_a_browser_click(client, store, redis):
    link = await create(store)
    resp = await client.get("/r/abcDEF12", headers={**BROWSER, "referer": "https://www.youtube.com/watch?v=x"})
    assert resp.status_code == 302
    assert resp.headers["location"] == TARGET
    assert resp.headers["cache-control"] == "no-store, private"
    assert resp.headers["x-robots-tag"] == "noindex, nofollow"
    assert "set-cookie" not in resp.headers

    events = await redis.xrange(keys.EVENTS_STREAM)
    assert len(events) == 1
    assert events[0][1]["l"] == str(link.id)
    assert events[0][1]["r"] == "www.youtube.com"


async def test_unknown_codes_are_404_and_cached_as_missing(client, store, redis):
    assert (await client.get("/r/doesnotexist", headers=BROWSER)).status_code == 404
    assert store._inner.lookups == 1
    assert await redis.get(keys.link("doesnotexist")) == "-"
    assert await stream_len(redis) == 0


@pytest.mark.parametrize("code", ["ab", "abc", "has%20space", "x" * 65, "abc.def", "abc%E2%80%8Bdef", "%C3%A9t%C3%A9-code"])
async def test_malformed_codes_are_404_before_any_lookup_or_redis_key(client, store, redis, code):
    assert (await client.get(f"/r/{code}", headers=BROWSER)).status_code == 404
    assert store._inner.lookups == 0
    assert await redis.keys("*") == []


async def test_disabled_link_is_404(client, store, redis):
    await create(store, active=False)
    assert (await client.get("/r/abcDEF12", headers=BROWSER)).status_code == 404
    assert await stream_len(redis) == 0


async def test_link_outside_window_redirects_without_counting(client, store, redis):
    past = datetime.now(UTC) - timedelta(days=2)
    await create(store, starts_at=past, ends_at=past + timedelta(days=1))
    resp = await client.get("/r/abcDEF12", headers=BROWSER)
    assert resp.status_code == 302 and resp.headers["location"] == TARGET
    assert await stream_len(redis) == 0


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"user-agent": "Discordbot/2.0"},
        {**BROWSER, "purpose": "prefetch"},
    ],
)
async def test_previews_bots_and_prefetch_redirect_without_counting(client, store, redis, headers):
    await create(store)
    resp = await client.get("/r/abcDEF12", headers=headers)
    assert resp.status_code == 302
    assert await stream_len(redis) == 0


async def test_head_redirects_without_counting(client, store, redis):
    await create(store)
    resp = await client.head("/r/abcDEF12", headers=BROWSER)
    assert resp.status_code == 302
    assert await stream_len(redis) == 0


async def test_repeat_clicks_from_one_visitor_count_once_as_unique(client, store, redis):
    link = await create(store)
    for _ in range(3):
        assert (await client.get("/r/abcDEF12", headers=BROWSER)).status_code == 302
    assert await bucket_totals(redis, link.id) == (3, 1)


async def test_forwarded_for_is_ignored_unless_a_proxy_is_trusted(client, store, redis):
    link = await create(store)
    for i in range(3):
        headers = {**BROWSER, "x-forwarded-for": f"198.51.100.{i}"}
        await client.get("/r/abcDEF12", headers=headers)
    assert await bucket_totals(redis, link.id) == (3, 1)


async def test_counting_failure_does_not_break_the_redirect(client, store, monkeypatch):
    await create(store)

    async def boom(*args, **kwargs):
        raise RuntimeError("redis exploded")

    monkeypatch.setattr(client._transport.app.state.deps.counter, "record", boom)
    resp = await client.get("/r/abcDEF12", headers=BROWSER)
    assert resp.status_code == 302 and resp.headers["location"] == TARGET


async def test_slow_counting_is_cut_off(client, store, settings, monkeypatch):
    import asyncio

    await create(store)

    async def slow(*args, **kwargs):
        await asyncio.sleep(settings.count_timeout * 4)

    monkeypatch.setattr(client._transport.app.state.deps.counter, "record", slow)
    started = time.perf_counter()
    resp = await client.get("/r/abcDEF12", headers=BROWSER)
    assert resp.status_code == 302
    assert time.perf_counter() - started < settings.count_timeout * 3


@pytest.mark.parametrize(
    "headers",
    [{}, {"authorization": "Bearer wrong"}, {"authorization": f"Basic {SERVICE_TOKEN}"}, {"authorization": SERVICE_TOKEN}],
)
async def test_internal_requires_bearer_token(client, headers):
    resp = await client.get("/internal/links/abcDEF12", headers=headers)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_docs_are_hidden_by_default(client):
    assert (await client.get("/docs")).status_code == 404
    assert (await client.get("/openapi.json")).status_code == 404


async def test_docs_can_be_switched_on(settings, redis, store, stats):
    app = build_app(settings.model_copy(update={"expose_docs": True}), redis, store, stats, secret=FINGERPRINT_SECRET.encode())
    async with http_client(app) as client:
        assert (await client.get("/docs")).status_code == 200
        assert "/internal/links" in (await client.get("/openapi.json")).json()["paths"]
        assert (await client.get("/redoc")).status_code == 404


async def test_create_link_generates_a_code(client, store):
    body = {"target_url": TARGET, "campaign_id": str(CAMPAIGN), "creator_id": str(CREATOR), "platform": "twitch"}
    resp = await client.post("/internal/links", json=body, headers=AUTH)
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert len(out["code"]) == 11 and out["active"] is True and out["platform"] == "twitch"
    assert (await store.get_by_code(out["code"])).target_url == TARGET


async def test_upsert_get_and_deactivate(client, stats):
    body = {"target_url": TARGET, "campaign_id": str(CAMPAIGN), "creator_id": str(CREATOR)}
    resp = await client.put("/internal/links/my-code_1", json=body, headers=AUTH)
    assert resp.status_code == 200 and resp.json()["code"] == "my-code_1"

    resp = await client.put("/internal/links/my-code_1", json={**body, "platform": "kick"}, headers=AUTH)
    assert resp.status_code == 200 and resp.json()["platform"] == "kick"

    resp = await client.get("/internal/links/my-code_1", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["totals"] == {"raw": 10, "unique": 4}
    assert ("link_totals", resp.json()["id"]) in stats.calls

    assert (await client.delete("/internal/links/my-code_1", headers=AUTH)).status_code == 204
    assert (await client.get("/internal/links/my-code_1", headers=AUTH)).json()["active"] is False
    assert (await client.delete("/internal/links/nope-nope", headers=AUTH)).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"target_url": "javascript:alert(1)", "campaign_id": str(CAMPAIGN), "creator_id": str(CREATOR)},
        {"target_url": TARGET, "campaign_id": "not a valid id", "creator_id": str(CREATOR)},
        {"target_url": TARGET, "campaign_id": str(CAMPAIGN), "creator_id": str(CREATOR), "platform": "Bad Platform"},
        {"target_url": TARGET, "campaign_id": str(CAMPAIGN), "creator_id": str(CREATOR), "starts_at": "2026-01-01T00:00:00"},
    ],
)
async def test_invalid_link_payloads_are_422(client, body):
    assert (await client.put("/internal/links/valid-code", json=body, headers=AUTH)).status_code == 422


async def test_invalid_code_in_path_is_422(client):
    body = {"target_url": TARGET, "campaign_id": str(CAMPAIGN), "creator_id": str(CREATOR)}
    assert (await client.put("/internal/links/ab", json=body, headers=AUTH)).status_code == 422


async def test_link_stats_passes_window_and_granularity(client, store, stats):
    link = await create(store)
    resp = await client.get(
        "/internal/links/abcDEF12/stats",
        params={"from": "2026-09-01T00:00:00Z", "to": "2026-09-02T00:00:00Z", "granularity": "minute"},
        headers=AUTH,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["points"] == [{"bucket": "2026-09-01T00:00:00Z", "raw": 3, "unique": 2, "group": None}]
    call = stats.calls[-1]
    assert call[0] == "link_series" and call[1] == link.id and call[4] is Granularity.minute
    assert call[2] == datetime(2026, 9, 1, tzinfo=UTC)


async def test_series_requests_are_capped(client, store):
    await create(store)
    resp = await client.get(
        "/internal/links/abcDEF12/stats",
        params={"from": "2026-01-01T00:00:00Z", "to": "2026-09-01T00:00:00Z", "granularity": "minute"},
        headers=AUTH,
    )
    assert resp.status_code == 422
    resp = await client.get(
        "/internal/links/abcDEF12/stats",
        params={"from": "2026-09-02T00:00:00Z", "to": "2026-09-01T00:00:00Z"},
        headers=AUTH,
    )
    assert resp.status_code == 422
    resp = await client.get("/internal/links/abcDEF12/stats", params={"from": "2026-09-01", "granularity": "week"}, headers=AUTH)
    assert resp.status_code == 422


@pytest.mark.parametrize("minutes, status_code", [(10_000, 200), (10_001, 422)])
async def test_series_may_have_exactly_the_maximum_number_of_points(client, store, minutes, status_code):
    await create(store)
    start = datetime(2026, 9, 1, tzinfo=UTC)
    params = {"from": start.isoformat(), "to": (start + timedelta(minutes=minutes)).isoformat(), "granularity": "minute"}
    assert (await client.get("/internal/links/abcDEF12/stats", params=params, headers=AUTH)).status_code == status_code


@pytest.mark.parametrize(
    "start, end, expected",
    [
        ("2026-09-01T12:00:00", "2026-09-01T13:00:00", (datetime(2026, 9, 1, 12, tzinfo=UTC), datetime(2026, 9, 1, 13, tzinfo=UTC))),
        ("2026-09-01T12:00:00+02:00", "2026-09-01T13:00:00-01:00", (datetime(2026, 9, 1, 10, tzinfo=UTC), datetime(2026, 9, 1, 14, tzinfo=UTC))),
    ],
)
async def test_windows_are_read_as_utc_when_no_offset_is_given(client, store, stats, start, end, expected):
    await create(store)
    resp = await client.get("/internal/links/abcDEF12/stats", params={"from": start, "to": end}, headers=AUTH)
    assert resp.status_code == 200, resp.text
    assert stats.calls[-1][2:4] == expected
    assert stats.calls[-1][2].utcoffset() == stats.calls[-1][3].utcoffset() == timedelta(0)
    resp = await client.get(f"/internal/campaigns/{CAMPAIGN}/referers", params={"from": start, "to": end}, headers=AUTH)
    assert resp.status_code == 200 and stats.calls[-1][2:4] == expected


async def test_an_empty_window_is_rejected(client, store):
    await create(store)
    params = {"from": "2026-09-01T12:00:00Z", "to": "2026-09-01T12:00:00Z"}
    assert (await client.get("/internal/links/abcDEF12/stats", params=params, headers=AUTH)).status_code == 422
    assert (await client.get(f"/internal/campaigns/{CAMPAIGN}/referers", params=params, headers=AUTH)).status_code == 422


async def test_campaign_endpoints(client, stats):
    base = f"/internal/campaigns/{CAMPAIGN}"
    resp = await client.get(f"{base}/stats", params={"from": "2026-09-01T00:00:00Z", "group_by": "platform"}, headers=AUTH)
    assert resp.status_code == 200, resp.text
    assert resp.json()["points"][0]["group"] == "youtube"
    assert stats.calls[-1][5] is GroupBy.platform

    assert (await client.get(f"{base}/links", headers=AUTH)).json() == []

    resp = await client.get(f"{base}/referers", params={"from": "2026-09-01T00:00:00Z", "limit": 5}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()[0] == {"host": "www.youtube.com", "clicks": 5}
    assert stats.calls[-1][4] == 5
    assert (await client.get(f"{base}/referers", params={"from": "2026-09-01T00:00:00Z", "limit": 500}, headers=AUTH)).status_code == 422


async def test_health_endpoints(client):
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    assert (await client.get("/readyz")).json() == {"redis": "ok", "database": "ok"}


async def test_a_hanging_dependency_fails_readiness_instead_of_hanging_it(client, monkeypatch):
    import asyncio

    from tracking.api import health

    async def hang() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(health, "_PROBE_TIMEOUT", 0.2)
    client._transport.app.state.deps.check_redis = hang
    started = time.perf_counter()
    resp = await client.get("/readyz")
    assert resp.status_code == 503 and resp.json() == {"redis": "fail", "database": "ok"}
    assert time.perf_counter() - started < 1.5


async def test_readyz_reports_failures(client):
    async def down() -> None:
        raise ConnectionError("no")

    client._transport.app.state.deps.check_database = down
    resp = await client.get("/readyz")
    assert resp.status_code == 503 and resp.json() == {"redis": "ok", "database": "fail"}


async def test_upsert_cannot_move_a_link_to_another_owner(client, store):
    await create(store, "own-code")
    body = {"target_url": TARGET, "campaign_id": str(CAMPAIGN), "creator_id": "33333333-3333-3333-3333-333333333333"}
    resp = await client.put("/internal/links/own-code", json=body, headers=AUTH)
    assert resp.status_code == 409
    assert (await store.get_by_code("own-code")).creator_id == CREATOR


async def test_campaign_links_include_totals(client, store, stats):
    link = await create(store)

    async def campaign_links(campaign_id):
        return [(link, Totals(raw=12, unique=5))]

    stats.campaign_links = campaign_links
    resp = await client.get(f"/internal/campaigns/{CAMPAIGN}/links", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()[0]["code"] == link.code and resp.json()[0]["totals"] == {"raw": 12, "unique": 5}


async def test_rate_limit_applies_through_the_app(client, store, redis, settings):
    link = await create(store)
    for i in range(settings.rate_limit_per_minute + 2):
        assert (await client.get("/r/abcDEF12", headers={"user-agent": f"Mozilla/5.0 ({i})"})).status_code == 302
    assert await bucket_totals(redis, link.id) == (settings.rate_limit_per_minute, settings.max_unique_per_ip_per_day)


async def test_ids_owned_by_the_campaign_service_round_trip(client, stats):
    body = {"target_url": TARGET, "campaign_id": "42", "creator_id": "7"}
    resp = await client.put("/internal/links/int-ids", json=body, headers=AUTH)
    assert resp.status_code == 200, resp.text
    assert (resp.json()["campaign_id"], resp.json()["creator_id"]) == ("42", "7")
    assert (await client.get("/internal/campaigns/42/links", headers=AUTH)).status_code == 200
    assert stats.calls[-1] == ("campaign_links", "42")
    for bad in ("not%20valid", "x" * 65, "..%2Fetc"):
        assert (await client.get(f"/internal/campaigns/{bad}/links", headers=AUTH)).status_code in (404, 422)


async def test_code_collisions_are_retried_then_reported_as_unavailable(settings, redis, stats, monkeypatch):
    from tracking.api import internal
    from tracking.links import LinkExists

    class CollidingStore(MemoryLinkStore):
        def __init__(self, collisions: int) -> None:
            super().__init__()
            self.collisions = collisions
            self.attempted: list[str] = []

        async def insert(self, code, data):
            self.attempted.append(code)
            if len(self.attempted) <= self.collisions:
                raise LinkExists(code)
            return await super().insert(code, data)

    codes = iter(f"code-{i:04d}" for i in range(100))
    monkeypatch.setattr(internal, "generate_code", lambda: next(codes))
    body = {"target_url": TARGET, "campaign_id": CAMPAIGN, "creator_id": CREATOR}

    lucky = CollidingStore(collisions=2)
    async with http_client(build_app(settings, redis, lucky, stats, secret=FINGERPRINT_SECRET.encode())) as client:
        resp = await client.post("/internal/links", json=body, headers=AUTH)
    assert resp.status_code == 201 and resp.json()["code"] == "code-0002"
    assert lucky.attempted == ["code-0000", "code-0001", "code-0002"]

    unlucky = CollidingStore(collisions=3)
    async with http_client(build_app(settings, redis, unlucky, stats, secret=FINGERPRINT_SECRET.encode())) as client:
        resp = await client.post("/internal/links", json=body, headers=AUTH)
    assert resp.status_code == 503 and resp.json() == {"detail": "could not allocate a unique code"}
    assert len(unlucky.attempted) == 3 and len(set(unlucky.attempted)) == 3
