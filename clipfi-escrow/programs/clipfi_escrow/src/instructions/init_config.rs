use anchor_lang::prelude::*;
use anchor_spl::associated_token::AssociatedToken;
use anchor_spl::token_2022::spl_token_2022::extension::{
    transfer_fee::TransferFeeConfig, BaseStateWithExtensions, StateWithExtensions,
};
use anchor_spl::token_2022::spl_token_2022::state::Mint as MintState;
use anchor_spl::token_interface::{Mint, TokenAccount, TokenInterface};

use crate::{
    error::ClipfiError, BonusTier, Config, ANCHOR_DISCRIMINATOR, BONUS_TIERS, CONFIG_SEED,
    MAX_BONUS_BPS, MAX_VESTING_SECS,
};

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct ConfigParams {
    pub oracle: Pubkey,
    pub arbiter: Pubkey,
    pub vesting_secs: i64,
    pub bonded_vesting_secs: i64,
    pub unstake_cooldown_secs: i64,
    pub notice_secs: i64,
    pub bonus_tiers: [BonusTier; BONUS_TIERS],
}

impl ConfigParams {
    pub fn validate(&self) -> Result<()> {
        require!(
            self.vesting_secs > 0 && self.vesting_secs <= MAX_VESTING_SECS,
            ClipfiError::InvalidVesting
        );
        require!(
            self.bonded_vesting_secs > 0 && self.bonded_vesting_secs <= self.vesting_secs,
            ClipfiError::InvalidVesting
        );
        require!(
            self.unstake_cooldown_secs >= self.vesting_secs
                && self.unstake_cooldown_secs <= MAX_VESTING_SECS,
            ClipfiError::InvalidVesting
        );
        require!(self.notice_secs > 0, ClipfiError::InvalidVesting);
        let mut last_bond = 0u64;
        for tier in self.bonus_tiers.iter().filter(|tier| tier.min_bond > 0) {
            require!(tier.min_bond > last_bond, ClipfiError::InvalidTiers);
            require!(tier.bonus_bps <= MAX_BONUS_BPS, ClipfiError::InvalidBps);
            last_bond = tier.min_bond;
        }
        Ok(())
    }
}

#[derive(Accounts)]
pub struct InitConfig<'info> {
    #[account(mut)]
    pub admin: Signer<'info>,

    #[account(mint::token_program = token_program)]
    pub mint: InterfaceAccount<'info, Mint>,

    #[account(
        init,
        payer = admin,
        space = ANCHOR_DISCRIMINATOR + Config::INIT_SPACE,
        seeds = [CONFIG_SEED],
        bump
    )]
    pub config: Account<'info, Config>,

    #[account(
        init,
        payer = admin,
        associated_token::mint = mint,
        associated_token::authority = config,
        associated_token::token_program = token_program
    )]
    pub bonus_vault: InterfaceAccount<'info, TokenAccount>,

    // only whoever can upgrade the program may bootstrap its config, which closes
    // the race where anyone front-runs the first init between deploy and setup
    #[account(
        constraint = program.programdata_address()? == Some(program_data.key()) @ ClipfiError::Unauthorized
    )]
    pub program: Program<'info, crate::program::ClipfiEscrow>,

    #[account(
        constraint = program_data.upgrade_authority_address == Some(admin.key()) @ ClipfiError::Unauthorized
    )]
    pub program_data: Account<'info, ProgramData>,

    pub associated_token_program: Program<'info, AssociatedToken>,
    pub token_program: Interface<'info, TokenInterface>,
    pub system_program: Program<'info, System>,
}

impl InitConfig<'_> {
    pub fn handle(&mut self, params: ConfigParams, bumps: &InitConfigBumps) -> Result<()> {
        params.validate()?;
        // a transfer-fee mint makes the vault receive less than fund_campaign records,
        // which would strand the last payout; refuse it instead of booking a lie
        require!(
            !mint_has_transfer_fee(&self.mint)?,
            ClipfiError::UnsupportedMint
        );
        self.config.set_inner(Config {
            admin: self.admin.key(),
            oracle: params.oracle,
            arbiter: params.arbiter,
            mint: self.mint.key(),
            bonus_vault: self.bonus_vault.key(),
            vesting_secs: params.vesting_secs,
            bonded_vesting_secs: params.bonded_vesting_secs,
            unstake_cooldown_secs: params.unstake_cooldown_secs,
            notice_secs: params.notice_secs,
            bonus_tiers: params.bonus_tiers,
            paused: false,
            bump: bumps.config,
        });
        Ok(())
    }
}

fn mint_has_transfer_fee(mint: &InterfaceAccount<Mint>) -> Result<bool> {
    let info = mint.to_account_info();
    let data = info.try_borrow_data()?;
    let state = StateWithExtensions::<MintState>::unpack(&data)
        .map_err(|_| error!(ClipfiError::UnsupportedMint))?;
    Ok(state.get_extension::<TransferFeeConfig>().is_ok())
}
