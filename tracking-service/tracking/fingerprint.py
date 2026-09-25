import hashlib
import hmac
import ipaddress
import logging
from collections.abc import Collection
from datetime import date

Network = ipaddress.IPv4Network | ipaddress.IPv6Network

log = logging.getLogger(__name__)

HASH_HEX_LENGTH = 32  # 128 bits


def client_ip(
    peer: str | None,
    forwarded_for: str | None,
    trusted_hops: int,
    trusted_proxies: Collection[Network] = (),
) -> str | None:
    """The N-th X-Forwarded-For entry from the right, if the peer is a trusted proxy."""
    if trusted_hops > 0 and _is_trusted(peer, trusted_proxies):
        hops = [_strip_port(part.strip()) for part in (forwarded_for or "").split(",")]
        if len(hops) >= trusted_hops and _is_ip(hops[-trusted_hops]):
            return hops[-trusted_hops]
        _warn_once(
            "TRACKING_TRUSTED_PROXY_HOPS=%d but X-Forwarded-For has %d usable hop(s); "
            "falling back to the peer address, so every visitor shares one rate limit",
            trusted_hops,
            sum(_is_ip(hop) for hop in hops),
        )
    if peer and _is_ip(peer):
        return peer
    return None


def _is_trusted(peer: str | None, networks: Collection[Network]) -> bool:
    if not peer or not _is_ip(peer):
        return False
    addr = ipaddress.ip_address(peer)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return any(addr in network for network in networks)


def _strip_port(value: str) -> str:
    if value.startswith("["):  # [v6]:port
        end = value.find("]")
        return value[1:end] if end > 0 else value
    if value.count(":") == 1:  # v4:port
        return value.rsplit(":", 1)[0]
    return value


_warned = False


def _warn_once(message: str, *args: object) -> None:
    global _warned
    if not _warned:
        _warned = True
        log.warning(message, *args)


def normalize_ip(ip: str) -> str:
    # IPv6 privacy extensions rotate inside a /64, so the /64 is the identity
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network((addr, 64), strict=False).network_address)
    return str(addr)


def visitor_hash(secret: bytes, ip: str, user_agent: str, day: date) -> str:
    message = f"{day.isoformat()}|{normalize_ip(ip)}|{user_agent}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()[:HASH_HEX_LENGTH]


def ip_hash(secret: bytes, ip: str) -> str:
    message = f"ip|{normalize_ip(ip)}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()[:HASH_HEX_LENGTH]


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True
