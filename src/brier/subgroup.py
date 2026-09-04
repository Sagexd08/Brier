"""Within-group calibration error: the quantity aggregate ECE cannot see.

PROPOSAL.md 7.4 names this as the sharpest scientific gap in the v0 mechanism.
The slash is driven by realised Brier score and the calibration claim is
defended with aggregate ECE, but ECE is an average over the whole population,
and an average is exactly the wrong instrument for detecting a defect that is
confined to a subset. Two subgroups can be miscalibrated in opposite directions
and cancel: overconfident on one, underconfident on the other, aggregate ECE
near zero, and every individual in both groups mispriced.

This module implements the within-group variant and the gap between them. It
deliberately reuses `expected_calibration_error` from .metrics rather than
reimplementing the binning: Definition 2 in the proposal (10 equal-width bins,
population-weighted, empty bins skipped) must mean one thing everywhere, and a
second implementation is a second thing that can drift from the first.

WHAT THIS DOES NOT DO. Measuring subgroup calibration is not enforcing it.
Nothing here is wired to a slash, and the on-chain register that tracks these
scores (SubgroupReputationRegister) takes its subgroup id from the caller --
so the partition is asserted by the operator, not proved. An operator free to
choose its own partition can choose one on which it looks calibrated. See that
contract's header; the honest scope is "makes a specific miscalibration
visible to an auditor who already knows which partition to ask about", not
"prevents subgroup miscalibration".
"""
from __future__ import annotations

import numpy as np

from .config import ECE_BINS
from .metrics import expected_calibration_error


def group_ece(probs, labels, groups, n_bins: int = ECE_BINS, min_size: int = 1):
    """ECE computed separately within each subgroup.

    Returns {group_value: {"ece": float, "n": int, "mean_prob": float,
    "base_rate": float}}.

    Groups smaller than `min_size` are omitted. Binned calibration on a handful
    of points is dominated by binning noise, and reporting it as a per-group ECE
    invites reading noise as evidence. The omission is explicit in the returned
    keys rather than silent: callers can compare against the group counts.
    """
    probs = np.asarray(probs, dtype=float).ravel()
    labels = np.asarray(labels, dtype=float).ravel()
    groups = np.asarray(groups).ravel()
    if not (probs.shape == labels.shape == groups.shape):
        raise ValueError("probs, labels and groups must have the same shape")

    out = {}
    for g in np.unique(groups):
        mask = groups == g
        n_g = int(mask.sum())
        if n_g < min_size:
            continue
        out[g.item() if hasattr(g, "item") else g] = {
            "ece": float(expected_calibration_error(probs[mask], labels[mask], n_bins)),
            "n": n_g,
            "mean_prob": float(probs[mask].mean()),
            "base_rate": float(labels[mask].mean()),
        }
    return out


def worst_group_ece(probs, labels, groups, n_bins: int = ECE_BINS, min_size: int = 1):
    """The largest within-group ECE, and which group attains it.

    This is the quantity a mechanism should slash on if it wants to be robust
    to subgroup miscalibration: an operator is only as calibrated as its worst
    subgroup. Returns (ece, group). Returns (nan, None) when no group clears
    `min_size` -- an absent measurement, never a passing one.
    """
    per = group_ece(probs, labels, groups, n_bins, min_size)
    if not per:
        return float("nan"), None
    g = max(per, key=lambda k: per[k]["ece"])
    return per[g]["ece"], g


def weighted_group_ece(probs, labels, groups, n_bins: int = ECE_BINS, min_size: int = 1):
    """Population-weighted mean of within-group ECEs.

    Note what this is NOT: it is not aggregate ECE. Aggregate ECE bins the whole
    population together, so within-bin cancellation across groups is invisible
    to it. This bins each group separately and only then averages, so a group
    that is overconfident and a group that is underconfident both contribute
    their absolute error instead of netting out. The gap between this and
    aggregate ECE is precisely the cancellation, which is what
    `calibration_gap` reports.
    """
    per = group_ece(probs, labels, groups, n_bins, min_size)
    if not per:
        return float("nan")
    total = sum(v["n"] for v in per.values())
    return float(sum(v["ece"] * v["n"] for v in per.values()) / total)


def calibration_gap(probs, labels, groups, n_bins: int = ECE_BINS, min_size: int = 1):
    """How much subgroup miscalibration the aggregate number hides.

    Returns a dict with the aggregate ECE, the population-weighted within-group
    ECE, the worst group's ECE, and the two gaps. A large `worst_gap` with a
    small `aggregate` is the adversarial case: a model that passes an
    aggregate-ECE check while being materially miscalibrated on an identifiable
    subgroup.
    """
    agg = float(expected_calibration_error(probs, labels, n_bins))
    weighted = weighted_group_ece(probs, labels, groups, n_bins, min_size)
    worst, worst_group = worst_group_ece(probs, labels, groups, n_bins, min_size)
    return {
        "aggregate_ece": agg,
        "weighted_group_ece": weighted,
        "worst_group_ece": worst,
        "worst_group": worst_group,
        # Positive means the aggregate understates the true miscalibration.
        "weighted_gap": weighted - agg,
        "worst_gap": worst - agg,
        "per_group": group_ece(probs, labels, groups, n_bins, min_size),
    }
