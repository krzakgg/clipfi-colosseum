import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from solders.pubkey import Pubkey

PROGRAM_ID = "GAXMVFUXzAPBwhW4cF127HiSZmiY791XX2mBFEqqBwx"
MINT = "So11111111111111111111111111111111111111112"
BRAND = "SysvarRent111111111111111111111111111111111"
CREATOR = "SysvarC1ock11111111111111111111111111111111"
ORACLE_TOKEN = "oracle-token-for-tests-0123456789abcdef"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ATA_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"

_REPO = Path(__file__).resolve().parents[2]
IDL_CANDIDATES = (_REPO.parent / "clipfi" / "idl" / "clipfi_escrow.json", _REPO / "clipfi-escrow" / "idl" / "clipfi_escrow.json")
IDL_PATH = next((path for path in IDL_CANDIDATES if path.is_file()), IDL_CANDIDATES[0])


def program():
    from clipfi_escrow import IdlProgram

    return IdlProgram.load(IDL_PATH, PROGRAM_ID)


def ata(owner: Pubkey, mint: Pubkey) -> Pubkey:
    return Pubkey.find_program_address(
        [bytes(owner), bytes(Pubkey.from_string(TOKEN_PROGRAM)), bytes(mint)], Pubkey.from_string(ATA_PROGRAM)
    )[0]


def campaign_row(**overrides):
    from models import Campaign

    fields = dict(
        id=7,
        title="Launch",
        company_id=3,
        total_budget=Decimal("1000.00"),
        budget_per_creator=Decimal("250.00"),
        payout_per_views=Decimal("15.00"),
        views_unit_step=1000,
        payout_per_click=Decimal("1.50"),
        brand_guidelines="no profanity",
        start_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    fields.update(overrides)
    return Campaign(**fields)


def company_row(wallet=BRAND):
    from models import Company

    return Company(id=3, name="Acme", email="acme@example.com", solana_wallet_address=wallet)


def campaign_account_bytes(brand: Pubkey, campaign_id: int, **overrides) -> bytes:
    idl = program()
    campaign = idl.campaign_pda(brand, campaign_id)
    value = {
        "brand": str(brand),
        "campaign_id": campaign_id,
        "mint": MINT,
        "vault": str(ata(campaign, Pubkey.from_string(MINT))),
        "funded_total": 5_000_000,
        "reserved": 1_000_000,
        "paid_total": 250_000,
        "rate_per_mille": [15_000_000, 15_000_000, 0, 1_500_000_000],
        "pending_rates": [0, 0, 0, 0],
        "pending_rates_at": 0,
        "max_per_creator": 250_000_000,
        "min_bond": 0,
        "start_ts": 1_790_000_000,
        "end_ts": 1_792_000_000,
        "standards_hash": list(hashlib.sha256(b"no profanity").digest()),
        "standards_version": 1,
        "pending_standards_hash": [0] * 32,
        "pending_standards_at": 0,
        "status": "Active",
        "bump": 254,
    }
    value.update(overrides)
    return idl.encode_account("Campaign", value)


class FakeDb:
    def __init__(self, *rows):
        self.rows = {(type(row), row.id): row for row in rows}

    async def get(self, model, key, **_):
        return self.rows.get((model, key))


@pytest.fixture
def escrow_settings(monkeypatch):
    from settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "solana_escrow_program_id", PROGRAM_ID)
    monkeypatch.setattr(settings, "solana_escrow_idl_path", str(IDL_PATH))
    monkeypatch.setattr(settings, "solana_bmoney_mint", MINT)
    monkeypatch.setattr(settings, "solana_bmoney_decimals", 6)
    monkeypatch.setattr(settings, "solana_oracle_token", SecretStr(ORACLE_TOKEN))
    return settings


@pytest.fixture
async def api(escrow_settings):
    import main
    from database import get_db
    from tracking_client import get_tracking

    main.app.dependency_overrides[get_db] = lambda: FakeDb(campaign_row(), company_row())
    main.app.dependency_overrides[get_tracking] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://waggi") as client:
        yield client
    main.app.dependency_overrides.pop(get_db, None)
    main.app.dependency_overrides.pop(get_tracking, None)


