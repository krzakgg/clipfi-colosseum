import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Protocol
from urllib.parse import urlsplit

import asyncpg
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from redis.asyncio import Redis
from redis.exceptions import RedisError

from tracking import keys

log = logging.getLogger(__name__)

CODE_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
PLATFORM_RE = re.compile(r"^[a-z0-9_]{1,32}$")
EXTERNAL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_URL_LENGTH = 2048
_GENERATED_CODE_BYTES = 8  # 11 chars
# outside this range timezone conversion can overflow
EARLIEST = datetime(2000, 1, 1, tzinfo=UTC)
LATEST = datetime(2100, 1, 1, tzinfo=UTC)


def bounded_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("must include a timezone")
    try:
        value = value.astimezone(UTC)
    except OverflowError:
        raise ValueError("timestamp out of range") from None
    if not EARLIEST <= value < LATEST:
        raise ValueError(f"must be between {EARLIEST.year} and {LATEST.year}")
    return value


ExternalId = Annotated[str, StringConstraints(pattern=EXTERNAL_ID_RE.pattern)]


class LinkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_url: str = Field(max_length=MAX_URL_LENGTH)
    campaign_id: ExternalId
    creator_id: ExternalId
    platform: str | None = Field(default=None, pattern=PLATFORM_RE.pattern)
    active: bool = True
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("target_url")
    @classmethod
    def _safe_url(cls, value: str) -> str:
        return validate_target_url(value)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _timezone_aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else bounded_utc(value)

    @model_validator(mode="after")
    def _window_ordered(self) -> "LinkInput":
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


