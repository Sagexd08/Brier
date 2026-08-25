//! Host-side check of the on-chain Brier math (anchor glue shimmed away).
pub const WAD: u128 = 1_000_000_000_000_000_000;
pub const BPS_DENOMINATOR: u64 = 10_000;
#[derive(Debug, PartialEq)]
pub enum BrierError { ConfidenceOutOfRange, CapOutOfRange, MathOverflow }
pub type Result<T> = core::result::Result<T, BrierError>;
macro_rules! require { ($c:expr, $e:expr) => { if !$c { return Err($e); } } }

/// Squared error between a reported confidence and a binary outcome, WAD-scaled.
///
/// Overflow analysis, mirroring the EVM contract's:
/// `diff <= WAD = 1e18`, so `diff * diff <= 1e36`, which exceeds u64 but fits
/// comfortably in u128 (max ~3.4e38). The EVM version used uint256 for the same
/// reason. Returning to WAD scale by dividing keeps the result in [0, WAD].
pub fn squared_error(confidence: u128, outcome_correct: bool) -> Result<u128> {
    require!(confidence <= WAD, BrierError::ConfidenceOutOfRange);

    let outcome: u128 = if outcome_correct { WAD } else { 0 };
    let diff = if confidence > outcome {
        confidence - outcome
    } else {
        outcome - confidence
    };

    diff.checked_mul(diff)
        .ok_or(BrierError::MathOverflow)?
        .checked_div(WAD)
        .ok_or(BrierError::MathOverflow)
}

/// Uncapped slash: `stake * (confidence - outcome)^2`.
///
/// Exposed separately so the monotonicity property can be tested against the
/// value the cap has not yet flattened — the same split the EVM library makes,
/// for the same reason (the cap deliberately destroys monotonicity above it).
pub fn raw_slash(stake: u64, confidence: u128, outcome_correct: bool) -> Result<u64> {
    let sq = squared_error(confidence, outcome_correct)?;
    let slash = (stake as u128)
        .checked_mul(sq)
        .ok_or(BrierError::MathOverflow)?
        .checked_div(WAD)
        .ok_or(BrierError::MathOverflow)?;
    // slash <= stake because sq <= WAD, so the cast back to u64 cannot truncate.
    u64::try_from(slash).map_err(|_| BrierError::MathOverflow)
}

/// Slash amount, capped at `max_slash_bps` of the operator's stake.
pub fn slash_amount(
    stake: u64,
    confidence: u128,
    outcome_correct: bool,
    max_slash_bps: u64,
) -> Result<u64> {
    require!(
        max_slash_bps <= BPS_DENOMINATOR,
        BrierError::CapOutOfRange
    );

    let raw = raw_slash(stake, confidence, outcome_correct)?;
    let cap = (stake as u128)
        .checked_mul(max_slash_bps as u128)
        .ok_or(BrierError::MathOverflow)?
        .checked_div(BPS_DENOMINATOR as u128)
        .ok_or(BrierError::MathOverflow)?;
    let cap = u64::try_from(cap).map_err(|_| BrierError::MathOverflow)?;

    Ok(if raw > cap { cap } else { raw })
}

#[cfg(test)]
mod tests {
    use super::*;

    const LAMPORTS: u64 = 1_000_000_000; // 1 SOL
    const STAKE: u64 = 100 * LAMPORTS;

    fn wad(x: f64) -> u128 {
        (x * WAD as f64) as u128
    }

    // -- known answers, identical to the EVM BrierMath.t.sol cases ----------

    #[test]
    fn confidence_half_is_symmetric() {
        let right = squared_error(WAD / 2, true).unwrap();
        let wrong = squared_error(WAD / 2, false).unwrap();
        assert_eq!(right, wrong);
        assert_eq!(right, wad(0.25));
    }

    #[test]
    fn confident_and_wrong_is_severe() {
        assert_eq!(squared_error(wad(0.99), false).unwrap(), wad(0.9801));
        // 98.01% of stake, matching the EVM figure exactly.
        assert_eq!(raw_slash(STAKE, wad(0.99), false).unwrap(), 98_010_000_000);
    }

