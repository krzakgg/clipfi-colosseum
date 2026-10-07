use anchor_lang::prelude::*;

#[event]
pub struct CampaignCreated {
    pub campaign: Pubkey,
    pub brand: Pubkey,
    pub campaign_id: u64,
    pub vault: Pubkey,
    pub start_ts: i64,
    pub end_ts: i64,
}

#[event]
pub struct CampaignFunded {
    pub campaign: Pubkey,
    pub amount: u64,
    pub funded_total: u64,
}

#[event]
pub struct Settled {
    pub campaign: Pubkey,
    pub creator: Pubkey,
    pub epoch: u64,
    pub units: [u64; 4],
    pub amount: u64,
    pub unlock_ts: i64,
    pub evidence_hash: [u8; 32],
}

#[event]
pub struct PayoutFlagged {
    pub campaign: Pubkey,
    pub creator: Pubkey,
    pub epoch: u64,
    pub reason: u16,
}

#[event]
pub struct PayoutResolved {
    pub campaign: Pubkey,
    pub creator: Pubkey,
    pub epoch: u64,
    pub approved: bool,
    pub amount: u64,
}

#[event]
pub struct PayoutReleased {
    pub campaign: Pubkey,
    pub creator: Pubkey,
    pub epoch: u64,
    pub amount: u64,
}

#[event]
pub struct CampaignClosed {
    pub campaign: Pubkey,
    pub refunded: u64,
    pub paid_total: u64,
}

#[event]
pub struct Staked {
    pub creator: Pubkey,
    pub amount: u64,
    pub bond: u64,
}

#[event]
pub struct UnstakeRequested {
    pub creator: Pubkey,
    pub amount: u64,
    pub unstake_at: i64,
}

#[event]
pub struct StakeWithdrawn {
    pub creator: Pubkey,
    pub amount: u64,
    pub bond: u64,
}

#[event]
pub struct AutoRestakeSet {
    pub creator: Pubkey,
    pub auto_restake_bps: u16,
}

#[event]
pub struct Slashed {
    pub campaign: Pubkey,
    pub creator: Pubkey,
    pub amount: u64,
    pub bond: u64,
}

#[event]
pub struct RatesProposed {
    pub campaign: Pubkey,
    pub rates: [u64; 4],
    pub effective_at: i64,
}

#[event]
pub struct RatesApplied {
    pub campaign: Pubkey,
    pub rates: [u64; 4],
}

#[event]
pub struct StandardsProposed {
    pub campaign: Pubkey,
    pub standards_hash: [u8; 32],
    pub effective_at: i64,
}

#[event]
pub struct StandardsApplied {
    pub campaign: Pubkey,
    pub standards_hash: [u8; 32],
    pub standards_version: u32,
}

#[event]
pub struct BonusPoolFunded {
    pub amount: u64,
    pub pool_balance: u64,
}

#[event]
pub struct BonusPaid {
    pub campaign: Pubkey,
    pub creator: Pubkey,
    pub epoch: u64,
    pub bonus: u64,
}

#[event]
pub struct BonusSkipped {
    pub campaign: Pubkey,
    pub creator: Pubkey,
    pub epoch: u64,
    pub bonus: u64,
    pub pool_balance: u64,
}

#[event]
pub struct AutoRestaked {
    pub campaign: Pubkey,
    pub creator: Pubkey,
    pub epoch: u64,
    pub amount: u64,
}

#[event]
pub struct ConfigUpdated {
    pub oracle: Pubkey,
    pub arbiter: Pubkey,
    pub vesting_secs: i64,
    pub bonded_vesting_secs: i64,
    pub unstake_cooldown_secs: i64,
    pub notice_secs: i64,
}

#[event]
pub struct PausedSet {
    pub paused: bool,
}

#[event]
pub struct RolledOver {
    pub from_campaign: Pubkey,
    pub to_campaign: Pubkey,
    pub amount: u64,
}
