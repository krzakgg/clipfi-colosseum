#![allow(clippy::result_large_err)]

mod common;

use {
    anchor_lang::{
        prelude::Pubkey, solana_program::instruction::Instruction, InstructionData, ToAccountMetas,
    },
    anchor_spl::associated_token::get_associated_token_address,
    clipfi_escrow::{
        BonusTier, Campaign, CampaignParams, CampaignStatus, ConfigParams, CreatorPosition, Payout,
        PayoutStatus, Stake,
    },
    common::*,
    litesvm::types::TransactionResult,
    solana_keypair::Keypair,
    solana_signer::Signer,
};

// 10000 short views * 2 + 2000 long views * 5 + 100 clicks * 50, all per thousand
const UNITS: [u64; 4] = [10_000, 2_000, 0, 100];
const EARNED: u64 = 35 * CLIP_USD;
const LIMIT: u64 = 40 * CLIP_USD;
const END: i64 = NOW + 30 * DAY;
const BPS: u64 = 10_000;
// 1000 short views at 2 per thousand
const SMALL: [u64; 4] = [1_000, 0, 0, 0];
const SMALL_PAY: u64 = 2 * CLIP_USD;

fn campaign_of(world: &World) -> Pubkey {
    campaign_pda(&world.brand.pubkey(), 1)
}

fn open_campaign(world: &mut World, campaign_id: u64, params: CampaignParams, budget: u64) {
    let brand = world.brand.pubkey();
    let ix = create_campaign_ix(&brand, &world.mint, campaign_id, params);
    send(&mut world.svm, ix, &[&world.brand]).unwrap();
    let brand_token = give_tokens(&mut world.svm, &brand, &world.mint, budget);
    let ix = fund_campaign_ix(
        &brand,
        &campaign_pda(&brand, campaign_id),
        &world.mint,
        &brand_token,
        budget,
    );
    send(&mut world.svm, ix, &[&world.brand]).unwrap();
}

fn world_with(params: CampaignParams, budget: u64) -> World {
    let mut world = World::with_config();
    open_campaign(&mut world, 1, params, budget);
    world
}

// a creator with lamports for rent and exactly `amount` tokens, all of them bonded
fn bonded_creator(world: &mut World, amount: u64) -> Keypair {
    let creator = funded(&mut world.svm);
    give_tokens(&mut world.svm, &creator.pubkey(), &world.mint, amount);
    stake(world, &creator, amount).unwrap();
    creator
}

fn stake(world: &mut World, creator: &Keypair, amount: u64) -> TransactionResult {
    let ix = stake_ix(&creator.pubkey(), &world.mint, amount);
    send(&mut world.svm, ix, &[creator])
}

fn request_unstake(world: &mut World, creator: &Keypair, amount: u64) -> TransactionResult {
    let ix = request_unstake_ix(&creator.pubkey(), amount);
    send(&mut world.svm, ix, &[creator])
}

fn withdraw_stake(world: &mut World, creator: &Keypair) -> TransactionResult {
    let ix = withdraw_stake_ix(&creator.pubkey(), &world.mint);
    send(&mut world.svm, ix, &[creator])
}

fn set_auto_restake(world: &mut World, creator: &Keypair, bps: u16) -> TransactionResult {
    let ix = set_auto_restake_ix(&creator.pubkey(), bps);
    send(&mut world.svm, ix, &[creator])
}

fn fund_pool(world: &mut World, amount: u64) {
    let funder = funded(&mut world.svm);
    let funder_token = give_tokens(&mut world.svm, &funder.pubkey(), &world.mint, amount);
    let ix = fund_bonus_pool_ix(&funder.pubkey(), &world.mint, &funder_token, amount);
    send(&mut world.svm, ix, &[&funder]).unwrap();
}

fn settle(world: &mut World, creator: &Pubkey, epoch: u64, units: [u64; 4]) -> TransactionResult {
    let ix = settle_ix(
        &world.oracle.pubkey(),
        &campaign_of(world),
        creator,
        epoch,
        units,
    );
    send(&mut world.svm, ix, &[&world.oracle])
}

fn settle_with_stake(
    world: &mut World,
    creator: &Pubkey,
    epoch: u64,
    units: [u64; 4],
    stake: Pubkey,
) -> TransactionResult {
    let campaign = campaign_of(world);
    let ix = Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::Settle {
            epoch,
            units,
            evidence_hash: [epoch as u8; 32],
        }
        .data(),
        clipfi_escrow::accounts::Settle {
            oracle: world.oracle.pubkey(),
            config: config_pda(),
            campaign,
            creator: *creator,
            stake,
            position: position_pda(&campaign, creator),
            payout: payout_pda(&campaign, creator, epoch),
            system_program: SYSTEM_PROGRAM,
        }
        .to_account_metas(None),
    );
    send(&mut world.svm, ix, &[&world.oracle])
}

fn flag(world: &mut World, creator: &Pubkey, epoch: u64) -> TransactionResult {
    let campaign = campaign_of(world);
    let ix = flag_ix(
        &world.brand.pubkey(),
        &campaign,
        &payout_pda(&campaign, creator, epoch),
        3,
    );
    send(&mut world.svm, ix, &[&world.brand])
}

fn resolve(world: &mut World, creator: &Pubkey, epoch: u64, approve: bool) -> TransactionResult {
    let ix = resolve_ix(
        &world.arbiter.pubkey(),
        &campaign_of(world),
        creator,
        epoch,
        &world.oracle.pubkey(),
        approve,
    );
    send(&mut world.svm, ix, &[&world.arbiter])
}

fn release(
    world: &mut World,
    cranker: &Keypair,
    creator: &Pubkey,
    epoch: u64,
) -> TransactionResult {
    let campaign = campaign_of(world);
    let ix = release_ix(
        &cranker.pubkey(),
        &campaign,
        &world.mint,
        creator,
        &payout_pda(&campaign, creator, epoch),
        &world.oracle.pubkey(),
    );
    send(&mut world.svm, ix, &[cranker])
}

fn release_bonded(
    world: &mut World,
    cranker: &Keypair,
    creator: &Pubkey,
    epoch: u64,
) -> TransactionResult {
    let campaign = campaign_of(world);
    let ix = release_bonded_ix(
        &cranker.pubkey(),
        &campaign,
        &world.mint,
        creator,
        &payout_pda(&campaign, creator, epoch),
        &world.oracle.pubkey(),
    );
    send(&mut world.svm, ix, &[cranker])
}

