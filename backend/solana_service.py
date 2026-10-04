import json
import secrets
import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import base58
from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction
from solders.instruction import AccountMeta, Instruction
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed, Finalized
from solana.exceptions import SolanaRpcException
from solana.rpc.core import (
    RPCException,
    RPCNoResultException,
    TransactionExpiredBlockheightExceededError,
    UnconfirmedTxError,
)

from models import (
    Campaign,
    CampaignSubmission,
    Company,
    Creator,
    SolanaDeposit,
    SolanaWithdrawal,
    SolanaWithdrawalChallenge,
)
from settings import get_settings

SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
CHALLENGE_TTL_SECONDS = 300
WITHDRAWAL_PROCESSING = "processing"
WITHDRAWAL_COMPLETED = "completed"
WITHDRAWAL_FAILED = "failed"


class SolanaServiceError(Exception):
    """Raised when the configured Solana treasury cannot complete a transfer."""


@dataclass(frozen=True)
class WithdrawalChallenge:
    nonce: str
    wallet_address: str
    destination: str
    lamports: int
    message: str
    expires_at: int
    account_type: str
    account_id: int


def _parse_keypair(value: str) -> Keypair:
    try:
        raw = value.strip()
        if raw.startswith("["):
            return Keypair.from_bytes(bytes(json.loads(raw)))
        return Keypair.from_base58_string(raw)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("SOLANA_TREASURY_PRIVATE_KEY ma nieprawidłowy format") from exc


def get_treasury_keypair() -> Keypair:
    settings = get_settings()
    if not settings.solana_treasury_private_key:
        raise SolanaServiceError("Brak konfiguracji SOLANA_TREASURY_PRIVATE_KEY")
    try:
        return _parse_keypair(settings.solana_treasury_private_key.get_secret_value())
    except RuntimeError as exc:
        raise SolanaServiceError(str(exc)) from exc


def validate_address(value: str) -> Pubkey:
    try:
        address = Pubkey.from_string(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nieprawidłowy adres portfela Solana",
        ) from exc
    if str(address) != value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Adres portfela musi być w kanonicznym formacie Base58",
        )
    return address


def build_withdrawal_message(
    wallet_address: str, destination: str, lamports: int, nonce: str
) -> str:
    return (
        "WAGGI withdrawal\n"
        f"wallet: {wallet_address}\n"
        f"destination: {destination}\n"
        f"lamports: {lamports}\n"
        f"nonce: {nonce}"
    )


async def create_challenge(
    db: AsyncSession,
    wallet_address: str,
    account_type: str,
    account_id: int,
    lamports: int,
) -> WithdrawalChallenge:
    validate_address(wallet_address)
    account = await get_account(db, account_type, account_id)
    destination = account.solana_wallet_address
    if not destination:
        raise HTTPException(status_code=400, detail="Najpierw ustaw adres portfela wypłat")
    settings = get_settings()
    if lamports > settings.solana_max_withdrawal_lamports:
        raise HTTPException(status_code=400, detail="Przekroczono limit pojedynczej wypłaty")

    nonce = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=CHALLENGE_TTL_SECONDS)
    message = build_withdrawal_message(wallet_address, destination, lamports, nonce)
    db.add(
        SolanaWithdrawalChallenge(
            nonce=nonce,
            wallet_address=wallet_address,
            destination=destination,
            lamports=lamports,
            message=message,
            expires_at=expires_at,
        )
    )
    await db.commit()
    return WithdrawalChallenge(
        nonce, wallet_address, destination, lamports, message, int(expires_at.timestamp()),
        account_type, account_id
    )