def test_instruction_discriminators_are_sha256_global_prefixes():
    idl = program()
    for name in idl.instructions:
        expected = hashlib.sha256(f"global:{name}".encode()).digest()[:8]
        print(f"checks discriminator of {name}: idl={idl.instruction_discriminator(name).hex()} sha256={expected.hex()}")
        assert idl.instruction_discriminator(name) == expected
    for name in idl.accounts:
        expected = hashlib.sha256(f"account:{name}".encode()).digest()[:8]
        print(f"checks account discriminator of {name}: {expected.hex()}")
        assert idl.account_discriminator(name) == expected


def test_pdas_match_find_program_address_with_fixed_inputs():
    idl = program()
    pid = Pubkey.from_string(PROGRAM_ID)
    brand, creator = Pubkey.from_string(BRAND), Pubkey.from_string(CREATOR)
    config = Pubkey.find_program_address([b"config"], pid)[0]
    campaign = Pubkey.find_program_address([b"campaign", bytes(brand), (42).to_bytes(8, "little")], pid)[0]
    position = Pubkey.find_program_address([b"position", bytes(campaign), bytes(creator)], pid)[0]
    payout = Pubkey.find_program_address([b"payout", bytes(campaign), bytes(creator), (3).to_bytes(8, "little")], pid)[0]
    stake = Pubkey.find_program_address([b"stake", bytes(creator)], pid)[0]
    print(f"checks config={config} campaign={campaign} position={position} payout={payout} stake={stake}")
    assert idl.config_pda() == config
    assert idl.campaign_pda(brand, 42) == campaign
    assert idl.position_pda(campaign, creator) == position
    assert idl.payout_pda(campaign, creator, 3) == payout
    assert idl.stake_pda(creator) == stake


def test_campaign_params_borsh_round_trip():
    idl = program()
    params = {
        "rate_per_mille": [15_000_000, 15_000_000, 0, 1_500_000_000],
        "max_per_creator": 250_000_000,
        "min_bond": 1_000_000,
        "start_ts": -5,
        "end_ts": 1_792_000_000,
        "standards_hash": list(hashlib.sha256(b"rules").digest()),
    }
    encoded = idl.codec.encode({"defined": {"name": "CampaignParams"}}, params)
    decoded, consumed = idl.codec.decode({"defined": {"name": "CampaignParams"}}, encoded)
    print(f"checks CampaignParams encodes to {len(encoded)} bytes (expected 96) and decodes back: {decoded == params}")
    assert len(encoded) == 4 * 8 + 8 + 8 + 8 + 8 + 32
    assert consumed == len(encoded)
    assert decoded == params
    assert encoded[:8] == (15_000_000).to_bytes(8, "little")
    assert encoded[48:56] == (-5).to_bytes(8, "little", signed=True)


def test_campaign_account_round_trip_built_from_idl():
    idl = program()
    brand = Pubkey.from_string(BRAND)
    data = campaign_account_bytes(brand, 7)
    decoded = idl.decode_account("Campaign", data)
    print(f"checks Campaign account: {len(data)} bytes, discriminator={data[:8].hex()}, decoded status={decoded['status']}")
    assert data[:8] == idl.account_discriminator("Campaign")
    assert decoded["brand"] == BRAND
    assert decoded["campaign_id"] == 7
    assert decoded["rate_per_mille"] == [15_000_000, 15_000_000, 0, 1_500_000_000]
    assert decoded["status"] == "Active"
    assert bytes(decoded["standards_hash"]) == hashlib.sha256(b"no profanity").digest()
    assert decoded["bump"] == 254
    with pytest.raises(Exception):
        idl.decode_account("Payout", data)


