use anchor_lang::prelude::*;
use anchor_spl::token_interface::{
    close_account, transfer_checked, CloseAccount, Mint, TokenAccount, TokenInterface,
    TransferChecked,
};

use crate::{
    error::ClipfiError, events::CampaignClosed, Campaign, CampaignStatus, Config, CAMPAIGN_SEED,
    CONFIG_SEED,
};

#[derive(Accounts)]
pub struct CloseCampaign<'info> {
    #[account(mut)]
    pub brand: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,

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

    #[account(mut)]
    pub vault: InterfaceAccount<'info, TokenAccount>,

    #[account(
        mut,
        token::mint = mint,
        token::authority = brand,
        token::token_program = token_program
    )]
    pub brand_token: InterfaceAccount<'info, TokenAccount>,

    pub token_program: Interface<'info, TokenInterface>,
}

impl CloseCampaign<'_> {
    pub fn handle(&mut self) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        require!(
            self.campaign.status == CampaignStatus::Active,
            ClipfiError::CampaignClosed
        );
        // the oracle gets one vesting period after the end to settle the last epoch
        let closable_from = self
            .campaign
            .end_ts
            .checked_add(self.config.vesting_secs)
            .ok_or(ClipfiError::Overflow)?;
        require!(now >= closable_from, ClipfiError::CampaignStillRunning);
        require!(self.campaign.reserved == 0, ClipfiError::PayoutsOutstanding);

        let campaign_id = self.campaign.campaign_id.to_le_bytes();
        let seeds = &[
            CAMPAIGN_SEED,
            self.campaign.brand.as_ref(),
            campaign_id.as_ref(),
            &[self.campaign.bump],
        ];
        let signer_seeds = [&seeds[..]];

        let refunded = self.vault.amount;
        if refunded > 0 {
            let accounts = TransferChecked {
                from: self.vault.to_account_info(),
                mint: self.mint.to_account_info(),
                to: self.brand_token.to_account_info(),
                authority: self.campaign.to_account_info(),
            };
            transfer_checked(
                CpiContext::new_with_signer(self.token_program.key(), accounts, &signer_seeds),
                refunded,
                self.mint.decimals,
            )?;
        }

        let accounts = CloseAccount {
            account: self.vault.to_account_info(),
            destination: self.brand.to_account_info(),
            authority: self.campaign.to_account_info(),
        };
        close_account(CpiContext::new_with_signer(
            self.token_program.key(),
            accounts,
            &signer_seeds,
        ))?;

        self.campaign.status = CampaignStatus::Closed;

        emit!(CampaignClosed {
            campaign: self.campaign.key(),
            refunded,
            paid_total: self.campaign.paid_total,
        });
        Ok(())
    }
}
