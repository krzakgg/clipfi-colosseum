use anchor_lang::prelude::*;
use anchor_spl::{
    associated_token::AssociatedToken,
    token_interface::{transfer_checked, Mint, TokenAccount, TokenInterface, TransferChecked},
};

use crate::{
    error::ClipfiError,
    events::{AutoRestakeSet, BonusPoolFunded, StakeWithdrawn, Staked, UnstakeRequested},
    Config, Stake, ANCHOR_DISCRIMINATOR, BPS_DENOMINATOR, CONFIG_SEED, STAKE_SEED,
};

#[derive(Accounts)]
pub struct StakeTokens<'info> {
    #[account(mut)]
    pub creator: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump, has_one = mint)]
    pub config: Account<'info, Config>,

    #[account(mint::token_program = token_program)]
    pub mint: InterfaceAccount<'info, Mint>,

    #[account(
        init_if_needed,
        payer = creator,
        space = ANCHOR_DISCRIMINATOR + Stake::INIT_SPACE,
        seeds = [STAKE_SEED, creator.key().as_ref()],
        bump
    )]
    pub stake: Account<'info, Stake>,

    #[account(
        init_if_needed,
        payer = creator,
        associated_token::mint = mint,
        associated_token::authority = stake,
        associated_token::token_program = token_program
    )]
    pub stake_token: InterfaceAccount<'info, TokenAccount>,

    #[account(
        mut,
        token::mint = mint,
        token::authority = creator,
        token::token_program = token_program
    )]
    pub creator_token: InterfaceAccount<'info, TokenAccount>,

    pub associated_token_program: Program<'info, AssociatedToken>,
    pub token_program: Interface<'info, TokenInterface>,
    pub system_program: Program<'info, System>,
}

impl StakeTokens<'_> {
    pub fn handle(&mut self, amount: u64, bumps: &StakeTokensBumps) -> Result<()> {
        require!(amount > 0, ClipfiError::ZeroAmount);
        require!(!self.config.paused, ClipfiError::Paused);

        let accounts = TransferChecked {
            from: self.creator_token.to_account_info(),
            mint: self.mint.to_account_info(),
            to: self.stake_token.to_account_info(),
            authority: self.creator.to_account_info(),
        };
        transfer_checked(
            CpiContext::new(self.token_program.key(), accounts),
            amount,
            self.mint.decimals,
        )?;

        let stake = &mut self.stake;
        stake.creator = self.creator.key();
        stake.token = self.stake_token.key();
        stake.bump = bumps.stake;
        stake.amount = stake
            .amount
            .checked_add(amount)
            .ok_or(ClipfiError::Overflow)?;

        emit!(Staked {
            creator: self.creator.key(),
            amount,
            bond: stake.bonded(),
        });
        Ok(())
    }
}

#[derive(Accounts)]
pub struct RequestUnstake<'info> {
    pub creator: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,

    #[account(mut, has_one = creator, seeds = [STAKE_SEED, creator.key().as_ref()], bump = stake.bump)]
    pub stake: Account<'info, Stake>,
}

impl RequestUnstake<'_> {
    pub fn handle(&mut self, amount: u64) -> Result<()> {
        require!(amount > 0, ClipfiError::ZeroAmount);
        let now = Clock::get()?.unix_timestamp;
        let stake = &mut self.stake;
        require!(amount <= stake.bonded(), ClipfiError::InsufficientStake);
        stake.pending_unstake = stake
            .pending_unstake
            .checked_add(amount)
            .ok_or(ClipfiError::Overflow)?;
        stake.unstake_at = now
            .checked_add(self.config.unstake_cooldown_secs)
            .ok_or(ClipfiError::Overflow)?;

        emit!(UnstakeRequested {
            creator: self.creator.key(),
            amount,
            unstake_at: stake.unstake_at,
        });
        Ok(())
    }
}

#[derive(Accounts)]
pub struct WithdrawStake<'info> {
    pub creator: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump, has_one = mint)]
    pub config: Account<'info, Config>,

    pub mint: InterfaceAccount<'info, Mint>,

    #[account(mut, has_one = creator, seeds = [STAKE_SEED, creator.key().as_ref()], bump = stake.bump)]
    pub stake: Account<'info, Stake>,

    #[account(mut, address = stake.token)]
    pub stake_token: InterfaceAccount<'info, TokenAccount>,

    #[account(
        mut,
        token::mint = mint,
        token::authority = creator,
        token::token_program = token_program
    )]
    pub creator_token: InterfaceAccount<'info, TokenAccount>,

    pub token_program: Interface<'info, TokenInterface>,
}

impl WithdrawStake<'_> {
    pub fn handle(&mut self) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        let pending = self.stake.pending_unstake;
        require!(pending > 0, ClipfiError::NothingToWithdraw);
        require!(now >= self.stake.unstake_at, ClipfiError::UnstakeNotReady);
        let amount = pending.min(self.stake.amount);

        let creator = self.creator.key();
        let seeds = &[STAKE_SEED, creator.as_ref(), &[self.stake.bump]];
        let signer_seeds = [&seeds[..]];
        let accounts = TransferChecked {
            from: self.stake_token.to_account_info(),
            mint: self.mint.to_account_info(),
            to: self.creator_token.to_account_info(),
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
        stake.pending_unstake = 0;
        stake.unstake_at = 0;

        emit!(StakeWithdrawn {
            creator,
            amount,
            bond: stake.bonded(),
        });
        Ok(())
    }
}

#[derive(Accounts)]
pub struct SetAutoRestake<'info> {
    pub creator: Signer<'info>,

    #[account(mut, has_one = creator, seeds = [STAKE_SEED, creator.key().as_ref()], bump = stake.bump)]
    pub stake: Account<'info, Stake>,
}

impl SetAutoRestake<'_> {
    pub fn handle(&mut self, bps: u16) -> Result<()> {
        require!(u128::from(bps) <= BPS_DENOMINATOR, ClipfiError::InvalidBps);
        self.stake.auto_restake_bps = bps;
        emit!(AutoRestakeSet {
            creator: self.creator.key(),
            auto_restake_bps: bps,
        });
        Ok(())
    }
}

#[derive(Accounts)]
pub struct FundBonusPool<'info> {
    pub funder: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump, has_one = mint, has_one = bonus_vault)]
    pub config: Account<'info, Config>,

    pub mint: InterfaceAccount<'info, Mint>,

    #[account(mut)]
    pub bonus_vault: InterfaceAccount<'info, TokenAccount>,

    #[account(
        mut,
        token::mint = mint,
        token::authority = funder,
        token::token_program = token_program
    )]
    pub funder_token: InterfaceAccount<'info, TokenAccount>,

    pub token_program: Interface<'info, TokenInterface>,
}

impl FundBonusPool<'_> {
    pub fn handle(&mut self, amount: u64) -> Result<()> {
        require!(amount > 0, ClipfiError::ZeroAmount);
        let accounts = TransferChecked {
            from: self.funder_token.to_account_info(),
            mint: self.mint.to_account_info(),
            to: self.bonus_vault.to_account_info(),
            authority: self.funder.to_account_info(),
        };
        transfer_checked(
            CpiContext::new(self.token_program.key(), accounts),
            amount,
            self.mint.decimals,
        )?;
        self.bonus_vault.reload()?;
        emit!(BonusPoolFunded {
            amount,
            pool_balance: self.bonus_vault.amount,
        });
        Ok(())
    }
}
