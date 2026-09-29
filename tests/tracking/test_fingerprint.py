import ipaddress
from datetime import date

from tracking.fingerprint import client_ip, ip_hash, normalize_ip, visitor_hash

SECRET = b"x" * 32
PROXIES = [ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("fd00::/8")]


def test_peer_used_when_no_proxies_trusted():
    assert client_ip("203.0.113.5", "10.0.0.1, 198.51.100.7", trusted_hops=0) == "203.0.113.5"


def test_forwarded_for_is_read_from_the_right():
    assert client_ip("10.0.0.2", "1.1.1.1, 203.0.113.5", 1, PROXIES) == "203.0.113.5"
    assert client_ip("10.0.0.2", "203.0.113.5, 10.0.0.1", 2, PROXIES) == "203.0.113.5"
    assert client_ip("::ffff:10.0.0.2", "203.0.113.5", 1, PROXIES) == "203.0.113.5"


def test_forwarded_for_is_ignored_when_the_peer_is_not_a_trusted_proxy():
    assert client_ip("198.51.100.9", "203.0.113.5", 1, PROXIES) == "198.51.100.9"
    assert client_ip("198.51.100.9", "203.0.113.5", 1) == "198.51.100.9"  # no proxies configured
    assert client_ip("2001:db8::9", "203.0.113.5", 1, PROXIES) == "2001:db8::9"


def test_forwarded_for_too_short_or_malformed_falls_back_to_peer():
    assert client_ip("10.0.0.2", "203.0.113.5", 2, PROXIES) == "10.0.0.2"
    assert client_ip("10.0.0.2", "not-an-ip", 1, PROXIES) == "10.0.0.2"
    assert client_ip("10.0.0.2", None, 1, PROXIES) == "10.0.0.2"


def test_forwarded_for_with_ports_is_accepted():
    assert client_ip("10.0.0.2", "203.0.113.5:51234", 1, PROXIES) == "203.0.113.5"
    assert client_ip("10.0.0.2", "[2001:db8::1]:51234", 1, PROXIES) == "2001:db8::1"
    assert client_ip("fd00::2", "2001:db8::1", 1, PROXIES) == "2001:db8::1"


def test_missing_forwarded_for_behind_trusted_proxy_warns_once(caplog):
    import tracking.fingerprint as fp

    fp._warned = False
    assert client_ip("10.0.0.2", None, 1, PROXIES) == "10.0.0.2"
    assert client_ip("10.0.0.2", "203.0.113.77", 2, PROXIES) == "10.0.0.2"
    assert caplog.text.count("falling back to the peer address") == 1
    assert "203.0.113.77" not in caplog.text  # never log a client address


def test_invalid_peer_yields_none():
    assert client_ip("unix-socket", None, trusted_hops=0) is None
    assert client_ip(None, None, trusted_hops=0) is None


def test_ipv6_is_truncated_to_slash_64():
    a = normalize_ip("2001:db8:abcd:1234:1111:2222:3333:4444")
    b = normalize_ip("2001:db8:abcd:1234:ffff:eeee:dddd:cccc")
    assert a == b == "2001:db8:abcd:1234::"
    assert normalize_ip("2001:db8:abcd:1235::1") != a


def test_ipv4_mapped_ipv6_is_unwrapped():
    assert normalize_ip("::ffff:203.0.113.5") == "203.0.113.5"


def test_visitor_hash_rotates_daily_and_depends_on_key():
    day1 = date(2026, 9, 21)
    day2 = date(2026, 9, 22)
    h1 = visitor_hash(SECRET, "203.0.113.5", "Mozilla/5.0", day1)
    assert len(h1) == 32 and all(c in "0123456789abcdef" for c in h1)
    assert h1 == visitor_hash(SECRET, "203.0.113.5", "Mozilla/5.0", day1)
    assert h1 != visitor_hash(SECRET, "203.0.113.5", "Mozilla/5.0", day2)
    assert h1 != visitor_hash(b"y" * 32, "203.0.113.5", "Mozilla/5.0", day1)
    assert h1 != visitor_hash(SECRET, "203.0.113.6", "Mozilla/5.0", day1)


def test_ip_hash_is_stable_across_ipv6_rotation():
    assert ip_hash(SECRET, "2001:db8::1") == ip_hash(SECRET, "2001:db8::2")
    assert ip_hash(SECRET, "2001:db8::1") != ip_hash(SECRET, "2001:db9::1")


def test_forwarded_for_is_ignored_when_no_hops_are_trusted_even_from_a_proxy():
    assert client_ip("10.0.0.2", "203.0.113.5", 0, PROXIES) == "10.0.0.2"


def test_a_peer_that_is_not_an_address_is_never_a_trusted_proxy():
    assert client_ip("unix-socket", "203.0.113.5", 1, PROXIES) is None
    assert client_ip(None, "203.0.113.5", 1, PROXIES) is None
