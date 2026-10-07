use anchor_lang::prelude::*;

#[error_code]
pub enum ClipfiError {
    #[msg("vesting must be between 1 second and 21 days")]
    InvalidVesting,
    #[msg("campaign must end after it starts and after now")]
    InvalidWindow,
    #[msg("at least one rate must be above zero")]
    InvalidRates,
    #[msg("limit per creator must be above zero")]
    InvalidLimit,
    #[msg("amount must be above zero")]
    ZeroAmount,
    #[msg("campaign is closed")]
    CampaignClosed,
    #[msg("arithmetic overflow")]
    Overflow,
    #[msg("arithmetic underflow")]
    Underflow,
    #[msg("campaign has not started yet")]
    NotStarted,
    #[msg("this epoch or a later one is already settled for the creator")]
    EpochAlreadySettled,
    #[msg("nothing to pay: no units, creator limit reached or budget used up")]
    NothingToSettle,
    #[msg("payout is not pending")]
    PayoutNotPending,
    #[msg("payout can only be flagged before it unlocks")]
    FlagWindowClosed,
    #[msg("payout is not flagged")]
    PayoutNotFlagged,
    #[msg("payout is flagged and waits for the arbiter")]
    PayoutFrozen,
    #[msg("payout is still vesting")]
    StillVesting,
    #[msg("campaign can be closed only after its end plus the vesting period")]
    CampaignStillRunning,
    #[msg("campaign still has payouts that are not released or cancelled")]
    PayoutsOutstanding,
    #[msg("mint is not supported: transfer-fee extension would desync the vault from the ledger")]
    UnsupportedMint,
    #[msg("only the program upgrade authority may initialize the config")]
    Unauthorized,
    #[msg("bonus or restake share must not exceed the allowed basis points")]
    InvalidBps,
    #[msg("bonus tiers must have increasing minimum bonds")]
    InvalidTiers,
    #[msg("creator bond is below the campaign minimum")]
    BondTooLow,
    #[msg("bond is smaller than the requested amount")]
    InsufficientStake,
    #[msg("unstake cooldown has not passed")]
    UnstakeNotReady,
    #[msg("nothing is pending withdrawal")]
    NothingToWithdraw,
    #[msg("rates have no pending change")]
    NothingPending,
    #[msg("rollover target must be an active campaign of the same brand with the same mint")]
    InvalidRolloverTarget,
    #[msg("program is paused")]
    Paused,
    #[msg("this payout auto-restakes, pass the stake accounts")]
    StakeRequired,
}
