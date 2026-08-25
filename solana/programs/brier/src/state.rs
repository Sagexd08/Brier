//! On-chain state. See solana/docs/PHASE1_ACCOUNT_MODEL.md for why the layout
//! is not a transliteration of the EVM storage model.

use anchor_lang::prelude::*;

/// 1.0 in fixed point, matching the EVM `BrierMath` WAD convention so the
/// slash formula is literally the same arithmetic on both chains.
pub const WAD: u128 = 1_000_000_000_000_000_000;

/// Basis-point denominator for the slash cap.
pub const BPS_DENOMINATOR: u64 = 10_000;

/// Floor on the unbonding period, mirroring the EVM contract's constant. A
/// zero-length period would reintroduce the withdraw-front-running exploit
/// that EVM Phase 3a closed, so it is rejected at initialisation.
pub const MIN_UNBONDING_PERIOD: i64 = 3_600; // 1 hour, in seconds

/// Upper bound on committee size, so the vote-counting loop is bounded and
/// cannot be used to exhaust compute units.
pub const MAX_COMMITTEE: usize = 16;

#[account]
#[derive(InitSpace)]
pub struct Config {
    pub admin: Pubkey,
    /// Fixed resolver committee. NOT decentralised: an admin-set list.
    /// See docs/PHASE3B_TRUST_MODEL.md (shared with the EVM build).
    #[max_len(MAX_COMMITTEE)]
    pub resolvers: Vec<Pubkey>,
    /// Votes required to resolve a dispute. Enforced >= 2 and <= resolvers.len().
    pub threshold: u8,
    /// Cap on any single slash, in basis points of the operator's stake.
    pub max_slash_bps: u64,
    /// Seconds between requesting a withdrawal and being able to execute it.
    pub unbonding_period: i64,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct Attestation {
    pub operator: Pubkey,
    /// Hash of (application id, decision, reason code).
    pub decision_hash: [u8; 32],
    /// Hash of the top-5 SHAP vector. Evidence only — NOT proved.
    pub shap_hash: [u8; 32],
    /// Calibrated probability that the decision was correct, WAD-scaled.
    pub confidence: u128,
    /// The base-model logit fed to the calibration head, fixed point.
    ///
    /// UNVERIFIED INPUT. Committing it binds the proof to this value; it does
    /// not establish where the value came from. The EVM build's input-logit
    /// provenance gap ports over unchanged — see PHASE3_TRUST_MODEL.md.
    pub margin: i64,
    /// Identifies base model + calibration head.
    pub model_version: [u8; 32],
    /// SP1 verification key hash for the proved program.
    ///
    /// Unlike the EVM build, where the verifying key bound one specific head,
    /// a zkVM vkey covers EVERY input to the same program. The model version is
    /// therefore committed separately in the proof's public values.
    pub sp1_vkey_hash: [u8; 32],
    /// Did on-chain verification of the SP1 Groth16 proof succeed?
    pub proof_verified: bool,
    pub timestamp: i64,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct StakeAccount {
    pub operator: Pubkey,
    /// Bonded lamports, tracked explicitly.
    ///
    /// Deliberately NOT inferred from `lamports()`, which also contains the
    /// rent-exempt minimum. Conflating the two would let an operator "withdraw"
    /// rent and de-rent the account, or make the slash arithmetic depend on the
    /// rent schedule. This hazard has no EVM equivalent.
    pub bonded: u64,
    /// Amount earmarked by a pending withdrawal request. Still fully slashable.
    pub pending_withdrawal: u64,
    /// Unix timestamp at which a pending withdrawal may execute. 0 = none.
    pub withdrawal_ready_at: i64,
    /// Open disputes naming this operator. Non-zero freezes withdrawal.
    pub open_dispute_count: u32,
    pub bump: u8,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace, Debug)]
pub enum DisputeStatus {
    Open,
    ResolvedUpheld,
    ResolvedOverturned,
}

#[account]
#[derive(InitSpace)]
pub struct Dispute {
    pub attestation: Pubkey,
    pub claimant: Pubkey,
    pub operator: Pubkey,
    pub status: DisputeStatus,
    pub votes_upheld: u8,
    pub votes_overturned: u8,
    pub slashed: u64,
    pub opened_at: i64,
    pub bump: u8,
}

/// The existence of this PDA IS the "resolver has voted" flag.
///
/// A bitmap on the Dispute account would work too, but a per-voter PDA cannot
/// desynchronise from the vote counts and makes double-voting impossible at the
/// runtime level (`init` fails if the account exists) rather than by an
/// explicit check that could be forgotten.
#[account]
#[derive(InitSpace)]
pub struct VoteRecord {
    pub dispute: Pubkey,
    pub resolver: Pubkey,
    pub upheld: bool,
    pub bump: u8,
}
