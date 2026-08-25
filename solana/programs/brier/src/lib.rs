//! Brier — confidence-calibrated slashing, Solana implementation.
//!
//! Port of the EVM reference implementation (tag `v0-evm`). The MECHANISM is
//! identical — slash by the Brier score over (reported confidence, adjudicated
//! outcome) — but every guarantee is re-established here from Solana-specific
//! tests, because the account model differs from EVM storage in ways that
//! change which checks are load-bearing.
//!
//! Trust model, unchanged from EVM and NOT improved by the port:
//!   * Only the calibration head is proved. The input logit is an unverified
//!     operator-supplied value; a fabricated logit still yields a valid proof.
//!   * Dispute resolution is an N-of-M committee: BOUNDED TRUST, not
//!     decentralisation. N colluding resolvers have the power a single admin
//!     had. The admin can replace the committee.
//! See solana/docs/PHASE3_TRUST_MODEL.md.

use anchor_lang::prelude::*;
use anchor_lang::solana_program::hash::hash;

pub mod brier_math;
pub mod errors;
pub mod state;

use errors::BrierError;
use state::*;

declare_id!("BrieR111111111111111111111111111111111111111");

#[program]
pub mod brier {
    use super::*;

    // =================================================================
    // Config
    // =================================================================

    pub fn initialize(
        ctx: Context<Initialize>,
        resolvers: Vec<Pubkey>,
        threshold: u8,
        max_slash_bps: u64,
        unbonding_period: i64,
    ) -> Result<()> {
        require!(
            unbonding_period >= MIN_UNBONDING_PERIOD,
            BrierError::UnbondingPeriodTooShort
        );
        require!(max_slash_bps <= BPS_DENOMINATOR, BrierError::CapOutOfRange);
        validate_committee(&resolvers, threshold)?;

        let cfg = &mut ctx.accounts.config;
        cfg.admin = ctx.accounts.admin.key();
        cfg.resolvers = resolvers;
        cfg.threshold = threshold;
        cfg.max_slash_bps = max_slash_bps;
        cfg.unbonding_period = unbonding_period;
        cfg.bump = ctx.bumps.config;
        Ok(())
    }

    /// Replace the resolver committee.
    ///
    /// NOTE, stated in code because it is load-bearing for the trust model:
    /// the admin retains this power, so bounded trust bounds the RESOLUTION
    /// step, not committee SELECTION. An admin can appoint a committee it
    /// controls. Asserted by `admin_can_replace_committee`.
    pub fn set_committee(
        ctx: Context<SetCommittee>,
        resolvers: Vec<Pubkey>,
        threshold: u8,
    ) -> Result<()> {
        validate_committee(&resolvers, threshold)?;
        let cfg = &mut ctx.accounts.config;
        cfg.resolvers = resolvers;
        cfg.threshold = threshold;
        Ok(())
    }

    // =================================================================
    // Attestation
    // =================================================================

    /// Record a decision together with its SP1 proof verification result.
    ///
    /// `proof_verified` is passed in by the caller in this build because SP1
    /// Groth16 verification via `sp1-solana` is a separate CPI whose CU cost is
    /// measured independently (see PHASE0_PROVING_STACK.md). Wiring that CPI is
    /// the remaining step; until it lands, this instruction records the flag
    /// rather than establishing it, and `attest_is_not_proof_of_verification`
    /// documents exactly that.
    pub fn attest(
        ctx: Context<Attest>,
        decision_hash: [u8; 32],
        shap_hash: [u8; 32],
        confidence: u128,
        margin: i64,
        model_version: [u8; 32],
        sp1_vkey_hash: [u8; 32],
        proof_verified: bool,
    ) -> Result<()> {
        require!(confidence <= WAD, BrierError::ConfidenceOutOfRange);

        let a = &mut ctx.accounts.attestation;
        a.operator = ctx.accounts.operator.key();
        a.decision_hash = decision_hash;
        a.shap_hash = shap_hash;
        a.confidence = confidence;
        a.margin = margin;
        a.model_version = model_version;
        a.sp1_vkey_hash = sp1_vkey_hash;
        a.proof_verified = proof_verified;
        a.timestamp = Clock::get()?.unix_timestamp;
        a.bump = ctx.bumps.attestation;
        Ok(())
    }

    // =================================================================
    // Staking + unbonding
    // =================================================================

