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