fn release_with(
    world: &mut World,
    cranker: &Keypair,
    creator: &Pubkey,
    epoch: u64,
    bonus_vault: Pubkey,
    stake: Option<Pubkey>,
    stake_token: Option<Pubkey>,
) -> TransactionResult {
    let campaign = campaign_of(world);
    let ix = Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::Release {}.data(),
        clipfi_escrow::accounts::Release {
            cranker: cranker.pubkey(),
            config: config_pda(),
            campaign,
            mint: world.mint,
            vault: vault_of(&campaign, &world.mint),
            bonus_vault,
            creator: *creator,
            creator_token: get_associated_token_address(creator, &world.mint),
            position: position_pda(&campaign, creator),
            payout: payout_pda(&campaign, creator, epoch),
            rent_payer: world.oracle.pubkey(),
            stake,
            stake_token,
            associated_token_program: ATA_PROGRAM,
            token_program: TOKEN_PROGRAM,
            system_program: SYSTEM_PROGRAM,
        }
        .to_account_metas(None),
    );
    send(&mut world.svm, ix, &[cranker])
}

fn slash(world: &mut World, creator: &Pubkey, amount: u64) -> TransactionResult {
    let ix = slash_ix(
        &world.arbiter.pubkey(),
        &campaign_of(world),
        &world.mint,
        creator,
        amount,
    );
    send(&mut world.svm, ix, &[&world.arbiter])
}

fn close(world: &mut World) -> TransactionResult {
    let brand = world.brand.pubkey();
    let brand_token = get_associated_token_address(&brand, &world.mint);
    let ix = close_campaign_ix(&brand, &campaign_of(world), &world.mint, &brand_token);
    send(&mut world.svm, ix, &[&world.brand])
}

fn payout_of(world: &World, creator: &Pubkey, epoch: u64) -> Payout {
    fetch(&world.svm, &payout_pda(&campaign_of(world), creator, epoch))
}

fn position_of(world: &World, creator: &Pubkey) -> CreatorPosition {
    fetch(&world.svm, &position_pda(&campaign_of(world), creator))
}

fn stake_of(world: &World, creator: &Pubkey) -> Stake {
    fetch(&world.svm, &stake_pda(creator))
}

fn campaign_state(world: &World) -> Campaign {
    fetch(&world.svm, &campaign_of(world))
}

fn creator_balance(world: &World, creator: &Pubkey) -> u64 {
    token_balance(
        &world.svm,
        &get_associated_token_address(creator, &world.mint),
    )
}

fn bond_balance(world: &World, creator: &Pubkey) -> u64 {
    token_balance(&world.svm, &stake_token_of(creator, &world.mint))
}

fn pool_balance(world: &World) -> u64 {
    token_balance(&world.svm, &bonus_vault_pda(&world.mint))
}

fn vault_balance(world: &World) -> u64 {
    token_balance(&world.svm, &vault_of(&campaign_of(world), &world.mint))
}

#[test]
fn stake_locks_the_bond_in_a_vault_the_creator_does_not_control() {
    let mut world = World::with_config();
    let creator = funded(&mut world.svm);
    let creator_token = give_tokens(
        &mut world.svm,
        &creator.pubkey(),
        &world.mint,
        80 * CLIP_USD,
    );

    println!("stake 50 clipUSD out of 80");
    stake(&mut world, &creator, 50 * CLIP_USD).unwrap();
    let bond = stake_of(&world, &creator.pubkey());
    println!(
        "stake: creator {} token {} amount {} pending {} unstake_at {} auto_restake_bps {} slashed {}; bond vault owner {}",
        bond.creator,
        bond.token,
        bond.amount,
        bond.pending_unstake,
        bond.unstake_at,
        bond.auto_restake_bps,
        bond.slashed_total,
        token_owner(&world.svm, &bond.token)
    );
    assert_eq!(bond.creator, creator.pubkey());
    assert_eq!(bond.token, stake_token_of(&creator.pubkey(), &world.mint));
    assert_eq!(
        (
            bond.amount,
            bond.pending_unstake,
            bond.unstake_at,
            bond.auto_restake_bps,
            bond.slashed_total
        ),
        (50 * CLIP_USD, 0, 0, 0, 0)
    );
    assert_eq!(
        token_owner(&world.svm, &bond.token),
        stake_pda(&creator.pubkey())
    );
    assert_eq!(bond_balance(&world, &creator.pubkey()), 50 * CLIP_USD);
    assert_eq!(token_balance(&world.svm, &creator_token), 30 * CLIP_USD);

    println!("stake 25 more");
    stake(&mut world, &creator, 25 * CLIP_USD).unwrap();
    assert_eq!(stake_of(&world, &creator.pubkey()).amount, 75 * CLIP_USD);
    assert_eq!(bond_balance(&world, &creator.pubkey()), 75 * CLIP_USD);
    assert_eq!(token_balance(&world.svm, &creator_token), 5 * CLIP_USD);

    println!("stake 0");
    expect_error(stake(&mut world, &creator, 0), "ZeroAmount");
    println!("stake 5.000001 with 5 left");
    expect_error(
        stake(&mut world, &creator, 5 * CLIP_USD + 1),
        "insufficient funds",
    );
    assert_eq!(stake_of(&world, &creator.pubkey()).amount, 75 * CLIP_USD);
    assert_eq!(token_balance(&world.svm, &creator_token), 5 * CLIP_USD);
}

#[test]
fn a_bond_is_funded_only_by_its_owner_and_only_with_the_configured_mint() {
    let mut world = World::with_config();
    let creator = funded(&mut world.svm);
    let stranger = funded(&mut world.svm);
    let creator_token = give_tokens(
        &mut world.svm,
        &creator.pubkey(),
        &world.mint,
        50 * CLIP_USD,
    );
    let stranger_token = give_tokens(
        &mut world.svm,
        &stranger.pubkey(),
        &world.mint,
        50 * CLIP_USD,
    );

    println!("the stranger stakes into his own bond out of the creator's token account");
    let ix = Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::Stake { amount: CLIP_USD }.data(),
        clipfi_escrow::accounts::StakeTokens {
            creator: stranger.pubkey(),
            config: config_pda(),
            mint: world.mint,
            stake: stake_pda(&stranger.pubkey()),
            stake_token: stake_token_of(&stranger.pubkey(), &world.mint),
            creator_token,
            associated_token_program: ATA_PROGRAM,
            token_program: TOKEN_PROGRAM,
            system_program: SYSTEM_PROGRAM,
        }
        .to_account_metas(None),
    );
    expect_error(
        send(&mut world.svm, ix, &[&stranger]),
        "ConstraintTokenOwner",
    );

    println!("the stranger stakes his own tokens into the creator's bond account");
    let ix = Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::Stake { amount: CLIP_USD }.data(),
        clipfi_escrow::accounts::StakeTokens {
            creator: stranger.pubkey(),
            config: config_pda(),
            mint: world.mint,
            stake: stake_pda(&creator.pubkey()),
            stake_token: stake_token_of(&creator.pubkey(), &world.mint),
            creator_token: stranger_token,
            associated_token_program: ATA_PROGRAM,
            token_program: TOKEN_PROGRAM,
            system_program: SYSTEM_PROGRAM,
        }
        .to_account_metas(None),
    );
    expect_error(send(&mut world.svm, ix, &[&stranger]), "ConstraintSeeds");

    println!("the creator stakes a token of another mint");
    let other_mint = create_mint(&mut world.svm, &world.admin.pubkey());
    give_tokens(
        &mut world.svm,
        &creator.pubkey(),
        &other_mint,
        50 * CLIP_USD,
    );
    let ix = stake_ix(&creator.pubkey(), &other_mint, 10 * CLIP_USD);
    expect_error(send(&mut world.svm, ix, &[&creator]), "ConstraintHasOne");

    assert!(!exists(&world.svm, &stake_pda(&creator.pubkey())));
    assert!(!exists(&world.svm, &stake_pda(&stranger.pubkey())));
    assert_eq!(token_balance(&world.svm, &creator_token), 50 * CLIP_USD);
    assert_eq!(token_balance(&world.svm, &stranger_token), 50 * CLIP_USD);
}