    #[test]
    fn confident_and_right_is_cheap() {
        assert_eq!(squared_error(wad(0.99), true).unwrap(), wad(0.0001));
        assert_eq!(raw_slash(STAKE, wad(0.99), true).unwrap(), 10_000_000);
    }

    #[test]
    fn uncertain_and_wrong_is_mild() {
        let uncertain = raw_slash(STAKE, wad(0.55), false).unwrap();
        let confident = raw_slash(STAKE, wad(0.99), false).unwrap();
        assert!(uncertain < confident);
        assert_eq!(uncertain, 30_250_000_000); // (0.55)^2 = 0.3025
    }

    #[test]
    fn extremes() {
        assert_eq!(squared_error(0, false).unwrap(), 0);
        assert_eq!(squared_error(WAD, true).unwrap(), 0);
        assert_eq!(squared_error(WAD, false).unwrap(), WAD);
        assert_eq!(squared_error(0, true).unwrap(), WAD);
    }

    // -- THE property: monotonic in miscalibration -------------------------

    #[test]
    fn monotonic_in_miscalibration_when_wrong() {
        let mut prev = 0u64;
        for c in 0..=100u128 {
            let conf = c * WAD / 100;
            let s = raw_slash(STAKE, conf, false).unwrap();
            if c > 0 {
                assert!(s > prev, "slash must strictly increase with confidence when wrong");
            }
            prev = s;
        }
    }

    #[test]
    fn monotonic_in_miscalibration_when_right() {
        let mut prev = u64::MAX;
        for c in 0..=100u128 {
            let conf = c * WAD / 100;
            let s = raw_slash(STAKE, conf, true).unwrap();
            assert!(s < prev, "slash must strictly decrease with confidence when right");
            prev = s;
        }
    }

    // -- properness: honest reporting minimises expected loss --------------

    #[test]
    fn proper_scoring_rule_honesty_is_optimal() {
        for p_pct in [30u128, 70] {
            let p = p_pct * WAD / 100;
            let mut best = u128::MAX;
            let mut best_report = 0u128;
            for c in 0..=100u128 {
                let report = c * WAD / 100;
                let expected = p * raw_slash(STAKE, report, true).unwrap() as u128 / WAD
                    + (WAD - p) * raw_slash(STAKE, report, false).unwrap() as u128 / WAD;
                if expected < best {
                    best = expected;
                    best_report = report;
                }
            }
            assert_eq!(best_report, p, "expected loss must be minimised at p={p_pct}%");
        }
    }

    // -- cap, bounds, overflow ---------------------------------------------

    #[test]
    fn cap_limits_slash() {
        assert_eq!(slash_amount(STAKE, wad(0.99), false, 5_000).unwrap(), STAKE / 2);
    }

    #[test]
    fn zero_cap_means_no_slash() {
        assert_eq!(slash_amount(STAKE, WAD, false, 0).unwrap(), 0);
    }

    #[test]
    fn rejects_confidence_above_one() {
        assert!(squared_error(WAD + 1, true).is_err());
    }

    #[test]
    fn rejects_cap_above_one_hundred_percent() {
        assert!(slash_amount(STAKE, WAD / 2, false, 10_001).is_err());
    }

    #[test]
    fn slash_never_exceeds_stake() {
        for c in 0..=100u128 {
            let conf = c * WAD / 100;
            for outcome in [true, false] {
                assert!(raw_slash(STAKE, conf, outcome).unwrap() <= STAKE);
            }
        }
    }

    /// u64::MAX lamports is far beyond the total SOL supply, but the library
    /// must not wrap there either.
    #[test]
    fn no_overflow_at_max_stake() {
        assert_eq!(raw_slash(u64::MAX, WAD, false).unwrap(), u64::MAX);
        assert_eq!(raw_slash(u64::MAX, WAD, true).unwrap(), 0);
    }

    /// Truncation rounds DOWN, i.e. always in the operator's favour — the same
    /// documented directional choice the EVM library makes.
    #[test]
    fn truncation_favours_the_operator() {
        assert_eq!(squared_error(1, false).unwrap(), 0);
    }
}