    pub fn stake(ctx: Context<Stake>, amount: u64) -> Result<()> {
        require!(amount > 0, BrierError::ZeroStake);

        // Move lamports from the operator into the stake PDA.
        anchor_lang::system_program::transfer(
            CpiContext::new(
                ctx.accounts.system_program.to_account_info(),
                anchor_lang::system_program::Transfer {
                    from: ctx.accounts.operator.to_account_info(),
                    to: ctx.accounts.stake_account.to_account_info(),
                },
            ),
            amount,
        )?;

        let s = &mut ctx.accounts.stake_account;
        s.operator = ctx.accounts.operator.key();
        s.bonded = s.bonded.checked_add(amount).ok_or(BrierError::MathOverflow)?;
        s.bump = ctx.bumps.stake_account;
        Ok(())
    }

    /// Step 1 of 2. Starts the unbonding clock; the stake stays bonded and
    /// FULLY SLASHABLE. Earmarking must not reduce the slashable balance --
    /// that would reintroduce the exploit in a weaker form.
    pub fn request_withdrawal(ctx: Context<OperatorStake>, amount: u64) -> Result<()> {
        let cfg_period = ctx.accounts.config.unbonding_period;
        let s = &mut ctx.accounts.stake_account;

        require!(amount > 0 && amount <= s.bonded, BrierError::InsufficientStake);
        require!(s.pending_withdrawal == 0, BrierError::WithdrawalAlreadyPending);

        s.pending_withdrawal = amount;
        s.withdrawal_ready_at = Clock::get()?
            .unix_timestamp
            .checked_add(cfg_period)
            .ok_or(BrierError::MathOverflow)?;
        Ok(())
    }

    /// Step 2 of 2. Blocked while the clock is immature OR any dispute naming
    /// this operator is open. Both are re-checked here, not at request time.
    pub fn execute_withdrawal(ctx: Context<ExecuteWithdrawal>) -> Result<()> {
        let s = &mut ctx.accounts.stake_account;
        require!(s.pending_withdrawal > 0, BrierError::NoPendingWithdrawal);
        require!(
            Clock::get()?.unix_timestamp >= s.withdrawal_ready_at,
            BrierError::WithdrawalNotReady
        );
        require!(
            s.open_dispute_count == 0,
            BrierError::WithdrawalFrozenByOpenDispute
        );

        // A slash during unbonding can have left less than was requested.
        let amount = s.pending_withdrawal.min(s.bonded);
        s.pending_withdrawal = 0;
        s.withdrawal_ready_at = 0;
        s.bonded = s.bonded.checked_sub(amount).ok_or(BrierError::MathOverflow)?;

        // Direct lamport move: the stake PDA is program-owned, so a System
        // transfer CPI is not available and would fail. The rent-exempt
        // minimum is preserved because `bonded` never includes it.
        transfer_from_pda(
            &ctx.accounts.stake_account.to_account_info(),
            &ctx.accounts.operator.to_account_info(),
            amount,
        )?;
        Ok(())
    }

    pub fn cancel_withdrawal(ctx: Context<OperatorStake>) -> Result<()> {
        let s = &mut ctx.accounts.stake_account;
        require!(s.pending_withdrawal > 0, BrierError::NoPendingWithdrawal);
        s.pending_withdrawal = 0;
        s.withdrawal_ready_at = 0;
        Ok(())
    }

    // =================================================================
    // Disputes
    // =================================================================

    /// One dispute per attestation is enforced STRUCTURALLY: the Dispute PDA is
    /// derived from the attestation, so `init` fails if it already exists. The
    /// EVM version needed an explicit `disputed` mapping plus a check.
    pub fn open_dispute(ctx: Context<OpenDispute>) -> Result<()> {
        require_keys_eq!(
            ctx.accounts.attestation.operator,
            ctx.accounts.stake_account.operator,
            BrierError::OperatorMismatch
        );

        let d = &mut ctx.accounts.dispute;
        d.attestation = ctx.accounts.attestation.key();
        d.claimant = ctx.accounts.claimant.key();
        d.operator = ctx.accounts.attestation.operator;
        d.status = DisputeStatus::Open;
        d.votes_upheld = 0;
        d.votes_overturned = 0;
        d.slashed = 0;
        d.opened_at = Clock::get()?.unix_timestamp;
        d.bump = ctx.bumps.dispute;

        let s = &mut ctx.accounts.stake_account;
        s.open_dispute_count = s
            .open_dispute_count
            .checked_add(1)
            .ok_or(BrierError::MathOverflow)?;
        Ok(())
    }

