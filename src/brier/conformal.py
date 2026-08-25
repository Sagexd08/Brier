"""Phase B: split conformal prediction.

Temperature scaling produces a point confidence with no guarantee attached.
Split conformal produces a *set* with a distribution-free marginal coverage
guarantee: over the randomness of the calibration and test draw, the true label
lands in the set at least 1-alpha of the time, with no assumption about the
model being correct, well specified, or even sensible. That is a strictly
stronger uncertainty claim than a calibrated scalar, and it is the reason this
phase was worth attempting.

Two properties of the guarantee are easy to overstate, so they are stated here:

  * It is **marginal**, not conditional. Coverage holds on average over the
    population, not within any particular subgroup. A conformal predictor can
    hit 90% overall while covering one subgroup at 60%. This is precisely the
    limitation already noted for aggregate ECE, and conformal does not fix it.
  * It requires **exchangeability** between the calibration and test draw.
    Under distribution shift the guarantee lapses, silently.

The calibration set is split in half: one half fits the temperature, the other
computes the conformal quantile. Reusing one split for both would break the
exchangeability argument, because the scores would no longer be drawn
independently of the fitted head.
"""
from __future__ import annotations

import numpy as np


def nonconformity(probs_positive: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Score of the TRUE label: 1 - p(true class). Higher = more surprising."""
    probs_positive = np.asarray(probs_positive, dtype=float).ravel()
    labels = np.asarray(labels, dtype=int).ravel()
    p_true = np.where(labels == 1, probs_positive, 1.0 - probs_positive)
    return 1.0 - p_true


def conformal_quantile(scores: np.ndarray, alpha: float = 0.1) -> float:
    """The finite-sample-corrected (1-alpha) quantile of calibration scores.

    The correction is ceil((n+1)(1-alpha))/n rather than a plain empirical
    quantile. Without it the guarantee is only asymptotic; with it, coverage is
    at least 1-alpha for every finite n. On a 100-point calibration half this
    is not a rounding detail -- it is the difference between a theorem and a
    hope.
    """
    scores = np.sort(np.asarray(scores, dtype=float).ravel())
    n = scores.size
    if n == 0:
        raise ValueError("no calibration scores")
    k = int(np.ceil((n + 1) * (1.0 - alpha)))
    if k > n:
        # Too few points to certify this alpha at all; the honest answer is a
        # vacuous set rather than a quantile that cannot support the claim.
        return 1.0
    return float(scores[k - 1])


def prediction_sets(probs_positive: np.ndarray, q: float) -> np.ndarray:
    """Boolean [n, 2] membership matrix for classes {0, 1}.

    A row may hold two members (the model is unsure and says so), one member
    (a confident call), or none. The empty set is not a failure mode to be
    suppressed: it means every label was more surprising than the calibration
    quantile allows, and it is the honest output when the model is confidently
    wrong about a point it has never seen the like of.
    """
    p = np.asarray(probs_positive, dtype=float).ravel()
    include_1 = (1.0 - p) <= q
    include_0 = p <= q
    return np.stack([include_0, include_1], axis=1)


def coverage(sets: np.ndarray, labels: np.ndarray) -> float:
    """Fraction of points whose true label is in the predicted set."""
    labels = np.asarray(labels, dtype=int).ravel()
    return float(sets[np.arange(len(labels)), labels].mean())


def average_set_size(sets: np.ndarray) -> float:
    """Mean cardinality. This is the efficiency side of the tradeoff.

    Coverage alone is trivially satisfiable -- always return {0,1} and you have
    100% coverage and zero information. Set size is what makes the guarantee
    mean something, so the two are always reported together.
    """
    return float(sets.sum(axis=1).mean())


def set_size_distribution(sets: np.ndarray) -> dict[int, float]:
    sizes = sets.sum(axis=1)
    return {int(k): float((sizes == k).mean()) for k in (0, 1, 2)}


def split_calibration(n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Halve the calibration split: one half for the head, one for conformal."""
    rng = np.random.default_rng(seed)
    idx = rng.permutation(n)
    half = n // 2
    return idx[:half], idx[half:]
