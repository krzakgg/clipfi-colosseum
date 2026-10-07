import base64
import hashlib
import json
import os
import struct
import time
from pathlib import Path

import httpx
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

ROOT = Path(__file__).resolve().parent.parent
KEYS = ROOT / ".keys"
TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ATA_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")
LOADER = Pubkey.from_string("BPFLoaderUpgradeab1e11111111111111111111111")
CLIP = 1_000_000


def load_chain():
    return json.load(open(KEYS / "chain.json"))


def rpc_url(chain):
    if os.getenv("CLIPFI_RPC_SCOPE") == "internal":
        return chain["rpc_url_internal"]
    return chain["rpc_url"]


def waggi_dir():
    return Path(os.getenv("WAGGI_DIR", str(ROOT.parent / "waggi")))


def save_chain(chain):
    json.dump(chain, open(KEYS / "chain.json", "w"), indent=2)


def keypair_from(secret):
    return Keypair.from_bytes(bytes(secret))


class Rpc:
    def __init__(self, url):
        self.url = url
        self.client = httpx.Client(timeout=60)

    def call(self, method, params):
        response = self.client.post(self.url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        body = response.json()
        if "error" in body:
            raise RuntimeError(f"{method}: {body['error']}")
        return body["result"]

    def account(self, pubkey):
        return self.call("getAccountInfo", [str(pubkey), {"encoding": "base64", "commitment": "confirmed"}])["value"]

    def exists(self, pubkey):
        return self.account(pubkey) is not None

    def token_balance(self, token_account):
        if not self.exists(token_account):
            return 0
        return int(self.call("getTokenAccountBalance", [str(token_account), {"commitment": "confirmed"}])["value"]["amount"])

    def lamports(self, pubkey):
        return self.call("getBalance", [str(pubkey), {"commitment": "confirmed"}])["value"]

    def airdrop(self, pubkey, lamports):
        signature = self.call("requestAirdrop", [str(pubkey), lamports])
        self.confirm(signature)
        return signature

    def send(self, instructions, payer, signers):
        blockhash = Hash.from_string(self.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])
        message = Message.new_with_blockhash(instructions, payer.pubkey(), blockhash)
        transaction = VersionedTransaction(message, signers)
        signature = self.call(
            "sendTransaction",
            [base64.b64encode(bytes(transaction)).decode(), {"encoding": "base64", "preflightCommitment": "confirmed"}],
        )
        self.confirm(signature)
        return signature

    def confirm(self, signature, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.call("getSignatureStatuses", [[signature]])["value"][0]
            if status is not None:
                if status.get("err"):
                    raise RuntimeError(f"transaction failed: {status['err']}")
                if status.get("confirmationStatus") in ("confirmed", "finalized"):
                    return
            time.sleep(0.5)
        raise RuntimeError(f"transaction {signature} not confirmed in {timeout}s")


def discriminator(name):
    return hashlib.sha256(f"global:{name}".encode()).digest()[:8]


def pda(seeds, program_id):
    return Pubkey.find_program_address(seeds, program_id)[0]


def ata(owner, mint):
    return pda([bytes(owner), bytes(TOKEN_PROGRAM), bytes(mint)], ATA_PROGRAM)


def config_pda(program_id):
    return pda([b"config"], program_id)


def program_data_pda(program_id):
    return pda([bytes(program_id)], LOADER)


def stake_pda(program_id, creator):
    return pda([b"stake", bytes(creator)], program_id)


def campaign_pda(program_id, brand, campaign_id):
    return pda([b"campaign", bytes(brand), struct.pack("<Q", campaign_id)], program_id)


def create_ata_ix(payer, owner, mint):
    return Instruction(
        ATA_PROGRAM,
        bytes([1]),
        [
            AccountMeta(payer, True, True),
            AccountMeta(ata(owner, mint), False, True),
            AccountMeta(owner, False, False),
            AccountMeta(mint, False, False),
            AccountMeta(SYSTEM_PROGRAM, False, False),
            AccountMeta(TOKEN_PROGRAM, False, False),
        ],
    )


def token_transfer_ix(owner, source, destination, amount):
    return Instruction(
        TOKEN_PROGRAM,
        bytes([3]) + struct.pack("<Q", amount),
        [
            AccountMeta(source, False, True),
            AccountMeta(destination, False, True),
            AccountMeta(owner, True, False),
        ],
    )


def sol_transfer_ix(sender, recipient, lamports):
    return Instruction(
        SYSTEM_PROGRAM,
        struct.pack("<IQ", 2, lamports),
        [AccountMeta(sender, True, True), AccountMeta(recipient, False, True)],
    )


def instruction_from_json(item):
    return Instruction(
        Pubkey.from_string(item["program_id"]),
        base64.b64decode(item["data"]),
        [AccountMeta(Pubkey.from_string(a["pubkey"]), a["is_signer"], a["is_writable"]) for a in item["accounts"]],
    )


def encode_config_params(oracle, arbiter, vesting, bonded, cooldown, notice, tiers):
    body = bytes(oracle) + bytes(arbiter) + struct.pack("<qqqq", vesting, bonded, cooldown, notice)
    for min_bond, bonus_bps in tiers:
        body += struct.pack("<QH", min_bond, bonus_bps)
    return body
