pub mod constants;
pub mod error;
pub mod events;
pub mod instructions;
pub mod state;

use anchor_lang::prelude::*;

pub use constants::*;
pub use events::*;
pub use instructions::*;
pub use state::*;

declare_id!("GAXMVFUXzAPBwhW4cF127HiSZmiY791XX2mBFEqqBwx");

#[program]
pub mod clipfi_escrow {
    use super::*;

    pub fn init_config(ctx: Context<InitConfig>, params: ConfigParams) -> Result<()> {
        ctx.accounts.handle(params, &ctx.bumps)
    }

    pub fn create_campaign(
        ctx: Context<CreateCampaign>,
        campaign_id: u64,
        params: CampaignParams,
    ) -> Result<()> {
        ctx.accounts.handle(campaign_id, params, &ctx.bumps)
    }

    pub fn fund_campaign(ctx: Context<FundCampaign>, amount: u64) -> Result<()> {
        ctx.accounts.handle(amount)
    }

    pub fn propose_rates(ctx: Context<ProposeRates>, rates: [u64; 4]) -> Result<()> {
        ctx.accounts.handle(rates)
    }

    pub fn propose_standards(
        ctx: Context<ProposeStandards>,
        standards_hash: [u8; 32],
    ) -> Result<()> {
        ctx.accounts.handle(standards_hash)
    }

    pub fn settle(
        ctx: Context<Settle>,
        epoch: u64,
        units: [u64; 4],
        evidence_hash: [u8; 32],
    ) -> Result<()> {
        ctx.accounts.handle(epoch, units, evidence_hash, &ctx.bumps)
    }

    pub fn flag_payout(ctx: Context<FlagPayout>, reason: u16) -> Result<()> {
        ctx.accounts.handle(reason)
    }

    pub fn resolve(ctx: Context<Resolve>, approve: bool) -> Result<()> {
        ctx.accounts.handle(approve)
    }

    pub fn slash(ctx: Context<Slash>, amount: u64) -> Result<()> {
        ctx.accounts.handle(amount)
    }

    pub fn release(ctx: Context<Release>) -> Result<()> {
        ctx.accounts.handle()
    }

    pub fn close_campaign(ctx: Context<CloseCampaign>) -> Result<()> {
        ctx.accounts.handle()
    }

    pub fn rollover(ctx: Context<Rollover>) -> Result<()> {
        ctx.accounts.handle()
    }

    pub fn stake(ctx: Context<StakeTokens>, amount: u64) -> Result<()> {
        ctx.accounts.handle(amount, &ctx.bumps)
    }

    pub fn request_unstake(ctx: Context<RequestUnstake>, amount: u64) -> Result<()> {
        ctx.accounts.handle(amount)
    }

    pub fn withdraw_stake(ctx: Context<WithdrawStake>) -> Result<()> {
        ctx.accounts.handle()
    }

    pub fn set_auto_restake(ctx: Context<SetAutoRestake>, bps: u16) -> Result<()> {
        ctx.accounts.handle(bps)
    }

    pub fn fund_bonus_pool(ctx: Context<FundBonusPool>, amount: u64) -> Result<()> {
        ctx.accounts.handle(amount)
    }

    pub fn update_config(ctx: Context<UpdateConfig>, params: ConfigParams) -> Result<()> {
        ctx.accounts.handle(params)
    }

    pub fn set_paused(ctx: Context<SetPaused>, paused: bool) -> Result<()> {
        ctx.accounts.handle(paused)
    }
}
