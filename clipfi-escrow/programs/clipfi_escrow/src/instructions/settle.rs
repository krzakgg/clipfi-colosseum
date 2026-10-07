use anchor_lang::prelude::*;

use crate::{
    error::ClipfiError,
    events::{RatesApplied, Settled, StandardsApplied},
    Campaign, CampaignStatus, Config, CreatorPosition, Payout, PayoutStatus, Stake,
    ANCHOR_DISCRIMINATOR, CAMPAIGN_SEED, CONFIG_SEED, PAYOUT_SEED, POSITION_SEED, STAKE_SEED,
    UNITS_PER_RATE,
};

#[derive(Accounts)]
#[instruction(epoch: u64)]
pub struct Settle<'info> {
    #[account(mut)]
    pub oracle: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump, has_one = oracle)]
    pub config: Account<'info, Config>,

    #[account(
        mut,
        seeds = [CAMPAIGN_SEED, campaign.brand.as_ref(), campaign.campaign_id.to_le_bytes().as_ref()],
        bump = campaign.bump
    )]
    pub campaign: Box<Account<'info, Campaign>>,

    /// CHECK: only names whose position and payout these are
    pub creator: UncheckedAccount<'info>,

    /// CHECK: the stake PDA of the creator, read only when it exists
    #[account(seeds = [STAKE_SEED, creator.key().as_ref()], bump)]
    pub stake: UncheckedAccount<'info>,

    #[account(
        init_if_needed,
        payer = oracle,
        space = ANCHOR_DISCRIMINATOR + CreatorPosition::INIT_SPACE,
        seeds = [POSITION_SEED, campaign.key().as_ref(), creator.key().as_ref()],
        bump
    )]
    pub position: Box<Account<'info, CreatorPosition>>,

    #[account(
        init,
        payer = oracle,
        space = ANCHOR_DISCRIMINATOR + Payout::INIT_SPACE,
        seeds = [
            PAYOUT_SEED,
            campaign.key().as_ref(),
            creator.key().as_ref(),
            epoch.to_le_bytes().as_ref()
        ],
        bump
    )]
    pub payout: Box<Account<'info, Payout>>,

    pub system_program: Program<'info, System>,
}

pub fn read_stake(stake: &AccountInfo) -> Result<Option<Stake>> {
    if stake.owner != &crate::ID || stake.data_is_empty() {
        return Ok(None);
    }
    let data = stake.try_borrow_data()?;
    Ok(Some(Stake::try_deserialize(&mut &data[..])?))
}

impl Settle<'_> {
    pub fn handle(
        &mut self,
        epoch: u64,
        units: [u64; 4],
        evidence_hash: [u8; 32],
        bumps: &SettleBumps,
    ) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        require!(!self.config.paused, ClipfiError::Paused);
        let campaign = &mut self.campaign;
        let position = &mut self.position;

        require!(
            campaign.status == CampaignStatus::Active,
            ClipfiError::CampaignClosed
        );
        require!(now >= campaign.start_ts, ClipfiError::NotStarted);
        require!(
            epoch > position.last_epoch,
            ClipfiError::EpochAlreadySettled
        );

        if campaign.pending_rates_at != 0 && now >= campaign.pending_rates_at {
            campaign.rate_per_mille = campaign.pending_rates;
            campaign.pending_rates = [0; 4];
            campaign.pending_rates_at = 0;
            emit!(RatesApplied {
                campaign: campaign.key(),
                rates: campaign.rate_per_mille,
            });
        }
        if campaign.pending_standards_at != 0 && now >= campaign.pending_standards_at {
            campaign.standards_hash = campaign.pending_standards_hash;
            campaign.standards_version = campaign
                .standards_version
                .checked_add(1)
                .ok_or(ClipfiError::Overflow)?;
            campaign.pending_standards_hash = [0; 32];
            campaign.pending_standards_at = 0;
            emit!(StandardsApplied {
                campaign: campaign.key(),
                standards_hash: campaign.standards_hash,
                standards_version: campaign.standards_version,
            });
        }

        let stake = read_stake(&self.stake.to_account_info())?;
        let bond = stake.as_ref().map(Stake::bonded).unwrap_or(0);
        let restake_bps = stake
            .as_ref()
            .map(|stake| stake.auto_restake_bps)
            .unwrap_or(0);
        require!(bond >= campaign.min_bond, ClipfiError::BondTooLow);
        let bonus_bps = self.config.bonus_bps_for(bond);

        let mut gross: u128 = 0;
        for (count, rate) in units.iter().zip(campaign.rate_per_mille) {
            let part = u128::from(*count)
                .checked_mul(u128::from(rate))
                .ok_or(ClipfiError::Overflow)?;
            gross = gross.checked_add(part).ok_or(ClipfiError::Overflow)?;
        }
        let gross = gross / UNITS_PER_RATE;

        let creator_room = campaign
            .max_per_creator
            .checked_sub(position.earned_total)
            .ok_or(ClipfiError::Underflow)?;
        let free = campaign.free_budget().ok_or(ClipfiError::Underflow)?;
        let amount = gross.min(u128::from(creator_room)).min(u128::from(free)) as u64;
        require!(amount > 0, ClipfiError::NothingToSettle);

        let unlock_ts = if bond > 0 {
            now.checked_add(self.config.bonded_vesting_secs)
                .ok_or(ClipfiError::Overflow)?
        } else {
            now.checked_add(self.config.vesting_secs)
                .ok_or(ClipfiError::Overflow)?
                .max(campaign.end_ts)
        };

        campaign.reserved = campaign
            .reserved
            .checked_add(amount)
            .ok_or(ClipfiError::Overflow)?;

        position.campaign = campaign.key();
        position.creator = self.creator.key();
        position.bump = bumps.position;
        position.last_epoch = epoch;
        position.earned_total = position
            .earned_total
            .checked_add(amount)
            .ok_or(ClipfiError::Overflow)?;
        for (total, count) in position.units_total.iter_mut().zip(units) {
            *total = total.checked_add(count).ok_or(ClipfiError::Overflow)?;
        }

        self.payout.set_inner(Payout {
            campaign: campaign.key(),
            creator: self.creator.key(),
            epoch,
            units,
            amount,
            bonus_bps,
            restake_bps,
            standards_version: campaign.standards_version,
            evidence_hash,
            unlock_ts,
            status: PayoutStatus::Pending,
            rent_payer: self.oracle.key(),
            bump: bumps.payout,
        });

        emit!(Settled {
            campaign: campaign.key(),
            creator: self.creator.key(),
            epoch,
            units,
            amount,
            unlock_ts,
            evidence_hash,
        });
        Ok(())
    }
}
