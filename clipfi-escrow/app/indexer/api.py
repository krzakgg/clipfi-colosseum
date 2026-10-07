from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import select

from app.db import Database
from app.indexer.models import Campaign, Cursor, Payout, ProgramEvent, Stake


def row(o):
    return {c.name: getattr(o, c.name) for c in o.__table__.columns}


def create_app(db=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.db = db or Database()
        await app.state.db.create_all()
        yield
        if db is None:
            await app.state.db.dispose()

    app = FastAPI(title="clipfi indexer", lifespan=lifespan)

    @app.get("/health")
    async def health():
        async with app.state.db.session() as s:
            c = await s.get(Cursor, "last_signature")
            n = (await s.execute(select(ProgramEvent.id).order_by(ProgramEvent.id.desc()).limit(1))).scalar_one_or_none()
        return {"ok": True, "last_signature": c.value if c else None, "events": n or 0}

    @app.get("/events")
    async def events(name: str | None = None, limit: int = Query(100, ge=1, le=1000)):
        q = select(ProgramEvent).order_by(ProgramEvent.slot.desc(), ProgramEvent.id.desc()).limit(limit)
        if name:
            q = q.where(ProgramEvent.event_name == name)
        async with app.state.db.session() as s:
            return [row(e) for e in (await s.execute(q)).scalars()]

    @app.get("/campaigns")
    async def campaigns():
        async with app.state.db.session() as s:
            return [row(c) for c in (await s.execute(select(Campaign).order_by(Campaign.last_slot.desc()))).scalars()]

    @app.get("/campaigns/{campaign}")
    async def campaign(campaign: str):
        async with app.state.db.session() as s:
            c = await s.get(Campaign, campaign)
            if c is None:
                raise HTTPException(404, "campaign not found")
            payouts = (await s.execute(select(Payout).where(Payout.campaign == campaign))).scalars()
            return {**row(c), "payouts": [row(p) for p in payouts]}

    @app.get("/payouts")
    async def payouts(campaign: str | None = None, creator: str | None = None):
        q = select(Payout).order_by(Payout.epoch.desc())
        if campaign:
            q = q.where(Payout.campaign == campaign)
        if creator:
            q = q.where(Payout.creator == creator)
        async with app.state.db.session() as s:
            return [row(p) for p in (await s.execute(q)).scalars()]

    @app.get("/stakes/{creator}")
    async def stake(creator: str):
        async with app.state.db.session() as s:
            st = await s.get(Stake, creator)
            if st is None:
                raise HTTPException(404, "no stake for creator")
            return row(st)

    return app


app = create_app()