#[test]
fn settle_reads_the_bond_of_the_creator_and_nobody_elses() {
    let params = CampaignParams {
        min_bond: 10 * CLIP_USD,
        ..default_params()
    };
    let mut world = world_with(params, 100 * CLIP_USD);
    let bonded = bonded_creator(&mut world, 20 * CLIP_USD);
    let (poor, forger) = (Pubkey::new_unique(), Pubkey::new_unique());

    println!("settle a creator without a bond, passing the bonded creator's stake account");
    expect_error(
        settle_with_stake(&mut world, &poor, 1, UNITS, stake_pda(&bonded.pubkey())),
        "ConstraintSeeds",
    );

    println!("a byte copy of the bonded creator's stake planted at the forger's stake address, owned by the token program");
    let data = world
        .svm
        .get_account(&stake_pda(&bonded.pubkey()))
        .unwrap()
        .data;
    put_account(&mut world.svm, stake_pda(&forger), data, TOKEN_PROGRAM);
    expect_error(settle(&mut world, &forger, 1, UNITS), "BondTooLow");

    println!("the bonded creator settles");
    settle(&mut world, &bonded.pubkey(), 1, UNITS).unwrap();
    assert_eq!(payout_of(&world, &bonded.pubkey(), 1).amount, EARNED);
    assert!(!exists(
        &world.svm,
        &position_pda(&campaign_of(&world), &poor)
    ));
    assert!(!exists(
        &world.svm,
        &position_pda(&campaign_of(&world), &forger)
    ));
}

#[test]
fn the_bonus_tier_is_chosen_at_settle_and_frozen_in_the_payout() {
    let world = World::new();
    let params = ConfigParams {
        bonus_tiers: [
            BonusTier {
                min_bond: 100 * CLIP_USD,
                bonus_bps: 300,
            },
            BonusTier {
                min_bond: 500 * CLIP_USD,
                bonus_bps: 500,
            },
            BonusTier {
                min_bond: 1_000 * CLIP_USD,
                bonus_bps: 800,
            },
        ],
        ..default_config_params(world.oracle.pubkey(), world.arbiter.pubkey())
    };
    let mut world = world.with_config_params(params);
    open_campaign(&mut world, 1, default_params(), 100 * CLIP_USD);

    for (bond, expected) in [
        (100 * CLIP_USD - 1, 0u16),
        (100 * CLIP_USD, 300),
        (999 * CLIP_USD, 500),
        (1_000 * CLIP_USD, 800),
    ] {
        let creator = bonded_creator(&mut world, bond);
        settle(&mut world, &creator.pubkey(), 1, SMALL).unwrap();
        let payout = payout_of(&world, &creator.pubkey(), 1);
        println!(
            "bond {bond}: bonus_bps {} (expected {expected})",
            payout.bonus_bps
        );
        assert_eq!(payout.bonus_bps, expected);
        assert_eq!(payout.amount, SMALL_PAY);
    }

    let climber = bonded_creator(&mut world, 100 * CLIP_USD);
    settle(&mut world, &climber.pubkey(), 1, SMALL).unwrap();
    assert_eq!(payout_of(&world, &climber.pubkey(), 1).bonus_bps, 300);

    println!("the creator bonds 900 more after epoch 1 was settled");
    give_tokens(
        &mut world.svm,
        &climber.pubkey(),
        &world.mint,
        900 * CLIP_USD,
    );
    stake(&mut world, &climber, 900 * CLIP_USD).unwrap();
    println!(
        "epoch 1 keeps bonus_bps {}",
        payout_of(&world, &climber.pubkey(), 1).bonus_bps
    );
    assert_eq!(payout_of(&world, &climber.pubkey(), 1).bonus_bps, 300);

    settle(&mut world, &climber.pubkey(), 2, SMALL).unwrap();
    println!(
        "epoch 2 with a bond of 1000: bonus_bps {}",
        payout_of(&world, &climber.pubkey(), 2).bonus_bps
    );
    assert_eq!(payout_of(&world, &climber.pubkey(), 2).bonus_bps, 800);

    println!("the creator asks to unstake 1 base unit; the pending part no longer counts");
    request_unstake(&mut world, &climber, 1).unwrap();
    settle(&mut world, &climber.pubkey(), 3, SMALL).unwrap();
    println!(
        "epoch 3 with 999.999999 bonded: bonus_bps {}",
        payout_of(&world, &climber.pubkey(), 3).bonus_bps
    );
    assert_eq!(payout_of(&world, &climber.pubkey(), 3).bonus_bps, 500);
    assert_eq!(payout_of(&world, &climber.pubkey(), 2).bonus_bps, 800);
}

#[test]
fn bonded_vesting_ignores_the_campaign_end() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let bonded = bonded_creator(&mut world, 10 * CLIP_USD);
    let leaving = bonded_creator(&mut world, 10 * CLIP_USD);
    let unbonded = Pubkey::new_unique();
    let cranker = funded(&mut world.svm);

    println!("the leaving creator asks to unstake his whole bond");
    request_unstake(&mut world, &leaving, 10 * CLIP_USD).unwrap();

    set_time(&mut world.svm, END - DAY);
    settle(&mut world, &bonded.pubkey(), 1, SMALL).unwrap();
    settle(&mut world, &leaving.pubkey(), 1, SMALL).unwrap();
    settle(&mut world, &unbonded, 1, SMALL).unwrap();
    let (bonded_unlock, leaving_unlock, unbonded_unlock) = (
        payout_of(&world, &bonded.pubkey(), 1).unlock_ts,
        payout_of(&world, &leaving.pubkey(), 1).unlock_ts,
        payout_of(&world, &unbonded, 1).unlock_ts,
    );
    println!(
        "settled one day before the end ({END}): bonded unlocks at {bonded_unlock} (now + {BONDED_VESTING}), leaving at {leaving_unlock}, unbonded at {unbonded_unlock} (now + {VESTING})"
    );
    assert_eq!(bonded_unlock, END - DAY + BONDED_VESTING);
    assert_eq!(leaving_unlock, END - DAY + VESTING);
    assert_eq!(unbonded_unlock, END - DAY + VESTING);
    assert_eq!(payout_of(&world, &leaving.pubkey(), 1).bonus_bps, 0);

    set_time(&mut world.svm, bonded_unlock - 1);
    println!("release the bonded payout one second early");
    expect_error(
        release(&mut world, &cranker, &bonded.pubkey(), 1),
        "StillVesting",
    );
    set_time(&mut world.svm, bonded_unlock);
    println!("release the bonded payout at its unlock, after the campaign end but before the regular vesting");
    release(&mut world, &cranker, &bonded.pubkey(), 1).unwrap();
    expect_error(release(&mut world, &cranker, &unbonded, 1), "StillVesting");
    expect_error(
        release(&mut world, &cranker, &leaving.pubkey(), 1),
        "StillVesting",
    );
    assert_eq!(creator_balance(&world, &bonded.pubkey()), SMALL_PAY);
}

