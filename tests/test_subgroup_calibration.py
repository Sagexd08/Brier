"""Known-answer tests for within-group calibration, and a pin on the negative
result from scripts/21_subgroup_adversary.py.

Two kinds of test here, and the distinction matters.

The first block is hand-computed known-answer tests of the subgroup metrics,
in the style of test_metrics.py: counts chosen so empirical frequencies are
exact, expected values derived from the ECE definition rather than copied from
a run.

The second block pins the ARTIFACT. Task 3a produced a null result -- the
subgroup gap on this dataset is indistinguishable from a random partition --
and that null is what blocks the on-chain half of the task. A null finding is
easy to erode later: shrink the minimum group size, drop the permutation
control, and something will eventually look significant. These tests make that
erosion fail loudly instead of silently, which is the only reason a negative
result stays honest over time.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.config import CALIB
from brier.metrics import expected_calibration_error
from brier.subgroup import calibration_gap, group_ece, weighted_group_ece, worst_group_ece

ARTIFACT = CALIB / "subgroup_adversary.json"


# ---------------------------------------------------------------------------
# Known-answer: the metrics themselves.
# ---------------------------------------------------------------------------

def test_group_ece_splits_the_population():
    # Group A: 100 at conf 0.8, exactly 60 positives -> freq 0.60, ECE 0.20.
    # Group B: 100 at conf 0.3, exactly 30 positives -> freq 0.30, ECE 0.00.
    probs = np.concatenate([np.full(100, 0.8), np.full(100, 0.3)])
    labels = np.concatenate([np.array([1] * 60 + [0] * 40),
                             np.array([1] * 30 + [0] * 70)])
    groups = np.array(["A"] * 100 + ["B"] * 100)

    per = group_ece(probs, labels, groups)
    assert per["A"]["ece"] == pytest.approx(0.20)
    assert per["B"]["ece"] == pytest.approx(0.00)
    assert per["A"]["n"] == 100 and per["B"]["n"] == 100


def test_aggregate_ece_hides_cancelling_subgroups():
    """The failure mode 7.4 names, constructed exactly.

    Both groups sit in the SAME confidence bin (0.5-0.6), so the aggregate
    pools them: group A is 20 points overconfident, group B is 20 points
    underconfident, and the pooled frequency lands exactly on the pooled
    confidence. Aggregate ECE is 0; each group's own ECE is 0.20.
    """
    probs = np.full(200, 0.55)
    # A: 35/100 positive (freq 0.35, conf 0.55 -> gap 0.20 overconfident)
    # B: 75/100 positive (freq 0.75, conf 0.55 -> gap 0.20 underconfident)
    labels = np.concatenate([np.array([1] * 35 + [0] * 65),
                             np.array([1] * 75 + [0] * 25)])
    groups = np.array(["A"] * 100 + ["B"] * 100)

    # Pooled: 110/200 = 0.55 exactly. The aggregate check sees nothing.
    assert expected_calibration_error(probs, labels) == pytest.approx(0.0)

    gap = calibration_gap(probs, labels, groups)
    assert gap["aggregate_ece"] == pytest.approx(0.0)
    assert gap["worst_group_ece"] == pytest.approx(0.20)
    assert gap["weighted_group_ece"] == pytest.approx(0.20)
    # This is the whole point: the aggregate understates by the full amount.
    assert gap["worst_gap"] == pytest.approx(0.20)


def test_weighted_group_ece_weights_by_population():
    # A: 150 at conf 0.8, 90 positives  -> freq 0.60, ECE 0.20
    # B:  50 at conf 0.2, 10 positives  -> freq 0.20, ECE 0.00
    # weighted = (150*0.20 + 50*0.00) / 200 = 0.15
    probs = np.concatenate([np.full(150, 0.8), np.full(50, 0.2)])
    labels = np.concatenate([np.array([1] * 90 + [0] * 60),
                             np.array([1] * 10 + [0] * 40)])
    groups = np.array(["A"] * 150 + ["B"] * 50)
    assert weighted_group_ece(probs, labels, groups) == pytest.approx(0.15)


def test_worst_group_ece_reports_which_group():
    probs = np.concatenate([np.full(100, 0.9), np.full(100, 0.5)])
    labels = np.concatenate([np.array([1] * 50 + [0] * 50),   # freq .50, ECE .40
                             np.array([1] * 50 + [0] * 50)])  # freq .50, ECE .00
    groups = np.array(["bad"] * 100 + ["ok"] * 100)
    ece, g = worst_group_ece(probs, labels, groups)
    assert ece == pytest.approx(0.40)
    assert g == "bad"


def test_small_groups_are_omitted_not_silently_passed():
    """A group below min_size must vanish from the result, not score 0.

    Scoring an unmeasurable group as well-calibrated is the failure that would
    make a subgroup gate dangerous: an operator could shard its worst subgroup
    into fragments too small to measure and score perfectly on all of them.
    """
    probs = np.concatenate([np.full(100, 0.8), np.full(5, 1.0)])
    labels = np.concatenate([np.array([1] * 80 + [0] * 20), np.zeros(5)])
    groups = np.array(["big"] * 100 + ["tiny"] * 5)

    per = group_ece(probs, labels, groups, min_size=30)
    assert "tiny" not in per, "an unmeasurable group must be absent, not scored"
    assert "big" in per

    # And when EVERY group is below the threshold, the result is nan -- an
    # absent measurement, never a passing one. Each group here holds 5.
    shards = np.array([f"shard{i // 5}" for i in range(105)])
    ece, g = worst_group_ece(probs, labels, shards, min_size=30)
    assert np.isnan(ece) and g is None


def test_group_ece_matches_aggregate_when_there_is_one_group():
    rng = np.random.default_rng(0)
    probs = rng.uniform(0, 1, 300)
    labels = (rng.uniform(0, 1, 300) < probs).astype(int)
    groups = np.zeros(300, dtype=int)
    per = group_ece(probs, labels, groups)
    assert per[0]["ece"] == pytest.approx(expected_calibration_error(probs, labels))


# ---------------------------------------------------------------------------
# The artifact: pinning the negative result so it cannot erode quietly.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def artifact():
    if not ARTIFACT.exists():
        pytest.skip(f"{ARTIFACT} not built; run scripts/21_subgroup_adversary.py")
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_artifact_records_a_negative_result(artifact):
    v = artifact["verdict"]
    assert v["effect_demonstrated"] is False
    assert v["task_3b_built"] is False
    assert v["reason"]


def test_gap_does_not_beat_the_permutation_null(artifact):
    """The finding: a random partition reproduces the whole effect.

    If a future change makes this pass, the subgroup claim becomes defensible
    and Task 3b unblocks -- but that must be a deliberate, re-measured decision,
    not something that drifts in unnoticed.
    """
    s = artifact["summary"]
    assert s["wilcoxon_p"] > 0.05, (
        "the subgroup gap now beats its permutation null; re-run the analysis "
        "and revisit Task 3b deliberately rather than assuming this test is stale"
    )
    assert s["seeds_beating_null"] <= len(artifact["seeds"]) // 2


def test_noise_floor_exceeds_aggregate_ece_at_subgroup_sizes(artifact):
    """Why the measurement cannot resolve the question either way.

    A perfectly calibrated model scores ECE ~0.119 at n=68 from binning alone.
    The pipeline's aggregate ECE is ~0.087. The estimator's own bias at
    subgroup sizes is larger than the entire quantity being measured.
    """
    floor = artifact["ece_noise_floor"]
    assert floor["68"]["mean"] > artifact["summary"]["mean_aggregate_ece"]
    # And the bias must fall monotonically with n -- that is what identifies it
    # as a small-sample artifact rather than a property of the model.
    means = [floor[str(n)]["mean"] for n in (68, 106, 200, 500, 2000, 10000)]
    assert means == sorted(means, reverse=True)


def test_smallest_measured_group_is_genuinely_small(artifact):
    """Guards the other erosion path: shrinking MIN_GROUP until a gap appears.

    Smaller groups have a higher noise floor, so lowering the threshold makes
    the apparent effect *stronger* while making it less real.
    """
    assert artifact["min_group_size"] >= 30
    assert artifact["summary"]["smallest_measured_group"] >= 30


def test_permutation_control_is_actually_run(artifact):
    assert artifact["n_permutations"] >= 100
    for row in artifact["per_seed"]:
        assert "null_worst_gap" in row, "every seed needs its own null"
