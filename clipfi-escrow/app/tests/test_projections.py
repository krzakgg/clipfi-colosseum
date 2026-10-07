from sqlalchemy import func, select

from app.indexer.models import Campaign, Payout, ProgramEvent, Stake
from app.indexer.poller import Poller
from app.indexer.projections import apply_event, apply_transaction

C = "GAXMVFUXzAPBwhW4cF127HiSZmiY791XX2mBFEqqBwx"
B = "11111111111111111111111111111112"
K = "SysvarC1ock11111111111111111111111111111111"
H = "ab" * 32


async def test_campaign_and_payout_lifecycle(db, decoder):
    events = [
        ("sig1", 10, [("CampaignCreated", {"campaign": C, "brand": B, "campaign_id": 1, "vault": K, "start_ts": 1, "end_ts": 2})]),
        ("sig2", 11, [("CampaignFunded", {"campaign": C, "amount": 85_000_000, "funded_total": 85_000_000})]),
        ("sig3", 12, [("Settled", {"campaign": C, "creator": K, "epoch": 1, "units": [1, 2, 3, 4], "amount": 5_000_000, "unlock_ts": 99, "evidence_hash": H})]),
        ("sig4", 13, [("PayoutFlagged", {"campaign": C, "creator": K, "epoch": 1, "reason": 3})]),
        ("sig5", 14, [("PayoutResolved", {"campaign": C, "creator": K, "epoch": 1, "approved": True, "amount": 4_000_000})]),
        ("sig6", 15, [("PayoutReleased", {"campaign": C, "creator": K, "epoch": 1, "amount": 4_000_000})]),
        ("sig7", 16, [("CampaignClosed", {"campaign": C, "refunded": 81_000_000, "paid_total": 4_000_000})]),
    ]
    for sig, slot, evs in events:
        logs = [decoder.build_log_line(n, d) for n, d in evs]
        async with db.session() as s:
            n = await apply_transaction(s, decoder, sig, slot, 1700000000 + slot, logs)
            await s.commit()
        assert n == len(evs)
    async with db.session() as s:
        c = await s.get(Campaign, C)
        p = (await s.execute(select(Payout))).scalar_one()
        total = (await s.execute(select(func.count(ProgramEvent.id)))).scalar_one()
    print(f"campaign: status={c.status} funded={c.funded_total} paid={c.paid_total} refunded={c.refunded}")
    print(f"payout: status={p.status} amount={p.amount} released={p.released_amount} reason={p.flag_reason} release_sig={p.release_signature}")
    print(f"program_events rows: {total}")
    assert (c.status, c.funded_total, c.paid_total, c.refunded, c.brand) == ("Closed", 85_000_000, 4_000_000, 81_000_000, B)
    assert (p.status, p.amount, p.released_amount, p.flag_reason, p.approved, p.release_signature) == ("Released", 4_000_000, 4_000_000, 3, True, "sig6")
    assert total == 7


async def test_unknown_event_lands_in_program_events_and_dedupes(db):
    meta = {"signature": "sigX", "slot": 5, "block_time": None}
    async with db.session() as s:
        assert await apply_event(s, "Tipped", {"from": B, "to": K, "amount": 1}, meta, 0) is True
        assert await apply_event(s, "Tipped", {"from": B, "to": K, "amount": 1}, meta, 0) is False
        await s.commit()
        rows = (await s.execute(select(ProgramEvent))).scalars().all()
    print(f"unknown event stored: {rows[0].event_name} {rows[0].data}; duplicate skipped; rows={len(rows)}")
    assert len(rows) == 1 and rows[0].event_name == "Tipped"


async def test_stake_projection(db):
    seq = [
        ("Staked", {"creator": K, "amount": 100}),
        ("Staked", {"creator": K, "amount": 50}),
        ("Slashed", {"creator": K, "amount": 30}),
        ("UnstakeRequested", {"creator": K, "amount": 20, "unlock_ts": 777}),
        ("StakeWithdrawn", {"creator": K, "amount": 20}),
        ("BonusPaid", {"creator": K, "campaign": C, "epoch": 1, "amount": 9}),
        ("RolledOver", {"from_campaign": C, "to_campaign": B, "amount": 10}),
    ]
    async with db.session() as s:
        for i, (n, d) in enumerate(seq):
            await apply_event(s, n, d, {"signature": f"s{i}", "slot": i}, 0)
        await s.commit()
        st = await s.get(Stake, K)
        src, dst = await s.get(Campaign, C), await s.get(Campaign, B)
    print(f"stake: staked={st.staked} pending={st.pending_unstake} withdrawn={st.withdrawn_total} slashed={st.slashed_total} bonus={st.bonus_total} unlock={st.unlock_ts} last={st.last_event}@{st.last_signature}")
    print(f"rollover: {C[:6]} rolled_over={src.rolled_over} -> {B[:6]} funded={dst.funded_total}")
    assert (st.staked, st.pending_unstake, st.withdrawn_total, st.slashed_total, st.bonus_total, st.unlock_ts) == (100, 0, 20, 30, 9, 777)
    assert (st.last_event, st.last_signature) == ("BonusPaid", "s5")
    assert src.rolled_over == 10 and dst.funded_total == 10


class FakeRpc:
    def __init__(self, decoder):
        self.chain = [
            ("sigA", 1, [decoder.build_log_line("CampaignCreated", {"campaign": C, "brand": B, "campaign_id": 1, "vault": K, "start_ts": 1, "end_ts": 2})], None),
            ("sigB", 2, [decoder.build_log_line("CampaignFunded", {"campaign": C, "amount": 5, "funded_total": 5})], None),
            ("sigC", 3, ["Program log: failed"], {"InstructionError": [0, "Custom"]}),
        ]
        self.calls = []

    async def signatures(self, address, before=None, until=None, limit=1000):
        self.calls.append(("sigs", before, until))
        out = []
        for sig, slot, _, err in reversed(self.chain):
            if sig == until:
                break
            out.append({"signature": sig, "slot": slot, "err": err})
        return out

    async def transaction(self, signature):
        self.calls.append(("tx", signature))
        sig, slot, logs, err = next(x for x in self.chain if x[0] == signature)
        return {"slot": slot, "blockTime": 1700000000 + slot, "meta": {"logMessages": logs, "err": err}}

    async def close(self):
        pass


async def test_poller_walks_newest_to_oldest_and_resumes(db, decoder):
    rpc = FakeRpc(decoder)
    poller = Poller(db, decoder, rpc=rpc, program_id="prog")
    n = await poller.poll_once()
    print(f"first poll indexed {n} events, rpc calls: {rpc.calls}")
    assert n == 2
    assert [c for c in rpc.calls if c[0] == "tx"] == [("tx", "sigA"), ("tx", "sigB")]
    assert await poller.last_signature() == "sigC"
    rpc.calls.clear()
    n = await poller.poll_once()
    print(f"second poll indexed {n} events, rpc calls: {rpc.calls}")
    assert n == 0 and rpc.calls == [("sigs", None, "sigC")]
    rpc.chain.append(("sigD", 4, [decoder.build_log_line("CampaignFunded", {"campaign": C, "amount": 1, "funded_total": 6})], None))
    n = await poller.poll_once()
    async with db.session() as s:
        c = await s.get(Campaign, C)
    print(f"third poll indexed {n} events, funded_total={c.funded_total}, cursor={await poller.last_signature()}")
    assert n == 1 and c.funded_total == 6 and await poller.last_signature() == "sigD"
