"""Phase D: counterfactual explanations, alongside the SHAP vector.

**Tier 1, evidence layer.** Same trust slot SHAP already occupies: computed
off-chain, hash-committed. The hash proves the operator recorded this
counterfactual at decision time and did not alter it afterwards. It proves
nothing about whether the counterfactual is faithful, achievable, or fair.

Why this and not just SHAP. Adverse action notices for a loan denial have to
give reason codes, and a SHAP attribution answers "what drove this decision"
while an applicant is asking "what would change it". Those are different
questions. "Your debt-to-income ratio contributed -0.62 to the reject margin"
is not something a person can act on; "reduce the instalment rate from 4% to
2% of income and this becomes an approval" is.

The search is a greedy coordinate descent over ACTIONABLE features only,
restricted to each feature's observed range so a counterfactual cannot ask for
a value the dataset has never seen. It is deliberately simple: DiCE-style
diverse counterfactual sets would be a better product, but the point here is
to establish the evidence slot and its trust tier, not to win a benchmark.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Features an applicant cannot change, or cannot be lawfully asked to change.
# `age_years` and `foreign_worker` are immutable in the relevant sense;
# `n_liable_maintenance` (dependants) is not something a lender may ask
# someone to alter. personal_status_sex is already dropped upstream, but is
# listed so that re-enabling it cannot silently make it actionable.
IMMUTABLE = frozenset({
    "age_years",
    "foreign_worker",
    "n_liable_maintenance",
    "personal_status_sex",
})

# Direction an applicant can realistically move a feature. A value of 0 means
# either direction is plausible. These encode real-world action, not model
# gradients: an applicant can shorten a loan or borrow less, and cannot
# instantly acquire seven years of employment history.
MONOTONE_ACTIONABLE = {
    "duration_months": 0,
    "credit_amount": 0,
    "installment_rate_pct_income": 0,
    "savings_status": +1,          # can save more
    "checking_status": +1,
    "other_debtors": +1,           # can add a guarantor
    "other_installment_plans": +1,  # can close other plans
    "property": 0,
    "housing": 0,
    "purpose": 0,
    "credit_history": 0,
    "residence_since": 0,
    "n_existing_credits": 0,
    "telephone": +1,
    "employment_since": 0,
    "job": 0,
}


def actionable_features(feature_names) -> list[str]:
    return [f for f in feature_names if f not in IMMUTABLE]


def feature_grid(X: pd.DataFrame, feature: str, max_values: int = 12) -> np.ndarray:
    """Candidate values for a feature, drawn from its observed distribution."""
    col = X[feature].to_numpy()
    uniq = np.unique(col)
    if uniq.size <= max_values:
        return uniq
    # Continuous: pick quantiles so candidates sit where the data is dense,
    # then SNAP each to the nearest observed value. Quantile interpolation
    # invents values that occur nowhere in the data -- proposing "reduce the
    # loan to 3,271 DM" when no such loan exists is not a plausible
    # counterfactual, and the Phase D plausibility check caught exactly this
    # (10 of 40 cases) before the snap was added.
    targets = np.quantile(col, np.linspace(0.0, 1.0, max_values))
    snapped = uniq[np.abs(uniq[None, :] - targets[:, None]).argmin(axis=1)]
    return np.unique(snapped)


def generate_counterfactual(
    predict_proba,
    x_row: pd.Series,
    X_reference: pd.DataFrame,
    target: float = 0.5,
    max_changes: int = 3,
    max_values: int = 12,
) -> dict:
    """Greedy search for the smallest change set that flips REJECT to APPROVE.

    `predict_proba` maps a one-row DataFrame to P(reject). A counterfactual is
    found when that probability drops below `target`.

    Greedy is a real limitation and is recorded in the result: it finds *a*
    small change set, not the provably minimal one. It is reported as
    `sparsity` rather than `minimality` for that reason.
    """
    current = x_row.copy()
    changes: list[dict] = []
    p_start = float(predict_proba(current.to_frame().T))
    p_current = p_start

    candidates = [f for f in actionable_features(X_reference.columns) if f in x_row.index]

    for _ in range(max_changes):
        if p_current < target:
            break

        best = None
        for feat in candidates:
            if any(c["feature"] == feat for c in changes):
                continue
            direction = MONOTONE_ACTIONABLE.get(feat, 0)
            original = current[feat]

            for value in feature_grid(X_reference, feat, max_values):
                if value == original:
                    continue
                if direction > 0 and value < original:
                    continue
                if direction < 0 and value > original:
                    continue

                trial = current.copy()
                trial[feat] = value
                p_trial = float(predict_proba(trial.to_frame().T))
                if best is None or p_trial < best["p"]:
                    best = {"feature": feat, "from": original, "to": value, "p": p_trial}

        # No single further change reduces the reject probability at all.
        if best is None or best["p"] >= p_current - 1e-9:
            break

        current[best["feature"]] = best["to"]
        p_current = best["p"]
        changes.append({
            "feature": best["feature"],
            "from": float(best["from"]),
            "to": float(best["to"]),
            "p_after": float(best["p"]),
        })

    return {
        "found": bool(p_current < target),
        "p_before": p_start,
        "p_after": p_current,
        "sparsity": len(changes),
        "changes": changes,
    }


def validate_counterfactual(cf: dict) -> list[str]:
    """Structural checks. Returns a list of violations; empty means clean."""
    problems = []
    for change in cf["changes"]:
        feat = change["feature"]
        if feat in IMMUTABLE:
            problems.append(f"{feat} is immutable and must never appear in a counterfactual")
        direction = MONOTONE_ACTIONABLE.get(feat, 0)
        delta = change["to"] - change["from"]
        if direction > 0 and delta < 0:
            problems.append(f"{feat} moved down but is only actionable upward")
        if direction < 0 and delta > 0:
            problems.append(f"{feat} moved up but is only actionable downward")
        if change["from"] == change["to"]:
            problems.append(f"{feat} recorded as changed but holds the same value")
    if cf["found"] and cf["p_after"] >= 0.5:
        problems.append("marked found but the reject probability did not fall below 0.5")
    return problems


def canonical_counterfactual(cf: dict) -> list:
    """Deterministic serialisation for hashing, mirroring canonical_shap_vector.

    Same fixed 6-decimal quantisation, for the same reason: platform-dependent
    float formatting would make the on-chain hash irreproducible.
    """
    return [
        [str(c["feature"]), f"{c['from']:.6f}", f"{c['to']:.6f}"]
        for c in cf["changes"]
    ]
