//! SP1 prover selection and network-cost logging.
//!
//! # Safety contract
//!
//! `NETWORK_PRIVATE_KEY` is read from the process environment and nowhere else.
//! This module must never:
//!   * write it to a file,
//!   * include it in a log line, `Debug` output, panic message, or error,
//!   * return it to a caller.
//!
//! `ProverMode` deliberately does not derive `Debug` in a way that could carry
//! the key, and the key is never stored in a struct field — it is read at the
//! point of use and handed straight to the SDK. `secret_is_never_rendered`
//! asserts the no-leak property rather than leaving it to review.
//!
//! # Why `network` is never a default
//!
//! Network mode spends real $PROVE per request. Defaulting to it anywhere —
//! a test, a CI job, `make research-eval` — would spend the user's funds on
//! every push. `ProverMode::from_env` therefore falls back to `Mock`, and
//! selecting `Network` requires an explicit `SP1_PROVER_MODE=network` set by a
//! human for that run.

use std::fmt;
use std::io::Write;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

/// Which prover backend to use.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum ProverMode {
    /// No real proving. Instant, free, and the default everywhere.
    Mock,
    /// Real proof generated on this machine. Free, but see the hardware
    /// requirements in solana/docs/PHASE0_PROVING_STACK.md.
    Local,
    /// Succinct Prover Network. COSTS REAL $PROVE PER REQUEST.
    Network,
}

impl ProverMode {
    /// Read the mode from `SP1_PROVER_MODE`, defaulting to `Mock`.
    ///
    /// An unrecognised value is an error rather than a silent fallback: a typo
    /// like `SP1_PROVER_MODE=netwrok` must not quietly run in mock mode and be
    /// mistaken for a real benchmark.
    pub fn from_env() -> Result<Self, ProverConfigError> {
        match std::env::var("SP1_PROVER_MODE") {
            Err(_) => Ok(ProverMode::Mock),
            Ok(v) => match v.trim().to_ascii_lowercase().as_str() {
                "" => Ok(ProverMode::Mock),
                "mock" => Ok(ProverMode::Mock),
                "local" => Ok(ProverMode::Local),
                "network" => Ok(ProverMode::Network),
                other => Err(ProverConfigError::UnknownMode(other.to_string())),
            },
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            ProverMode::Mock => "mock",
            ProverMode::Local => "local",
            ProverMode::Network => "network",
        }
    }

    /// True only for the mode that spends money.
    pub fn costs_money(self) -> bool {
        matches!(self, ProverMode::Network)
    }
}

impl fmt::Display for ProverMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl fmt::Debug for ProverMode {
    // Explicit, so no future derive can pick up a key-bearing field.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "ProverMode({})", self.as_str())
    }
}

#[derive(Debug)]
pub enum ProverConfigError {
    /// The value is echoed because a mode string is not secret. Compare with
    /// `MissingNetworkKey`, which deliberately carries nothing.
    UnknownMode(String),
    /// Network mode selected without a key present.
    ///
    /// Carries NO payload: not the variable's value, not its length, not a
    /// prefix. An error type is a common accidental leak path.
    MissingNetworkKey,
}

impl fmt::Display for ProverConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ProverConfigError::UnknownMode(v) => write!(
                f,
                "unknown SP1_PROVER_MODE {v:?}; expected one of: mock, local, network"
            ),
            ProverConfigError::MissingNetworkKey => f.write_str(
                "SP1_PROVER_MODE=network requires NETWORK_PRIVATE_KEY to be set in the \
                 environment. See docs/prover-network-setup.md for the manual steps. \
                 Network proving spends real $PROVE per request.",
            ),
        }
    }
}

impl std::error::Error for ProverConfigError {}

/// Verify that network mode is usable WITHOUT returning or copying the key.
///
/// Returns `Ok(())` only. The caller then hands control to the SDK, which reads
/// the same variable itself. Deliberately no `get_network_key()` accessor
/// exists — anything that returns the key invites it into a log line.
pub fn ensure_network_key_present() -> Result<(), ProverConfigError> {
    match std::env::var("NETWORK_PRIVATE_KEY") {
        Ok(v) if !v.trim().is_empty() => Ok(()),
        _ => Err(ProverConfigError::MissingNetworkKey),
    }
}

