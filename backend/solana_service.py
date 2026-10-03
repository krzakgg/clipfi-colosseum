import json
import secrets
import time
from dataclasses import dataclass

import base58
from fastapi import HTTPException, status
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.system_program import TransferParams, transfer
from solders.message import Message
from solders.transaction import Transaction

from settings import get_settings

SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
CHALLENGE_TTL_SECONDS = 300
MAX_CHALLENGES = 1000


class SolanaServiceError(Exception):
    """Raised when the configured Solana treasury cannot complete a transfer."""


@dataclass
class WithdrawalChallenge:
    wallet_address: str
    destination: str
    lamports: int
    message: str
    expires_at: int


def _parse_keypair(value: str) -> Keypair:
    try:
        raw = value.strip()
        if raw.startswith("["):
            secret_key = bytes(json.loads(raw))
        else:
            # Solana CLI exports secret keys as base58 strings.
            return Keypair.from_base58_string(raw)
        return Keypair.from_bytes(secret_key)
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
        return Pubkey.from_string(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nieprawidłowy adres portfela Solana",
        ) from exc


def build_withdrawal_message(
    wallet_address: str,
    destination: str,
    lamports: int,
    nonce: str,
) -> str:
    return (
        f"WAGGI withdrawal\n"
        f"wallet: {wallet_address}\n"
        f"destination: {destination}\n"
        f"lamports: {lamports}\n"
        f"nonce: {nonce}"
    )


def create_challenge(
    wallet_address: str,
    destination: str,
    lamports: int,
) -> tuple[str, str, int]:
    wallet = validate_address(wallet_address)
    target = validate_address(destination)
    if str(wallet) != wallet_address or str(target) != destination:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Adres portfela musi być w kanonicznym formacie Base58",
        )

    nonce = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + CHALLENGE_TTL_SECONDS
    message = build_withdrawal_message(wallet_address, destination, lamports, nonce)
    _CHALLENGES[nonce] = WithdrawalChallenge(
        wallet_address=wallet_address,
        destination=destination,
        lamports=lamports,
        message=message,
        expires_at=expires_at,
    )
    if len(_CHALLENGES) > MAX_CHALLENGES:
        oldest_nonce = min(_CHALLENGES, key=lambda key: _CHALLENGES[key].expires_at)
        _CHALLENGES.pop(oldest_nonce, None)
    return nonce, message, expires_at


def verify_challenge(
    wallet_address: str,
    destination: str,
    lamports: int,
    nonce: str,
    signature: str,
) -> WithdrawalChallenge:
    challenge = _CHALLENGES.pop(nonce, None)
    if not challenge or challenge.expires_at < int(time.time()):
        raise HTTPException(status_code=400, detail="Challenge wygasł lub został już użyty")
    if (
        challenge.wallet_address != wallet_address
        or challenge.destination != destination
        or challenge.lamports != lamports
    ):
        raise HTTPException(status_code=400, detail="Dane wypłaty nie pasują do challenge")

    try:
        signature_bytes = base58.b58decode(signature)
        valid = Signature.from_bytes(signature_bytes).verify(
            validate_address(wallet_address),
            challenge.message.encode("utf-8"),
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(status_code=401, detail="Nieprawidłowy podpis portfela")
    return challenge


_CHALLENGES: dict[str, WithdrawalChallenge] = {}


async def withdraw(challenge: WithdrawalChallenge) -> str:
    keypair = get_treasury_keypair()
    client = AsyncClient(get_settings().solana_rpc_url)
    try:
        response = await client.get_latest_blockhash(commitment=Confirmed)
        if not response.value:
            raise SolanaServiceError("Nie udało się pobrać blockhasha Solany")

        instruction = transfer(
            TransferParams(
                from_pubkey=keypair.pubkey(),
                to_pubkey=validate_address(challenge.destination),
                lamports=challenge.lamports,
            )
        )
        transaction = Transaction(
            [keypair],
            Message.new_with_blockhash(
                [instruction],
                keypair.pubkey(),
                response.value.blockhash,
            ),
            response.value.blockhash,
        )
        result = await client.send_transaction(transaction)
        if not result.value:
            raise SolanaServiceError("RPC Solany nie zwróciło sygnatury transakcji")
        confirmation = await client.confirm_transaction(result.value, commitment=Confirmed)
        if confirmation.value is False:
            raise SolanaServiceError("Transakcja wypłaty nie została potwierdzona")
        return str(result.value)
    finally:
        await client.close()


async def get_balance(address: str) -> int:
    client = AsyncClient(get_settings().solana_rpc_url)
    try:
        response = await client.get_balance(validate_address(address), commitment=Confirmed)
        return response.value
    finally:
        await client.close()
