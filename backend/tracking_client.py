from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypeVar

import httpx
from fastapi import Request

T = TypeVar("T")

UNAVAILABLE_DETAIL = "Serwis śledzenia kliknięć jest chwilowo niedostępny"


class TrackingError(Exception):
    pass


class TrackingUnavailable(TrackingError):
    pass


class TrackingRejected(TrackingError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ClickTotals:
    raw: int
    unique: int


class TrackingClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        redirect_base: str,
        *,
        timeout: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            transport=transport,
        )
        self._redirect_base = redirect_base.rstrip("/")

    def public_url(self, code: str) -> str:
        return f"{self._redirect_base}/{code}"

    async def create_link(
        self,
        *,
        campaign_id: int,
        creator_id: int,
        target_url: str,
        starts_at: datetime | None,
        ends_at: datetime | None,
    ) -> str:
        response = await self._send(
            "POST", "/internal/links", json=_link_body(campaign_id, creator_id, target_url, starts_at, ends_at)
        )
        _expect(response, 201)
        return _parsed(response, _code)

    async def update_link(
        self,
        code: str,
        *,
        campaign_id: int,
        creator_id: int,
        target_url: str,
        starts_at: datetime | None,
        ends_at: datetime | None,
    ) -> None:
        response = await self._send(
            "PUT", f"/internal/links/{code}", json=_link_body(campaign_id, creator_id, target_url, starts_at, ends_at)
        )
        _expect(response, 200)

    async def deactivate_link(self, code: str) -> None:
        _expect(await self._send("DELETE", f"/internal/links/{code}"), 204, 404)

    async def link_totals(self, code: str) -> ClickTotals | None:
        response = await self._send("GET", f"/internal/links/{code}")
        if response.status_code == 404:
            return None
        _expect(response, 200)
        return _parsed(response, lambda body: _totals(body["totals"]))

    async def campaign_totals(self, campaign_id: int) -> dict[str, ClickTotals]:
        response = await self._send("GET", f"/internal/campaigns/{campaign_id}/links")
        _expect(response, 200)
        return _parsed(response, lambda body: {_code(item): _totals(item["totals"]) for item in body})

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _send(self, method: str, path: str, *, json: Any = None) -> httpx.Response:
        try:
            response = await self._http.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise TrackingUnavailable(f"{method} {path}: {exc}") from exc
        if response.status_code in (409, 422):
            raise TrackingRejected(_detail(response))
        return response


def get_tracking(request: Request) -> TrackingClient:
    return request.app.state.tracking


def _link_body(
    campaign_id: int, creator_id: int, target_url: str, starts_at: datetime | None, ends_at: datetime | None
) -> dict[str, Any]:
    return {
        "target_url": target_url,
        "campaign_id": str(campaign_id),
        "creator_id": str(creator_id),
        "starts_at": _utc_iso(starts_at),
        "ends_at": _utc_iso(ends_at),
    }


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def _expect(response: httpx.Response, *statuses: int) -> None:
    if response.status_code not in statuses:
        request = response.request
        raise TrackingUnavailable(f"{request.method} {request.url.path}: HTTP {response.status_code}")


def _parsed(response: httpx.Response, parse: Callable[[Any], T]) -> T:
    try:
        return parse(response.json())
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        request = response.request
        raise TrackingUnavailable(f"{request.method} {request.url.path}: unexpected response body") from exc


def _code(body: Any) -> str:
    code = body["code"]
    if not isinstance(code, str):
        raise TypeError("code is not a string")
    return code


def _totals(body: Any) -> ClickTotals:
    return ClickTotals(raw=int(body["raw"]), unique=int(body["unique"]))


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or f"HTTP {response.status_code}"
    detail = body.get("detail", body) if isinstance(body, dict) else body
    if isinstance(detail, list):
        return "; ".join(str(item.get("msg", item)) if isinstance(item, dict) else str(item) for item in detail)
    if isinstance(detail, dict):
        return "; ".join(f"{key}: {value}" for key, value in detail.items())
    return str(detail)
