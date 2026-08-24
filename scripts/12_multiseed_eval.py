"""Phase 1 (research pass): multi-seed calibration evaluation.

The v0 numbers were single runs at seed 42. A single run cannot distinguish a
real effect from a lucky split, so every headline calibration claim is re-run
across a pinned seed list and reported as mean +/- std.

The seed list is PINNED in config.EVAL_SEEDS and is not a tunable knob: the
full list is always run and always reported. There is no mechanism in this
script to select, drop, or reorder seeds, which is deliberate -- it makes
cherry-picking impossible rather than merely discouraged.

Each seed perturbs BOTH the data split and the head initialisation, so the
reported spread covers split luck and optimisation luck together.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.config import CALIB, EVAL_SEEDS, MODEL_VERSION
from brier.data import load_frame, split_three_way
from brier.metrics import (
    brier_score,
    expected_calibration_error,
    max_calibration_error,
)
from brier.models import (
    MLPCalibrationHead,
    TemperatureScaler,
    apply_head,
    base_margins,
    fit_calibration_head,
    train_base_classifier,
)


def run_seed(df, seed: int) -> dict:
    """One complete train -> calibrate -> evaluate cycle at a given seed."""
    np.random.seed(seed)
    torch.manual_seed(seed)

    splits = split_three_way(df, seed=seed)
    Xtr, ytr = splits["train"]
    Xca, yca = splits["calib"]
    Xte, yte = splits["test"]

    base = train_base_classifier(Xtr, ytr, seed=seed)
    m_ca = base_margins(base, Xca)
    m_te = base_margins(base, Xte)

    p_te_raw = 1.0 / (1.0 + np.exp(-m_te))

    temp, _ = fit_calibration_head(TemperatureScaler(), m_ca, yca, seed=seed)
    p_te_temp = apply_head(temp, m_te)

    mlp, _ = fit_calibration_head(MLPCalibrationHead(16), m_ca, yca, seed=seed)
    p_te_mlp = apply_head(mlp, m_te)

    # Leakage control: the same head fitted on TRAIN margins instead.
    m_tr = base_margins(base, Xtr)
    ctl, _ = fit_calibration_head(TemperatureScaler(), m_tr, ytr, seed=seed)
    p_te_ctl = apply_head(ctl, m_te)

    def acc(p):
        return float(((p > 0.5).astype(int) == yte).mean())

    return {
        "seed": seed,
        "temperature": temp.temperature,
        "control_temperature": ctl.temperature,
        "accuracy": {
            "base_train": float((base.predict(Xtr) == ytr).mean()),
            "uncalibrated": acc(p_te_raw),
            "temperature": acc(p_te_temp),
            "mlp": acc(p_te_mlp),
        },
        "ece": {
            "uncalibrated": expected_calibration_error(p_te_raw, yte),
            "temperature": expected_calibration_error(p_te_temp, yte),
            "mlp": expected_calibration_error(p_te_mlp, yte),
            "control_fitted_on_train": expected_calibration_error(p_te_ctl, yte),
        },
        "brier": {
            "uncalibrated": brier_score(p_te_raw, yte),
            "temperature": brier_score(p_te_temp, yte),
            "mlp": brier_score(p_te_mlp, yte),
        },
        "mce": {
            "uncalibrated": max_calibration_error(p_te_raw, yte),
            "temperature": max_calibration_error(p_te_temp, yte),
            "mlp": max_calibration_error(p_te_mlp, yte),
        },
    }


def wilcoxon_paired(a: list[float], b: list[float]) -> dict:
    """Paired Wilcoxon signed-rank test, a vs b, two-sided.

    Reported alongside the sign count and the median paired difference,
    because with n=10 seeds the p-value alone is a weak summary: the
    smallest attainable two-sided p is 0.002, and a significant p with a
    negligible effect size would not support the claim either.
    """
    from scipy.stats import wilcoxon

    a_arr, b_arr = np.asarray(a, float), np.asarray(b, float)
    diff = a_arr - b_arr
    n_nonzero = int(np.sum(diff != 0))
    if n_nonzero == 0:
        return {"statistic": None, "p_value": 1.0, "n": len(a),
                "n_nonzero": 0, "note": "all pairs identical"}
    stat, p = wilcoxon(a_arr, b_arr)
    return {
        "statistic": float(stat),
        "p_value": float(p),
        "n": len(a),
        "n_nonzero": n_nonzero,
        "n_a_lower": int(np.sum(diff < 0)),
        "median_difference": float(np.median(diff)),
        "mean_difference": float(np.mean(diff)),
    }


def summarise(values: list[float]) -> dict:
    arr = np.asarray(values, dtype=float)
    return {
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
        "min": float(arr.min()),
        "max": float(arr.max()),
        "median": float(np.median(arr)),
        "n": int(arr.size),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(CALIB / "multiseed_report.json"))
    args = ap.parse_args()

    seeds = list(EVAL_SEEDS)
    print(f"Running {len(seeds)} pinned seeds: {seeds}")
    df = load_frame()

    t0 = time.perf_counter()
    runs = []
    for i, s in enumerate(seeds, 1):
        r = run_seed(df, s)
        runs.append(r)
        print(f"  [{i:2d}/{len(seeds)}] seed={s:5d}  "
              f"ECE unc={r['ece']['uncalibrated']:.4f} "
              f"temp={r['ece']['temperature']:.4f} "
              f"mlp={r['ece']['mlp']:.4f}  T={r['temperature']:.3f}")
    elapsed = time.perf_counter() - t0

    def col(section, key):
        return [r[section][key] for r in runs]

    summary = {
        metric: {k: summarise(col(metric, k)) for k in runs[0][metric]}
        for metric in ("ece", "brier", "mce", "accuracy")
    }
    summary["temperature"] = summarise([r["temperature"] for r in runs])
    summary["control_temperature"] = summarise([r["control_temperature"] for r in runs])

    # --- the claim under test -------------------------------------------
    # v0 asserted "temperature scaling beats the MLP head" from one run each.
    ece_temp, ece_mlp = col("ece", "temperature"), col("ece", "mlp")
    brier_temp, brier_mlp = col("brier", "temperature"), col("brier", "mlp")
    ece_unc = col("ece", "uncalibrated")
    ece_ctl = col("ece", "control_fitted_on_train")

    tests = {
        "temperature_vs_mlp_ece": wilcoxon_paired(ece_temp, ece_mlp),
        "temperature_vs_mlp_brier": wilcoxon_paired(brier_temp, brier_mlp),
        "temperature_vs_uncalibrated_ece": wilcoxon_paired(ece_temp, ece_unc),
        "control_vs_uncalibrated_ece": wilcoxon_paired(ece_ctl, ece_unc),
    }

    n_temp_wins = int(np.sum(np.asarray(ece_temp) < np.asarray(ece_mlp)))
    n_ctl_worse = int(np.sum(np.asarray(ece_ctl) > np.asarray(ece_unc)))

    report = {
        "model_version": MODEL_VERSION,
        "seeds": seeds,
        "n_seeds": len(seeds),
        "elapsed_s": elapsed,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "torch": torch.__version__,
        },
        "runs": runs,
        "summary": summary,
        "significance": tests,
        "temperature_beats_mlp_on_ece_in_n_seeds": n_temp_wins,
        "control_worse_than_uncalibrated_in_n_seeds": n_ctl_worse,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    # --- console summary --------------------------------------------------
    print(f"\n{'='*72}\nSUMMARY over {len(seeds)} seeds ({elapsed:.1f}s)\n{'='*72}")
    print(f"{'metric':<28} {'mean':>9} {'std':>9} {'min':>9} {'max':>9}")
    for key in ("uncalibrated", "temperature", "mlp", "control_fitted_on_train"):
        s = summary["ece"][key]
        print(f"ECE  {key:<23} {s['mean']:9.4f} {s['std']:9.4f} {s['min']:9.4f} {s['max']:9.4f}")
    for key in ("uncalibrated", "temperature", "mlp"):
        s = summary["brier"][key]
        print(f"Brier {key:<22} {s['mean']:9.4f} {s['std']:9.4f} {s['min']:9.4f} {s['max']:9.4f}")
    for key in ("uncalibrated", "temperature", "mlp"):
        s = summary["accuracy"][key]
        print(f"Acc  {key:<23} {s['mean']:9.4f} {s['std']:9.4f} {s['min']:9.4f} {s['max']:9.4f}")
    s = summary["temperature"]
    print(f"T    {'(learned)':<23} {s['mean']:9.4f} {s['std']:9.4f} {s['min']:9.4f} {s['max']:9.4f}")

    print(f"\n{'-'*72}\nCLAIM: temperature scaling beats the MLP head on ECE")
    t = tests["temperature_vs_mlp_ece"]
    print(f"  temperature lower in {n_temp_wins}/{len(seeds)} seeds")
    print(f"  Wilcoxon signed-rank: W={t['statistic']}, p={t['p_value']:.5f}, "
          f"median diff={t['median_difference']:+.5f}")
    verdict = "SUPPORTED" if (t["p_value"] < 0.05 and t["median_difference"] < 0) else "NOT SUPPORTED"
    print(f"  VERDICT at alpha=0.05: {verdict}")

    print(f"\nCLAIM: fitting the head on TRAIN is worse than not calibrating")
    t2 = tests["control_vs_uncalibrated_ece"]
    print(f"  control worse in {n_ctl_worse}/{len(seeds)} seeds, "
          f"p={t2['p_value']:.5f}, median diff={t2['median_difference']:+.5f}")

    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