async def test_funding_instruction_creates_and_funds_when_campaign_is_missing(api, monkeypatch):
    import solana_service

    async def missing(address):
        return None

    monkeypatch.setattr(solana_service, "rpc_account_data", missing)
    response = await api.post(
        "/api/solana/campaign/7/escrow/funding-instruction",
        json={"company_wallet": BRAND, "amount": "123.456789", "min_bond": "2"},
    )
    body = response.json()
    names = [program().instruction_discriminator(n) for n in ("create_campaign", "fund_campaign")]
    print(f"checks status={response.status_code} instructions={len(body.get('instructions', []))} campaign_pda={body.get('campaign_pda')}")
    assert response.status_code == 200, response.text
    assert len(body["instructions"]) == 2
    import base64

    create, fund = body["instructions"]
    assert base64.b64decode(create["data"])[:8] == names[0]
    assert base64.b64decode(fund["data"])[:8] == names[1]
    assert base64.b64decode(fund["data"])[8:16] == (123_456_789).to_bytes(8, "little")
    assert create["program_id"] == PROGRAM_ID
    brand = Pubkey.from_string(BRAND)
    campaign = program().campaign_pda(brand, 7)
    assert body["campaign_pda"] == str(campaign)
    assert body["vault"] == str(ata(campaign, Pubkey.from_string(MINT)))
    create_accounts = [item["pubkey"] for item in create["accounts"]]
    assert create_accounts == [
        BRAND, str(program().config_pda()), MINT, str(campaign), body["vault"], ATA_PROGRAM, TOKEN_PROGRAM,
        "11111111111111111111111111111111",
    ]
    assert create["accounts"][0] == {"pubkey": BRAND, "is_signer": True, "is_writable": True}
    params = program().codec.decode({"defined": {"name": "CampaignParams"}}, base64.b64decode(create["data"])[16:])[0]
    print(f"checks on-chain params derived from the waggi campaign: {params}")
    assert params["rate_per_mille"] == [15_000_000, 15_000_000, 0, 1_500_000_000]
    assert params["max_per_creator"] == 250_000_000
    assert params["min_bond"] == 2_000_000
    assert params["start_ts"] == int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
    assert bytes(params["standards_hash"]) == hashlib.sha256(b"no profanity").digest()
    fund_accounts = [item["pubkey"] for item in fund["accounts"]]
    assert fund_accounts == [BRAND, str(campaign), MINT, str(ata(brand, Pubkey.from_string(MINT))), body["vault"], TOKEN_PROGRAM]


async def test_funding_instruction_only_funds_when_campaign_exists(api, monkeypatch):
    import solana_service

    brand = Pubkey.from_string(BRAND)
    seen = []

    async def existing(address):
        seen.append(str(address))
        return campaign_account_bytes(brand, 7)

    monkeypatch.setattr(solana_service, "rpc_account_data", existing)
    response = await api.post(
        "/api/solana/campaign/7/escrow/funding-instruction", json={"company_wallet": BRAND, "amount": "10"}
    )
    body = response.json()
    print(f"checks status={response.status_code} reader asked for {seen} and got {len(body.get('instructions', []))} instruction(s)")
    assert response.status_code == 200, response.text
    assert seen == [str(program().campaign_pda(brand, 7))]
    assert len(body["instructions"]) == 1
    import base64

    assert base64.b64decode(body["instructions"][0]["data"])[:8] == program().instruction_discriminator("fund_campaign")

    wrong = await api.post("/api/solana/campaign/7/escrow/funding-instruction", json={"company_wallet": CREATOR, "amount": "10"})
    print(f"checks a foreign wallet is refused with {wrong.status_code}")
    assert wrong.status_code == 403

    view = await api.get("/api/solana/campaign/7/escrow")
    print(f"checks GET escrow exists={view.json()['exists']} funded_total={view.json()['campaign']['funded_total']}")
    assert view.status_code == 200
    assert view.json()["exists"] is True
    assert view.json()["campaign"]["funded_total"] == "5000000"
    assert view.json()["campaign"]["status"] == "Active"


