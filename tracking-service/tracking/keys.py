PREFIX = "trk"

BUCKET_INDEX = f"{PREFIX}:bkt:idx"
EVENTS_STREAM = f"{PREFIX}:events"
EVENTS_GROUP = "pg"


def link(code: str) -> str:
    return f"{PREFIX}:link:{code}"


def dedup(link_id: int, visitor_hash: str) -> str:
    return f"{PREFIX}:dd:{link_id}:{visitor_hash}"


def rate_limit(ip_hash: str) -> str:
    return f"{PREFIX}:rl:{ip_hash}"


def ip_uniques(link_id: int, ip_hash: str) -> str:
    return f"{PREFIX}:ipu:{link_id}:{ip_hash}"


def miss_budget(ip_hash: str) -> str:
    return f"{PREFIX}:miss:{ip_hash}"


def bucket(epoch_minute: int) -> str:
    return f"{PREFIX}:bkt:{epoch_minute}"
