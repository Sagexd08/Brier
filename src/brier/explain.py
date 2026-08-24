"""Phase 2: SHAP explainability vectors.

TreeExplainer is exact for tree ensembles (not sampling-based), so
attributions are deterministic given the model and input -- no seed dependence
in the explainer itself. We still pin seeds everywhere and verify rerun
identity rather than assuming it.

The SHAP vector is COMMITTED on-chain as a hash, not zk-proved. It is evidence
that the operator recorded a specific explanation at decision time, and nothing
stronger: a hash proves the explanation was not altered after the fact, not
that it faithfully describes the model.
"""
from __future__ import annotations

import numpy as np


def build_explainer(base_model):
    """Exact TreeExplainer over the base XGBoost model."""
    import shap
    return shap.TreeExplainer(base_model)


def shap_values_for(explainer, X) -> np.ndarray:
    """Return a (n_samples, n_features) SHAP matrix in MARGIN space."""
    vals = explainer.shap_values(X, check_additivity=False)
    arr = np.asarray(vals, dtype=float)
    if arr.ndim == 3:            # some versions return (n, f, classes)
        arr = arr[..., -1]
    return arr


def top_k_attributions(shap_row: np.ndarray, feature_names, k: int = 5):
    """Top-k features for one decision, ranked by |SHAP|.

    Signed values are preserved: the sign carries the direction (positive =
    pushes toward REJECT, since the model's positive class is 'bad credit').
    """
    order = np.argsort(-np.abs(shap_row))[:k]
    return [
        {
            "feature": feature_names[i],
            "shap": float(shap_row[i]),
            "direction": "toward_reject" if shap_row[i] > 0 else "toward_approve",
        }
        for i in order
    ]


def additivity_error(explainer, shap_matrix: np.ndarray, margins: np.ndarray) -> float:
    """Max |sum(shap) + base_value - model_margin|.

    A correctness check on the explainer itself: SHAP values are an additive
    decomposition of the margin, so this must be ~0. If it is not, the
    attributions are not describing the model that made the decision.
    """
    base = float(np.asarray(explainer.expected_value).ravel()[-1])
    recon = shap_matrix.sum(axis=1) + base
    return float(np.max(np.abs(recon - margins)))


def canonical_shap_vector(top_k) -> list:
    """Deterministic serialisation of a top-k vector for hashing.

    Fixed 6-decimal quantisation: float formatting must not vary across
    platforms or the on-chain hash would not reproduce.
    """
    return [[str(t["feature"]), f"{t['shap']:.6f}"] for t in top_k]
