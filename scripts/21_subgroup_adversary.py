"""Task 3a: does aggregate ECE hide subgroup miscalibration on this dataset?

**HEADLINE RESULT: NO -- and the reason is more interesting than a yes would
have been. This is a negative result, reported at the same visibility as a
positive one, and it BLOCKS the on-chain half of this task (Task 3b).**

PROPOSAL.md 7.4 names aggregate ECE's blindness to subgroup miscalibration as
the sharpest scientific gap in the v0 mechanism. The plan was to construct a
model that is aggregate-calibrated but subgroup-miscalibrated, show the current
rule misses it, then implement a within-group variant that catches it, and key
an on-chain SubgroupReputationRegister off the demonstrated effect.

What the measurement actually shows, in order:

1. The honest pipeline DOES look subgroup-miscalibrated. Group 1's within-group
   ECE exceeds aggregate ECE in 10/10 pinned seeds (mean 0.1349 vs 0.0870, a
   55% understatement). Taken alone this looks like a clean confirmation of 7.4.

2. It is not. A permutation null -- shuffling the subgroup labels while keeping
   the group sizes -- produces a worst-group gap of 0.0559, against the real
   partition's 0.0548. Wilcoxon signed-rank p = 0.92; the real partition beats
   its own null in 3/10 seeds. **A random partition into groups of these sizes
   reproduces the entire effect.**

3. The mechanism is a small-sample bias in ECE itself, not subgroup structure.
   With 10 equal-width bins, a PERFECTLY calibrated model -- calibrated by
   construction, p drawn uniform and y ~ Bernoulli(p) -- scores:

       n =    68   ECE 0.1188        n =   500   ECE 0.0451
       n =   106   ECE 0.0989        n =  2000   ECE 0.0223
       n =   200   ECE 0.0695        n = 10000   ECE 0.0098

   Within-bin accuracy is estimated from a handful of points, and |acc - conf|
   is an absolute value, so sampling error cannot cancel -- it accumulates.
   ECE is biased upward, and the bias grows as groups get smaller.

   The test split here is 200 rows. The two measurable subgroups hold 68 and
   106. At n = 68 the noise floor (0.1188) is larger than the honest model's
   aggregate ECE (0.0870) -- so a within-group ECE on this dataset is
   dominated by the estimator's own bias, and cannot be evidence about the
   model.

CONSEQUENCE, stated plainly: this dataset cannot support the subgroup claim in
either direction. It does not show that Brier is subgroup-calibrated -- absence
of measurable evidence is not evidence of absence, and the honest reading of
7.4 is that it remains OPEN, not closed. What it does show is that the obvious
way to close it is invalid: a within-group ECE gate on 1,000 rows would fire on
noise, and slashing an operator for it would be slashing them for a
small-sample artifact of the auditor's own estimator.

Task 3b (SubgroupReputationRegister.sol) is therefore NOT built. Building an
on-chain register to track a quantity this measurement cannot establish would
be shipping a contract for an effect that was never demonstrated -- and worse,
the register would look like evidence the gap had been closed.

WHAT WOULD SETTLE IT. Roughly 2,000 rows per subgroup puts the noise floor near
0.02, below the effect sizes at stake. That means a dataset ~20x this one, or a
debiased estimator whose own noise floor is characterised (adaptive/equal-mass
binning, or a kernel calibration estimator with a bootstrap CI). Both are named
in PROPOSAL.md 8.

Writes artifacts/calibration/subgroup_adversary.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from scipy.stats import wilcoxon
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.config import CALIB, CALIB_FRAC, ECE_BINS, EVAL_SEEDS, SEED, TRAIN_FRAC
from brier.data import load_frame, split_three_way
from brier.metrics import expected_calibration_error
from brier.models import (
    TemperatureScaler,
    apply_head,
    base_margins,
    fit_calibration_head,
    train_base_classifier,
)
from brier.subgroup import group_ece

# Dropped from the features by load_frame(drop_protected=True); recovered here
# only as a grouping label, never as a model input.
SUBGROUP_COL = "personal_status_sex"

# Groups below this are not measured at all. Even at this size the noise floor
# is ~0.12, which is the finding rather than a workaround.
MIN_GROUP = 30

# Permutation draws per seed for the null. 200 x 10 seeds = 2,000 shuffles.
N_PERMUTATIONS = 200

# Sample sizes for the noise-floor characterisation.
FLOOR_SIZES = (68, 106, 200, 500, 2000, 10000)
FLOOR_DRAWS = 400


def _split_indices(n: int, y: np.ndarray, seed: int):
    """Reproduce split_three_way's partition as INDEX arrays.

    split_three_way returns data, not indices, and the subgroup label must be
    aligned to the test rows. Same function, fractions, seed and stratification,
    so the test set is the one the rest of the pipeline uses. Asserted in main().
    """
    idx = np.arange(n)
    calib_plus_test = 1.0 - TRAIN_FRAC
    idx_train, idx_rest = train_test_split(
        idx, test_size=calib_plus_test, random_state=seed, stratify=y
    )
    idx_calib, idx_test = train_test_split(
        idx_rest, train_size=CALIB_FRAC / calib_plus_test,
        random_state=seed, stratify=y[idx_rest]
    )
    return idx_train, idx_calib, idx_test


def ece_noise_floor(sizes=FLOOR_SIZES, draws=FLOOR_DRAWS, n_bins=ECE_BINS, seed=7):
    """ECE of a model that is perfectly calibrated BY CONSTRUCTION.

    p ~ Uniform(0,1) and y ~ Bernoulli(p), so the true calibration error is
    exactly zero at every p. Whatever ECE reports is therefore entirely the
    estimator's own small-sample bias. This is the control the subgroup
    comparison needs and did not have.
    """
    rng = np.random.default_rng(seed)
    out = {}
    for n in sizes:
        vals = [
            expected_calibration_error(p := rng.uniform(0, 1, n),
                                       (rng.uniform(0, 1, n) < p).astype(int), n_bins)
            for _ in range(draws)
        ]
        out[n] = {"mean": float(np.mean(vals)), "std": float(np.std(vals))}
    return out


def main() -> int:
    CALIB.mkdir(parents=True, exist_ok=True)

    df = load_frame()
    y_all = df["label"].values
    groups_all = load_frame(drop_protected=False)[SUBGROUP_COL].astype(int).values
    assert len(groups_all) == len(df), "subgroup labels misaligned with features"
    assert SUBGROUP_COL not in df.columns, "protected attribute leaked into features"

    rng = np.random.default_rng(12345)
    per_seed = []

    print(f"{'seed':>8}  {'aggECE':>7} {'worstG':>7} {'nullG':>7}  groups")
    for seed in EVAL_SEEDS:
        np.random.seed(seed)
        torch.manual_seed(seed)

        splits = split_three_way(df, seed=seed)
        Xtr, ytr = splits["train"]
        Xca, yca = splits["calib"]
        Xte, yte = splits["test"]

        _, idx_calib, idx_test = _split_indices(len(df), y_all, seed)
        assert np.array_equal(y_all[idx_test], yte), "reconstructed test split mismatch"
        assert np.array_equal(y_all[idx_calib], yca), "reconstructed calib split mismatch"
        g_te = groups_all[idx_test]

        base = train_base_classifier(Xtr, ytr, seed=seed)
        temp = TemperatureScaler()
        temp, _ = fit_calibration_head(temp, base_margins(base, Xca), yca, seed=seed)
        p = apply_head(temp, base_margins(base, Xte))

        agg = float(expected_calibration_error(p, yte, ECE_BINS))
        per = group_ece(p, yte, g_te, ECE_BINS, min_size=MIN_GROUP)
        worst = max(v["ece"] for v in per.values())

        # The control the naive comparison lacks: shuffle group membership,
        # hold the group sizes fixed. Any gap that survives this is structure;
        # any gap that does not is the estimator's bias at that group size.
        null = [
            max(v["ece"] for v in
                group_ece(p, yte, rng.permutation(g_te), ECE_BINS, MIN_GROUP).values())
            for _ in range(N_PERMUTATIONS)
        ]

        per_seed.append({
            "seed": seed,
            "aggregate_ece": agg,
            "worst_group_ece": worst,
            "worst_gap": worst - agg,
            "null_worst_group_ece": float(np.mean(null)),
            "null_worst_gap": float(np.mean(null)) - agg,
            "groups": {str(k): {"ece": v["ece"], "n": v["n"]} for k, v in per.items()},
        })
        print(f"{seed:>8}  {agg:.4f}  {worst:.4f}  {np.mean(null):.4f}  "
              + " ".join(f"g{k}:n={v['n']},ece={v['ece']:.3f}" for k, v in sorted(per.items())))

    real = np.array([r["worst_gap"] for r in per_seed])
    null = np.array([r["null_worst_gap"] for r in per_seed])
    stat, pvalue = wilcoxon(real, null)
    beats_null = int((real > null).sum())

    print(f"\nreal worst-group gap  mean {real.mean():+.4f}")
    print(f"null worst-group gap  mean {null.mean():+.4f}")
    print(f"real > null in {beats_null}/{len(EVAL_SEEDS)} seeds")
    print(f"Wilcoxon signed-rank: statistic={stat:.1f}  p={pvalue:.4f}")

    floor = ece_noise_floor()
    print("\nECE of a PERFECTLY calibrated model (bias of the estimator alone):")
    for n, v in floor.items():
        print(f"  n={n:6d}  ECE {v['mean']:.4f} +/- {v['std']:.4f}")

    # A structural effect requires BOTH: beating the permutation null, and
    # group sizes at which the estimator can resolve the effect at all.
    smallest = min(int(v["n"]) for r in per_seed for v in r["groups"].values())
    floor_at_smallest = floor[68]["mean"] if smallest <= 68 else floor[106]["mean"]

    structural = bool(pvalue < 0.05 and real.mean() > null.mean())
    resolvable = bool(float(np.mean([r["aggregate_ece"] for r in per_seed])) > floor_at_smallest)

    print(f"\nbeats permutation null (p<0.05):     {structural}")
    print(f"group sizes above the noise floor:   {resolvable}")
    print(f"EFFECT DEMONSTRATED: {structural and resolvable}")
    if not (structural and resolvable):
        print("\nTask 3b (SubgroupReputationRegister.sol) is BLOCKED and not built.")
        print("Reporting the null rather than shrinking MIN_GROUP or dropping the")
        print("permutation control until something passes.")

    payload = {
        "question": "Does aggregate ECE hide subgroup miscalibration on UCI German Credit?",
        "answer": "No -- not measurably. The apparent gap is the ECE estimator's "
                  "small-sample bias, reproduced in full by a random partition.",
        "subgroup_column": SUBGROUP_COL,
        "ece_bins": ECE_BINS,
        "min_group_size": MIN_GROUP,
        "n_permutations": N_PERMUTATIONS,
        "seeds": list(EVAL_SEEDS),
        "per_seed": per_seed,
        "summary": {
            "mean_aggregate_ece": float(np.mean([r["aggregate_ece"] for r in per_seed])),
            "mean_worst_group_ece": float(np.mean([r["worst_group_ece"] for r in per_seed])),
            "mean_real_gap": float(real.mean()),
            "mean_null_gap": float(null.mean()),
            "seeds_beating_null": beats_null,
            "wilcoxon_statistic": float(stat),
            "wilcoxon_p": float(pvalue),
            "smallest_measured_group": smallest,
        },
        "ece_noise_floor": {str(k): v for k, v in floor.items()},
        "verdict": {
            "beats_permutation_null": structural,
            "groups_above_noise_floor": resolvable,
            "effect_demonstrated": structural and resolvable,
            "task_3b_built": False,
            "reason": "The worst-group ECE gap is statistically indistinguishable "
                      "from a random partition of the same group sizes "
                      f"(Wilcoxon p={pvalue:.4f}), and at n=68 a perfectly "
                      "calibrated model already scores ECE 0.1188 -- above this "
                      "pipeline's aggregate ECE. The dataset cannot resolve the "
                      "question in either direction, so 7.4 stays OPEN.",
        },
    }

    out = CALIB / "subgroup_adversary.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")

    # Exit 0: the measurement ran correctly and produced a valid negative
    # result. A null finding is a legitimate outcome, not a pipeline failure,
    # and failing the build for it would pressure future runs to bury it.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