#[test]
fn the_bonus_comes_from_the_pool_and_never_from_the_campaign_vault() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let creator = bonded_creator(&mut world, TIER_BOND);
    let cranker = funded(&mut world.svm);
    let bonus = SMALL_PAY * u64::from(TIER_BPS) / BPS;
    fund_pool(&mut world, 100_000);
    println!(
        "pool funded with 100000 base units; one payout of {SMALL_PAY} earns a bonus of {bonus}"
    );

    for epoch in 1..=3 {
        settle(&mut world, &creator.pubkey(), epoch, SMALL).unwrap();
        assert_eq!(
            payout_of(&world, &creator.pubkey(), epoch).bonus_bps,
            TIER_BPS
        );
    }
    set_time(&mut world.svm, NOW + BONDED_VESTING);

    println!("release epoch 1");
    release(&mut world, &cranker, &creator.pubkey(), 1).unwrap();
    let campaign = campaign_state(&world);
    println!(
        "creator {} pool {} vault {} paid_total {} reserved {} free {:?}",
        creator_balance(&world, &creator.pubkey()),
        pool_balance(&world),
        vault_balance(&world),
        campaign.paid_total,
        campaign.reserved,
        campaign.free_budget()
    );
    assert_eq!(
        creator_balance(&world, &creator.pubkey()),
        SMALL_PAY + bonus
    );
    assert_eq!(pool_balance(&world), 100_000 - bonus);
    assert_eq!(vault_balance(&world), 100 * CLIP_USD - SMALL_PAY);
    assert_eq!(
        (campaign.paid_total, campaign.reserved),
        (SMALL_PAY, 2 * SMALL_PAY)
    );
    assert_eq!(campaign.free_budget(), Some(100 * CLIP_USD - 3 * SMALL_PAY));

    println!(
        "release epoch 2: the pool holds 40000, less than the bonus, so nothing is taken from it"
    );
    release(&mut world, &cranker, &creator.pubkey(), 2).unwrap();
    println!(
        "creator {} pool {}",
        creator_balance(&world, &creator.pubkey()),
        pool_balance(&world)
    );
    assert_eq!(
        creator_balance(&world, &creator.pubkey()),
        2 * SMALL_PAY + bonus
    );
    assert_eq!(pool_balance(&world), 40_000);
    assert!(!exists(
        &world.svm,
        &payout_pda(&campaign_of(&world), &creator.pubkey(), 2)
    ));

    println!("top the pool up to exactly one bonus");
    fund_pool(&mut world, 20_000);
    release(&mut world, &cranker, &creator.pubkey(), 3).unwrap();
    println!(
        "creator {} pool {}",
        creator_balance(&world, &creator.pubkey()),
        pool_balance(&world)
    );
    assert_eq!(
        creator_balance(&world, &creator.pubkey()),
        3 * SMALL_PAY + 2 * bonus
    );
    assert_eq!(pool_balance(&world), 0);

    let campaign = campaign_state(&world);
    assert_eq!(vault_balance(&world), 100 * CLIP_USD - 3 * SMALL_PAY);
    assert_eq!((campaign.paid_total, campaign.reserved), (3 * SMALL_PAY, 0));
    assert_eq!(
        position_of(&world, &creator.pubkey()).claimed_total,
        3 * SMALL_PAY
    );
}

#[test]
fn bonus_and_restake_are_rounded_down() {
    let params = CampaignParams {
        rate_per_mille: [1, 0, 0, 0],
        ..default_params()
    };
    let mut world = world_with(params, CLIP_USD);
    let tiny = bonded_creator(&mut world, TIER_BOND);
    let bigger = bonded_creator(&mut world, TIER_BOND);
    let cranker = funded(&mut world.svm);
    set_auto_restake(&mut world, &tiny, 2500).unwrap();
    set_auto_restake(&mut world, &bigger, 2500).unwrap();
    fund_pool(&mut world, CLIP_USD);

    println!("rate of 1 base unit per 1000 views: 1999 views pay 1, 3333000 views pay 3333");
    settle(&mut world, &tiny.pubkey(), 1, [1_999, 0, 0, 0]).unwrap();
    settle(&mut world, &bigger.pubkey(), 1, [3_333_000, 0, 0, 0]).unwrap();
    assert_eq!(payout_of(&world, &tiny.pubkey(), 1).amount, 1);
    assert_eq!(payout_of(&world, &bigger.pubkey(), 1).amount, 3_333);

    set_time(&mut world.svm, NOW + BONDED_VESTING);
    release_bonded(&mut world, &cranker, &tiny.pubkey(), 1).unwrap();
    release_bonded(&mut world, &cranker, &bigger.pubkey(), 1).unwrap();
    println!(
        "payout 1 at 300 bps bonus and 2500 bps restake: creator got {}, bond {} | payout 3333: creator got {}, bond {} | pool {}",
        creator_balance(&world, &tiny.pubkey()),
        stake_of(&world, &tiny.pubkey()).amount,
        creator_balance(&world, &bigger.pubkey()),
        stake_of(&world, &bigger.pubkey()).amount,
        pool_balance(&world)
    );
    assert_eq!(creator_balance(&world, &tiny.pubkey()), 1);
    assert_eq!(stake_of(&world, &tiny.pubkey()).amount, TIER_BOND);
    assert_eq!(creator_balance(&world, &bigger.pubkey()), 2_500 + 99);
    assert_eq!(stake_of(&world, &bigger.pubkey()).amount, TIER_BOND + 833);
    assert_eq!(bond_balance(&world, &bigger.pubkey()), TIER_BOND + 833);
    assert_eq!(pool_balance(&world), CLIP_USD - 99);
    assert_eq!(campaign_state(&world).paid_total, 3_334);
}

