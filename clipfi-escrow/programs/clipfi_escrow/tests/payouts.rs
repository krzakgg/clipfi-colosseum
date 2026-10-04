#![allow(clippy::result_large_err)]

mod common;

use {
    anchor_lang::prelude::Pubkey,
    anchor_spl::associated_token::get_associated_token_address,
    clipfi_escrow::{
        Campaign, CampaignParams, CampaignStatus, CreatorPosition, Payout, PayoutStatus,
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

fn campaign_of(world: &World) -> Pubkey {
    campaign_pda(&world.brand.pubkey(), 1)
}

fn world_with(params: CampaignParams, budget: u64) -> World {
    let mut world = World::with_config();
    let brand = world.brand.pubkey();
    let ix = create_campaign_ix(&brand, &world.mint, 1, params);
    send(&mut world.svm, ix, &[&world.brand]).unwrap();
    let brand_token = give_tokens(&mut world.svm, &brand, &world.mint, budget);
    let ix = fund_campaign_ix(
        &brand,
        &campaign_pda(&brand, 1),
        &world.mint,
        &brand_token,
        budget,
    );
    send(&mut world.svm, ix, &[&world.brand]).unwrap();
    world
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

fn campaign_state(world: &World) -> Campaign {
    fetch(&world.svm, &campaign_of(world))
}

fn creator_balance(world: &World, creator: &Pubkey) -> u64 {
    token_balance(
        &world.svm,
        &get_associated_token_address(creator, &world.mint),
    )
}

#[test]
fn settle_pays_units_times_rate_and_reserves_the_budget() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let creator = Pubkey::new_unique();
    println!(
        "settle epoch 1: units {UNITS:?} at rates {:?}",
        default_params().rate_per_mille
    );
    settle(&mut world, &creator, 1, UNITS).unwrap();

    let payout = payout_of(&world, &creator, 1);
    let position = position_of(&world, &creator);
    let campaign = campaign_state(&world);
    println!(
        "payout: amount {} status {:?} unlock_ts {} | campaign: reserved {} free {:?} | position: earned {} last_epoch {}",
        payout.amount, payout.status, payout.unlock_ts, campaign.reserved, campaign.free_budget(),
        position.earned_total, position.last_epoch
    );
    assert_eq!(payout.amount, EARNED);
    assert_eq!(payout.status, PayoutStatus::Pending);
    assert_eq!(payout.unlock_ts, END);
    assert_eq!(
        (payout.campaign, payout.creator, payout.epoch),
        (campaign_of(&world), creator, 1)
    );
    assert_eq!(payout.units, UNITS);
    assert_eq!(payout.evidence_hash, [1; 32]);
    assert_eq!(payout.rent_payer, world.oracle.pubkey());

    assert_eq!(campaign.reserved, EARNED);
    assert_eq!(campaign.free_budget(), Some(65 * CLIP_USD));
    assert_eq!(campaign.paid_total, 0);

    assert_eq!((position.earned_total, position.claimed_total), (EARNED, 0));
    assert_eq!((position.last_epoch, position.units_total), (1, UNITS));

    let vault = vault_of(&campaign_of(&world), &world.mint);
    println!("vault still holds {}", token_balance(&world.svm, &vault));
    assert_eq!(token_balance(&world.svm, &vault), 100 * CLIP_USD);
}

#[test]
fn amounts_are_rounded_down_in_favour_of_the_vault() {
    let params = CampaignParams {
        rate_per_mille: [1, 0, 0, 0],
        ..default_params()
    };
    let mut world = world_with(params, CLIP_USD);
    let creator = Pubkey::new_unique();

    println!("rate of 1 base unit per 1000 views; settle 999 views");
    expect_error(
        settle(&mut world, &creator, 1, [999, 0, 0, 0]),
        "NothingToSettle",
    );

    println!("settle 1999 views");
    settle(&mut world, &creator, 1, [1999, 0, 0, 0]).unwrap();
    println!("payout amount: {}", payout_of(&world, &creator, 1).amount);
    assert_eq!(payout_of(&world, &creator, 1).amount, 1);
}

#[test]
fn a_creator_cannot_earn_more_than_the_limit_set_by_the_brand() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let creator = Pubkey::new_unique();

    settle(&mut world, &creator, 1, UNITS).unwrap();
    println!(
        "epoch 1 paid {}; the limit per creator is {LIMIT}",
        payout_of(&world, &creator, 1).amount
    );

    println!("epoch 2 with the same units, worth {EARNED} again");
    settle(&mut world, &creator, 2, UNITS).unwrap();
    println!("epoch 2 paid {}", payout_of(&world, &creator, 2).amount);
    assert_eq!(payout_of(&world, &creator, 2).amount, LIMIT - EARNED);
    assert_eq!(position_of(&world, &creator).earned_total, LIMIT);

    println!("epoch 3 once the limit is reached");
    expect_error(settle(&mut world, &creator, 3, UNITS), "NothingToSettle");
    assert_eq!(position_of(&world, &creator).last_epoch, 2);
    assert_eq!(campaign_state(&world).reserved, LIMIT);
}

#[test]
fn payouts_never_exceed_the_budget_that_is_still_free() {
    let mut world = World::with_funded_campaign(1, 50 * CLIP_USD);
    let (first, second, third) = (
        Pubkey::new_unique(),
        Pubkey::new_unique(),
        Pubkey::new_unique(),
    );

    settle(&mut world, &first, 1, UNITS).unwrap();
    settle(&mut world, &second, 1, UNITS).unwrap();
    println!(
        "budget 50: first creator got {}, second got {}",
        payout_of(&world, &first, 1).amount,
        payout_of(&world, &second, 1).amount
    );
    assert_eq!(payout_of(&world, &first, 1).amount, EARNED);
    assert_eq!(payout_of(&world, &second, 1).amount, 15 * CLIP_USD);
    assert_eq!(campaign_state(&world).free_budget(), Some(0));

    println!("third creator, with nothing left");
    expect_error(settle(&mut world, &third, 1, UNITS), "NothingToSettle");
    assert_eq!(campaign_state(&world).reserved, 50 * CLIP_USD);
}

#[test]
fn an_epoch_is_settled_once_and_epochs_only_move_forward() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let creator = Pubkey::new_unique();
    let cranker = funded(&mut world.svm);
    let small = [1_000, 0, 0, 0];

    settle(&mut world, &creator, 2, small).unwrap();
    println!("epoch 2 settled; settling epoch 2 again");
    expect_error(settle(&mut world, &creator, 2, small), "already in use");

    println!("settling the earlier epoch 1");
    expect_error(
        settle(&mut world, &creator, 1, small),
        "EpochAlreadySettled",
    );

    set_time(&mut world.svm, END);
    release(&mut world, &cranker, &creator, 2).unwrap();
    println!("epoch 2 was released and its payout account closed; settling epoch 2 once more");
    expect_error(
        settle(&mut world, &creator, 2, small),
        "EpochAlreadySettled",
    );

    println!("epoch 3");
    settle(&mut world, &creator, 3, small).unwrap();
    assert_eq!(position_of(&world, &creator).last_epoch, 3);
}

