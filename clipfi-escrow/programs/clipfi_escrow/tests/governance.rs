#![allow(clippy::result_large_err)]

mod common;

use {
    anchor_lang::{
        prelude::Pubkey, solana_program::instruction::Instruction, InstructionData, ToAccountMetas,
    },
    anchor_spl::associated_token::get_associated_token_address,
    clipfi_escrow::{
        BonusTier, Campaign, CampaignParams, CampaignStatus, Config, ConfigParams, Payout,
    },
    common::*,
    litesvm::types::TransactionResult,
    solana_keypair::Keypair,
    solana_signer::Signer,
};

const UNITS: [u64; 4] = [10_000, 2_000, 0, 100];
const EARNED: u64 = 35 * CLIP_USD;
const END: i64 = NOW + 30 * DAY;
const SMALL: [u64; 4] = [1_000, 0, 0, 0];
const SMALL_PAY: u64 = 2 * CLIP_USD;

fn campaign_of(world: &World) -> Pubkey {
    campaign_pda(&world.brand.pubkey(), 1)
}

fn bonded_creator(world: &mut World, amount: u64) -> Keypair {
    let creator = funded(&mut world.svm);
    give_tokens(&mut world.svm, &creator.pubkey(), &world.mint, amount);
    let ix = stake_ix(&creator.pubkey(), &world.mint, amount);
    send(&mut world.svm, ix, &[&creator]).unwrap();
    creator
}

fn settle_on(
    world: &mut World,
    oracle: &Keypair,
    campaign: &Pubkey,
    creator: &Pubkey,
    epoch: u64,
    units: [u64; 4],
) -> TransactionResult {
    let ix = settle_ix(&oracle.pubkey(), campaign, creator, epoch, units);
    send(&mut world.svm, ix, &[oracle])
}

