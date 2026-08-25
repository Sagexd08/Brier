"""Phase B: split conformal prediction.

The coverage guarantee is the only reason this phase exists, so the tests
target the guarantee's machinery rather than the happy path: the finite-sample
quantile correction, the coverage/efficiency tradeoff, and the degenerate cases
where the honest answer is a vacuous set.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.conformal import (
    average_set_size,
    conformal_quantile,
    coverage,
    nonconformity,
    prediction_sets,
    set_size_distribution,
    split_calibration,
)


def test_nonconformity_is_one_minus_true_class_probability():
    probs = np.array([0.9, 0.9, 0.2, 0.2])
    labels = np.array([1, 0, 1, 0])
    got = nonconformity(probs, labels)
    np.testing.assert_allclose(got, [0.1, 0.9, 0.8, 0.2])


def test_quantile_uses_finite_sample_correction_not_plain_quantile():
    """ceil((n+1)(1-alpha))/n, not np.quantile.

    With n=10 and alpha=0.1, k = ceil(11*0.9) = ceil(9.9) = 10, so the
    quantile is the LARGEST score. A plain 90th-percentile would return
    something smaller and would not support the finite-sample guarantee.
    """
    scores = np.linspace(0.0, 1.0, 10)
    assert conformal_quantile(scores, alpha=0.1) == pytest.approx(scores.max())
    # np.quantile would give a strictly smaller value here.
    assert np.quantile(scores, 0.9) < scores.max()


def test_quantile_is_vacuous_when_n_too_small_for_alpha():
    """n=5 cannot certify alpha=0.05: k = ceil(6*0.95) = 6 > 5.

    Returning 1.0 makes every set contain both labels, which is honest --
    the procedure cannot support the requested level, so it declines to
    exclude anything rather than silently returning a quantile that does
    not carry the guarantee.
    """
    assert conformal_quantile(np.linspace(0, 1, 5), alpha=0.05) == 1.0


def test_quantile_rejects_empty_input():
    with pytest.raises(ValueError):
        conformal_quantile(np.array([]))


def test_prediction_sets_can_be_empty_singleton_or_full():
    # q = 0.3: include_1 iff p >= 0.7, include_0 iff p <= 0.3
    sets = prediction_sets(np.array([0.95, 0.5, 0.05]), q=0.3)
    assert sets[0].tolist() == [False, True]    # confident reject
    assert sets[1].tolist() == [False, False]   # empty: nothing is plausible
    assert sets[2].tolist() == [True, False]    # confident accept


def test_full_set_when_quantile_is_one():
    sets = prediction_sets(np.array([0.01, 0.5, 0.99]), q=1.0)
    assert sets.all(), "a vacuous quantile must include every label"
    assert average_set_size(sets) == 2.0


def test_coverage_counts_the_true_label_only():
    sets = np.array([[True, False], [False, True], [True, True], [False, False]])
    labels = np.array([0, 0, 1, 1])
    # hit, miss, hit, miss
    assert coverage(sets, labels) == pytest.approx(0.5)


def test_size_distribution_sums_to_one():
    sets = prediction_sets(np.array([0.95, 0.5, 0.05, 0.5]), q=0.3)
    dist = set_size_distribution(sets)
    assert sum(dist.values()) == pytest.approx(1.0)


def test_calibration_halves_are_disjoint_and_cover_everything():
    a, b = split_calibration(101, seed=42)
    assert not (set(a.tolist()) & set(b.tolist()))
    assert sorted(a.tolist() + b.tolist()) == list(range(101))


def test_calibration_split_is_deterministic_for_a_seed():
    a1, b1 = split_calibration(50, seed=7)
    a2, b2 = split_calibration(50, seed=7)
    np.testing.assert_array_equal(a1, a2)
    np.testing.assert_array_equal(b1, b2)


def test_coverage_guarantee_holds_on_synthetic_exchangeable_data():
    """The theorem, checked on data that actually satisfies its assumption.

    The Phase B script measures coverage on the real split, where stratified
    sampling mildly breaks exchangeability. Here the draw is genuinely iid, so
    coverage should meet the target -- if it fails here, the implementation is
    wrong rather than the data being awkward.
    """
    rng = np.random.default_rng(0)
    alpha = 0.1
    hits = []
    for _ in range(300):
        p_true = rng.uniform(0.05, 0.95, size=400)
        labels = (rng.uniform(size=400) < p_true).astype(int)
        # A well-specified forecaster: reported probability IS the true one.
        cal, test = slice(0, 200), slice(200, 400)
        q = conformal_quantile(nonconformity(p_true[cal], labels[cal]), alpha=alpha)
        sets = prediction_sets(p_true[test], q)
        hits.append(coverage(sets, labels[test]))
    assert np.mean(hits) >= 1.0 - alpha, (
        f"marginal coverage {np.mean(hits):.4f} below target {1 - alpha}"
    )


def test_smaller_alpha_never_yields_smaller_sets():
    """Efficiency must move monotonically with the level, or the quantile is wrong."""
    rng = np.random.default_rng(3)
    p = rng.uniform(0.02, 0.98, size=300)
    labels = (rng.uniform(size=300) < p).astype(int)
    scores = nonconformity(p, labels)

    sizes = []
    for alpha in (0.30, 0.20, 0.10, 0.05):
        q = conformal_quantile(scores, alpha=alpha)
        sizes.append(average_set_size(prediction_sets(p, q)))
    assert sizes == sorted(sizes), f"set size must not shrink as alpha falls: {sizes}"
