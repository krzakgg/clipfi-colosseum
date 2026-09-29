import json
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from starlette.responses import RedirectResponse

from tests.tracking.conftest import FINGERPRINT_SECRET, PROJECT_DIR, SERVICE_TOKEN
from tests.tracking.fakes import MemoryLinkStore, RecordingStats, bucket_totals, build_app, http_client
from tracking import keys
from tracking import links as links_module
from tracking import stats as stats_module
from tracking.config import Settings
from tracking.filters import referer_host, reject_reason
from tracking.fingerprint import client_ip
from tracking.links import (
    CODE_RE,
    CachedLinkStore,
    LinkInput,
    PostgresLinkStore,
    validate_target_url,
)
from tracking.stats import Granularity, GroupBy, PostgresStats

CAMPAIGN = "11111111-1111-1111-1111-111111111111"
CREATOR = "22222222-2222-2222-2222-222222222222"
BROWSER = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0"}
AUTH = {"authorization": f"Bearer {SERVICE_TOKEN}"}
TARGET = "https://store.example.com/app/1"
LINK_BODY = {"target_url": TARGET, "campaign_id": str(CAMPAIGN), "creator_id": str(CREATOR)}


@pytest.fixture
def store(redis):
    return CachedLinkStore(MemoryLinkStore(), redis, positive_ttl=300, negative_ttl=30)


@pytest.fixture
def app_for(settings, redis, store):
    def make(**overrides):
        return build_app(
            settings.model_copy(update=overrides),
            redis,
            store,
            RecordingStats(),
            secret=FINGERPRINT_SECRET.encode(),
        )

    return make


@pytest.fixture
async def client(app_for):
    async with http_client(app_for()) as client:
        yield client


async def add_link(store, code="abcDEF12", **overrides):
    data = dict(target_url=TARGET, campaign_id=CAMPAIGN, creator_id=CREATOR, platform="youtube")
    data.update(overrides)
    return await store.upsert(code, LinkInput(**data))


async def counted(redis) -> int:
    return len(await redis.xrange(keys.EVENTS_STREAM))


def concrete(path: str) -> str:
    return path.replace("{code}", "abcDEF12").replace("{campaign_id}", str(CAMPAIGN))


async def test_every_internal_route_rejects_requests_without_the_token(app_for):
    from tracking.api import internal

    app = app_for()
    routes = [(route.path, method) for route in internal.router.routes for method in route.methods]
    assert len(routes) >= 8
    async with http_client(app) as client:
        for path, method in routes:
            resp = await client.request(method, concrete(path), params={"from": "2026-09-01T00:00:00Z"})
            assert resp.status_code == 401, (method, path, resp.status_code)


@pytest.mark.parametrize(
    "authorization",
    [
        f"Bearer {SERVICE_TOKEN[:-1]}",
        f"Bearer {SERVICE_TOKEN}x",
        f"Bearer {SERVICE_TOKEN.upper()}",
        f"Token {SERVICE_TOKEN}",
        f"Bearer{SERVICE_TOKEN}",
        "Bearer ",
        "Bearer",
        "Bearer zażółć-gęślą-jaźń-0123456789abcdef",
        f"Basic {SERVICE_TOKEN}",
    ],
)
async def test_near_miss_tokens_are_rejected(client, authorization):
    resp = await client.get("/internal/links/abcDEF12", headers={"authorization": authorization.encode()})
    assert resp.status_code == 401


