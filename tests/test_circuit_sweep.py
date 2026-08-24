"""Phase 2 (research pass): tests over the circuit-size sweep."""
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "artifacts" / "zk" / "circuit_sweep.json"


@pytest.fixture(scope="module")
def sweep():
    if not REPORT.exists():
        pytest.skip("circuit_sweep.json absent; run scripts/32_circuit_sweep.py")
    r = json.loads(REPORT.read_text())
    return [x for x in r["records"] if x.get("verify_ok")], r


def test_sweep_spans_at_least_two_orders_of_magnitude(sweep):
    recs, _ = sweep
    p = [x["n_params"] for x in recs]
    assert max(p) / min(p) >= 100, "sweep must span >=2 orders of magnitude"


def test_every_head_in_sweep_actually_verified(sweep):
    recs, r = sweep
    assert len(recs) == len([x for x in r["records"] if "error" not in x])
    for x in recs:
        assert x["verify_ok"] is True


def test_logrows_constant_across_sweep(sweep):
    """The control that makes the overhead claim meaningful."""
    recs, r = sweep
    assert r["logrows_constant"], f"logrows varied: {r['distinct_logrows']}"
    assert {x["logrows"] for x in recs} == {15}


def test_rows_used_do_scale_with_parameters(sweep):
    """The circuit genuinely does more work as params grow -- otherwise
    'flat proving time' would be trivial rather than interesting."""
    recs, _ = sweep
    p = np.array([x["n_params"] for x in recs], float)
    rows = np.array([x["num_rows_used"] for x in recs], float)
    assert np.corrcoef(p, rows)[0, 1] > 0.95


def test_proving_time_is_flat_in_parameter_count(sweep):
    """The Phase 2 finding, as a falsifiable assertion."""
    recs, _ = sweep
    p = np.array([x["n_params"] for x in recs], float)
    t = np.array([x["prove_s"] for x in recs], float)
    rho, pval = spearmanr(p, t)
    assert pval > 0.05, f"proving time now correlates with params (rho={rho}, p={pval})"
    slope = np.polyfit(np.log10(p), t, 1)[0]
    assert abs(slope) < 0.1, f"slope {slope:.4f} s/decade is no longer flat"


def test_sweep_does_not_cross_capacity_and_says_so(sweep):
    """Guards the stated scope limit: if a future sweep crosses the boundary,
    this fails and the 'unmeasured above logrows 15' wording must change."""
    recs, _ = sweep
    max_rows = max(x["num_rows_used"] for x in recs)
    assert max_rows < 2 ** 15, "sweep now crosses capacity; update the scope-limit claim"
