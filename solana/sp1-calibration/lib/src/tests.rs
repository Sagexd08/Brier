//! Tests for the fixed-point calibration head.
//!
//! The important ones are the cross-implementation checks: this Rust code must
//! agree with the PyTorch head that the EVM build actually trained and proved.
//! Two implementations of "the same" function that were never compared is a
//! standard source of silent divergence, and the whole point of the port is
//! that the mechanism is the same on both chains.

use super::*;

/// Trained temperature from the EVM build (artifacts/calibration/temperature_head.pt).
/// Cross-check fixture: solana/sp1-calibration/lib/crosscheck.json.
const T_TRAINED: f64 = 3.01210355758667;

fn to_fp(x: f64) -> i64 {
    (x * SCALE as f64).round() as i64
}

fn from_fp(x: i64) -> f64 {
    x as f64 / SCALE as f64
}

// ---------------------------------------------------------------------
// Cross-implementation: Rust fixed point vs the trained PyTorch head
// ---------------------------------------------------------------------

/// Margins and expected outputs taken from the trained EVM head. If the fixed
/// point implementation drifts from the float one, this fails.
#[test]
fn matches_pytorch_head_on_real_margins() {
    // (margin, expected float-head output) — first five rows of the EVM test split.
    let cases = [
        (-7.908789_f64, -2.625670_f64),
        (-0.835007, -0.277217),
        (2.425111, 0.805122),
        (-6.820258, -2.264284),
        (-6.484130, -2.152692),
    ];
    let t_fp = to_fp(T_TRAINED);

    for (margin, expected) in cases {
        let got = from_fp(temperature_head(to_fp(margin), t_fp));
        let err = (got - expected).abs();
        assert!(
            err < 1e-5,
            "margin {margin}: fixed point {got} vs float {expected} (err {err:e})"
        );
    }
}

/// Quantisation error is bounded, and the bound is a property of THIS
/// implementation — not the ~4.2e-4 figure EZKL reported for the Halo2 circuit.
/// That number belongs to a different proving system and does not transfer.
#[test]
fn quantisation_error_is_bounded_and_measured_here() {
    let t_fp = to_fp(T_TRAINED);
    let mut worst = 0.0_f64;

    // Sweep the observed margin range at fine resolution.
    let mut m = -13.0_f64;
    while m <= 8.0 {
        let exact = m / T_TRAINED;
        let got = from_fp(temperature_head(to_fp(m), t_fp));
        worst = worst.max((got - exact).abs());
        m += 0.001;
    }
    // Two SCALE ulps: one from quantising the input, one from the divide.
    assert!(worst < 3.0 / SCALE as f64, "worst-case error {worst:e} too large");
}

// ---------------------------------------------------------------------
// Temperature head
// ---------------------------------------------------------------------

#[test]
fn temperature_above_one_softens_toward_zero_logit() {
    // T > 1 must shrink the magnitude of the logit (pushing sigmoid toward 0.5).
    let t_fp = to_fp(3.0);
    for m in [4.0_f64, -4.0, 12.5, -12.5] {
        let out = from_fp(temperature_head(to_fp(m), t_fp));
        assert!(out.abs() < m.abs(), "T>1 must soften: {m} -> {out}");
        assert_eq!(out.signum(), m.signum(), "sign must be preserved");
    }
}

#[test]
fn temperature_of_one_is_identity() {
    let t_fp = to_fp(1.0);
    for m in [0.0_f64, 1.5, -7.25] {
        assert_eq!(temperature_head(to_fp(m), t_fp), to_fp(m));
    }
}

#[test]
fn zero_logit_maps_to_zero_for_any_temperature() {
    for t in [0.5_f64, 1.0, 3.0, 10.0] {
        assert_eq!(temperature_head(0, to_fp(t)), 0);
    }
}

#[test]
fn temperature_head_is_monotonic_in_the_logit() {
    let t_fp = to_fp(T_TRAINED);
    let mut prev = i64::MIN;
    let mut m = -60.0_f64;
    while m <= 60.0 {
        let out = temperature_head(to_fp(m), t_fp);
        assert!(out >= prev, "monotonicity violated at {m}");
        prev = out;
        m += 0.01;
    }
}

#[test]
#[should_panic(expected = "temperature must be positive")]
fn zero_temperature_panics_rather_than_wrapping() {
    temperature_head(to_fp(1.0), 0);
}