async def test_escrow_view_reports_missing_campaign_as_not_existing(api, monkeypatch):
    import solana_service

    async def missing(address):
        return None

    monkeypatch.setattr(solana_service, "rpc_account_data", missing)
    view = await api.get("/api/solana/campaign/7/escrow")
    print(f"checks GET escrow on an undeployed program: {view.json()}")
    assert view.status_code == 200
    assert view.json() == {
        "exists": False,
        "campaign_pda": str(program().campaign_pda(Pubkey.from_string(BRAND), 7)),
        "vault": str(ata(program().campaign_pda(Pubkey.from_string(BRAND), 7), Pubkey.from_string(MINT))),
        "campaign": None,
    }


async def test_settle_rejects_wrong_oracle_token(api, monkeypatch):
    import solana_service

    async def never(*args, **kwargs):
        raise AssertionError("must not reach the chain")

    monkeypatch.setattr(solana_service, "send_instructions", never)
    body = {"wallet_address": CREATOR, "epoch": 1, "units": [0, 0, 0, 5], "evidence_hash": "ab" * 32}
    wrong = await api.post("/api/solana/campaign/7/escrow/settle", json=body, headers={"X-Oracle-Token": "nope"})
    missing = await api.post("/api/solana/campaign/7/escrow/settle", json=body)
    resolve = await api.post(
        "/api/solana/campaign/7/escrow/resolve", json={"wallet_address": CREATOR, "epoch": 1, "approve": True},
        headers={"X-Oracle-Token": "nope"},
    )
    print(f"checks settle wrong token={wrong.status_code} no token={missing.status_code} resolve wrong token={resolve.status_code}")
    assert (wrong.status_code, missing.status_code, resolve.status_code) == (403, 403, 403)


async def test_settle_with_the_right_token_signs_as_oracle(api, monkeypatch):
    import solana_service
    from solders.keypair import Keypair

    oracle = Keypair()
    sent = []

    async def capture(keypair, instructions):
        sent.append((keypair, instructions))
        return "5igNature"

    monkeypatch.setattr(solana_service, "send_instructions", capture)
    monkeypatch.setattr(solana_service, "get_treasury_keypair", lambda: oracle)
    response = await api.post(
        "/api/solana/campaign/7/escrow/settle",
        json={"wallet_address": CREATOR, "epoch": 2, "units": [10, 20, 0, 5], "evidence_hash": "cd" * 32},
        headers={"X-Oracle-Token": ORACLE_TOKEN},
    )
    print(f"checks settle status={response.status_code} body={response.json()}")
    assert response.status_code == 200, response.text
    keypair, [instruction] = sent[0]
    campaign = program().campaign_pda(Pubkey.from_string(BRAND), 7)
    creator = Pubkey.from_string(CREATOR)
    payout = program().payout_pda(campaign, creator, 2)
    assert keypair is oracle
    assert response.json() == {"signature": "5igNature", "payout_pda": str(payout), "units": [10, 20, 0, 5]}
    assert bytes(instruction.data)[:8] == program().instruction_discriminator("settle")
    assert bytes(instruction.data)[8:16] == (2).to_bytes(8, "little")
    assert bytes(instruction.data)[16:48] == b"".join(unit.to_bytes(8, "little") for unit in (10, 20, 0, 5))
    assert bytes(instruction.data)[48:80] == bytes.fromhex("cd" * 32)
    assert [str(meta.pubkey) for meta in instruction.accounts] == [
        str(oracle.pubkey()), str(program().config_pda()), str(campaign), CREATOR,
        str(program().stake_pda(creator)), str(program().position_pda(campaign, creator)), str(payout),
        "11111111111111111111111111111111",
    ]
    assert instruction.accounts[0].is_signer and instruction.accounts[0].is_writable


