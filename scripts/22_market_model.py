"""Phase 2: the welfare model for confidence-attested decision markets.

Computes every number in PAPER.md's economic framework section, so the
chapter's arithmetic is reproducible rather than asserted. Nothing here is a
simulation of a real market: it is the numerical companion to the propositions,
and its job is to make the algebra checkable and the crossovers concrete.

THE SETUP. A buyer-agent purchases a decision from a seller-agent through an
x402-gated endpoint. The decision is binary and the buyer must choose whether to
act on it:

    act and the decision is right  -> buyer gains V
    act and the decision is wrong  -> buyer loses K
    abstain                        -> 0

A rational buyer acts iff its posterior that the decision is right exceeds
t = K / (V + K). The buyer's only information about that posterior is the
confidence c the seller reports. So the entire question is whether c is
informative -- and that is a question about the seller's incentives, not about
the model's accuracy.

THREE REGIMES.

  Plain x402. The seller is paid per call and bears no cost for a wrong
  decision. Reporting is free, so any c is as cheap as any other and the
  sale-maximising report is c = 1 for every decision. c carries no information,
  the buyer cannot condition on it, and it acts always. Welfare is the
  unconditional mean payoff.

  HeLa-style accountability bond (RELATED_WORK_V2.md 2). A flat fraction of the
  bond is slashed on an adverse verdict. Crucially the slash does not depend on
  c, so the reporting margin is STILL unconstrained and c = 1 remains optimal.
  What the bond does constrain is the participation margin: the seller only
  sells decisions whose expected slash is below the price. That is a real
  welfare improvement, and the model gives it full credit.

  Brier. The slash is S(c-o)^2, strictly proper, so the seller's expected-loss
  minimising report is c = p (Proposition 1). c is now informative and each
  buyer applies its own threshold t to it.

WHAT THE MODEL SHOWS, including where Brier does not win:

  1. Brier beats plain x402 iff the per-attestation cost g is below the
     screening value G. At L1 gas prices with these parameters g exceeds G and
     Brier is welfare-NEGATIVE. This is the participation condition of 6.11,
     and the honest reading is that the mechanism does not pay for itself on
     cheap decisions or expensive chains.

  2. Against a single buyer, an optimally tuned HeLa bond matches Brier
     EXACTLY. Not approximately -- exactly, because both end up implementing
     the same threshold. Brier's advantage there is that it needs no tuning;
     it is not that it achieves something a bond cannot.

  3. The separation appears only with heterogeneous buyers. A bond implements
     ONE pooled threshold; the report c is a sufficient statistic that each
     buyer applies its OWN threshold to. Optimally tuned, the bond still loses
     ~70% of the gain when buyers' thresholds range over [0.50, 0.95].

Writes artifacts/calibration/market_model.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.config import CALIB

# Draws from the seller's decision population. Fixed seed; the numbers in the
# proposal must be reproducible to the digit.
N_DRAWS = 400_000
SEED = 0

# Beta(5,2): most decisions are sound, a minority are not. Shape chosen so the
# mean correctness (~0.714) is near the prototype's measured test accuracy
# (0.715, PAPER.md 6.1) rather than picked to flatter the result.
BETA_A, BETA_B = 5.0, 2.0

# One credit decision. A wrong approval costs 4x what a right one earns --
# the asymmetry the UCI dataset itself ships (data.py header: 5x), rounded down.
V, K = 100.0, 400.0

# Price of one decision through the endpoint.
PRICE = 20.0

# Per-attestation verification cost, from the measured gas table (6.11).
GAS_COSTS = {
    "L1 busy (30 gwei)": 79.86,
    "L1 quiet (10 gwei)": 26.62,
    "L2 typical (0.05 gwei)": 0.13,
    "L2 cheap (0.01 gwei)": 0.03,
}

# Heterogeneous buyers for the separation result. Same V, escalating downside:
# a thin-margin lender, a normal one, a regulated one, a systemically exposed
# one. Their optimal thresholds span 0.50 to 0.95.
BUYERS = [(100.0, 100.0), (100.0, 400.0), (100.0, 900.0), (100.0, 1900.0)]


def payoff(ps, V, K):
    """Buyer's expected payoff from acting on a decision correct w.p. p."""
    return ps * V - (1.0 - ps) * K


def welfare_x402(ps, V, K):
    """Plain x402: c is uninformative, so the buyer acts unconditionally."""
    return float(np.mean(payoff(ps, V, K)))


def welfare_brier(ps, V, K, g=0.0):
    """Brier: c = p, so the buyer acts iff p >= t = K/(V+K)."""
    t = K / (V + K)
    return float(np.mean(np.where(ps >= t, payoff(ps, V, K), 0.0))) - g


def welfare_hela(ps, V, K, phi_B_d, price=PRICE):
    """Flat-fraction bond: the report is still uninformative, but the seller
    only sells when price exceeds its expected slash phi*B*d*(1-p), i.e. when
    p >= 1 - price/(phi*B*d). One pooled threshold for every buyer."""
    p_min = max(0.0, 1.0 - price / phi_B_d) if phi_B_d > 0 else 0.0
    return float(np.mean(np.where(ps >= p_min, payoff(ps, V, K), 0.0))), p_min


