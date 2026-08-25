"""Phase B: does split conformal actually hit its target coverage here?

Conformal theory guarantees marginal coverage under exchangeability. That is a
theorem, but the theorem is about the idealised procedure -- it says nothing
about whether this implementation, on this 100-point calibration half, with
this base model, delivers it. So it is measured across the pinned seeds rather
than assumed, at three target levels.

Reported together, always:
  * empirical coverage (did it hit 1-alpha?)
  * average set size (was the guarantee bought with vacuous sets?)

    python scripts/14_phaseB_conformal.py

Writes artifacts/ablation/phaseB.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brier.config import ARTIFACTS, EVAL_SEEDS  # noqa: E402
from brier.conformal import (  # noqa: E402
    average_set_size,
    conformal_quantile,
    coverage,
    nonconformity,
    prediction_sets,
    set_size_distribution,
    split_calibration,
)
from brier.data import load_frame, split_three_way  # noqa: E402
from brier.models import (  # noqa: E402
    TemperatureScaler,
    apply_head,
    base_margins,
    fit_calibration_head,
    train_base_classifier,
)

OUT = ARTIFACTS / "ablation"
ALPHAS = (0.20, 0.10, 0.05)


def run_seed(df, seed: int) -> dict:
    split = split_three_way(df, seed=seed)
    (X_tr, y_tr) = split["train"]
    (X_ca, y_ca) = split["calib"]
    (X_te, y_te) = split["test"]

    model = train_base_classifier(X_tr, y_tr, seed=seed)

    # The calibration split is halved so the temperature and the conformal
    # quantile never see the same points.
    head_idx, conf_idx = split_calibration(len(y_ca), seed)
    m_ca = base_margins(model, X_ca)
    m_te = base_margins(model, X_te)

    head = TemperatureScaler()
    head, _ = fit_calibration_head(head, m_ca[head_idx], y_ca[head_idx], seed=seed)

    p_conf = apply_head(head, m_ca[conf_idx])
    p_test = apply_head(head, m_te)

    scores = nonconformity(p_conf, y_ca[conf_idx])

    out = {"seed": seed, "n_conformal": int(len(conf_idx)), "levels": {}}
    for alpha in ALPHAS:
        q = conformal_quantile(scores, alpha=alpha)
        sets = prediction_sets(p_test, q)
        out["levels"][f"{alpha:.2f}"] = {
            "target_coverage": 1.0 - alpha,
            "empirical_coverage": coverage(sets, y_te),
            "avg_set_size": average_set_size(sets),
            "size_distribution": set_size_distribution(sets),
            "quantile": q,
        }
    return out


def main() -> int:
    df = load_frame()
    rows = []
    for seed in EVAL_SEEDS:
        print(f"  seed {seed} ...", flush=True)
        rows.append(run_seed(df, seed))

    summary = {}
    for alpha in ALPHAS:
        key = f"{alpha:.2f}"
        cov = np.array([r["levels"][key]["empirical_coverage"] for r in rows])
        size = np.array([r["levels"][key]["avg_set_size"] for r in rows])
        target = 1.0 - alpha
        summary[key] = {
            "target_coverage": target,
            "coverage_mean": float(cov.mean()),
            "coverage_std": float(cov.std(ddof=0)),
            "coverage_min": float(cov.min()),
            "seeds_at_or_above_target": int((cov >= target).sum()),
            "avg_set_size_mean": float(size.mean()),
            "avg_set_size_std": float(size.std(ddof=0)),
        }

    payload = {"seeds": list(EVAL_SEEDS), "alphas": list(ALPHAS),
               "per_seed": rows, "summary": summary}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phaseB.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n  target   empirical coverage   min     >=target   avg set size")
    for alpha in ALPHAS:
        s = summary[f"{alpha:.2f}"]
        print("  {:.2f}     {:.4f}+/-{:.4f}      {:.4f}  {:2d}/10      {:.3f}+/-{:.3f}".format(
            s["target_coverage"], s["coverage_mean"], s["coverage_std"],
            s["coverage_min"], s["seeds_at_or_above_target"],
            s["avg_set_size_mean"], s["avg_set_size_std"]))
    print(f"\n  wrote {(OUT / 'phaseB.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