#[test]
fn only_the_oracle_can_settle() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let campaign = campaign_of(&world);
    let creator = funded(&mut world.svm);

    println!("the creator settles for himself");
    let ix = settle_ix(&creator.pubkey(), &campaign, &creator.pubkey(), 1, UNITS);
    expect_error(send(&mut world.svm, ix, &[&creator]), "ConstraintHasOne");

    println!("the brand settles");
    let ix = settle_ix(
        &world.brand.pubkey(),
        &campaign,
        &creator.pubkey(),
        1,
        UNITS,
    );
    expect_error(
        send(&mut world.svm, ix, &[&world.brand]),
        "ConstraintHasOne",
    );

    assert_eq!(campaign_state(&world).reserved, 0);
}

#[test]
fn nothing_is_settled_before_the_campaign_starts() {
    let params = CampaignParams {
        start_ts: NOW + DAY,
        ..default_params()
    };
    let mut world = world_with(params, 100 * CLIP_USD);
    let creator = Pubkey::new_unique();

    println!("settle one day before the start");
    expect_error(settle(&mut world, &creator, 1, UNITS), "NotStarted");

    set_time(&mut world.svm, NOW + DAY);
    println!("settle at the start");
    settle(&mut world, &creator, 1, UNITS).unwrap();
}

