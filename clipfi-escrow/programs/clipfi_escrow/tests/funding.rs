#![allow(clippy::result_large_err)]

mod common;

use {
    clipfi_escrow::{Campaign, CampaignParams, CampaignStatus, Config, ConfigParams},
    common::*,
    solana_signer::Signer,
};

#[test]
fn config_stores_the_roles_the_mint_and_the_vesting_period() {
    let world = World::with_config();
    let config: Config = fetch(&world.svm, &config_pda());
    println!(
        "config: admin {} oracle {} arbiter {} mint {} vesting {}s",
        config.admin, config.oracle, config.arbiter, config.mint, config.vesting_secs
    );
    assert_eq!(config.admin, world.admin.pubkey());
    assert_eq!(config.oracle, world.oracle.pubkey());
    assert_eq!(config.arbiter, world.arbiter.pubkey());
    assert_eq!(config.mint, world.mint);
    assert_eq!(config.vesting_secs, VESTING);
}

#[test]
fn vesting_must_be_between_one_second_and_21_days() {
    for vesting_secs in [0, -1, 21 * DAY + 1] {
        let mut world = World::new();
        println!("init_config with vesting_secs = {vesting_secs}");
        let ix = init_config_ix(
            &world.admin.pubkey(),
            &world.mint,
            &world.program_data,
            ConfigParams {
                vesting_secs,
                ..default_config_params(world.oracle.pubkey(), world.arbiter.pubkey())
            },
        );
        expect_error(send(&mut world.svm, ix, &[&world.admin]), "InvalidVesting");
    }

    let mut world = World::new();
    println!("init_config with vesting_secs = 21 days");
    let ix = init_config_ix(
        &world.admin.pubkey(),
        &world.mint,
        &world.program_data,
        ConfigParams {
            vesting_secs: 21 * DAY,
            ..default_config_params(world.oracle.pubkey(), world.arbiter.pubkey())
        },
    );
    send(&mut world.svm, ix, &[&world.admin]).unwrap();
}

#[test]
fn init_config_rejects_a_mint_with_a_transfer_fee() {
    let mut world = World::new();
    let fee_mint = create_fee_mint(&mut world.svm, &world.admin.pubkey());
    println!("init_config with a Token-2022 mint that has a TransferFeeConfig extension");
    let ix = init_config_ix_with(
        &world.admin.pubkey(),
        &fee_mint,
        &world.program_data,
        default_config_params(world.oracle.pubkey(), world.arbiter.pubkey()),
        TOKEN_2022_PROGRAM,
    );
    expect_error(send(&mut world.svm, ix, &[&world.admin]), "UnsupportedMint");
}

#[test]
fn init_config_is_gated_to_the_program_upgrade_authority() {
    let mut world = World::new();
    let intruder = funded(&mut world.svm);
    println!("intruder front-runs init_config before the real deployer, signing as admin");
    let ix = init_config_ix(
        &intruder.pubkey(),
        &world.mint,
        &world.program_data,
        default_config_params(intruder.pubkey(), intruder.pubkey()),
    );
    expect_error(send(&mut world.svm, ix, &[&intruder]), "Unauthorized");

    println!(
        "the real upgrade authority ({}) initializes the config",
        world.admin.pubkey()
    );
    let ix = init_config_ix(
        &world.admin.pubkey(),
        &world.mint,
        &world.program_data,
        default_config_params(world.oracle.pubkey(), world.arbiter.pubkey()),
    );
    send(&mut world.svm, ix, &[&world.admin]).unwrap();
    let config: Config = fetch(&world.svm, &config_pda());
    assert_eq!(config.admin, world.admin.pubkey());
}

#[test]
fn config_can_be_created_only_once() {
    let mut world = World::with_config();
    let intruder = funded(&mut world.svm);
    println!("a second init_config, signed by {}", intruder.pubkey());
    let ix = init_config_ix(
        &intruder.pubkey(),
        &world.mint,
        &world.program_data,
        ConfigParams {
            vesting_secs: DAY,
            ..default_config_params(intruder.pubkey(), intruder.pubkey())
        },
    );
    expect_error(send(&mut world.svm, ix, &[&intruder]), "already in use");

    let config: Config = fetch(&world.svm, &config_pda());
    println!("admin is still {}", config.admin);
    assert_eq!(config.admin, world.admin.pubkey());
}

