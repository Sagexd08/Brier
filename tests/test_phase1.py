"""Phase 1 correctness tests: split disjointness, calibration behaviour, guards.

These encode the properties that make the ECE result trustworthy, not the ECE
value itself (which is data-dependent and lives in RESULTS.md).
"""
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.config import PROTECTED_COLUMNS
from brier.data import load_frame, split_three_way
from brier.models import (
    MLPCalibrationHead,
    TemperatureScaler,
    apply_head,
    fit_calibration_head,
)


@pytest.fixture(scope="module")
def splits():
    return split_three_way(load_frame())


def test_splits_are_mutually_disjoint(splits):
    """The whole calibration argument collapses if these overlap."""
    frames = {k: splits[k][0] for k in ("train", "calib", "test")}
    # Reconstruct identity by row content hash, since indices were reset.
    sigs = {k: {tuple(r) for r in v.to_numpy().tolist()} for k, v in frames.items()}
    assert not (sigs["train"] & sigs["calib"])
    assert not (sigs["train"] & sigs["test"])
    assert not (sigs["calib"] & sigs["test"])


def test_split_sizes_and_stratification(splits):
    assert len(splits["train"][1]) == 600
    assert len(splits["calib"][1]) == 200
    assert len(splits["test"][1]) == 200
    # Stratified: every split carries the population reject rate.
    for k in ("train", "calib", "test"):
        assert splits[k][1].mean() == pytest.approx(0.30, abs=0.01)


def test_protected_attribute_is_excluded(splits):
    for col in PROTECTED_COLUMNS:
        assert col not in splits["feature_names"]


def test_temperature_head_has_exactly_one_parameter():
    assert sum(p.numel() for p in TemperatureScaler().parameters()) == 1


def test_mlp_head_stays_under_circuit_budget():
    """Circuit feasibility depends on this staying small."""
    assert MLPCalibrationHead(16).n_parameters() == 321
    assert MLPCalibrationHead(16).n_parameters() < 10_000


def test_temperature_above_one_softens_confidence():
    """T>1 must move probabilities toward 0.5, T<1 away from it."""
    head = TemperatureScaler()
    with torch.no_grad():
        head.log_temperature.fill_(float(np.log(3.0)))
    margins = np.array([4.0, -4.0])
    p = apply_head(head, margins)
    raw = 1.0 / (1.0 + np.exp(-margins))
    assert abs(p[0] - 0.5) < abs(raw[0] - 0.5)
    assert abs(p[1] - 0.5) < abs(raw[1] - 0.5)


def test_fit_recovers_known_temperature():
    """Known-answer: data generated at T=2 should fit back to about T=2."""
    rng = np.random.default_rng(0)
    true_t = 2.0
    margins = rng.normal(0, 4, size=4000)
    probs = 1.0 / (1.0 + np.exp(-margins / true_t))
    labels = (rng.random(4000) < probs).astype(int)
    head, _ = fit_calibration_head(TemperatureScaler(), margins, labels)
    assert head.temperature == pytest.approx(true_t, rel=0.15)


def test_fit_rejects_diverged_loss():
    """A nan fit must raise, never silently return a broken head."""
    with pytest.raises(RuntimeError):
        fit_calibration_head(
            MLPCalibrationHead(16), np.array([np.nan, 1.0, 2.0]), np.array([0, 1, 0])
        )


def test_fit_returns_finite_loss_on_real_margins(splits):
    rng = np.random.default_rng(1)
    margins = rng.normal(-3, 4, size=200)
    labels = (rng.random(200) < 1 / (1 + np.exp(-margins))).astype(int)
    for head in (TemperatureScaler(), MLPCalibrationHead(16)):
        _, loss = fit_calibration_head(head, margins, labels)
        assert np.isfinite(loss)


def test_calibrated_outputs_are_valid_probabilities():
    rng = np.random.default_rng(2)
    margins = rng.normal(0, 5, size=300)
    labels = (rng.random(300) < 0.4).astype(int)
    head, _ = fit_calibration_head(TemperatureScaler(), margins, labels)
    p = apply_head(head, margins)
    assert np.all(p >= 0.0) and np.all(p <= 1.0)
    assert np.all(np.isfinite(p))
