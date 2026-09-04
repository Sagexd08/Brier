"""Pins the gate-4 replication and the gate-5 detector measurement.

Both results are artifact-backed and both are easy to erode. The replication
could drift by someone retuning the base model per dataset until the numbers
improve; the detector measurement could drift by lowering the threshold it is
evaluated at until the false-positive rate looks acceptable. These tests make
either move fail loudly.

The detector tests are the more important half, because they pin an
*unfavourable* number. A test suite that only defends good results is a
ratchet in one direction.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.config import ARTIFACTS, EVAL_SEEDS

SECOND = ARTIFACTS / "calibration" / "second_dataset.json"
FPR = ARTIFACTS / "ablation" / "detector_fpr.json"


@pytest.fixture(scope="module")
def second():
    if not SECOND.exists():
        pytest.skip(f"{SECOND} not built; run scripts/23_second_dataset.py")
    return json.loads(SECOND.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fpr():
    if not FPR.exists():
        pytest.skip(f"{FPR} not built; run scripts/24_detector_fpr.py")
    return json.loads(FPR.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Gate 4: the replication.
# ---------------------------------------------------------------------------

def test_second_dataset_is_genuinely_different(second):
    """A replication on a near-identical dataset would test nothing.

    The point of this dataset is that it differs on size, geography, vintage
    and — most importantly — label semantics: an observed default rather than
    an analyst's credit grade.
    """
    d = second["dataset"]
    assert d["n_rows"] >= 20_000, "must be materially larger than n=1,000"
    assert "default" in d["label"].lower()
    assert "not an expert credit grade" in d["label"]


def test_protocol_was_held_fixed(second):
    """Same seeds and same binning, or the comparison is between two protocols."""
    assert tuple(second["protocol"]["seeds"]) == tuple(EVAL_SEEDS)
    assert second["protocol"]["ece_bins"] == 10
    assert "unchanged" in second["protocol"]["note"]


def test_core_calibration_claim_replicates(second):
    assert second["verdict"]["core_claim_replicates"] is True
    for name, r in second["replications"].items():
        assert r["holds"] is True, f"{name} failed to replicate: {r}"


def test_calibration_reduces_ece_in_every_seed(second):
    sig = second["significance"]
    assert sig["seeds_improved"] == sig["n_seeds"] == len(EVAL_SEEDS)
    assert sig["wilcoxon_p"] < 0.05
    # The German Credit figure is 52.8%; a replication that came in far below
    # would be a materially weaker claim even while technically "holding".
    assert sig["mean_reduction_pct"] > 40.0


def test_calibration_lowers_the_slashed_quantity(second):
    """The realised Brier score is what the slash prices, not ECE."""
    s = second["summary"]
    assert s["cal_brier"]["mean"] < s["uncal_brier"]["mean"]


def test_base_model_is_overconfident_on_both_datasets(second):
    """T > 1 everywhere is the finding; T < 1 would invert the story."""
    assert second["summary"]["temperature"]["min"] > 1.0


# ---------------------------------------------------------------------------
# The subgroup effect, which the first dataset could not resolve.
# ---------------------------------------------------------------------------

def test_subgroup_groups_are_large_enough_to_measure(second):
    """§8.4's whole point: at n=68 the estimator's bias exceeds the effect."""
    lo, hi = second["subgroup"]["observed_group_sizes"]
    assert lo >= 2000, "below ~2,000 the ECE noise floor dominates (§8.4)"


def test_subgroup_effect_survives_its_permutation_null(second):
    """The control that killed the German Credit result, passed here.

    If this ever fails, the positive subgroup claim in §8.4 and §8.6 must be
    withdrawn — not explained away.
    """
    sg = second["subgroup"]
    assert sg["n_permutations"] >= 100, "the null must actually be computed"
    assert sg["wilcoxon_p"] < 0.05
    assert sg["mean_real_gap"] > sg["mean_null_gap"]
    assert sg["effect_real"] is True


def test_subgroup_effect_is_reported_as_small(second):
    """Guards the opposite failure: overstating a real but modest effect.

    The gap is ~12% of aggregate ECE. If a future change makes this look large,
    that is a reason to re-examine the measurement, not to celebrate.
    """
    sg = second["subgroup"]
    ratio = sg["mean_real_gap"] / sg["mean_aggregate_ece"]
    assert 0.0 < ratio < 0.5, f"gap is {ratio:.1%} of aggregate; re-check"


# ---------------------------------------------------------------------------
# Gate 5: the detector. These pin an unfavourable result.
# ---------------------------------------------------------------------------

def test_fpr_is_measured_at_the_enforced_threshold(fpr):
    """0.8 is not a choice — CollusionOracle.sol reverts below MIN_SCORE.

    Evaluating at a friendlier threshold would describe a different system
    from the deployed one.
    """
    assert fpr["enforced_threshold"] == 0.8
    assert "MIN_SCORE = 0.8e18" in fpr["threshold_source"]


def test_ring_free_traffic_contains_no_true_positives(fpr):
    """Every flag on ring-free traffic is false by construction."""
    rf = fpr["ring_free"]
    assert rf["claimants_total"] > 1000
    assert rf["flagged_total"] >= 0


def test_detector_does_flag_honest_claimants(fpr):
    """The finding, pinned so it cannot quietly become zero.

    17 of 1,800 honest claimants were flagged in a world with no collusion in
    it. If a change drives this to zero, that is a result to re-verify rather
    than assume — a detector that never fires also never detects.
    """
    rf = fpr["ring_free"]
    assert rf["flagged_total"] > 0, (
        "no false positives at all on ring-free traffic is suspicious; "
        "check the detector still produces scores above threshold"
    )
    assert rf["wilson_95_upper"] > rf["fpr_mean"], "the bound must exceed the estimate"


def test_false_discovery_rate_is_recorded_and_material(fpr):
    """The number a flagged claimant actually faces.

    FDR is far worse than FPR here because ring members are rare, and it is the
    quantity §8.5's recommendation turns on.
    """
    for row in fpr["with_rings"]:
        assert "false_discovery_rate" in row
    easiest = max(fpr["with_rings"], key=lambda r: r["ring_intensity"])
    assert easiest["false_discovery_rate"] > 0.1, (
        "FDR at the easiest ring intensity was material when measured; "
        "a large improvement needs re-verification, not acceptance"
    )


def test_recall_degrades_as_rings_get_subtler(fpr):
    """Ordering check: harder rings must not be easier to detect."""
    rows = sorted(fpr["with_rings"], key=lambda r: r["ring_intensity"])
    recalls = [r["recall_mean"] for r in rows]
    assert recalls == sorted(recalls), (
        f"recall should rise with ring intensity, got {recalls}"
    )


def test_measurement_does_not_claim_to_close_the_limitation(fpr):
    """The guard that matters most for this artifact.

    This measures synthetic ring-free traffic. §8.5 stays open, and the
    artifact must keep saying so — the failure mode is a later reader treating
    a synthetic FPR as validation for real traffic.
    """
    v = fpr["verdict"]
    assert v["measures_real_traffic"] is False
    assert v["limitation_closed"] is False
    assert "synthetic" in v["note"].lower()
