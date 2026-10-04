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

    pub fn init_config(
        ctx: Context<InitConfig>,
        oracle: Pubkey,
        arbiter: Pubkey,
        vesting_secs: i64,
    ) -> Result<()> {
        ctx.accounts
            .handle(oracle, arbiter, vesting_secs, &ctx.bumps)
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

    pub fn release(ctx: Context<Release>) -> Result<()> {
        ctx.accounts.handle()
    }

    pub fn close_campaign(ctx: Context<CloseCampaign>) -> Result<()> {
        ctx.accounts.handle()
    }
}