/// Resolve the mode and check its prerequisites.
///
/// `local` and `mock` must never touch `NETWORK_PRIVATE_KEY`. That is asserted
/// by `local_mode_never_requires_network_key`, because a code path that
/// accidentally demands credentials offline would break CI in a way that
/// tempts someone to set the key there.
pub fn resolve() -> Result<ProverMode, ProverConfigError> {
    let mode = ProverMode::from_env()?;
    if mode == ProverMode::Network {
        ensure_network_key_present()?;
    }
    Ok(mode)
}

// ---------------------------------------------------------------------
// Cost logging (network mode only)
// ---------------------------------------------------------------------

/// One metered proof request. Feeds Phase 2's proving-cost measurement.
///
/// Contains no key material by construction: there is no field that could
/// hold one.
#[derive(Clone)]
pub struct CostRecord {
    pub unix_ms: u128,
    pub program: String,
    pub n_params: Option<u32>,
    pub cycles: Option<u64>,
    /// Cost as reported by the SDK, if it exposes one. `None` means the SDK
    /// did not report a cost — recorded as unknown rather than guessed at.
    pub prove_cost: Option<String>,
    pub duration_ms: u128,
    pub success: bool,
}

impl CostRecord {
    fn to_json(&self) -> String {
        let q = |o: &Option<String>| match o {
            Some(s) => format!("{s:?}"),
            None => "null".to_string(),
        };
        let n = |o: &Option<u64>| match o {
            Some(v) => v.to_string(),
            None => "null".to_string(),
        };
        format!(
            "{{\"unix_ms\":{},\"program\":{:?},\"n_params\":{},\"cycles\":{},\
             \"prove_cost\":{},\"duration_ms\":{},\"success\":{}}}",
            self.unix_ms,
            self.program,
            self.n_params.map(|v| v.to_string()).unwrap_or("null".into()),
            n(&self.cycles),
            q(&self.prove_cost),
            self.duration_ms,
            self.success
        )
    }
}

pub fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

fn cost_log_path() -> PathBuf {
    std::env::var("SP1_COST_LOG")
        .unwrap_or_else(|_| "artifacts/prover/network_costs.jsonl".to_string())
        .into()
}

/// Append a cost record. No-op unless the mode actually spends money, so mock
/// and local runs cannot pollute the cost dataset with free proofs.
pub fn log_cost(mode: ProverMode, rec: &CostRecord) -> std::io::Result<()> {
    if !mode.costs_money() {
        return Ok(());
    }
    let path = cost_log_path();
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let mut f = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)?;
    writeln!(f, "{}", rec.to_json())
}

