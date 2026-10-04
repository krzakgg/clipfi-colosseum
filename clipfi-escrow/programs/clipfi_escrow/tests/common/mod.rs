#![allow(dead_code, clippy::result_large_err)]

use {
    anchor_lang::{
        prelude::Pubkey, solana_program::instruction::Instruction, AccountDeserialize,
        InstructionData, ToAccountMetas,
    },
    anchor_spl::associated_token::get_associated_token_address,
    clipfi_escrow::{CampaignParams, CAMPAIGN_SEED, CONFIG_SEED, PAYOUT_SEED, POSITION_SEED},
    litesvm::{types::TransactionResult, LiteSVM},
    solana_account::Account,
    solana_clock::Clock,
    solana_keypair::Keypair,
    solana_message::{Message, VersionedMessage},
    solana_signer::Signer,
    solana_transaction::versioned::VersionedTransaction,
};

pub const TOKEN_PROGRAM: Pubkey = anchor_spl::token::ID;
pub const TOKEN_2022_PROGRAM: Pubkey = anchor_spl::token_2022::ID;
pub const ATA_PROGRAM: Pubkey = anchor_spl::associated_token::ID;
pub const SYSTEM_PROGRAM: Pubkey = anchor_lang::system_program::ID;

pub const DECIMALS: u8 = 6;
pub const CLIP_USD: u64 = 1_000_000;
pub const NOW: i64 = 1_790_000_000;
pub const DAY: i64 = 86_400;
pub const VESTING: i64 = 14 * DAY;

const MINT_LEN: usize = 82;
const TOKEN_ACCOUNT_LEN: usize = 165;

pub struct World {
    pub svm: LiteSVM,
    pub admin: Keypair,
    pub oracle: Keypair,
    pub arbiter: Keypair,
    pub brand: Keypair,
    pub mint: Pubkey,
    pub program_data: Pubkey,
}

impl World {
    pub fn new() -> Self {
        let mut svm = LiteSVM::new();
        svm.add_program(
            clipfi_escrow::id(),
            include_bytes!("../../../../target/deploy/clipfi_escrow.so"),
        )
        .unwrap();

        let mut clock: Clock = svm.get_sysvar();
        clock.unix_timestamp = NOW;
        svm.set_sysvar(&clock);

        let admin = funded(&mut svm);
        let oracle = funded(&mut svm);
        let arbiter = funded(&mut svm);
        let brand = funded(&mut svm);
        let mint = create_mint(&mut svm, &admin.pubkey());
        let program_data = arm_deployer(&mut svm, &admin.pubkey());
        Self {
            svm,
            admin,
            oracle,
            arbiter,
            brand,
            mint,
            program_data,
        }
    }

    pub fn with_config() -> Self {
        let mut world = Self::new();
        let ix = init_config_ix(
            &world.admin.pubkey(),
            &world.mint,
            world.oracle.pubkey(),
            world.arbiter.pubkey(),
            VESTING,
            &world.program_data,
        );
        send(&mut world.svm, ix, &[&world.admin]).unwrap();
        world
    }

    pub fn with_campaign(campaign_id: u64) -> Self {
        let mut world = Self::with_config();
        let ix = create_campaign_ix(
            &world.brand.pubkey(),
            &world.mint,
            campaign_id,
            default_params(),
        );
        send(&mut world.svm, ix, &[&world.brand]).unwrap();
        world
    }

    pub fn with_funded_campaign(campaign_id: u64, budget: u64) -> Self {
        let mut world = Self::with_campaign(campaign_id);
        let brand = world.brand.pubkey();
        let campaign = campaign_pda(&brand, campaign_id);
        let brand_token = give_tokens(&mut world.svm, &brand, &world.mint, budget);
        let ix = fund_campaign_ix(&brand, &campaign, &world.mint, &brand_token, budget);
        send(&mut world.svm, ix, &[&world.brand]).unwrap();
        world
    }
}

