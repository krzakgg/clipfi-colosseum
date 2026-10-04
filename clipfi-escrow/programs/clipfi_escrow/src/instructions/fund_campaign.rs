use anchor_lang::prelude::*;
use anchor_spl::token_interface::{
    transfer_checked, Mint, TokenAccount, TokenInterface, TransferChecked,
};

use crate::{error::ClipfiError, events::CampaignFunded, Campaign, CampaignStatus, CAMPAIGN_SEED};

#[derive(Accounts)]
pub struct FundCampaign<'info> {
    pub brand: Signer<'info>,

    #[account(
        mut,
        has_one = brand,
        has_one = mint,
        has_one = vault,
        seeds = [CAMPAIGN_SEED, brand.key().as_ref(), campaign.campaign_id.to_le_bytes().as_ref()],
        bump = campaign.bump
    )]
    pub campaign: Account<'info, Campaign>,

    pub mint: InterfaceAccount<'info, Mint>,

    #[account(
        mut,
        token::mint = mint,
        token::authority = brand,
        token::token_program = token_program
    )]
    pub brand_token: InterfaceAccount<'info, TokenAccount>,

    #[account(mut)]
    pub vault: InterfaceAccount<'info, TokenAccount>,

    pub token_program: Interface<'info, TokenInterface>,
}

impl FundCampaign<'_> {
    pub fn handle(&mut self, amount: u64) -> Result<()> {
        require!(amount > 0, ClipfiError::ZeroAmount);
        require!(
            self.campaign.status == CampaignStatus::Active,
            ClipfiError::CampaignClosed
        );

        let accounts = TransferChecked {
            from: self.brand_token.to_account_info(),
            mint: self.mint.to_account_info(),
            to: self.vault.to_account_info(),
            authority: self.brand.to_account_info(),
        };
        transfer_checked(
            CpiContext::new(self.token_program.key(), accounts),
            amount,
            self.mint.decimals,
        )?;

        self.campaign.funded_total = self
            .campaign
            .funded_total
            .checked_add(amount)
            .ok_or(ClipfiError::Overflow)?;

        emit!(CampaignFunded {
            campaign: self.campaign.key(),
            amount,
            funded_total: self.campaign.funded_total,
        });
        Ok(())
    }
}