#[test]
fn a_payout_unlocks_at_campaign_end_or_after_the_vesting_period_whichever_is_later() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let (early, late, after_end) = (
        Pubkey::new_unique(),
        Pubkey::new_unique(),
        Pubkey::new_unique(),
    );
    let small = [1_000, 0, 0, 0];

    settle(&mut world, &early, 1, small).unwrap();
    println!(
        "settled 30 days before the end: unlock_ts {} (end is {END})",
        payout_of(&world, &early, 1).unlock_ts
    );
    assert_eq!(payout_of(&world, &early, 1).unlock_ts, END);

    set_time(&mut world.svm, END - DAY);
    settle(&mut world, &late, 1, small).unwrap();
    println!(
        "settled 1 day before the end: unlock_ts {}",
        payout_of(&world, &late, 1).unlock_ts
    );
    assert_eq!(payout_of(&world, &late, 1).unlock_ts, END - DAY + VESTING);

    set_time(&mut world.svm, END + DAY);
    settle(&mut world, &after_end, 1, small).unwrap();
    println!(
        "settled 1 day after the end: unlock_ts {}",
        payout_of(&world, &after_end, 1).unlock_ts
    );
    assert_eq!(
        payout_of(&world, &after_end, 1).unlock_ts,
        END + DAY + VESTING
    );
}

#[test]
fn release_pays_the_creator_after_vesting_and_closes_the_payout() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let creator = Pubkey::new_unique();
    let cranker = funded(&mut world.svm);
    let oracle = world.oracle.pubkey();
    settle(&mut world, &creator, 1, UNITS).unwrap();
    let payout = payout_pda(&campaign_of(&world), &creator, 1);
    let oracle_before = lamports(&world.svm, &oracle);

    println!("release right after settle");
    expect_error(release(&mut world, &cranker, &creator, 1), "StillVesting");
    set_time(&mut world.svm, END - 1);
    println!("release one second before unlock");
    expect_error(release(&mut world, &cranker, &creator, 1), "StillVesting");

    set_time(&mut world.svm, END);
    println!("release at unlock, sent by a third party");
    release(&mut world, &cranker, &creator, 1).unwrap();

    let campaign = campaign_state(&world);
    let vault = vault_of(&campaign_of(&world), &world.mint);
    println!(
        "creator holds {}, vault holds {}, reserved {}, paid_total {}, claimed {}",
        creator_balance(&world, &creator),
        token_balance(&world.svm, &vault),
        campaign.reserved,
        campaign.paid_total,
        position_of(&world, &creator).claimed_total
    );
    assert_eq!(creator_balance(&world, &creator), EARNED);
    assert_eq!(token_balance(&world.svm, &vault), 65 * CLIP_USD);
    assert_eq!((campaign.reserved, campaign.paid_total), (0, EARNED));
    assert_eq!(position_of(&world, &creator).claimed_total, EARNED);

    println!(
        "payout account exists: {}; rent returned to the oracle: {} lamports; creator paid {} lamports",
        exists(&world.svm, &payout),
        lamports(&world.svm, &oracle) - oracle_before,
        lamports(&world.svm, &creator)
    );
    assert!(!exists(&world.svm, &payout));
    assert!(lamports(&world.svm, &oracle) > oracle_before);
    assert_eq!(lamports(&world.svm, &creator), 0);

    println!("release the same payout again");
    expect_error(
        release(&mut world, &cranker, &creator, 1),
        "AccountNotInitialized",
    );
    assert_eq!(creator_balance(&world, &creator), EARNED);
}

