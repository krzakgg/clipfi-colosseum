import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from tests.backend.conftest import SERVICE_TOKEN
from tracking_client import (
    ClickTotals,
    TrackingClient,
    TrackingRejected,
    TrackingUnavailable,
)

START = datetime(2026, 10, 1, tzinfo=timezone.utc)


def client_for(handler) -> TrackingClient:
    return TrackingClient(
        "http://tracking.internal", SERVICE_TOKEN, "https://go.example.com/r/", transport=httpx.MockTransport(handler)
    )


async def test_create_link_sends_ids_as_strings_with_the_campaign_window():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(201, json={"code": "abcDEF12345"})

    code = await client_for(handler).create_link(
        campaign_id=42,
        creator_id=7,
        target_url="https://shop.example.com/game",
        starts_at=START,
        ends_at=START + timedelta(days=30),
    )

    assert code == "abcDEF12345"
    request = seen[0]
    assert (request.method, request.url.path) == ("POST", "/internal/links")
    assert request.headers["authorization"] == f"Bearer {SERVICE_TOKEN}"
    assert json.loads(request.content) == {
        "target_url": "https://shop.example.com/game",
        "campaign_id": "42",
        "creator_id": "7",
        "starts_at": "2026-10-01T00:00:00+00:00",
        "ends_at": "2026-10-31T00:00:00+00:00",
    }


async def test_naive_dates_are_sent_as_utc_and_missing_ones_as_null():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"code": "abcDEF12345"})

    await client_for(handler).update_link(
        "abcDEF12345", campaign_id=1, creator_id=2, target_url="https://x.example", starts_at=datetime(2026, 10, 1), ends_at=None
    )

    body = json.loads(seen[0].content)
    assert (seen[0].method, seen[0].url.path) == ("PUT", "/internal/links/abcDEF12345")
    assert (body["starts_at"], body["ends_at"]) == ("2026-10-01T00:00:00+00:00", None)


def test_public_url_joins_the_redirect_base_and_the_code():
    assert client_for(lambda request: None).public_url("abcDEF12345") == "https://go.example.com/r/abcDEF12345"


@pytest.mark.parametrize(
    "status_code,body,expected",
    [
        (422, {"detail": [{"msg": "Value error, must be an http(s) URL"}]}, "must be an http(s) URL"),
        (409, {"detail": "campaign_id and creator_id of an existing link cannot change"}, "cannot change"),
    ],
)
async def test_refusals_carry_the_reason(status_code, body, expected):
    tracking = client_for(lambda request: httpx.Response(status_code, json=body))
    with pytest.raises(TrackingRejected) as refused:
        await tracking.create_link(campaign_id=1, creator_id=2, target_url="ftp://x", starts_at=None, ends_at=None)
    assert expected in refused.value.detail


OPERATIONS = {
    "create": lambda t: t.create_link(campaign_id=1, creator_id=2, target_url="https://x.example", starts_at=None, ends_at=None),
    "update": lambda t: t.update_link(
        "abcDEF12345", campaign_id=1, creator_id=2, target_url="https://x.example", starts_at=None, ends_at=None
    ),
    "deactivate": lambda t: t.deactivate_link("abcDEF12345"),
    "link_totals": lambda t: t.link_totals("abcDEF12345"),
    "campaign_totals": lambda t: t.campaign_totals(1),
}


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("status_code", [301, 400, 401, 403, 500, 502, 503])
async def test_server_side_failures_mean_unavailable(operation, status_code):
    tracking = client_for(lambda request: httpx.Response(status_code, json={"detail": "nope"}))
    with pytest.raises(TrackingUnavailable):
        await OPERATIONS[operation](tracking)


@pytest.mark.parametrize("operation, status_code", [("create", 200), ("update", 201), ("update", 204), ("deactivate", 200)])
async def test_an_unexpected_success_code_is_not_taken_as_success(operation, status_code):
    tracking = client_for(lambda request: httpx.Response(status_code, json={"code": "abcDEF12345"}))
    with pytest.raises(TrackingUnavailable):
        await OPERATIONS[operation](tracking)


async def test_network_failures_mean_unavailable():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(TrackingUnavailable):
        await client_for(handler).link_totals("abcDEF12345")


async def test_deactivating_a_link_tracking_does_not_know_is_not_an_error():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(404, json={"detail": "Not Found"})

    await client_for(handler).deactivate_link("abcDEF12345")
    assert (seen[0].method, seen[0].url.path) == ("DELETE", "/internal/links/abcDEF12345")


async def test_link_totals():
    def handler(request):
        if request.url.path.endswith("known-code"):
            return httpx.Response(200, json={"code": "known-code", "totals": {"raw": 5, "unique": 2}})
        return httpx.Response(404, json={"detail": "Not Found"})

    tracking = client_for(handler)
    assert await tracking.link_totals("known-code") == ClickTotals(raw=5, unique=2)
    assert await tracking.link_totals("other-code") is None


async def test_campaign_totals_are_keyed_by_code():
    def handler(request):
        assert request.url.path == "/internal/campaigns/42/links"
        return httpx.Response(
            200,
            json=[
                {"code": "first-code", "totals": {"raw": 9, "unique": 4}},
                {"code": "other-code", "totals": {"raw": 0, "unique": 0}},
            ],
        )

    assert await client_for(handler).campaign_totals(42) == {
        "first-code": ClickTotals(raw=9, unique=4),
        "other-code": ClickTotals(raw=0, unique=0),
    }


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>proxy error page</html>"),
        httpx.Response(204),
        httpx.Response(307, headers={"location": "http://elsewhere"}),
        httpx.Response(200, json={"unexpected": "shape"}),
        httpx.Response(200, json=["not", "objects"]),
    ],
)
async def test_anything_but_a_well_formed_answer_means_unavailable(response):
    tracking = client_for(lambda request: response)
    with pytest.raises(TrackingUnavailable):
        await tracking.campaign_totals(1)
    with pytest.raises(TrackingUnavailable):
        await tracking.link_totals("abcDEF12345")
    with pytest.raises(TrackingUnavailable):
        await tracking.create_link(campaign_id=1, creator_id=2, target_url="https://x.example", starts_at=None, ends_at=None)


@pytest.mark.parametrize(
    "response,expected",
    [
        (httpx.Response(422, text="plain text refusal"), "plain text refusal"),
        (httpx.Response(422, json={"detail": {"field": "bad"}}), "bad"),
        (httpx.Response(422, json=["odd"]), "odd"),
    ],
)
async def test_refusals_with_unusual_bodies_still_carry_a_reason(response, expected):
    tracking = client_for(lambda request: response)
    with pytest.raises(TrackingRejected) as refused:
        await tracking.create_link(campaign_id=1, creator_id=2, target_url="https://x.example", starts_at=None, ends_at=None)
    assert expected in refused.value.detail
