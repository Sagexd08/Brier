"""Phase A: the deep tabular base model and the heterogeneous ensemble.

The ablation result for this phase is null -- the ensemble does not
significantly improve calibration and costs accuracy. These tests therefore
guard the two things that would make that null result untrustworthy: that the
ensemble combines correctly, and that nothing in Phase A widened the proved
surface.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.deep import _logit, _sigmoid, _embed_dim, ensemble_margins, split_columns
from brier.data import NUMERIC_COLUMNS


def test_split_columns_partitions_every_feature_exactly_once():
    names = list(NUMERIC_COLUMNS) + ["checking_status", "purpose", "job"]
    cat, num = split_columns(names)
    assert sorted(cat + num) == sorted(names)
    assert not (set(cat) & set(num))
    assert set(num) == set(NUMERIC_COLUMNS)


def test_purpose_is_treated_as_categorical():
    """`purpose` is 10 unordered codes. Feeding it to a linear layer as an
    integer would assert an ordering that does not exist."""
    cat, num = split_columns(["purpose", "age_years"])
    assert "purpose" in cat and "purpose" not in num


def test_embed_dim_is_clamped_both_ends():
    assert _embed_dim(2) == 2          # floor
    assert _embed_dim(100) == 8        # ceiling
    assert 2 <= _embed_dim(10) <= 8


def test_sigmoid_logit_roundtrip():
    z = np.array([-8.0, -1.0, 0.0, 1.0, 8.0])
    np.testing.assert_allclose(_logit(_sigmoid(z)), z, atol=1e-4)


def test_sigmoid_does_not_overflow_on_extreme_margins():
    out = _sigmoid(np.array([-1e6, 1e6]))
    assert np.all(np.isfinite(out))
    assert out[0] == pytest.approx(0.0, abs=1e-12)
    assert out[1] == pytest.approx(1.0, abs=1e-12)


def test_ensemble_averages_in_probability_space_not_logit_space():
    """The distinguishing case: one model is confidently wrong.

    Averaging logits lets the extreme margin dominate, because logit space is
    unbounded. Averaging probabilities bounds each vote to [0,1]. With margins
    -20 and +2 the probability average is ~0.44 (logit ~ -0.25), whereas the
    logit average would be -9, i.e. essentially certain.
    """
    got = ensemble_margins(np.array([-20.0]), np.array([2.0]))
    logit_space_average = -9.0
    assert got[0] > logit_space_average + 5, "extreme margin must not dominate"
    assert _sigmoid(got)[0] == pytest.approx(
        0.5 * (_sigmoid(np.array([-20.0]))[0] + _sigmoid(np.array([2.0]))[0]), abs=1e-6
    )


def test_ensemble_is_symmetric_at_equal_weight():
    a, b = np.array([1.5]), np.array([-0.4])
    np.testing.assert_allclose(ensemble_margins(a, b), ensemble_margins(b, a), atol=1e-9)


def test_ensemble_of_identical_models_is_the_identity():
    m = np.array([-3.0, 0.0, 2.5])
    np.testing.assert_allclose(ensemble_margins(m, m), m, atol=1e-4)


def test_ensemble_weight_shifts_toward_the_weighted_member():
    a, b = np.array([4.0]), np.array([-4.0])
    assert ensemble_margins(a, b, weight=0.9)[0] > ensemble_margins(a, b, weight=0.5)[0]


def test_ensemble_output_is_a_scalar_margin_per_row():
    """Phase A must not widen the proved surface.

    The calibration head -- the only thing in the circuit -- consumes one
    scalar per decision. However elaborate the base model becomes, the
    interface it hands downstream has to stay exactly this shape.
    """
    out = ensemble_margins(np.zeros(17), np.ones(17))
    assert out.shape == (17,)
    assert out.dtype == np.float64