#[test]
fn brand_creates_a_campaign_with_an_empty_vault_it_does_not_control() {
    let world = World::with_campaign(1);
    let address = campaign_pda(&world.brand.pubkey(), 1);
    let campaign: Campaign = fetch(&world.svm, &address);
    let vault = vault_of(&address, &world.mint);
    println!(
        "campaign {address}: brand {} vault {} rates {:?} limit per creator {}",
        campaign.brand, campaign.vault, campaign.rate_per_mille, campaign.max_per_creator
    );
    assert_eq!(campaign.brand, world.brand.pubkey());
    assert_eq!(campaign.campaign_id, 1);
    assert_eq!(campaign.mint, world.mint);
    assert_eq!(campaign.vault, vault);
    assert_eq!(campaign.rate_per_mille, default_params().rate_per_mille);
    assert_eq!(campaign.max_per_creator, 40 * CLIP_USD);
    assert_eq!((campaign.start_ts, campaign.end_ts), (NOW, NOW + 30 * DAY));
    assert_eq!(
        (
            campaign.funded_total,
            campaign.reserved,
            campaign.paid_total
        ),
        (0, 0, 0)
    );
    assert_eq!(campaign.status, CampaignStatus::Active);

    println!(
        "vault holds {} and is owned by {}",
        token_balance(&world.svm, &vault),
        token_owner(&world.svm, &vault)
    );
    assert_eq!(token_balance(&world.svm, &vault), 0);
    assert_eq!(token_owner(&world.svm, &vault), address);
}

#[test]
fn campaign_parameters_are_validated() {
    type Change = fn(&mut CampaignParams);
    let cases: [(&str, Change, &str); 5] = [
        (
            "end before start",
            |p| p.end_ts = p.start_ts - 1,
            "InvalidWindow",
        ),
        (
            "end equal to start",
            |p| p.end_ts = p.start_ts,
            "InvalidWindow",
        ),
        (
            "already over",
            |p| (p.start_ts, p.end_ts) = (NOW - 2 * DAY, NOW - DAY),
            "InvalidWindow",
        ),
        (
            "all rates zero",
            |p| p.rate_per_mille = [0; 4],
            "InvalidRates",
        ),
        (
            "no limit per creator",
            |p| p.max_per_creator = 0,
            "InvalidLimit",
        ),
    ];
    for (name, change, error) in cases {
        let mut world = World::with_config();
        let mut params = default_params();
        change(&mut params);
        println!("create_campaign: {name}");
        let ix = create_campaign_ix(&world.brand.pubkey(), &world.mint, 1, params);
        expect_error(send(&mut world.svm, ix, &[&world.brand]), error);
    }
}

#[test]
fn campaign_must_use_the_configured_mint() {
    let mut world = World::with_config();
    let other_mint = create_mint(&mut world.svm, &world.brand.pubkey());
    println!(
        "create_campaign with mint {other_mint} instead of {}",
        world.mint
    );
    let ix = create_campaign_ix(&world.brand.pubkey(), &other_mint, 1, default_params());
    expect_error(
        send(&mut world.svm, ix, &[&world.brand]),
        "ConstraintHasOne",
    );
}

#[test]
fn the_same_campaign_id_cannot_be_created_twice_by_one_brand() {
    let mut world = World::with_campaign(1);
    println!("create_campaign with id 1 again");
    let ix = create_campaign_ix(&world.brand.pubkey(), &world.mint, 1, default_params());
    expect_error(send(&mut world.svm, ix, &[&world.brand]), "already in use");

    println!("another brand uses id 1 for its own campaign");
    let other_brand = funded(&mut world.svm);
    let ix = create_campaign_ix(&other_brand.pubkey(), &world.mint, 1, default_params());
    send(&mut world.svm, ix, &[&other_brand]).unwrap();
}