fn settle(world: &mut World, creator: &Pubkey, epoch: u64, units: [u64; 4]) -> TransactionResult {
    let campaign = campaign_of(world);
    let oracle = world.oracle.insecure_clone();
    settle_on(world, &oracle, &campaign, creator, epoch, units)
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

fn close(world: &mut World) -> TransactionResult {
    let brand = world.brand.pubkey();
    let brand_token = get_associated_token_address(&brand, &world.mint);
    let ix = close_campaign_ix(&brand, &campaign_of(world), &world.mint, &brand_token);
    send(&mut world.svm, ix, &[&world.brand])
}

fn propose_rates(world: &mut World, rates: [u64; 4]) -> TransactionResult {
    let ix = propose_rates_ix(&world.brand.pubkey(), &campaign_of(world), rates);
    send(&mut world.svm, ix, &[&world.brand])
}

fn propose_standards(world: &mut World, hash: [u8; 32]) -> TransactionResult {
    let ix = propose_standards_ix(&world.brand.pubkey(), &campaign_of(world), hash);
    send(&mut world.svm, ix, &[&world.brand])
}

fn rollover(world: &mut World, target_campaign: &Pubkey) -> TransactionResult {
    let ix = rollover_ix(
        &world.brand.pubkey(),
        &campaign_of(world),
        target_campaign,
        &world.mint,
    );
    send(&mut world.svm, ix, &[&world.brand])
}

fn update_config(world: &mut World, admin: &Keypair, params: ConfigParams) -> TransactionResult {
    let ix = update_config_ix(&admin.pubkey(), params);
    send(&mut world.svm, ix, &[admin])
}

fn set_paused(world: &mut World, admin: &Keypair, paused: bool) -> TransactionResult {
    let ix = set_paused_ix(&admin.pubkey(), paused);
    send(&mut world.svm, ix, &[admin])
}

fn config_state(world: &World) -> Config {
    fetch(&world.svm, &config_pda())
}

fn campaign_state(world: &World) -> Campaign {
    fetch(&world.svm, &campaign_of(world))
}

fn payout_of(world: &World, creator: &Pubkey, epoch: u64) -> Payout {
    fetch(&world.svm, &payout_pda(&campaign_of(world), creator, epoch))
}

fn creator_balance(world: &World, creator: &Pubkey) -> u64 {
    token_balance(
        &world.svm,
        &get_associated_token_address(creator, &world.mint),
    )
}

fn tier(min_bond: u64, bonus_bps: u16) -> BonusTier {
    BonusTier {
        min_bond,
        bonus_bps,
    }
}

#[test]
fn config_stores_the_bond_rules_and_owns_the_bonus_vault() {
    let world = World::with_config();
    let config = config_state(&world);
    println!(
        "config: bonus_vault {} (owner {}) bonded_vesting {} unstake_cooldown {} notice {} tiers {:?} paused {}",
        config.bonus_vault,
        token_owner(&world.svm, &config.bonus_vault),
        config.bonded_vesting_secs,
        config.unstake_cooldown_secs,
        config.notice_secs,
        config.bonus_tiers,
        config.paused
    );
    assert_eq!(config.bonus_vault, bonus_vault_pda(&world.mint));
    assert_eq!(token_owner(&world.svm, &config.bonus_vault), config_pda());
    assert_eq!(token_balance(&world.svm, &config.bonus_vault), 0);
    assert_eq!(config.bonded_vesting_secs, BONDED_VESTING);
    assert_eq!(config.unstake_cooldown_secs, UNSTAKE_COOLDOWN);
    assert_eq!(config.notice_secs, NOTICE);
    assert_eq!(config.bonus_tiers[0], tier(TIER_BOND, TIER_BPS));
    assert_eq!(config.bonus_tiers[1], BonusTier::default());
    assert_eq!(config.bonus_tiers[2], BonusTier::default());
    assert!(!config.paused);
    assert_eq!(config.bonus_bps_for(TIER_BOND - 1), 0);
    assert_eq!(config.bonus_bps_for(TIER_BOND), TIER_BPS);
    assert_eq!(config.bonus_bps_for(u64::MAX), TIER_BPS);
}

type Mutation = Box<dyn Fn(ConfigParams) -> ConfigParams>;

#[test]
fn config_rules_are_validated() {
    let base = |world: &World| default_config_params(world.oracle.pubkey(), world.arbiter.pubkey());
    let cases: Vec<(&str, Mutation, &str)> = vec![
        (
            "bonded vesting of 0",
            Box::new(|p| ConfigParams {
                bonded_vesting_secs: 0,
                ..p
            }),
            "InvalidVesting",
        ),
        (
            "bonded vesting longer than the regular vesting",
            Box::new(|p| ConfigParams {
                bonded_vesting_secs: VESTING + 1,
                ..p
            }),
            "InvalidVesting",
        ),
        (
            "unstake cooldown shorter than the vesting",
            Box::new(|p| ConfigParams {
                unstake_cooldown_secs: VESTING - 1,
                ..p
            }),
            "InvalidVesting",
        ),
        (
            "unstake cooldown longer than 21 days",
            Box::new(|p| ConfigParams {
                unstake_cooldown_secs: 21 * DAY + 1,
                ..p
            }),
            "InvalidVesting",
        ),
        (
            "notice period of 0",
            Box::new(|p| ConfigParams {
                notice_secs: 0,
                ..p
            }),
            "InvalidVesting",
        ),
        (
            "two tiers with the same minimum bond",
            Box::new(|p| ConfigParams {
                bonus_tiers: [
                    tier(100 * CLIP_USD, 300),
                    tier(100 * CLIP_USD, 400),
                    BonusTier::default(),
                ],
                ..p
            }),
            "InvalidTiers",
        ),
        (
            "tiers with decreasing minimum bonds",
            Box::new(|p| ConfigParams {
                bonus_tiers: [
                    tier(100 * CLIP_USD, 300),
                    tier(50 * CLIP_USD, 400),
                    BonusTier::default(),
                ],
                ..p
            }),
            "InvalidTiers",
        ),
        (
            "a bonus of 20.01%",
            Box::new(|p| ConfigParams {
                bonus_tiers: [
                    tier(100 * CLIP_USD, 2_001),
                    BonusTier::default(),
                    BonusTier::default(),
                ],
                ..p
            }),
            "InvalidBps",
        ),
    ];
    for (label, mutate, expected) in cases {
        let mut world = World::new();
        println!("init_config with {label}");
        let ix = init_config_ix(
            &world.admin.pubkey(),
            &world.mint,
            &world.program_data,
            mutate(base(&world)),
        );
        expect_error(send(&mut world.svm, ix, &[&world.admin]), expected);
        assert!(!exists(&world.svm, &config_pda()));
    }

    println!("init_config with bonded vesting = vesting = cooldown, a 20% top tier and a disabled tier with min_bond 0");
    let world = World::new();
    let params = ConfigParams {
        vesting_secs: 10 * DAY,
        bonded_vesting_secs: 10 * DAY,
        unstake_cooldown_secs: 10 * DAY,
        bonus_tiers: [tier(0, 9_999), tier(CLIP_USD, 2_000), BonusTier::default()],
        ..base(&world)
    };
    let world = world.with_config_params(params);
    let config = config_state(&world);
    println!(
        "a bond of 0.5 earns {} bps, a bond of 1 earns {} bps",
        config.bonus_bps_for(CLIP_USD / 2),
        config.bonus_bps_for(CLIP_USD)
    );
    assert_eq!(config.bonus_bps_for(CLIP_USD / 2), 0);
    assert_eq!(config.bonus_bps_for(CLIP_USD), 2_000);
}

#[test]
fn only_the_admin_updates_the_config_and_rotated_keys_take_over() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let admin = world.admin.insecure_clone();
    let stranger = funded(&mut world.svm);
    let new_oracle = funded(&mut world.svm);
    let new_arbiter = funded(&mut world.svm);
    let before = config_state(&world);

    println!("a stranger rotates the oracle to himself");
    let params = default_config_params(stranger.pubkey(), stranger.pubkey());
    expect_error(
        update_config(&mut world, &stranger, params),
        "ConstraintHasOne",
    );

    println!("the admin submits a vesting of 0");
    let params = ConfigParams {
        vesting_secs: 0,
        ..default_config_params(world.oracle.pubkey(), world.arbiter.pubkey())
    };
    expect_error(update_config(&mut world, &admin, params), "InvalidVesting");
    assert_eq!(config_state(&world).oracle, before.oracle);

    println!("the admin rotates the oracle and the arbiter and lowers the bonus tier to a 50 bond at 100 bps");
    let params = ConfigParams {
        bonus_tiers: [
            tier(50 * CLIP_USD, 100),
            BonusTier::default(),
            BonusTier::default(),
        ],
        ..default_config_params(new_oracle.pubkey(), new_arbiter.pubkey())
    };
    update_config(&mut world, &admin, params).unwrap();
    let config = config_state(&world);
    println!(
        "oracle {} arbiter {} admin {} mint {} bonus_vault {}",
        config.oracle, config.arbiter, config.admin, config.mint, config.bonus_vault
    );
    assert_eq!(config.oracle, new_oracle.pubkey());
    assert_eq!(config.arbiter, new_arbiter.pubkey());
    assert_eq!(config.admin, before.admin);
    assert_eq!(config.mint, before.mint);
    assert_eq!(config.bonus_vault, before.bonus_vault);
    assert_eq!(config.bonus_tiers[0], tier(50 * CLIP_USD, 100));

    let creator = bonded_creator(&mut world, 60 * CLIP_USD);
    let campaign = campaign_of(&world);
    println!("the old oracle settles");
    let old_oracle = world.oracle.insecure_clone();
    expect_error(
        settle_on(
            &mut world,
            &old_oracle,
            &campaign,
            &creator.pubkey(),
            1,
            UNITS,
        ),
        "ConstraintHasOne",
    );
    println!("the new oracle settles a creator bonded with 60");
    settle_on(
        &mut world,
        &new_oracle,
        &campaign,
        &creator.pubkey(),
        1,
        UNITS,
    )
    .unwrap();
    println!(
        "payout: amount {} bonus_bps {}",
        payout_of(&world, &creator.pubkey(), 1).amount,
        payout_of(&world, &creator.pubkey(), 1).bonus_bps
    );
    assert_eq!(payout_of(&world, &creator.pubkey(), 1).bonus_bps, 100);

    let ix = flag_ix(
        &world.brand.pubkey(),
        &campaign,
        &payout_pda(&campaign, &creator.pubkey(), 1),
        1,
    );
    send(&mut world.svm, ix, &[&world.brand]).unwrap();
    println!("the old arbiter resolves");
    let ix = resolve_ix(
        &world.arbiter.pubkey(),
        &campaign,
        &creator.pubkey(),
        1,
        &new_oracle.pubkey(),
        true,
    );
    let old_arbiter = world.arbiter.insecure_clone();
    expect_error(
        send(&mut world.svm, ix, &[&old_arbiter]),
        "ConstraintHasOne",
    );
    println!("the new arbiter resolves");
    let ix = resolve_ix(
        &new_arbiter.pubkey(),
        &campaign,
        &creator.pubkey(),
        1,
        &new_oracle.pubkey(),
        true,
    );
    send(&mut world.svm, ix, &[&new_arbiter]).unwrap();
}

