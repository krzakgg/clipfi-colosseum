# Tracking Service — design

Date: 2026-09-21. Scope: the *Tracking Service* microservice only (redirects, click
counting, click analytics). Identity, Campaign and Finance services are out of scope;
this service exposes an internal HTTP API for them.

## Responsibilities

1. **Redirect** a visitor who opens a creator's reflink (`/r/{code}`) to the campaign
   target URL as fast as possible.
2. **Count** the click in Redis on the hot path (one Lua script, one round trip), with
   per-visitor-per-day dedup, per-IP rate limiting and bot/prefetch filtering.
3. **Persist** counts and raw click events into PostgreSQL with minimal delay, via a
   separate flusher process, so that the API process never touches Postgres on the
   hot path (except a cache miss on link lookup).
4. **Serve** link/campaign statistics (time series, per-link totals, referer breakdown)
   to the other services over an authenticated internal API.

## Non-goals

Reflink *ownership* (which creator gets which link, payouts, budgets) stays in the
Campaign and Finance services. This service only knows `campaign_id`/`creator_id` as
opaque strings (`[A-Za-z0-9_-]{1,64}`, owned by the Campaign service) so that stats can be
grouped. No user-facing pages; a redirect is a bare
`302`.

## Components

| Component | Process | Purpose |
| --- | --- | --- |
| `tracking.app` | `uvicorn` | FastAPI app: public redirect route, internal API, health |
| `tracking.flusher` | `python -m tracking.flusher` | Redis stream/buckets → Postgres, event retention |
| `tracking.migrate` | one-shot | applies `migrations/*.sql` under an advisory lock |

Runtime dependencies: Redis 7 (single instance), PostgreSQL 14+.

## Data flow (hot path)

```
GET /r/{code}
  ├─ code regex check                → 404 on mismatch
  ├─ link lookup: Redis JSON cache   → miss: Postgres, then cache (positive 300 s / negative 30 s)
  ├─ link missing or active=false    → 404
  ├─ build 302 to link.target_url    (Cache-Control: no-store, X-Robots-Tag: noindex)
  ├─ countable?  method GET, real UA, no prefetch header, link inside [starts_at, ends_at)
  └─ if countable: Lua script (≤250 ms budget, failure never blocks the redirect)
        INCR   trk:rl:{ip_hash}            rate limit, 60 s window   → 'ratelimited'
        SET NX trk:dd:{link_id}:{visitor}  TTL until UTC midnight    → unique / repeat
        INCR   trk:ipu:{link_id}:{ip_hash}  daily cap on uniques per address (UA rotation)
        HINCRBY trk:bkt:{epoch_minute}  "{link_id}:r" (+ ":u" when unique)
        ZADD   trk:bkt:idx {epoch_minute}
        XADD   trk:events MAXLEN ~ N  {l, t, u, v, r}
```

Design choices:

* **Redirect even when not counting.** A link that is outside its campaign window still
  redirects (the studio still wants the traffic; the creator is just not paid). Only
  `active=false` (studio/ops disabled the link) or an unknown code returns 404.
* **302, never 301/308**, so browsers never cache the redirect and skip us.
* **Visitor identity** is `HMAC-SHA256(secret, utc_date | normalized_ip | user_agent)`.
  IPv6 is truncated to /64, IPv4-mapped addresses unwrapped. The raw IP is never stored
  or logged. Because the date is part of the hash, "unique" means *unique per link, per
  visitor, per UTC day*; the dedup key expires at midnight UTC.
* **Client IP trust** is explicit: `TRACKING_TRUSTED_PROXY_HOPS=N` takes the N-th value
  from the right of `X-Forwarded-For`; `0` uses the socket peer. Uvicorn's own proxy
  header handling is disabled so there is a single source of truth.
* **Counting failure is non-fatal**: Redis down or slow → the visitor is still
  redirected, the click is dropped and a warning is logged.

## Data flow (flusher)

Two independent loops in one process; both are safe to run in several replicas.

