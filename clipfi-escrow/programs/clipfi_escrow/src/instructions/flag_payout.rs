use anchor_lang::prelude::*;

use crate::{error::ClipfiError, events::PayoutFlagged, Campaign, Payout, PayoutStatus};

#[derive(Accounts)]
pub struct FlagPayout<'info> {
    pub brand: Signer<'info>,

    #[account(has_one = brand)]
    pub campaign: Account<'info, Campaign>,

    #[account(mut, has_one = campaign)]
    pub payout: Account<'info, Payout>,
}

impl FlagPayout<'_> {
    pub fn handle(&mut self, reason: u16) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        require!(
            self.payout.status == PayoutStatus::Pending,
            ClipfiError::PayoutNotPending
        );
        require!(now < self.payout.unlock_ts, ClipfiError::FlagWindowClosed);

        self.payout.status = PayoutStatus::Flagged;

        emit!(PayoutFlagged {
            campaign: self.campaign.key(),
            creator: self.payout.creator,
            epoch: self.payout.epoch,
            reason,
        });
        Ok(())
    }
}
