"""Moves click events and per-minute counters from Redis to Postgres."""

import asyncio
import logging
import signal
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import asyncpg
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from tracking import keys
from tracking.config import Settings, configure_logging
from tracking.filters import is_plain_host
from tracking.links import EARLIEST, LATEST, bounded_utc

log = logging.getLogger(__name__)

_CLAIM_INTERVAL = 60.0
_PRUNE_INTERVAL = 3600.0
_PRUNE_BATCH = 10_000
_MAX_BACKOFF = 30.0
_MAX_BIGINT = 2**63 - 1
_MAX_INT = 2**31 - 1
_FIRST_MINUTE = int(EARLIEST.timestamp()) // 60
_LAST_MINUTE = int(LATEST.timestamp()) // 60
_VISITOR_HASH_LENGTH = 32


@dataclass(frozen=True, slots=True)
class ClickEvent:
    id: str
    link_id: int
    occurred_at: datetime
    is_unique: bool
    visitor_hash: str
    referer_host: str | None


@dataclass(frozen=True, slots=True)
class BucketRow:
    link_id: int
    bucket_start: datetime
    raw: int
    unique: int


class Sink(Protocol):
    async def write_events(self, events: Sequence[ClickEvent]) -> None: ...

    async def write_buckets(self, rows: Sequence[BucketRow]) -> None: ...

    async def prune_events(self, older_than: datetime, limit: int) -> int:
        ...


def parse_event(entry_id: str, fields: dict[str, str]) -> ClickEvent:
    link_id = int(fields["l"])
    if not 0 < link_id <= _MAX_BIGINT:
        raise ValueError(f"link id out of range: {fields['l'][:30]}")
    try:
        occurred_at = bounded_utc(datetime.fromtimestamp(int(fields["t"]) / 1000, tz=UTC))
    except (OverflowError, OSError) as exc:
        raise ValueError(f"timestamp out of range: {fields['t'][:30]}") from exc
    visitor = fields["v"]
    if len(visitor) != _VISITOR_HASH_LENGTH or not all(c in "0123456789abcdef" for c in visitor):
        raise ValueError("visitor hash is not a 32-character hex digest")
    referer = fields["r"] or None
    if referer is not None and not is_plain_host(referer):
        raise ValueError("referer is not a plain host")
    return ClickEvent(
        id=entry_id,
        link_id=link_id,
        occurred_at=occurred_at,
        is_unique=fields["u"] == "1",
        visitor_hash=visitor,
        referer_host=referer,
    )


def parse_bucket(epoch_minute: int, fields: dict[str, str]) -> list[BucketRow]:
    counts: dict[int, dict[str, int]] = {}
    for field, value in fields.items():
        link_id, _, kind = field.partition(":")
        try:
            parsed_link, parsed_value = int(link_id), int(value)
            # must fit the BIGINT / INTEGER columns
            valid = kind in ("r", "u") and 0 < parsed_link <= _MAX_BIGINT and 0 <= parsed_value <= _MAX_INT
        except ValueError:
            valid = False
        if not valid:
            log.error("skipping malformed bucket field %r=%r in minute %d", field[:64], value[:32], epoch_minute)
            continue
        counts.setdefault(parsed_link, {})[kind] = parsed_value
    bucket_start = datetime.fromtimestamp(epoch_minute * 60, tz=UTC)
    return [
        BucketRow(link_id=link_id, bucket_start=bucket_start, raw=c.get("r", 0), unique=c.get("u", 0))
        for link_id, c in sorted(counts.items())
    ]


