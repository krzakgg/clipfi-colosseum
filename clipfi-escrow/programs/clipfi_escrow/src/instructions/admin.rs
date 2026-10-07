use anchor_lang::prelude::*;

use crate::{
    events::{ConfigUpdated, PausedSet},
    Config, ConfigParams, CONFIG_SEED,
};

#[derive(Accounts)]
pub struct UpdateConfig<'info> {
    pub admin: Signer<'info>,

    #[account(mut, seeds = [CONFIG_SEED], bump = config.bump, has_one = admin)]
    pub config: Account<'info, Config>,
}

impl UpdateConfig<'_> {
    pub fn handle(&mut self, params: ConfigParams) -> Result<()> {
        params.validate()?;
        let config = &mut self.config;
        config.oracle = params.oracle;
        config.arbiter = params.arbiter;
        config.vesting_secs = params.vesting_secs;
        config.bonded_vesting_secs = params.bonded_vesting_secs;
        config.unstake_cooldown_secs = params.unstake_cooldown_secs;
        config.notice_secs = params.notice_secs;
        config.bonus_tiers = params.bonus_tiers;

        emit!(ConfigUpdated {
            oracle: params.oracle,
            arbiter: params.arbiter,
            vesting_secs: params.vesting_secs,
            bonded_vesting_secs: params.bonded_vesting_secs,
            unstake_cooldown_secs: params.unstake_cooldown_secs,
            notice_secs: params.notice_secs,
        });
        Ok(())
    }
}

#[derive(Accounts)]
pub struct SetPaused<'info> {
    pub admin: Signer<'info>,

    #[account(mut, seeds = [CONFIG_SEED], bump = config.bump, has_one = admin)]
    pub config: Account<'info, Config>,
}

impl SetPaused<'_> {
    pub fn handle(&mut self, paused: bool) -> Result<()> {
        self.config.paused = paused;
        emit!(PausedSet { paused });
        Ok(())
    }
}
