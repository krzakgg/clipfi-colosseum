import hmac
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.db import Database
from app.partner.service import PartnerError, PartnerService
from app.settings import settings


class KycIn(BaseModel):
    status: str
    provider_ref: str | None = None


class OnrampIn(BaseModel):
    brand_wallet: str
    usd_amount: float


class OfframpIn(BaseModel):
    creator_wallet: str
    clipusd_amount: float
    payout_method: str


def token_guard(expected):
    async def dependency(x_partner_token: str | None = Header(default=None)):
        if not expected or x_partner_token is None or not hmac.compare_digest(x_partner_token, expected):
            raise HTTPException(401, "partner token required")

    return dependency


def create_app(db=None, service=None, token=None):
    guard = [Depends(token_guard(settings.partner_token if token is None else token))]
    @asynccontextmanager
    async def lifespan(app):
        app.state.db = db or Database()
        await app.state.db.create_all()
        app.state.svc = service or PartnerService(app.state.db)
        yield
        if db is None:
            await app.state.db.dispose()

    app = FastAPI(title="clipfi partner", lifespan=lifespan)

    @app.exception_handler(PartnerError)
    async def partner_error(request, exc):
        raise HTTPException(exc.code, str(exc))

    @app.get("/health")
    async def health():
        return {"ok": True, "issuer": app.state.svc.issuer.enabled}

    @app.post("/kyc/{wallet}", dependencies=guard)
    async def set_kyc(wallet: str, body: KycIn):
        return await app.state.svc.set_kyc(wallet, body.status, body.provider_ref)

    @app.get("/kyc/{wallet}", dependencies=guard)
    async def get_kyc(wallet: str):
        k = await app.state.svc.get_kyc(wallet)
        if k is None:
            raise HTTPException(404, "no kyc record")
        return k

    @app.post("/onramp", dependencies=guard)
    async def onramp(body: OnrampIn):
        return await app.state.svc.onramp(body.brand_wallet, body.usd_amount)

    @app.post("/offramp", dependencies=guard)
    async def offramp(body: OfframpIn):
        return await app.state.svc.offramp(body.creator_wallet, body.clipusd_amount, body.payout_method)

    @app.get("/ledger", dependencies=guard)
    async def ledger(wallet: str | None = None):
        return await app.state.svc.ledger(wallet)

    return app


app = create_app()
