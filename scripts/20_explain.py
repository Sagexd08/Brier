"""Phase 2: generate SHAP vectors + run directional sanity checks.

Sanity checks are stated as claims a credit analyst would make BEFORE looking
at the output, then verified against measured attributions. A FAIL is reported
as a FAIL, not quietly dropped.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.config import MODELS, SEED, SHAP_DIR
from brier.data import FEATURE_DESCRIPTIONS, load_frame, split_three_way
from brier.explain import (
    additivity_error,
    build_explainer,
    canonical_shap_vector,
    shap_values_for,
    top_k_attributions,
)
from brier.models import base_margins, train_base_classifier

# Claims stated up front. `expect` is the sign of the correlation between the
# feature VALUE and its SHAP contribution toward REJECT.
#   +1 : higher value should push toward REJECT
#   -1 : higher value should push toward APPROVE
SANITY_CLAIMS = [
    ("installment_rate_pct_income", +1,
     "Higher installment burden as a share of income (DTI proxy) should push toward REJECT"),
    ("duration_months", +1,
     "Longer loan duration should push toward REJECT"),
    ("credit_history", -1,
     "Better credit history (higher code = all paid duly) should push toward APPROVE"),
    ("checking_status", -1,
     "Healthier checking account status should push toward APPROVE"),
    ("savings_status", -1,
     "More savings should push toward APPROVE"),
]


def main() -> int:
    np.random.seed(SEED)
    SHAP_DIR.mkdir(parents=True, exist_ok=True)

    df = load_frame()
    splits = split_three_way(df)
    Xtr, ytr = splits["train"]
    Xte, yte = splits["test"]
    features = splits["feature_names"]

    base = train_base_classifier(Xtr, ytr, seed=SEED)
    expl = build_explainer(base)
    sv = shap_values_for(expl, Xte)
    margins = base_margins(base, Xte)

    print(f"SHAP matrix: {sv.shape}  (test rows x features)")

    # --- correctness: additivity ------------------------------------------
    add_err = additivity_error(expl, sv, margins)
    print(f"additivity max abs error: {add_err:.3e}")
    if add_err > 1e-3:
        print("FAIL: SHAP values do not reconstruct the model margin.")
        return 1

    # --- stability across reruns ------------------------------------------
    identical = True
    n_rerun = 3
    for _ in range(n_rerun):
        expl2 = build_explainer(train_base_classifier(Xtr, ytr, seed=SEED))
        sv2 = shap_values_for(expl2, Xte)
        if not np.allclose(sv, sv2, atol=1e-10, rtol=0):
            identical = False
    print(f"rerun stability ({n_rerun} reruns, bit-identical): {identical}")
    if not identical:
        print("FAIL: attributions are not reproducible across reruns.")
        return 1

    # --- global importance -------------------------------------------------
    mean_abs = np.abs(sv).mean(axis=0)
    order = np.argsort(-mean_abs)[:5]
    global_top5 = [
        {"feature": features[i], "mean_abs_shap": float(mean_abs[i]),
         "description": FEATURE_DESCRIPTIONS.get(features[i], "")}
        for i in order
    ]
    print("\nglobal top-5 (mean |SHAP|):")
    for r in global_top5:
        print(f"  {r['feature']:32s} {r['mean_abs_shap']:.4f}")

    # --- directional sanity checks ----------------------------------------
    print("\ndirectional sanity checks:")
    checks = []
    for feat, expected_sign, claim in SANITY_CLAIMS:
        j = features.index(feat)
        x = Xte[feat].to_numpy(dtype=float)
        s = sv[:, j]
        if np.std(x) < 1e-12 or np.std(s) < 1e-12:
            verdict, corr = "INCONCLUSIVE", float("nan")
        else:
            corr = float(np.corrcoef(x, s)[0, 1])
            ok = (corr > 0) if expected_sign > 0 else (corr < 0)
            verdict = "PASS" if ok else "FAIL"
        evidence = f"corr(value, SHAP-toward-reject) = {corr:+.3f}"
        print(f"  [{verdict:12s}] {feat:30s} {evidence}")
        checks.append({"feature": feat, "claim": claim, "verdict": verdict,
                       "correlation": corr, "evidence": evidence})

    n_fail = sum(1 for c in checks if c["verdict"] == "FAIL")

    # --- per-decision top-5 vectors ---------------------------------------
    per_decision = []
    for i in range(len(Xte)):
        tk = top_k_attributions(sv[i], features, k=5)
        per_decision.append({
            "index": i,
            "margin": float(margins[i]),
            "label": int(yte[i]),
            "top5": tk,
            "canonical": canonical_shap_vector(tk),
        })

    report = {
        "seed": SEED,
        "n_explained": len(per_decision),
        "additivity_max_abs_error": add_err,
        "rerun_identical": identical,
        "n_rerun_checks": n_rerun,
        "global_top5": global_top5,
        "sanity_checks": checks,
        "n_sanity_fail": n_fail,
    }
    (SHAP_DIR / "phase2_report.json").write_text(json.dumps(report, indent=2))
    (SHAP_DIR / "per_decision.json").write_text(json.dumps(per_decision, indent=2))
    np.save(SHAP_DIR / "shap_test.npy", sv)
    print(f"\nwrote {SHAP_DIR/'phase2_report.json'}  ({n_fail} sanity FAILs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
