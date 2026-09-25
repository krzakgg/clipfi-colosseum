import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from tracking import keys
from tracking.filters import referer_host, reject_reason
from tracking.fingerprint import client_ip
from tracking.links import CODE_RE

log = logging.getLogger(__name__)

router = APIRouter()

_REDIRECT_HEADERS = {
    "Cache-Control": "no-store, private",
    "X-Robots-Tag": "noindex, nofollow",
}


@router.api_route("/{code}", methods=["GET", "HEAD"], include_in_schema=False)
async def redirect(code: str, request: Request) -> RedirectResponse:
    if not CODE_RE.fullmatch(code):
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    deps = request.app.state.deps
    settings = request.app.state.settings
    peer = request.client.host if request.client else None
    # HAProxy appends its own header line instead of extending the existing one
    forwarded_for = ", ".join(request.headers.getlist("x-forwarded-for")) or None
    ip = client_ip(peer, forwarded_for, settings.trusted_proxy_hops, settings.trusted_proxies)

    miss_budget = keys.miss_budget(deps.counter.address(ip)) if ip else None
    link = await deps.links.get_by_code(code, miss_budget=miss_budget)
    if link is None or not link.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    response = RedirectResponse(link.target_url, status_code=status.HTTP_302_FOUND, headers=_REDIRECT_HEADERS)

    now = datetime.now(UTC)
    if not link.counts_at(now):
        return response
    if reject_reason(request.method, request.headers) is not None or ip is None:
        return response

    try:
        await asyncio.wait_for(
            deps.counter.record(
                link,
                ip=ip,
                user_agent=request.headers["user-agent"],
                referer_host=referer_host(request.headers),
                now=now,
            ),
            timeout=settings.count_timeout,
        )
    except TimeoutError:
        log.warning("click not counted for link %s: redis timeout", link.id)
    except Exception as exc:
        log.warning("click not counted for link %s: %s", link.id, exc)
    return response
