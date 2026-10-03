from pydantic import BaseModel, Field


class SolanaConfigResponse(BaseModel):
    cluster: str
    rpc_url: str
    treasury_address: str
    system_program_id: str


class WithdrawalChallengeRequest(BaseModel):
    wallet_address: str
    destination: str
    lamports: int = Field(gt=0, le=10_000_000_000)


class WithdrawalChallengeResponse(BaseModel):
    nonce: str
    message: str
    expires_at: int


class WithdrawalRequest(WithdrawalChallengeRequest):
    nonce: str = Field(min_length=16, max_length=128)
    signature: str = Field(min_length=80, max_length=256)