#[test]
fn pause_stops_settling_staking_and_new_campaigns_but_not_exits() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let admin = world.admin.insecure_clone();
    let stranger = funded(&mut world.svm);
    let cranker = funded(&mut world.svm);
    let creator = bonded_creator(&mut world, 10 * CLIP_USD);
    settle(&mut world, &creator.pubkey(), 1, SMALL).unwrap();
    let ix = request_unstake_ix(&creator.pubkey(), 5 * CLIP_USD);
    send(&mut world.svm, ix, &[&creator]).unwrap();

    println!("a stranger pauses the program");
    expect_error(set_paused(&mut world, &stranger, true), "ConstraintHasOne");
    assert!(!config_state(&world).paused);

    println!("the admin pauses");
    set_paused(&mut world, &admin, true).unwrap();
    assert!(config_state(&world).paused);

    println!("settle while paused");
    expect_error(settle(&mut world, &creator.pubkey(), 2, SMALL), "Paused");
    println!("stake while paused");
    give_tokens(&mut world.svm, &creator.pubkey(), &world.mint, CLIP_USD);
    let ix = stake_ix(&creator.pubkey(), &world.mint, CLIP_USD);
    expect_error(send(&mut world.svm, ix, &[&creator]), "Paused");
    println!("create a campaign while paused");
    let ix = create_campaign_ix(&world.brand.pubkey(), &world.mint, 2, default_params());
    expect_error(send(&mut world.svm, ix, &[&world.brand]), "Paused");
    assert!(!exists(&world.svm, &campaign_pda(&world.brand.pubkey(), 2)));

    set_time(&mut world.svm, NOW + UNSTAKE_COOLDOWN);
    println!("release a vested payout while paused");
    release(&mut world, &cranker, &creator.pubkey(), 1).unwrap();
    assert_eq!(
        creator_balance(&world, &creator.pubkey()),
        CLIP_USD + SMALL_PAY
    );
    println!("withdraw a matured unstake while paused");
    let ix = withdraw_stake_ix(&creator.pubkey(), &world.mint);
    send(&mut world.svm, ix, &[&creator]).unwrap();
    assert_eq!(
        creator_balance(&world, &creator.pubkey()),
        CLIP_USD + SMALL_PAY + 5 * CLIP_USD
    );

    set_time(&mut world.svm, END + VESTING);
    println!("close the campaign while paused");
    close(&mut world).unwrap();
    assert_eq!(campaign_state(&world).status, CampaignStatus::Closed);

    println!("the admin unpauses");
    set_paused(&mut world, &admin, false).unwrap();
    let params = CampaignParams {
        end_ts: END + 90 * DAY,
        ..default_params()
    };
    let ix = create_campaign_ix(&world.brand.pubkey(), &world.mint, 2, params);
    send(&mut world.svm, ix, &[&world.brand]).unwrap();
    let ix = stake_ix(&creator.pubkey(), &world.mint, CLIP_USD);
    send(&mut world.svm, ix, &[&creator]).unwrap();
    assert!(exists(&world.svm, &campaign_pda(&world.brand.pubkey(), 2)));
}