#[test]
fn a_payout_cannot_be_released_from_another_campaign() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let brand = world.brand.pubkey();
    let oracle = world.oracle.pubkey();
    let creator = Pubkey::new_unique();
    let cranker = funded(&mut world.svm);
    let first = campaign_of(&world);
    let second = campaign_pda(&brand, 2);

    let ix = create_campaign_ix(&brand, &world.mint, 2, default_params());
    send(&mut world.svm, ix, &[&world.brand]).unwrap();
    let brand_token = give_tokens(&mut world.svm, &brand, &world.mint, 100 * CLIP_USD);
    let ix = fund_campaign_ix(&brand, &second, &world.mint, &brand_token, 100 * CLIP_USD);
    send(&mut world.svm, ix, &[&world.brand]).unwrap();

    settle(&mut world, &creator, 1, UNITS).unwrap();
    let ix = settle_ix(&oracle, &second, &creator, 1, [1_000, 0, 0, 0]);
    send(&mut world.svm, ix, &[&world.oracle]).unwrap();
    set_time(&mut world.svm, END);

    println!("release the 35 clipUSD payout of campaign 1 against the vault of campaign 2");
    let ix = release_ix(
        &cranker.pubkey(),
        &second,
        &world.mint,
        &creator,
        &payout_pda(&first, &creator, 1),
        &oracle,
    );
    expect_error(send(&mut world.svm, ix, &[&cranker]), "ConstraintHasOne");
    assert_eq!(
        token_balance(&world.svm, &vault_of(&second, &world.mint)),
        100 * CLIP_USD
    );
}

#[test]
fn a_flag_from_the_brand_freezes_the_payout_until_the_arbiter_approves_it() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let creator = Pubkey::new_unique();
    let cranker = funded(&mut world.svm);
    settle(&mut world, &creator, 1, UNITS).unwrap();

    println!("the brand flags the payout");
    flag(&mut world, &creator, 1).unwrap();
    assert_eq!(payout_of(&world, &creator, 1).status, PayoutStatus::Flagged);

    set_time(&mut world.svm, END + DAY);
    println!("release after unlock while flagged");
    expect_error(release(&mut world, &cranker, &creator, 1), "PayoutFrozen");
    assert_eq!(campaign_state(&world).reserved, EARNED);

    println!("the arbiter approves");
    resolve(&mut world, &creator, 1, true).unwrap();
    assert_eq!(
        payout_of(&world, &creator, 1).status,
        PayoutStatus::Approved
    );

    println!("the brand flags the approved payout again");
    expect_error(flag(&mut world, &creator, 1), "PayoutNotPending");

    release(&mut world, &cranker, &creator, 1).unwrap();
    println!(
        "released: creator holds {}",
        creator_balance(&world, &creator)
    );
    assert_eq!(creator_balance(&world, &creator), EARNED);
}

#[test]
fn a_rejected_payout_returns_the_money_to_the_campaign_budget() {
    let mut world = World::with_funded_campaign(1, EARNED);
    let (cheater, honest) = (Pubkey::new_unique(), Pubkey::new_unique());
    let oracle = world.oracle.pubkey();
    settle(&mut world, &cheater, 1, UNITS).unwrap();
    let payout = payout_pda(&campaign_of(&world), &cheater, 1);

    println!("the whole budget is reserved; another creator cannot be settled");
    expect_error(settle(&mut world, &honest, 1, UNITS), "NothingToSettle");

    flag(&mut world, &cheater, 1).unwrap();
    let oracle_before = lamports(&world.svm, &oracle);
    println!("the arbiter rejects the flagged payout");
    resolve(&mut world, &cheater, 1, false).unwrap();

    let position = position_of(&world, &cheater);
    println!(
        "payout account exists: {}; reserved {}; position earned {} units {:?}; rent back to the oracle: {}",
        exists(&world.svm, &payout),
        campaign_state(&world).reserved,
        position.earned_total,
        position.units_total,
        lamports(&world.svm, &oracle) - oracle_before
    );
    assert!(!exists(&world.svm, &payout));
    assert_eq!(campaign_state(&world).reserved, 0);
    assert_eq!((position.earned_total, position.units_total), (0, [0; 4]));
    assert!(lamports(&world.svm, &oracle) > oracle_before);

    println!("the freed budget goes to the other creator");
    settle(&mut world, &honest, 1, UNITS).unwrap();
    assert_eq!(payout_of(&world, &honest, 1).amount, EARNED);

    println!("the rejected epoch cannot be settled again for the same creator");
    expect_error(
        settle(&mut world, &cheater, 1, UNITS),
        "EpochAlreadySettled",
    );
}

