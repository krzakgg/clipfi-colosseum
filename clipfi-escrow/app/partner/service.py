import time

from sqlalchemy import select

from app.partner.chain import DECIMALS, Issuer
from app.partner.models import KycRecord, LedgerEntry
from app.settings import settings

UNIT = 10 ** DECIMALS
STATUSES = ("approved", "rejected", "pending")


class PartnerError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def to_units(usd):
    return int(round(float(usd) * UNIT))


def split_fee(usd_units, margin_bps=None):
    bps = settings.margin_bps if margin_bps is None else margin_bps
    fee = usd_units * bps // 10_000
    return fee, usd_units - fee


class PartnerService:
    def __init__(self, db, denylist=None, issuer=None, margin_bps=None):
        self.db = db
        self.denylist = set(settings.denylist if denylist is None else denylist)
        self.issuer = issuer or Issuer()
        self.margin_bps = margin_bps

    async def set_kyc(self, wallet, status, provider_ref=None):
        if status not in STATUSES:
            raise PartnerError(422, "invalid status")
        reason = None
        if wallet in self.denylist:
            status, reason = "rejected", "sanctions_hit"
        async with self.db.session() as s:
            rec = await s.get(KycRecord, wallet)
            if rec is None:
                rec = KycRecord(wallet=wallet)
                s.add(rec)
            rec.status, rec.provider_ref, rec.reason, rec.updated_at = status, provider_ref, reason, int(time.time())
            await s.commit()
            return self._kyc(rec)

    async def get_kyc(self, wallet):
        async with self.db.session() as s:
            rec = await s.get(KycRecord, wallet)
        if rec is None:
            if wallet in self.denylist:
                return {"wallet": wallet, "status": "rejected", "provider_ref": None, "reason": "sanctions_hit"}
            return None
        return self._kyc(rec)

    @staticmethod
    def _kyc(rec):
        return {"wallet": rec.wallet, "status": rec.status, "provider_ref": rec.provider_ref, "reason": rec.reason, "updated_at": rec.updated_at}

    async def require_approved(self, wallet):
        k = await self.get_kyc(wallet)
        if k is None or k["status"] != "approved":
            raise PartnerError(403, "kyc not approved")

    async def onramp(self, brand_wallet, usd_amount):
        usd_units = to_units(usd_amount)
        if usd_units <= 0:
            raise PartnerError(422, "amount must be positive")
        await self.require_approved(brand_wallet)
        fee, clip = split_fee(usd_units, self.margin_bps)
        row = LedgerEntry(kind="onramp", wallet=brand_wallet, usd_amount=usd_units, fee=fee, clipusd_amount=clip, status="recorded")
        if self.issuer.enabled:
            row.tx_signature = await self.issuer.mint_to(brand_wallet, clip)
        row.status = "minted"
        async with self.db.session() as s:
            s.add(row)
            await s.commit()
            return self._row(row)

    async def offramp(self, creator_wallet, clipusd_amount, payout_method):
        clip = to_units(clipusd_amount)
        if clip <= 0:
            raise PartnerError(422, "amount must be positive")
        await self.require_approved(creator_wallet)
        row = LedgerEntry(kind="offramp", wallet=creator_wallet, usd_amount=clip, fee=0, clipusd_amount=clip, payout_method=payout_method, status="awaiting_transfer")
        if self.issuer.enabled:
            sig = await self.issuer.burn_from(creator_wallet, clip)
            if sig:
                row.tx_signature, row.status = sig, "burned"
            else:
                row.deposit_address = self.issuer.deposit_address
        async with self.db.session() as s:
            s.add(row)
            await s.commit()
            return self._row(row)

    async def ledger(self, wallet=None):
        q = select(LedgerEntry).order_by(LedgerEntry.id.desc())
        if wallet:
            q = q.where(LedgerEntry.wallet == wallet)
        async with self.db.session() as s:
            return [self._row(r) for r in (await s.execute(q)).scalars()]

    @staticmethod
    def _row(r):
        return {c.name: getattr(r, c.name) for c in r.__table__.columns}
