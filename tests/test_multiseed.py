"""Phase 1 (research pass): tests over the multi-seed evaluation.

These assert properties of the committed multi-seed report. They are the
mechanism that stops a headline statistic from drifting away from the data:
if a claim in README/PROPOSAL stops holding across seeds, a test here fails.

Run `make research-eval` (or scripts/12_multiseed_eval.py) to regenerate the
report before running these.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brier.config import EVAL_SEEDS

REPORT = ROOT / "artifacts" / "calibration" / "multiseed_report.json"


@pytest.fixture(scope="module")
def report():
    if not REPORT.exists():
        pytest.skip("multiseed_report.json absent; run scripts/12_multiseed_eval.py")
    return json.loads(REPORT.read_text())


def test_all_pinned_seeds_were_run(report):
    """No seed may be dropped from the reported set."""
    assert report["seeds"] == list(EVAL_SEEDS)
    assert len(report["runs"]) == len(EVAL_SEEDS)
    assert {r["seed"] for r in report["runs"]} == set(EVAL_SEEDS)


def test_at_least_ten_seeds(report):
    assert report["n_seeds"] >= 10


def test_calibration_reduces_ece_in_every_seed(report):
    """The core premise. If this fails in any seed, the thesis is weaker
    than stated and the README must say so."""
    for r in report["runs"]:
        assert r["ece"]["temperature"] < r["ece"]["uncalibrated"], (
            f"seed {r['seed']}: temperature scaling did not reduce ECE"
        )


def test_fitting_on_train_is_worse_than_not_calibrating(report):
    """The leakage control, across seeds rather than anecdotally."""
    n = sum(
        1 for r in report["runs"]
        if r["ece"]["control_fitted_on_train"] > r["ece"]["uncalibrated"]
    )
    assert n == len(report["runs"]), (
        f"control was worse than uncalibrated in only {n}/{len(report['runs'])} seeds"
    )
    t = report["significance"]["control_vs_uncalibrated_ece"]
    assert t["p_value"] < 0.05
    assert t["median_difference"] > 0


def test_learned_temperature_always_exceeds_one(report):
    """T > 1 means the base model needed softening. If a seed produced T < 1
    the 'deliberately overconfident' framing would not hold there."""
    for r in report["runs"]:
        assert r["temperature"] > 1.0, f"seed {r['seed']}: T={r['temperature']}"


def test_temperature_beats_mlp_claim_matches_reported_strength(report):
    """v0 asserted this from a single run. Across seeds it holds, but NOT
    unanimously -- this test pins the actual strength so the prose cannot
    quietly upgrade it to 'always'."""
    t = report["significance"]["temperature_vs_mlp_ece"]
    wins = report["temperature_beats_mlp_on_ece_in_n_seeds"]
    n = report["n_seeds"]

    # Significant at alpha=0.05 in the stated direction ...
    assert t["p_value"] < 0.05
    assert t["median_difference"] < 0
    # ... but strictly not unanimous. If this ever becomes n/n, the docs
    # should be updated to say so, and this assertion revisited.
    assert wins < n, (
        "temperature now wins in every seed; the README wording "
        "('wins in most seeds') understates the result and should be updated"
    )
    assert wins >= (n // 2) + 1, "claimed majority no longer holds"


def test_reported_summary_matches_raw_runs(report):
    """Guard against a hand-edited summary block."""
    for metric in ("ece", "brier"):
        for key in report["summary"][metric]:
            vals = [r[metric][key] for r in report["runs"]]
            assert report["summary"][metric][key]["mean"] == pytest.approx(
                float(np.mean(vals)), rel=1e-9
            )
            assert report["summary"][metric][key]["n"] == len(vals)


def test_seed_42_is_not_the_most_flattering_seed(report):
    """Cherry-picking check, mechanised.

    v0 published seed 42 alone. This asserts that seed 42 is not the seed
    with the largest ECE reduction, i.e. the single-seed result was not
    selected to look good.
    """
    reductions = {
        r["seed"]: 1.0 - r["ece"]["temperature"] / r["ece"]["uncalibrated"]
        for r in report["runs"]
    }
    best = max(reductions, key=reductions.get)
    assert best != 42, (
        "seed 42 has the largest reduction of all seeds; publishing it alone "
        "would be cherry-picking"
    )