#[test]
fn propose_rates_takes_effect_after_the_notice_period() {
    let mut world = World::with_funded_campaign(1, 200 * CLIP_USD);
    let (alice, bob) = (Pubkey::new_unique(), Pubkey::new_unique());
    let stranger = funded(&mut world.svm);
    let old = default_params().rate_per_mille;
    let new = [4 * CLIP_USD, 5 * CLIP_USD, CLIP_USD / 10, 50 * CLIP_USD];
    let newer = [6 * CLIP_USD, 5 * CLIP_USD, CLIP_USD / 10, 50 * CLIP_USD];

    println!("a stranger proposes rates");
    let ix = propose_rates_ix(&stranger.pubkey(), &campaign_of(&world), new);
    expect_error(send(&mut world.svm, ix, &[&stranger]), "ConstraintSeeds");
    println!("the brand proposes all-zero rates");
    expect_error(propose_rates(&mut world, [0; 4]), "InvalidRates");
    assert_eq!(campaign_state(&world).pending_rates_at, 0);

    println!("the brand proposes {new:?} (short views doubled)");
    propose_rates(&mut world, new).unwrap();
    let campaign = campaign_state(&world);
    println!(
        "pending {:?} effective at {} (now + {NOTICE}); current {:?}",
        campaign.pending_rates, campaign.pending_rates_at, campaign.rate_per_mille
    );
    assert_eq!(campaign.pending_rates, new);
    assert_eq!(campaign.pending_rates_at, NOW + NOTICE);
    assert_eq!(campaign.rate_per_mille, old);

    set_time(&mut world.svm, NOW + NOTICE - 1);
    settle(&mut world, &alice, 1, SMALL).unwrap();
    println!(
        "one second before the notice ends 1000 views pay {}",
        payout_of(&world, &alice, 1).amount
    );
    assert_eq!(payout_of(&world, &alice, 1).amount, SMALL_PAY);
    assert_eq!(campaign_state(&world).rate_per_mille, old);
    assert_eq!(campaign_state(&world).pending_rates, new);

    println!("a second proposal {newer:?} before the first takes effect replaces it and restarts the notice");
    propose_rates(&mut world, newer).unwrap();
    let campaign = campaign_state(&world);
    assert_eq!(campaign.pending_rates, newer);
    assert_eq!(campaign.pending_rates_at, NOW + 2 * NOTICE - 1);

    set_time(&mut world.svm, NOW + NOTICE);
    settle(&mut world, &alice, 2, SMALL).unwrap();
    println!(
        "when the first notice would have ended 1000 views still pay {}",
        payout_of(&world, &alice, 2).amount
    );
    assert_eq!(payout_of(&world, &alice, 2).amount, SMALL_PAY);
    assert_eq!(campaign_state(&world).rate_per_mille, old);

    set_time(&mut world.svm, NOW + 2 * NOTICE - 1);
    settle(&mut world, &bob, 1, SMALL).unwrap();
    let campaign = campaign_state(&world);
    println!(
        "when the second notice ends another creator's settle applies the rates: bob gets {}, campaign rates {:?}, pending {:?} at {}",
        payout_of(&world, &bob, 1).amount,
        campaign.rate_per_mille,
        campaign.pending_rates,
        campaign.pending_rates_at
    );
    assert_eq!(payout_of(&world, &bob, 1).amount, 6 * CLIP_USD);
    assert_eq!(campaign.rate_per_mille, newer);
    assert_eq!(
        (campaign.pending_rates, campaign.pending_rates_at),
        ([0; 4], 0)
    );

    println!("the earlier payouts keep their amounts");
    assert_eq!(payout_of(&world, &alice, 1).amount, SMALL_PAY);
    assert_eq!(payout_of(&world, &alice, 2).amount, SMALL_PAY);
    settle(&mut world, &alice, 3, SMALL).unwrap();
    assert_eq!(payout_of(&world, &alice, 3).amount, 6 * CLIP_USD);
}