#[test]
fn a_flag_freezes_a_bonded_payout_and_an_approved_one_still_gets_its_bonus() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let creator = bonded_creator(&mut world, TIER_BOND);
    let cranker = funded(&mut world.svm);
    fund_pool(&mut world, 10 * CLIP_USD);
    let bonus = EARNED * u64::from(TIER_BPS) / BPS;

    settle(&mut world, &creator.pubkey(), 1, UNITS).unwrap();
    flag(&mut world, &creator.pubkey(), 1).unwrap();
    set_time(&mut world.svm, NOW + BONDED_VESTING);
    println!("release a flagged bonded payout after its unlock");
    expect_error(
        release(&mut world, &cranker, &creator.pubkey(), 1),
        "PayoutFrozen",
    );

    println!("the arbiter approves, the release pays amount and bonus");
    resolve(&mut world, &creator.pubkey(), 1, true).unwrap();
    assert_eq!(
        payout_of(&world, &creator.pubkey(), 1).status,
        PayoutStatus::Approved
    );
    release(&mut world, &cranker, &creator.pubkey(), 1).unwrap();
    println!(
        "creator {} = {EARNED} + {bonus}; pool {}",
        creator_balance(&world, &creator.pubkey()),
        pool_balance(&world)
    );
    assert_eq!(creator_balance(&world, &creator.pubkey()), EARNED + bonus);
    assert_eq!(pool_balance(&world), 10 * CLIP_USD - bonus);
}

#[test]
fn auto_restake_is_snapshotted_at_settle_and_enforced_at_release() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let creator = bonded_creator(&mut world, 50 * CLIP_USD);
    let cranker = funded(&mut world.svm);
    let restaked = EARNED * 2_500 / BPS;

    set_auto_restake(&mut world, &creator, 2_500).unwrap();
    assert_eq!(stake_of(&world, &creator.pubkey()).auto_restake_bps, 2_500);
    settle(&mut world, &creator.pubkey(), 1, UNITS).unwrap();
    println!(
        "settled with auto-restake 2500: payout restake_bps {}",
        payout_of(&world, &creator.pubkey(), 1).restake_bps
    );
    assert_eq!(payout_of(&world, &creator.pubkey(), 1).restake_bps, 2_500);

    println!("the creator drops auto-restake to 0 after the settle");
    set_auto_restake(&mut world, &creator, 0).unwrap();
    assert_eq!(payout_of(&world, &creator.pubkey(), 1).restake_bps, 2_500);

    set_time(&mut world.svm, NOW + BONDED_VESTING);
    println!("release without the stake accounts");
    expect_error(
        release(&mut world, &cranker, &creator.pubkey(), 1),
        "StakeRequired",
    );
    assert_eq!(campaign_state(&world).reserved, EARNED);

    println!("release with the stake accounts");
    release_bonded(&mut world, &cranker, &creator.pubkey(), 1).unwrap();
    let bond = stake_of(&world, &creator.pubkey());
    let campaign = campaign_state(&world);
    println!(
        "creator {} (= {EARNED} - {restaked}), bond {} (token {}), vault {}, paid_total {}, claimed {}",
        creator_balance(&world, &creator.pubkey()),
        bond.amount,
        bond_balance(&world, &creator.pubkey()),
        vault_balance(&world),
        campaign.paid_total,
        position_of(&world, &creator.pubkey()).claimed_total
    );
    assert_eq!(
        creator_balance(&world, &creator.pubkey()),
        EARNED - restaked
    );
    assert_eq!(bond.amount, 50 * CLIP_USD + restaked);
    assert_eq!(
        bond_balance(&world, &creator.pubkey()),
        50 * CLIP_USD + restaked
    );
    assert_eq!(vault_balance(&world), 65 * CLIP_USD);
    assert_eq!((campaign.paid_total, campaign.reserved), (EARNED, 0));
    assert_eq!(position_of(&world, &creator.pubkey()).claimed_total, EARNED);

    println!("epoch 2 settled after auto-restake was set to 0 releases without the stake accounts");
    settle(&mut world, &creator.pubkey(), 2, SMALL).unwrap();
    assert_eq!(payout_of(&world, &creator.pubkey(), 2).restake_bps, 0);
    set_time(&mut world.svm, NOW + 2 * BONDED_VESTING);
    release(&mut world, &cranker, &creator.pubkey(), 2).unwrap();
    assert_eq!(
        creator_balance(&world, &creator.pubkey()),
        EARNED - restaked + SMALL_PAY
    );
    assert_eq!(
        stake_of(&world, &creator.pubkey()).amount,
        50 * CLIP_USD + restaked
    );
}

#[test]
fn full_auto_restake_sends_the_whole_payout_to_the_bond() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let creator = bonded_creator(&mut world, 10 * CLIP_USD);
    let stranger = funded(&mut world.svm);
    let cranker = funded(&mut world.svm);

    println!("set_auto_restake 10001 bps");
    expect_error(set_auto_restake(&mut world, &creator, 10_001), "InvalidBps");
    println!("a stranger sets the creator's auto-restake");
    let ix = Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::SetAutoRestake { bps: 10_000 }.data(),
        clipfi_escrow::accounts::SetAutoRestake {
            creator: stranger.pubkey(),
            stake: stake_pda(&creator.pubkey()),
        }
        .to_account_metas(None),
    );
    expect_error(send(&mut world.svm, ix, &[&stranger]), "ConstraintSeeds");
    assert_eq!(stake_of(&world, &creator.pubkey()).auto_restake_bps, 0);

    println!("set_auto_restake 10000 bps, settle, release");
    set_auto_restake(&mut world, &creator, 10_000).unwrap();
    settle(&mut world, &creator.pubkey(), 1, SMALL).unwrap();
    set_time(&mut world.svm, NOW + BONDED_VESTING);
    release_bonded(&mut world, &cranker, &creator.pubkey(), 1).unwrap();
    println!(
        "creator holds {}, bond {}, vault {}",
        creator_balance(&world, &creator.pubkey()),
        stake_of(&world, &creator.pubkey()).amount,
        vault_balance(&world)
    );
    assert_eq!(creator_balance(&world, &creator.pubkey()), 0);
    assert_eq!(
        stake_of(&world, &creator.pubkey()).amount,
        10 * CLIP_USD + SMALL_PAY
    );
    assert_eq!(
        bond_balance(&world, &creator.pubkey()),
        10 * CLIP_USD + SMALL_PAY
    );
    assert_eq!(vault_balance(&world), 100 * CLIP_USD - SMALL_PAY);
    assert_eq!(campaign_state(&world).paid_total, SMALL_PAY);
}

