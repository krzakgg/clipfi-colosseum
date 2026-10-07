from sqlalchemy import JSON, BigInteger, Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProgramEvent(Base):
    __tablename__ = "program_events"
    __table_args__ = (UniqueConstraint("signature", "index", name="uq_event_sig_idx"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signature: Mapped[str] = mapped_column(String(128), index=True)
    index: Mapped[int] = mapped_column(Integer)
    slot: Mapped[int] = mapped_column(BigInteger, index=True)
    block_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_name: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[dict] = mapped_column(JSON)


class Campaign(Base):
    __tablename__ = "campaigns"
    campaign: Mapped[str] = mapped_column(String(64), primary_key=True)
    brand: Mapped[str | None] = mapped_column(String(64), nullable=True)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    vault: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    end_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    funded_total: Mapped[int] = mapped_column(BigInteger, default=0)
    paid_total: Mapped[int] = mapped_column(BigInteger, default=0)
    refunded: Mapped[int] = mapped_column(BigInteger, default=0)
    rolled_over: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(16), default="Active")
    last_slot: Mapped[int] = mapped_column(BigInteger, default=0)


class Payout(Base):
    __tablename__ = "payouts"
    __table_args__ = (UniqueConstraint("campaign", "creator", "epoch", name="uq_payout"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign: Mapped[str] = mapped_column(String(64), index=True)
    creator: Mapped[str] = mapped_column(String(64), index=True)
    epoch: Mapped[int] = mapped_column(BigInteger)
    units: Mapped[list | None] = mapped_column(JSON, nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, default=0)
    unlock_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="Pending")
    flag_reason: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    released_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    bonus_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    release_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Stake(Base):
    __tablename__ = "stakes"
    creator: Mapped[str] = mapped_column(String(64), primary_key=True)
    staked: Mapped[int] = mapped_column(BigInteger, default=0)
    pending_unstake: Mapped[int] = mapped_column(BigInteger, default=0)
    unlock_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    withdrawn_total: Mapped[int] = mapped_column(BigInteger, default=0)
    slashed_total: Mapped[int] = mapped_column(BigInteger, default=0)
    bonus_total: Mapped[int] = mapped_column(BigInteger, default=0)
    last_event: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Cursor(Base):
    __tablename__ = "indexer_cursor"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[str] = mapped_column(String(128))
