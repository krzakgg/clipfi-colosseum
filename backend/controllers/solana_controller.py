from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.solana import (
    DepositRequest,
    FeeQuoteResponse,
    CampaignEscrowInstructionRequest,
    CampaignEscrowActionRequest,
    SolanaConfigResponse,
    WalletRequest,
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
    deposit,
    set_wallet,
    verify_challenge,
    withdraw,
    calculate_fee,
    fee_bps_for,
    build_campaign_funding_instruction,
    build_campaign_take_instruction,
    build_campaign_refund_instruction,
)
from database import get_db

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
        escrow_program_id=settings.solana_escrow_program_id,
        bmoney_mint=settings.solana_bmoney_mint,
        escrow_counter_mint=settings.solana_escrow_counter_mint,
        escrow_release_authority=settings.solana_escrow_release_authority
        or treasury_address,
        company_deposit_fee_bps=settings.solana_company_deposit_fee_bps,
        company_withdrawal_fee_bps=settings.solana_company_withdrawal_fee_bps,
        creator_withdrawal_fee_bps=settings.solana_creator_withdrawal_fee_bps,
    )


@router.get("/balance/{address}")
async def solana_balance(address: str):
    return {"address": address, "lamports": await get_balance(address)}


@router.post("/wallet")
async def configure_wallet(payload: WalletRequest, db: AsyncSession = Depends(get_db)):
    wallet_address = await set_wallet(
        db, payload.account_type, payload.account_id, payload.wallet_address,
        payload.signature
    )
    return {"wallet_address": wallet_address}


@router.get("/account/{account_type}/{account_id}")
async def account_wallet(
    account_type: str, account_id: int, db: AsyncSession = Depends(get_db)
):
    from solana_service import get_account

    account = await get_account(db, account_type, account_id)
    return {
        "wallet_address": account.solana_wallet_address,
        "internal_balance": str(account.internal_balance or 0),
    }


@router.post("/deposit")
async def solana_deposit(
    payload: DepositRequest, db: AsyncSession = Depends(get_db)
):
    internal_amount, lamports = await deposit(
        db,
        payload.account_type,
        payload.account_id,
        payload.wallet_address,
        payload.signature,
    )
    return {
        "signature": payload.signature,
        "lamports": lamports,
        "internal_amount": str(internal_amount),
        "fee_lamports": calculate_fee(
            lamports, fee_bps_for(payload.account_type, "deposit")
        ),
    }


@router.post("/fee-quote", response_model=FeeQuoteResponse)
async def solana_fee_quote(
    operation: str, account_type: str, lamports: int
):
    if operation not in {"deposit", "withdrawal"} or account_type not in {"company", "creator"}:
        raise HTTPException(status_code=422, detail="Nieprawidłowy typ operacji lub konta")
    if lamports <= 0:
        raise HTTPException(status_code=422, detail="Kwota musi być dodatnia")
    fee = calculate_fee(lamports, fee_bps_for(account_type, operation))
    return FeeQuoteResponse(
        operation=operation,
        account_type=account_type,
        fee_bps=fee_bps_for(account_type, operation),
        fee_lamports=fee,
        net_lamports=lamports - fee if operation == "deposit" else lamports,
    )


@router.post("/campaign/{campaign_id}/escrow/funding-instruction")
async def campaign_escrow_funding_instruction(
    campaign_id: int,
    payload: CampaignEscrowInstructionRequest,
    db: AsyncSession = Depends(get_db),
):
    return await build_campaign_funding_instruction(db, campaign_id, payload.company_wallet)


@router.post("/campaign/{campaign_id}/escrow/release")
async def campaign_escrow_release(
    campaign_id: int,
    payload: CampaignEscrowActionRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        instruction = await build_campaign_take_instruction(
            db, campaign_id, payload.wallet_address
        )
    except SolanaServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return instruction


@router.post("/campaign/{campaign_id}/escrow/refund-instruction")
async def campaign_escrow_refund(
    campaign_id: int,
    payload: CampaignEscrowActionRequest,
    db: AsyncSession = Depends(get_db),
):
    return await build_campaign_refund_instruction(
        db, campaign_id, payload.wallet_address
    )


@router.post("/withdraw/challenge", response_model=WithdrawalChallengeResponse)
async def withdrawal_challenge(
    payload: WithdrawalChallengeRequest, db: AsyncSession = Depends(get_db)
):
    challenge = await create_challenge(
        db,
        payload.wallet_address,
        payload.account_type,
        payload.account_id,
        payload.lamports,
        payload.destination_wallet_address,
    )
    return WithdrawalChallengeResponse(
        nonce=challenge.nonce,
        message=challenge.message,
        expires_at=challenge.expires_at,
        fee_lamports=challenge.fee_lamports,
        total_internal_amount=str(challenge.total_internal_amount),
    )


@router.post("/withdraw")
async def solana_withdraw(
    payload: WithdrawalRequest, db: AsyncSession = Depends(get_db)
):
    challenge, withdrawal = await verify_challenge(
        db,
        payload.wallet_address,
        payload.account_type,
        payload.account_id,
        payload.lamports,
        payload.nonce,
        payload.signature,
        payload.destination_wallet_address,
    )
    try:
        signature = await withdraw(db, challenge, withdrawal.id)
    except SolanaServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"signature": signature, "cluster": get_settings().solana_cluster}
