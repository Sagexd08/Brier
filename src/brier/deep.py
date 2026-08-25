"""Phase A: a deep tabular base model, and a heterogeneous ensemble.

This is **Tier 1** work. Nothing here enters a circuit.

The distinction matters enough to restate: the zk circuit proves the
*calibration head*, which consumes a single scalar margin. Whatever produces
that margin -- one tree ensemble, one neural network, or an average of both --
is outside the proof entirely. So the base model may be arbitrarily
sophisticated without changing circuit cost by one row, and a more sophisticated
base model earns nothing cryptographically. It earns its place only if the
ablation says it does.

The ensemble combines in PROBABILITY space and then returns to logit space, so
the calibration head downstream sees exactly the scalar interface it already
had. That keeps Phase A from silently widening the proved surface.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn

from .config import SEED
from .data import NUMERIC_COLUMNS

# Everything that is not numeric is a small-cardinality code, so it gets an
# embedding rather than being fed to a linear layer as a bare integer. Treating
# `purpose` (10 unordered codes) as a real number is the specific error this
# avoids -- ordinal columns survive it, unordered ones do not.
EMBED_MIN_DIM = 2
EMBED_MAX_DIM = 8


def split_columns(feature_names: list[str]) -> tuple[list[str], list[str]]:
    """Partition features into (categorical, numeric)."""
    numeric = [c for c in feature_names if c in NUMERIC_COLUMNS]
    categorical = [c for c in feature_names if c not in NUMERIC_COLUMNS]
    return categorical, numeric


def _embed_dim(cardinality: int) -> int:
    """Fast-ai style rule, clamped. Small data, so keep these narrow."""
    return int(min(EMBED_MAX_DIM, max(EMBED_MIN_DIM, round(cardinality / 2))))


class TabularNet(nn.Module):
    """Entity-embedding MLP for mixed categorical/numeric tabular data.

    One embedding table per categorical column, concatenated with standardised
    numerics, then a two-hidden-layer MLP with dropout. Outputs a LOGIT, matching
    `base_margins` from the XGBoost path so the two are directly averageable.
    """

    def __init__(self, cardinalities: list[int], n_numeric: int,
                 hidden: int = 64, dropout: float = 0.25):
        super().__init__()
        self.embeddings = nn.ModuleList([
            nn.Embedding(card, _embed_dim(card)) for card in cardinalities
        ])
        embed_total = sum(_embed_dim(c) for c in cardinalities)

        # Numeric standardisation is a buffer, fitted on TRAIN only, so it
        # travels with the model rather than living in a preprocessing step
        # that could be applied inconsistently at inference.
        self.register_buffer("num_mean", torch.zeros(n_numeric))
        self.register_buffer("num_std", torch.ones(n_numeric))

        self.net = nn.Sequential(
            nn.Linear(embed_total + n_numeric, hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden // 2, 1),
        )

    def fit_numeric_scale(self, x_num: np.ndarray) -> None:
        self.num_mean.copy_(torch.tensor(x_num.mean(axis=0), dtype=torch.float32))
        std = x_num.std(axis=0)
        std[std < 1e-8] = 1.0
        self.num_std.copy_(torch.tensor(std, dtype=torch.float32))

    def forward(self, x_cat: torch.Tensor, x_num: torch.Tensor) -> torch.Tensor:
        parts = [emb(x_cat[:, i]) for i, emb in enumerate(self.embeddings)]
        parts.append((x_num - self.num_mean) / self.num_std)
        return self.net(torch.cat(parts, dim=1))

    def n_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())


def _prepare(X, categorical: list[str], numeric: list[str],
             cardinalities: list[int] | None = None):
    """DataFrame -> (int codes, float matrix), clipping unseen codes."""
    x_cat = X[categorical].to_numpy(dtype=np.int64)
    if cardinalities is not None:
        # A code above what training saw would index out of the embedding
        # table. Clip rather than crash: this is a held-out-split artifact on
        # 600 training rows, not a data error.
        for j, card in enumerate(cardinalities):
            np.clip(x_cat[:, j], 0, card - 1, out=x_cat[:, j])
    x_num = X[numeric].to_numpy(dtype=np.float32)
    return x_cat, x_num


def train_tabular_nn(X_train, y_train, feature_names: list[str], seed: int = SEED,
                     epochs: int = 220, lr: float = 3e-3, weight_decay: float = 1e-4,
                     batch_size: int = 64):
    """Train the entity-embedding MLP on the training split only.

    Unlike the XGBoost base model -- which is deliberately overfit to reproduce
    the overconfidence calibration exists to fix -- this one carries dropout and
    weight decay. That is intentional and worth flagging: if the NN is better
    calibrated simply because it is regularised, that is a statement about
    regularisation, not about depth. The ablation reports uncalibrated ECE for
    both so the comparison is visible rather than buried.
    """
    torch.manual_seed(seed)
    np.random.seed(seed)

    categorical, numeric = split_columns(feature_names)
    cardinalities = [int(X_train[c].max()) + 1 for c in categorical]

    model = TabularNet(cardinalities, len(numeric))
    x_cat, x_num = _prepare(X_train, categorical, numeric)
    model.fit_numeric_scale(x_num)

    xc = torch.tensor(x_cat)
    xn = torch.tensor(x_num)
    y = torch.tensor(np.asarray(y_train, dtype=np.float32)).reshape(-1, 1)

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    loss_fn = nn.BCEWithLogitsLoss()

    n = len(y)
    model.train()
    for _ in range(epochs):
        perm = torch.randperm(n)
        for start in range(0, n, batch_size):
            idx = perm[start:start + batch_size]
            opt.zero_grad()
            loss = loss_fn(model(xc[idx], xn[idx]), y[idx])
            loss.backward()
            opt.step()
        sched.step()

    model.eval()
    model._categorical = categorical
    model._numeric = numeric
    model._cardinalities = cardinalities
    return model


def nn_margins(model: TabularNet, X) -> np.ndarray:
    """Logit of the reject class, matching `base_margins`' contract."""
    x_cat, x_num = _prepare(X, model._categorical, model._numeric, model._cardinalities)
    model.eval()
    with torch.no_grad():
        out = model(torch.tensor(x_cat), torch.tensor(x_num))
    return out.numpy().ravel().astype(float)


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))


def _logit(p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    p = np.clip(p, eps, 1.0 - eps)
    return np.log(p / (1.0 - p))


def ensemble_margins(margins_a: np.ndarray, margins_b: np.ndarray,
                     weight: float = 0.5) -> np.ndarray:
    """Average two models in probability space, return the resulting logit.

    Averaging logits instead would let one confidently-wrong model dominate,
    because logit space is unbounded -- a margin of -11 outvotes a margin of
    +3 no matter how sure the second model is. Probability space bounds each
    member's vote to [0,1], which is the behaviour wanted from an ensemble.

    The return trip through `_logit` keeps the downstream interface a single
    scalar margin, so the calibration head and its circuit are untouched.
    """
    p = weight * _sigmoid(margins_a) + (1.0 - weight) * _sigmoid(margins_b)
    return _logit(p)