pub fn default_params() -> CampaignParams {
    CampaignParams {
        rate_per_mille: [2 * CLIP_USD, 5 * CLIP_USD, CLIP_USD / 10, 50 * CLIP_USD],
        max_per_creator: 40 * CLIP_USD,
        start_ts: NOW,
        end_ts: NOW + 30 * DAY,
        standards_hash: [7; 32],
    }
}

pub fn funded(svm: &mut LiteSVM) -> Keypair {
    let keypair = Keypair::new();
    svm.airdrop(&keypair.pubkey(), 10_000_000_000).unwrap();
    keypair
}

pub fn send(svm: &mut LiteSVM, ix: Instruction, signers: &[&Keypair]) -> TransactionResult {
    let message =
        Message::new_with_blockhash(&[ix], Some(&signers[0].pubkey()), &svm.latest_blockhash());
    let tx = VersionedTransaction::try_new(VersionedMessage::Legacy(message), signers).unwrap();
    let result = svm.send_transaction(tx);
    svm.expire_blockhash();
    result
}

pub fn expect_error(result: TransactionResult, expected: &str) {
    let logs = match result {
        Ok(_) => panic!("expected {expected}, but the transaction went through"),
        Err(failure) => failure.meta.logs.join("\n"),
    };
    assert!(logs.contains(expected), "expected {expected} in:\n{logs}");
    println!("  rejected: {expected}");
}

pub fn fetch<T: AccountDeserialize>(svm: &LiteSVM, address: &Pubkey) -> T {
    let account = svm.get_account(address).expect("account does not exist");
    T::try_deserialize(&mut account.data.as_slice()).unwrap()
}

fn put(svm: &mut LiteSVM, address: Pubkey, data: Vec<u8>, owner: Pubkey) {
    let lamports = svm.minimum_balance_for_rent_exemption(data.len());
    svm.set_account(
        address,
        Account {
            lamports,
            data,
            owner,
            executable: false,
            rent_epoch: 0,
        },
    )
    .unwrap();
}

pub fn create_mint(svm: &mut LiteSVM, authority: &Pubkey) -> Pubkey {
    let mint = Pubkey::new_unique();
    let mut data = vec![0u8; MINT_LEN];
    data[0..4].copy_from_slice(&1u32.to_le_bytes());
    data[4..36].copy_from_slice(authority.as_ref());
    data[44] = DECIMALS;
    data[45] = 1;
    put(svm, mint, data, TOKEN_PROGRAM);
    mint
}

// a Token-2022 mint carrying the TransferFeeConfig extension, forged byte-for-byte:
// base mint (82) + padding to Account::LEN (165) + account-type tag + TLV {type=1, len=108}
pub fn create_fee_mint(svm: &mut LiteSVM, authority: &Pubkey) -> Pubkey {
    let mint = Pubkey::new_unique();
    let mut data = vec![0u8; 278];
    data[0..4].copy_from_slice(&1u32.to_le_bytes());
    data[4..36].copy_from_slice(authority.as_ref());
    data[44] = DECIMALS;
    data[45] = 1;
    data[165] = 1; // AccountType::Mint
    data[166..168].copy_from_slice(&1u16.to_le_bytes()); // ExtensionType::TransferFeeConfig
    data[168..170].copy_from_slice(&108u16.to_le_bytes()); // its length
    put(svm, mint, data, TOKEN_2022_PROGRAM);
    mint
}

pub fn give_tokens(svm: &mut LiteSVM, owner: &Pubkey, mint: &Pubkey, amount: u64) -> Pubkey {
    let address = get_associated_token_address(owner, mint);
    let mut data = vec![0u8; TOKEN_ACCOUNT_LEN];
    data[0..32].copy_from_slice(mint.as_ref());
    data[32..64].copy_from_slice(owner.as_ref());
    data[64..72].copy_from_slice(&amount.to_le_bytes());
    data[108] = 1;
    put(svm, address, data, TOKEN_PROGRAM);
    address
}

pub fn token_balance(svm: &LiteSVM, token_account: &Pubkey) -> u64 {
    let account = svm
        .get_account(token_account)
        .expect("token account does not exist");
    u64::from_le_bytes(account.data[64..72].try_into().unwrap())
}