#[test]
fn release_rejects_foreign_stake_accounts_and_a_foreign_bonus_vault() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let alice = bonded_creator(&mut world, 50 * CLIP_USD);
    let bob = bonded_creator(&mut world, 50 * CLIP_USD);
    let cranker = funded(&mut world.svm);
    set_auto_restake(&mut world, &alice, 2_500).unwrap();
    settle(&mut world, &alice.pubkey(), 1, SMALL).unwrap();
    set_time(&mut world.svm, NOW + BONDED_VESTING);
    let payout = payout_pda(&campaign_of(&world), &alice.pubkey(), 1);
    let mint = world.mint;
    let bonus_vault = bonus_vault_pda(&mint);
    let brand_token = get_associated_token_address(&world.brand.pubkey(), &mint);

    println!("release alice's payout with bob's stake accounts");
    expect_error(
        release_with(
            &mut world,
            &cranker,
            &alice.pubkey(),
            1,
            bonus_vault,
            Some(stake_pda(&bob.pubkey())),
            Some(stake_token_of(&bob.pubkey(), &mint)),
        ),
        "ConstraintSeeds",
    );

    println!("release with alice's stake but bob's bond token account");
    expect_error(
        release_with(
            &mut world,
            &cranker,
            &alice.pubkey(),
            1,
            bonus_vault,
            Some(stake_pda(&alice.pubkey())),
            Some(stake_token_of(&bob.pubkey(), &mint)),
        ),
        "Unauthorized",
    );

    println!("release with the brand's token account in place of the bonus vault");
    expect_error(
        release_with(
            &mut world,
            &cranker,
            &alice.pubkey(),
            1,
            brand_token,
            Some(stake_pda(&alice.pubkey())),
            Some(stake_token_of(&alice.pubkey(), &mint)),
        ),
        "ConstraintHasOne",
    );

    assert!(exists(&world.svm, &payout));
    assert_eq!(stake_of(&world, &bob.pubkey()).amount, 50 * CLIP_USD);
    assert_eq!(bond_balance(&world, &bob.pubkey()), 50 * CLIP_USD);
    assert_eq!(campaign_state(&world).reserved, SMALL_PAY);

    println!("release with alice's own accounts");
    release_bonded(&mut world, &cranker, &alice.pubkey(), 1).unwrap();
    assert_eq!(
        stake_of(&world, &alice.pubkey()).amount,
        50 * CLIP_USD + SMALL_PAY / 4
    );
}

#[test]
fn unstaking_takes_the_cooldown_and_a_new_request_restarts_it() {
    let mut world = World::with_config();
    let creator = bonded_creator(&mut world, 100 * CLIP_USD);

    println!("request_unstake 0");
    expect_error(request_unstake(&mut world, &creator, 0), "ZeroAmount");
    println!("request_unstake 100.000001 of a 100 bond");
    expect_error(
        request_unstake(&mut world, &creator, 100 * CLIP_USD + 1),
        "InsufficientStake",
    );
    println!("withdraw_stake with nothing pending");
    expect_error(withdraw_stake(&mut world, &creator), "NothingToWithdraw");

    request_unstake(&mut world, &creator, 40 * CLIP_USD).unwrap();
    let bond = stake_of(&world, &creator.pubkey());
    println!(
        "requested 40: amount {} pending {} unstake_at {} (now + {UNSTAKE_COOLDOWN})",
        bond.amount, bond.pending_unstake, bond.unstake_at
    );
    assert_eq!(
        (bond.amount, bond.pending_unstake),
        (100 * CLIP_USD, 40 * CLIP_USD)
    );
    assert_eq!(bond.unstake_at, NOW + UNSTAKE_COOLDOWN);
    assert_eq!(bond.bonded(), 60 * CLIP_USD);

    println!("request_unstake 60.000001 more with 60 still bonded");
    expect_error(
        request_unstake(&mut world, &creator, 60 * CLIP_USD + 1),
        "InsufficientStake",
    );

    set_time(&mut world.svm, NOW + 10 * DAY);
    println!("ten days later: request 10 more, the cooldown restarts for the whole pending amount");
    request_unstake(&mut world, &creator, 10 * CLIP_USD).unwrap();
    let bond = stake_of(&world, &creator.pubkey());
    println!(
        "pending {} unstake_at {}",
        bond.pending_unstake, bond.unstake_at
    );
    assert_eq!(bond.pending_unstake, 50 * CLIP_USD);
    assert_eq!(bond.unstake_at, NOW + 10 * DAY + UNSTAKE_COOLDOWN);

    set_time(&mut world.svm, NOW + UNSTAKE_COOLDOWN);
    println!("withdraw at the first deadline");
    expect_error(withdraw_stake(&mut world, &creator), "UnstakeNotReady");
    set_time(&mut world.svm, NOW + 10 * DAY + UNSTAKE_COOLDOWN - 1);
    println!("withdraw one second before the second deadline");
    expect_error(withdraw_stake(&mut world, &creator), "UnstakeNotReady");
    assert_eq!(creator_balance(&world, &creator.pubkey()), 0);

    set_time(&mut world.svm, NOW + 10 * DAY + UNSTAKE_COOLDOWN);
    println!("withdraw at the second deadline");
    withdraw_stake(&mut world, &creator).unwrap();
    let bond = stake_of(&world, &creator.pubkey());
    println!(
        "creator holds {}, bond vault {}, amount {} pending {} unstake_at {}",
        creator_balance(&world, &creator.pubkey()),
        bond_balance(&world, &creator.pubkey()),
        bond.amount,
        bond.pending_unstake,
        bond.unstake_at
    );
    assert_eq!(creator_balance(&world, &creator.pubkey()), 50 * CLIP_USD);
    assert_eq!(bond_balance(&world, &creator.pubkey()), 50 * CLIP_USD);
    assert_eq!(
        (bond.amount, bond.pending_unstake, bond.unstake_at),
        (50 * CLIP_USD, 0, 0)
    );

    println!("withdraw again");
    expect_error(withdraw_stake(&mut world, &creator), "NothingToWithdraw");
}

#[test]
fn a_pending_unstake_stops_counting_as_bond_but_stays_slashable() {
    let params = CampaignParams {
        min_bond: 10 * CLIP_USD,
        ..default_params()
    };
    let mut world = world_with(params, 100 * CLIP_USD);
    let creator = bonded_creator(&mut world, 10 * CLIP_USD);

    settle(&mut world, &creator.pubkey(), 1, SMALL).unwrap();
    println!("the creator asks to unstake 1 base unit, then epoch 2 is settled");
    request_unstake(&mut world, &creator, 1).unwrap();
    expect_error(
        settle(&mut world, &creator.pubkey(), 2, SMALL),
        "BondTooLow",
    );

    println!("during the cooldown the arbiter slashes the full 10");
    slash(&mut world, &creator.pubkey(), 10 * CLIP_USD).unwrap();
    let bond = stake_of(&world, &creator.pubkey());
    println!(
        "amount {} pending {} slashed {} vault {}",
        bond.amount,
        bond.pending_unstake,
        bond.slashed_total,
        vault_balance(&world)
    );
    assert_eq!(
        (bond.amount, bond.pending_unstake, bond.slashed_total),
        (0, 0, 10 * CLIP_USD)
    );
    assert_eq!(vault_balance(&world), 110 * CLIP_USD);

    set_time(&mut world.svm, NOW + UNSTAKE_COOLDOWN);
    println!("withdraw after the cooldown with nothing left");
    expect_error(withdraw_stake(&mut world, &creator), "NothingToWithdraw");
    assert_eq!(creator_balance(&world, &creator.pubkey()), 0);
}

