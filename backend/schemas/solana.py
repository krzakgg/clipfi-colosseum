from decimal import Decimal

from pydantic import BaseModel, Field


class SolanaConfigResponse(BaseModel):
    cluster: str
    rpc_url: str
    treasury_address: str
    system_program_id: str
    escrow_program_id: str = ""
    bmoney_mint: str = ""
    clipusd_mint: str = ""
    bonus_vault: str = ""
    company_deposit_fee_bps: int = 0
    company_withdrawal_fee_bps: int = 0
    creator_withdrawal_fee_bps: int = 0


class WithdrawalChallengeRequest(BaseModel):
    wallet_address: str
    destination_wallet_address: str
    lamports: int = Field(gt=0, le=10_000_000_000)
    account_type: str = Field(pattern="^(company|creator)$")
    account_id: int = Field(gt=0)


class WithdrawalChallengeResponse(BaseModel):
    nonce: str
    message: str
    expires_at: int
    fee_lamports: int
    total_internal_amount: str


class WithdrawalRequest(WithdrawalChallengeRequest):
    nonce: str = Field(min_length=16, max_length=128)
    signature: str = Field(min_length=80, max_length=256)


class WalletRequest(BaseModel):
    account_type: str = Field(pattern="^(company|creator)$")
    account_id: int = Field(gt=0)
    wallet_address: str
    signature: str | None = Field(default=None, min_length=80, max_length=256)


class DepositRequest(BaseModel):
    account_type: str = Field(pattern="^(company|creator)$")
    account_id: int = Field(gt=0)
    wallet_address: str
    signature: str = Field(min_length=80, max_length=100)


class FeeQuoteResponse(BaseModel):
    operation: str
    account_type: str
    fee_bps: int
    fee_lamports: int
    net_lamports: int


class EscrowFundingRequest(BaseModel):
    company_wallet: str
    amount: Decimal = Field(gt=0)
    min_bond: Decimal = Field(default=Decimal(0), ge=0)


class EscrowSettleRequest(BaseModel):
    wallet_address: str
    epoch: int = Field(ge=0)
    units: list[int] | None = Field(default=None, min_length=4, max_length=4)
    evidence_hash: str = Field(pattern="^[0-9a-fA-F]{64}$")


class EscrowReleaseRequest(BaseModel):
    wallet_address: str
    epoch: int = Field(ge=0)
    signature: str | None = Field(default=None, min_length=80, max_length=256)


class EscrowFlagRequest(BaseModel):
    company_wallet: str
    wallet_address: str
    epoch: int = Field(ge=0)
    reason: int = Field(ge=0, le=65_535)


class EscrowResolveRequest(BaseModel):
    wallet_address: str
    epoch: int = Field(ge=0)
    approve: bool
    slash_amount: Decimal = Field(default=Decimal(0), ge=0)


class EscrowCloseRequest(BaseModel):
    company_wallet: str


class EscrowRolloverRequest(BaseModel):
    company_wallet: str
    target_campaign_id: int = Field(gt=0)


class StakeInstructionRequest(BaseModel):
    wallet_address: str
    action: str = Field(pattern="^(stake|request_unstake|withdraw_stake|set_auto_restake)$")
    amount: Decimal | None = Field(default=None, gt=0)
    bps: int | None = Field(default=None, ge=0, le=10_000)