#[test]
fn brand_funds_the_campaign_and_can_top_it_up() {
    let mut world = World::with_campaign(1);
    let brand = world.brand.pubkey();
    let campaign = campaign_pda(&brand, 1);
    let vault = vault_of(&campaign, &world.mint);
    let brand_token = give_tokens(&mut world.svm, &brand, &world.mint, 100 * CLIP_USD);

    println!("fund_campaign with 85 clipUSD");
    let ix = fund_campaign_ix(&brand, &campaign, &world.mint, &brand_token, 85 * CLIP_USD);
    send(&mut world.svm, ix, &[&world.brand]).unwrap();
    println!(
        "vault {} brand {} funded_total {}",
        token_balance(&world.svm, &vault),
        token_balance(&world.svm, &brand_token),
        fetch::<Campaign>(&world.svm, &campaign).funded_total
    );
    assert_eq!(token_balance(&world.svm, &vault), 85 * CLIP_USD);
    assert_eq!(token_balance(&world.svm, &brand_token), 15 * CLIP_USD);
    assert_eq!(
        fetch::<Campaign>(&world.svm, &campaign).funded_total,
        85 * CLIP_USD
    );

    println!("fund_campaign with 10 clipUSD more");
    let ix = fund_campaign_ix(&brand, &campaign, &world.mint, &brand_token, 10 * CLIP_USD);
    send(&mut world.svm, ix, &[&world.brand]).unwrap();
    println!(
        "vault {} brand {} funded_total {}",
        token_balance(&world.svm, &vault),
        token_balance(&world.svm, &brand_token),
        fetch::<Campaign>(&world.svm, &campaign).funded_total
    );
    assert_eq!(token_balance(&world.svm, &vault), 95 * CLIP_USD);
    assert_eq!(token_balance(&world.svm, &brand_token), 5 * CLIP_USD);
    assert_eq!(
        fetch::<Campaign>(&world.svm, &campaign).funded_total,
        95 * CLIP_USD
    );
}

#[test]
fn funding_needs_a_positive_amount_and_enough_tokens() {
    let mut world = World::with_campaign(1);
    let brand = world.brand.pubkey();
    let campaign = campaign_pda(&brand, 1);
    let brand_token = give_tokens(&mut world.svm, &brand, &world.mint, 10 * CLIP_USD);

    println!("fund_campaign with 0");
    let ix = fund_campaign_ix(&brand, &campaign, &world.mint, &brand_token, 0);
    expect_error(send(&mut world.svm, ix, &[&world.brand]), "ZeroAmount");

    println!("fund_campaign with 11 clipUSD while holding 10");
    let ix = fund_campaign_ix(&brand, &campaign, &world.mint, &brand_token, 11 * CLIP_USD);
    expect_error(
        send(&mut world.svm, ix, &[&world.brand]),
        "insufficient funds",
    );

    assert_eq!(
        token_balance(&world.svm, &vault_of(&campaign, &world.mint)),
        0
    );
    assert_eq!(fetch::<Campaign>(&world.svm, &campaign).funded_total, 0);
}

#[test]
fn only_the_brand_can_fund_and_only_from_its_own_tokens() {
    let mut world = World::with_campaign(1);
    let brand = world.brand.pubkey();
    let campaign = campaign_pda(&brand, 1);
    let stranger = funded(&mut world.svm);
    let stranger_token = give_tokens(
        &mut world.svm,
        &stranger.pubkey(),
        &world.mint,
        50 * CLIP_USD,
    );

    println!("a stranger signs fund_campaign as the brand of someone else's campaign");
    let ix = fund_campaign_ix(
        &stranger.pubkey(),
        &campaign,
        &world.mint,
        &stranger_token,
        CLIP_USD,
    );
    expect_error(send(&mut world.svm, ix, &[&stranger]), "ConstraintSeeds");

    println!("the brand tries to fund from the stranger's token account");
    let ix = fund_campaign_ix(&brand, &campaign, &world.mint, &stranger_token, CLIP_USD);
    expect_error(
        send(&mut world.svm, ix, &[&world.brand]),
        "ConstraintTokenOwner",
    );

    assert_eq!(token_balance(&world.svm, &stranger_token), 50 * CLIP_USD);
    assert_eq!(
        token_balance(&world.svm, &vault_of(&campaign, &world.mint)),
        0
    );
}
