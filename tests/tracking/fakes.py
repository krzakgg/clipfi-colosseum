"""In-memory stand-ins for the Postgres-backed pieces, used by the unit tests."""

import itertools
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from tracking import keys
from tracking.app import create_app
from tracking.clicks import ClickCounter
from tracking.deps import Deps
from tracking.links import Link, LinkExists, LinkInput, LinkOwnerMismatch
from tracking.stats import Point, RefererCount, Totals


class MemoryLinkStore:
    def __init__(self) -> None:
        self._by_code: dict[str, Link] = {}
        self._ids = itertools.count(1)
        self.lookups = 0

    async def get_by_code(self, code: str, *, miss_budget: str | None = None) -> Link | None:
        self.lookups += 1
        return self._by_code.get(code)

    async def insert(self, code: str, data: LinkInput) -> Link:
        if code in self._by_code:
            raise LinkExists(code)
        return self._store(code, data, next(self._ids), datetime.now(UTC))

    async def upsert(self, code: str, data: LinkInput) -> Link:
        existing = self._by_code.get(code)
        if existing and (existing.campaign_id, existing.creator_id) != (data.campaign_id, data.creator_id):
            raise LinkOwnerMismatch(code)
        link_id = existing.id if existing else next(self._ids)
        created_at = existing.created_at if existing else datetime.now(UTC)
        return self._store(code, data, link_id, created_at)

    async def deactivate(self, code: str) -> Link | None:
        existing = self._by_code.get(code)
        if existing is None:
            return None
        data = LinkInput(
            target_url=existing.target_url,
            campaign_id=existing.campaign_id,
            creator_id=existing.creator_id,
            platform=existing.platform,
            active=False,
            starts_at=existing.starts_at,
            ends_at=existing.ends_at,
        )
        return self._store(code, data, existing.id, existing.created_at)

    async def list_by_campaign(self, campaign_id: str) -> list[Link]:
        return sorted((l for l in self._by_code.values() if l.campaign_id == campaign_id), key=lambda l: l.id)

    def _store(self, code: str, data: LinkInput, link_id: int, created_at: datetime) -> Link:
        link = Link(
            id=link_id,
            code=code,
            campaign_id=data.campaign_id,
            creator_id=data.creator_id,
            target_url=data.target_url,
            platform=data.platform,
            active=data.active,
            starts_at=data.starts_at,
            ends_at=data.ends_at,
            created_at=created_at,
            updated_at=datetime.now(UTC),
        )
        self._by_code[code] = link
        return link


class RecordingStats:
    """StatsSource that returns fixed values and records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def link_totals(self, link_id):
        self.calls.append(("link_totals", link_id))
        return Totals(raw=10, unique=4)

    async def link_series(self, link_id, start, end, granularity):
        self.calls.append(("link_series", link_id, start, end, granularity))
        return [Point(bucket=start, raw=3, unique=2)]

    async def campaign_links(self, campaign_id):
        self.calls.append(("campaign_links", campaign_id))
        return []

    async def campaign_series(self, campaign_id, start, end, granularity, group_by):
        self.calls.append(("campaign_series", campaign_id, start, end, granularity, group_by))
        return [Point(bucket=start, raw=3, unique=2, group="youtube" if group_by else None)]

    async def campaign_referers(self, campaign_id, start, end, limit):
        self.calls.append(("campaign_referers", campaign_id, start, end, limit))
        return [RefererCount(host="www.youtube.com", clicks=5), RefererCount(host=None, clicks=1)]


def build_app(settings, redis, store, stats, *, secret: bytes):
    """The real FastAPI app wired to in-memory / fakeredis dependencies."""

    async def ok() -> None:
        return None

    app = create_app(settings)
    app.state.deps = Deps(
        links=store,
        counter=ClickCounter(
            redis,
            secret=secret,
            rate_limit_per_minute=settings.rate_limit_per_minute,
            max_unique_per_ip_per_day=settings.max_unique_per_ip_per_day,
            bucket_ttl=settings.bucket_ttl,
            stream_maxlen=settings.stream_maxlen,
        ),
        stats=stats,
        check_redis=ok,
        check_database=ok,
        close=ok,
    )
    return app


def http_client(app, peer: tuple[str, int] = ("203.0.113.5", 51000), **kwargs) -> AsyncClient:
    transport = ASGITransport(app=app, client=peer, **kwargs)
    return AsyncClient(transport=transport, base_url="http://tracking.test")


async def raw_asgi(app, method: str, path: str, headers: list[tuple[bytes, bytes]], body: bytes = b"", peer=("203.0.113.5", 51000)):
    """Drive the ASGI app directly, for requests an HTTP client library refuses to send."""
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [(b"host", b"tracking.test")] + headers, "client": peer, "server": ("tracking.test", 80),
    }
    messages = [{"type": "http.request", "body": body, "more_body": False}]
    sent: list[dict] = []

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], {k.decode(): v.decode() for k, v in start.get("headers", [])}, payload


async def bucket_totals(redis, link_id: int) -> tuple[int, int]:
    raw = unique = 0
    for minute in await redis.zrange(keys.BUCKET_INDEX, 0, -1):
        fields = await redis.hgetall(keys.bucket(int(minute)))
        raw += int(fields.get(f"{link_id}:r", 0))
        unique += int(fields.get(f"{link_id}:u", 0))
    return raw, unique
