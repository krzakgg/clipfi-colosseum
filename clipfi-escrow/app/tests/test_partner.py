import httpx
import pytest

from app.partner.api import create_app
from app.partner.service import PartnerError, PartnerService, split_fee, to_units

BRAND = "11111111111111111111111111111112"
CREATOR = "SysvarC1ock11111111111111111111111111111111"
BAD = "SysvarRent111111111111111111111111111111111"


def test_fee_math():
    fee, clip = split_fee(to_units(100), 1500)
    print(f"100 USD -> fee={fee / 1e6} clipUSD={clip / 1e6}")
    assert (fee, clip) == (15_000_000, 85_000_000)
    fee, clip = split_fee(to_units("0.01"), 1500)
    print(f"0.01 USD -> fee={fee} clip={clip} (integer floor, 6 decimals)")
    assert (fee, clip) == (1_500, 8_500)
    fee, clip = split_fee(to_units(1), 0)
    print(f"margin 0 bps -> fee={fee} clip={clip}")
    assert (fee, clip) == (0, 1_000_000)
    assert sum(split_fee(123_456_789, 1500)) == 123_456_789


async def test_kyc_gating_and_denylist(db):
    svc = PartnerService(db, denylist=[BAD], margin_bps=1500)
    with pytest.raises(PartnerError) as e:
        await svc.onramp(BRAND, 100)
    print(f"onramp without KYC -> {e.value.code} {e.value}")
    assert e.value.code == 403
    await svc.set_kyc(BRAND, "pending", "prov-1")
    with pytest.raises(PartnerError):
        await svc.onramp(BRAND, 100)
    print("onramp with KYC pending -> rejected")
    k = await svc.set_kyc(BRAND, "approved", "prov-1")
    print(f"kyc set -> {k}")
    row = await svc.onramp(BRAND, 100)
    print(f"onramp after approval -> status={row['status']} fee={row['fee']} clip={row['clipusd_amount']}")
    assert row["status"] == "minted" and row["fee"] == 15_000_000 and row["clipusd_amount"] == 85_000_000
    k = await svc.set_kyc(BAD, "approved", "prov-2")
    print(f"denylisted wallet approved by provider -> stored as {k['status']} ({k['reason']})")
    assert k["status"] == "rejected" and k["reason"] == "sanctions_hit"
    with pytest.raises(PartnerError) as e:
        await svc.offramp(BAD, 10, "sepa")
    assert e.value.code == 403
    print("offramp for denylisted wallet -> 403")
    with pytest.raises(PartnerError) as e:
        await svc.set_kyc(BRAND, "weird")
    assert e.value.code == 422


async def test_offramp_at_par_and_ledger(db):
    svc = PartnerService(db, denylist=[], margin_bps=1500)
    await svc.set_kyc(CREATOR, "approved", "p")
    await svc.set_kyc(BRAND, "approved", "p")
    await svc.onramp(BRAND, 200)
    row = await svc.offramp(CREATOR, 42.5, "card")
    print(f"offramp 42.5 clipUSD -> usd={row['usd_amount']} fee={row['fee']} status={row['status']} method={row['payout_method']}")
    assert row["usd_amount"] == row["clipusd_amount"] == 42_500_000 and row["fee"] == 0
    assert row["status"] == "awaiting_transfer" and row["tx_signature"] is None
    led = await svc.ledger(CREATOR)
    print(f"ledger({CREATOR[:8]}) -> {[(r['kind'], r['clipusd_amount']) for r in led]}")
    assert len(led) == 1 and led[0]["kind"] == "offramp"
    led = await svc.ledger()
    print(f"ledger(all) -> {[(r['kind'], r['wallet'][:6], r['clipusd_amount']) for r in led]}")
    assert [r["kind"] for r in led] == ["offramp", "onramp"]
    with pytest.raises(PartnerError):
        await svc.offramp(CREATOR, 0, "card")


async def test_partner_http_api(db):
    svc = PartnerService(db, denylist=[BAD], margin_bps=1500)
    app = create_app(db, svc, token="secret-token")
    app.state.db, app.state.svc = db, svc
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers={"X-Partner-Token": "secret-token"}) as c:
        r = await c.get("/health")
        print("GET /health ->", r.json())
        assert r.json() == {"ok": True, "issuer": False}
        r = await c.get(f"/kyc/{BRAND}")
        assert r.status_code == 404
        r = await c.post("/onramp", json={"brand_wallet": BRAND, "usd_amount": 100})
        print("POST /onramp without kyc ->", r.status_code, r.json())
        assert r.status_code == 403
        r = await c.post(f"/kyc/{BRAND}", json={"status": "approved", "provider_ref": "x"})
        print("POST /kyc ->", r.json())
        assert r.json()["status"] == "approved"
        r = await c.get(f"/kyc/{BAD}")
        print("GET /kyc denylisted (no record) ->", r.json())
        assert r.json()["status"] == "rejected"
        r = await c.post("/onramp", json={"brand_wallet": BRAND, "usd_amount": 100})
        print("POST /onramp ->", r.json())
        assert r.json()["clipusd_amount"] == 85_000_000
        r = await c.post("/offramp", json={"creator_wallet": BRAND, "clipusd_amount": 10, "payout_method": "sepa"})
        print("POST /offramp ->", r.json())
        assert r.json()["fee"] == 0 and r.json()["status"] == "awaiting_transfer"
        r = await c.get("/ledger", params={"wallet": BRAND})
        print("GET /ledger ->", [(x["kind"], x["clipusd_amount"]) for x in r.json()])
        assert len(r.json()) == 2


async def test_api_requires_the_partner_token(db):
    svc = PartnerService(db, denylist=[], margin_bps=1500)
    app = create_app(db, svc, token="secret-token")
    app.state.db, app.state.svc = db, svc
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
        print(f"GET /health without token -> {r.status_code}")
        assert r.status_code == 200
        for path, send in (
            ("POST /kyc", lambda h: c.post(f"/kyc/{BRAND}", json={"status": "approved"}, headers=h)),
            ("GET /kyc", lambda h: c.get(f"/kyc/{BRAND}", headers=h)),
            ("POST /onramp", lambda h: c.post("/onramp", json={"brand_wallet": BRAND, "usd_amount": 100}, headers=h)),
            ("POST /offramp", lambda h: c.post("/offramp", json={"creator_wallet": BRAND, "clipusd_amount": 1, "payout_method": "card"}, headers=h)),
            ("GET /ledger", lambda h: c.get("/ledger", headers=h)),
        ):
            missing = await send({})
            wrong = await send({"X-Partner-Token": "nope"})
            print(f"{path}: no token -> {missing.status_code}, wrong token -> {wrong.status_code}")
            assert (missing.status_code, wrong.status_code) == (401, 401)
        r = await c.post(f"/kyc/{BRAND}", json={"status": "approved"}, headers={"X-Partner-Token": "secret-token"})
        print(f"POST /kyc with the token -> {r.status_code} {r.json()['status']}")
        assert r.status_code == 200


async def test_api_fails_closed_without_a_configured_token(db):
    svc = PartnerService(db, denylist=[], margin_bps=1500)
    app = create_app(db, svc, token="")
    app.state.db, app.state.svc = db, svc
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/kyc/{BRAND}", json={"status": "approved"}, headers={"X-Partner-Token": ""})
        print(f"no token configured, empty header -> {r.status_code}")
        assert r.status_code == 401