def test_rate_mapping_from_waggi_campaign(escrow_settings):
    from solana_service import campaign_chain_params, rate_per_mille_from_campaign

    rates = rate_per_mille_from_campaign(campaign_row())
    print(f"checks 15.00 per 1000 views -> {rates[0]} per mille, 1.50 per click -> {rates[3]} per mille")
    assert rates == [15_000_000, 15_000_000, 0, 1_500_000_000]

    stepped = rate_per_mille_from_campaign(campaign_row(payout_per_views=Decimal("3.33"), views_unit_step=100, payout_per_click=None))
    print(f"checks 3.33 per 100 views -> {stepped[0]} per mille, no click rate -> {stepped[3]}")
    assert stepped == [33_300_000, 33_300_000, 0, 0]

    params = campaign_chain_params(campaign_row(budget_per_creator=None, brand_guidelines=None, start_date=None, end_date=None), Decimal("0.5"))
    print(f"checks fallbacks: max_per_creator={params['max_per_creator']} min_bond={params['min_bond']} window={params['end_ts'] - params['start_ts']}s")
    assert params["max_per_creator"] == 1_000_000_000
    assert params["min_bond"] == 500_000
    assert params["end_ts"] - params["start_ts"] == 30 * 24 * 3600
    assert bytes(params["standards_hash"]) == hashlib.sha256(b"").digest()


def test_release_passes_stake_accounts_only_when_restaking_or_staked(escrow_settings):
    from solana_service import build_release_instruction, escrow_context

    brand, creator = Pubkey.from_string(BRAND), Pubkey.from_string(CREATOR)
    ctx = escrow_context(brand, 7)
    cranker = Pubkey.from_string(MINT)
    rent_payer = str(Pubkey.from_string(TOKEN_PROGRAM))
    stake = ctx.program.stake_pda(creator)
    stake_token = ata(stake, Pubkey.from_string(MINT))
    names = [account["name"] for account in ctx.program.instructions["release"]["accounts"]]
    stake_index, token_index = names.index("stake"), names.index("stake_token")

    plain = build_release_instruction(ctx, creator, 1, {"rent_payer": rent_payer, "restake_bps": 0}, False, cranker)
    restaking = build_release_instruction(ctx, creator, 1, {"rent_payer": rent_payer, "restake_bps": 250}, False, cranker)
    staked = build_release_instruction(ctx, creator, 1, {"rent_payer": rent_payer}, True, cranker)
    plain_keys = [str(meta.pubkey) for meta in plain.accounts]
    restaking_keys = [str(meta.pubkey) for meta in restaking.accounts]
    staked_keys = [str(meta.pubkey) for meta in staked.accounts]
    print(f"checks restake_bps=0 and no stake -> stake slots {plain_keys[stake_index]}, {plain_keys[token_index]}")
    print(f"checks restake_bps=250 -> stake slots {restaking_keys[stake_index]}, {restaking_keys[token_index]}")
    assert plain_keys[stake_index] == plain_keys[token_index] == PROGRAM_ID
    assert not plain.accounts[stake_index].is_writable
    assert restaking_keys[stake_index] == str(stake)
    assert restaking_keys[token_index] == str(stake_token)
    assert restaking.accounts[stake_index].is_writable
    assert staked_keys[stake_index] == str(stake)
    assert plain_keys[names.index("rent_payer")] == rent_payer
    assert plain_keys[names.index("payout")] == str(ctx.program.payout_pda(ctx.campaign, creator, 1))
    assert plain_keys[0] == str(cranker) and plain.accounts[0].is_signer
    assert bytes(plain.data) == ctx.program.instruction_discriminator("release")


