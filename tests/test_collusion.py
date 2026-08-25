"""Phase E: the dispute graph and the collusion detector.

The detector is validated on synthetic rings, so these tests guard the thing
that makes that validation meaningful: that the generator produces the
structure it claims to, and that no ground-truth label can leak into the
features the model sees. A detector that is accidentally shown its own answer
would score perfectly and detect nothing.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.collusion import (
    build_adjacency,
    claimant_features,
    generate_dispute_graph,
    predict_scores,
    train_detector,
)


@pytest.fixture(scope="module")
def graph():
    return generate_dispute_graph(seed=7)


def test_generator_is_deterministic_for_a_seed():
    a = generate_dispute_graph(seed=3)
    b = generate_dispute_graph(seed=3)
    np.testing.assert_array_equal(a["edges"], b["edges"])
    np.testing.assert_array_equal(a["labels"], b["labels"])


def test_rings_are_disjoint_and_labelled(graph):
    seen = set()
    for ring in graph["rings"]:
        assert not (seen & set(ring["claimants"])), "a claimant is in two rings"
        seen.update(ring["claimants"])
    # Every ring member is labelled 1, and nobody else is.
    assert set(np.where(graph["labels"] == 1)[0].tolist()) == seen


def test_both_ring_kinds_are_generated(graph):
    kinds = {r["kind"] for r in graph["rings"]}
    assert kinds == {"shielding", "griefing"}, (
        "both signatures must be exercised; they have opposite outcome skews"
    )


def test_ring_members_concentrate_on_their_operator(graph):
    """The structural property the detector is supposed to find.

    Asserted in aggregate rather than per claimant. At intensity 0.85 a ring
    member with only three disputes can land below any fixed per-node
    threshold purely by chance -- that is sampling noise, not a generator
    fault, and a test that fails on it would be testing the wrong thing.
    """
    edges = graph["edges"]
    ring_shares, other_shares = [], []

    in_ring = {c: r["operator"] for r in graph["rings"] for c in r["claimants"]}
    for c in range(graph["n_claimants"]):
        mine = edges[edges[:, 0] == c]
        if len(mine) < 2:
            continue
        counts = np.bincount(mine[:, 1])
        if c in in_ring:
            ring_shares.append(float((mine[:, 1] == in_ring[c]).mean()))
        else:
            other_shares.append(float(counts.max() / len(mine)))

    assert np.mean(ring_shares) > 0.7, (
        f"rings must concentrate on their operator (mean {np.mean(ring_shares):.2f})"
    )
    assert np.mean(ring_shares) > np.mean(other_shares) + 0.2, (
        "ring concentration must stand clear of what ordinary claimants show "
        f"({np.mean(ring_shares):.2f} vs {np.mean(other_shares):.2f})"
    )


def test_features_do_not_leak_the_label(graph):
    """No feature may be a giveaway for ring membership.

    If any single feature separated the classes almost perfectly, the GNN's
    score would say nothing about graph structure. This is the test that keeps
    the Phase E result honest.
    """
    x = claimant_features(graph)
    y = graph["labels"]
    active = x[:, 0] > 0  # claimants with at least one dispute
    for j in range(x.shape[1]):
        col, yy = x[active, j], y[active]
        if yy.sum() == 0 or (~yy.astype(bool)).sum() == 0:
            continue
        order = np.argsort(col)
        ranks = np.empty(len(col), float)
        ranks[order] = np.arange(1, len(col) + 1)
        pos = ranks[yy == 1]
        n_pos, n_neg = len(pos), int((yy == 0).sum())
        auc = (pos.sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
        assert abs(auc - 0.5) < 0.49, f"feature {j} alone separates the classes (AUC {auc:.3f})"


def test_feature_matrix_shape_and_finiteness(graph):
    x = claimant_features(graph)
    assert x.shape == (graph["n_claimants"], 6)
    assert np.all(np.isfinite(x))


def test_isolated_claimant_has_zero_features():
    g = generate_dispute_graph(n_claimants=50, n_disputes=5, n_rings=1,
                               ring_size=2, seed=11)
    x = claimant_features(g)
    disputed = set(g["edges"][:, 0].tolist())
    for c in range(g["n_claimants"]):
        if c not in disputed:
            assert not x[c].any(), "a claimant with no disputes must have no features"


def test_adjacency_is_symmetric(graph):
    nb = build_adjacency(graph)
    for i, neighbours in enumerate(nb):
        for j in neighbours:
            assert i in nb[j], f"edge {i}-{j} is not symmetric"


def test_adjacency_excludes_self_loops(graph):
    for i, neighbours in enumerate(build_adjacency(graph)):
        assert i not in neighbours


def test_detector_beats_chance_on_easy_rings():
    """A floor, not a headline. The full sweep lives in the Phase E script."""
    g = generate_dispute_graph(ring_intensity=1.0, seed=5)
    x, y = claimant_features(g), g["labels"]
    nb = build_adjacency(g)

    rng = np.random.default_rng(5)
    perm = rng.permutation(len(y))
    train = np.zeros(len(y), bool)
    train[perm[: len(y) // 2]] = True

    model = train_detector(x, nb, y, train, seed=5, epochs=150)
    scores = predict_scores(model, x, nb)

    test = ~train
    s, yy = scores[test], y[test]
    order = np.argsort(s)
    ranks = np.empty(len(s), float)
    ranks[order] = np.arange(1, len(s) + 1)
    pos = ranks[yy == 1]
    n_pos, n_neg = len(pos), int((yy == 0).sum())
    auc = (pos.sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    assert auc > 0.6, f"detector no better than chance on separable rings (AUC {auc:.3f})"


def test_scores_are_probabilities(graph):
    x, y = claimant_features(graph), graph["labels"]
    nb = build_adjacency(graph)
    train = np.ones(len(y), bool)
    model = train_detector(x, nb, y, train, seed=1, epochs=30)
    s = predict_scores(model, x, nb)
    assert s.shape == (graph["n_claimants"],)
    assert np.all((s >= 0) & (s <= 1))