#[test]
fn propose_standards_versions_the_rules_and_payouts_record_the_version_in_force() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let creator = Pubkey::new_unique();
    let stranger = funded(&mut world.svm);
    let campaign = campaign_state(&world);
    println!(
        "campaign starts with standards {:?} version {}",
        campaign.standards_hash[0], campaign.standards_version
    );
    assert_eq!(
        (campaign.standards_hash, campaign.standards_version),
        ([7; 32], 1)
    );

    println!("a stranger proposes standards");
    let ix = propose_standards_ix(&stranger.pubkey(), &campaign_of(&world), [9; 32]);
    expect_error(send(&mut world.svm, ix, &[&stranger]), "ConstraintSeeds");

    propose_standards(&mut world, [9; 32]).unwrap();
    let campaign = campaign_state(&world);
    assert_eq!(campaign.pending_standards_hash, [9; 32]);
    assert_eq!(campaign.pending_standards_at, NOW + NOTICE);
    assert_eq!(campaign.standards_hash, [7; 32]);

    set_time(&mut world.svm, NOW + NOTICE - 1);
    settle(&mut world, &creator, 1, SMALL).unwrap();
    println!(
        "settled one second before the notice ends: payout version {}",
        payout_of(&world, &creator, 1).standards_version
    );
    assert_eq!(payout_of(&world, &creator, 1).standards_version, 1);

    set_time(&mut world.svm, NOW + NOTICE);
    settle(&mut world, &creator, 2, SMALL).unwrap();
    let campaign = campaign_state(&world);
    println!(
        "settled when the notice ends: campaign standards {:?} version {}, pending {:?} at {}, payout version {}",
        campaign.standards_hash[0],
        campaign.standards_version,
        campaign.pending_standards_hash[0],
        campaign.pending_standards_at,
        payout_of(&world, &creator, 2).standards_version
    );
    assert_eq!(
        (campaign.standards_hash, campaign.standards_version),
        ([9; 32], 2)
    );
    assert_eq!(
        (
            campaign.pending_standards_hash,
            campaign.pending_standards_at
        ),
        ([0; 32], 0)
    );
    assert_eq!(payout_of(&world, &creator, 2).standards_version, 2);
    assert_eq!(payout_of(&world, &creator, 1).standards_version, 1);

    propose_standards(&mut world, [11; 32]).unwrap();
    set_time(&mut world.svm, NOW + 2 * NOTICE);
    settle(&mut world, &creator, 3, SMALL).unwrap();
    assert_eq!(campaign_state(&world).standards_version, 3);
    assert_eq!(payout_of(&world, &creator, 3).standards_version, 3);
}

