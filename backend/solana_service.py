import json
import secrets
import base64
import hashlib
from struct import error as struct_error
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

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

from solana.rpc.types import TxOpts, MemcmpOpts

from clipfi_escrow import (
    ASSOCIATED_TOKEN_PROGRAM_ID as _ASSOCIATED_TOKEN_PROGRAM,
    SYSTEM_PROGRAM_ID as _SYSTEM_PROGRAM,
    TOKEN_PROGRAM_ID as _TOKEN_PROGRAM,
    IdlError,
    IdlProgram,
    account_field_offset,
    associated_token_address,
    resolve_idl_path,
)
from models import (
    Campaign,
    CampaignRefLink,
    Company,
    Creator,
    SolanaDeposit,
    SolanaWithdrawal,
    SolanaWithdrawalChallenge,
)
from settings import get_settings
from tracking_client import TrackingClient, TrackingError

SYSTEM_PROGRAM_ID = str(_SYSTEM_PROGRAM)
TOKEN_PROGRAM_ID = str(_TOKEN_PROGRAM)
ASSOCIATED_TOKEN_PROGRAM_ID = str(_ASSOCIATED_TOKEN_PROGRAM)
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
    fee_lamports: int
    total_internal_amount: Decimal


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
    wallet_address: str, destination: str, lamports: int, fee_lamports: int, nonce: str
) -> str:
    return (
        "WAGGI withdrawal\n"
        f"wallet: {wallet_address}\n"
        f"destination: {destination}\n"
        f"lamports: {lamports}\n"
        f"fee_lamports: {fee_lamports}\n"
        f"nonce: {nonce}"
    )


def fee_bps_for(account_type: str, operation: str) -> int:
    settings = get_settings()
    if account_type == "company" and operation == "deposit":
        return settings.solana_company_deposit_fee_bps
    if account_type == "creator" and operation == "deposit":
        return 0
    if account_type == "company":
        return settings.solana_company_withdrawal_fee_bps
    if account_type == "creator" and operation == "withdrawal":
        return settings.solana_creator_withdrawal_fee_bps
    raise ValueError("Nieprawidłowy typ konta lub operacja prowizji")


def calculate_fee(lamports: int, fee_bps: int) -> int:
    return (lamports * fee_bps + 9_999) // 10_000


def internal_amount_for_lamports(lamports: int) -> Decimal:
    return (
        Decimal(lamports)
        / Decimal(1_000_000_000)
        * Decimal(str(get_settings().solana_internal_currency_per_sol))
    )


async def create_challenge(
    db: AsyncSession,
    wallet_address: str,
    account_type: str,
    account_id: int,
    lamports: int,
    destination_wallet_address: str,
) -> WithdrawalChallenge:
    validate_address(wallet_address)
    destination = str(validate_address(destination_wallet_address))
    await get_account(db, account_type, account_id)
    settings = get_settings()
    if lamports > settings.solana_max_withdrawal_lamports:
        raise HTTPException(status_code=400, detail="Przekroczono limit pojedynczej wypłaty")

    nonce = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=CHALLENGE_TTL_SECONDS)
    fee_lamports = calculate_fee(lamports, fee_bps_for(account_type, "withdrawal"))
    total_internal_amount = internal_amount_for_lamports(lamports + fee_lamports)
    message = build_withdrawal_message(
        wallet_address, destination, lamports, fee_lamports, nonce
    )
    db.add(
        SolanaWithdrawalChallenge(
            nonce=nonce,
            wallet_address=wallet_address,
            destination=destination,
            lamports=lamports,
            fee_lamports=fee_lamports,
            message=message,
            expires_at=expires_at,
        )
    )
    await db.commit()
    return WithdrawalChallenge(
        nonce, wallet_address, destination, lamports, message, int(expires_at.timestamp()),
        account_type, account_id, fee_lamports, total_internal_amount
    )


