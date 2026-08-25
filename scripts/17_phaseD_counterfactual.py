"""Phase D: counterfactual explanations, validated alongside SHAP.

Validation here is structural and behavioural, not a benchmark score. The
questions that matter for an adverse-action notice are:

  1. Does it find a counterfactual at all, and for what fraction of rejections?
  2. Is it actionable -- never proposing a change to an immutable attribute?
  3. Is it plausible -- staying inside values the data actually contains?
  4. Is it sparse enough for a person to act on?
  5. Does it AGREE with SHAP? A counterfactual that flips a feature SHAP says
     is irrelevant would mean one of the two explanations is lying.

Point 5 is the cross-check worth having, since SHAP and the counterfactual are
committed together as one evidence bundle. If they routinely disagree, the
bundle is internally inconsistent and that is worth knowing.

    python scripts/17_phaseD_counterfactual.py

Writes artifacts/ablation/phaseD.json.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brier.config import ARTIFACTS, SEED  # noqa: E402
from brier.counterfactual import (  # noqa: E402
    IMMUTABLE,
    actionable_features,
    canonical_counterfactual,
    generate_counterfactual,
    validate_counterfactual,
)
from brier.data import load_frame, split_three_way  # noqa: E402
from brier.explain import (  # noqa: E402
    build_explainer,
    canonical_shap_vector,
    shap_values_for,
    top_k_attributions,
)
from brier.models import train_base_classifier  # noqa: E402

OUT = ARTIFACTS / "ablation"
N_CASES = 40


def main() -> int:
    df = load_frame()
    split = split_three_way(df, seed=SEED)
    (X_tr, y_tr) = split["train"]
    (X_te, y_te) = split["test"]
    names = split["feature_names"]

    model = train_base_classifier(X_tr, y_tr, seed=SEED)

    def predict_proba(frame):
        return float(model.predict_proba(frame)[:, 1][0])

    explainer = build_explainer(model)
    shap_te = shap_values_for(explainer, X_te)

    # Only rejections need an adverse action notice.
    probs = model.predict_proba(X_te)[:, 1]
    rejected = np.where(probs >= 0.5)[0][:N_CASES]

    cases = []
    for i in rejected:
        row = X_te.iloc[i]
        cf = generate_counterfactual(predict_proba, row, X_tr)
        problems = validate_counterfactual(cf)

        top5 = top_k_attributions(shap_te[i], names, k=5)
        shap_top_names = {t["feature"] for t in top5}
        cf_names = {c["feature"] for c in cf["changes"]}

        # Plausibility: every proposed value must occur in the training data.
        implausible = [
            c["feature"] for c in cf["changes"]
            if c["to"] not in set(np.unique(X_tr[c["feature"]].to_numpy()))
        ]

        bundle = {
            "shap": canonical_shap_vector(top5),
            "counterfactual": canonical_counterfactual(cf),
        }
        digest = hashlib.sha256(
            json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

        cases.append({
            "index": int(i),
            "found": cf["found"],
            "sparsity": cf["sparsity"],
            "p_before": cf["p_before"],
            "p_after": cf["p_after"],
            "changes": cf["changes"],
            "violations": problems,
            "implausible_values": implausible,
            "shap_top5": [t["feature"] for t in top5],
            "cf_features_in_shap_top5": sorted(cf_names & shap_top_names),
            "overlap_fraction": (len(cf_names & shap_top_names) / len(cf_names)) if cf_names else None,
            "evidence_hash": digest,
        })

    found = [c for c in cases if c["found"]]
    overlaps = [c["overlap_fraction"] for c in cases if c["overlap_fraction"] is not None]
    all_violations = [v for c in cases for v in c["violations"]]
    all_implausible = [f for c in cases for f in c["implausible_values"]]

    # Determinism: the committed hash must reproduce exactly on a rerun.
    recheck = generate_counterfactual(predict_proba, X_te.iloc[rejected[0]], X_tr)
    deterministic = (canonical_counterfactual(recheck)
                     == canonical_counterfactual(
                         generate_counterfactual(predict_proba, X_te.iloc[rejected[0]], X_tr)))

    summary = {
        "n_rejections_examined": len(cases),
        "n_counterfactual_found": len(found),
        "found_rate": len(found) / len(cases) if cases else 0.0,
        "mean_sparsity_when_found": float(np.mean([c["sparsity"] for c in found])) if found else None,
        "max_sparsity": int(max((c["sparsity"] for c in cases), default=0)),
        "immutable_violations": len(all_violations),
        "implausible_values": len(all_implausible),
        "mean_shap_overlap": float(np.mean(overlaps)) if overlaps else None,
        "hash_deterministic": bool(deterministic),
        "immutable_features": sorted(IMMUTABLE),
        "n_actionable_features": len(actionable_features(names)),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phaseD.json").write_text(
        json.dumps({"summary": summary, "cases": cases}, indent=2), encoding="utf-8")

    print(f"  rejections examined        {summary['n_rejections_examined']}")
    print(f"  counterfactual found       {summary['n_counterfactual_found']}"
          f"  ({summary['found_rate']:.0%})")
    print(f"  mean changes when found    {summary['mean_sparsity_when_found']}")
    print(f"  immutable violations       {summary['immutable_violations']}")
    print(f"  implausible values         {summary['implausible_values']}")
    print(f"  mean overlap with SHAP     {summary['mean_shap_overlap']:.3f}"
          if summary["mean_shap_overlap"] is not None else "  mean overlap: n/a")
    print(f"  hash deterministic         {summary['hash_deterministic']}")
    print(f"\n  wrote {(OUT / 'phaseD.json').relative_to(ROOT)}")

    if summary["immutable_violations"] or summary["implausible_values"]:
        print("\n  FAIL: a counterfactual proposed an immutable or unseen value")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