#[test]
#[should_panic(expected = "temperature must be positive")]
fn negative_temperature_panics() {
    temperature_head(to_fp(1.0), to_fp(-2.0));
}

// ---------------------------------------------------------------------
// Overflow safety at the declared bounds
// ---------------------------------------------------------------------

/// Everything inside MAX_ABS_LOGIT must be computable without i64 overflow.
/// Rust would panic on overflow in debug and wrap in release; neither is
/// acceptable inside a proof, so the bound is asserted rather than assumed.
#[test]
fn extreme_but_in_range_inputs_do_not_overflow() {
    let t_small = to_fp(0.001); // smallest sane temperature -> largest output
    let out = temperature_head(MAX_ABS_LOGIT, t_small);
    assert!(out > 0, "must not wrap to negative");
    let out_neg = temperature_head(-MAX_ABS_LOGIT, t_small);
    assert!(out_neg < 0);
    assert_eq!(out, -out_neg, "must stay symmetric");
}

#[test]
fn fp_mul_and_div_round_trip_within_one_ulp() {
    let a = to_fp(3.7);
    let b = to_fp(2.9);
    let round_tripped = fp_div(fp_mul(a, b), b);
    assert!((round_tripped - a).abs() <= 1, "round trip drifted: {round_tripped} vs {a}");
}

// ---------------------------------------------------------------------
// MLP head
// ---------------------------------------------------------------------

#[test]
fn mlp_relu_actually_clamps_negatives() {
    // Weights chosen so layer 1 is driven strongly negative; ReLU must zero it,
    // leaving only the final bias.
    let h = 2;
    let w1 = vec![to_fp(-1000.0); h];
    let b1 = vec![to_fp(-1000.0); h];
    let w2 = vec![to_fp(1.0); h * h];
    let b2 = vec![0i64; h];
    let w3 = vec![to_fp(1.0); h];
    let b3 = to_fp(0.5);

    let out = mlp_head(
        to_fp(5.0), 0, to_fp(1.0), &w1, &b1, &w2, &b2, &w3, b3,
    );
    assert_eq!(out, b3, "all activations should be clamped to zero");
}

#[test]
fn mlp_identity_configuration_passes_input_through() {
    // 1x1 network with unit weights and zero biases is the identity on positives.
    let w1 = vec![to_fp(1.0)];
    let b1 = vec![0i64];
    let w2 = vec![to_fp(1.0)];
    let b2 = vec![0i64];
    let w3 = vec![to_fp(1.0)];
    let out = mlp_head(to_fp(2.5), 0, to_fp(1.0), &w1, &b1, &w2, &b2, &w3, 0);
    assert!((from_fp(out) - 2.5).abs() < 1e-5, "identity net changed the value: {}", from_fp(out));
}

#[test]
fn mlp_input_normalisation_is_applied() {
    let w1 = vec![to_fp(1.0)];
    let b1 = vec![0i64];
    let w2 = vec![to_fp(1.0)];
    let b2 = vec![0i64];
    let w3 = vec![to_fp(1.0)];
    // (10 - 4) / 2 = 3
    let out = mlp_head(to_fp(10.0), to_fp(4.0), to_fp(2.0), &w1, &b1, &w2, &b2, &w3, 0);
    assert!((from_fp(out) - 3.0).abs() < 1e-5, "normalisation not applied: {}", from_fp(out));
}

#[test]
#[should_panic(expected = "w1 shape")]
fn mlp_rejects_mismatched_weight_shapes() {
    let w1 = vec![to_fp(1.0); 3]; // wrong length vs b1
    let b1 = vec![0i64; 2];
    let w2 = vec![to_fp(1.0); 4];
    let b2 = vec![0i64; 2];
    let w3 = vec![to_fp(1.0); 2];
    mlp_head(0, 0, to_fp(1.0), &w1, &b1, &w2, &b2, &w3, 0);
}

#[test]
#[should_panic(expected = "input std must be positive")]
fn mlp_rejects_zero_input_std() {
    let w1 = vec![to_fp(1.0)];
    let b1 = vec![0i64];
    let w2 = vec![to_fp(1.0)];
    let b2 = vec![0i64];
    let w3 = vec![to_fp(1.0)];
    mlp_head(to_fp(1.0), 0, 0, &w1, &b1, &w2, &b2, &w3, 0);
}
