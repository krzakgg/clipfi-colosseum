use anchor_lang::prelude::*;
use anchor_spl::token_2022::spl_token_2022::extension::{
    transfer_fee::TransferFeeConfig, BaseStateWithExtensions, StateWithExtensions,
};
use anchor_spl::token_2022::spl_token_2022::state::Mint as MintState;
use anchor_spl::token_interface::Mint;

use crate::{error::ClipfiError, Config, ANCHOR_DISCRIMINATOR, CONFIG_SEED, MAX_VESTING_SECS};

#[derive(Accounts)]
pub struct InitConfig<'info> {
    #[account(mut)]
    pub admin: Signer<'info>,

    pub mint: InterfaceAccount<'info, Mint>,

    #[account(
        init,
        payer = admin,
        space = ANCHOR_DISCRIMINATOR + Config::INIT_SPACE,
        seeds = [CONFIG_SEED],
        bump
    )]
    pub config: Account<'info, Config>,

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

    pub system_program: Program<'info, System>,
}

impl InitConfig<'_> {
    pub fn handle(
        &mut self,
        oracle: Pubkey,
        arbiter: Pubkey,
        vesting_secs: i64,
        bumps: &InitConfigBumps,
    ) -> Result<()> {
        require!(
            vesting_secs > 0 && vesting_secs <= MAX_VESTING_SECS,
            ClipfiError::InvalidVesting
        );
        // a transfer-fee mint makes the vault receive less than fund_campaign records,
        // which would strand the last payout; refuse it instead of booking a lie
        require!(
            !mint_has_transfer_fee(&self.mint)?,
            ClipfiError::UnsupportedMint
        );
        self.config.set_inner(Config {
            admin: self.admin.key(),
            oracle,
            arbiter,
            mint: self.mint.key(),
            vesting_secs,
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
