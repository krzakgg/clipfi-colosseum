import hashlib
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import base58
import httpx
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from chain_common import (
    CLIP,
    Rpc,
    ata,
    create_ata_ix,
    instruction_from_json,
    keypair_from,
    load_chain,
    rpc_url,
    sol_transfer_ix,
    token_transfer_ix,
    waggi_dir,
)

BACKEND = os.getenv("CLIPFI_BACKEND_URL", "http://localhost:8000")
UNITS = [10_000, 0, 0, 0]
STEP = 0


def step(text):
    global STEP
    STEP += 1
    print(f"\n[{STEP}] {text}", flush=True)


def check(condition, text):
    print(f"    {'ok' if condition else 'FAIL'}: {text}", flush=True)
    if not condition:
        sys.exit(1)


def oracle_token():
    value = os.getenv("CLIPFI_ORACLE_TOKEN")
    if value:
        return value
    for line in (waggi_dir() / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("SOLANA_ORACLE_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("SOLANA_ORACLE_TOKEN not found, run setup first")


def sign(keypair, message):
    return base58.b58encode(bytes(keypair.sign_message(message.encode()))).decode()


def main():
    chain = load_chain()
    rpc = Rpc(rpc_url(chain))
    api = httpx.Client(base_url=BACKEND, timeout=90)
    token = oracle_token()
    program = chain["program_id"]
    mint = Pubkey.from_string(chain["mint"])
    brand = keypair_from(chain["deployer_secret"])
    creator = Keypair()
    tag = int(time.time())

    def post(path, body, expect=200, headers=None):
        response = api.post(path, json=body, headers=headers or {})
        if response.status_code != expect:
            print(f"    {path} -> {response.status_code} {response.text[:300]}")
            sys.exit(1)
        return response.json()

    def get(path, expect=200):
        response = api.get(path)
        if response.status_code != expect:
            print(f"    {path} -> {response.status_code} {response.text[:300]}")
            sys.exit(1)
        return response.json()

    step(f"backend {BACKEND} is configured for program {program}")
    config = get("/api/solana/config")
    check(config["escrow_program_id"] == program, f"escrow_program_id {config['escrow_program_id']}")
    check(config["clipusd_mint"] == str(mint), f"clipusd_mint {config['clipusd_mint']}")
    print(f"    cluster {config['cluster']} rpc {config['rpc_url']} treasury {config['treasury_address']} bonus vault {config['bonus_vault']}")

    step(f"creator wallet {creator.pubkey()} gets SOL for rent and 200 clipUSD from the treasury")
    if chain["cluster"] == "localnet":
        rpc.airdrop(creator.pubkey(), 2_000_000_000)
    else:
        rpc.send([sol_transfer_ix(brand.pubkey(), creator.pubkey(), 50_000_000)], brand, [brand])
    rpc.send(
        [
            create_ata_ix(brand.pubkey(), creator.pubkey(), mint),
            token_transfer_ix(brand.pubkey(), ata(brand.pubkey(), mint), ata(creator.pubkey(), mint), 200 * CLIP),
        ],
        brand,
        [brand],
    )
    check(rpc.token_balance(ata(creator.pubkey(), mint)) == 200 * CLIP, "creator holds 200 clipUSD")

    step("register a company and a creator through the waggi API")
    company = post("/api/companies", {"name": f"E2E Brand {tag}", "email": f"brand-{tag}@example.com", "password": "e2epassword1"}, 201)
    person = post("/api/creators", {"username": f"e2ecreator{tag}", "full_name": "E2E Creator", "email": f"creator-{tag}@example.com", "password": "e2epassword1"}, 201)
    print(f"    company id {company['id']}, creator id {person['id']}")

    step("both verify their Solana wallets with a signed message")
    for account_type, account_id, keypair in (("company", company["id"], brand), ("creator", person["id"], creator)):
        wallet = str(keypair.pubkey())
        message = f"WAGGI wallet verification\naccount_type: {account_type}\naccount_id: {account_id}\nwallet_address: {wallet}"
        post("/api/solana/wallet", {"account_type": account_type, "account_id": account_id, "wallet_address": wallet, "signature": sign(keypair, message)})
        account = get(f"/api/solana/account/{account_type}/{account_id}")
        check(account["wallet_address"] == wallet, f"{account_type} wallet {wallet}")

    step("the company creates a campaign: 2.00 clipUSD per 1000 views, 100 per creator")
    now = datetime.now(timezone.utc)
    campaign = post(
        "/api/campaigns",
        {
            "company_id": company["id"],
            "title": f"E2E campaign {tag}",
            "description": "end to end run",
            "total_budget": "1000",
            "budget_per_creator": "100",
            "payout_per_views": "2.00",
            "views_unit_step": 1000,
            "payout_per_click": "0.05",
            "brand_guidelines": "say the name in the first 5 seconds",
            "start_date": now.isoformat(),
            "end_date": (now + timedelta(days=30)).isoformat(),
        },
        201,
    )
    campaign_id = campaign["id"]
    print(f"    campaign id {campaign_id}")

    step("funding-instruction: the brand signs create_campaign + fund_campaign for 500 clipUSD")
    funding = post(f"/api/solana/campaign/{campaign_id}/escrow/funding-instruction", {"company_wallet": str(brand.pubkey()), "amount": "500", "min_bond": "0"})
    check(len(funding["instructions"]) == 2, f"{len(funding['instructions'])} instructions returned")
    signature = rpc.send([instruction_from_json(i) for i in funding["instructions"]], brand, [brand])
    print(f"    sent {signature}")
    escrow = get(f"/api/solana/campaign/{campaign_id}/escrow")
    check(escrow["exists"], f"campaign account {escrow['campaign_pda']} exists")
    check(int(escrow["campaign"]["funded_total"]) == 500 * CLIP, f"funded_total {escrow['campaign']['funded_total']}")
    check(list(map(int, escrow["campaign"]["rate_per_mille"]))[0] == 2 * CLIP, f"rate_per_mille {escrow['campaign']['rate_per_mille']}")

    step("the creator bonds 150 clipUSD through stake/instruction")
    staking = post("/api/solana/stake/instruction", {"wallet_address": str(creator.pubkey()), "action": "stake", "amount": "150"})
    rpc.send([instruction_from_json(i) for i in staking["instructions"]], creator, [creator])
    stake = get(f"/api/solana/stake/{creator.pubkey()}")
    check(stake["exists"] and int(stake["amount"]) == 150 * CLIP, f"bond {stake['amount']}")

    step("the oracle settles epoch 1: 10000 short views -> 20 clipUSD, bonded tier 300 bps")
    evidence = hashlib.sha256(b"epoch-1").hexdigest()
    settled = post(
        f"/api/solana/campaign/{campaign_id}/escrow/settle",
        {"wallet_address": str(creator.pubkey()), "epoch": 1, "units": UNITS, "evidence_hash": evidence},
        headers={"X-Oracle-Token": token},
    )
    print(f"    sent {settled['signature']}")
    payouts = get(f"/api/solana/campaign/{campaign_id}/payouts/{creator.pubkey()}")
    check(len(payouts) == 1, f"{len(payouts)} payout listed")
    check(int(payouts[0]["amount"]) == 20 * CLIP, f"amount {payouts[0]['amount']}")
    check(int(payouts[0]["bonus_bps"]) == 300, f"bonus_bps {payouts[0]['bonus_bps']}")
    unlock = int(payouts[0]["unlock_ts"])

    step("release before the unlock is refused without spending a fee")
    response = api.post(f"/api/solana/campaign/{campaign_id}/escrow/release", json={"wallet_address": str(creator.pubkey()), "epoch": 1}, headers={"X-Oracle-Token": token})
    check(response.status_code == 409, f"{response.status_code} {response.json().get('detail')}")

    step("a wrong creator signature is refused")
    response = api.post(f"/api/solana/campaign/{campaign_id}/escrow/release", json={"wallet_address": str(creator.pubkey()), "epoch": 1, "signature": sign(brand, "nonsense")})
    check(response.status_code == 403, f"{response.status_code} {response.json().get('detail')}")

    wait = max(0, unlock - int(time.time()) + 3)
    step(f"wait {wait}s for the bonded unlock, then the creator releases with a signed message")
    time.sleep(wait)
    message = f"WAGGI release\ncampaign_id: {campaign_id}\nepoch: 1\nwallet_address: {creator.pubkey()}"
    released = post(f"/api/solana/campaign/{campaign_id}/escrow/release", {"wallet_address": str(creator.pubkey()), "epoch": 1, "signature": sign(creator, message)})
    print(f"    sent {released['signature']}")
    balance = rpc.token_balance(ata(creator.pubkey(), mint))
    check(balance == 50 * CLIP + 20 * CLIP + 600_000, f"creator holds {balance / CLIP} clipUSD = 50 left + 20 payout + 0.6 bonus")
    check(get(f"/api/solana/campaign/{campaign_id}/payouts/{creator.pubkey()}") == [], "payout account closed")

    step("epoch 2 is settled, the brand flags it, the arbiter rejects and slashes 10 clipUSD of the bond")
    post(
        f"/api/solana/campaign/{campaign_id}/escrow/settle",
        {"wallet_address": str(creator.pubkey()), "epoch": 2, "units": UNITS, "evidence_hash": hashlib.sha256(b"epoch-2").hexdigest()},
        headers={"X-Oracle-Token": token},
    )
    flag = post(f"/api/solana/campaign/{campaign_id}/escrow/flag", {"company_wallet": str(brand.pubkey()), "wallet_address": str(creator.pubkey()), "epoch": 2, "reason": 1})
    rpc.send([instruction_from_json(i) for i in flag["instructions"]], brand, [brand])
    resolved = post(
        f"/api/solana/campaign/{campaign_id}/escrow/resolve",
        {"wallet_address": str(creator.pubkey()), "epoch": 2, "approve": False, "slash_amount": "10"},
        headers={"X-Oracle-Token": token},
    )
    print(f"    sent {resolved['signature']}")
    stake = get(f"/api/solana/stake/{creator.pubkey()}")
    check(int(stake["amount"]) == 140 * CLIP, f"bond after slash {stake['amount']}")
    check(int(stake["slashed_total"]) == 10 * CLIP, f"slashed_total {stake['slashed_total']}")
    check(get(f"/api/solana/campaign/{campaign_id}/payouts/{creator.pubkey()}") == [], "rejected payout closed")
    escrow = get(f"/api/solana/campaign/{campaign_id}/escrow")["campaign"]
    check(int(escrow["funded_total"]) == 510 * CLIP, f"funded_total {escrow['funded_total']} (500 + 10 slashed)")
    check(int(escrow["paid_total"]) == 20 * CLIP and int(escrow["reserved"]) == 0, f"paid_total {escrow['paid_total']} reserved {escrow['reserved']}")

    step("the creator asks to unstake 40 and the bond stops counting immediately")
    unstaking = post("/api/solana/stake/instruction", {"wallet_address": str(creator.pubkey()), "action": "request_unstake", "amount": "40"})
    rpc.send([instruction_from_json(i) for i in unstaking["instructions"]], creator, [creator])
    stake = get(f"/api/solana/stake/{creator.pubkey()}")
    check(int(stake["pending_unstake"]) == 40 * CLIP and int(stake["unstake_at"]) > time.time(), f"pending {stake['pending_unstake']} until {stake['unstake_at']}")

    print(f"\nPASS: campaign {campaign_id}, company {company['id']}, creator {person['id']} ({creator.pubkey()})")


if __name__ == "__main__":
    main()
