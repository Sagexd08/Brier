"""Gate 5: the collusion detector's false-positive rate at the enforced threshold.

PAPER.md §8.5 states that the detector is wired to an enforcement action while
its false-positive rate on real traffic is unknown, and calls that the sharpest
limitation in the system. `docs/VENUE.md` lists it as a submission gate.

WHAT THIS CAN AND CANNOT MEASURE, stated first because the distinction is the
whole point and it is easy to overclaim here.

It CANNOT measure the false-positive rate on real dispute traffic. The protocol
has never run, so no real dispute graph exists, and no labelled real collusion
exists to be right or wrong about. Nothing in this script changes that, and
§8.5's limitation is NOT closed by it.

What it CAN measure is the quantity an operator actually needs before attaching
the oracle, and which was simply never computed: **on traffic containing no
rings at all, how often does the detector flag someone at the threshold the
contract enforces?** Every flag on ring-free traffic is false by construction,
so this is a true false-positive rate -- on synthetic traffic, against a
generator whose realism is itself an assumption.

That framing matters. A detector that fires on 15% of honest claimants in a
world with no collusion in it is unusable regardless of how well it recovers
injected rings, and §A.5's recall figures cannot reveal that. A detector that
fires on 0% is not thereby validated for real traffic -- it has only cleared the
lowest bar there is.

THE THRESHOLD IS NOT A FREE PARAMETER. CollusionOracle.sol fixes
MIN_SCORE = 0.8e18 and rejects any flag below it, so 0.8 is the operating point
that matters. Reporting an ROC curve and letting a reader pick a threshold would
describe a system other than the deployed one.

Writes artifacts/ablation/detector_fpr.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.collusion import (
    build_adjacency,
    claimant_features,
    generate_dispute_graph,
    predict_scores,
    train_detector,
)
from brier.config import ARTIFACTS, EVAL_SEEDS

ABLATION = ARTIFACTS / "ablation"

# The threshold CollusionOracle.sol enforces. Not a tunable knob here:
# `MIN_SCORE = 0.8e18`, and flag() reverts below it.
ENFORCED_THRESHOLD = 0.8

# Secondary operating points, reported only to show how sharply the rate moves
# with the threshold -- NOT as an invitation to pick a friendlier one.
REPORTED_THRESHOLDS = (0.5, 0.8, 0.9, 0.95)

# Ring intensities for the held-out evaluation. Lower is harder: at 0.85 a ring
# member sends 85% of its disputes to the ring's operator.
INTENSITIES = (0.85, 0.60, 0.40)


def _graph_scores(train_seed: int, eval_graph_kwargs: dict):
    """Train on one graph, score a disjoint second graph.

    Training and evaluating on one graph would measure memorisation. The
    detector never sees the evaluation graph.
    """
    g_train = generate_dispute_graph(seed=train_seed)
    x_tr = claimant_features(g_train)
    nb_tr = build_adjacency(g_train)
    # The whole training graph is training data: evaluation happens on a
    # disjoint second graph, which is a stricter split than the within-graph
    # mask A.5 uses -- there, train and test nodes share edges.
    train_mask = np.ones(len(g_train["labels"]), dtype=bool)
    model = train_detector(x_tr, nb_tr, g_train["labels"], train_mask, seed=train_seed)

    g_eval = generate_dispute_graph(**eval_graph_kwargs)
    x_ev = claimant_features(g_eval)
    nb_ev = build_adjacency(g_eval)
    return predict_scores(model, x_ev, nb_ev), g_eval


def main() -> int:
    ABLATION.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------
    # 1. The measurement that matters: NO RINGS. Every flag is false.
    # ---------------------------------------------------------------
    print("A. ring-free traffic (n_rings=0) -- every flag is a false positive")
    clean_rows = []
    for seed in EVAL_SEEDS:
        np.random.seed(seed)
        torch.manual_seed(seed)
        scores, g = _graph_scores(
            train_seed=seed,
            eval_graph_kwargs={"n_rings": 0, "seed": seed + 500_000},
        )
        assert g["labels"].sum() == 0, "ring-free graph must contain no positives"

        row = {"seed": seed, "n_claimants": int(len(scores)),
               "max_score": float(scores.max()), "mean_score": float(scores.mean())}
        for t in REPORTED_THRESHOLDS:
            flagged = int((scores >= t).sum())
            row[f"fpr@{t}"] = flagged / len(scores)
            row[f"flagged@{t}"] = flagged
        clean_rows.append(row)
        print(f"  seed {seed:>8}  n={row['n_claimants']:4d}  "
              f"max score {row['max_score']:.4f}  "
              f"flagged@0.8 {row['flagged@0.8']:3d}  "
              f"FPR@0.8 {row['fpr@0.8']:.4f}")

    fpr = np.array([r[f"fpr@{ENFORCED_THRESHOLD}"] for r in clean_rows])
    flagged_total = sum(r[f"flagged@{ENFORCED_THRESHOLD}"] for r in clean_rows)
    claimants_total = sum(r["n_claimants"] for r in clean_rows)

    print(f"\n  FPR at the enforced threshold ({ENFORCED_THRESHOLD}): "
          f"{fpr.mean():.4f} +/- {fpr.std(ddof=1):.4f}")
    print(f"  {flagged_total} honest claimants flagged out of {claimants_total} "
          f"across {len(EVAL_SEEDS)} ring-free graphs")

    # Wilson upper bound: with few or zero events, the point estimate is not the
    # number to act on. A 0/1800 observation is consistent with a rate that is
    # small but not zero, and an operator deciding whether to attach the oracle
    # needs the bound rather than the estimate.
    z = 1.96
    n, k = claimants_total, flagged_total
    denom = 1 + z * z / n
    centre = (k / n + z * z / (2 * n)) / denom
    half = z * np.sqrt(k / n * (1 - k / n) / n + z * z / (4 * n * n)) / denom
    wilson_hi = centre + half
    print(f"  95% Wilson upper bound on the true rate: {wilson_hi:.5f} "
          f"({wilson_hi * 100:.3f}%)")

    # ---------------------------------------------------------------
    # 2. FPR among honest claimants when rings ARE present. The operational
    #    case: the detector is not run on clean traffic, it is run on traffic
    #    that may contain rings, and it must not sweep up bystanders.
    # ---------------------------------------------------------------
    print("\nB. traffic WITH rings -- FPR among the honest, recall among ring members")
    mixed_rows = []
    for intensity in INTENSITIES:
        per_int = []
        for seed in EVAL_SEEDS:
            np.random.seed(seed)
            torch.manual_seed(seed)
            scores, g = _graph_scores(
                train_seed=seed,
                eval_graph_kwargs={"ring_intensity": intensity, "seed": seed + 500_000},
            )
            y = g["labels"].astype(bool)
            flag = scores >= ENFORCED_THRESHOLD
            honest = ~y
            per_int.append({
                "seed": seed,
                "fpr": float((flag & honest).sum() / honest.sum()),
                "recall": float((flag & y).sum() / y.sum()) if y.sum() else float("nan"),
                "n_honest": int(honest.sum()),
                "n_ring": int(y.sum()),
            })
        f = np.array([r["fpr"] for r in per_int])
        rc = np.array([r["recall"] for r in per_int])
        # Of everyone flagged, what fraction was honest? This is the number a
        # flagged claimant cares about, and it is not the FPR.
        tp = np.array([r["recall"] * r["n_ring"] for r in per_int])
        fp = np.array([r["fpr"] * r["n_honest"] for r in per_int])
        fdr = float(fp.sum() / (fp.sum() + tp.sum())) if (fp.sum() + tp.sum()) else 0.0
        mixed_rows.append({
            "ring_intensity": intensity,
            "fpr_mean": float(f.mean()), "fpr_std": float(f.std(ddof=1)),
            "recall_mean": float(rc.mean()), "recall_std": float(rc.std(ddof=1)),
            "false_discovery_rate": fdr,
            "per_seed": per_int,
        })
        print(f"  intensity {intensity:.2f}:  FPR {f.mean():.4f} +/- {f.std(ddof=1):.4f}   "
              f"recall {rc.mean():.4f} +/- {rc.std(ddof=1):.4f}   "
              f"FDR {fdr:.4f}")

    # ---------------------------------------------------------------
    # 3. Verdict, and what it does not license.
    # ---------------------------------------------------------------
    usable = bool(wilson_hi < 0.01)
    print(f"\nFPR upper bound below 1%: {usable}")
    print("This measures SYNTHETIC ring-free traffic. It does not measure real")
    print("traffic, and PAPER.md 8.5 stays open -- what changes is that an")
    print("operator now has a number where there was none, and a generator they")
    print("can substitute their own traffic into.")

    payload = {
        "question": "How often does the detector flag an honest claimant at the "
                    "threshold CollusionOracle.sol enforces?",
        "enforced_threshold": ENFORCED_THRESHOLD,
        "threshold_source": "CollusionOracle.sol MIN_SCORE = 0.8e18",
        "seeds": list(EVAL_SEEDS),
        "ring_free": {
            "per_seed": clean_rows,
            "fpr_mean": float(fpr.mean()),
            "fpr_std": float(fpr.std(ddof=1)),
            "flagged_total": flagged_total,
            "claimants_total": claimants_total,
            "wilson_95_upper": float(wilson_hi),
        },
        "with_rings": mixed_rows,
        "verdict": {
            "fpr_upper_bound_below_1pct": usable,
            "measures_real_traffic": False,
            "limitation_closed": False,
            "note": "The protocol has never run, so no real dispute graph and no "
                    "labelled real collusion exist. This bounds the false-positive "
                    "rate on SYNTHETIC ring-free traffic, which is a true FPR "
                    "against a generator whose realism is an assumption. PAPER.md "
                    "8.5 remains open; what it gains is a measured number and a "
                    "reproducible procedure an operator can re-run on their own "
                    "traffic once they have some.",
        },
    }

    out = ABLATION / "detector_fpr.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