async def test_payouts_are_decoded_from_a_program_accounts_response(api, monkeypatch):
    import solana_service

    idl = program()
    brand, creator = Pubkey.from_string(BRAND), Pubkey.from_string(CREATOR)
    campaign = idl.campaign_pda(brand, 7)
    seen = {}

    def payout_bytes(epoch: int, amount: int, status: str) -> bytes:
        return idl.encode_account(
            "Payout",
            {
                "campaign": str(campaign),
                "creator": CREATOR,
                "epoch": epoch,
                "units": [1, 2, 3, 4],
                "amount": amount,
                "bonus_bps": 150,
                "restake_bps": 300,
                "standards_version": 2,
                "evidence_hash": list(hashlib.sha256(f"epoch-{epoch}".encode()).digest()),
                "unlock_ts": 1_792_000_000 + epoch,
                "status": status,
                "rent_payer": MINT,
                "bump": 251,
            },
        )

    async def fabricated(program_id, filters):
        seen["program_id"] = str(program_id)
        seen["filters"] = [(item.offset, item.bytes) for item in filters]
        return [
            (str(idl.payout_pda(campaign, creator, 5)), payout_bytes(5, 7_000_000, "Approved")),
            ("garbage", b"\x00" * 10),
            (str(idl.payout_pda(campaign, creator, 4)), payout_bytes(4, 1_500_000, "Flagged")),
        ]

    monkeypatch.setattr(solana_service, "rpc_program_accounts", fabricated)
    response = await api.get(f"/api/solana/campaign/7/payouts/{CREATOR}")
    print(f"checks status={response.status_code} filters={seen['filters']} rows={len(response.json())}")
    assert response.status_code == 200, response.text
    import base58

    assert seen["program_id"] == PROGRAM_ID
    assert seen["filters"] == [
        (0, base58.b58encode(idl.account_discriminator("Payout")).decode()),
        (8, base58.b58encode(bytes(campaign)).decode()),
        (40, base58.b58encode(bytes(creator)).decode()),
    ]
    rows = response.json()
    has_restake = idl.has_account_field("Payout", "restake_bps")
    print(f"checks decoded payouts (IDL has restake_bps={has_restake}): {json.dumps(rows)[:400]}")
    assert [row["epoch"] for row in rows] == [4, 5]
    assert rows[1]["amount"] == "7000000"
    assert rows[1]["bonus_bps"] == 150
    assert rows[1]["restake_bps"] == (300 if has_restake else 0)
    assert rows[1]["status"] == "Approved" and rows[0]["status"] == "Flagged"
    assert rows[1]["unlock_ts"] == 1_792_000_005
    assert rows[1]["evidence_hash"] == hashlib.sha256(b"epoch-5").hexdigest()
    assert rows[1]["address"] == str(idl.payout_pda(campaign, creator, 5))
    assert rows[1]["units"] == ["1", "2", "3", "4"]


async def test_stake_instructions_and_stake_view(api, monkeypatch):
    import base64

    import solana_service

    idl = program()
    creator = Pubkey.from_string(CREATOR)
    stake = idl.stake_pda(creator)
    response = await api.post("/api/solana/stake/instruction", json={"wallet_address": CREATOR, "action": "stake", "amount": "12.5"})
    print(f"checks stake instruction status={response.status_code} stake_pda={response.json().get('stake_pda')}")
    assert response.status_code == 200, response.text
    [instruction] = response.json()["instructions"]
    data = base64.b64decode(instruction["data"])
    assert data == idl.instruction_discriminator("stake") + (12_500_000).to_bytes(8, "little")
    assert [item["pubkey"] for item in instruction["accounts"]] == [
        CREATOR, str(idl.config_pda()), MINT, str(stake), str(ata(stake, Pubkey.from_string(MINT))),
        str(ata(creator, Pubkey.from_string(MINT))), ATA_PROGRAM, TOKEN_PROGRAM, "11111111111111111111111111111111",
    ]
    auto = await api.post("/api/solana/stake/instruction", json={"wallet_address": CREATOR, "action": "set_auto_restake", "bps": 2500})
    assert base64.b64decode(auto.json()["instructions"][0]["data"]) == idl.instruction_discriminator("set_auto_restake") + (2500).to_bytes(2, "little")
    incomplete = await api.post("/api/solana/stake/instruction", json={"wallet_address": CREATOR, "action": "request_unstake"})
    print(f"checks request_unstake without amount -> {incomplete.status_code}")
    assert incomplete.status_code == 400

    async def missing(address):
        return None

    monkeypatch.setattr(solana_service, "rpc_account_data", missing)
    absent = await api.get(f"/api/solana/stake/{CREATOR}")
    print(f"checks stake view without an account: {absent.json()}")
    assert absent.json()["exists"] is False and absent.json()["amount"] == "0"

    async def present(address):
        return idl.encode_account(
            "Stake",
            {"creator": CREATOR, "token": str(ata(stake, Pubkey.from_string(MINT))), "amount": 12_500_000, "pending_unstake": 500_000,
             "unstake_at": 1_792_000_000, "auto_restake_bps": 2500, "slashed_total": 1, "bump": 250},
        )

    monkeypatch.setattr(solana_service, "rpc_account_data", present)
    found = await api.get(f"/api/solana/stake/{CREATOR}")
    print(f"checks stake view with an account: {found.json()}")
    assert found.json()["exists"] is True
    assert (found.json()["amount"], found.json()["pending_unstake"], found.json()["auto_restake_bps"]) == ("12500000", "500000", 2500)