// ---------------------------------------------------------------------
// tests
// ---------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    /// Env-var mutation is process-global, so these run under one lock rather
    /// than racing each other.
    static LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    fn with_env<F: FnOnce()>(pairs: &[(&str, Option<&str>)], f: F) {
        let _g = LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let saved: Vec<(String, Option<String>)> = pairs
            .iter()
            .map(|(k, _)| (k.to_string(), std::env::var(k).ok()))
            .collect();
        for (k, v) in pairs {
            match v {
                Some(val) => std::env::set_var(k, val),
                None => std::env::remove_var(k),
            }
        }
        f();
        for (k, v) in saved {
            match v {
                Some(val) => std::env::set_var(&k, val),
                None => std::env::remove_var(&k),
            }
        }
    }

    #[test]
    fn default_is_mock_when_unset() {
        with_env(&[("SP1_PROVER_MODE", None)], || {
            assert_eq!(ProverMode::from_env().unwrap(), ProverMode::Mock);
        });
    }

    #[test]
    fn empty_value_is_mock_not_network() {
        with_env(&[("SP1_PROVER_MODE", Some(""))], || {
            assert_eq!(ProverMode::from_env().unwrap(), ProverMode::Mock);
        });
    }

    /// A typo must be an error, not a silent mock run that could be mistaken
    /// for a real benchmark.
    #[test]
    fn unknown_mode_is_an_error() {
        with_env(&[("SP1_PROVER_MODE", Some("netwrok"))], || {
            assert!(matches!(
                ProverMode::from_env(),
                Err(ProverConfigError::UnknownMode(_))
            ));
        });
    }

    /// THE offline guarantee: local mode must work with no network key at all.
    #[test]
    fn local_mode_never_requires_network_key() {
        with_env(
            &[("SP1_PROVER_MODE", Some("local")), ("NETWORK_PRIVATE_KEY", None)],
            || {
                assert_eq!(resolve().unwrap(), ProverMode::Local);
            },
        );
    }

    #[test]
    fn mock_mode_never_requires_network_key() {
        with_env(
            &[("SP1_PROVER_MODE", Some("mock")), ("NETWORK_PRIVATE_KEY", None)],
            || {
                assert_eq!(resolve().unwrap(), ProverMode::Mock);
            },
        );
    }

    #[test]
    fn network_mode_without_key_fails_closed() {
        with_env(
            &[("SP1_PROVER_MODE", Some("network")), ("NETWORK_PRIVATE_KEY", None)],
            || {
                assert!(matches!(resolve(), Err(ProverConfigError::MissingNetworkKey)));
            },
        );
    }

    #[test]
    fn whitespace_only_key_is_treated_as_absent() {
        with_env(
            &[
                ("SP1_PROVER_MODE", Some("network")),
                ("NETWORK_PRIVATE_KEY", Some("   ")),
            ],
            || {
                assert!(matches!(resolve(), Err(ProverConfigError::MissingNetworkKey)));
            },
        );
    }

    /// No rendering of any error or mode may contain key material.
    #[test]
    fn secret_is_never_rendered() {
        const CANARY: &str = "0xDEADBEEFCAFEBABE_do_not_leak_this_value";
        with_env(
            &[
                ("SP1_PROVER_MODE", Some("network")),
                ("NETWORK_PRIVATE_KEY", Some(CANARY)),
            ],
            || {
                // Resolve succeeds; nothing returned carries the key.
                let mode = resolve().unwrap();
                assert_eq!(mode, ProverMode::Network);
                for s in [
                    format!("{mode}"),
                    format!("{mode:?}"),
                    format!("{}", ProverConfigError::MissingNetworkKey),
                    format!("{:?}", ProverConfigError::MissingNetworkKey),
                ] {
                    assert!(!s.contains(CANARY), "key leaked into: {s}");
                    assert!(!s.contains("DEADBEEF"), "partial key leaked into: {s}");
                }
            },
        );
    }

    #[test]
    fn cost_record_json_has_no_key_field() {
        let rec = CostRecord {
            unix_ms: 1,
            program: "calibration-head".into(),
            n_params: Some(321),
            cycles: Some(12345),
            prove_cost: None,
            duration_ms: 42,
            success: true,
        };
        let json = rec.to_json();
        for forbidden in ["key", "secret", "private", "token"] {
            assert!(!json.to_lowercase().contains(forbidden), "suspicious field in {json}");
        }
        assert!(json.contains("\"cycles\":12345"));
        assert!(json.contains("\"prove_cost\":null"), "unknown cost must be null, not guessed");
    }

    /// Free modes must not write to the cost dataset.
    #[test]
    fn cost_logging_is_a_noop_for_free_modes() {
        let rec = CostRecord {
            unix_ms: 0,
            program: "x".into(),
            n_params: None,
            cycles: None,
            prove_cost: None,
            duration_ms: 0,
            success: true,
        };
        let tmp = std::env::temp_dir().join("brier_cost_should_not_exist.jsonl");
        let _ = std::fs::remove_file(&tmp);
        with_env(&[("SP1_COST_LOG", Some(tmp.to_str().unwrap()))], || {
            log_cost(ProverMode::Mock, &rec).unwrap();
            log_cost(ProverMode::Local, &rec).unwrap();
        });
        assert!(!tmp.exists(), "free modes must not create a cost log");
    }

    #[test]
    fn only_network_mode_costs_money() {
        assert!(!ProverMode::Mock.costs_money());
        assert!(!ProverMode::Local.costs_money());
        assert!(ProverMode::Network.costs_money());
    }
}
