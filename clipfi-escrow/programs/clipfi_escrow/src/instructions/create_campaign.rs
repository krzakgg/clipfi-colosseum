use anchor_lang::prelude::*;
use anchor_spl::{
    associated_token::AssociatedToken,
    token_interface::{Mint, TokenAccount, TokenInterface},
};

use crate::{
    error::ClipfiError, events::CampaignCreated, Campaign, CampaignStatus, Config,
    ANCHOR_DISCRIMINATOR, CAMPAIGN_SEED, CONFIG_SEED,
};

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct CampaignParams {
    pub rate_per_mille: [u64; 4],
    pub max_per_creator: u64,
    pub start_ts: i64,
    pub end_ts: i64,
    pub standards_hash: [u8; 32],
}

#[derive(Accounts)]
#[instruction(campaign_id: u64)]
pub struct CreateCampaign<'info> {
    #[account(mut)]
    pub brand: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump, has_one = mint)]
    pub config: Account<'info, Config>,

    #[account(mint::token_program = token_program)]
    pub mint: InterfaceAccount<'info, Mint>,

    #[account(
        init,
        payer = brand,
        space = ANCHOR_DISCRIMINATOR + Campaign::INIT_SPACE,
        seeds = [CAMPAIGN_SEED, brand.key().as_ref(), campaign_id.to_le_bytes().as_ref()],
        bump
    )]
    pub campaign: Account<'info, Campaign>,

    #[account(
        init,
        payer = brand,
        associated_token::mint = mint,
        associated_token::authority = campaign,
        associated_token::token_program = token_program
    )]
    pub vault: InterfaceAccount<'info, TokenAccount>,

    pub associated_token_program: Program<'info, AssociatedToken>,
    pub token_program: Interface<'info, TokenInterface>,
    pub system_program: Program<'info, System>,
}

impl CreateCampaign<'_> {
    pub fn handle(
        &mut self,
        campaign_id: u64,
        params: CampaignParams,
        bumps: &CreateCampaignBumps,
    ) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        require!(
            params.end_ts > params.start_ts && params.end_ts > now,
            ClipfiError::InvalidWindow
        );
        require!(
            params.rate_per_mille.iter().any(|rate| *rate > 0),
            ClipfiError::InvalidRates
        );
        require!(params.max_per_creator > 0, ClipfiError::InvalidLimit);

        self.campaign.set_inner(Campaign {
            brand: self.brand.key(),
            campaign_id,
            mint: self.mint.key(),
            vault: self.vault.key(),
            funded_total: 0,
            reserved: 0,
            paid_total: 0,
            rate_per_mille: params.rate_per_mille,
            max_per_creator: params.max_per_creator,
            start_ts: params.start_ts,
            end_ts: params.end_ts,
            standards_hash: params.standards_hash,
            status: CampaignStatus::Active,
            bump: bumps.campaign,
        });

        emit!(CampaignCreated {
            campaign: self.campaign.key(),
            brand: self.brand.key(),
            campaign_id,
            vault: self.vault.key(),
            start_ts: params.start_ts,
            end_ts: params.end_ts,
        });
        Ok(())
    }
}