#[test]
fn proposals_die_with_the_campaign() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    set_time(&mut world.svm, END + VESTING);
    close(&mut world).unwrap();
    println!("propose rates and standards on a closed campaign");
    expect_error(
        propose_rates(&mut world, default_params().rate_per_mille),
        "CampaignClosed",
    );
    expect_error(propose_standards(&mut world, [9; 32]), "CampaignClosed");
    let campaign = campaign_state(&world);
    assert_eq!(
        (campaign.pending_rates_at, campaign.pending_standards_at),
        (0, 0)
    );
}

#[test]
fn rollover_moves_the_unused_budget_and_closes_the_source_vault() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let brand = world.brand.pubkey();
    let creator = Pubkey::new_unique();
    let cranker = funded(&mut world.svm);
    let source = campaign_of(&world);
    let target = campaign_pda(&brand, 2);
    let source_vault = vault_of(&source, &world.mint);
    let target_vault = vault_of(&target, &world.mint);
    let params = CampaignParams {
        end_ts: NOW + 90 * DAY,
        ..default_params()
    };
    let ix = create_campaign_ix(&brand, &world.mint, 2, params);
    send(&mut world.svm, ix, &[&world.brand]).unwrap();

    println!("rollover on the first day");
    expect_error(rollover(&mut world, &target), "CampaignStillRunning");
    settle(&mut world, &creator, 1, UNITS).unwrap();
    set_time(&mut world.svm, END + VESTING - 1);
    println!("rollover one second before end + vesting");
    expect_error(rollover(&mut world, &target), "CampaignStillRunning");
    set_time(&mut world.svm, END + VESTING);
    println!("rollover with a payout still outstanding");
    expect_error(rollover(&mut world, &target), "PayoutsOutstanding");

    release(&mut world, &cranker, &creator, 1).unwrap();
    let brand_before = lamports(&world.svm, &brand);
    println!("rollover of the 65 clipUSD left in campaign 1 into campaign 2");
    rollover(&mut world, &target).unwrap();

    let source_state: Campaign = fetch(&world.svm, &source);
    let target_state: Campaign = fetch(&world.svm, &target);
    println!(
        "source: status {:?} vault exists {} paid_total {} | target: status {:?} funded_total {} vault {} | brand got {} lamports of rent back",
        source_state.status,
        exists(&world.svm, &source_vault),
        source_state.paid_total,
        target_state.status,
        target_state.funded_total,
        token_balance(&world.svm, &target_vault),
        lamports(&world.svm, &brand) - brand_before
    );
    assert_eq!(source_state.status, CampaignStatus::Closed);
    assert!(!exists(&world.svm, &source_vault));
    assert_eq!(source_state.paid_total, EARNED);
    assert_eq!(target_state.status, CampaignStatus::Active);
    assert_eq!(target_state.funded_total, 65 * CLIP_USD);
    assert_eq!(token_balance(&world.svm, &target_vault), 65 * CLIP_USD);
    assert!(lamports(&world.svm, &brand) > brand_before);
    assert_eq!(creator_balance(&world, &creator), EARNED);

    println!("the rolled-over budget pays creators of campaign 2");
    let oracle = world.oracle.insecure_clone();
    settle_on(
        &mut world,
        &oracle,
        &target,
        &Pubkey::new_unique(),
        1,
        UNITS,
    )
    .unwrap();
    assert_eq!(fetch::<Campaign>(&world.svm, &target).reserved, EARNED);

    println!("the closed source accepts nothing more");
    expect_error(settle(&mut world, &creator, 2, UNITS), "CampaignClosed");
    expect_error(close(&mut world), "AccountNotInitialized");
    expect_error(rollover(&mut world, &target), "AccountNotInitialized");
    let brand_token = get_associated_token_address(&brand, &world.mint);
    let ix = fund_campaign_ix(&brand, &source, &world.mint, &brand_token, CLIP_USD);
    expect_error(
        send(&mut world.svm, ix, &[&world.brand]),
        "AccountNotInitialized",
    );
}