def main() -> int:
    CALIB.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    ps = rng.beta(BETA_A, BETA_B, N_DRAWS)

    t = K / (V + K)
    w_x402 = welfare_x402(ps, V, K)
    w_brier_gross = welfare_brier(ps, V, K, g=0.0)
    screening_value = w_brier_gross - w_x402

    print(f"decision population: Beta({BETA_A},{BETA_B}), mean p = {ps.mean():.4f}")
    print(f"buyer acts iff c >= t = {t:.4f}   (V={V}, K={K})\n")
    print(f"plain x402 welfare        {w_x402:9.4f}")
    print(f"Brier gross welfare       {w_brier_gross:9.4f}")
    print(f"screening value G         {screening_value:9.4f}"
          f"   <- the most Brier can cost and still pay")

    # --- 1. the participation condition, at measured gas prices --------------
    print("\nparticipation condition, at measured per-attestation costs:")
    participation = {}
    for label, g in GAS_COSTS.items():
        w = welfare_brier(ps, V, K, g=g)
        participation[label] = {
            "cost": g, "welfare": w, "gain_over_x402": w - w_x402, "worth_it": w > w_x402
        }
        verdict = "pays" if w > w_x402 else "DOES NOT PAY"
        print(f"  {label:26s} g={g:6.2f}  welfare {w:9.4f}  "
              f"gain {w - w_x402:+9.4f}  {verdict}")

    # --- 2. single buyer: a tuned bond matches Brier exactly -----------------
    grid = np.linspace(1.0, 3000.0, 3000)
    hela_curve = [(float(v), *welfare_hela(ps, V, K, v)) for v in grid]
    best_v, best_w, best_pmin = max(hela_curve, key=lambda r: r[1])

    print(f"\nsingle buyer, HeLa tuned over phi*B*d:")
    print(f"  best welfare {best_w:.4f} at phi*B*d={best_v:.1f} -> pooled threshold {best_pmin:.4f}")
    print(f"  Brier gross  {w_brier_gross:.4f} at threshold {t:.4f}")
    print(f"  difference   {w_brier_gross - best_w:+.4f}"
          f"  -- a tuned bond MATCHES Brier here; Brier's edge is needing no tuning")

    sensitivity = {}
    for mult in (0.5, 1.0, 2.0):
        w, pmin = welfare_hela(ps, V, K, best_v * mult)
        sensitivity[f"x{mult}"] = {"phi_B_d": best_v * mult, "threshold": pmin,
                                   "welfare": w, "vs_brier": w - w_brier_gross}
        print(f"    bond x{mult:.1f}: threshold {pmin:.4f}  welfare {w:9.4f}  "
              f"({w - w_brier_gross:+.4f} vs Brier)")

    # --- 3. heterogeneous buyers: where the separation actually lives --------
    def brier_hetero():
        return float(np.mean([
            np.mean(np.where(ps >= Kb / (Vb + Kb), payoff(ps, Vb, Kb), 0.0))
            for Vb, Kb in BUYERS
        ]))

    def hela_hetero(phi_B_d):
        p_min = max(0.0, 1.0 - PRICE / phi_B_d) if phi_B_d > 0 else 0.0
        return float(np.mean([
            np.mean(np.where(ps >= p_min, payoff(ps, Vb, Kb), 0.0)) for Vb, Kb in BUYERS
        ])), p_min

    b_het = brier_hetero()
    h_curve = [(float(v), *hela_hetero(v)) for v in grid]
    h_best_v, h_best_w, h_best_pmin = max(h_curve, key=lambda r: r[1])
    loss = b_het - h_best_w

    print(f"\nheterogeneous buyers (thresholds "
          f"{[round(Kb / (Vb + Kb), 2) for Vb, Kb in BUYERS]}):")
    print(f"  Brier, each buyer applies its own threshold  {b_het:9.4f}")
    print(f"  HeLa, one pooled threshold, best tuned       {h_best_w:9.4f}"
          f"  (threshold {h_best_pmin:.4f})")
    print(f"  efficiency loss from pooling                 {loss:9.4f}"
          f"  ({100 * loss / abs(b_het):.1f}%)")

    payload = {
        "setup": {
            "n_draws": N_DRAWS, "seed": SEED,
            "beta": [BETA_A, BETA_B], "mean_p": float(ps.mean()),
            "V": V, "K": K, "price": PRICE, "threshold": t,
        },
        "single_buyer": {
            "welfare_x402": w_x402,
            "welfare_brier_gross": w_brier_gross,
            "screening_value": screening_value,
            "participation": participation,
            "hela_best": {"phi_B_d": best_v, "threshold": best_pmin, "welfare": best_w},
            "hela_matches_brier": abs(w_brier_gross - best_w) < 1e-6,
            "hela_sensitivity": sensitivity,
        },
        "heterogeneous_buyers": {
            "buyers": [{"V": Vb, "K": Kb, "threshold": Kb / (Vb + Kb)} for Vb, Kb in BUYERS],
            "welfare_brier": b_het,
            "hela_best": {"phi_B_d": h_best_v, "threshold": h_best_pmin, "welfare": h_best_w},
            "pooling_loss": loss,
            "pooling_loss_pct": 100 * loss / abs(b_het),
        },
    }

    out = CALIB / "market_model.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