def validate_target_url(value: str) -> str:
    if any(ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in value):
        raise ValueError("must not contain whitespace or control characters")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https"):
        raise ValueError("must be an http(s) URL")
    if not parts.hostname:
        raise ValueError("must include a host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("must not include credentials")
    return value


@dataclass(frozen=True, slots=True)
class Link:
    id: int
    code: str
    campaign_id: str
    creator_id: str
    target_url: str
    platform: str | None
    active: bool
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def counts_at(self, now: datetime) -> bool:
        if not self.active:
            return False
        if self.starts_at is not None and now < self.starts_at:
            return False
        if self.ends_at is not None and now >= self.ends_at:
            return False
        return True


class _CachedLink(LinkInput):
    id: int = Field(gt=0, lt=2**63)
    code: str = Field(pattern=CODE_RE.pattern)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class LinkExists(Exception):
    pass


class LinkOwnerMismatch(Exception):
    """Changing the owner of a code would move its paid click history."""


class LinkStore(Protocol):
    async def get_by_code(self, code: str, *, miss_budget: str | None = None) -> Link | None:
        ...

    async def insert(self, code: str, data: LinkInput) -> Link:
        ...

    async def upsert(self, code: str, data: LinkInput) -> Link:
        ...

    async def deactivate(self, code: str) -> Link | None: ...

    async def list_by_campaign(self, campaign_id: str) -> list[Link]: ...


def generate_code() -> str:
    return secrets.token_urlsafe(_GENERATED_CODE_BYTES)


_COLUMNS = (
    "id, code, campaign_id, creator_id, target_url, platform, active, "
    "starts_at, ends_at, created_at, updated_at"
)
_SELECT_BY_CODE = f"SELECT {_COLUMNS} FROM links WHERE code = $1"
_SELECT_BY_CAMPAIGN = f"SELECT {_COLUMNS} FROM links WHERE campaign_id = $1 ORDER BY created_at, id"
_INSERT = (
    "INSERT INTO links (code, campaign_id, creator_id, target_url, platform, active, starts_at, ends_at) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
)
_INSERT_RETURNING = _INSERT + f"RETURNING {_COLUMNS}"
_UPSERT = (
    _INSERT
    + "ON CONFLICT (code) DO UPDATE SET "
    "target_url = EXCLUDED.target_url, platform = EXCLUDED.platform, active = EXCLUDED.active, "
    "starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at, updated_at = now() "
    "WHERE links.campaign_id = EXCLUDED.campaign_id AND links.creator_id = EXCLUDED.creator_id "
    f"RETURNING {_COLUMNS}"
)
_DEACTIVATE = f"UPDATE links SET active = FALSE, updated_at = now() WHERE code = $1 RETURNING {_COLUMNS}"


class PostgresLinkStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_by_code(self, code: str, *, miss_budget: str | None = None) -> Link | None:
        row = await self._pool.fetchrow(_SELECT_BY_CODE, code)
        return _from_row(row) if row else None

    async def insert(self, code: str, data: LinkInput) -> Link:
        try:
            row = await self._pool.fetchrow(_INSERT_RETURNING, code, *_params(data))
        except asyncpg.UniqueViolationError as exc:
            raise LinkExists(code) from exc
        return _from_row(row)

    async def upsert(self, code: str, data: LinkInput) -> Link:
        row = await self._pool.fetchrow(_UPSERT, code, *_params(data))
        if row is None:  # WHERE guard rejected the update
            raise LinkOwnerMismatch(code)
        return _from_row(row)

    async def deactivate(self, code: str) -> Link | None:
        row = await self._pool.fetchrow(_DEACTIVATE, code)
        return _from_row(row) if row else None

    async def list_by_campaign(self, campaign_id: str) -> list[Link]:
        rows = await self._pool.fetch(_SELECT_BY_CAMPAIGN, campaign_id)
        return [_from_row(row) for row in rows]


def _params(data: LinkInput) -> tuple:
    return (
        data.campaign_id,
        data.creator_id,
        data.target_url,
        data.platform,
        data.active,
        data.starts_at,
        data.ends_at,
    )


def _from_row(row: asyncpg.Record) -> Link:
    return Link(**dict(row))


_NEGATIVE = "-"


class CachedLinkStore:

    def __init__(
        self,
        inner: LinkStore,
        redis: Redis,
        *,
        positive_ttl: int,
        negative_ttl: int,
        miss_limit_per_minute: int = 0,
    ) -> None:
        self._inner = inner
        self._redis = redis
        self._positive_ttl = positive_ttl
        self._negative_ttl = negative_ttl
        self._miss_limit = miss_limit_per_minute

    async def get_by_code(self, code: str, *, miss_budget: str | None = None) -> Link | None:
        key = keys.link(code)
        try:
            cached = await self._redis.get(key)
        except RedisError as exc:
            log.warning("link cache read failed: %s", exc)
            cached = None
        if cached == _NEGATIVE:
            return None
        if cached:
            try:
                return _decode(cached)
            except ValueError as exc:
                log.warning("dropping unreadable cache entry for %s: %s", code, str(exc)[:200])

        if miss_budget and self._miss_limit and not await self._miss_allowed(miss_budget):
            return None
        link = await self._inner.get_by_code(code)
        value, ttl = (_encode(link), self._positive_ttl) if link else (_NEGATIVE, self._negative_ttl)
        try:
            await self._redis.set(key, value, ex=ttl)
        except RedisError as exc:
            log.warning("link cache write failed: %s", exc)
        return link

    async def _miss_allowed(self, key: str) -> bool:
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, 60)
                misses, _ = await pipe.execute()
        except RedisError as exc:
            log.warning("miss budget check failed: %s", exc)
            return True
        return misses <= self._miss_limit

    async def insert(self, code: str, data: LinkInput) -> Link:
        link = await self._inner.insert(code, data)
        await self._invalidate(code)
        return link

    async def upsert(self, code: str, data: LinkInput) -> Link:
        link = await self._inner.upsert(code, data)
        await self._invalidate(code)
        return link

    async def deactivate(self, code: str) -> Link | None:
        link = await self._inner.deactivate(code)
        if link:
            await self._invalidate(code)
        return link

    async def list_by_campaign(self, campaign_id: str) -> list[Link]:
        return await self._inner.list_by_campaign(campaign_id)

    async def _invalidate(self, code: str) -> None:
        await self._redis.delete(keys.link(code))


def _encode(link: Link) -> str:
    return json.dumps(
        {
            "id": link.id,
            "code": link.code,
            "campaign_id": str(link.campaign_id),
            "creator_id": str(link.creator_id),
            "target_url": link.target_url,
            "platform": link.platform,
            "active": link.active,
            "starts_at": link.starts_at.isoformat() if link.starts_at else None,
            "ends_at": link.ends_at.isoformat() if link.ends_at else None,
            "created_at": link.created_at.isoformat(),
            "updated_at": link.updated_at.isoformat(),
        },
        separators=(",", ":"),
    )


def _decode(raw: str | bytes) -> Link:
    # cache entries get the same validation as API input
    return Link(**_CachedLink.model_validate_json(raw, strict=True).model_dump())