async def verify_challenge(
    db: AsyncSession,
    wallet_address: str,
    account_type: str,
    account_id: int,
    lamports: int,
    nonce: str,
    signature: str,
    destination_wallet_address: str,
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
        destination = str(validate_address(destination_wallet_address))
        fee_lamports = record.fee_lamports
        total_internal_amount = internal_amount_for_lamports(lamports + fee_lamports)
        if (
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

        current_balance = Decimal(str(account.internal_balance or 0))
        if current_balance < total_internal_amount:
            raise HTTPException(status_code=400, detail="Niewystarczające saldo waluty wewnętrznej")
        account.internal_balance = current_balance - total_internal_amount
        record.used_at = now
        withdrawal = SolanaWithdrawal(
            nonce=nonce,
            wallet_address=wallet_address,
            destination=destination,
            lamports=lamports,
            internal_amount=total_internal_amount,
            fee_lamports=fee_lamports,
            fee_internal_amount=internal_amount_for_lamports(fee_lamports),
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
            , fee_lamports, total_internal_amount
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
    db: AsyncSession, account_type: str, account_id: int, wallet_address: str,
    signature: str | None = None,
) -> str:
    address = validate_address(wallet_address)
    account = await get_account(db, account_type, account_id)
    message = (
        f"WAGGI wallet verification\naccount_type: {account_type}\n"
        f"account_id: {account_id}\nwallet_address: {wallet_address}"
    )
    if account.solana_wallet_address != wallet_address:
        if not signature:
            raise HTTPException(
                status_code=400,
                detail="Nowy portfel wymaga podpisania wiadomości w tym portfelu",
            )
        try:
            valid = Signature.from_bytes(base58.b58decode(signature)).verify(
                address, message.encode("utf-8")
            )
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise HTTPException(status_code=401, detail="Nieprawidłowy podpis portfela")
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

        fee_lamports = calculate_fee(
            amount, fee_bps_for(account_type, "deposit")
        )
        credited_lamports = amount - fee_lamports
        internal_amount = internal_amount_for_lamports(credited_lamports)
        account.internal_balance = Decimal(str(account.internal_balance or 0)) + internal_amount
        db.add(
            SolanaDeposit(
                signature=signature,
                account_type=account_type,
                account_id=account_id,
                wallet_address=wallet_address,
                lamports=amount,
                fee_lamports=fee_lamports,
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
            instructions = [instruction]
            fee_wallet = (
                get_settings().solana_platform_fee_wallet_address
                or get_settings().solana_treasury_address
                or str(keypair.pubkey())
            )
            if challenge.fee_lamports and fee_wallet != str(keypair.pubkey()):
                instructions.append(
                    transfer(
                        TransferParams(
                            from_pubkey=keypair.pubkey(),
                            to_pubkey=validate_address(fee_wallet),
                            lamports=challenge.fee_lamports,
                        )
                    )
                )
            message = MessageV0.try_compile(
                payer=keypair.pubkey(),
                instructions=instructions,
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


_program_cache: dict[tuple[str, float, str], IdlProgram] = {}


@dataclass(frozen=True)
class EscrowContext:
    program: IdlProgram
    mint: Pubkey
    config: Pubkey
    bonus_vault: Pubkey
    brand: Pubkey
    campaign: Pubkey
    vault: Pubkey

    def brand_token(self) -> Pubkey:
        return associated_token_address(self.brand, self.mint)

    def creator_token(self, creator: Pubkey) -> Pubkey:
        return associated_token_address(creator, self.mint)

    def stake_token(self, stake: Pubkey) -> Pubkey:
        return associated_token_address(stake, self.mint)


def escrow_program() -> IdlProgram:
    settings = get_settings()
    try:
        path = resolve_idl_path(settings.solana_escrow_idl_path or None)
    except IdlError as exc:
        raise SolanaServiceError(str(exc)) from exc
    key = (str(path), path.stat().st_mtime, settings.solana_escrow_program_id)
    program = _program_cache.get(key)
    if program is None:
        try:
            program = IdlProgram.load(path, settings.solana_escrow_program_id or None)
        except (OSError, ValueError, KeyError, IdlError) as exc:
            raise SolanaServiceError(f"Nie można wczytać IDL clipfi_escrow: {exc}") from exc
        _program_cache.clear()
        _program_cache[key] = program
    return program


def clipusd_mint() -> Pubkey:
    settings = get_settings()
    if not settings.solana_bmoney_mint:
        raise SolanaServiceError("Escrow wymaga SOLANA_BMONEY_MINT")
    return validate_address(settings.solana_bmoney_mint)


def token_units(amount: Decimal | str | int) -> int:
    scale = Decimal(10) ** get_settings().solana_bmoney_decimals
    scaled = (Decimal(str(amount)) * scale).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if scaled < 0:
        raise HTTPException(status_code=400, detail="Kwota nie może być ujemna")
    return int(scaled)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def rate_per_mille_from_campaign(campaign: Campaign) -> list[int]:
    scale = Decimal(10) ** get_settings().solana_bmoney_decimals
    views = Decimal(0)
    if campaign.payout_per_views is not None:
        step = Decimal(campaign.views_unit_step or 1000)
        views = (Decimal(str(campaign.payout_per_views)) * Decimal(1000) / step * scale).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
    clicks = Decimal(0)
    if campaign.payout_per_click is not None:
        clicks = (Decimal(str(campaign.payout_per_click)) * Decimal(1000) * scale).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
    return [int(views), int(views), 0, int(clicks)]


def campaign_chain_params(campaign: Campaign, min_bond: Decimal | str | int = 0) -> dict:
    now = datetime.now(timezone.utc)
    start = _utc(campaign.start_date) if campaign.start_date else now
    end = _utc(campaign.end_date) if campaign.end_date else now + timedelta(days=30)
    per_creator = campaign.budget_per_creator
    if per_creator is None:
        per_creator = campaign.total_budget or 0
    return {
        "rate_per_mille": rate_per_mille_from_campaign(campaign),
        "max_per_creator": token_units(Decimal(str(per_creator))),
        "min_bond": token_units(min_bond),
        "start_ts": int(start.timestamp()),
        "end_ts": int(end.timestamp()),
        "standards_hash": list(hashlib.sha256((campaign.brand_guidelines or "").encode("utf-8")).digest()),
    }


def escrow_context(brand: Pubkey, campaign_id: int) -> EscrowContext:
    program = escrow_program()
    mint = clipusd_mint()
    config = program.config_pda()
    campaign = program.campaign_pda(brand, campaign_id)
    return EscrowContext(
        program=program,
        mint=mint,
        config=config,
        bonus_vault=associated_token_address(config, mint),
        brand=brand,
        campaign=campaign,
        vault=associated_token_address(campaign, mint),
    )


def escrow_config_view() -> dict:
    settings = get_settings()
    view = {
        "escrow_program_id": settings.solana_escrow_program_id,
        "clipusd_mint": settings.solana_bmoney_mint,
        "bonus_vault": "",
    }
    try:
        program = escrow_program()
        view["escrow_program_id"] = str(program.program_id)
        if settings.solana_bmoney_mint:
            view["bonus_vault"] = str(associated_token_address(program.config_pda(), clipusd_mint()))
    except (SolanaServiceError, HTTPException):
        pass
    return view


def oracle_token_valid(token: str | None) -> bool:
    expected = get_settings().solana_oracle_token.get_secret_value()
    return bool(expected and token) and secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))


def require_oracle_token(token: str | None) -> None:
    if not oracle_token_valid(token):
        raise HTTPException(status_code=403, detail="Nieprawidłowy token wyroczni")


def build_release_message(campaign_id: int, epoch: int, wallet_address: str) -> str:
    return f"WAGGI release\ncampaign_id: {campaign_id}\nepoch: {epoch}\nwallet_address: {wallet_address}"


def release_signature_valid(campaign_id: int, epoch: int, wallet_address: str, signature: str | None) -> bool:
    if not signature:
        return False
    try:
        return Signature.from_bytes(base58.b58decode(signature)).verify(
            validate_address(wallet_address), build_release_message(campaign_id, epoch, wallet_address).encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


_RPC_ERRORS = (
    OSError,
    RuntimeError,
    ValueError,
    SolanaRpcException,
    RPCException,
    RPCNoResultException,
    TransactionExpiredBlockheightExceededError,
    UnconfirmedTxError,
)


async def rpc_account_data(address: Pubkey) -> bytes | None:
    try:
        async with AsyncClient(get_settings().solana_rpc_url) as client:
            response = await client.get_account_info(address, commitment=Confirmed, encoding="base64")
    except _RPC_ERRORS as exc:
        raise SolanaServiceError(f"RPC Solany nie odpowiada: {exc}") from exc
    if response.value is None:
        return None
    return bytes(response.value.data)


async def rpc_program_accounts(program_id: Pubkey, filters: list[MemcmpOpts]) -> list[tuple[str, bytes]]:
    try:
        async with AsyncClient(get_settings().solana_rpc_url) as client:
            response = await client.get_program_accounts(
                program_id, commitment=Confirmed, encoding="base64", filters=filters
            )
    except (RPCException, RPCNoResultException):
        return []
    except _RPC_ERRORS as exc:
        raise SolanaServiceError(f"RPC Solany nie odpowiada: {exc}") from exc
    return [(str(item.pubkey), bytes(item.account.data)) for item in response.value or []]


async def read_account(name: str, address: Pubkey) -> dict | None:
    data = await rpc_account_data(address)
    if data is None:
        return None
    try:
        return escrow_program().decode_account(name, data)
    except (IdlError, struct_error) as exc:
        raise SolanaServiceError(f"Nie można zdekodować konta {name}: {exc}") from exc


async def send_instructions(keypair: Keypair, instructions: list[Instruction]) -> str:
    try:
        async with AsyncClient(get_settings().solana_rpc_url) as client:
            blockhash = await client.get_latest_blockhash(commitment=Finalized)
            if not blockhash.value:
                raise SolanaServiceError("Nie udało się pobrać blockhasha Solany")
            message = MessageV0.try_compile(
                payer=keypair.pubkey(),
                instructions=instructions,
                address_lookup_table_accounts=[],
                recent_blockhash=blockhash.value.blockhash,
            )
            result = await client.send_transaction(
                VersionedTransaction(message, [keypair]), opts=TxOpts(preflight_commitment=Confirmed)
            )
            if not result.value:
                raise SolanaServiceError("RPC Solany nie zwróciło sygnatury transakcji")
            confirmation = await client.confirm_transaction(result.value, commitment=Confirmed)
            statuses = confirmation.value if isinstance(confirmation.value, list) else []
            if statuses and statuses[0] is not None and getattr(statuses[0], "err", None):
                raise SolanaServiceError(f"Transakcja odrzucona: {statuses[0].err}")
            return str(result.value)
    except SolanaServiceError:
        raise
    except _RPC_ERRORS as exc:
        raise SolanaServiceError(f"Nie udało się wysłać transakcji: {exc}") from exc


async def _campaign_with_brand(db: AsyncSession, campaign_id: int) -> tuple[Campaign, Company, Pubkey]:
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")
    company = await db.get(Company, campaign.company_id)
    if not company or not company.solana_wallet_address:
        raise HTTPException(status_code=400, detail="Firma nie ma zweryfikowanego portfela Solana")
    return campaign, company, validate_address(company.solana_wallet_address)


def _require_company_wallet(company: Company, company_wallet: str) -> None:
    if company.solana_wallet_address != company_wallet:
        raise HTTPException(status_code=403, detail="Portfel nie należy do firmy kampanii")


def _common_accounts(ctx: EscrowContext) -> dict:
    return {
        "config": ctx.config,
        "mint": ctx.mint,
        "campaign": ctx.campaign,
        "vault": ctx.vault,
        "bonus_vault": ctx.bonus_vault,
        "token_program": _TOKEN_PROGRAM,
        "associated_token_program": _ASSOCIATED_TOKEN_PROGRAM,
        "system_program": _SYSTEM_PROGRAM,
    }


def _enum_name(value) -> str:
    if isinstance(value, dict):
        return next(iter(value))
    return str(value)


def _campaign_view(account: dict) -> dict:
    return {
        "brand": account["brand"],
        "campaign_id": int(account["campaign_id"]),
        "mint": account["mint"],
        "vault": account["vault"],
        "funded_total": str(account["funded_total"]),
        "reserved": str(account["reserved"]),
        "paid_total": str(account["paid_total"]),
        "rate_per_mille": [str(rate) for rate in account["rate_per_mille"]],
        "pending_rates": [str(rate) for rate in account.get("pending_rates", [])],
        "pending_rates_at": int(account.get("pending_rates_at", 0)),
        "max_per_creator": str(account["max_per_creator"]),
        "min_bond": str(account["min_bond"]),
        "start_ts": int(account["start_ts"]),
        "end_ts": int(account["end_ts"]),
        "standards_hash": bytes(account["standards_hash"]).hex(),
        "standards_version": int(account["standards_version"]),
        "status": _enum_name(account["status"]),
    }


def _payout_view(address: str, payout: dict) -> dict:
    return {
        "address": address,
        "campaign": payout["campaign"],
        "creator": payout["creator"],
        "epoch": int(payout["epoch"]),
        "units": [str(unit) for unit in payout["units"]],
        "amount": str(payout["amount"]),
        "bonus_bps": int(payout["bonus_bps"]),
        "restake_bps": int(payout.get("restake_bps", 0) or 0),
        "standards_version": int(payout["standards_version"]),
        "evidence_hash": bytes(payout["evidence_hash"]).hex(),
        "unlock_ts": int(payout["unlock_ts"]),
        "status": _enum_name(payout["status"]),
        "rent_payer": payout["rent_payer"],
    }


async def build_escrow_funding_instructions(
    db: AsyncSession, campaign_id: int, company_wallet: str, amount: Decimal, min_bond: Decimal = Decimal(0)
) -> dict:
    campaign, company, brand = await _campaign_with_brand(db, campaign_id)
    _require_company_wallet(company, company_wallet)
    units = token_units(amount)
    if units <= 0:
        raise HTTPException(status_code=400, detail="Kwota zasilenia musi być dodatnia")
    ctx = escrow_context(brand, campaign_id)
    accounts = {**_common_accounts(ctx), "brand": brand, "brand_token": ctx.brand_token()}
    instructions = []
    if await read_account("Campaign", ctx.campaign) is None:
        instructions.append(
            ctx.program.build(
                "create_campaign",
                {"campaign_id": campaign_id, "params": campaign_chain_params(campaign, min_bond)},
                accounts,
            )
        )
    instructions.append(ctx.program.build("fund_campaign", {"amount": units}, accounts))
    return {
        "instructions": instructions,
        "campaign_pda": str(ctx.campaign),
        "vault": str(ctx.vault),
        "mint": str(ctx.mint),
        "amount": units,
    }


async def get_escrow_campaign(db: AsyncSession, campaign_id: int) -> dict:
    _, _, brand = await _campaign_with_brand(db, campaign_id)
    ctx = escrow_context(brand, campaign_id)
    account = await read_account("Campaign", ctx.campaign)
    return {
        "exists": account is not None,
        "campaign_pda": str(ctx.campaign),
        "vault": str(ctx.vault),
        "campaign": _campaign_view(account) if account else None,
    }


async def _units_from_tracking(
    db: AsyncSession, campaign_id: int, wallet_address: str, tracking: TrackingClient | None
) -> list[int]:
    if tracking is None:
        raise HTTPException(status_code=400, detail="Podaj units; serwis śledzenia nie jest dostępny")
    creator = await db.scalar(select(Creator).where(Creator.solana_wallet_address == wallet_address))
    if not creator:
        raise HTTPException(status_code=400, detail="Brak twórcy z tym portfelem Solana")
    link = await db.scalar(
        select(CampaignRefLink).where(
            CampaignRefLink.campaign_id == campaign_id, CampaignRefLink.creator_id == creator.id
        )
    )
    if not link:
        raise HTTPException(status_code=400, detail="Twórca nie ma reflinku w tej kampanii; podaj units")
    try:
        totals = await tracking.link_totals(link.code)
    except TrackingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if totals is None:
        raise HTTPException(status_code=400, detail="Serwis śledzenia nie zna reflinku; podaj units")
    return [0, 0, 0, int(totals.unique)]


async def settle_payout(
    db: AsyncSession,
    campaign_id: int,
    wallet_address: str,
    epoch: int,
    units: list[int] | None,
    evidence_hash: str,
    tracking: TrackingClient | None = None,
) -> dict:
    _, _, brand = await _campaign_with_brand(db, campaign_id)
    creator = validate_address(wallet_address)
    if units is None:
        units = await _units_from_tracking(db, campaign_id, wallet_address, tracking)
    if len(units) != 4 or any(unit < 0 for unit in units):
        raise HTTPException(status_code=400, detail="units musi mieć 4 nieujemne wartości")
    ctx = escrow_context(brand, campaign_id)
    keypair = get_treasury_keypair()
    payout = ctx.program.payout_pda(ctx.campaign, creator, epoch)
    instruction = ctx.program.instruction(
        "settle",
        {"epoch": epoch, "units": [int(unit) for unit in units], "evidence_hash": bytes.fromhex(evidence_hash)},
        {
            **_common_accounts(ctx),
            "oracle": keypair.pubkey(),
            "creator": creator,
            "stake": ctx.program.stake_pda(creator),
            "position": ctx.program.position_pda(ctx.campaign, creator),
            "payout": payout,
        },
    )
    signature = await send_instructions(keypair, [instruction])
    return {"signature": signature, "payout_pda": str(payout), "units": units}


def build_release_instruction(
    ctx: EscrowContext, creator: Pubkey, epoch: int, payout: dict, stake_exists: bool, cranker: Pubkey
) -> Instruction:
    with_stake = int(payout.get("restake_bps", 0) or 0) > 0 or stake_exists
    stake = ctx.program.stake_pda(creator) if with_stake else None
    return ctx.program.instruction(
        "release",
        {},
        {
            **_common_accounts(ctx),
            "cranker": cranker,
            "creator": creator,
            "creator_token": ctx.creator_token(creator),
            "position": ctx.program.position_pda(ctx.campaign, creator),
            "payout": ctx.program.payout_pda(ctx.campaign, creator, epoch),
            "rent_payer": payout["rent_payer"],
            "stake": stake,
            "stake_token": ctx.stake_token(stake) if stake else None,
        },
    )


async def release_payout(
    db: AsyncSession,
    campaign_id: int,
    wallet_address: str,
    epoch: int,
    oracle_token: str | None = None,
    signature: str | None = None,
) -> dict:
    creator = validate_address(wallet_address)
    if not oracle_token_valid(oracle_token) and not release_signature_valid(campaign_id, epoch, wallet_address, signature):
        raise HTTPException(status_code=403, detail="Wymagany token wyroczni lub podpis twórcy wiadomości release")
    _, _, brand = await _campaign_with_brand(db, campaign_id)
    ctx = escrow_context(brand, campaign_id)
    payout_pda = ctx.program.payout_pda(ctx.campaign, creator, epoch)
    payout = await read_account("Payout", payout_pda)
    if payout is None:
        raise HTTPException(status_code=409, detail="Brak rozliczenia na łańcuchu dla tej epoki")
    if _enum_name(payout["status"]) == "Flagged":
        raise HTTPException(status_code=409, detail="Rozliczenie jest oflagowane przez markę i czeka na arbitra")
    now = int(datetime.now(timezone.utc).timestamp())
    if int(payout["unlock_ts"]) > now:
        raise HTTPException(status_code=409, detail=f"Rozliczenie odblokuje się o {int(payout['unlock_ts'])} (vesting)")
    stake_exists = await rpc_account_data(ctx.program.stake_pda(creator)) is not None
    keypair = get_treasury_keypair()
    instruction = build_release_instruction(ctx, creator, epoch, payout, stake_exists, keypair.pubkey())
    signature = await send_instructions(keypair, [instruction])
    return {"signature": signature, "payout_pda": str(payout_pda)}


async def build_flag_instruction(
    db: AsyncSession, campaign_id: int, company_wallet: str, wallet_address: str, epoch: int, reason: int
) -> dict:
    _, company, brand = await _campaign_with_brand(db, campaign_id)
    _require_company_wallet(company, company_wallet)
    creator = validate_address(wallet_address)
    ctx = escrow_context(brand, campaign_id)
    payout = ctx.program.payout_pda(ctx.campaign, creator, epoch)
    instruction = ctx.program.build(
        "flag_payout", {"reason": reason}, {**_common_accounts(ctx), "brand": brand, "payout": payout}
    )
    return {"instructions": [instruction], "payout_pda": str(payout)}


async def resolve_payout(
    db: AsyncSession,
    campaign_id: int,
    wallet_address: str,
    epoch: int,
    approve: bool,
    slash_amount: Decimal = Decimal(0),
) -> dict:
    _, _, brand = await _campaign_with_brand(db, campaign_id)
    creator = validate_address(wallet_address)
    ctx = escrow_context(brand, campaign_id)
    payout_pda = ctx.program.payout_pda(ctx.campaign, creator, epoch)
    payout = await read_account("Payout", payout_pda)
    if payout is None:
        raise HTTPException(status_code=404, detail="Brak rozliczenia na łańcuchu dla tej epoki")
    keypair = get_treasury_keypair()
    base = {**_common_accounts(ctx), "arbiter": keypair.pubkey(), "creator": creator}
    instructions = [
        ctx.program.instruction(
            "resolve",
            {"approve": approve},
            {
                **base,
                "position": ctx.program.position_pda(ctx.campaign, creator),
                "payout": payout_pda,
                "rent_payer": payout["rent_payer"],
            },
        )
    ]
    slash_units = token_units(slash_amount)
    if slash_units > 0:
        stake = ctx.program.stake_pda(creator)
        instructions.append(
            ctx.program.instruction(
                "slash", {"amount": slash_units}, {**base, "stake": stake, "stake_token": ctx.stake_token(stake)}
            )
        )
    signature = await send_instructions(keypair, instructions)
    return {"signature": signature, "payout_pda": str(payout_pda), "slashed": slash_units}


async def build_close_instruction(db: AsyncSession, campaign_id: int, company_wallet: str) -> dict:
    _, company, brand = await _campaign_with_brand(db, campaign_id)
    _require_company_wallet(company, company_wallet)
    ctx = escrow_context(brand, campaign_id)
    instruction = ctx.program.build(
        "close_campaign", {}, {**_common_accounts(ctx), "brand": brand, "brand_token": ctx.brand_token()}
    )
    return {"instructions": [instruction], "campaign_pda": str(ctx.campaign), "vault": str(ctx.vault)}


async def build_rollover_instruction(
    db: AsyncSession, campaign_id: int, company_wallet: str, target_campaign_id: int
) -> dict:
    campaign, company, brand = await _campaign_with_brand(db, campaign_id)
    _require_company_wallet(company, company_wallet)
    target = await db.get(Campaign, target_campaign_id)
    if not target or target.company_id != campaign.company_id:
        raise HTTPException(status_code=404, detail="Kampania docelowa nie istnieje lub należy do innej firmy")
    ctx = escrow_context(brand, campaign_id)
    target_campaign = ctx.program.campaign_pda(brand, target_campaign_id)
    target_vault = associated_token_address(target_campaign, ctx.mint)
    instruction = ctx.program.build(
        "rollover",
        {},
        {**_common_accounts(ctx), "brand": brand, "target_campaign": target_campaign, "target_vault": target_vault},
    )
    return {
        "instructions": [instruction],
        "campaign_pda": str(ctx.campaign),
        "target_campaign_pda": str(target_campaign),
        "target_vault": str(target_vault),
    }


async def list_payouts(db: AsyncSession, campaign_id: int, wallet_address: str) -> list[dict]:
    _, _, brand = await _campaign_with_brand(db, campaign_id)
    creator = validate_address(wallet_address)
    ctx = escrow_context(brand, campaign_id)
    program = ctx.program
    filters = [
        MemcmpOpts(offset=0, bytes=base58.b58encode(program.account_discriminator("Payout")).decode("ascii")),
        MemcmpOpts(
            offset=account_field_offset(program, "Payout", "campaign"),
            bytes=base58.b58encode(bytes(ctx.campaign)).decode("ascii"),
        ),
        MemcmpOpts(
            offset=account_field_offset(program, "Payout", "creator"),
            bytes=base58.b58encode(bytes(creator)).decode("ascii"),
        ),
    ]
    rows = await rpc_program_accounts(program.program_id, filters)
    payouts = []
    for address, data in rows:
        try:
            payouts.append(_payout_view(address, program.decode_account("Payout", data)))
        except (IdlError, struct_error):
            continue
    payouts.sort(key=lambda item: item["epoch"])
    return payouts


def build_stake_instruction(
    wallet_address: str, action: str, amount: Decimal | None = None, bps: int | None = None
) -> dict:
    creator = validate_address(wallet_address)
    program = escrow_program()
    mint = clipusd_mint()
    stake = program.stake_pda(creator)
    stake_token = associated_token_address(stake, mint)
    accounts = {
        "creator": creator,
        "config": program.config_pda(),
        "mint": mint,
        "stake": stake,
        "stake_token": stake_token,
        "creator_token": associated_token_address(creator, mint),
        "token_program": _TOKEN_PROGRAM,
        "associated_token_program": _ASSOCIATED_TOKEN_PROGRAM,
        "system_program": _SYSTEM_PROGRAM,
    }
    if action in ("stake", "request_unstake"):
        if amount is None:
            raise HTTPException(status_code=400, detail="Akcja wymaga pola amount")
        units = token_units(amount)
        if units <= 0:
            raise HTTPException(status_code=400, detail="Kwota musi być dodatnia")
        instruction = program.build(action, {"amount": units}, accounts)
    elif action == "withdraw_stake":
        instruction = program.build(action, {}, accounts)
    elif action == "set_auto_restake":
        if bps is None:
            raise HTTPException(status_code=400, detail="Akcja wymaga pola bps")
        instruction = program.build(action, {"bps": bps}, accounts)
    else:
        raise HTTPException(status_code=422, detail="Nieznana akcja stake")
    return {"instructions": [instruction], "stake_pda": str(stake), "stake_token": str(stake_token)}


async def get_stake(wallet_address: str) -> dict:
    creator = validate_address(wallet_address)
    program = escrow_program()
    stake = program.stake_pda(creator)
    account = await read_account("Stake", stake)
    if account is None:
        return {
            "exists": False,
            "stake_pda": str(stake),
            "amount": "0",
            "pending_unstake": "0",
            "unstake_at": 0,
            "auto_restake_bps": 0,
            "slashed_total": "0",
        }
    return {
        "exists": True,
        "stake_pda": str(stake),
        "token": account["token"],
        "amount": str(account["amount"]),
        "pending_unstake": str(account["pending_unstake"]),
        "unstake_at": int(account["unstake_at"]),
        "auto_restake_bps": int(account["auto_restake_bps"]),
        "slashed_total": str(account["slashed_total"]),
    }
