"""Known-answer tests for the calibration metrics.

Every expected value here is computed by hand from the ECE definition, not
copied from a library run. Counts are chosen so that empirical frequencies are
exact (no rounding), which is what makes these known-answer rather than
approximate.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.metrics import (
    brier_score,
    expected_calibration_error,
    max_calibration_error,
    reliability_curve,
)


def test_ece_perfect_calibration_is_zero():
    probs = np.array([0.0] * 50 + [1.0] * 50)
    labels = np.array([0] * 50 + [1] * 50)
    assert expected_calibration_error(probs, labels) == pytest.approx(0.0)


def test_ece_maximally_overconfident_is_one():
    probs = np.ones(100)
    labels = np.zeros(100)
    assert expected_calibration_error(probs, labels) == pytest.approx(1.0)


def test_ece_single_bin_equals_absolute_gap():
    # 100 samples all at conf 0.8; exactly 60 positives -> freq 0.60.
    probs = np.full(100, 0.8)
    labels = np.array([1] * 60 + [0] * 40)
    assert expected_calibration_error(probs, labels) == pytest.approx(0.2)


def test_ece_is_weighted_by_bin_population():
    # Bin A: 90 samples, conf 0.85, exactly 63 positives -> freq 0.70, gap 0.15
    # Bin B: 10 samples, conf 0.15, exactly  6 positives -> freq 0.60, gap 0.45
    # ECE = 0.9*0.15 + 0.1*0.45 = 0.135 + 0.045 = 0.18
    probs = np.array([0.85] * 90 + [0.15] * 10)
    labels = np.array([1] * 63 + [0] * 27 + [1] * 6 + [0] * 4)
    assert expected_calibration_error(probs, labels) == pytest.approx(0.18)


def test_mce_reports_worst_bin_not_average():
    probs = np.array([0.85] * 90 + [0.15] * 10)
    labels = np.array([1] * 63 + [0] * 27 + [1] * 6 + [0] * 4)
    # Worst gap is bin B's 0.45, even though it holds only 10% of the mass.
    assert max_calibration_error(probs, labels) == pytest.approx(0.45)


def test_empty_bins_are_skipped_not_counted_as_perfect():
    # All mass in one bin; the other 9 bins are empty and must not dilute ECE.
    probs = np.full(20, 0.95)
    labels = np.zeros(20)
    assert expected_calibration_error(probs, labels) == pytest.approx(0.95)


def test_reliability_curve_bins_and_counts():
    probs = np.array([0.05, 0.15, 0.95])
    labels = np.array([0, 1, 1])
    rows = reliability_curve(probs, labels, n_bins=10)
    assert len(rows) == 10
    assert sum(r["count"] for r in rows) == 3
    assert rows[0]["count"] == 1 and rows[1]["count"] == 1 and rows[9]["count"] == 1
    # Empty bins carry None rather than a fabricated 0.0.
    assert rows[5]["mean_conf"] is None


def test_bin_edge_convention_is_right_closed():
    # p exactly on an interior edge (0.3) belongs to the LOWER bin.
    rows = reliability_curve(np.array([0.3]), np.array([1]), n_bins=10)
    assert rows[2]["count"] == 1
    assert rows[3]["count"] == 0


def test_brier_score_known_values():
    assert brier_score(np.full(100, 0.5), np.array([1] * 50 + [0] * 50)) == pytest.approx(0.25)
    assert brier_score(np.array([1.0, 0.0]), np.array([1, 0])) == pytest.approx(0.0)
    assert brier_score(np.array([1.0, 0.0]), np.array([0, 1])) == pytest.approx(1.0)


def test_rejects_out_of_range_probabilities():
    with pytest.raises(ValueError):
        expected_calibration_error(np.array([1.5]), np.array([1]))
    with pytest.raises(ValueError):
        expected_calibration_error(np.array([-0.1]), np.array([0]))


def test_rejects_mismatched_shapes():
    with pytest.raises(ValueError):
        expected_calibration_error(np.array([0.5, 0.5]), np.array([1]))
