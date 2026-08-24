"""Phase 2 tests: SHAP correctness, determinism, and canonical serialisation."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brier.config import SEED
from brier.data import load_frame, split_three_way
from brier.explain import (
    additivity_error,
    build_explainer,
    canonical_shap_vector,
    shap_values_for,
    top_k_attributions,
)
from brier.models import base_margins, train_base_classifier


@pytest.fixture(scope="module")
def fitted():
    splits = split_three_way(load_frame())
    Xtr, ytr = splits["train"]
    Xte, yte = splits["test"]
    base = train_base_classifier(Xtr, ytr, seed=SEED)
    expl = build_explainer(base)
    sv = shap_values_for(expl, Xte)
    return {"expl": expl, "sv": sv, "Xte": Xte,
            "margins": base_margins(base, Xte),
            "features": splits["feature_names"]}


def test_shap_matrix_shape(fitted):
    assert fitted["sv"].shape == (len(fitted["Xte"]), len(fitted["features"]))


def test_shap_is_additive_decomposition_of_margin(fitted):
    """SHAP values + base value must reconstruct the model's margin."""
    err = additivity_error(fitted["expl"], fitted["sv"], fitted["margins"])
    assert err < 1e-3, f"additivity violated: {err}"


def test_attributions_are_deterministic(fitted):
    """TreeExplainer is exact; reruns must be bit-identical, not merely close."""
    sv2 = shap_values_for(fitted["expl"], fitted["Xte"])
    assert np.array_equal(fitted["sv"], sv2)


def test_top_k_returns_k_ranked_by_absolute_value(fitted):
    row = fitted["sv"][0]
    tk = top_k_attributions(row, fitted["features"], k=5)
    assert len(tk) == 5
    mags = [abs(t["shap"]) for t in tk]
    assert mags == sorted(mags, reverse=True)


def test_top_k_direction_matches_sign(fitted):
    for t in top_k_attributions(fitted["sv"][0], fitted["features"], k=5):
        expected = "toward_reject" if t["shap"] > 0 else "toward_approve"
        assert t["direction"] == expected


def test_canonical_vector_is_stable_and_quantised(fitted):
    tk = top_k_attributions(fitted["sv"][3], fitted["features"], k=5)
    a = canonical_shap_vector(tk)
    b = canonical_shap_vector(tk)
    assert a == b
    for _, val in a:
        # Fixed 6-decimal quantisation keeps the on-chain hash reproducible.
        assert len(val.split(".")[1]) == 6


def test_directional_sanity_checks_all_pass():
    """The committed Phase 2 report must contain zero directional failures."""
    report = json.loads((ROOT / "artifacts" / "shap" / "phase2_report.json").read_text())
    fails = [c for c in report["sanity_checks"] if c["verdict"] == "FAIL"]
    assert not fails, f"directional sanity failures: {fails}"


def test_credit_history_encoding_follows_empirical_risk():
    """Regression test for the encoding bug found in Phase 2.

    Higher credit_history code must mean lower measured bad rate. The naive
    codebook ordering violates this and made SHAP look wrong when it was right.
    """
    df = load_frame()
    rates = df.groupby("credit_history")["label"].mean()
    assert rates.loc[0] > rates.loc[4], "code 0 must be riskier than code 4"
    assert rates.loc[0] == pytest.approx(0.625, abs=0.01)
    assert rates.loc[4] == pytest.approx(0.1706, abs=0.01)
