//! SP1 guest program: the Brier calibration head.
//!
//! This is the Solana-side replacement for the EVM build's EZKL/Halo2 circuit.
//! The *mechanism* is identical — map a base-model logit to a calibrated
//! confidence — but the execution model is not:
//!
//!   EVM:    ONNX graph -> EZKL -> Halo2 arithmetic circuit -> KZG proof
//!   Solana: Rust program -> SP1 zkVM (RISC-V) -> STARK -> Groth16 wrap
//!
//! Consequences that matter for correctness, not just performance:
//!
//! 1. **Fixed-point, not float.** A zkVM executes real RISC-V, so `f32` would
//!    technically run — but floating point makes the proof's meaning
//!    host-dependent and the on-chain comparison unreliable. All arithmetic
//!    here is i64 fixed-point with an explicit scale, matching the WAD
//!    convention already used by the EVM `BrierMath` contract.
//!
//! 2. **The quantisation error is a different number.** EZKL's fixed-point
//!    scale (input/param scale 13) produced a documented ~4.2e-4 deviation from
//!    the float head. This program's error is governed by SCALE below and is a
//!    separate quantity. It is NOT inherited from the EVM measurement.
//!
//! 3. **Public values are the trust boundary.** Whatever is committed here is
//!    what the on-chain program can constrain. The margin is committed as a
//!    public input for exactly the same reason as on EVM — and, exactly as on
//!    EVM, committing it does NOT prove where it came from. The input-logit
//!    provenance gap ports over unchanged. See docs/PHASE3_TRUST_MODEL.md.
#![no_main]
sp1_zkvm::entrypoint!(main);

/// Fixed-point scale: values are stored as `value * SCALE`.
///
/// 1e6 keeps six decimal places, which is far finer than the decision needs
/// (a Brier slash is quadratic in a confidence that is itself uncertain at the
/// ~1e-2 level), while leaving ample headroom in i64 against overflow:
/// the largest intermediate is `logit_fp * SCALE` ~= 2e7 * 1e6 = 2e13 << i64::MAX.
pub const SCALE: i64 = 1_000_000;

/// Maximum absolute logit accepted, in fixed point (±64.0).
///
/// Base-model margins observed in the EVM build span roughly [-12.6, +7.5].
/// A bound two orders of magnitude wider than that is generous for real inputs
/// while making every downstream multiplication provably overflow-free.
/// Rejecting out-of-range input inside the guest means a proof cannot exist for
/// a nonsensical logit — a cheap constraint the EVM circuit did not have.
pub const MAX_ABS_LOGIT: i64 = 64 * SCALE;

/// Calibration head variants.
///
/// Both are proved by the same guest; which one ran is committed in the public
/// values so a verifier can tell them apart. This mirrors the EVM build, where
/// the verifying key distinguished the temperature head from the MLP head.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum HeadKind {
    /// `logit / T` — the 1-parameter head. `T` is fixed point.
    Temperature = 0,
    /// A 1 -> h -> h -> 1 ReLU MLP over fixed-point weights.
    Mlp = 1,
}

/// Saturating fixed-point multiply: (a * b) / SCALE.
#[inline]
fn fp_mul(a: i64, b: i64) -> i64 {
    // i128 intermediate: a,b are bounded by construction, but the guest must
    // not rely on that for memory safety.
    (((a as i128) * (b as i128)) / (SCALE as i128)) as i64
}

/// Saturating fixed-point divide: (a * SCALE) / b.
#[inline]
fn fp_div(a: i64, b: i64) -> i64 {
    assert!(b != 0, "division by zero temperature");
    (((a as i128) * (SCALE as i128)) / (b as i128)) as i64
}

/// Temperature scaling: `logit / T`, in fixed point.
pub fn temperature_head(logit_fp: i64, t_fp: i64) -> i64 {
    assert!(t_fp > 0, "temperature must be positive");
    fp_div(logit_fp, t_fp)
}