async def test_unauthenticated_body_is_not_parsed(client):
    resp = await client.post(
        "/internal/links", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 401


async def test_unauthenticated_caller_cannot_make_us_buffer_a_huge_body(client):
    resp = await client.post(
        "/internal/links", content=b"x" * 5_000_000, headers={"content-type": "application/json"}
    )
    assert resp.status_code == 401


async def test_oversized_authenticated_body_is_refused(client):
    body = {**LINK_BODY, "padding": "x" * 200_000}
    resp = await client.post("/internal/links", content=json.dumps(body), headers={**AUTH, "content-type": "application/json"})
    assert resp.status_code == 413


async def test_unknown_fields_are_rejected_not_silently_ignored(client, store):
    resp = await client.put(
        "/internal/links/good-code", json={**LINK_BODY, "id": 1, "created_at": "2020-01-01T00:00:00Z"}, headers=AUTH
    )
    assert resp.status_code == 422
    assert await store.get_by_code("good-code") is None


@pytest.mark.parametrize(
    "params",
    [
        {"from": "0001-01-01T00:00:00+14:00"},
        {"from": "2026-09-01T00:00:00Z", "to": "9999-12-31T23:59:59-14:00"},
        {"from": "1970-01-01T00:00:00Z", "granularity": "day"},
    ],
)
async def test_out_of_range_timestamps_are_422_not_500(client, store, params):
    await add_link(store)
    resp = await client.get("/internal/links/abcDEF12/stats", params=params, headers=AUTH)
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("value", ["9999-12-31T23:59:59-14:00", "0001-01-01T00:00:00+14:00", "1900-01-01T00:00:00Z"])
async def test_link_windows_outside_a_sane_range_are_rejected(client, value):
    resp = await client.put("/internal/links/good-code", json={**LINK_BODY, "starts_at": value}, headers=AUTH)
    assert resp.status_code == 422


async def test_internal_errors_do_not_leak_details(app_for):
    app = app_for()

    async def broken(link_id):
        raise RuntimeError("password=hunter2 host=db.internal")

    app.state.deps.stats.link_totals = broken
    await app.state.deps.links.upsert("abcDEF12", LinkInput(**LINK_BODY))
    async with http_client(app, raise_app_exceptions=False) as client:
        resp = await client.get("/internal/links/abcDEF12", headers=AUTH)
    assert resp.status_code == 500
    assert "hunter2" not in resp.text and "db.internal" not in resp.text


async def test_public_listener_does_not_serve_the_internal_api(app_for, store):
    await add_link(store)
    async with http_client(app_for(api_role="public")) as client:
        assert (await client.get("/internal/links/abcDEF12", headers=AUTH)).status_code == 404
        assert (await client.post("/internal/links", json=LINK_BODY, headers=AUTH)).status_code == 404
        assert (await client.get("/r/abcDEF12", headers=BROWSER)).status_code == 302
        assert (await client.get("/healthz")).status_code == 200


async def test_internal_listener_does_not_serve_redirects(app_for, store):
    await add_link(store)
    async with http_client(app_for(api_role="internal")) as client:
        assert (await client.get("/r/abcDEF12", headers=BROWSER)).status_code == 404
        assert (await client.get("/internal/links/abcDEF12", headers=AUTH)).status_code == 200


def test_compose_publishes_only_the_public_listener():
    import yaml

    compose = yaml.safe_load((PROJECT_DIR / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    published = {name for name, svc in services.items() if svc.get("ports")}
    assert published == {"api-public"}
    assert services["api-public"]["environment"]["TRACKING_API_ROLE"] == "public"
    assert services["api-internal"]["environment"]["TRACKING_API_ROLE"] == "internal"
    data_net = compose["networks"]["tracking-data"]
    assert data_net.get("internal") is True
    for name in ("redis", "postgres"):
        assert services[name]["networks"] == ["tracking-data"], name


async def test_trailing_slash_does_not_reflect_the_host_header(client, store):
    await add_link(store)
    resp = await client.get("/r/abcDEF12/", headers={**BROWSER, "host": "evil.example"})
    assert "evil.example" not in resp.headers.get("location", "")
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/r/abcDEF12%0A",
        "/r/abcDEF12%00",
        "/r/abcDEF12%0D%0ASet-Cookie:%20a=b",
        "/r/abc%D9%A1%D9%A2%D9%A3",  # Arabic-Indic digits
        "/r/abcDEF12%2F..%2F..%2Finternal",
        "/r/%61bcDEF12",  # percent-encoded but otherwise valid: must equal the plain code
    ],
)
async def test_hostile_codes_never_redirect_or_count(client, store, redis, path):
    await add_link(store)
    resp = await client.get(path, headers=BROWSER)
    if path == "/r/%61bcDEF12":
        assert resp.status_code == 302  # decoded before matching; same link, not a bypass
    else:
        assert resp.status_code == 404
        assert store._inner.lookups == 0
        assert await redis.keys("*") == [keys.link("abcDEF12")]
    assert "set-cookie" not in resp.headers


async def test_unknown_and_disabled_links_look_identical(client, store):
    await add_link(store, "off-link", active=False)
    unknown = await client.get("/r/never-existed", headers=BROWSER)
    disabled = await client.get("/r/off-link", headers=BROWSER)
    assert (unknown.status_code, unknown.content) == (disabled.status_code, disabled.content)


async def test_redirect_carries_no_internal_details(client, store):
    link = await add_link(store)
    resp = await client.get("/r/abcDEF12", headers=BROWSER)
    blob = json.dumps(dict(resp.headers)) + resp.text
    for secret in (str(link.campaign_id), str(link.creator_id), SERVICE_TOKEN, FINGERPRINT_SECRET):
        assert secret not in blob


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_redirect_route_rejects_write_methods(client, store, redis, method):
    await add_link(store)
    resp = await client.request(method, "/r/abcDEF12", headers=BROWSER)
    assert resp.status_code == 405
    assert await counted(redis) == 0


async def test_poisoned_cache_entry_cannot_turn_into_an_unsafe_redirect(client, store, redis):
    link = await add_link(store)
    poisoned = {
        "id": link.id, "code": link.code, "campaign_id": str(CAMPAIGN), "creator_id": str(CREATOR),
        "target_url": "javascript:alert(document.cookie)", "platform": None, "active": True,
        "starts_at": None, "ends_at": None,
        "created_at": link.created_at.isoformat(), "updated_at": link.updated_at.isoformat(),
    }
    await redis.set(keys.link(link.code), json.dumps(poisoned))
    resp = await client.get("/r/abcDEF12", headers=BROWSER)
    assert resp.status_code == 302
    assert resp.headers["location"] == TARGET  # fell back to the database, not the cache


async def test_spoofed_forwarded_for_from_an_untrusted_peer_is_ignored(app_for, store, redis, settings):
    link = await add_link(store)
    app = app_for(trusted_proxy_hops=1)
    async with http_client(app, peer=("198.51.100.23", 40000)) as client:
        for i in range(20):
            headers = {**BROWSER, "x-forwarded-for": f"203.0.113.{i}"}
            assert (await client.get("/r/abcDEF12", headers=headers)).status_code == 302
    assert await bucket_totals(redis, link.id) == (settings.rate_limit_per_minute, 1)


async def test_forwarded_for_from_a_trusted_proxy_is_honoured(app_for, store, redis):
    import ipaddress

    link = await add_link(store)
    app = app_for(trusted_proxy_hops=1, trusted_proxies=[ipaddress.ip_network("10.0.0.0/8")])
    async with http_client(app, peer=("10.0.0.2", 40000)) as client:
        for i in range(3):
            headers = {**BROWSER, "x-forwarded-for": f"attacker-junk, 203.0.113.{i}"}
            await client.get("/r/abcDEF12", headers=headers)
    assert await bucket_totals(redis, link.id) == (3, 3)


async def test_one_address_cannot_farm_uniques_by_rotating_user_agents(client, store, redis, settings):
    link = await add_link(store)
    for i in range(50):
        await client.get("/r/abcDEF12", headers={"user-agent": f"Mozilla/5.0 (rotated {i})"})
    assert await bucket_totals(redis, link.id) == (settings.rate_limit_per_minute, settings.max_unique_per_ip_per_day)


EVIL = "x'); DROP TABLE links; --"


class RecordingPool:
    """Stands in for asyncpg.Pool and records exactly what SQL text is sent."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if sql.lstrip().startswith(("INSERT", "UPDATE")):
            now = datetime.now(UTC)
            return {
                "id": 1, "code": args[0], "campaign_id": CAMPAIGN, "creator_id": CREATOR, "target_url": TARGET,
                "platform": None, "active": True, "starts_at": None, "ends_at": None, "created_at": now, "updated_at": now,
            }
        if "SUM(" in sql:
            return {"raw": 0, "uniq": 0}
        return None

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return []


def _sql_constants(*modules) -> set[str]:
    found = set()
    for module in modules:
        for value in vars(module).values():
            if isinstance(value, str):
                found.add(value)
            elif isinstance(value, dict):
                found.update(v for v in value.values() if isinstance(v, str))
    return found


async def test_caller_input_never_becomes_sql_text():
    pool = RecordingPool()
    link_store = PostgresLinkStore(pool)
    stats = PostgresStats(pool)
    # model_construct skips validation
    evil_input = LinkInput.model_construct(
        target_url=EVIL, campaign_id=CAMPAIGN, creator_id=CREATOR, platform=EVIL, active=True, starts_at=None, ends_at=None
    )
    await link_store.get_by_code(EVIL)
    await link_store.insert(EVIL, evil_input)
    await link_store.upsert(EVIL, evil_input)
    await link_store.deactivate(EVIL)
    await link_store.list_by_campaign(CAMPAIGN)
    start, end = datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 2, tzinfo=UTC)
    await stats.link_totals(1)
    for granularity in Granularity:
        await stats.link_series(1, start, end, granularity)
        for group_by in (None, *GroupBy):
            await stats.campaign_series(CAMPAIGN, start, end, granularity, group_by)
    await stats.campaign_links(CAMPAIGN)
    await stats.campaign_referers(CAMPAIGN, start, end, 10)

    allowed = _sql_constants(links_module, stats_module)
    assert len(pool.calls) >= 20
    for sql, _args in pool.calls:
        assert sql in allowed, sql
        assert EVIL not in sql


_any_text = st.text(alphabet=st.characters(codec="utf-8", exclude_categories=("Cs",)), max_size=300)


@hyp_settings(max_examples=400, suppress_health_check=[HealthCheck.too_slow])
@given(_any_text)
def test_an_accepted_target_url_can_never_break_the_location_header(candidate):
    try:
        url = validate_target_url(candidate)
    except ValueError:
        return
    location = dict(RedirectResponse(url).raw_headers)[b"location"]
    assert all(0x21 <= byte <= 0x7E for byte in location), location


_address_like = st.one_of(st.none(), _any_text, st.ip_addresses().map(str))


@hyp_settings(max_examples=400)
@given(
    _address_like,
    st.one_of(st.none(), _any_text, st.lists(_address_like.map(str), max_size=5).map(", ".join)),
    st.integers(min_value=0, max_value=10),
)
def test_client_ip_never_crashes_and_returns_only_addresses(peer, forwarded_for, hops):
    import ipaddress

    everything = [ipaddress.ip_network("0.0.0.0/0"), ipaddress.ip_network("::/0")]
    result = client_ip(peer, forwarded_for, hops, everything)
    if result is not None:
        ipaddress.ip_address(result)


@hyp_settings(max_examples=400)
@given(_any_text, _any_text)
def test_header_filters_never_crash_and_referer_is_always_a_plain_host(user_agent, referer):
    reject_reason("GET", {"user-agent": user_agent, "referer": referer, "sec-purpose": referer})
    host = referer_host({"referer": referer})
    assert host is None or (len(host) <= 253 and all(c in "abcdefghijklmnopqrstuvwxyz0123456789.-:" for c in host))


@hyp_settings(max_examples=400)
@given(_any_text)
def test_only_plain_codes_pass_the_code_check(code):
    if CODE_RE.fullmatch(code):
        assert code.isascii() and 4 <= len(code) <= 64
        assert all(c.isalnum() or c in "-_" for c in code)


def test_secrets_never_show_up_in_settings_repr_or_logs(settings):
    text = repr(settings) + str(settings) + settings.model_dump_json()
    assert SERVICE_TOKEN not in text and FINGERPRINT_SECRET not in text


@pytest.mark.parametrize("field", ["service_token", "fingerprint_secret"])
def test_short_secrets_refuse_to_start(field):
    values = dict(database_url="postgresql://x", service_token="a" * 32, fingerprint_secret="b" * 32, _env_file=None)
    values[field] = "short-secret"
    with pytest.raises(ValueError):
        Settings(**values)


async def test_a_second_forwarded_for_line_cannot_be_forged_by_the_client(app_for, store, redis, settings):
    import ipaddress

    link = await add_link(store)
    app = app_for(trusted_proxy_hops=1, trusted_proxies=[ipaddress.ip_network("10.0.0.0/8")])
    async with http_client(app, peer=("10.0.0.2", 40000)) as client:
        for i in range(10):
            headers = [
                ("user-agent", f"{BROWSER['user-agent']} {i}"),
                ("x-forwarded-for", f"203.0.113.{i}"),
                ("x-forwarded-for", "198.51.100.7"),
            ]
            assert (await client.get("/r/abcDEF12", headers=headers)).status_code == 302
    assert await bucket_totals(redis, link.id) == (settings.rate_limit_per_minute, settings.max_unique_per_ip_per_day)


async def test_gate_also_guards_the_internal_api_under_a_root_path(app_for):
    async with http_client(app_for(), root_path="/api") as client:
        resp = await client.post(
            "/api/internal/links", content=b"{not json", headers={"content-type": "application/json"}
        )
    assert resp.status_code == 401


def test_forwarded_for_is_trusted_from_nobody_unless_configured():
    base = dict(database_url="postgresql://x", service_token="a" * 32, fingerprint_secret="b" * 32, _env_file=None)
    assert Settings(**base).trusted_proxies == []
    with pytest.raises(ValueError):
        Settings(**base, trusted_proxy_hops=1)
    assert Settings(**base, trusted_proxy_hops=1, trusted_proxies=["10.1.2.0/24"]).trusted_proxies


@pytest.mark.parametrize(
    "corrupt",
    [
        {"starts_at": "2020-01-01T00:00:00"},  # naive timestamp
        {"campaign_id": 5},
        {"target_url": "https://example.com/" + "a" * 60_000},
        {"id": "7"},
        {"created_at": 12345},
        {"platform": "Not A Slug!"},
        {"active": "yes"},
    ],
)
async def test_corrupt_cache_entries_fall_back_to_the_database(client, store, redis, corrupt):
    link = await add_link(store)
    entry = {
        "id": link.id, "code": link.code, "campaign_id": str(CAMPAIGN), "creator_id": str(CREATOR),
        "target_url": TARGET, "platform": "youtube", "active": True, "starts_at": None, "ends_at": None,
        "created_at": link.created_at.isoformat(), "updated_at": link.updated_at.isoformat(),
    }
    await redis.set(keys.link(link.code), json.dumps({**entry, **corrupt}))
    for _ in range(2):
        resp = await client.get("/r/abcDEF12", headers=BROWSER)
        assert resp.status_code == 302 and resp.headers["location"] == TARGET
    assert store._inner.lookups == 1
    assert json.loads(await redis.get(keys.link(link.code))) == entry


def test_compose_binds_the_published_port_to_localhost_only():
    import yaml

    compose = yaml.safe_load((PROJECT_DIR / "docker-compose.yml").read_text(encoding="utf-8"))
    assert compose["services"]["api-public"]["ports"] == ["127.0.0.1:8080:8000"]


async def test_request_with_both_content_length_and_transfer_encoding_is_refused(app_for):
    from tests.tracking.fakes import raw_asgi

    status_code, headers, _ = await raw_asgi(
        app_for(), "POST", "/internal/links",
        [(b"content-length", b"4"), (b"transfer-encoding", b"chunked"), (b"authorization", f"Bearer {SERVICE_TOKEN}".encode())],
        body=b"{}",
    )
    assert status_code == 400
    assert headers.get("connection") == "close"  # the pipelined bytes after it are never parsed


async def test_oversized_request_headers_get_431_and_close_the_connection(app_for, store):
    from tests.tracking.fakes import raw_asgi

    await add_link(store)
    status_code, headers, _ = await raw_asgi(
        app_for(), "GET", "/r/abcDEF12", [(b"user-agent", BROWSER["user-agent"].encode()), (b"x-big", b"a" * 100_000)]
    )
    assert status_code == 431
    assert headers.get("connection") == "close"
    status_code, _, _ = await raw_asgi(app_for(), "GET", "/r/abcDEF12", [(b"user-agent", BROWSER["user-agent"].encode()), (b"x-ok", b"a" * 4000)])
    assert status_code == 302


async def test_guessing_codes_stops_reaching_the_database(settings, redis):
    inner = MemoryLinkStore()
    store = CachedLinkStore(inner, redis, positive_ttl=300, negative_ttl=30, miss_limit_per_minute=settings.miss_limit_per_minute)
    app = build_app(settings, redis, store, RecordingStats(), secret=FINGERPRINT_SECRET.encode())
    async with http_client(app) as client:
        for i in range(settings.miss_limit_per_minute + 20):
            assert (await client.get(f"/r/guess-{i:05d}", headers=BROWSER)).status_code == 404
    assert inner.lookups == settings.miss_limit_per_minute
    await store.upsert("abcDEF12", LinkInput(**LINK_BODY))
    async with http_client(app, peer=("198.51.100.4", 4000)) as client:
        assert (await client.get("/r/abcDEF12", headers=BROWSER)).status_code == 302


def test_deployment_files_keep_the_hardening_flags():
    root = PROJECT_DIR
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8").replace("\\\n", " ")
    cmd = next(line for line in dockerfile.splitlines() if line.startswith("CMD"))
    for flag in ("--no-access-log", "--no-proxy-headers", "--no-server-header", "--http", "h11", "--h11-max-incomplete-event-size"):
        assert flag in cmd, flag


def test_compose_uses_least_privilege_accounts():
    import yaml

    compose = yaml.safe_load((PROJECT_DIR / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert "--requirepass" in " ".join(services["redis"]["command"])
    assert any("postgres-init" in volume for volume in services["postgres"]["volumes"])
    assert "TRACKING_MIGRATE_DATABASE_URL" in services["migrate"]["environment"]
    for name in ("api-public", "api-internal", "flusher"):
        assert "TRACKING_MIGRATE_DATABASE_URL" not in services[name].get("environment", {}), name
    assert services["api-public"]["environment"]["UVICORN_LIMIT_CONCURRENCY"]


async def test_the_router_checks_the_token_even_without_the_gate(app_for):
    from fastapi import FastAPI

    from tracking.api import internal

    wired = app_for()
    bare = FastAPI()
    bare.include_router(internal.router)
    bare.state.service_token = wired.state.service_token
    bare.state.deps = wired.state.deps
    async with http_client(bare) as client:
        for headers in ({}, {"authorization": "Bearer not-the-token"}, {"authorization": SERVICE_TOKEN}):
            resp = await client.get("/internal/links/abcDEF12", headers=headers)
            assert resp.status_code == 401
            assert resp.json() == {"detail": "invalid service token"}
            assert resp.headers["www-authenticate"] == "Bearer"
        assert (await client.get("/internal/links/abcDEF12", headers=AUTH)).status_code == 404