    /// Cast one committee vote. The outcome lands only when a side reaches the
    /// threshold; below it the dispute stays Open, so the operator's withdrawal
    /// stays frozen meanwhile.
    pub fn vote_dispute(ctx: Context<VoteDispute>, upheld: bool) -> Result<()> {
        let cfg = &ctx.accounts.config;
        let resolver = ctx.accounts.resolver.key();
        require!(cfg.resolvers.contains(&resolver), BrierError::NotResolver);
        require!(
            ctx.accounts.dispute.status == DisputeStatus::Open,
            BrierError::DisputeNotOpen
        );

        // Double-voting is impossible: this PDA is `init`, so a second vote by
        // the same resolver fails at the runtime level.
        let v = &mut ctx.accounts.vote_record;
        v.dispute = ctx.accounts.dispute.key();
        v.resolver = resolver;
        v.upheld = upheld;
        v.bump = ctx.bumps.vote_record;

        let d = &mut ctx.accounts.dispute;
        if upheld {
            d.votes_upheld = d.votes_upheld.checked_add(1).ok_or(BrierError::MathOverflow)?;
        } else {
            d.votes_overturned = d
                .votes_overturned
                .checked_add(1)
                .ok_or(BrierError::MathOverflow)?;
        }

        let t = cfg.threshold;
        if d.votes_upheld < t && d.votes_overturned < t {
            return Ok(()); // below threshold on both sides
        }
        let decision_upheld = d.votes_upheld >= t;

        // --- resolve -------------------------------------------------
        let s = &mut ctx.accounts.stake_account;
        let slash = brier_math::slash_amount(
            s.bonded,
            ctx.accounts.attestation.confidence,
            decision_upheld,
            cfg.max_slash_bps,
        )?;

        s.bonded = s.bonded.checked_sub(slash).ok_or(BrierError::MathOverflow)?;
        s.open_dispute_count = s
            .open_dispute_count
            .checked_sub(1)
            .ok_or(BrierError::MathOverflow)?;

        d.slashed = slash;
        d.status = if decision_upheld {
            DisputeStatus::ResolvedUpheld
        } else {
            DisputeStatus::ResolvedOverturned
        };

        if slash > 0 {
            transfer_from_pda(
                &ctx.accounts.stake_account.to_account_info(),
                &ctx.accounts.claimant.to_account_info(),
                slash,
            )?;
        }
        Ok(())
    }
}

// =====================================================================
// helpers
// =====================================================================

fn validate_committee(resolvers: &[Pubkey], threshold: u8) -> Result<()> {
    require!(
        resolvers.len() <= MAX_COMMITTEE,
        BrierError::InvalidCommittee
    );
    // threshold < 2 would make "N-of-M" a single key again.
    require!(
        threshold >= 2 && (threshold as usize) <= resolvers.len(),
        BrierError::InvalidCommittee
    );
    for (i, r) in resolvers.iter().enumerate() {
        require!(*r != Pubkey::default(), BrierError::DuplicateResolver);
        for other in &resolvers[i + 1..] {
            require!(r != other, BrierError::DuplicateResolver);
        }
    }
    Ok(())
}

/// Move lamports out of a program-owned PDA.
///
/// A System `transfer` CPI cannot debit an account the System Program does not
/// own, so the lamport fields are adjusted directly. This has no EVM analogue
/// and is a place where a naive port silently fails.
fn transfer_from_pda(from: &AccountInfo, to: &AccountInfo, amount: u64) -> Result<()> {
    let mut from_lamports = from.try_borrow_mut_lamports()?;
    let mut to_lamports = to.try_borrow_mut_lamports()?;
    **from_lamports = from_lamports
        .checked_sub(amount)
        .ok_or(BrierError::MathOverflow)?;
    **to_lamports = to_lamports
        .checked_add(amount)
        .ok_or(BrierError::MathOverflow)?;
    Ok(())
}

/// Deterministic decision hash helper, exposed for clients.
pub fn decision_hash(application_id: &[u8], decision: &[u8], reason_code: &[u8]) -> [u8; 32] {
    let mut buf = Vec::new();
    buf.extend_from_slice(&(application_id.len() as u32).to_le_bytes());
    buf.extend_from_slice(application_id);
    buf.extend_from_slice(&(decision.len() as u32).to_le_bytes());
    buf.extend_from_slice(decision);
    buf.extend_from_slice(&(reason_code.len() as u32).to_le_bytes());
    buf.extend_from_slice(reason_code);
    hash(&buf).to_bytes()
}

