"""Endpoint tests for the passkey (WebAuthn) router with a software authenticator."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import redis.asyncio as aioredis
from tests.auth.conftest import PASSWORD
from sqlalchemy import select
from starlette.requests import Request
from webauthn.helpers import base64url_to_bytes
from tests.auth.webauthn_sim import SoftAuthenticator

from waggi_auth.config import settings
from waggi_auth.models import UserPasskey
from waggi_auth.routers.passkeys import _resolve_rp
from waggi_auth.stores import challenges

ORIGIN = "http://localhost:5173"
RP_ID = "localhost"


def _headers(origin: str = ORIGIN) -> dict[str, str]:
    return {"Origin": origin}


async def _register_passkey(client, auth_headers, *, nickname="My key", sim=None, password=PASSWORD, **device):
    sim = sim or SoftAuthenticator()
    r = await client.post(
        "/api/v1/auth/passkeys/register/begin",
        headers={**auth_headers, **_headers()},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    challenge = base64url_to_bytes(body["options"]["challenge"])
    credential = sim.register(challenge=challenge, rp_id=RP_ID, origin=ORIGIN, **device)
    r = await client.post(
        "/api/v1/auth/passkeys/register/finish",
        headers={**auth_headers, **_headers()},
        json={
            "handle": body["handle"],
            "credential": credential,
            "password": password,
            "nickname": nickname,
        },
    )
    return r, sim


async def _login_passkey(client, sim, *, user_verification=True, corrupt_signature=False, sign_count=None):
    r = await client.post("/api/v1/auth/passkeys/login/begin", headers=_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    challenge = base64url_to_bytes(body["options"]["challenge"])
    assertion = sim.assertion(
        challenge=challenge,
        rp_id=RP_ID,
        origin=ORIGIN,
        user_verification=user_verification,
        corrupt_signature=corrupt_signature,
        sign_count=sign_count,
    )
    return await client.post(
        "/api/v1/auth/passkeys/login/finish",
        headers=_headers(),
        json={"handle": body["handle"], "credential": assertion},
    )


# --- registration ---------------------------------------------------------------


async def test_register_begin_returns_options(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/passkeys/register/begin",
        headers={**auth_headers(user), **_headers()},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["handle"]
    options = body["options"]
    assert options["rp"]["id"] == RP_ID
    assert options["rp"]["name"] == settings.webauthn_rp_name
    assert options["user"]["name"] == user.email
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["authenticatorSelection"]["residentKey"] == "preferred"
    assert options["challenge"]


async def test_register_begin_requires_auth(client) -> None:
    r = await client.post("/api/v1/auth/passkeys/register/begin", headers=_headers())
    assert r.status_code == 401


async def test_register_begin_excludes_existing_credentials(client, make_user, auth_headers, db) -> None:
    user = await make_user()
    r, _sim = await _register_passkey(client, auth_headers(user))
    assert r.status_code == 201

    r = await client.post(
        "/api/v1/auth/passkeys/register/begin",
        headers={**auth_headers(user), **_headers()},
    )
    excluded = r.json()["options"]["excludeCredentials"]
    assert len(excluded) == 1
    assert excluded[0]["id"] == r.json()["options"]["excludeCredentials"][0]["id"]


async def test_register_finish_stores_credential(client, make_user, auth_headers, db) -> None:
    user = await make_user()
    r, _sim = await _register_passkey(client, auth_headers(user), nickname="Phone")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["nickname"] == "Phone"
    assert body["id"]

    row = (await db.execute(select(UserPasskey).where(UserPasskey.user_id == user.id))).scalar_one()
    assert row.credential_id  # b64url
    assert row.public_key  # COSE bytes
    assert row.sign_count == 0
    assert row.transports == ["internal"]
    # Default sim: unidentified authenticator -> no aaguid, platform attachment.
    assert row.aaguid is None
    assert row.attachment == "platform"
    assert row.backed_up is False


async def test_register_finish_stores_device_metadata(client, make_user, auth_headers, db) -> None:
    """AAGUID + attachment + backup flag are captured and the brand name is
    resolved at read time for the account page."""
    user = await make_user()
    google = "ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4"  # Google Password Manager
    r, _sim = await _register_passkey(
        client,
        auth_headers(user),
        aaguid=google,
        attachment="cross-platform",
        backup_eligible=True,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["aaguid"] == google
    assert body["attachment"] == "cross-platform"
    assert body["backed_up"] is True

    row = (await db.execute(select(UserPasskey).where(UserPasskey.user_id == user.id))).scalar_one()
    assert row.aaguid == google
    assert row.attachment == "cross-platform"
    assert row.backed_up is True

    # The list endpoint serves the raw facts (brand naming is frontend-side).
    items = (await client.get("/api/v1/auth/passkeys", headers=auth_headers(user))).json()
    assert items[0]["aaguid"] == google
    assert items[0]["backed_up"] is True
    assert "device_name" not in items[0]


async def test_register_finish_unknown_aaguid_stored_as_is(client, make_user, auth_headers) -> None:
    """An AAGUID missing from the (frontend) name registry is still stored —
    the backend serves raw facts and never filters by recognizability."""
    user = await make_user()
    unknown = "12345678-1234-1234-1234-123456789abc"
    r, _sim = await _register_passkey(client, auth_headers(user), aaguid=unknown)
    assert r.status_code == 201, r.text
    assert r.json()["aaguid"] == unknown


async def test_register_finish_invalid_attachment_rejected(client, make_user, auth_headers, db) -> None:
    """A garbage attachment string is rejected by py_webauthn's strict JSON
    parsing (422) — it never reaches our normalizer, which only guards
    non-string values as defense in depth."""
    user = await make_user()
    r, _sim = await _register_passkey(client, auth_headers(user), attachment="carrier-pigeon")
    assert r.status_code == 422
    rows = (await db.execute(select(UserPasskey).where(UserPasskey.user_id == user.id))).scalars().all()
    assert rows == []  # nothing stored


def test_normalize_aaguid_variants() -> None:
    from waggi_auth.routers.passkeys import _normalize_aaguid

    zero = "00000000-0000-0000-0000-000000000000"
    assert _normalize_aaguid(None) is None
    assert _normalize_aaguid("") is None
    assert _normalize_aaguid(zero) is None  # unidentified authenticator
    assert _normalize_aaguid("EA9B8D66-4D01-1D21-3CE4-B6B48CB575D4") == ("ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4")


async def test_register_finish_unknown_handle(client, make_user, auth_headers) -> None:
    user = await make_user()
    sim = SoftAuthenticator()
    r = await client.post(
        "/api/v1/auth/passkeys/register/finish",
        headers=auth_headers(user),
        json={
            "handle": "nope",
            "credential": sim.register(challenge=b"x" * 32, rp_id=RP_ID, origin=ORIGIN),
            "password": PASSWORD,
        },
    )
    assert r.status_code == 401


async def test_register_finish_wrong_challenge(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/passkeys/register/begin",
        headers={**auth_headers(user), **_headers()},
    )
    handle = r.json()["handle"]
    sim = SoftAuthenticator()
    # credential bound to a DIFFERENT challenge than the one stored
    credential = sim.register(challenge=b"attacker-challenge" + b"0" * 16, rp_id=RP_ID, origin=ORIGIN)
    r = await client.post(
        "/api/v1/auth/passkeys/register/finish",
        headers={**auth_headers(user), **_headers()},
        json={"handle": handle, "credential": credential, "password": PASSWORD},
    )
    assert r.status_code == 422


async def test_register_finish_rejects_wrong_password_and_keeps_challenge(client, make_user, auth_headers) -> None:
    """Step-up ordering: the password is checked BEFORE the single-use challenge
    is consumed — a typo must not burn the ceremony, and a stolen token must
    not be able to register a passkey at all."""
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/passkeys/register/begin",
        headers={**auth_headers(user), **_headers()},
    )
    body = r.json()
    challenge = base64url_to_bytes(body["options"]["challenge"])
    sim = SoftAuthenticator()
    credential = sim.register(challenge=challenge, rp_id=RP_ID, origin=ORIGIN)

    r = await client.post(
        "/api/v1/auth/passkeys/register/finish",
        headers={**auth_headers(user), **_headers()},
        json={"handle": body["handle"], "credential": credential, "password": "WrongPassword123!"},
    )
    assert r.status_code == 422

    # Same handle + ceremony credential still works once the password is right.
    r = await client.post(
        "/api/v1/auth/passkeys/register/finish",
        headers={**auth_headers(user), **_headers()},
        json={"handle": body["handle"], "credential": credential, "password": PASSWORD},
    )
    assert r.status_code == 201, r.text


async def test_register_finish_requires_user_verification(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.post(
        "/api/v1/auth/passkeys/register/begin",
        headers={**auth_headers(user), **_headers()},
    )
    body = r.json()
    challenge = base64url_to_bytes(body["options"]["challenge"])
    sim = SoftAuthenticator()
    credential = sim.register(challenge=challenge, rp_id=RP_ID, origin=ORIGIN, user_verification=False)
    r = await client.post(
        "/api/v1/auth/passkeys/register/finish",
        headers={**auth_headers(user), **_headers()},
        json={"handle": body["handle"], "credential": credential, "password": PASSWORD},
    )
    assert r.status_code == 422


async def test_register_finish_duplicate_credential_conflict(client, make_user, auth_headers) -> None:
    user = await make_user()
    sim = SoftAuthenticator()
    r1, _ = await _register_passkey(client, auth_headers(user), sim=sim)
    assert r1.status_code == 201
    # Same authenticator registers again (new ceremony, same credential id).
    r2, _ = await _register_passkey(client, auth_headers(user), sim=sim)
    assert r2.status_code == 409


# --- login -------------------------------------------------------------------------


async def test_login_begin_is_public(client) -> None:
    r = await client.post("/api/v1/auth/passkeys/login/begin", headers=_headers())
    assert r.status_code == 200
    options = r.json()["options"]
    assert options["rpId"] == RP_ID
    assert options["userVerification"] == "required"
    assert not options.get("allowCredentials")  # usernameless: discoverable creds


async def test_login_finish_issues_tokens(client, make_user, auth_headers, db) -> None:
    user = await make_user()
    _, sim = await _register_passkey(client, auth_headers(user))
    r = await _login_passkey(client, sim)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] and body["refresh_token"]

    row = (await db.execute(select(UserPasskey).where(UserPasskey.user_id == user.id))).scalar_one()
    assert row.sign_count == 1
    assert row.last_used_at is not None


async def test_login_finish_unknown_handle(client) -> None:
    sim = SoftAuthenticator()  # noqa: F841 — used for realism of the payload below
    r = await client.post(
        "/api/v1/auth/passkeys/login/finish",
        headers=_headers(),
        json={"handle": "nope", "credential": {"id": "x"}},
    )
    assert r.status_code == 401


async def test_login_finish_unknown_credential(client) -> None:
    r = await client.post("/api/v1/auth/passkeys/login/begin", headers=_headers())
    handle = r.json()["handle"]
    r = await client.post(
        "/api/v1/auth/passkeys/login/finish",
        headers=_headers(),
        json={"handle": handle, "credential": {"id": "unknown-credential", "response": {}}},
    )
    assert r.status_code == 401


async def test_login_finish_malformed_credential(client) -> None:
    r = await client.post("/api/v1/auth/passkeys/login/begin", headers=_headers())
    handle = r.json()["handle"]
    r = await client.post(
        "/api/v1/auth/passkeys/login/finish",
        headers=_headers(),
        json={"handle": handle, "credential": {"id": ""}},
    )
    assert r.status_code == 422


async def test_login_finish_structurally_invalid_payload_401(client, make_user, auth_headers) -> None:
    """A credential dict that survives the id check but fails py_webauthn's
    strict JSON parsing (e.g. response not a dict) is a 401, never a 500."""
    user = await make_user()
    _, sim = await _register_passkey(client, auth_headers(user))
    r = await client.post("/api/v1/auth/passkeys/login/begin", headers=_headers())
    handle = r.json()["handle"]
    r = await client.post(
        "/api/v1/auth/passkeys/login/finish",
        headers=_headers(),
        json={
            "handle": handle,
            "credential": {"id": sim.credential_id.hex()[:10], "response": "not-a-dict"},
        },
    )
    assert r.status_code == 401


async def test_login_finish_inactive_user(client, make_user, auth_headers, db) -> None:
    user = await make_user()
    _, sim = await _register_passkey(client, auth_headers(user))
    user.is_active = False
    await db.commit()
    r = await _login_passkey(client, sim)
    assert r.status_code == 401


async def test_login_finish_bad_signature(client, make_user, auth_headers) -> None:
    user = await make_user()
    _, sim = await _register_passkey(client, auth_headers(user))
    r = await _login_passkey(client, sim, corrupt_signature=True)
    assert r.status_code == 401


async def test_login_finish_stale_sign_count_rejected(client, make_user, auth_headers) -> None:
    """Replayed assertion (sign count not increasing) must be rejected."""
    user = await make_user()
    _, sim = await _register_passkey(client, auth_headers(user))
    r = await _login_passkey(client, sim)
    assert r.status_code == 200  # count now 1

    r = await _login_passkey(client, sim, sign_count=1)  # not increasing
    assert r.status_code == 401


async def test_login_finish_requires_user_verification(client, make_user, auth_headers) -> None:
    user = await make_user()
    _, sim = await _register_passkey(client, auth_headers(user))
    r = await _login_passkey(client, sim, user_verification=False)
    assert r.status_code == 401


async def test_login_finish_totp_fallback_when_uv_absent(client, make_user, auth_headers, monkeypatch) -> None:
    """Defense in depth: without UV, a TOTP-enabled user gets an MFA challenge."""
    user = await make_user(totp=True)
    _, sim = await _register_passkey(client, auth_headers(user))

    from waggi_auth.routers import passkeys as passkeys_router

    def fake_verify(**kwargs):  # sync, like the real webauthn verifier
        return SimpleNamespace(new_sign_count=7, user_verified=False)

    monkeypatch.setattr(passkeys_router, "verify_authentication_response", fake_verify)
    r = await _login_passkey(client, sim)
    assert r.status_code == 200
    assert r.json().get("mfa_required") is True


# --- rp resolution -----------------------------------------------------------------


def _request_with_origin(origin: str | None) -> Request:
    headers = [("origin", origin)] if origin else []
    return Request({"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers]})


def test_resolve_rp_no_origin_uses_default() -> None:
    rp_id, origins = _resolve_rp(_request_with_origin(None))
    assert rp_id == settings.webauthn_rp_id
    assert origins == settings.webauthn_origins_list


def test_resolve_rp_default_host() -> None:
    rp_id, origins = _resolve_rp(_request_with_origin("http://localhost:5173"))
    assert rp_id == "localhost"
    assert origins == settings.webauthn_origins_list


def test_resolve_rp_unknown_host_falls_back_to_default() -> None:
    rp_id, _ = _resolve_rp(_request_with_origin("http://evil.example"))
    assert rp_id == settings.webauthn_rp_id


def test_resolve_rp_extra_host(monkeypatch) -> None:
    monkeypatch.setattr(settings, "webauthn_extra_rp_hosts", "abc.ngrok-free.dev")
    rp_id, origins = _resolve_rp(_request_with_origin("https://abc.ngrok-free.dev"))
    assert rp_id == "abc.ngrok-free.dev"
    assert origins == ["https://abc.ngrok-free.dev"]


def test_resolve_rp_for_rp_id_variants() -> None:
    from waggi_auth.routers.passkeys import _resolve_rp_for_rp_id

    # Default host maps to the full configured origins list.
    rp_id, origins = _resolve_rp_for_rp_id(settings.webauthn_rp_id)
    assert rp_id == settings.webauthn_rp_id
    assert origins == settings.webauthn_origins_list
    # Any other (extra) host maps to its https origin only.
    rp_id, origins = _resolve_rp_for_rp_id("abc.ngrok-free.dev")
    assert rp_id == "abc.ngrok-free.dev"
    assert origins == ["https://abc.ngrok-free.dev"]


def test_parse_transports_defensive_branches() -> None:
    from waggi_auth.routers.passkeys import _parse_transports

    assert _parse_transports({}) == []
    assert _parse_transports({"response": {}}) == []
    assert _parse_transports({"response": {"transports": "internal"}}) == []  # not a list
    assert _parse_transports({"response": {"transports": ["usb", 7, None]}}) == ["usb"]
    assert _parse_transports({"response": {"transports": ["usb", "internal"]}}) == ["usb", "internal"]


# --- Redis outage --------------------------------------------------------------------


async def test_begin_fails_503_when_challenge_store_down(client, make_user, auth_headers, monkeypatch) -> None:
    user = await make_user()

    class Boom:
        async def set(self, *a, **k):
            raise aioredis.RedisError("down")

    monkeypatch.setattr(challenges, "redis_client", lambda url: Boom())
    r = await client.post("/api/v1/auth/passkeys/register/begin", headers={**auth_headers(user), **_headers()})
    assert r.status_code == 503


async def test_finish_fails_503_when_challenge_pop_down(client, make_user, auth_headers, monkeypatch) -> None:
    """Challenge-store outage at the FINISH step (pop path) -> 503."""
    user = await make_user()

    class Boom:
        async def getdel(self, *a, **k):
            raise aioredis.RedisError("down")

    monkeypatch.setattr(challenges, "redis_client", lambda url: Boom())
    sim = SoftAuthenticator()
    r = await client.post(
        "/api/v1/auth/passkeys/register/finish",
        headers={**auth_headers(user), **_headers()},
        json={
            "handle": "any",
            "credential": sim.register(challenge=b"x" * 32, rp_id=RP_ID, origin=ORIGIN),
            "password": PASSWORD,
        },
    )
    assert r.status_code == 503


# --- management -----------------------------------------------------------------------


async def _seed_two_passkeys(client, make_user, auth_headers):
    user = await make_user()
    r1, _sim1 = await _register_passkey(client, auth_headers(user), nickname="Phone")
    r2, _sim2 = await _register_passkey(client, auth_headers(user), nickname="YubiKey")
    assert r1.status_code == 201 and r2.status_code == 201
    return user


async def test_list_passkeys(client, make_user, auth_headers) -> None:
    user = await _seed_two_passkeys(client, make_user, auth_headers)
    r = await client.get("/api/v1/auth/passkeys", headers=auth_headers(user))
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    assert {i["nickname"] for i in items} == {"Phone", "YubiKey"}


async def test_rename_passkey(client, make_user, auth_headers) -> None:
    user = await _seed_two_passkeys(client, make_user, auth_headers)
    items = (await client.get("/api/v1/auth/passkeys", headers=auth_headers(user))).json()
    target = next(i for i in items if i["nickname"] == "Phone")
    r = await client.patch(
        f"/api/v1/auth/passkeys/{target['id']}",
        headers=auth_headers(user),
        json={"nickname": "iPhone"},
    )
    assert r.status_code == 200
    assert r.json()["nickname"] == "iPhone"


async def test_rename_foreign_passkey_404(client, make_user, auth_headers) -> None:
    owner = await _seed_two_passkeys(client, make_user, auth_headers)
    other = await make_user(email="other@example.com")

    items = (await client.get("/api/v1/auth/passkeys", headers=auth_headers(owner))).json()
    r = await client.patch(
        f"/api/v1/auth/passkeys/{items[0]['id']}",
        headers=auth_headers(other),
        json={"nickname": "steal"},
    )
    assert r.status_code == 404  # not 403: no existence leak


async def test_delete_passkey(client, make_user, auth_headers) -> None:
    user = await _seed_two_passkeys(client, make_user, auth_headers)
    items = (await client.get("/api/v1/auth/passkeys", headers=auth_headers(user))).json()
    r = await client.delete(f"/api/v1/auth/passkeys/{items[0]['id']}", headers=auth_headers(user))
    assert r.status_code == 200
    items = (await client.get("/api/v1/auth/passkeys", headers=auth_headers(user))).json()
    assert len(items) == 1
    # deleting again -> 404
    r = await client.delete(f"/api/v1/auth/passkeys/{items[0]['id']}", headers=auth_headers(user))
    assert r.status_code in (200, 404)


async def test_delete_foreign_passkey_404(client, make_user, auth_headers) -> None:
    owner = await _seed_two_passkeys(client, make_user, auth_headers)
    other = await make_user(email="other@example.com")
    items = (await client.get("/api/v1/auth/passkeys", headers=auth_headers(owner))).json()
    r = await client.delete(f"/api/v1/auth/passkeys/{items[0]['id']}", headers=auth_headers(other))
    assert r.status_code == 404


async def test_rename_unknown_passkey_404(client, make_user, auth_headers) -> None:
    user = await make_user()
    r = await client.patch(
        f"/api/v1/auth/passkeys/{uuid.uuid4()}",
        headers=auth_headers(user),
        json={"nickname": "x"},
    )
    assert r.status_code == 404
