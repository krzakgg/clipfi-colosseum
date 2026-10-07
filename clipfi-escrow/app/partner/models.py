import time

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KycRecord(Base):
    __tablename__ = "kyc"
    wallet: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    provider_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=lambda: int(time.time()))


class LedgerEntry(Base):
    __tablename__ = "ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(8), index=True)
    wallet: Mapped[str] = mapped_column(String(64), index=True)
    usd_amount: Mapped[int] = mapped_column(BigInteger)
    fee: Mapped[int] = mapped_column(BigInteger, default=0)
    clipusd_amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24))
    payout_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tx_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deposit_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=lambda: int(time.time()))