async def verify_challenge(
    db: AsyncSession,
    wallet_address: str,
    account_type: str,
    account_id: int,
    lamports: int,
    nonce: str,
    signature: str,
) -> tuple[WithdrawalChallenge, SolanaWithdrawal]:
    async with db.begin():
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:wallet_address))"),
            {"wallet_address": wallet_address},
        )
        result = await db.execute(
            select(SolanaWithdrawalChallenge)
            .where(SolanaWithdrawalChallenge.nonce == nonce)
            .with_for_update()
        )
        record = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if not record or record.used_at or record.expires_at < now:
            raise HTTPException(status_code=400, detail="Challenge wygasł lub został już użyty")
        account = await get_account(db, account_type, account_id)
        destination = account.solana_wallet_address
        if not destination or (
            record.wallet_address != wallet_address
            or record.destination != destination
            or record.lamports != lamports
            or destination != record.destination
        ):
            raise HTTPException(status_code=400, detail="Dane wypłaty nie pasują do challenge")

        try:
            signature_bytes = base58.b58decode(signature)
            valid = Signature.from_bytes(signature_bytes).verify(
                validate_address(wallet_address), record.message.encode("utf-8")
            )
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise HTTPException(status_code=401, detail="Nieprawidłowy podpis portfela")

        settings = get_settings()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        total = await db.scalar(
            select(func.coalesce(func.sum(SolanaWithdrawal.lamports), 0)).where(
                SolanaWithdrawal.wallet_address == wallet_address,
                SolanaWithdrawal.created_at >= day_start,
                SolanaWithdrawal.status.in_(
                    [WITHDRAWAL_PROCESSING, WITHDRAWAL_COMPLETED]
                ),
            )
        )
        if total + lamports > settings.solana_daily_withdrawal_limit_lamports:
            raise HTTPException(status_code=400, detail="Przekroczono dzienny limit wypłat")

        internal_amount = (
            Decimal(lamports) / Decimal(1_000_000_000)
            * Decimal(str(settings.solana_internal_currency_per_sol))
        )
        current_balance = Decimal(str(account.internal_balance or 0))
        if current_balance < internal_amount:
            raise HTTPException(status_code=400, detail="Niewystarczające saldo waluty wewnętrznej")
        account.internal_balance = current_balance - internal_amount
        record.used_at = now
        withdrawal = SolanaWithdrawal(
            nonce=nonce,
            wallet_address=wallet_address,
            destination=destination,
            lamports=lamports,
            internal_amount=internal_amount,
            status=WITHDRAWAL_PROCESSING,
        )
        db.add(withdrawal)

    return (
        WithdrawalChallenge(
            record.nonce,
            record.wallet_address,
            record.destination,
            record.lamports,
            record.message, int(record.expires_at.timestamp()), account_type, account_id
        ),
        withdrawal,
    )


async def get_account(db: AsyncSession, account_type: str, account_id: int):
    model = Company if account_type == "company" else Creator
    account = await db.get(model, account_id, with_for_update=True)
    if not account:
        raise HTTPException(status_code=404, detail="Nie znaleziono konta")
    return account


async def set_wallet(
    db: AsyncSession, account_type: str, account_id: int, wallet_address: str
) -> str:
    validate_address(wallet_address)
    account = await get_account(db, account_type, account_id)
    account.solana_wallet_address = wallet_address
    await db.commit()
    return wallet_address


async def deposit(
    db: AsyncSession, account_type: str, account_id: int, wallet_address: str, signature: str
) -> tuple[Decimal, int]:
    validate_address(wallet_address)
    async with db.begin():
        existing = await db.scalar(
            select(SolanaDeposit).where(SolanaDeposit.signature == signature).with_for_update()
        )
        if existing:
            if existing.account_type != account_type or existing.account_id != account_id:
                raise HTTPException(status_code=409, detail="Wpłata jest przypisana do innego konta")
            return Decimal(str(existing.internal_amount)), existing.lamports

        account = await get_account(db, account_type, account_id)
        if account.solana_wallet_address != wallet_address:
            raise HTTPException(status_code=400, detail="Portfel nie jest przypisany do konta")

        settings = get_settings()
        async with AsyncClient(settings.solana_rpc_url) as client:
            response = await client.get_transaction(
                signature, commitment=Finalized, max_supported_transaction_version=0
            )
        if not response.value:
            raise HTTPException(status_code=400, detail="Nie znaleziono potwierdzonej transakcji")
        payload = json.loads(response.value.to_json())
        meta = payload.get("transaction", {}).get("meta") or {}
        if meta.get("err") is not None:
            raise HTTPException(status_code=400, detail="Transakcja wpłaty zakończyła się błędem")
        transaction_payload = payload.get("transaction", {})
        message = transaction_payload.get("message") or transaction_payload.get(
            "transaction", {}
        ).get("message")
        if not message:
            raise HTTPException(status_code=400, detail="Nieprawidłowy format transakcji wpłaty")
        treasury = settings.solana_treasury_address or str(get_treasury_keypair().pubkey())
        amount = 0
        for instruction in message.get("instructions", []):
            parsed = instruction.get("parsed", {})
            info = parsed.get("info", {})
            if (
                parsed.get("type") == "transfer"
                and info.get("source") == wallet_address
                and info.get("destination") == treasury
            ):
                amount += int(info.get("lamports", 0))
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Transakcja nie zawiera wpłaty do skarbca")

        internal_amount = (
            Decimal(amount) / Decimal(1_000_000_000)
            * Decimal(str(settings.solana_internal_currency_per_sol))
        )
        account.internal_balance = Decimal(str(account.internal_balance or 0)) + internal_amount
        db.add(
            SolanaDeposit(
                signature=signature,
                account_type=account_type,
                account_id=account_id,
                wallet_address=wallet_address,
                lamports=amount,
                internal_amount=internal_amount,
                status="credited",
            )
        )
    return internal_amount, amount