#[test]
fn rollover_only_into_an_active_campaign_of_the_same_brand() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let brand = world.brand.pubkey();
    let stranger = funded(&mut world.svm);
    let source = campaign_of(&world);
    let long = CampaignParams {
        end_ts: NOW + 90 * DAY,
        ..default_params()
    };
    for id in [2, 4] {
        let ix = create_campaign_ix(&brand, &world.mint, id, long.clone());
        send(&mut world.svm, ix, &[&world.brand]).unwrap();
    }
    let ix = create_campaign_ix(&brand, &world.mint, 3, default_params());
    send(&mut world.svm, ix, &[&world.brand]).unwrap();
    let ix = create_campaign_ix(&stranger.pubkey(), &world.mint, 1, long.clone());
    send(&mut world.svm, ix, &[&stranger]).unwrap();
    let (target, third, fourth) = (
        campaign_pda(&brand, 2),
        campaign_pda(&brand, 3),
        campaign_pda(&brand, 4),
    );
    let foreign = campaign_pda(&stranger.pubkey(), 1);

    set_time(&mut world.svm, END + VESTING);
    let brand_token = get_associated_token_address(&brand, &world.mint);
    let ix = close_campaign_ix(&brand, &third, &world.mint, &brand_token);
    send(&mut world.svm, ix, &[&world.brand]).unwrap();

    println!("rollover into the campaign itself: the same mutable account twice is refused before any rule runs");
    expect_error(
        rollover(&mut world, &source),
        "ConstraintDuplicateMutableAccount",
    );
    println!("rollover into another brand's campaign");
    expect_error(rollover(&mut world, &foreign), "InvalidRolloverTarget");
    println!("the stranger rolls the brand's budget into his own campaign");
    let ix = rollover_ix(&stranger.pubkey(), &source, &foreign, &world.mint);
    expect_error(send(&mut world.svm, ix, &[&stranger]), "ConstraintSeeds");
    println!("rollover into a closed campaign whose vault is gone");
    expect_error(rollover(&mut world, &third), "AccountNotInitialized");
    println!("rollover into campaign 2 while naming the vault of campaign 4");
    let ix = Instruction::new_with_bytes(
        clipfi_escrow::id(),
        &clipfi_escrow::instruction::Rollover {}.data(),
        clipfi_escrow::accounts::Rollover {
            brand,
            config: config_pda(),
            campaign: source,
            vault: vault_of(&source, &world.mint),
            target_campaign: target,
            target_vault: vault_of(&fourth, &world.mint),
            mint: world.mint,
            token_program: TOKEN_PROGRAM,
        }
        .to_account_metas(None),
    );
    expect_error(
        send(&mut world.svm, ix, &[&world.brand]),
        "InvalidRolloverTarget",
    );

    assert_eq!(
        token_balance(&world.svm, &vault_of(&source, &world.mint)),
        100 * CLIP_USD
    );
    assert_eq!(
        token_balance(&world.svm, &vault_of(&target, &world.mint)),
        0
    );
    assert_eq!(
        token_balance(&world.svm, &vault_of(&fourth, &world.mint)),
        0
    );
    assert_eq!(
        token_balance(&world.svm, &vault_of(&foreign, &world.mint)),
        0
    );
    assert_eq!(campaign_state(&world).status, CampaignStatus::Active);

    println!("rollover into campaign 2 with its own vault");
    rollover(&mut world, &target).unwrap();
    assert_eq!(
        token_balance(&world.svm, &vault_of(&target, &world.mint)),
        100 * CLIP_USD
    );
    assert_eq!(
        fetch::<Campaign>(&world.svm, &target).funded_total,
        100 * CLIP_USD
    );
}

