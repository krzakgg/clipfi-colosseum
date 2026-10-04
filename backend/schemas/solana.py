from pydantic import BaseModel, Field


class SolanaConfigResponse(BaseModel):
    cluster: str
    rpc_url: str
    treasury_address: str
    system_program_id: str
    escrow_program_id: str = ""
    bmoney_mint: str = ""
    escrow_counter_mint: str = ""
    escrow_release_authority: str = ""
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


class CampaignEscrowInstructionRequest(BaseModel):
    company_wallet: str


class CampaignEscrowActionRequest(BaseModel):
    wallet_address: str
