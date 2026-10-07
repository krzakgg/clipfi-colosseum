use anchor_lang::prelude::*;
use anchor_spl::{
    associated_token::AssociatedToken,
    token_interface::{transfer_checked, Mint, TokenAccount, TokenInterface, TransferChecked},
};

use crate::{
    error::ClipfiError,
    events::{AutoRestaked, BonusPaid, BonusSkipped, PayoutReleased},
    Campaign, Config, CreatorPosition, Payout, PayoutStatus, Stake, BPS_DENOMINATOR, CAMPAIGN_SEED,
    CONFIG_SEED, POSITION_SEED, STAKE_SEED,
};

#[derive(Accounts)]
pub struct Release<'info> {
    #[account(mut)]
    pub cranker: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump, has_one = mint, has_one = bonus_vault)]
    pub config: Box<Account<'info, Config>>,

    #[account(mut, has_one = mint, has_one = vault)]
    pub campaign: Box<Account<'info, Campaign>>,

    pub mint: Box<InterfaceAccount<'info, Mint>>,

    #[account(mut)]
    pub vault: Box<InterfaceAccount<'info, TokenAccount>>,

    #[account(mut)]
    pub bonus_vault: Box<InterfaceAccount<'info, TokenAccount>>,

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

    #[account(mut, seeds = [STAKE_SEED, creator.key().as_ref()], bump)]
    pub stake: Option<Box<Account<'info, Stake>>>,

    #[account(mut, token::mint = mint, token::token_program = token_program)]
    pub stake_token: Option<Box<InterfaceAccount<'info, TokenAccount>>>,

    pub associated_token_program: Program<'info, AssociatedToken>,
    pub token_program: Interface<'info, TokenInterface>,
    pub system_program: Program<'info, System>,
}

fn share(amount: u64, bps: u16) -> Result<u64> {
    let value = u128::from(amount)
        .checked_mul(u128::from(bps))
        .ok_or(ClipfiError::Overflow)?
        / BPS_DENOMINATOR;
    Ok(value as u64)
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
        let epoch = self.payout.epoch;

        let campaign_id = self.campaign.campaign_id.to_le_bytes();
        let seeds = &[
            CAMPAIGN_SEED,
            self.campaign.brand.as_ref(),
            campaign_id.as_ref(),
            &[self.campaign.bump],
        ];
        let signer_seeds = [&seeds[..]];

        let restake = if self.payout.restake_bps > 0 {
            let (stake, stake_token) = match (&self.stake, &self.stake_token) {
                (Some(stake), Some(stake_token)) => (stake, stake_token),
                _ => return err!(ClipfiError::StakeRequired),
            };
            require_keys_eq!(stake.token, stake_token.key(), ClipfiError::Unauthorized);
            share(amount, self.payout.restake_bps)?
        } else {
            0
        };
        if restake > 0 {
            let stake_token = self.stake_token.as_ref().unwrap();
            let accounts = TransferChecked {
                from: self.vault.to_account_info(),
                mint: self.mint.to_account_info(),
                to: stake_token.to_account_info(),
                authority: self.campaign.to_account_info(),
            };
            transfer_checked(
                CpiContext::new_with_signer(self.token_program.key(), accounts, &signer_seeds),
                restake,
                self.mint.decimals,
            )?;
            let stake = self.stake.as_mut().unwrap();
            stake.amount = stake
                .amount
                .checked_add(restake)
                .ok_or(ClipfiError::Overflow)?;
            emit!(AutoRestaked {
                campaign: self.campaign.key(),
                creator: self.creator.key(),
                epoch,
                amount: restake,
            });
        }

        let to_creator = amount.checked_sub(restake).ok_or(ClipfiError::Underflow)?;
        if to_creator > 0 {
            let accounts = TransferChecked {
                from: self.vault.to_account_info(),
                mint: self.mint.to_account_info(),
                to: self.creator_token.to_account_info(),
                authority: self.campaign.to_account_info(),
            };
            transfer_checked(
                CpiContext::new_with_signer(self.token_program.key(), accounts, &signer_seeds),
                to_creator,
                self.mint.decimals,
            )?;
        }

        self.campaign.reserved = self
            .campaign
            .reserved
            .checked_sub(amount)
            .ok_or(ClipfiError::Underflow)?;
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

        let bonus = share(amount, self.payout.bonus_bps)?;
        if bonus > 0 {
            if self.bonus_vault.amount >= bonus {
                let config_seeds = &[CONFIG_SEED, &[self.config.bump]];
                let config_signer = [&config_seeds[..]];
                let accounts = TransferChecked {
                    from: self.bonus_vault.to_account_info(),
                    mint: self.mint.to_account_info(),
                    to: self.creator_token.to_account_info(),
                    authority: self.config.to_account_info(),
                };
                transfer_checked(
                    CpiContext::new_with_signer(self.token_program.key(), accounts, &config_signer),
                    bonus,
                    self.mint.decimals,
                )?;
                emit!(BonusPaid {
                    campaign: self.campaign.key(),
                    creator: self.creator.key(),
                    epoch,
                    bonus,
                });
            } else {
                emit!(BonusSkipped {
                    campaign: self.campaign.key(),
                    creator: self.creator.key(),
                    epoch,
                    bonus,
                    pool_balance: self.bonus_vault.amount,
                });
            }
        }

        emit!(PayoutReleased {
            campaign: self.campaign.key(),
            creator: self.creator.key(),
            epoch,
            amount,
        });
        Ok(())
    }
}