#[test]
fn only_the_brand_of_the_campaign_can_flag_and_only_before_unlock() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let campaign = campaign_of(&world);
    let creator = Pubkey::new_unique();
    settle(&mut world, &creator, 1, UNITS).unwrap();
    let payout = payout_pda(&campaign, &creator, 1);

    let stranger = funded(&mut world.svm);
    println!("a stranger flags the payout");
    let ix = flag_ix(&stranger.pubkey(), &campaign, &payout, 1);
    expect_error(send(&mut world.svm, ix, &[&stranger]), "ConstraintHasOne");

    println!("another brand flags it through its own campaign");
    let other_campaign = campaign_pda(&stranger.pubkey(), 1);
    let ix = create_campaign_ix(&stranger.pubkey(), &world.mint, 1, default_params());
    send(&mut world.svm, ix, &[&stranger]).unwrap();
    let ix = flag_ix(&stranger.pubkey(), &other_campaign, &payout, 1);
    expect_error(send(&mut world.svm, ix, &[&stranger]), "ConstraintHasOne");
    assert_eq!(payout_of(&world, &creator, 1).status, PayoutStatus::Pending);

    set_time(&mut world.svm, END);
    println!("the brand flags at unlock time");
    expect_error(flag(&mut world, &creator, 1), "FlagWindowClosed");

    set_time(&mut world.svm, END - 1);
    println!("the brand flags one second before unlock, then once more");
    flag(&mut world, &creator, 1).unwrap();
    expect_error(flag(&mut world, &creator, 1), "PayoutNotPending");
}

#[test]
fn only_the_arbiter_resolves_and_only_flagged_payouts() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let campaign = campaign_of(&world);
    let oracle = world.oracle.pubkey();
    let creator = Pubkey::new_unique();
    settle(&mut world, &creator, 1, UNITS).unwrap();

    println!("the arbiter cancels a payout nobody flagged");
    expect_error(resolve(&mut world, &creator, 1, false), "PayoutNotFlagged");

    flag(&mut world, &creator, 1).unwrap();
    println!("the brand rejects its own flag as if it were the arbiter");
    let ix = resolve_ix(
        &world.brand.pubkey(),
        &campaign,
        &creator,
        1,
        &oracle,
        false,
    );
    expect_error(
        send(&mut world.svm, ix, &[&world.brand]),
        "ConstraintHasOne",
    );

    println!("the oracle approves as if it were the arbiter");
    let ix = resolve_ix(&oracle, &campaign, &creator, 1, &oracle, true);
    expect_error(
        send(&mut world.svm, ix, &[&world.oracle]),
        "ConstraintHasOne",
    );

    println!("the arbiter cancels, naming himself as the rent receiver");
    let ix = resolve_ix(
        &world.arbiter.pubkey(),
        &campaign,
        &creator,
        1,
        &world.arbiter.pubkey(),
        false,
    );
    expect_error(
        send(&mut world.svm, ix, &[&world.arbiter]),
        "ConstraintHasOne",
    );

    assert_eq!(payout_of(&world, &creator, 1).status, PayoutStatus::Flagged);
}

#[test]
fn the_budget_cannot_be_taken_back_early_or_while_payouts_are_outstanding() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let brand = world.brand.pubkey();
    let creator = Pubkey::new_unique();
    let cranker = funded(&mut world.svm);
    give_tokens(&mut world.svm, &brand, &world.mint, 0);

    println!("close on the first day");
    expect_error(close(&mut world), "CampaignStillRunning");
    set_time(&mut world.svm, END + VESTING - 1);
    println!("close one second before end + vesting");
    expect_error(close(&mut world), "CampaignStillRunning");

    settle(&mut world, &creator, 1, UNITS).unwrap();
    set_time(&mut world.svm, END + VESTING);
    println!("close at end + vesting with one payout still vesting");
    expect_error(close(&mut world), "PayoutsOutstanding");

    println!("a stranger closes the campaign into his own account");
    let stranger = funded(&mut world.svm);
    let stranger_token = give_tokens(&mut world.svm, &stranger.pubkey(), &world.mint, 0);
    let ix = close_campaign_ix(
        &stranger.pubkey(),
        &campaign_of(&world),
        &world.mint,
        &stranger_token,
    );
    expect_error(send(&mut world.svm, ix, &[&stranger]), "ConstraintSeeds");

    println!("the brand closes into the stranger's token account");
    let ix = close_campaign_ix(&brand, &campaign_of(&world), &world.mint, &stranger_token);
    expect_error(
        send(&mut world.svm, ix, &[&world.brand]),
        "ConstraintTokenOwner",
    );

    set_time(&mut world.svm, END + 2 * VESTING);
    release(&mut world, &cranker, &creator, 1).unwrap();
    println!("close after the last payout is released");
    close(&mut world).unwrap();
    assert_eq!(campaign_state(&world).status, CampaignStatus::Closed);
}

