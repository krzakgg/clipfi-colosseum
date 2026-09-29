import pytest

from tracking.filters import referer_host, reject_reason

BROWSER = {"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0 Safari/537.36"}


def test_plain_browser_get_is_counted():
    assert reject_reason("GET", BROWSER) is None


def test_head_is_not_counted():
    assert reject_reason("HEAD", BROWSER) == "method"


def test_missing_user_agent_is_not_counted():
    assert reject_reason("GET", {}) == "no_user_agent"
    assert reject_reason("GET", {"user-agent": "   "}) == "no_user_agent"


@pytest.mark.parametrize(
    "ua",
    [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Discordbot/2.0",
        "facebookexternalhit/1.1",
        "curl/8.4.0",
        "python-requests/2.32",
        "Mozilla/5.0 HeadlessChrome/120.0",
        "TelegramBot (like TwitterBot)",
        "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
        "DuckDuckBot-Https/1.1",
        "Mozilla/5.0 (compatible; PetalBot;+https://webmaster.petalsearch.com/site/petalbot)",
    ],
)
def test_bots_and_link_previews_are_not_counted(ua):
    assert reject_reason("GET", {"user-agent": ua}) == "bot"


@pytest.mark.parametrize(
    "ua",
    [
        "Mozilla/5.0 (Linux; Android 10; CUBOT X30) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Version/17.5 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    ],
)
def test_real_devices_are_counted(ua):
    assert reject_reason("GET", {"user-agent": ua}) is None


@pytest.mark.parametrize(
    "header,value",
    [("purpose", "prefetch"), ("sec-purpose", "prefetch;prerender"), ("x-moz", "prefetch"), ("x-purpose", "preview")],
)
def test_prefetch_is_not_counted(header, value):
    assert reject_reason("GET", {**BROWSER, header: value}) == "prefetch"


def test_referer_host_keeps_only_the_host():
    assert referer_host({"referer": "https://www.YouTube.com/watch?v=abc&user=secret"}) == "www.youtube.com"
    assert referer_host({"referer": "https://[2001:db8::1]:8443/x"}) == "2001:db8::1"
    assert referer_host({}) is None
    assert referer_host({"referer": "not a url"}) is None
    assert referer_host({"referer": "https://" + "a" * 300 + ".com/"}) is None


@pytest.mark.parametrize(
    "referer",
    [
        "https://evil<script>alert(1)</script>.com/x",
        "https://host with space/",
        "https://%3Cb%3E.example/",
    ],
)
def test_referer_hosts_with_markup_or_odd_characters_are_dropped(referer):
    assert referer_host({"referer": referer}) is None


def test_referer_ip_literals_are_kept():
    assert referer_host({"referer": "http://203.0.113.5:8080/"}) == "203.0.113.5"
