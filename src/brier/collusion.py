"""Phase E: graph-based collusion detection over the dispute graph.

**Tier 1, off-chain monitoring. This is a flagging tool, not an enforcement
mechanism.** Nothing here is wired to a slashing trigger, and it must not be:
the model is validated only against synthetic injected rings, so its
real-world false-positive rate is unknown. Automatically slashing an operator
on the output of a detector whose precision on real collusion has never been
measured would be indefensible, and saying "the GNN flagged you" is not an
evidentiary standard.

WHAT IS MODELLED. Disputes form a bipartite graph: claimants on one side,
model operators on the other, an edge per dispute. Genuine disputes should
look roughly like independent draws -- a claimant disputes the operator whose
decision hurt them, and different claimants have no particular reason to
concentrate on the same operator. Collusion breaks that: a ring of wallets
disputes one operator far more than chance explains, and the outcomes skew.

Two ring shapes are generated and detected, because they have opposite
signatures:

  * SHIELDING -- confederate claimants file disputes against their own
    operator on decisions that will be upheld, harvesting a near-zero slash
    and a clean reputation record.
  * GRIEFING -- a ring targets a competitor operator, filing disputes it hopes
    a captured or careless committee will overturn.

The architecture is a hand-rolled GraphSAGE (mean aggregation, two hops). It
is written out rather than imported so the propagation rule is auditable in
the same file as the claims made about it -- and because a 200-node graph does
not need a framework.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn


# ----------------------------------------------------------------------
# Synthetic graph generation
# ----------------------------------------------------------------------

def generate_dispute_graph(
    n_operators: int = 25,
    n_claimants: int = 180,
    n_disputes: int = 900,
    n_rings: int = 3,
    ring_size: int = 6,
    ring_intensity: float = 0.85,
    seed: int = 42,
) -> dict:
    """Build a bipartite dispute graph with known collusion rings injected.

    `ring_intensity` is the fraction of a ring member's disputes aimed at the
    ring's operator. At 1.0 the ring is trivially separable by degree alone;
    values below 1 force the detector to use structure rather than a threshold.

    Returns node features, edges, and the ground-truth ring labels. The labels
    exist ONLY because the rings were injected -- this is the entire reason the
    evaluation is honest about being synthetic.
    """
    rng = np.random.default_rng(seed)

    ring_claimants: list[list[int]] = []
    ring_operators: list[int] = []
    ring_kinds: list[str] = []
    taken_claimants: set[int] = set()
    taken_operators: set[int] = set()

    for r in range(n_rings):
        members = []
        while len(members) < ring_size:
            c = int(rng.integers(n_claimants))
            if c not in taken_claimants:
                taken_claimants.add(c)
                members.append(c)
        op = int(rng.integers(n_operators))
        while op in taken_operators:
            op = int(rng.integers(n_operators))
        taken_operators.add(op)
        ring_claimants.append(members)
        ring_operators.append(op)
        ring_kinds.append("shielding" if r % 2 == 0 else "griefing")

    member_to_ring = {c: r for r, ms in enumerate(ring_claimants) for c in ms}

    edges: list[tuple[int, int]] = []      # (claimant, operator)
    confidences: list[float] = []
    upheld: list[int] = []

    for _ in range(n_disputes):
        c = int(rng.integers(n_claimants))
        r = member_to_ring.get(c)

        if r is not None and rng.random() < ring_intensity:
            op = ring_operators[r]
            if ring_kinds[r] == "shielding":
                # Confident decisions that get upheld: a token slash, and a
                # reputation record that looks spotless.
                conf = float(rng.uniform(0.90, 0.99))
                out = 1
            else:
                # Target a competitor and push for an overturn.
                conf = float(rng.uniform(0.85, 0.99))
                out = 0
        else:
            op = int(rng.integers(n_operators))
            conf = float(rng.uniform(0.50, 0.99))
            # Honest disputes are upheld at a rate that does not depend on
            # who filed them.
            out = int(rng.random() < 0.55)

        edges.append((c, op))
        confidences.append(conf)
        upheld.append(out)

    edges_arr = np.array(edges, dtype=np.int64)
    conf_arr = np.array(confidences, dtype=np.float64)
    upheld_arr = np.array(upheld, dtype=np.int64)

    labels = np.zeros(n_claimants, dtype=np.int64)
    for members in ring_claimants:
        labels[members] = 1

    return {
        "n_operators": n_operators,
        "n_claimants": n_claimants,
        "edges": edges_arr,
        "confidences": conf_arr,
        "upheld": upheld_arr,
        "labels": labels,
        "rings": [
            {"claimants": ms, "operator": op, "kind": k}
            for ms, op, k in zip(ring_claimants, ring_operators, ring_kinds)
        ],
    }


def claimant_features(graph: dict) -> np.ndarray:
    """Per-claimant features. Deliberately NOT including ring membership.

    Every feature here is computable from public on-chain dispute history:
    counts, concentration, outcome skew, and the confidences involved. Nothing
    requires off-chain identity information.
    """
    n_c = graph["n_claimants"]
    edges, conf, upheld = graph["edges"], graph["confidences"], graph["upheld"]

    feats = np.zeros((n_c, 6), dtype=np.float32)
    for c in range(n_c):
        mask = edges[:, 0] == c
        n = int(mask.sum())
        if n == 0:
            continue
        ops = edges[mask, 1]
        counts = np.bincount(ops)
        # Concentration: share of this claimant's disputes on its top operator.
        concentration = counts.max() / n
        # Herfindahl index over the operators disputed.
        hhi = float(((counts / n) ** 2).sum())

        feats[c] = [
            n / 10.0,
            concentration,
            hhi,
            float(np.unique(ops).size) / 10.0,
            float(conf[mask].mean()),
            float(upheld[mask].mean()),
        ]
    return feats


def build_adjacency(graph: dict) -> list[np.ndarray]:
    """Claimant-to-claimant adjacency: two claimants are linked when they have
    disputed the same operator. This is the projection a ring shows up in."""
    n_c = graph["n_claimants"]
    edges = graph["edges"]

    by_operator: dict[int, set[int]] = {}
    for c, op in edges:
        by_operator.setdefault(int(op), set()).add(int(c))

    neighbours: list[set[int]] = [set() for _ in range(n_c)]
    for _, claimants in by_operator.items():
        cl = list(claimants)
        # A very popular operator links everyone to everyone and carries no
        # signal, so skip the dense hubs -- they only add noise.
        if len(cl) > 40:
            continue
        for i, a in enumerate(cl):
            for b in cl[i + 1:]:
                neighbours[a].add(b)
                neighbours[b].add(a)
    return [np.array(sorted(s), dtype=np.int64) for s in neighbours]


# ----------------------------------------------------------------------
# Model
# ----------------------------------------------------------------------

class SAGELayer(nn.Module):
    """One GraphSAGE layer: concat(self, mean(neighbours)) -> linear -> ReLU."""

    def __init__(self, in_dim: int, out_dim: int):
        super().__init__()
        self.lin = nn.Linear(in_dim * 2, out_dim)

    def forward(self, h: torch.Tensor, neighbours: list[np.ndarray]) -> torch.Tensor:
        agg = torch.zeros_like(h)
        for i, nb in enumerate(neighbours):
            if nb.size:
                agg[i] = h[nb].mean(dim=0)
            # Isolated node: its own features are the only evidence, so the
            # aggregate stays zero rather than borrowing from the graph mean.
        return torch.relu(self.lin(torch.cat([h, agg], dim=1)))


class CollusionSAGE(nn.Module):
    """Two-hop GraphSAGE node classifier over the claimant projection."""

    def __init__(self, in_dim: int, hidden: int = 24):
        super().__init__()
        self.l1 = SAGELayer(in_dim, hidden)
        self.l2 = SAGELayer(hidden, hidden)
        self.out = nn.Linear(hidden, 1)

    def forward(self, x, neighbours):
        h = self.l1(x, neighbours)
        h = self.l2(h, neighbours)
        return self.out(h)


def train_detector(x: np.ndarray, neighbours: list[np.ndarray], y: np.ndarray,
                   train_mask: np.ndarray, seed: int = 42,
                   epochs: int = 300, lr: float = 0.01) -> CollusionSAGE:
    torch.manual_seed(seed)
    model = CollusionSAGE(x.shape[1])
    xt = torch.tensor(x)
    yt = torch.tensor(y, dtype=torch.float32).reshape(-1, 1)
    mt = torch.tensor(train_mask)

    # Rings are a small minority, so the positive class is upweighted --
    # otherwise the loss is minimised by predicting "no collusion" everywhere,
    # which scores well and detects nothing.
    n_pos = float(y[train_mask].sum())
    n_neg = float((~y[train_mask].astype(bool)).sum())
    pos_weight = torch.tensor([max(1.0, n_neg / max(n_pos, 1.0))])

    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    model.train()
    for _ in range(epochs):
        opt.zero_grad()
        logits = model(xt, neighbours)
        loss = loss_fn(logits[mt], yt[mt])
        loss.backward()
        opt.step()
    model.eval()
    return model


def predict_scores(model: CollusionSAGE, x: np.ndarray,
                   neighbours: list[np.ndarray]) -> np.ndarray:
    with torch.no_grad():
        return torch.sigmoid(model(torch.tensor(x), neighbours)).numpy().ravel()
