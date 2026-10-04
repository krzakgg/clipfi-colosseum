use anchor_lang::prelude::*;

use crate::{
    error::ClipfiError, events::Settled, Campaign, CampaignStatus, Config, CreatorPosition, Payout,
    PayoutStatus, ANCHOR_DISCRIMINATOR, CAMPAIGN_SEED, CONFIG_SEED, PAYOUT_SEED, POSITION_SEED,
    UNITS_PER_RATE,
};

#[derive(Accounts)]
#[instruction(epoch: u64)]
pub struct Settle<'info> {
    #[account(mut)]
    pub oracle: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump, has_one = oracle)]
    pub config: Account<'info, Config>,

    #[account(
        mut,
        seeds = [CAMPAIGN_SEED, campaign.brand.as_ref(), campaign.campaign_id.to_le_bytes().as_ref()],
        bump = campaign.bump
    )]
    pub campaign: Box<Account<'info, Campaign>>,

    /// CHECK: only names whose position and payout these are
    pub creator: UncheckedAccount<'info>,

    #[account(
        init_if_needed,
        payer = oracle,
        space = ANCHOR_DISCRIMINATOR + CreatorPosition::INIT_SPACE,
        seeds = [POSITION_SEED, campaign.key().as_ref(), creator.key().as_ref()],
        bump
    )]
    pub position: Box<Account<'info, CreatorPosition>>,

    #[account(
        init,
        payer = oracle,
        space = ANCHOR_DISCRIMINATOR + Payout::INIT_SPACE,
        seeds = [
            PAYOUT_SEED,
            campaign.key().as_ref(),
            creator.key().as_ref(),
            epoch.to_le_bytes().as_ref()
        ],
        bump
    )]
    pub payout: Box<Account<'info, Payout>>,

    pub system_program: Program<'info, System>,
}

impl Settle<'_> {
    pub fn handle(
        &mut self,
        epoch: u64,
        units: [u64; 4],
        evidence_hash: [u8; 32],
        bumps: &SettleBumps,
    ) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        let campaign = &mut self.campaign;
        let position = &mut self.position;

        require!(
            campaign.status == CampaignStatus::Active,
            ClipfiError::CampaignClosed
        );
        require!(now >= campaign.start_ts, ClipfiError::NotStarted);
        require!(
            epoch > position.last_epoch,
            ClipfiError::EpochAlreadySettled
        );

        let mut gross: u128 = 0;
        for (count, rate) in units.iter().zip(campaign.rate_per_mille) {
            let part = u128::from(*count)
                .checked_mul(u128::from(rate))
                .ok_or(ClipfiError::Overflow)?;
            gross = gross.checked_add(part).ok_or(ClipfiError::Overflow)?;
        }
        let gross = gross / UNITS_PER_RATE;

        let creator_room = campaign
            .max_per_creator
            .checked_sub(position.earned_total)
            .ok_or(ClipfiError::Underflow)?;
        let free = campaign.free_budget().ok_or(ClipfiError::Underflow)?;
        let amount = gross.min(u128::from(creator_room)).min(u128::from(free)) as u64;
        require!(amount > 0, ClipfiError::NothingToSettle);

        let vested = now
            .checked_add(self.config.vesting_secs)
            .ok_or(ClipfiError::Overflow)?;
        let unlock_ts = vested.max(campaign.end_ts);

        campaign.reserved = campaign
            .reserved
            .checked_add(amount)
            .ok_or(ClipfiError::Overflow)?;

        position.campaign = campaign.key();
        position.creator = self.creator.key();
        position.bump = bumps.position;
        position.last_epoch = epoch;
        position.earned_total = position
            .earned_total
            .checked_add(amount)
            .ok_or(ClipfiError::Overflow)?;
        for (total, count) in position.units_total.iter_mut().zip(units) {
            *total = total.checked_add(count).ok_or(ClipfiError::Overflow)?;
        }

        self.payout.set_inner(Payout {
            campaign: campaign.key(),
            creator: self.creator.key(),
            epoch,
            units,
            amount,
            evidence_hash,
            unlock_ts,
            status: PayoutStatus::Pending,
            rent_payer: self.oracle.key(),
            bump: bumps.payout,
        });

        emit!(Settled {
            campaign: campaign.key(),
            creator: self.creator.key(),
            epoch,
            units,
            amount,
            unlock_ts,
            evidence_hash,
        });
        Ok(())
    }
}