#[test]
fn withdraw_only_to_the_creators_own_account_and_only_from_the_real_bond_vault() {
    let mut world = World::with_config();
    let creator = bonded_creator(&mut world, 100 * CLIP_USD);
    let stranger = funded(&mut world.svm);
    let stranger_token = give_tokens(&mut world.svm, &stranger.pubkey(), &world.mint, 0);
    request_unstake(&mut world, &creator, 40 * CLIP_USD).unwrap();
    set_time(&mut world.svm, NOW + UNSTAKE_COOLDOWN);

    let (mint, stake) = (world.mint, stake_pda(&creator.pubkey()));
    let withdraw = move |signer: &Pubkey, stake_token: Pubkey, creator_token: Pubkey| {
        Instruction::new_with_bytes(
            clipfi_escrow::id(),
            &clipfi_escrow::instruction::WithdrawStake {}.data(),
            clipfi_escrow::accounts::WithdrawStake {
                creator: *signer,
                config: config_pda(),
                mint,
                stake,
                stake_token,
                creator_token,
                token_program: TOKEN_PROGRAM,
            }
            .to_account_metas(None),
        )
    };

    println!("the stranger withdraws the creator's pending unstake into his own account");
    let ix = withdraw(
        &stranger.pubkey(),
        stake_token_of(&creator.pubkey(), &world.mint),
        stranger_token,
    );
    expect_error(send(&mut world.svm, ix, &[&stranger]), "ConstraintSeeds");

    println!("the creator withdraws into the stranger's token account");
    let ix = withdraw(
        &creator.pubkey(),
        stake_token_of(&creator.pubkey(), &world.mint),
        stranger_token,
    );
    expect_error(
        send(&mut world.svm, ix, &[&creator]),
        "ConstraintTokenOwner",
    );

    println!("the creator withdraws from a token account that is not the bond vault");
    let ix = withdraw(
        &creator.pubkey(),
        stranger_token,
        get_associated_token_address(&creator.pubkey(), &world.mint),
    );
    expect_error(send(&mut world.svm, ix, &[&creator]), "ConstraintAddress");

    assert_eq!(
        stake_of(&world, &creator.pubkey()).pending_unstake,
        40 * CLIP_USD
    );
    assert_eq!(bond_balance(&world, &creator.pubkey()), 100 * CLIP_USD);
    assert_eq!(token_balance(&world.svm, &stranger_token), 0);

    println!("the creator withdraws properly");
    withdraw_stake(&mut world, &creator).unwrap();
    assert_eq!(creator_balance(&world, &creator.pubkey()), 40 * CLIP_USD);
}

#[test]
fn slashing_returns_the_bond_to_the_brands_budget() {
    let mut world = World::with_funded_campaign(1, EARNED);
    let cheater = bonded_creator(&mut world, 100 * CLIP_USD);
    let honest = Pubkey::new_unique();
    let cranker = funded(&mut world.svm);
    let brand_token = get_associated_token_address(&world.brand.pubkey(), &world.mint);

    settle(&mut world, &cheater.pubkey(), 1, UNITS).unwrap();
    println!("the whole budget is reserved by the cheater");
    expect_error(settle(&mut world, &honest, 1, UNITS), "NothingToSettle");

    flag(&mut world, &cheater.pubkey(), 1).unwrap();
    resolve(&mut world, &cheater.pubkey(), 1, false).unwrap();
    println!("the arbiter rejected the payout; now he slashes 20 of the 100 bond");
    slash(&mut world, &cheater.pubkey(), 20 * CLIP_USD).unwrap();
    let bond = stake_of(&world, &cheater.pubkey());
    let campaign = campaign_state(&world);
    println!(
        "vault {} funded_total {} free {:?} | bond amount {} slashed_total {} bond vault {}",
        vault_balance(&world),
        campaign.funded_total,
        campaign.free_budget(),
        bond.amount,
        bond.slashed_total,
        bond_balance(&world, &cheater.pubkey())
    );
    assert_eq!(vault_balance(&world), EARNED + 20 * CLIP_USD);
    assert_eq!(campaign.funded_total, EARNED + 20 * CLIP_USD);
    assert_eq!(campaign.free_budget(), Some(EARNED + 20 * CLIP_USD));
    assert_eq!(
        (bond.amount, bond.slashed_total),
        (80 * CLIP_USD, 20 * CLIP_USD)
    );
    assert_eq!(bond_balance(&world, &cheater.pubkey()), 80 * CLIP_USD);

    println!("the honest creator is paid in full, partly from the slashed bond");
    settle(&mut world, &honest, 1, UNITS).unwrap();
    assert_eq!(payout_of(&world, &honest, 1).amount, EARNED);
    assert_eq!(campaign_state(&world).free_budget(), Some(20 * CLIP_USD));

    set_time(&mut world.svm, END + VESTING);
    release(&mut world, &cranker, &honest, 1).unwrap();
    close(&mut world).unwrap();
    let refunded = token_balance(&world.svm, &brand_token);
    println!(
        "honest creator {}, brand refund {}, budget {EARNED} + slashed {}",
        creator_balance(&world, &honest),
        refunded,
        20 * CLIP_USD
    );
    assert_eq!(creator_balance(&world, &honest), EARNED);
    assert_eq!(refunded, 20 * CLIP_USD);
    assert_eq!(
        creator_balance(&world, &honest) + refunded,
        EARNED + 20 * CLIP_USD
    );
    assert_eq!(campaign_state(&world).status, CampaignStatus::Closed);
}

