from fastapi import APIRouter, HTTPException, status

from schemas.solana import (
    SolanaConfigResponse,
    WithdrawalChallengeRequest,
    WithdrawalChallengeResponse,
    WithdrawalRequest,
)
from settings import get_settings
from solana_service import (
    SYSTEM_PROGRAM_ID,
    SolanaServiceError,
    create_challenge,
    get_balance,
    get_treasury_keypair,
    verify_challenge,
    withdraw,
)

router = APIRouter(prefix="/api/solana", tags=["solana"])


@router.get("/config", response_model=SolanaConfigResponse)
async def solana_config():
    settings = get_settings()
    try:
        treasury_address = str(get_treasury_keypair().pubkey())
    except SolanaServiceError:
        treasury_address = settings.solana_treasury_address
    if not treasury_address:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Skarbiec Solany nie jest skonfigurowany",
        )
    return SolanaConfigResponse(
        cluster=settings.solana_cluster,
        rpc_url=settings.solana_rpc_url,
        treasury_address=treasury_address,
        system_program_id=SYSTEM_PROGRAM_ID,
    )


@router.get("/balance/{address}")
async def solana_balance(address: str):
    return {"address": address, "lamports": await get_balance(address)}


@router.post("/withdraw/challenge", response_model=WithdrawalChallengeResponse)
async def withdrawal_challenge(payload: WithdrawalChallengeRequest):
    nonce, message, expires_at = create_challenge(
        payload.wallet_address,
        payload.destination,
        payload.lamports,
    )
    return WithdrawalChallengeResponse(nonce=nonce, message=message, expires_at=expires_at)


@router.post("/withdraw")
async def solana_withdraw(payload: WithdrawalRequest):
    challenge = verify_challenge(
        payload.wallet_address,
        payload.destination,
        payload.lamports,
        payload.nonce,
        payload.signature,
    )
    try:
        signature = await withdraw(challenge)
    except SolanaServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"signature": signature, "cluster": get_settings().solana_cluster}
