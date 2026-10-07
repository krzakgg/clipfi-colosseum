import os
import struct
import sys

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from chain_common import (
    ATA_PROGRAM,
    CLIP,
    SYSTEM_PROGRAM,
    TOKEN_PROGRAM,
    Rpc,
    ata,
    config_pda,
    discriminator,
    encode_config_params,
    keypair_from,
    load_chain,
    program_data_pda,
    rpc_url,
    save_chain,
)

VESTING = int(os.getenv("CLIPFI_VESTING_SECS", "180"))
BONDED_VESTING = int(os.getenv("CLIPFI_BONDED_VESTING_SECS", "60"))
UNSTAKE_COOLDOWN = int(os.getenv("CLIPFI_UNSTAKE_COOLDOWN_SECS", "180"))
NOTICE = int(os.getenv("CLIPFI_NOTICE_SECS", "60"))
TIER_BOND = int(float(os.getenv("CLIPFI_TIER_BOND", "100")) * CLIP)
TIER_BPS = int(os.getenv("CLIPFI_TIER_BPS", "300"))
BONUS_POOL = int(float(os.getenv("CLIPFI_BONUS_POOL", "1000")) * CLIP)


def main():
    chain = load_chain()
    rpc = Rpc(rpc_url(chain))
    program = Pubkey.from_string(chain["program_id"])
    mint = Pubkey.from_string(chain["mint"])
    deployer = keypair_from(chain["deployer_secret"])
    config = config_pda(program)
    bonus_vault = ata(config, mint)
    chain["config"] = str(config)
    chain["bonus_vault"] = str(bonus_vault)

    if rpc.exists(config):
        print(f"config {config} already initialized, bonus vault {bonus_vault} holds {rpc.token_balance(bonus_vault) / CLIP} clipUSD")
        save_chain(chain)
        return

    params = encode_config_params(
        deployer.pubkey(),
        deployer.pubkey(),
        VESTING,
        BONDED_VESTING,
        UNSTAKE_COOLDOWN,
        NOTICE,
        [(TIER_BOND, TIER_BPS), (0, 0), (0, 0)],
    )
    init = Instruction(
        program,
        discriminator("init_config") + params,
        [
            AccountMeta(deployer.pubkey(), True, True),
            AccountMeta(mint, False, False),
            AccountMeta(config, False, True),
            AccountMeta(bonus_vault, False, True),
            AccountMeta(program, False, False),
            AccountMeta(program_data_pda(program), False, False),
            AccountMeta(ATA_PROGRAM, False, False),
            AccountMeta(TOKEN_PROGRAM, False, False),
            AccountMeta(SYSTEM_PROGRAM, False, False),
        ],
    )
    fund = Instruction(
        program,
        discriminator("fund_bonus_pool") + struct.pack("<Q", BONUS_POOL),
        [
            AccountMeta(deployer.pubkey(), True, False),
            AccountMeta(config, False, False),
            AccountMeta(mint, False, False),
            AccountMeta(bonus_vault, False, True),
            AccountMeta(ata(deployer.pubkey(), mint), False, True),
            AccountMeta(TOKEN_PROGRAM, False, False),
        ],
    )
    signature = rpc.send([init, fund], deployer, [deployer])
    print(
        f"init_config sent: {signature}\n"
        f"  oracle = arbiter = {deployer.pubkey()}\n"
        f"  vesting {VESTING}s, bonded vesting {BONDED_VESTING}s, unstake cooldown {UNSTAKE_COOLDOWN}s, notice {NOTICE}s\n"
        f"  tier: bond {TIER_BOND / CLIP} clipUSD -> {TIER_BPS} bps\n"
        f"  bonus pool {bonus_vault} funded with {BONUS_POOL / CLIP} clipUSD"
    )
    save_chain(chain)


if __name__ == "__main__":
    sys.exit(main())
