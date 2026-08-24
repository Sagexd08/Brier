"""Calibration metrics.

ECE is the headline metric for this project, so it is implemented explicitly
rather than pulled from a library: the definition (bin count, weighting,
bin-edge convention) is exactly the thing a reviewer needs to audit.
"""
from __future__ import annotations

import numpy as np

from .config import ECE_BINS


def expected_calibration_error(probs, labels, n_bins: int = ECE_BINS):
    """Equal-width binned ECE, weighted by bin population.

        ECE = sum_b (n_b / N) * | acc(b) - conf(b) |

    `probs` are predicted probabilities of the POSITIVE class and `labels` the
    corresponding 0/1 outcomes. Bins partition [0,1] into `n_bins` equal-width
    intervals, left-open/right-closed except the first bin which includes 0.
    Empty bins contribute zero weight (they are skipped, not counted as
    perfectly calibrated).
    """
    probs = np.asarray(probs, dtype=float).ravel()
    labels = np.asarray(labels, dtype=float).ravel()
    if probs.shape != labels.shape:
        raise ValueError("probs and labels must have the same shape")
    if probs.size == 0:
        raise ValueError("empty input")
    if np.any(probs < 0) or np.any(probs > 1):
        raise ValueError("probs must lie in [0,1]")

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    # np.digitize with right=True puts p in bin b when edges[b-1] < p <= edges[b].
    bin_ids = np.digitize(probs, edges[1:-1], right=True)

    n = probs.size
    ece = 0.0
    for b in range(n_bins):
        mask = bin_ids == b
        n_b = int(mask.sum())
        if n_b == 0:
            continue                      # empty bin contributes no weight
        acc_b = labels[mask].mean()       # empirical frequency
        conf_b = probs[mask].mean()       # mean predicted confidence
        ece += (n_b / n) * abs(acc_b - conf_b)
    return float(ece)


def reliability_curve(probs, labels, n_bins: int = ECE_BINS):
    """Per-bin (mean confidence, empirical accuracy, count) for plotting."""
    probs = np.asarray(probs, dtype=float).ravel()
    labels = np.asarray(labels, dtype=float).ravel()
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_ids = np.digitize(probs, edges[1:-1], right=True)

    rows = []
    for b in range(n_bins):
        mask = bin_ids == b
        n_b = int(mask.sum())
        rows.append({
            "bin_lo": float(edges[b]),
            "bin_hi": float(edges[b + 1]),
            "count": n_b,
            "mean_conf": float(probs[mask].mean()) if n_b else None,
            "empirical_freq": float(labels[mask].mean()) if n_b else None,
        })
    return rows


def brier_score(probs, labels):
    """Mean squared error of probabilistic forecasts. Strictly proper."""
    probs = np.asarray(probs, dtype=float).ravel()
    labels = np.asarray(labels, dtype=float).ravel()
    return float(np.mean((probs - labels) ** 2))


def max_calibration_error(probs, labels, n_bins: int = ECE_BINS):
    """Worst-case gap over non-empty bins."""
    rows = reliability_curve(probs, labels, n_bins)
    gaps = [abs(r["empirical_freq"] - r["mean_conf"]) for r in rows if r["count"] > 0]
    return float(max(gaps)) if gaps else 0.0