#[test]
fn rollover_of_an_empty_vault_is_refused() {
    let mut world = World::with_funded_campaign(1, EARNED);
    let brand = world.brand.pubkey();
    let creator = Pubkey::new_unique();
    let cranker = funded(&mut world.svm);
    let params = CampaignParams {
        end_ts: NOW + 90 * DAY,
        ..default_params()
    };
    let ix = create_campaign_ix(&brand, &world.mint, 2, params);
    send(&mut world.svm, ix, &[&world.brand]).unwrap();
    let target = campaign_pda(&brand, 2);

    settle(&mut world, &creator, 1, UNITS).unwrap();
    set_time(&mut world.svm, END + VESTING);
    release(&mut world, &cranker, &creator, 1).unwrap();
    println!(
        "the whole budget was paid out; the vault holds {}",
        token_balance(&world.svm, &vault_of(&campaign_of(&world), &world.mint))
    );
    expect_error(rollover(&mut world, &target), "ZeroAmount");
    assert_eq!(campaign_state(&world).status, CampaignStatus::Active);

    println!("close_campaign still works and reclaims the vault rent");
    close(&mut world).unwrap();
    assert_eq!(campaign_state(&world).status, CampaignStatus::Closed);
    assert_eq!(fetch::<Campaign>(&world.svm, &target).funded_total, 0);
}