#[test]
fn whole_campaign_every_token_ends_up_with_a_creator_or_back_with_the_brand() {
    let budget = 100 * CLIP_USD;
    let mut world = World::with_funded_campaign(1, budget);
    let brand = world.brand.pubkey();
    let brand_token = get_associated_token_address(&brand, &world.mint);
    let vault = vault_of(&campaign_of(&world), &world.mint);
    let cranker = funded(&mut world.svm);
    let (first, cheater, third) = (
        Pubkey::new_unique(),
        Pubkey::new_unique(),
        Pubkey::new_unique(),
    );

    settle(&mut world, &first, 1, UNITS).unwrap();
    settle(&mut world, &cheater, 1, UNITS).unwrap();
    println!("epoch 1: two creators settled, 35 each; the brand flags the second, the arbiter rejects it");
    flag(&mut world, &cheater, 1).unwrap();
    resolve(&mut world, &cheater, 1, false).unwrap();

    set_time(&mut world.svm, NOW + DAY);
    settle(&mut world, &third, 2, UNITS).unwrap();
    set_time(&mut world.svm, NOW + 2 * DAY);
    settle(&mut world, &third, 3, UNITS).unwrap();
    println!(
        "epochs 2 and 3: third creator settled {} and {} (limit {LIMIT})",
        payout_of(&world, &third, 2).amount,
        payout_of(&world, &third, 3).amount
    );

    set_time(&mut world.svm, END + VESTING);
    release(&mut world, &cranker, &first, 1).unwrap();
    release(&mut world, &cranker, &third, 2).unwrap();
    release(&mut world, &cranker, &third, 3).unwrap();
    close(&mut world).unwrap();

    let campaign = campaign_state(&world);
    let paid = creator_balance(&world, &first) + creator_balance(&world, &third);
    let refunded = token_balance(&world.svm, &brand_token);
    println!(
        "first {} + third {} = {paid} paid; {refunded} back to the brand; vault exists: {}; status {:?}",
        creator_balance(&world, &first),
        creator_balance(&world, &third),
        exists(&world.svm, &vault),
        campaign.status
    );
    assert_eq!(creator_balance(&world, &first), EARNED);
    assert_eq!(creator_balance(&world, &third), LIMIT);
    assert!(!exists(
        &world.svm,
        &get_associated_token_address(&cheater, &world.mint)
    ));
    assert_eq!(refunded, 25 * CLIP_USD);
    assert_eq!(paid + refunded, budget);
    assert_eq!((campaign.paid_total, campaign.reserved), (paid, 0));
    assert_eq!(campaign.status, CampaignStatus::Closed);
    assert!(!exists(&world.svm, &vault));
}

#[test]
fn a_closed_campaign_accepts_nothing_more() {
    let mut world = World::with_funded_campaign(1, 100 * CLIP_USD);
    let brand = world.brand.pubkey();
    let campaign = campaign_of(&world);
    let creator = Pubkey::new_unique();
    set_time(&mut world.svm, END + VESTING);
    close(&mut world).unwrap();
    let brand_token = get_associated_token_address(&brand, &world.mint);
    println!(
        "closed with no payouts: the brand got {} back",
        token_balance(&world.svm, &brand_token)
    );
    assert_eq!(token_balance(&world.svm, &brand_token), 100 * CLIP_USD);

    println!("settle on the closed campaign");
    expect_error(settle(&mut world, &creator, 1, UNITS), "CampaignClosed");

    println!("fund the closed campaign");
    let ix = fund_campaign_ix(&brand, &campaign, &world.mint, &brand_token, CLIP_USD);
    expect_error(
        send(&mut world.svm, ix, &[&world.brand]),
        "AccountNotInitialized",
    );

    println!("close it a second time");
    expect_error(close(&mut world), "AccountNotInitialized");
    assert_eq!(token_balance(&world.svm, &brand_token), 100 * CLIP_USD);
}