/// Two-layer ReLU MLP head over fixed-point weights.
///
/// Layout matches the EVM/PyTorch head: input normalisation folded in, then
/// Linear(1,h) -> ReLU -> Linear(h,h) -> ReLU -> Linear(h,1). The sigmoid is
/// deliberately NOT applied here: like the EVM version, the head emits a LOGIT
/// and the sigmoid is applied off-proof. Keeping a transcendental out of the
/// proved region is the same design choice, made for the same reason.
pub fn mlp_head(
    logit_fp: i64,
    in_mean_fp: i64,
    in_std_fp: i64,
    w1: &[i64],
    b1: &[i64],
    w2: &[i64],
    b2: &[i64],
    w3: &[i64],
    b3: i64,
) -> i64 {
    let h = b1.len();
    assert_eq!(w1.len(), h, "w1 shape");
    assert_eq!(b2.len(), h, "b2 shape");
    assert_eq!(w2.len(), h * h, "w2 shape");
    assert_eq!(w3.len(), h, "w3 shape");
    assert!(in_std_fp > 0, "input std must be positive");

    // Input standardisation, folded into the graph exactly as on EVM.
    let x = fp_div(logit_fp - in_mean_fp, in_std_fp);

    // Layer 1: (1 -> h), ReLU
    let mut a1 = vec![0i64; h];
    for i in 0..h {
        let v = fp_mul(w1[i], x) + b1[i];
        a1[i] = if v > 0 { v } else { 0 };
    }

    // Layer 2: (h -> h), ReLU
    let mut a2 = vec![0i64; h];
    for i in 0..h {
        let mut acc = b2[i];
        for j in 0..h {
            acc += fp_mul(w2[i * h + j], a1[j]);
        }
        a2[i] = if acc > 0 { acc } else { 0 };
    }

    // Layer 3: (h -> 1), linear
    let mut out = b3;
    for i in 0..h {
        out += fp_mul(w3[i], a2[i]);
    }
    out
}

pub fn main() {
    // ---- private/committed inputs -------------------------------------
    // The margin is read as a normal input and then COMMITTED, making it a
    // public value. Committing binds the proof to this specific margin; it
    // does not establish that the margin came from any particular model.
    let logit_fp = sp1_zkvm::io::read::<i64>();
    let head_kind = sp1_zkvm::io::read::<u8>();
    let model_version = sp1_zkvm::io::read::<[u8; 32]>();

    assert!(
        logit_fp.abs() <= MAX_ABS_LOGIT,
        "logit out of supported range"
    );

    let calibrated_fp = match head_kind {
        0 => {
            let t_fp = sp1_zkvm::io::read::<i64>();
            temperature_head(logit_fp, t_fp)
        }
        1 => {
            let in_mean_fp = sp1_zkvm::io::read::<i64>();
            let in_std_fp = sp1_zkvm::io::read::<i64>();
            let w1 = sp1_zkvm::io::read::<Vec<i64>>();
            let b1 = sp1_zkvm::io::read::<Vec<i64>>();
            let w2 = sp1_zkvm::io::read::<Vec<i64>>();
            let b2 = sp1_zkvm::io::read::<Vec<i64>>();
            let w3 = sp1_zkvm::io::read::<Vec<i64>>();
            let b3 = sp1_zkvm::io::read::<i64>();
            mlp_head(
                logit_fp, in_mean_fp, in_std_fp, &w1, &b1, &w2, &b2, &w3, b3,
            )
        }
        _ => panic!("unknown head kind"),
    };

    // ---- public values -------------------------------------------------
    // Committed in a fixed order. The on-chain program deserialises exactly
    // this layout; see solana/programs/attestation.
    //
    // `model_version` is committed so that a proof produced under one set of
    // head weights cannot be replayed as evidence for another. On EVM this was
    // implicit in the verifying key; in a zkVM the SAME vkey covers every input
    // to the same program, so the version must be committed explicitly. This is
    // a genuine architectural difference, not a stylistic one.
    sp1_zkvm::io::commit(&logit_fp);
    sp1_zkvm::io::commit(&calibrated_fp);
    sp1_zkvm::io::commit(&head_kind);
    sp1_zkvm::io::commit(&model_version);
}