async def test_config_exposes_clipusd_mint_and_bonus_vault(api, monkeypatch):
    from settings import get_settings

    monkeypatch.setattr(get_settings(), "solana_treasury_address", BRAND)
    monkeypatch.setattr(get_settings(), "solana_treasury_private_key", None)
    response = await api.get("/api/solana/config")
    body = response.json()
    bonus_vault = ata(program().config_pda(), Pubkey.from_string(MINT))
    print(f"checks config escrow_program_id={body.get('escrow_program_id')} clipusd_mint={body.get('clipusd_mint')} bonus_vault={body.get('bonus_vault')}")
    assert response.status_code == 200, response.text
    assert body["escrow_program_id"] == PROGRAM_ID
    assert body["clipusd_mint"] == MINT
    assert body["bonus_vault"] == str(bonus_vault)
    assert "escrow_counter_mint" not in body and "escrow_release_authority" not in body


def payout_account(idl, campaign: Pubkey, epoch: int, status: str, unlock_ts: int, rent_payer: str, creator: str = CREATOR) -> bytes:
    return idl.encode_account(
        "Payout",
        {
            "campaign": str(campaign),
            "creator": creator,
            "epoch": epoch,
            "units": [0, 0, 0, 9],
            "amount": 4_500_000,
            "bonus_bps": 0,
            "restake_bps": 0,
            "standards_version": 1,
            "evidence_hash": [0] * 32,
            "unlock_ts": unlock_ts,
            "status": status,
            "rent_payer": rent_payer,
            "bump": 253,
        },
    )


@pytest.fixture
def release_chain(monkeypatch):
    import solana_service
    from solders.keypair import Keypair

    idl = program()
    campaign = idl.campaign_pda(Pubkey.from_string(BRAND), 7)
    treasury = Keypair()
    state = {
        "payouts": {str(idl.payout_pda(campaign, Pubkey.from_string(CREATOR), 1)): payout_account(idl, campaign, 1, "Pending", 1_700_000_000, str(treasury.pubkey()))},
        "sent": [],
        "treasury": treasury,
        "campaign": campaign,
    }

    async def reader(address):
        return state["payouts"].get(str(address))

    async def capture(keypair, instructions):
        state["sent"].append((keypair, instructions))
        return "re1easeSig"

    monkeypatch.setattr(solana_service, "rpc_account_data", reader)
    monkeypatch.setattr(solana_service, "send_instructions", capture)
    monkeypatch.setattr(solana_service, "get_treasury_keypair", lambda: treasury)
    return state


async def test_release_rejects_a_wrong_creator_signature(api, release_chain):
    import base58
    from solders.keypair import Keypair

    from solana_service import build_release_message

    message = build_release_message(7, 1, CREATOR)
    forged = base58.b58encode(bytes(Keypair().sign_message(message.encode()))).decode()
    body = {"wallet_address": CREATOR, "epoch": 1}
    no_auth = await api.post("/api/solana/campaign/7/escrow/release", json=body)
    wrong_token = await api.post("/api/solana/campaign/7/escrow/release", json=body, headers={"X-Oracle-Token": "nope"})
    forged_sig = await api.post("/api/solana/campaign/7/escrow/release", json={**body, "signature": forged})
    print(f"checks release no auth={no_auth.status_code} wrong token={wrong_token.status_code} forged signature={forged_sig.status_code}")
    assert (no_auth.status_code, wrong_token.status_code, forged_sig.status_code) == (403, 403, 403)
    assert release_chain["sent"] == []


