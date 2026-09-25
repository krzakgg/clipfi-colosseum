from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from tracking.clicks import ClickCounter
from tracking.links import LinkStore
from tracking.stats import StatsSource


@dataclass(slots=True)
class Deps:
    links: LinkStore
    counter: ClickCounter
    stats: StatsSource
    check_redis: Callable[[], Awaitable[None]]
    check_database: Callable[[], Awaitable[None]]
    close: Callable[[], Awaitable[None]]
