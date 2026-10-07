use anchor_lang::prelude::*;

use crate::BONUS_TIERS;

#[derive(
    AnchorSerialize, AnchorDeserialize, InitSpace, Clone, Copy, PartialEq, Eq, Debug, Default,
)]
pub struct BonusTier {
    pub min_bond: u64,
    pub bonus_bps: u16,
}

#[account]
#[derive(InitSpace)]
pub struct Config {
    pub admin: Pubkey,
    pub oracle: Pubkey,
    pub arbiter: Pubkey,
    pub mint: Pubkey,
    pub bonus_vault: Pubkey,
    pub vesting_secs: i64,
    pub bonded_vesting_secs: i64,
    pub unstake_cooldown_secs: i64,
    pub notice_secs: i64,
    pub bonus_tiers: [BonusTier; BONUS_TIERS],
    pub paused: bool,
    pub bump: u8,
}

impl Config {
    pub fn bonus_bps_for(&self, bond: u64) -> u16 {
        self.bonus_tiers
            .iter()
            .filter(|tier| tier.min_bond > 0 && bond >= tier.min_bond)
            .map(|tier| tier.bonus_bps)
            .max()
            .unwrap_or(0)
    }
}

#[derive(AnchorSerialize, AnchorDeserialize, InitSpace, Clone, Copy, PartialEq, Eq, Debug)]
pub enum CampaignStatus {
    Active,
    Closed,
}

#[account]
#[derive(InitSpace)]
pub struct Campaign {
    pub brand: Pubkey,
    pub campaign_id: u64,
    pub mint: Pubkey,
    pub vault: Pubkey,
    pub funded_total: u64,
    pub reserved: u64,
    pub paid_total: u64,
    // short, long, stream, click
    pub rate_per_mille: [u64; 4],
    pub pending_rates: [u64; 4],
    pub pending_rates_at: i64,
    pub max_per_creator: u64,
    pub min_bond: u64,
    pub start_ts: i64,
    pub end_ts: i64,
    pub standards_hash: [u8; 32],
    pub standards_version: u32,
    pub pending_standards_hash: [u8; 32],
    pub pending_standards_at: i64,
    pub status: CampaignStatus,
    pub bump: u8,
}

impl Campaign {
    pub fn free_budget(&self) -> Option<u64> {
        self.funded_total
            .checked_sub(self.paid_total)?
            .checked_sub(self.reserved)
    }
}

#[account]
#[derive(InitSpace)]
pub struct CreatorPosition {
    pub campaign: Pubkey,
    pub creator: Pubkey,
    pub earned_total: u64,
    pub claimed_total: u64,
    pub last_epoch: u64,
    pub units_total: [u64; 4],
    pub bump: u8,
}

// a released or cancelled payout is closed, so those two states only exist as events
#[derive(AnchorSerialize, AnchorDeserialize, InitSpace, Clone, Copy, PartialEq, Eq, Debug)]
pub enum PayoutStatus {
    Pending,
    Flagged,
    Approved,
}

#[account]
#[derive(InitSpace)]
pub struct Payout {
    pub campaign: Pubkey,
    pub creator: Pubkey,
    pub epoch: u64,
    pub units: [u64; 4],
    pub amount: u64,
    pub bonus_bps: u16,
    pub restake_bps: u16,
    pub standards_version: u32,
    pub evidence_hash: [u8; 32],
    pub unlock_ts: i64,
    pub status: PayoutStatus,
    pub rent_payer: Pubkey,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct Stake {
    pub creator: Pubkey,
    pub token: Pubkey,
    pub amount: u64,
    pub pending_unstake: u64,
    pub unstake_at: i64,
    pub auto_restake_bps: u16,
    pub slashed_total: u64,
    pub bump: u8,
}

impl Stake {
    pub fn bonded(&self) -> u64 {
        self.amount.saturating_sub(self.pending_unstake)
    }
}
