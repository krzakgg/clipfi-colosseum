use anchor_lang::prelude::*;
use anchor_spl::{
    associated_token::AssociatedToken,
    token_interface::{transfer_checked, Mint, TokenAccount, TokenInterface, TransferChecked},
};

use crate::{
    error::ClipfiError, events::PayoutReleased, Campaign, CreatorPosition, Payout, PayoutStatus,
    CAMPAIGN_SEED, POSITION_SEED,
};

#[derive(Accounts)]
pub struct Release<'info> {
    #[account(mut)]
    pub cranker: Signer<'info>,

    #[account(mut, has_one = mint, has_one = vault)]
    pub campaign: Box<Account<'info, Campaign>>,

    pub mint: Box<InterfaceAccount<'info, Mint>>,

    #[account(mut)]
    pub vault: Box<InterfaceAccount<'info, TokenAccount>>,

    /// CHECK: the creator named in the payout
    pub creator: UncheckedAccount<'info>,

    #[account(
        init_if_needed,
        payer = cranker,
        associated_token::mint = mint,
        associated_token::authority = creator,
        associated_token::token_program = token_program
    )]
    pub creator_token: Box<InterfaceAccount<'info, TokenAccount>>,

    #[account(
        mut,
        seeds = [POSITION_SEED, campaign.key().as_ref(), creator.key().as_ref()],
        bump = position.bump
    )]
    pub position: Box<Account<'info, CreatorPosition>>,

    #[account(
        mut,
        close = rent_payer,
        has_one = campaign,
        has_one = creator,
        has_one = rent_payer
    )]
    pub payout: Box<Account<'info, Payout>>,

    /// CHECK: gets the payout rent back
    #[account(mut)]
    pub rent_payer: UncheckedAccount<'info>,

    pub associated_token_program: Program<'info, AssociatedToken>,
    pub token_program: Interface<'info, TokenInterface>,
    pub system_program: Program<'info, System>,
}

impl Release<'_> {
    pub fn handle(&mut self) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        require!(
            self.payout.status != PayoutStatus::Flagged,
            ClipfiError::PayoutFrozen
        );
        require!(now >= self.payout.unlock_ts, ClipfiError::StillVesting);
        let amount = self.payout.amount;

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
            to: self.creator_token.to_account_info(),
            authority: self.campaign.to_account_info(),
        };
        transfer_checked(
            CpiContext::new_with_signer(self.token_program.key(), accounts, &signer_seeds),
            amount,
            self.mint.decimals,
        )?;

        self.campaign.reserved = self
            .campaign
            .reserved
            .checked_sub(amount)
            .ok_or(ClipfiError::Overflow)?;
        self.campaign.paid_total = self
            .campaign
            .paid_total
            .checked_add(amount)
            .ok_or(ClipfiError::Overflow)?;
        self.position.claimed_total = self
            .position
            .claimed_total
            .checked_add(amount)
            .ok_or(ClipfiError::Overflow)?;

        emit!(PayoutReleased {
            campaign: self.campaign.key(),
            creator: self.creator.key(),
            epoch: self.payout.epoch,
            amount,
        });
        Ok(())
    }
}