async def withdraw(db: AsyncSession, challenge: WithdrawalChallenge, withdrawal_id: int) -> str:
    try:
        keypair = get_treasury_keypair()
        async with AsyncClient(get_settings().solana_rpc_url) as client:
            response = await client.get_latest_blockhash(commitment=Finalized)
            if not response.value:
                raise SolanaServiceError("Nie udało się pobrać blockhasha Solany")

            instruction = transfer(
                TransferParams(
                    from_pubkey=keypair.pubkey(),
                    to_pubkey=validate_address(challenge.destination),
                    lamports=challenge.lamports,
                )
            )
            message = MessageV0.try_compile(
                payer=keypair.pubkey(),
                instructions=[instruction],
                address_lookup_table_accounts=[],
                recent_blockhash=response.value.blockhash,
            )
            transaction = VersionedTransaction(message, [keypair])
            result = await client.send_transaction(transaction)
            if not result.value:
                raise SolanaServiceError("RPC Solany nie zwróciło sygnatury transakcji")
            confirmation = await client.confirm_transaction(result.value, commitment=Finalized)
            if confirmation.value is False:
                raise SolanaServiceError("Transakcja wypłaty nie została potwierdzona")
            signature = str(result.value)
    except (
        OSError,
        RuntimeError,
        ValueError,
        SolanaServiceError,
        SolanaRpcException,
        RPCException,
        RPCNoResultException,
        TransactionExpiredBlockheightExceededError,
        UnconfirmedTxError,
    ) as exc:
        async with db.begin():
            withdrawal = await db.get(SolanaWithdrawal, withdrawal_id, with_for_update=True)
            if withdrawal:
                withdrawal.status = WITHDRAWAL_FAILED
                withdrawal.error = str(exc)[:500]
                account = await get_account(db, challenge.account_type, challenge.account_id)
                account.internal_balance = (
                    Decimal(str(account.internal_balance or 0))
                    + Decimal(str(withdrawal.internal_amount))
                )
        if isinstance(exc, SolanaServiceError):
            raise
        raise SolanaServiceError("Nie udało się wykonać wypłaty SOL") from exc

    async with db.begin():
        withdrawal = await db.get(SolanaWithdrawal, withdrawal_id, with_for_update=True)
        if not withdrawal:
            raise SolanaServiceError("Nie znaleziono rejestru wypłaty")
        withdrawal.status = WITHDRAWAL_COMPLETED
        withdrawal.signature = signature
        withdrawal.completed_at = datetime.now(timezone.utc)
    return signature


async def get_balance(address: str) -> int:
    validate_address(address)
    async with AsyncClient(get_settings().solana_rpc_url) as client:
        response = await client.get_balance(
            validate_address(address), commitment=Confirmed
        )
        return response.value


def _escrow_config() -> tuple[Pubkey, Pubkey, Pubkey]:
    settings = get_settings()
    if not settings.solana_escrow_program_id or not settings.solana_bmoney_mint:
        raise SolanaServiceError(
            "Escrow nie jest skonfigurowany: ustaw SOLANA_ESCROW_PROGRAM_ID i SOLANA_BMONEY_MINT"
        )
    program_id = validate_address(settings.solana_escrow_program_id)
    mint = validate_address(settings.solana_bmoney_mint)
    authority = validate_address(
        settings.solana_escrow_release_authority
        or str(get_treasury_keypair().pubkey())
    )
    return program_id, mint, authority


def _associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    address, _ = Pubkey.find_program_address(
        [bytes(owner), bytes(Pubkey.from_string(TOKEN_PROGRAM_ID)), bytes(mint)],
        Pubkey.from_string(ASSOCIATED_TOKEN_PROGRAM_ID),
    )
    return address


def _anchor_discriminator(name: str) -> bytes:
    return hashlib.sha256(f"global:{name}".encode("utf-8")).digest()[:8]


def _campaign_pda(program_id: Pubkey, maker: Pubkey, campaign_id: int) -> Pubkey:
    address, _ = Pubkey.find_program_address(
        [b"campaign-offer", bytes(maker), campaign_id.to_bytes(8, "little")],
        program_id,
    )
    return address


def _instruction_payload(instruction: Instruction) -> dict:
    return {
        "program_id": str(instruction.program_id),
        "data": base64.b64encode(bytes(instruction.data)).decode("ascii"),
        "accounts": [
            {
                "pubkey": str(meta.pubkey),
                "is_signer": meta.is_signer,
                "is_writable": meta.is_writable,
            }
            for meta in instruction.accounts
        ],
    }


