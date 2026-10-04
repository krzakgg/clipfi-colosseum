use anchor_lang::prelude::*;

use crate::{
    error::ClipfiError, events::PayoutResolved, Campaign, Config, CreatorPosition, Payout,
    PayoutStatus, CONFIG_SEED, POSITION_SEED,
};

#[derive(Accounts)]
pub struct Resolve<'info> {
    pub arbiter: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump, has_one = arbiter)]
    pub config: Account<'info, Config>,

    #[account(mut)]
    pub campaign: Account<'info, Campaign>,

    #[account(
        mut,
        seeds = [POSITION_SEED, campaign.key().as_ref(), payout.creator.as_ref()],
        bump = position.bump
    )]
    pub position: Account<'info, CreatorPosition>,

    #[account(mut, has_one = campaign, has_one = rent_payer)]
    pub payout: Account<'info, Payout>,

    /// CHECK: gets the rent back when the payout is cancelled
    #[account(mut)]
    pub rent_payer: UncheckedAccount<'info>,
}

impl Resolve<'_> {
    pub fn handle(&mut self, approve: bool) -> Result<()> {
        require!(
            self.payout.status == PayoutStatus::Flagged,
            ClipfiError::PayoutNotFlagged
        );
        let amount = self.payout.amount;

        emit!(PayoutResolved {
            campaign: self.campaign.key(),
            creator: self.payout.creator,
            epoch: self.payout.epoch,
            approved: approve,
            amount,
        });

        if approve {
            self.payout.status = PayoutStatus::Approved;
            return Ok(());
        }

        self.campaign.reserved = self
            .campaign
            .reserved
            .checked_sub(amount)
            .ok_or(ClipfiError::Underflow)?;
        self.position.earned_total = self
            .position
            .earned_total
            .checked_sub(amount)
            .ok_or(ClipfiError::Underflow)?;
        for (total, count) in self.position.units_total.iter_mut().zip(self.payout.units) {
            *total = total.checked_sub(count).ok_or(ClipfiError::Overflow)?;
        }
        self.payout.close(self.rent_payer.to_account_info())
    }
}
