use anchor_lang::prelude::*;

use crate::{
    error::ClipfiError,
    events::{RatesProposed, StandardsProposed},
    Campaign, CampaignStatus, Config, CAMPAIGN_SEED, CONFIG_SEED,
};

#[derive(Accounts)]
pub struct ProposeRates<'info> {
    pub brand: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,

    #[account(
        mut,
        has_one = brand,
        seeds = [CAMPAIGN_SEED, brand.key().as_ref(), campaign.campaign_id.to_le_bytes().as_ref()],
        bump = campaign.bump
    )]
    pub campaign: Account<'info, Campaign>,
}

impl ProposeRates<'_> {
    pub fn handle(&mut self, rates: [u64; 4]) -> Result<()> {
        require!(
            self.campaign.status == CampaignStatus::Active,
            ClipfiError::CampaignClosed
        );
        require!(
            rates.iter().any(|rate| *rate > 0),
            ClipfiError::InvalidRates
        );
        let now = Clock::get()?.unix_timestamp;
        let effective_at = now
            .checked_add(self.config.notice_secs)
            .ok_or(ClipfiError::Overflow)?;
        self.campaign.pending_rates = rates;
        self.campaign.pending_rates_at = effective_at;
        emit!(RatesProposed {
            campaign: self.campaign.key(),
            rates,
            effective_at,
        });
        Ok(())
    }
}

#[derive(Accounts)]
pub struct ProposeStandards<'info> {
    pub brand: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,

    #[account(
        mut,
        has_one = brand,
        seeds = [CAMPAIGN_SEED, brand.key().as_ref(), campaign.campaign_id.to_le_bytes().as_ref()],
        bump = campaign.bump
    )]
    pub campaign: Account<'info, Campaign>,
}

impl ProposeStandards<'_> {
    pub fn handle(&mut self, standards_hash: [u8; 32]) -> Result<()> {
        require!(
            self.campaign.status == CampaignStatus::Active,
            ClipfiError::CampaignClosed
        );
        let now = Clock::get()?.unix_timestamp;
        let effective_at = now
            .checked_add(self.config.notice_secs)
            .ok_or(ClipfiError::Overflow)?;
        self.campaign.pending_standards_hash = standards_hash;
        self.campaign.pending_standards_at = effective_at;
        emit!(StandardsProposed {
            campaign: self.campaign.key(),
            standards_hash,
            effective_at,
        });
        Ok(())
    }
}
