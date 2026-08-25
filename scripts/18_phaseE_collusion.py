"""Phase E: can a GNN recover injected collusion rings?

There are no labelled real collusion examples -- the protocol has never run --
so no real-world detection performance is claimed or claimable. What CAN be
established is whether the detector recovers rings that were deliberately
planted, across a range of how hard they were made to see. That is the
honest question, and it is the only one answered here.

Two controls keep the result meaningful:

  * a DEGREE BASELINE (rank claimants by concentration on their top operator).
    If the GNN cannot beat that, the graph structure is contributing nothing
    and the model is an expensive threshold.
  * an INTENSITY SWEEP. At intensity 1.0 a ring member disputes only its own
    operator and is trivially separable. Reporting only that number would be
    close to dishonest, so the sweep goes down to 0.5 where the ring is half
    camouflaged in normal traffic.

    python scripts/18_phaseE_collusion.py

Writes artifacts/ablation/phaseE.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brier.collusion import (  # noqa: E402
    build_adjacency,
    claimant_features,
    generate_dispute_graph,
    predict_scores,
    train_detector,
)
from brier.config import ARTIFACTS  # noqa: E402

OUT = ARTIFACTS / "ablation"
INTENSITIES = (1.0, 0.85, 0.70, 0.60, 0.50)
TRIALS = 5


def average_precision(scores: np.ndarray, labels: np.ndarray) -> float:
    order = np.argsort(-scores)
    y = labels[order]
    tp = np.cumsum(y)
    precision = tp / np.arange(1, len(y) + 1)
    total = y.sum()
    return float((precision * y).sum() / total) if total else 0.0


def roc_auc(scores: np.ndarray, labels: np.ndarray) -> float:
    pos, neg = scores[labels == 1], scores[labels == 0]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    # Rank-based Mann-Whitney U, ties counted as half.
    order = np.argsort(scores)
    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    r_pos = ranks[labels == 1].sum()
    return float((r_pos - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


def precision_at_k(scores: np.ndarray, labels: np.ndarray, k: int) -> float:
    top = np.argsort(-scores)[:k]
    return float(labels[top].mean())


def run_trial(intensity: float, seed: int) -> dict:
    g = generate_dispute_graph(ring_intensity=intensity, seed=seed)
    x = claimant_features(g)
    nb = build_adjacency(g)
    y = g["labels"]

    # Half the claimants are used for training; the metrics below are computed
    # on the held-out half only.
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(y))
    train_mask = np.zeros(len(y), dtype=bool)
    train_mask[perm[: len(y) // 2]] = True
    test_mask = ~train_mask

    model = train_detector(x, nb, y, train_mask, seed=seed)
    scores = predict_scores(model, x, nb)

    # Control: concentration on the top operator, feature index 1.
    baseline = x[:, 1]

    n_rings_in_test = int(y[test_mask].sum())
    return {
        "intensity": intensity,
        "seed": seed,
        "n_ring_claimants_in_test": n_rings_in_test,
        "gnn": {
            "auc": roc_auc(scores[test_mask], y[test_mask]),
            "avg_precision": average_precision(scores[test_mask], y[test_mask]),
            "precision_at_k": precision_at_k(scores[test_mask], y[test_mask],
                                             max(n_rings_in_test, 1)),
        },
        "degree_baseline": {
            "auc": roc_auc(baseline[test_mask], y[test_mask]),
            "avg_precision": average_precision(baseline[test_mask], y[test_mask]),
            "precision_at_k": precision_at_k(baseline[test_mask], y[test_mask],
                                             max(n_rings_in_test, 1)),
        },
    }


def main() -> int:
    rows = []
    for intensity in INTENSITIES:
        for t in range(TRIALS):
            print(f"  intensity {intensity:.2f}  trial {t} ...", flush=True)
            rows.append(run_trial(intensity, seed=1000 + t))

    summary = {}
    for intensity in INTENSITIES:
        sel = [r for r in rows if r["intensity"] == intensity]
        entry = {}
        for arm in ("gnn", "degree_baseline"):
            for metric in ("auc", "avg_precision", "precision_at_k"):
                vals = np.array([s[arm][metric] for s in sel], dtype=float)
                entry[f"{arm}_{metric}"] = {"mean": float(np.nanmean(vals)),
                                            "std": float(np.nanstd(vals))}
        summary[f"{intensity:.2f}"] = entry

    payload = {
        "intensities": list(INTENSITIES),
        "trials_per_intensity": TRIALS,
        "per_trial": rows,
        "summary": summary,
        "validation_status": "synthetic_only",
        "caveat": (
            "Rings are injected, so labels exist by construction. No real-world "
            "detection performance is claimed. This is a monitoring and triage "
            "aid; it is not wired to any enforcement action and must not be."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phaseE.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n  intensity     GNN AUC        baseline AUC    GNN P@k     base P@k")
    for intensity in INTENSITIES:
        s = summary[f"{intensity:.2f}"]
        print("  {:.2f}          {:.3f}+/-{:.3f}  {:.3f}+/-{:.3f}   {:.3f}       {:.3f}".format(
            intensity,
            s["gnn_auc"]["mean"], s["gnn_auc"]["std"],
            s["degree_baseline_auc"]["mean"], s["degree_baseline_auc"]["std"],
            s["gnn_precision_at_k"]["mean"], s["degree_baseline_precision_at_k"]["mean"]))
    print(f"\n  wrote {(OUT / 'phaseE.json').relative_to(ROOT)}")
    print("  validation: SYNTHETIC ONLY -- monitoring aid, not an enforcement trigger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