// =====================================================================
// account contexts
//
// Every context below declares its signer and owner constraints explicitly.
// Missing signer / owner checks are the most common real-world Anchor
// vulnerability class, so `has_one`, `seeds`, and `Signer` are used rather than
// relying on convention. Phase 3 tests attack these directly.
// =====================================================================

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(mut)]
    pub admin: Signer<'info>,
    #[account(
        init,
        payer = admin,
        space = 8 + Config::INIT_SPACE,
        seeds = [b"config"],
        bump
    )]
    pub config: Account<'info, Config>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct SetCommittee<'info> {
    // `has_one = admin` ties the signer to the stored admin; without it any
    // signer could pass a config account and mutate it.
    #[account(mut, seeds = [b"config"], bump = config.bump, has_one = admin @ BrierError::NotAdmin)]
    pub config: Account<'info, Config>,
    pub admin: Signer<'info>,
}

#[derive(Accounts)]
#[instruction(decision_hash: [u8; 32])]
pub struct Attest<'info> {
    #[account(mut)]
    pub operator: Signer<'info>,
    #[account(
        init,
        payer = operator,
        space = 8 + Attestation::INIT_SPACE,
        seeds = [b"attestation", operator.key().as_ref(), decision_hash.as_ref()],
        bump
    )]
    pub attestation: Account<'info, Attestation>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Stake<'info> {
    #[account(mut)]
    pub operator: Signer<'info>,
    #[account(
        init_if_needed,
        payer = operator,
        space = 8 + StakeAccount::INIT_SPACE,
        seeds = [b"stake", operator.key().as_ref()],
        bump
    )]
    pub stake_account: Account<'info, StakeAccount>,
    pub system_program: Program<'info, System>,
}

/// Operator-only stake operations that do not move lamports.
#[derive(Accounts)]
pub struct OperatorStake<'info> {
    pub operator: Signer<'info>,
    #[account(seeds = [b"config"], bump = config.bump)]
    pub config: Account<'info, Config>,
    #[account(
        mut,
        seeds = [b"stake", operator.key().as_ref()],
        bump = stake_account.bump,
        has_one = operator @ BrierError::OperatorMismatch
    )]
    pub stake_account: Account<'info, StakeAccount>,
}

#[derive(Accounts)]
pub struct ExecuteWithdrawal<'info> {
    #[account(mut)]
    pub operator: Signer<'info>,
    #[account(
        mut,
        seeds = [b"stake", operator.key().as_ref()],
        bump = stake_account.bump,
        has_one = operator @ BrierError::OperatorMismatch
    )]
    pub stake_account: Account<'info, StakeAccount>,
}

#[derive(Accounts)]
pub struct OpenDispute<'info> {
    #[account(mut)]
    pub claimant: Signer<'info>,
    pub attestation: Account<'info, Attestation>,
    #[account(
        mut,
        seeds = [b"stake", attestation.operator.as_ref()],
        bump = stake_account.bump
    )]
    pub stake_account: Account<'info, StakeAccount>,
    #[account(
        init,
        payer = claimant,
        space = 8 + Dispute::INIT_SPACE,
        seeds = [b"dispute", attestation.key().as_ref()],
        bump
    )]
    pub dispute: Account<'info, Dispute>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct VoteDispute<'info> {
    #[account(mut)]
    pub resolver: Signer<'info>,
    #[account(seeds = [b"config"], bump = config.bump)]
    pub config: Account<'info, Config>,
    #[account(
        mut,
        seeds = [b"dispute", attestation.key().as_ref()],
        bump = dispute.bump,
        constraint = dispute.attestation == attestation.key() @ BrierError::PublicValuesMismatch
    )]
    pub dispute: Account<'info, Dispute>,
    pub attestation: Account<'info, Attestation>,
    #[account(
        mut,
        seeds = [b"stake", attestation.operator.as_ref()],
        bump = stake_account.bump
    )]
    pub stake_account: Account<'info, StakeAccount>,
    /// CHECK: paid the slash; identity is constrained to the dispute's recorded
    /// claimant so an attacker cannot redirect the payout.
    #[account(mut, address = dispute.claimant @ BrierError::OperatorMismatch)]
    pub claimant: AccountInfo<'info>,
    #[account(
        init,
        payer = resolver,
        space = 8 + VoteRecord::INIT_SPACE,
        seeds = [b"vote", dispute.key().as_ref(), resolver.key().as_ref()],
        bump
    )]
    pub vote_record: Account<'info, VoteRecord>,
    pub system_program: Program<'info, System>,
}
