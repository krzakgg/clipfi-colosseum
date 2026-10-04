use anchor_lang::prelude::*;

#[account]
#[derive(InitSpace)]
pub struct Config {
    pub admin: Pubkey,
    pub oracle: Pubkey,
    pub arbiter: Pubkey,
    pub mint: Pubkey,
    pub vesting_secs: i64,
    pub bump: u8,
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
    pub max_per_creator: u64,
    pub start_ts: i64,
    pub end_ts: i64,
    pub standards_hash: [u8; 32],
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
    pub evidence_hash: [u8; 32],
    pub unlock_ts: i64,
    pub status: PayoutStatus,
    pub rent_payer: Pubkey,
    pub bump: u8,
}
