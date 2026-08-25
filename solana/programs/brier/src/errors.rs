use anchor_lang::prelude::*;

#[error_code]
pub enum BrierError {
    #[msg("confidence must be <= 1.0 (WAD)")]
    ConfidenceOutOfRange,
    #[msg("slash cap must be <= 10000 bps")]
    CapOutOfRange,
    #[msg("arithmetic overflow")]
    MathOverflow,
    #[msg("unbonding period is below the minimum")]
    UnbondingPeriodTooShort,
    #[msg("committee size or threshold is invalid (need 2 <= threshold <= size)")]
    InvalidCommittee,
    #[msg("duplicate resolver in committee")]
    DuplicateResolver,
    #[msg("signer is not a member of the resolver committee")]
    NotResolver,
    #[msg("signer is not the admin")]
    NotAdmin,
    #[msg("stake amount must be non-zero")]
    ZeroStake,
    #[msg("requested amount exceeds bonded stake")]
    InsufficientStake,
    #[msg("a withdrawal request is already pending")]
    WithdrawalAlreadyPending,
    #[msg("no pending withdrawal")]
    NoPendingWithdrawal,
    #[msg("unbonding period has not elapsed")]
    WithdrawalNotReady,
    #[msg("withdrawal frozen: an open dispute names this operator")]
    WithdrawalFrozenByOpenDispute,
    #[msg("dispute is not open")]
    DisputeNotOpen,
    #[msg("attestation does not belong to the referenced operator")]
    OperatorMismatch,
    #[msg("SP1 proof verification failed")]
    ProofVerificationFailed,
    #[msg("public values do not match the attested decision")]
    PublicValuesMismatch,
}