async def build_campaign_funding_instruction(
    db: AsyncSession, campaign_id: int, company_wallet: str
) -> dict:
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")
    company = await db.get(Company, campaign.company_id)
    if not company or company.solana_wallet_address != company_wallet:
        raise HTTPException(status_code=403, detail="Portfel nie należy do firmy kampanii")
    if campaign.total_budget <= 0:
        raise HTTPException(status_code=400, detail="Kampania nie ma dodatniego budżetu")
    creator_result = await db.execute(
        select(Creator)
        .join(CampaignSubmission, CampaignSubmission.creator_id == Creator.id)
        .where(CampaignSubmission.campaign_id == campaign_id)
        .order_by(CampaignSubmission.id.asc())
    )
    creator = creator_result.scalars().first()
    creator_wallet = creator.solana_wallet_address if creator else None
    if not creator_wallet:
        raise HTTPException(
            status_code=400,
            detail="Kampania musi mieć przypisanego twórcę z portfelem Solana",
        )

    program_id, mint, authority = _escrow_config()
    maker = validate_address(company_wallet)
    creator = validate_address(creator_wallet)
    maker_token = _associated_token_address(maker, mint)
    offer = _campaign_pda(program_id, maker, campaign_id)
    vault = _associated_token_address(offer, mint)
    amount = int(
        Decimal(str(campaign.total_budget))
        * Decimal(10 ** get_settings().solana_bmoney_decimals)
    )
    data = _anchor_discriminator("create_campaign_offer") + campaign_id.to_bytes(8, "little") + amount.to_bytes(8, "little")
    instruction = Instruction(
        program_id,
        data,
        [
            AccountMeta(maker, True, True),
            AccountMeta(creator, False, False),
            AccountMeta(authority, False, False),
            AccountMeta(mint, False, False),
            AccountMeta(maker_token, False, True),
            AccountMeta(offer, False, True),
            AccountMeta(vault, False, True),
            AccountMeta(Pubkey.from_string(TOKEN_PROGRAM_ID), False, False),
            AccountMeta(Pubkey.from_string(SYSTEM_PROGRAM_ID), False, False),
            AccountMeta(Pubkey.from_string(ASSOCIATED_TOKEN_PROGRAM_ID), False, False),
        ],
    )
    return {
        "campaign_id": campaign_id,
        "amount": amount,
        "mint": str(mint),
        "offer": str(offer),
        "vault": str(vault),
        "release_authority": str(authority),
        "instruction": _instruction_payload(instruction),
    }


async def release_campaign_offer(db: AsyncSession, campaign_id: int) -> str:
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")
    creator_result = await db.execute(
        select(Creator)
        .join(CampaignSubmission, CampaignSubmission.creator_id == Creator.id)
        .where(CampaignSubmission.campaign_id == campaign_id)
        .order_by(CampaignSubmission.id.asc())
    )
    creator = creator_result.scalars().first()
    if not creator or not creator.solana_wallet_address:
        raise HTTPException(status_code=400, detail="Brak portfela twórcy")

    program_id, mint, authority = _escrow_config()
    keypair = get_treasury_keypair()
    if keypair.pubkey() != authority:
        raise SolanaServiceError(
            "SOLANA_ESCROW_RELEASE_AUTHORITY musi wskazywać portfel skarbca"
        )
    company = await db.get(Company, campaign.company_id)
    if not company or not company.solana_wallet_address:
        raise HTTPException(status_code=400, detail="Brak portfela firmy")
    maker = validate_address(company.solana_wallet_address)
    creator_key = validate_address(creator.solana_wallet_address)
    offer = _campaign_pda(program_id, maker, campaign_id)
    vault = _associated_token_address(offer, mint)
    creator_token = _associated_token_address(creator_key, mint)
    instruction = Instruction(
        program_id,
        _anchor_discriminator("release_campaign_offer")
        + campaign_id.to_bytes(8, "little"),
        [
            AccountMeta(authority, True, True),
            AccountMeta(creator_key, False, True),
            AccountMeta(mint, False, False),
            AccountMeta(creator_token, False, True),
            AccountMeta(offer, False, True),
            AccountMeta(maker, False, True),
            AccountMeta(vault, False, True),
            AccountMeta(Pubkey.from_string(TOKEN_PROGRAM_ID), False, False),
            AccountMeta(Pubkey.from_string(SYSTEM_PROGRAM_ID), False, False),
            AccountMeta(Pubkey.from_string(ASSOCIATED_TOKEN_PROGRAM_ID), False, False),
        ],
    )
    async with AsyncClient(get_settings().solana_rpc_url) as client:
        blockhash = await client.get_latest_blockhash(commitment=Finalized)
        message = MessageV0.try_compile(
            payer=authority,
            instructions=[instruction],
            address_lookup_table_accounts=[],
            recent_blockhash=blockhash.value.blockhash,
        )
        result = await client.send_transaction(VersionedTransaction(message, [keypair]))
        if not result.value:
            raise SolanaServiceError("RPC Solany nie zwróciło sygnatury escrow")
        confirmation = await client.confirm_transaction(result.value, commitment=Finalized)
        if confirmation.value is False:
            raise SolanaServiceError("Wypłata escrow nie została potwierdzona")
        return str(result.value)
