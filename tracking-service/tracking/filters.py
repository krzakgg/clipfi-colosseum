import re
from collections.abc import Mapping
from urllib.parse import urlsplit

# "bot" only at the end of a token, so phones like "CUBOT X30" still count
_BOT_UA = re.compile(
    r"bot(?:[/;)\-]|$)|crawl|spider|slurp|fetch|preview|scan|monitor|validator|lighthouse|pingdom|"
    r"headless|phantom|selenium|playwright|puppeteer|"
    r"curl|wget|httpie|python|java/|go-http|okhttp|httpclient|libwww|axios|node-fetch|"
    r"facebookexternalhit|whatsapp|telegram|discord|slack|twitter|linkedin|pinterest|skype|"
    r"embedly|quora|outbrain|vkshare|redditbot",
    re.IGNORECASE,
)
_PREFETCH_HEADERS = ("purpose", "sec-purpose", "x-purpose", "x-moz")
_PREFETCH_VALUES = ("prefetch", "prerender", "preview")
_HOST_RE = re.compile(r"[a-z0-9.\-]{1,253}|[0-9a-f:.]{2,45}")


def reject_reason(method: str, headers: Mapping[str, str]) -> str | None:
    if method != "GET":
        return "method"
    user_agent = headers.get("user-agent", "").strip()
    if not user_agent:
        return "no_user_agent"
    if _BOT_UA.search(user_agent):
        return "bot"
    for name in _PREFETCH_HEADERS:
        value = headers.get(name, "").lower()
        if any(marker in value for marker in _PREFETCH_VALUES):
            return "prefetch"
    return None


def is_plain_host(host: str) -> bool:
    return _HOST_RE.fullmatch(host) is not None


def referer_host(headers: Mapping[str, str]) -> str | None:
    referer = headers.get("referer")
    if not referer:
        return None
    try:
        host = urlsplit(referer).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()
    return host if is_plain_host(host) else None
