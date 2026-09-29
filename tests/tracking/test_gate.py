import json

import pytest

from tests.tracking.conftest import SERVICE_TOKEN
from tracking.auth import InternalGate
from tracking.hardening import RequestGuard

TOKEN = SERVICE_TOKEN.encode()
AUTH = (b"authorization", f"Bearer {SERVICE_TOKEN}".encode())


class Inner:
    def __init__(self) -> None:
        self.calls = 0
        self.bodies: list[bytes] = []
        self.after_body: list[dict] = []

    async def __call__(self, scope, receive, send):
        self.calls += 1
        if scope["type"] != "http":
            return
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        self.bodies.append(body)
        self.after_body.append(await receive())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"inner"})


def http_scope(path: str, headers: list[tuple[bytes, bytes]], root_path: str = "") -> dict:
    return {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": root_path,
        "headers": headers, "client": ("203.0.113.5", 1), "server": ("tracking.test", 80),
    }


async def drive(app, scope, chunks: list[bytes], *, disconnect_after: int | None = None):
    messages = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1} for i, chunk in enumerate(chunks)
    ]
    if disconnect_after is not None:
        messages = messages[:disconnect_after]
    received = 0
    sent: list[dict] = []

    async def receive():
        nonlocal received
        received += 1
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    start = next((m for m in sent if m["type"] == "http.response.start"), None)
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return (start["status"] if start else None), body, received


@pytest.fixture
def inner():
    return Inner()


@pytest.fixture
def gate(inner):
    return InternalGate(inner, token=TOKEN, max_body=1024)


async def test_authenticated_body_reaches_the_app_exactly_once(gate, inner):
    status, body, _ = await drive(gate, http_scope("/internal/links", [AUTH]), [b'{"a":', b"1}"])
    assert (status, body) == (200, b"inner")
    assert inner.bodies == [b'{"a":1}']
    assert inner.after_body == [{"type": "http.disconnect"}]


async def test_streamed_body_over_the_cap_is_cut_off_without_a_content_length(gate, inner):
    status, body, received = await drive(gate, http_scope("/internal/links", [AUTH]), [b"x" * 600, b"x" * 600, b"x" * 10_000])
    assert status == 413 and json.loads(body) == {"detail": "request body too large"}
    assert inner.calls == 0
    assert received == 2


async def test_body_exactly_at_the_cap_is_accepted(gate, inner):
    status, _, _ = await drive(gate, http_scope("/internal/links", [AUTH, (b"content-length", b"1024")]), [b"x" * 1024])
    assert status == 200 and inner.bodies == [b"x" * 1024]


@pytest.mark.parametrize("declared", [b"1025", b"-1", b"+5", b"1e3", b" 10", b"0x10", b"", b"\xb2", b"\xb9\xb2"])
async def test_declared_length_over_the_cap_or_not_a_plain_number_is_refused_unread(gate, inner, declared):
    status, _, received = await drive(gate, http_scope("/internal/links", [AUTH, (b"content-length", declared)]), [b"{}"])
    assert status == 413
    assert inner.calls == 0 and received == 0


async def test_missing_token_is_refused_before_any_body_is_read(gate, inner):
    status, body, received = await drive(gate, http_scope("/internal/links", []), [b"x" * 5000])
    assert status == 401 and json.loads(body) == {"detail": "invalid service token"}
    assert inner.calls == 0 and received == 0


async def test_client_that_disconnects_mid_body_never_reaches_the_app(gate, inner):
    status, _, _ = await drive(gate, http_scope("/internal/links", [AUTH]), [b"x" * 100, b"x" * 100], disconnect_after=1)
    assert status is None
    assert inner.calls == 0


@pytest.mark.parametrize("path", ["/internal", "/internal/", "/internal/links/abc"])
async def test_every_path_under_the_prefix_is_gated(gate, inner, path):
    status, _, _ = await drive(gate, http_scope(path, []), [b""])
    assert status == 401 and inner.calls == 0


@pytest.mark.parametrize("path", ["/internalx", "/r/internal", "/healthz", "/"])
async def test_paths_outside_the_prefix_pass_through_untouched(gate, inner, path):
    status, _, _ = await drive(gate, http_scope(path, []), [b"big" * 1000])
    assert status == 200 and inner.bodies == [b"big" * 1000]


async def test_prefix_is_matched_after_the_root_path_is_stripped(gate, inner):
    status, _, _ = await drive(gate, http_scope("/api/internal/links", [], root_path="/api"), [b"{}"])
    assert status == 401 and inner.calls == 0


@pytest.mark.parametrize("middleware", [
    lambda app: InternalGate(app, token=TOKEN, max_body=1024),
    lambda app: RequestGuard(app, max_header_bytes=1024),
])
async def test_non_http_scopes_are_passed_through(inner, middleware):
    await middleware(inner)({"type": "lifespan"}, None, None)
    assert inner.calls == 1


async def test_header_budget_counts_names_and_values(inner):
    guard = RequestGuard(inner, max_header_bytes=1024)
    at_limit = [(b"x-a", b"v" * (1024 - 3))]
    status, _, _ = await drive(guard, http_scope("/r/abc", at_limit), [b""])
    assert status == 200
    status, _, _ = await drive(guard, http_scope("/r/abc", [(b"x-a", b"v" * (1024 - 2))]), [b""])
    assert status == 431


async def test_header_budget_is_the_sum_of_all_headers(inner):
    guard = RequestGuard(inner, max_header_bytes=1024)
    headers = [(b"x-a", b"v" * 500), (b"x-b", b"v" * 500), (b"x-c", b"v" * 20)]
    status, body, _ = await drive(guard, http_scope("/r/abc", headers), [b""])
    assert status == 431 and json.loads(body) == {"detail": "request headers too large"}
    assert inner.calls == 0


async def test_both_framing_headers_are_refused_before_the_app_sees_the_body(inner):
    guard = RequestGuard(inner, max_header_bytes=1024)
    headers = [(b"content-length", b"2"), (b"transfer-encoding", b"chunked")]
    status, body, received = await drive(guard, http_scope("/r/abc", headers), [b"{}"])
    assert status == 400 and json.loads(body) == {"detail": "ambiguous message framing"}
    assert inner.calls == 0 and received == 0