pub fn token_owner(svm: &LiteSVM, token_account: &Pubkey) -> Pubkey {
    let account = svm
        .get_account(token_account)
        .expect("token account does not exist");
    Pubkey::new_from_array(account.data[32..64].try_into().unwrap())
}

pub fn config_pda() -> Pubkey {
    Pubkey::find_program_address(&[CONFIG_SEED], &clipfi_escrow::id()).0
}

pub fn campaign_pda(brand: &Pubkey, campaign_id: u64) -> Pubkey {
    Pubkey::find_program_address(
        &[CAMPAIGN_SEED, brand.as_ref(), &campaign_id.to_le_bytes()],
        &clipfi_escrow::id(),
    )
    .0
}

pub fn vault_of(campaign: &Pubkey, mint: &Pubkey) -> Pubkey {
    get_associated_token_address(campaign, mint)
}

pub fn init_config_ix(
    admin: &Pubkey,
    mint: &Pubkey,
    oracle: Pubkey,
    arbiter: Pubkey,
    vesting_secs: i64,
    program_data: &Pubkey,
) -> Instruction {
    Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::InitConfig {
            oracle,
            arbiter,
            vesting_secs,
        }
        .data(),
        clipfi_escrow::accounts::InitConfig {
            admin: *admin,
            mint: *mint,
            config: config_pda(),
            program: clipfi_escrow::id(),
            program_data: *program_data,
            system_program: SYSTEM_PROGRAM,
        }
        .to_account_metas(None),
    )
}

// LiteSVM deploys the program as upgradeable; forge its ProgramData so the
// upgrade-authority gate in init_config has a real authority to check against
pub fn arm_deployer(svm: &mut LiteSVM, authority: &Pubkey) -> Pubkey {
    let program = svm
        .get_account(&clipfi_escrow::id())
        .expect("program account");
    let loader = program.owner;
    let program_data = Pubkey::new_from_array(program.data[4..36].try_into().unwrap());
    let mut data = vec![0u8; 45];
    data[0..4].copy_from_slice(&3u32.to_le_bytes()); // UpgradeableLoaderState::ProgramData
    data[12] = 1; // Option::Some
    data[13..45].copy_from_slice(authority.as_ref());
    let lamports = svm.minimum_balance_for_rent_exemption(data.len());
    svm.set_account(
        program_data,
        Account {
            lamports,
            data,
            owner: loader,
            executable: false,
            rent_epoch: 0,
        },
    )
    .unwrap();
    program_data
}

pub fn create_campaign_ix(
    brand: &Pubkey,
    mint: &Pubkey,
    campaign_id: u64,
    params: CampaignParams,
) -> Instruction {
    let campaign = campaign_pda(brand, campaign_id);
    Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::CreateCampaign {
            campaign_id,
            params,
        }
        .data(),
        clipfi_escrow::accounts::CreateCampaign {
            brand: *brand,
            config: config_pda(),
            mint: *mint,
            campaign,
            vault: vault_of(&campaign, mint),
            associated_token_program: ATA_PROGRAM,
            token_program: TOKEN_PROGRAM,
            system_program: SYSTEM_PROGRAM,
        }
        .to_account_metas(None),
    )
}

pub fn fund_campaign_ix(
    brand: &Pubkey,
    campaign: &Pubkey,
    mint: &Pubkey,
    brand_token: &Pubkey,
    amount: u64,
) -> Instruction {
    Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::FundCampaign { amount }.data(),
        clipfi_escrow::accounts::FundCampaign {
            brand: *brand,
            campaign: *campaign,
            mint: *mint,
            brand_token: *brand_token,
            vault: vault_of(campaign, mint),
            token_program: TOKEN_PROGRAM,
        }
        .to_account_metas(None),
    )
}

pub fn set_time(svm: &mut LiteSVM, unix_timestamp: i64) {
    let mut clock: Clock = svm.get_sysvar();
    clock.unix_timestamp = unix_timestamp;
    svm.set_sysvar(&clock);
}

