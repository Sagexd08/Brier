"""Phase A ablation: XGBoost vs deep tabular NN vs their ensemble.

Protocol is identical to scripts/12_multiseed_eval.py -- the same pinned seed
list, the same three-way split, the same ECE implementation -- so the numbers
here are directly comparable to the existing baseline rather than merely
similar to it.

Two things are reported separately and must not be conflated:

  * ACCURACY, which is what an ensemble is usually expected to improve, and
  * CALIBRATION (ECE), which is the only quantity this project's mechanism
    prices.

A model can gain accuracy while losing calibration. If that happens it is
reported as such rather than summarised as "the ensemble is better".

    python scripts/13_phaseA_ablation.py

Writes artifacts/ablation/phaseA.json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brier.config import ARTIFACTS, EVAL_SEEDS  # noqa: E402
from brier.data import load_frame, split_three_way  # noqa: E402
from brier.deep import ensemble_margins, nn_margins, train_tabular_nn  # noqa: E402
from brier.metrics import brier_score, expected_calibration_error  # noqa: E402
from brier.models import (  # noqa: E402
    TemperatureScaler,
    apply_head,
    base_margins,
    fit_calibration_head,
    train_base_classifier,
)

OUT = ARTIFACTS / "ablation"


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))


def _evaluate(margins_calib, y_calib, margins_test, y_test, seed):
    """Uncalibrated and temperature-calibrated metrics for one margin source."""
    uncal_probs = _sigmoid(margins_test)

    head = TemperatureScaler()
    head, _ = fit_calibration_head(head, margins_calib, y_calib, seed=seed)
    cal_probs = apply_head(head, margins_test)

    preds = (cal_probs >= 0.5).astype(int)
    return {
        "uncal_ece": expected_calibration_error(uncal_probs, y_test),
        "uncal_brier": brier_score(uncal_probs, y_test),
        "cal_ece": expected_calibration_error(cal_probs, y_test),
        "cal_brier": brier_score(cal_probs, y_test),
        "accuracy": float((preds == y_test).mean()),
        "temperature": head.temperature,
    }


def run_seed(df, seed: int) -> dict:
    split = split_three_way(df, seed=seed)
    (X_tr, y_tr) = split["train"]
    (X_ca, y_ca) = split["calib"]
    (X_te, y_te) = split["test"]
    names = split["feature_names"]

    t0 = time.time()
    xgb = train_base_classifier(X_tr, y_tr, seed=seed)
    t_xgb = time.time() - t0

    t0 = time.time()
    net = train_tabular_nn(X_tr, y_tr, names, seed=seed)
    t_nn = time.time() - t0

    m_xgb_ca, m_xgb_te = base_margins(xgb, X_ca), base_margins(xgb, X_te)
    m_nn_ca, m_nn_te = nn_margins(net, X_ca), nn_margins(net, X_te)
    m_ens_ca = ensemble_margins(m_xgb_ca, m_nn_ca)
    m_ens_te = ensemble_margins(m_xgb_te, m_nn_te)

    return {
        "seed": seed,
        "train_seconds": {"xgboost": t_xgb, "nn": t_nn},
        "nn_parameters": net.n_parameters(),
        "xgboost": _evaluate(m_xgb_ca, y_ca, m_xgb_te, y_te, seed),
        "nn": _evaluate(m_nn_ca, y_ca, m_nn_te, y_te, seed),
        "ensemble": _evaluate(m_ens_ca, y_ca, m_ens_te, y_te, seed),
    }


def _agg(rows, model, key):
    vals = np.array([r[model][key] for r in rows], dtype=float)
    return {"mean": float(vals.mean()), "std": float(vals.std(ddof=0)),
            "values": [float(v) for v in vals]}


def main() -> int:
    df = load_frame()
    rows = []
    for seed in EVAL_SEEDS:
        print(f"  seed {seed} ...", flush=True)
        rows.append(run_seed(df, seed))

    models = ("xgboost", "nn", "ensemble")
    keys = ("uncal_ece", "cal_ece", "cal_brier", "accuracy")
    summary = {m: {k: _agg(rows, m, k) for k in keys} for m in models}

    # Paired comparisons against the XGBoost baseline, on CALIBRATED ECE --
    # the quantity the mechanism actually prices.
    from scipy.stats import wilcoxon

    comparisons = {}
    base = np.array([r["xgboost"]["cal_ece"] for r in rows])
    for m in ("nn", "ensemble"):
        other = np.array([r[m]["cal_ece"] for r in rows])
        diff = other - base
        stat, pval = wilcoxon(other, base)
        comparisons[f"{m}_vs_xgboost_cal_ece"] = {
            "wins": int((diff < 0).sum()),
            "losses": int((diff > 0).sum()),
            "median_diff": float(np.median(diff)),
            "wilcoxon_W": float(stat),
            "p_value": float(pval),
        }

    acc_base = np.array([r["xgboost"]["accuracy"] for r in rows])
    acc_ens = np.array([r["ensemble"]["accuracy"] for r in rows])
    stat, pval = wilcoxon(acc_ens, acc_base)
    comparisons["ensemble_vs_xgboost_accuracy"] = {
        "wins": int((acc_ens > acc_base).sum()),
        "losses": int((acc_ens < acc_base).sum()),
        "median_diff": float(np.median(acc_ens - acc_base)),
        "wilcoxon_W": float(stat),
        "p_value": float(pval),
    }

    payload = {"seeds": list(EVAL_SEEDS), "per_seed": rows,
               "summary": summary, "comparisons": comparisons}

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phaseA.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n  model      uncal ECE        cal ECE          cal Brier        accuracy")
    for m in models:
        s = summary[m]
        print("  {:9s}  {:.4f}+/-{:.4f}  {:.4f}+/-{:.4f}  {:.4f}+/-{:.4f}  {:.4f}+/-{:.4f}".format(
            m, s["uncal_ece"]["mean"], s["uncal_ece"]["std"],
            s["cal_ece"]["mean"], s["cal_ece"]["std"],
            s["cal_brier"]["mean"], s["cal_brier"]["std"],
            s["accuracy"]["mean"], s["accuracy"]["std"]))
    print()
    for k, v in comparisons.items():
        print(f"  {k}: {v['wins']}W/{v['losses']}L  median {v['median_diff']:+.5f}  p={v['p_value']:.4f}")
    print(f"\n  wrote {(OUT / 'phaseA.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