class Flusher:
    def __init__(
        self,
        redis: Redis,
        sink: Sink,
        settings: Settings,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._redis = redis
        self._sink = sink
        self._settings = settings
        self._clock = clock
        self._consumer = settings.consumer_name

    async def run(self, stop: asyncio.Event) -> None:
        await self.ensure_group()
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self._events_loop(stop), name="events")
            tasks.create_task(self._buckets_loop(stop), name="buckets")
            if self._settings.events_retention_days:
                tasks.create_task(self._prune_loop(stop), name="prune")

    async def ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(keys.EVENTS_STREAM, keys.EVENTS_GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def flush_events_once(self, *, block_ms: int | None = None) -> int:
        response = await self._redis.xreadgroup(
            keys.EVENTS_GROUP,
            self._consumer,
            {keys.EVENTS_STREAM: ">"},
            count=self._settings.events_batch_size,
            block=block_ms,
        )
        return await self._persist(_entries(response))

    async def drain_own_pending(self) -> int:
        """Replay entries this consumer read but never acked (crash recovery)."""
        total = 0
        while True:
            response = await self._redis.xreadgroup(
                keys.EVENTS_GROUP,
                self._consumer,
                {keys.EVENTS_STREAM: "0"},
                count=self._settings.events_batch_size,
            )
            entries = _entries(response)
            if not entries:
                return total
            total += await self._persist(entries)

    async def claim_stale_once(self) -> int:
        total = 0
        start = "0-0"
        while True:
            response = await self._redis.xautoclaim(
                keys.EVENTS_STREAM,
                keys.EVENTS_GROUP,
                self._consumer,
                min_idle_time=self._settings.pending_claim_idle_ms,
                start_id=start,
                count=self._settings.events_batch_size,
            )
            next_start, entries = response[0], response[1]
            total += await self._persist(entries)
            if not entries or next_start == "0-0":
                return total
            start = next_start

    async def _persist(self, entries: Sequence[tuple[str, dict[str, str] | None]]) -> int:
        events: list[ClickEvent] = []
        discard: list[str] = []
        for entry_id, fields in entries:
            if fields is None:  # trimmed from the stream while pending
                discard.append(entry_id)
                continue
            try:
                events.append(parse_event(entry_id, fields))
            except (KeyError, ValueError, TypeError) as exc:
                log.error("discarding malformed click event %s: %s", entry_id, exc)
                discard.append(entry_id)
        if events:
            await self._sink.write_events(events)
        acked = [event.id for event in events] + discard
        if acked:
            await self._redis.xack(keys.EVENTS_STREAM, keys.EVENTS_GROUP, *acked)
        return len(events)

    async def _events_loop(self, stop: asyncio.Event) -> None:
        backoff = 1.0
        last_claim = 0.0
        while not stop.is_set():
            try:
                if time.monotonic() - last_claim >= _CLAIM_INTERVAL:
                    await self.drain_own_pending()
                    await self.claim_stale_once()
                    last_claim = time.monotonic()
                if not await self.flush_events_once(block_ms=self._settings.events_block_ms):
                    await asyncio.sleep(0)
                backoff = 1.0
            except Exception:
                log.exception("event flush failed; retrying in %.0fs", backoff)
                await _sleep(stop, backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)
                last_claim = 0.0

    async def flush_buckets_once(self) -> int:
        now_minute = int(self._clock().timestamp()) // 60
        close_before = now_minute - (self._settings.bucket_close_grace + 59) // 60
        written = 0
        for member in await self._redis.zrange(keys.BUCKET_INDEX, 0, -1):
            try:
                minute = int(member)
                valid = _FIRST_MINUTE <= minute < _LAST_MINUTE
            except ValueError:
                minute, valid = None, False
            if not valid:
                log.error("dropping malformed bucket index entry %r", member[:64])
                async with self._redis.pipeline(transaction=True) as pipe:
                    pipe.zrem(keys.BUCKET_INDEX, member)
                    if minute is not None:
                        pipe.delete(keys.bucket(minute))
                    await pipe.execute()
                continue
            key = keys.bucket(minute)
            rows = parse_bucket(minute, await self._redis.hgetall(key))
            if rows:
                await self._sink.write_buckets(rows)
                written += len(rows)
            if minute < close_before:
                async with self._redis.pipeline(transaction=True) as pipe:
                    pipe.delete(key)
                    pipe.zrem(keys.BUCKET_INDEX, member)
                    await pipe.execute()
        return written

    async def _buckets_loop(self, stop: asyncio.Event) -> None:
        backoff = 1.0
        while not stop.is_set():
            try:
                await self.flush_buckets_once()
                backoff = 1.0
                await _sleep(stop, self._settings.flush_interval)
            except Exception:
                log.exception("bucket flush failed; retrying in %.0fs", backoff)
                await _sleep(stop, backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)

    async def prune_once(self) -> int:
        cutoff = self._clock() - timedelta(days=self._settings.events_retention_days)
        total = 0
        while True:
            deleted = await self._sink.prune_events(cutoff, _PRUNE_BATCH)
            total += deleted
            if deleted < _PRUNE_BATCH:
                return total

    async def _prune_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                deleted = await self.prune_once()
                if deleted:
                    log.info("pruned %d click events", deleted)
            except Exception:
                log.exception("event pruning failed")
            await _sleep(stop, _PRUNE_INTERVAL)


def _entries(response) -> list[tuple[str, dict[str, str] | None]]:
    if not response:
        return []
    return list(response[0][1])


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


_INSERT_EVENT = (
    "INSERT INTO click_events (id, link_id, occurred_at, is_unique, visitor_hash, referer_host) "
    "VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (id) DO NOTHING"
)
_UPSERT_BUCKET = (
    "INSERT INTO click_buckets (link_id, bucket_start, raw_clicks, unique_clicks) "
    "VALUES ($1, $2, $3, $4) "
    "ON CONFLICT (link_id, bucket_start) DO UPDATE SET "
    "raw_clicks = GREATEST(click_buckets.raw_clicks, EXCLUDED.raw_clicks), "
    "unique_clicks = GREATEST(click_buckets.unique_clicks, EXCLUDED.unique_clicks)"
)
_PRUNE_EVENTS = (
    "DELETE FROM click_events WHERE ctid IN "
    "(SELECT ctid FROM click_events WHERE occurred_at < $1 LIMIT $2)"
)


class PostgresSink:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def write_events(self, events: Sequence[ClickEvent]) -> None:
        rows = [(e.id, e.link_id, e.occurred_at, e.is_unique, e.visitor_hash, e.referer_host) for e in events]
        await self._write(_INSERT_EVENT, rows, "click event")

    async def write_buckets(self, rows: Sequence[BucketRow]) -> None:
        params = [(r.link_id, r.bucket_start, r.raw, r.unique) for r in rows]
        await self._write(_UPSERT_BUCKET, params, "bucket")

    async def prune_events(self, older_than: datetime, limit: int) -> int:
        status = await self._pool.execute(_PRUNE_EVENTS, older_than, limit)
        return int(status.rsplit(" ", 1)[-1])

    async def _write(self, statement: str, rows: list[tuple], what: str) -> None:
        async with self._pool.acquire() as conn:
            try:
                async with conn.transaction():
                    await conn.executemany(statement, rows)
                return
            except (asyncpg.IntegrityConstraintViolationError, asyncpg.DataError) as exc:
                log.warning("batch of %d %ss rejected (%s); retrying row by row", len(rows), what, exc)
            # one bad row must not block the whole batch forever
            for row in rows:
                try:
                    await conn.execute(statement, *row)
                except (asyncpg.IntegrityConstraintViolationError, asyncpg.DataError) as exc:
                    log.error("dropping %s %r: %s", what, row[:2], exc)



async def _main(settings: Settings) -> None:
    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=settings.events_block_ms / 1000 + 5,
        socket_connect_timeout=5,
        health_check_interval=30,
    )
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=4, command_timeout=60)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    log.info("flusher %s starting", settings.consumer_name)
    try:
        await Flusher(redis, PostgresSink(pool), settings).run(stop)
    finally:
        await pool.close()
        await redis.aclose()
        log.info("flusher stopped")


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    asyncio.run(_main(settings))


if __name__ == "__main__":
    main()