pub fn exists(svm: &LiteSVM, address: &Pubkey) -> bool {
    svm.get_account(address)
        .is_some_and(|account| account.lamports > 0)
}

pub fn lamports(svm: &LiteSVM, address: &Pubkey) -> u64 {
    svm.get_balance(address).unwrap_or(0)
}

pub fn position_pda(campaign: &Pubkey, creator: &Pubkey) -> Pubkey {
    Pubkey::find_program_address(
        &[POSITION_SEED, campaign.as_ref(), creator.as_ref()],
        &clipfi_escrow::id(),
    )
    .0
}

pub fn payout_pda(campaign: &Pubkey, creator: &Pubkey, epoch: u64) -> Pubkey {
    Pubkey::find_program_address(
        &[
            PAYOUT_SEED,
            campaign.as_ref(),
            creator.as_ref(),
            &epoch.to_le_bytes(),
        ],
        &clipfi_escrow::id(),
    )
    .0
}

pub fn settle_ix(
    oracle: &Pubkey,
    campaign: &Pubkey,
    creator: &Pubkey,
    epoch: u64,
    units: [u64; 4],
) -> Instruction {
    Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::Settle {
            epoch,
            units,
            evidence_hash: [epoch as u8; 32],
        }
        .data(),
        clipfi_escrow::accounts::Settle {
            oracle: *oracle,
            config: config_pda(),
            campaign: *campaign,
            creator: *creator,
            position: position_pda(campaign, creator),
            payout: payout_pda(campaign, creator, epoch),
            system_program: SYSTEM_PROGRAM,
        }
        .to_account_metas(None),
    )
}

pub fn flag_ix(brand: &Pubkey, campaign: &Pubkey, payout: &Pubkey, reason: u16) -> Instruction {
    Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::FlagPayout { reason }.data(),
        clipfi_escrow::accounts::FlagPayout {
            brand: *brand,
            campaign: *campaign,
            payout: *payout,
        }
        .to_account_metas(None),
    )
}

pub fn resolve_ix(
    arbiter: &Pubkey,
    campaign: &Pubkey,
    creator: &Pubkey,
    epoch: u64,
    rent_payer: &Pubkey,
    approve: bool,
) -> Instruction {
    Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::Resolve { approve }.data(),
        clipfi_escrow::accounts::Resolve {
            arbiter: *arbiter,
            config: config_pda(),
            campaign: *campaign,
            position: position_pda(campaign, creator),
            payout: payout_pda(campaign, creator, epoch),
            rent_payer: *rent_payer,
        }
        .to_account_metas(None),
    )
}

pub fn release_ix(
    cranker: &Pubkey,
    campaign: &Pubkey,
    mint: &Pubkey,
    creator: &Pubkey,
    payout: &Pubkey,
    rent_payer: &Pubkey,
) -> Instruction {
    Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::Release {}.data(),
        clipfi_escrow::accounts::Release {
            cranker: *cranker,
            campaign: *campaign,
            mint: *mint,
            vault: vault_of(campaign, mint),
            creator: *creator,
            creator_token: get_associated_token_address(creator, mint),
            position: position_pda(campaign, creator),
            payout: *payout,
            rent_payer: *rent_payer,
            associated_token_program: ATA_PROGRAM,
            token_program: TOKEN_PROGRAM,
            system_program: SYSTEM_PROGRAM,
        }
        .to_account_metas(None),
    )
}

pub fn close_campaign_ix(
    brand: &Pubkey,
    campaign: &Pubkey,
    mint: &Pubkey,
    brand_token: &Pubkey,
) -> Instruction {
    Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::CloseCampaign {}.data(),
        clipfi_escrow::accounts::CloseCampaign {
            brand: *brand,
            config: config_pda(),
            campaign: *campaign,
            mint: *mint,
            vault: vault_of(campaign, mint),
            brand_token: *brand_token,
            token_program: TOKEN_PROGRAM,
        }
        .to_account_metas(None),
    )
}
