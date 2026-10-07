from sqlalchemy import select

from app.indexer.models import Campaign, Payout, ProgramEvent, Stake

HANDLERS = {}


def on(*names):
    def deco(fn):
        for n in names:
            HANDLERS[n] = fn
        return fn
    return deco


async def _campaign(session, key, meta):
    c = await session.get(Campaign, key)
    if c is None:
        c = Campaign(campaign=key)
        session.add(c)
    c.last_slot = max(c.last_slot or 0, meta.get("slot", 0))
    return c


async def _payout(session, data):
    q = select(Payout).where(
        Payout.campaign == data["campaign"], Payout.creator == data["creator"], Payout.epoch == data["epoch"]
    )
    p = (await session.execute(q)).scalar_one_or_none()
    if p is None:
        p = Payout(campaign=data["campaign"], creator=data["creator"], epoch=data["epoch"])
        session.add(p)
    return p


async def _stake(session, creator):
    s = await session.get(Stake, creator)
    if s is None:
        s = Stake(creator=creator)
        session.add(s)
    return s


@on("CampaignCreated")
async def campaign_created(session, data, meta):
    c = await _campaign(session, data["campaign"], meta)
    c.brand = data.get("brand")
    c.campaign_id = data.get("campaign_id")
    c.vault = data.get("vault")
    c.start_ts = data.get("start_ts")
    c.end_ts = data.get("end_ts")
    c.status = "Active"


@on("CampaignFunded")
async def campaign_funded(session, data, meta):
    c = await _campaign(session, data["campaign"], meta)
    c.funded_total = data.get("funded_total", (c.funded_total or 0) + data.get("amount", 0))


@on("CampaignClosed")
async def campaign_closed(session, data, meta):
    c = await _campaign(session, data["campaign"], meta)
    c.refunded = data.get("refunded", 0)
    c.paid_total = data.get("paid_total", c.paid_total)
    c.status = "Closed"


@on("RolledOver")
async def rolled_over(session, data, meta):
    src = data.get("from_campaign") or data.get("campaign")
    amount = data.get("amount", 0)
    if src:
        c = await _campaign(session, src, meta)
        c.rolled_over = (c.rolled_over or 0) + amount
    dst = data.get("to_campaign")
    if dst:
        d = await _campaign(session, dst, meta)
        d.funded_total = data.get("funded_total", (d.funded_total or 0) + amount)


@on("Settled")
async def settled(session, data, meta):
    p = await _payout(session, data)
    p.units = data.get("units")
    p.amount = data.get("amount", 0)
    p.unlock_ts = data.get("unlock_ts")
    p.evidence_hash = data.get("evidence_hash")
    p.status = "Pending"


@on("PayoutFlagged")
async def payout_flagged(session, data, meta):
    p = await _payout(session, data)
    p.status = "Flagged"
    p.flag_reason = data.get("reason")


@on("PayoutResolved")
async def payout_resolved(session, data, meta):
    p = await _payout(session, data)
    p.approved = data.get("approved")
    p.amount = data.get("amount", p.amount)
    p.status = "Approved" if p.approved else "Rejected"


@on("PayoutReleased")
async def payout_released(session, data, meta):
    p = await _payout(session, data)
    p.released_amount = data.get("amount", 0)
    p.release_signature = meta.get("signature")
    p.status = "Released"
    c = await _campaign(session, data["campaign"], meta)
    c.paid_total = (c.paid_total or 0) + p.released_amount


@on("BonusPaid")
async def bonus_paid(session, data, meta):
    amount = data.get("amount", 0)
    if "campaign" in data and "epoch" in data:
        p = await _payout(session, data)
        p.bonus_amount = amount
    s = await _stake(session, data["creator"])
    s.bonus_total = (s.bonus_total or 0) + amount
    s.last_event, s.last_signature = "BonusPaid", meta.get("signature")


@on("Staked")
async def staked(session, data, meta):
    s = await _stake(session, data["creator"])
    s.staked = data.get("total", (s.staked or 0) + data.get("amount", 0))
    s.last_event, s.last_signature = "Staked", meta.get("signature")


@on("UnstakeRequested")
async def unstake_requested(session, data, meta):
    s = await _stake(session, data["creator"])
    amount = data.get("amount", 0)
    s.staked = max((s.staked or 0) - amount, 0)
    s.pending_unstake = (s.pending_unstake or 0) + amount
    s.unlock_ts = data.get("unlock_ts")
    s.last_event, s.last_signature = "UnstakeRequested", meta.get("signature")


@on("StakeWithdrawn")
async def stake_withdrawn(session, data, meta):
    s = await _stake(session, data["creator"])
    amount = data.get("amount", 0)
    s.pending_unstake = max((s.pending_unstake or 0) - amount, 0)
    s.withdrawn_total = (s.withdrawn_total or 0) + amount
    s.last_event, s.last_signature = "StakeWithdrawn", meta.get("signature")


@on("Slashed")
async def slashed(session, data, meta):
    s = await _stake(session, data["creator"])
    amount = data.get("amount", 0)
    s.staked = data.get("remaining", max((s.staked or 0) - amount, 0))
    s.slashed_total = (s.slashed_total or 0) + amount
    s.last_event, s.last_signature = "Slashed", meta.get("signature")


async def apply_event(session, name, data, meta, index=0):
    exists = await session.execute(
        select(ProgramEvent.id).where(ProgramEvent.signature == meta["signature"], ProgramEvent.index == index)
    )
    if exists.scalar_one_or_none() is not None:
        return False
    session.add(ProgramEvent(
        signature=meta["signature"], index=index, slot=meta.get("slot", 0),
        block_time=meta.get("block_time"), event_name=name, data=data,
    ))
    handler = HANDLERS.get(name)
    if handler:
        await handler(session, data, meta)
    return True


async def apply_transaction(session, decoder, signature, slot, block_time, log_messages):
    meta = {"signature": signature, "slot": slot, "block_time": block_time}
    n = 0
    for i, (name, data) in enumerate(decoder.decode_logs(log_messages)):
        if await apply_event(session, name, data, meta, i):
            n += 1
    return n
