import httpx

from app.indexer.api import create_app
from app.indexer.projections import apply_event

C = "GAXMVFUXzAPBwhW4cF127HiSZmiY791XX2mBFEqqBwx"
K = "SysvarC1ock11111111111111111111111111111111"


async def seed(db):
    async with db.session() as s:
        await apply_event(s, "CampaignCreated", {"campaign": C, "brand": K, "campaign_id": 1, "vault": K, "start_ts": 1, "end_ts": 2}, {"signature": "s1", "slot": 1}, 0)
        await apply_event(s, "Settled", {"campaign": C, "creator": K, "epoch": 1, "units": [1, 0, 0, 0], "amount": 7, "unlock_ts": 3, "evidence_hash": "00" * 32}, {"signature": "s2", "slot": 2}, 0)
        await apply_event(s, "Staked", {"creator": K, "amount": 500}, {"signature": "s3", "slot": 3}, 0)
        await apply_event(s, "Tipped", {"x": 1}, {"signature": "s4", "slot": 4}, 0)
        await s.commit()


async def test_read_api(db):
    await seed(db)
    app = create_app(db)
    app.state.db = db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
        print("GET /health ->", r.json())
        assert r.status_code == 200 and r.json()["ok"] and r.json()["events"] == 4
        r = await c.get("/events", params={"limit": 2})
        print("GET /events?limit=2 ->", [e["event_name"] for e in r.json()])
        assert [e["event_name"] for e in r.json()] == ["Tipped", "Staked"]
        r = await c.get("/events", params={"name": "Settled"})
        print("GET /events?name=Settled ->", r.json())
        assert len(r.json()) == 1 and r.json()[0]["data"]["amount"] == 7
        r = await c.get("/campaigns")
        print("GET /campaigns ->", [x["campaign"] for x in r.json()])
        assert r.json()[0]["campaign"] == C
        r = await c.get(f"/campaigns/{C}")
        print(f"GET /campaigns/{C[:8]} -> payouts={len(r.json()['payouts'])}")
        assert r.json()["payouts"][0]["amount"] == 7
        r = await c.get("/campaigns/nope")
        assert r.status_code == 404
        r = await c.get("/payouts", params={"campaign": C, "creator": K})
        print("GET /payouts?campaign&creator ->", r.json())
        assert len(r.json()) == 1 and r.json()[0]["status"] == "Pending"
        r = await c.get("/payouts", params={"creator": "other"})
        assert r.json() == []
        r = await c.get(f"/stakes/{K}")
        print(f"GET /stakes/{K[:8]} ->", r.json())
        assert r.json()["staked"] == 500
        r = await c.get("/stakes/nobody")
        assert r.status_code == 404
