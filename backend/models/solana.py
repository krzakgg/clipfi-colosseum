from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class SolanaWithdrawalChallenge(Base):
    __tablename__ = "solana_withdrawal_challenges"

    nonce: Mapped[str] = mapped_column(String(128), primary_key=True)
    wallet_address: Mapped[str] = mapped_column(String(44), nullable=False, index=True)
    destination: Mapped[str] = mapped_column(String(44), nullable=False)
    lamports: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_lamports: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    message: Mapped[str] = mapped_column(String(512), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SolanaWithdrawal(Base):
    __tablename__ = "solana_withdrawals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nonce: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    wallet_address: Mapped[str] = mapped_column(String(44), nullable=False, index=True)
    destination: Mapped[str] = mapped_column(String(44), nullable=False)
    lamports: Mapped[int] = mapped_column(BigInteger, nullable=False)
    internal_amount: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    fee_lamports: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    fee_internal_amount: Mapped[float] = mapped_column(
        Numeric(20, 8), nullable=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    signature: Mapped[str | None] = mapped_column(String(100), unique=True)
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SolanaDeposit(Base):
    __tablename__ = "solana_deposits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signature: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(44), nullable=False)
    lamports: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_lamports: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    internal_amount: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