* **Events**: `XREADGROUP` (group `pg`) in batches → `INSERT ... ON CONFLICT DO NOTHING`
  into `click_events` → `XACK`. On start, own pending entries are replayed and stale
  entries of dead consumers are `XAUTOCLAIM`ed. Malformed entries are logged and acked.
* **Buckets**: every `flush_interval` seconds, for every minute in `trk:bkt:idx`:
  `HGETALL` → upsert into `click_buckets` with `GREATEST(existing, incoming)` (set
  semantics, so re-flushing is idempotent) → if the minute is older than
  `bucket_close_grace` (5 min, must exceed API/flusher clock skew), `DEL` the hash and
  `ZREM` it from the index. A click that lands in an already closed minute is lost, not
  double counted; hosts are assumed NTP-synced.
* **Retention**: hourly batched `DELETE` of `click_events` older than
  `events_retention_days` (0 disables). `click_buckets` are kept forever (small).

`click_buckets` is the authoritative source for payouts. `click_events` is for
analytics and fraud review; the stream is trimmed approximately at `stream_maxlen`, so
under an extreme backlog events can be lost while counts are not (bucket hashes live
48 h in Redis).

## Postgres schema

`links(id, code UNIQUE, campaign_id, creator_id, target_url, platform, active,
starts_at, ends_at, created_at, updated_at)`,
`click_buckets(link_id, bucket_start, raw_clicks, unique_clicks) PK(link_id,
bucket_start)`, `click_events(id = stream id, link_id, occurred_at, is_unique,
visitor_hash, referer_host)`, `schema_migrations(version)`.

Links are never hard-deleted (history must stay consistent for payouts).

## Internal API (bearer `TRACKING_SERVICE_TOKEN`, constant-time compare)

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/internal/links` | create with a generated 11-char random code |
| PUT | `/internal/links/{code}` | idempotent upsert; `campaign_id`/`creator_id` immutable (409) |
| GET | `/internal/links/{code}` | link + totals |
| DELETE | `/internal/links/{code}` | sets `active=false` |
| GET | `/internal/links/{code}/stats` | series: `from`, `to`, `granularity` |
| GET | `/internal/campaigns/{id}/links` | links with totals (creator table) |
| GET | `/internal/campaigns/{id}/stats` | series, optional `group_by=platform|creator` |
| GET | `/internal/campaigns/{id}/referers` | top referer hosts from events |

Series requests are capped at 10 000 points. `granularity` is an enum mapped to
`date_trunc`; no SQL is ever built from strings.

## Security summary

Hardened on 2026-09-23 after an attack-test pass.

* Public and internal routes run as separate processes (`TRACKING_API_ROLE`); only the
  public one is published, Redis/Postgres sit on an `internal: true` network.
* An ASGI gate checks the service token and caps the body before FastAPI parses it.
* `X-Forwarded-For` is honoured only from peers in `TRACKING_TRUSTED_PROXIES`.
* Cached links are re-validated on read; trailing-slash redirects are disabled;
  unknown JSON fields are rejected; timestamps are bounded to 2000-2100.
* uvicorn runs h11 with a buffer limit and no access log; the application refuses
  CL+TE framing (400, close) and oversized headers (431), budgets uncached lookups per
  address, and connects to Postgres as a least-privilege account (migration 0002).
  Redis requires a password.

* Secrets only from environment; minimum length enforced at startup.
* Public route: strict code regex, no user input reflected, `Location` only from
  validated stored URLs (http/https, host present, no credentials, no control chars).
* Internal route: bearer token, `hmac.compare_digest`, OpenAPI docs disabled by default.
* No raw IPs stored or logged anywhere; visitor hash is keyed and day-rotating.
* Bot/prefetch/HEAD requests are redirected but not counted; per-IP rate limit inside
  the Lua script bounds Redis growth from a single source.
* All SQL parametrised (asyncpg); migrations run under `pg_advisory_lock`.
* Container runs as a non-root user.
