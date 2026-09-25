from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

import asyncpg

from tracking.links import Link


class Granularity(StrEnum):
    minute = "minute"
    hour = "hour"
    day = "day"


class GroupBy(StrEnum):
    platform = "platform"
    creator = "creator"


@dataclass(frozen=True, slots=True)
class Totals:
    raw: int
    unique: int


@dataclass(frozen=True, slots=True)
class Point:
    bucket: datetime
    raw: int
    unique: int
    group: str | None = None


@dataclass(frozen=True, slots=True)
class RefererCount:
    host: str | None
    clicks: int


class StatsSource(Protocol):
    async def link_totals(self, link_id: int) -> Totals: ...

    async def link_series(self, link_id: int, start: datetime, end: datetime, granularity: Granularity) -> list[Point]: ...

    async def campaign_links(self, campaign_id: str) -> list[tuple[Link, Totals]]: ...

    async def campaign_series(
        self, campaign_id: str, start: datetime, end: datetime, granularity: Granularity, group_by: GroupBy | None
    ) -> list[Point]: ...

    async def campaign_referers(self, campaign_id: str, start: datetime, end: datetime, limit: int) -> list[RefererCount]: ...


_LINK_TOTALS = (
    "SELECT COALESCE(SUM(raw_clicks), 0) AS raw, COALESCE(SUM(unique_clicks), 0) AS uniq "
    "FROM click_buckets WHERE link_id = $1"
)
_LINK_SERIES = (
    "SELECT date_trunc($4::text, bucket_start, 'UTC') AS bucket, SUM(raw_clicks) AS raw, SUM(unique_clicks) AS uniq "
    "FROM click_buckets WHERE link_id = $1 AND bucket_start >= $2 AND bucket_start < $3 "
    "GROUP BY 1 ORDER BY 1"
)
_CAMPAIGN_LINKS = (
    "SELECT l.id, l.code, l.campaign_id, l.creator_id, l.target_url, l.platform, l.active, "
    "l.starts_at, l.ends_at, l.created_at, l.updated_at, "
    "COALESCE(SUM(b.raw_clicks), 0) AS raw, COALESCE(SUM(b.unique_clicks), 0) AS uniq "
    "FROM links l LEFT JOIN click_buckets b ON b.link_id = l.id "
    "WHERE l.campaign_id = $1 GROUP BY l.id ORDER BY l.created_at, l.id"
)
_CAMPAIGN_SERIES = (
    "SELECT date_trunc($4::text, b.bucket_start, 'UTC') AS bucket, SUM(b.raw_clicks) AS raw, SUM(b.unique_clicks) AS uniq "
    "FROM click_buckets b JOIN links l ON l.id = b.link_id "
    "WHERE l.campaign_id = $1 AND b.bucket_start >= $2 AND b.bucket_start < $3 "
    "GROUP BY 1 ORDER BY 1"
)
# explicit 'UTC' so results don't depend on the session TimeZone
_CAMPAIGN_SERIES_BY = {
    GroupBy.platform: (
        "SELECT date_trunc($4::text, b.bucket_start, 'UTC') AS bucket, COALESCE(l.platform, '') AS grp, "
        "SUM(b.raw_clicks) AS raw, SUM(b.unique_clicks) AS uniq "
        "FROM click_buckets b JOIN links l ON l.id = b.link_id "
        "WHERE l.campaign_id = $1 AND b.bucket_start >= $2 AND b.bucket_start < $3 "
        "GROUP BY 1, 2 ORDER BY 1, 2"
    ),
    GroupBy.creator: (
        "SELECT date_trunc($4::text, b.bucket_start, 'UTC') AS bucket, l.creator_id AS grp, "
        "SUM(b.raw_clicks) AS raw, SUM(b.unique_clicks) AS uniq "
        "FROM click_buckets b JOIN links l ON l.id = b.link_id "
        "WHERE l.campaign_id = $1 AND b.bucket_start >= $2 AND b.bucket_start < $3 "
        "GROUP BY 1, 2 ORDER BY 1, 2"
    ),
}
_CAMPAIGN_REFERERS = (
    "SELECT e.referer_host AS host, COUNT(*) AS clicks "
    "FROM click_events e JOIN links l ON l.id = e.link_id "
    "WHERE l.campaign_id = $1 AND e.occurred_at >= $2 AND e.occurred_at < $3 "
    "GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT $4"
)


class PostgresStats:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def link_totals(self, link_id: int) -> Totals:
        row = await self._pool.fetchrow(_LINK_TOTALS, link_id)
        return Totals(raw=int(row["raw"]), unique=int(row["uniq"]))

    async def link_series(self, link_id: int, start: datetime, end: datetime, granularity: Granularity) -> list[Point]:
        rows = await self._pool.fetch(_LINK_SERIES, link_id, start, end, granularity.value)
        return [Point(bucket=r["bucket"], raw=int(r["raw"]), unique=int(r["uniq"])) for r in rows]

    async def campaign_links(self, campaign_id: str) -> list[tuple[Link, Totals]]:
        rows = await self._pool.fetch(_CAMPAIGN_LINKS, campaign_id)
        result = []
        for row in rows:
            fields = dict(row)
            totals = Totals(raw=int(fields.pop("raw")), unique=int(fields.pop("uniq")))
            result.append((Link(**fields), totals))
        return result

    async def campaign_series(
        self, campaign_id: str, start: datetime, end: datetime, granularity: Granularity, group_by: GroupBy | None
    ) -> list[Point]:
        if group_by is None:
            rows = await self._pool.fetch(_CAMPAIGN_SERIES, campaign_id, start, end, granularity.value)
            return [Point(bucket=r["bucket"], raw=int(r["raw"]), unique=int(r["uniq"])) for r in rows]
        rows = await self._pool.fetch(_CAMPAIGN_SERIES_BY[group_by], campaign_id, start, end, granularity.value)
        return [Point(bucket=r["bucket"], raw=int(r["raw"]), unique=int(r["uniq"]), group=r["grp"]) for r in rows]

    async def campaign_referers(self, campaign_id: str, start: datetime, end: datetime, limit: int) -> list[RefererCount]:
        rows = await self._pool.fetch(_CAMPAIGN_REFERERS, campaign_id, start, end, limit)
        return [RefererCount(host=r["host"], clicks=int(r["clicks"])) for r in rows]
