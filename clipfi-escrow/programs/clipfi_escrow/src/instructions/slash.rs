use anchor_lang::prelude::*;
use anchor_spl::token_interface::{
    transfer_checked, Mint, TokenAccount, TokenInterface, TransferChecked,
};

use crate::{
    error::ClipfiError, events::Slashed, Campaign, CampaignStatus, Config, Stake, CONFIG_SEED,
    STAKE_SEED,
};

#[derive(Accounts)]
pub struct Slash<'info> {
    pub arbiter: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump, has_one = arbiter, has_one = mint)]
    pub config: Box<Account<'info, Config>>,

    #[account(mut, has_one = mint, has_one = vault)]
    pub campaign: Box<Account<'info, Campaign>>,

    pub mint: Box<InterfaceAccount<'info, Mint>>,

    #[account(mut)]
    pub vault: Box<InterfaceAccount<'info, TokenAccount>>,

    /// CHECK: the bonded creator being slashed
    pub creator: UncheckedAccount<'info>,

    #[account(mut, has_one = creator, seeds = [STAKE_SEED, creator.key().as_ref()], bump = stake.bump)]
    pub stake: Box<Account<'info, Stake>>,

    #[account(mut, address = stake.token)]
    pub stake_token: Box<InterfaceAccount<'info, TokenAccount>>,

    pub token_program: Interface<'info, TokenInterface>,
}

impl Slash<'_> {
    pub fn handle(&mut self, amount: u64) -> Result<()> {
        require!(amount > 0, ClipfiError::ZeroAmount);
        require!(
            self.campaign.status == CampaignStatus::Active,
            ClipfiError::CampaignClosed
        );
        require!(amount <= self.stake.amount, ClipfiError::InsufficientStake);

        let creator = self.creator.key();
        let seeds = &[STAKE_SEED, creator.as_ref(), &[self.stake.bump]];
        let signer_seeds = [&seeds[..]];
        let accounts = TransferChecked {
            from: self.stake_token.to_account_info(),
            mint: self.mint.to_account_info(),
            to: self.vault.to_account_info(),
            authority: self.stake.to_account_info(),
        };
        transfer_checked(
            CpiContext::new_with_signer(self.token_program.key(), accounts, &signer_seeds),
            amount,
            self.mint.decimals,
        )?;

        let stake = &mut self.stake;
        stake.amount = stake
            .amount
            .checked_sub(amount)
            .ok_or(ClipfiError::Underflow)?;
        stake.pending_unstake = stake.pending_unstake.min(stake.amount);
        stake.slashed_total = stake
            .slashed_total
            .checked_add(amount)
            .ok_or(ClipfiError::Overflow)?;
        self.campaign.funded_total = self
            .campaign
            .funded_total
            .checked_add(amount)
            .ok_or(ClipfiError::Overflow)?;

        emit!(Slashed {
            campaign: self.campaign.key(),
            creator,
            amount,
            bond: stake.bonded(),
        });
        Ok(())
    }
}