async def test_release_with_oracle_token_signs_as_cranker(api, release_chain):
    response = await api.post(
        "/api/solana/campaign/7/escrow/release", json={"wallet_address": CREATOR, "epoch": 1}, headers={"X-Oracle-Token": ORACLE_TOKEN}
    )
    print(f"checks release via oracle token status={response.status_code} body={response.json()}")
    assert response.status_code == 200, response.text
    assert response.json()["signature"] == "re1easeSig"
    keypair, [instruction] = release_chain["sent"][0]
    assert keypair is release_chain["treasury"]
    assert bytes(instruction.data) == program().instruction_discriminator("release")
    assert str(instruction.accounts[0].pubkey) == str(release_chain["treasury"].pubkey())
    names = [account["name"] for account in program().instructions["release"]["accounts"]]
    assert str(instruction.accounts[names.index("rent_payer")].pubkey) == str(release_chain["treasury"].pubkey())
    assert str(instruction.accounts[names.index("stake")].pubkey) == PROGRAM_ID


async def test_release_with_a_valid_creator_signature(api, release_chain):
    import base58
    from solders.keypair import Keypair

    from solana_service import build_release_message

    creator = Keypair()
    wallet = str(creator.pubkey())
    idl = program()
    campaign = release_chain["campaign"]
    rent_payer = str(release_chain["treasury"].pubkey())
    release_chain["payouts"][str(idl.payout_pda(campaign, creator.pubkey(), 1))] = payout_account(idl, campaign, 1, "Approved", 1_700_000_000, rent_payer, wallet)
    message = build_release_message(7, 1, wallet)
    signature = base58.b58encode(bytes(creator.sign_message(message.encode()))).decode()
    other_epoch = await api.post("/api/solana/campaign/7/escrow/release", json={"wallet_address": wallet, "epoch": 2, "signature": signature})
    response = await api.post("/api/solana/campaign/7/escrow/release", json={"wallet_address": wallet, "epoch": 1, "signature": signature})
    print(f"checks release signed by the creator over {message!r}: status={response.status_code} body={response.json()}; same signature for epoch 2 -> {other_epoch.status_code}")
    assert other_epoch.status_code == 403
    assert response.status_code == 200, response.text
    assert response.json()["signature"] == "re1easeSig"
    names = [account["name"] for account in idl.instructions["release"]["accounts"]]
    assert str(release_chain["sent"][0][1][0].accounts[names.index("creator")].pubkey) == wallet


async def test_release_refuses_flagged_or_vesting_payouts_before_spending_fees(api, release_chain):
    idl = program()
    campaign = release_chain["campaign"]
    rent_payer = str(release_chain["treasury"].pubkey())
    key = str(idl.payout_pda(campaign, Pubkey.from_string(CREATOR), 1))
    headers = {"X-Oracle-Token": ORACLE_TOKEN}
    body = {"wallet_address": CREATOR, "epoch": 1}

    release_chain["payouts"][key] = payout_account(idl, campaign, 1, "Flagged", 1_700_000_000, rent_payer)
    flagged = await api.post("/api/solana/campaign/7/escrow/release", json=body, headers=headers)
    release_chain["payouts"][key] = payout_account(idl, campaign, 1, "Pending", 4_102_444_800, rent_payer)
    vesting = await api.post("/api/solana/campaign/7/escrow/release", json=body, headers=headers)
    del release_chain["payouts"][key]
    missing = await api.post("/api/solana/campaign/7/escrow/release", json=body, headers=headers)
    print(f"checks flagged={flagged.status_code} {flagged.json()['detail']!r}; vesting={vesting.status_code} {vesting.json()['detail']!r}; missing={missing.status_code} {missing.json()['detail']!r}")
    assert (flagged.status_code, vesting.status_code, missing.status_code) == (409, 409, 409)
    assert "oflagowane" in flagged.json()["detail"]
    assert "4102444800" in vesting.json()["detail"]
    assert release_chain["sent"] == []