#[test]
fn slash_is_bounded_and_arbiter_only() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let creator = bonded_creator(&mut world, 50 * CLIP_USD);
    let campaign = campaign_of(&world);
    let brand = world.brand.pubkey();

    println!("slash 0");
    expect_error(slash(&mut world, &creator.pubkey(), 0), "ZeroAmount");
    println!("slash 50.000001 of a 50 bond");
    expect_error(
        slash(&mut world, &creator.pubkey(), 50 * CLIP_USD + 1),
        "InsufficientStake",
    );

    for (name, signer) in [
        ("brand", &world.brand),
        ("oracle", &world.oracle),
        ("creator", &creator),
    ] {
        println!("the {name} slashes as if he were the arbiter");
        let ix = slash_ix(
            &signer.pubkey(),
            &campaign,
            &world.mint,
            &creator.pubkey(),
            CLIP_USD,
        );
        expect_error(send(&mut world.svm, ix, &[signer]), "ConstraintHasOne");
    }

    println!("slash into the vault of another campaign");
    let ix = create_campaign_ix(&brand, &world.mint, 2, default_params());
    send(&mut world.svm, ix, &[&world.brand]).unwrap();
    let other_vault = vault_of(&campaign_pda(&brand, 2), &world.mint);
    let ix = Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::Slash { amount: CLIP_USD }.data(),
        clipfi_escrow::accounts::Slash {
            arbiter: world.arbiter.pubkey(),
            config: config_pda(),
            campaign,
            mint: world.mint,
            vault: other_vault,
            creator: creator.pubkey(),
            stake: stake_pda(&creator.pubkey()),
            stake_token: stake_token_of(&creator.pubkey(), &world.mint),
            token_program: TOKEN_PROGRAM,
        }
        .to_account_metas(None),
    );
    expect_error(
        send(&mut world.svm, ix, &[&world.arbiter]),
        "ConstraintHasOne",
    );
    assert_eq!(stake_of(&world, &creator.pubkey()).amount, 50 * CLIP_USD);
    assert_eq!(token_balance(&world.svm, &other_vault), 0);

    println!("slash exactly the whole bond, then one more unit");
    slash(&mut world, &creator.pubkey(), 50 * CLIP_USD).unwrap();
    assert_eq!(stake_of(&world, &creator.pubkey()).amount, 0);
    assert_eq!(vault_balance(&world), 150 * CLIP_USD);
    expect_error(slash(&mut world, &creator.pubkey(), 1), "InsufficientStake");

    set_time(&mut world.svm, END + VESTING);
    close(&mut world).unwrap();
    println!("slash into a closed campaign whose vault is gone");
    expect_error(
        slash(&mut world, &creator.pubkey(), 1),
        "AccountNotInitialized",
    );
}

#[test]
fn whole_bonded_campaign_every_token_is_accounted_for() {
    let budget = 100 * CLIP_USD;
    let mut world = World::with_funded_campaign(1, budget);
    let brand_token = get_associated_token_address(&world.brand.pubkey(), &world.mint);
    let cranker = funded(&mut world.svm);
    let alice = bonded_creator(&mut world, TIER_BOND);
    let cheater = bonded_creator(&mut world, 50 * CLIP_USD);
    let una = Pubkey::new_unique();
    set_auto_restake(&mut world, &alice, 2_500).unwrap();
    fund_pool(&mut world, 10 * CLIP_USD);

    settle(&mut world, &alice.pubkey(), 1, UNITS).unwrap();
    settle(&mut world, &cheater.pubkey(), 1, UNITS).unwrap();
    settle(&mut world, &una, 1, UNITS).unwrap();
    println!(
        "epoch 1: alice {} (bonded, tier {TIER_BPS} bps), cheater {}, una {} (unbonded, got what was left)",
        payout_of(&world, &alice.pubkey(), 1).amount,
        payout_of(&world, &cheater.pubkey(), 1).amount,
        payout_of(&world, &una, 1).amount
    );
    assert_eq!(payout_of(&world, &una, 1).amount, 30 * CLIP_USD);

    println!("the brand flags the cheater, the arbiter rejects and slashes 20 of the 50 bond");
    flag(&mut world, &cheater.pubkey(), 1).unwrap();
    resolve(&mut world, &cheater.pubkey(), 1, false).unwrap();
    slash(&mut world, &cheater.pubkey(), 20 * CLIP_USD).unwrap();
    assert_eq!(campaign_state(&world).funded_total, budget + 20 * CLIP_USD);

    set_time(&mut world.svm, NOW + DAY);
    settle(&mut world, &una, 2, UNITS).unwrap();
    println!(
        "epoch 2: una gets the rest of her limit: {}",
        payout_of(&world, &una, 2).amount
    );
    assert_eq!(payout_of(&world, &una, 2).amount, LIMIT - 30 * CLIP_USD);

    set_time(&mut world.svm, NOW + BONDED_VESTING);
    println!("day 7: alice releases early with her bonus and 25% auto-restake");
    release_bonded(&mut world, &cranker, &alice.pubkey(), 1).unwrap();
    let alice_restake = EARNED / 4;
    let alice_bonus = EARNED * u64::from(TIER_BPS) / BPS;
    assert_eq!(
        creator_balance(&world, &alice.pubkey()),
        EARNED - alice_restake + alice_bonus
    );
    assert_eq!(
        stake_of(&world, &alice.pubkey()).amount,
        TIER_BOND + alice_restake
    );

    set_time(&mut world.svm, END + VESTING);
    release(&mut world, &cranker, &una, 1).unwrap();
    release(&mut world, &cranker, &una, 2).unwrap();
    close(&mut world).unwrap();

    let campaign = campaign_state(&world);
    let refunded = token_balance(&world.svm, &brand_token);
    let paid = creator_balance(&world, &alice.pubkey()) - alice_bonus
        + alice_restake
        + creator_balance(&world, &una);
    let bonds = bond_balance(&world, &alice.pubkey()) + bond_balance(&world, &cheater.pubkey());
    let everything = creator_balance(&world, &alice.pubkey())
        + creator_balance(&world, &una)
        + bonds
        + pool_balance(&world)
        + refunded;
    println!(
        "alice {} una {} | bonds {} (alice {}, cheater {}) | pool {} | refund {} | paid_total {} | sum {everything} of {} put in",
        creator_balance(&world, &alice.pubkey()),
        creator_balance(&world, &una),
        bonds,
        bond_balance(&world, &alice.pubkey()),
        bond_balance(&world, &cheater.pubkey()),
        pool_balance(&world),
        refunded,
        campaign.paid_total,
        budget + 10 * CLIP_USD + TIER_BOND + 50 * CLIP_USD
    );
    assert_eq!(creator_balance(&world, &una), LIMIT);
    assert_eq!(creator_balance(&world, &cheater.pubkey()), 0);
    assert_eq!(bond_balance(&world, &cheater.pubkey()), 30 * CLIP_USD);
    assert_eq!(pool_balance(&world), 10 * CLIP_USD - alice_bonus);
    assert_eq!(refunded, budget + 20 * CLIP_USD - EARNED - LIMIT);
    assert_eq!(paid + refunded, budget + 20 * CLIP_USD);
    assert_eq!(
        (campaign.paid_total, campaign.reserved),
        (EARNED + LIMIT, 0)
    );
    assert_eq!(
        everything,
        budget + 10 * CLIP_USD + TIER_BOND + 50 * CLIP_USD
    );
    assert_eq!(campaign.status, CampaignStatus::Closed);
}
