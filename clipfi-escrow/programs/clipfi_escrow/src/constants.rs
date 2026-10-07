pub const CONFIG_SEED: &[u8] = b"config";
pub const CAMPAIGN_SEED: &[u8] = b"campaign";
pub const POSITION_SEED: &[u8] = b"position";
pub const PAYOUT_SEED: &[u8] = b"payout";
pub const STAKE_SEED: &[u8] = b"stake";

pub const ANCHOR_DISCRIMINATOR: usize = 8;
pub const MAX_VESTING_SECS: i64 = 21 * 24 * 60 * 60;
pub const UNITS_PER_RATE: u128 = 1000;
pub const BPS_DENOMINATOR: u128 = 10_000;
pub const MAX_BONUS_BPS: u16 = 2_000;
pub const BONUS_TIERS: usize = 3;
