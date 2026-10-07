use anchor_lang::prelude::*;
use anchor_spl::token_interface::{
    close_account, transfer_checked, CloseAccount, Mint, TokenAccount, TokenInterface,
    TransferChecked,
};

use crate::{
    error::ClipfiError, events::RolledOver, Campaign, CampaignStatus, Config, CAMPAIGN_SEED,
    CONFIG_SEED,
};

#[derive(Accounts)]
pub struct Rollover<'info> {
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
    pub campaign: Box<Account<'info, Campaign>>,

    #[account(mut)]
    pub vault: InterfaceAccount<'info, TokenAccount>,

    #[account(
        mut,
        has_one = brand @ ClipfiError::InvalidRolloverTarget,
        has_one = mint @ ClipfiError::InvalidRolloverTarget,
        constraint = target_campaign.key() != campaign.key() @ ClipfiError::InvalidRolloverTarget,
        constraint = target_campaign.status == CampaignStatus::Active @ ClipfiError::InvalidRolloverTarget,
        constraint = target_campaign.vault == target_vault.key() @ ClipfiError::InvalidRolloverTarget
    )]
    pub target_campaign: Box<Account<'info, Campaign>>,

    #[account(mut)]
    pub target_vault: InterfaceAccount<'info, TokenAccount>,

    pub mint: InterfaceAccount<'info, Mint>,

    pub token_program: Interface<'info, TokenInterface>,
}

impl Rollover<'_> {
    pub fn handle(&mut self) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        require!(
            self.campaign.status == CampaignStatus::Active,
            ClipfiError::CampaignClosed
        );
        let closable_from = self
            .campaign
            .end_ts
            .checked_add(self.config.vesting_secs)
            .ok_or(ClipfiError::Overflow)?;
        require!(now >= closable_from, ClipfiError::CampaignStillRunning);
        require!(self.campaign.reserved == 0, ClipfiError::PayoutsOutstanding);

        let amount = self.vault.amount;
        require!(amount > 0, ClipfiError::ZeroAmount);

        let campaign_id = self.campaign.campaign_id.to_le_bytes();
        let seeds = &[
            CAMPAIGN_SEED,
            self.campaign.brand.as_ref(),
            campaign_id.as_ref(),
            &[self.campaign.bump],
        ];
        let signer_seeds = [&seeds[..]];
        let accounts = TransferChecked {
            from: self.vault.to_account_info(),
            mint: self.mint.to_account_info(),
            to: self.target_vault.to_account_info(),
            authority: self.campaign.to_account_info(),
        };
        transfer_checked(
            CpiContext::new_with_signer(self.token_program.key(), accounts, &signer_seeds),
            amount,
            self.mint.decimals,
        )?;

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
        self.target_campaign.funded_total = self
            .target_campaign
            .funded_total
            .checked_add(amount)
            .ok_or(ClipfiError::Overflow)?;

        emit!(RolledOver {
            from_campaign: self.campaign.key(),
            to_campaign: self.target_campaign.key(),
            amount,
        });
        Ok(())
    }
}
