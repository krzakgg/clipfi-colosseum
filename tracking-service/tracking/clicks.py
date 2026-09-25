from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Literal

from redis.asyncio import Redis

from tracking import keys
from tracking.fingerprint import ip_hash, visitor_hash
from tracking.links import Link

Outcome = Literal["unique", "repeat", "ratelimited"]

_SCRIPT = files("tracking").joinpath("lua/count_click.lua").read_text(encoding="utf-8")


class ClickCounter:

    def __init__(
        self,
        redis: Redis,
        *,
        secret: bytes,
        rate_limit_per_minute: int,
        max_unique_per_ip_per_day: int,
        bucket_ttl: int,
        stream_maxlen: int,
    ) -> None:
        self._script = redis.register_script(_SCRIPT)
        self._secret = secret
        self._rate_limit = rate_limit_per_minute
        self._max_unique_per_ip = max_unique_per_ip_per_day
        self._bucket_ttl = bucket_ttl
        self._stream_maxlen = stream_maxlen

    def address(self, ip: str) -> str:
        return ip_hash(self._secret, ip)

    async def record(
        self,
        link: Link,
        *,
        ip: str,
        user_agent: str,
        referer_host: str | None,
        now: datetime,
    ) -> Outcome:
        now = now.astimezone(UTC)
        visitor = visitor_hash(self._secret, ip, user_agent, now.date())
        address = self.address(ip)
        epoch_minute = int(now.timestamp()) // 60
        result = await self._script(
            keys=[
                keys.rate_limit(address),
                keys.dedup(link.id, visitor),
                keys.bucket(epoch_minute),
                keys.BUCKET_INDEX,
                keys.EVENTS_STREAM,
                keys.ip_uniques(link.id, address),
            ],
            args=[
                self._rate_limit,
                seconds_until_utc_midnight(now),
                link.id,
                epoch_minute,
                self._bucket_ttl,
                self._stream_maxlen,
                int(now.timestamp() * 1000),
                visitor,
                referer_host or "",
                self._max_unique_per_ip,
            ],
        )
        return result.decode() if isinstance(result, bytes) else result


def seconds_until_utc_midnight(now: datetime) -> int:
    now = now.astimezone(UTC)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - now).total_seconds()))
