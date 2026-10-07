from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.solana import (
    DepositRequest,
    EscrowCloseRequest,
    EscrowFlagRequest,
    EscrowFundingRequest,
    EscrowReleaseRequest,
    EscrowResolveRequest,
    EscrowRolloverRequest,
    EscrowSettleRequest,
    FeeQuoteResponse,
    SolanaConfigResponse,
    StakeInstructionRequest,
    WalletRequest,
    WithdrawalChallengeRequest,
    WithdrawalChallengeResponse,
    WithdrawalRequest,
)
from settings import get_settings
from solana_service import (
    SYSTEM_PROGRAM_ID,
    SolanaServiceError,
    build_close_instruction,
    build_escrow_funding_instructions,
    build_flag_instruction,
    build_rollover_instruction,
    build_stake_instruction,
    calculate_fee,
    create_challenge,
    deposit,
    escrow_config_view,
    fee_bps_for,
    get_balance,
    get_escrow_campaign,
    get_stake,
    get_treasury_keypair,
    list_payouts,
    release_payout,
    require_oracle_token,
    resolve_payout,
    set_wallet,
    settle_payout,
    verify_challenge,
    withdraw,
)
from database import get_db
from tracking_client import TrackingClient, get_tracking

router = APIRouter(prefix="/api/solana", tags=["solana"])

OracleToken = Annotated[str | None, Header(alias="X-Oracle-Token")]



async def _escrow(call):
    try:
        return await call
    except SolanaServiceError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


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
    escrow = escrow_config_view()
    return SolanaConfigResponse(
        cluster=settings.solana_cluster,
        rpc_url=settings.solana_rpc_url,
        treasury_address=treasury_address,
        system_program_id=SYSTEM_PROGRAM_ID,
        escrow_program_id=escrow["escrow_program_id"],
        bmoney_mint=settings.solana_bmoney_mint,
        clipusd_mint=escrow["clipusd_mint"],
        bonus_vault=escrow["bonus_vault"],
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
    payload: EscrowFundingRequest,
    db: AsyncSession = Depends(get_db),
):
    return await _escrow(
        build_escrow_funding_instructions(
            db, campaign_id, payload.company_wallet, payload.amount, payload.min_bond
        )
    )


@router.get("/campaign/{campaign_id}/escrow")
async def campaign_escrow(campaign_id: int, db: AsyncSession = Depends(get_db)):
    return await _escrow(get_escrow_campaign(db, campaign_id))


@router.post("/campaign/{campaign_id}/escrow/settle")
async def campaign_escrow_settle(
    campaign_id: int,
    payload: EscrowSettleRequest,
    x_oracle_token: OracleToken = None,
    db: AsyncSession = Depends(get_db),
    tracking: TrackingClient = Depends(get_tracking),
):
    require_oracle_token(x_oracle_token)
    return await _escrow(
        settle_payout(
            db,
            campaign_id,
            payload.wallet_address,
            payload.epoch,
            payload.units,
            payload.evidence_hash,
            tracking,
        )
    )


@router.post("/campaign/{campaign_id}/escrow/release")
async def campaign_escrow_release(
    campaign_id: int,
    payload: EscrowReleaseRequest,
    x_oracle_token: OracleToken = None,
    db: AsyncSession = Depends(get_db),
):
    return await _escrow(
        release_payout(
            db, campaign_id, payload.wallet_address, payload.epoch, x_oracle_token, payload.signature
        )
    )


@router.post("/campaign/{campaign_id}/escrow/flag")
async def campaign_escrow_flag(
    campaign_id: int,
    payload: EscrowFlagRequest,
    db: AsyncSession = Depends(get_db),
):
    return await _escrow(
        build_flag_instruction(
            db, campaign_id, payload.company_wallet, payload.wallet_address, payload.epoch, payload.reason
        )
    )


@router.post("/campaign/{campaign_id}/escrow/resolve")
async def campaign_escrow_resolve(
    campaign_id: int,
    payload: EscrowResolveRequest,
    x_oracle_token: OracleToken = None,
    db: AsyncSession = Depends(get_db),
):
    require_oracle_token(x_oracle_token)
    return await _escrow(
        resolve_payout(
            db, campaign_id, payload.wallet_address, payload.epoch, payload.approve, payload.slash_amount
        )
    )


@router.post("/campaign/{campaign_id}/escrow/close")
async def campaign_escrow_close(
    campaign_id: int,
    payload: EscrowCloseRequest,
    db: AsyncSession = Depends(get_db),
):
    return await _escrow(build_close_instruction(db, campaign_id, payload.company_wallet))


@router.post("/campaign/{campaign_id}/escrow/rollover")
async def campaign_escrow_rollover(
    campaign_id: int,
    payload: EscrowRolloverRequest,
    db: AsyncSession = Depends(get_db),
):
    return await _escrow(
        build_rollover_instruction(db, campaign_id, payload.company_wallet, payload.target_campaign_id)
    )


@router.get("/campaign/{campaign_id}/payouts/{wallet_address}")
async def campaign_payouts(
    campaign_id: int, wallet_address: str, db: AsyncSession = Depends(get_db)
):
    return await _escrow(list_payouts(db, campaign_id, wallet_address))


@router.post("/stake/instruction")
async def stake_instruction(payload: StakeInstructionRequest):
    try:
        return build_stake_instruction(payload.wallet_address, payload.action, payload.amount, payload.bps)
    except SolanaServiceError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/stake/{wallet_address}")
async def stake_account(wallet_address: str):
    return await _escrow(get_stake(wallet_address))


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
