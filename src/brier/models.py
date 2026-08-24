"""Base classifier and calibration heads.

Design note: the base model is trained deliberately in an OVERFITTING regime
(deep, unregularised trees, no early stopping). This is not an accident and not
a way to flatter the calibration result -- it reproduces the condition that
makes calibration worth doing in the first place. Production gradient-boosted
models tuned for accuracy are routinely overconfident on held-out data, and a
calibration-insurance mechanism that only works on already-calibrated models
would be pointless. The regime is documented in docs/PHASE1.md.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn

from .config import SEED


def train_base_classifier(X_train, y_train, seed: int = SEED):
    """XGBoost, deep and unregularised -> confident and overfit."""
    from xgboost import XGBClassifier

    model = XGBClassifier(
        n_estimators=400,
        max_depth=8,            # deep
        learning_rate=0.3,      # aggressive
        reg_lambda=0.0,         # no L2
        reg_alpha=0.0,
        min_child_weight=1,     # allow tiny leaves -> memorisation
        subsample=1.0,
        colsample_bytree=1.0,
        random_state=seed,
        n_jobs=4,
        eval_metric="logloss",
        tree_method="hist",
    )
    model.fit(X_train, y_train, verbose=False)
    return model


def base_logits(model, X) -> np.ndarray:
    """Raw margin (logit) of the positive/reject class.

    This logit is the ONLY thing handed to the calibration head, and therefore
    the only quantity that enters the zk circuit.
    """
    return np.asarray(model.predict_proba(X, output_margin=False), dtype=float)[:, 1]


def base_margins(model, X) -> np.ndarray:
    """Untransformed margin, i.e. the pre-sigmoid score.

    Uses the sklearn wrapper's output_margin path so that the DataFrame's
    feature names are preserved; constructing a bare DMatrix drops them and
    XGBoost then refuses to predict.
    """
    return np.asarray(
        model.predict(X, output_margin=True), dtype=float
    ).ravel()


class TemperatureScaler(nn.Module):
    """Single-parameter calibration head: sigmoid(logit / T).

    One learnable parameter. Trivially provable in-circuit; used as the
    documented fallback if the MLP head proves infeasible.
    """

    def __init__(self):
        super().__init__()
        self.log_temperature = nn.Parameter(torch.zeros(1))

    @property
    def temperature(self) -> float:
        return float(torch.exp(self.log_temperature).item())

    def forward(self, logits: torch.Tensor) -> torch.Tensor:
        # Parameterised in log-space so T stays strictly positive.
        return logits / torch.exp(self.log_temperature)


class MLPCalibrationHead(nn.Module):
    """2-layer MLP calibration head mapping a raw margin -> calibrated logit.

    Deliberately tiny for circuit feasibility. With hidden=16 the parameter
    count is 1*16+16 + 16*16+16 + 16*1+1 = 321 parameters, far under the 10k
    ceiling. Outputs a LOGIT; the sigmoid is applied outside so the circuit
    stays affine+ReLU, which is far cheaper to prove than a sigmoid.

    Input normalisation is part of the module, not a preprocessing step. Raw
    XGBoost margins span roughly [-11, +9]; feeding those directly to LBFGS
    made the optimiser diverge to a nan loss while still producing
    finite-looking predictions. Folding the affine normalisation into the first
    layer keeps the circuit identical in structure (it is just a Linear) while
    making the fit numerically stable.
    """

    def __init__(self, hidden: int = 16):
        super().__init__()
        # Fixed (non-learned) input standardisation, calibrated in `fit_input_scale`.
        self.register_buffer("in_mean", torch.zeros(1))
        self.register_buffer("in_std", torch.ones(1))
        self.net = nn.Sequential(
            nn.Linear(1, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, 1),
        )

    def fit_input_scale(self, margins: np.ndarray) -> None:
        """Set normalisation from the CALIBRATION margins only."""
        self.in_mean.fill_(float(np.mean(margins)))
        std = float(np.std(margins))
        self.in_std.fill_(std if std > 1e-8 else 1.0)

    def forward(self, margins: torch.Tensor) -> torch.Tensor:
        return self.net((margins - self.in_mean) / self.in_std)

    def n_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())


def fit_calibration_head(
    head: nn.Module,
    margins_calib: np.ndarray,
    labels_calib: np.ndarray,
    max_iter: int = 300,
    lr: float = 0.5,
    seed: int = SEED,
):
    """Fit a calibration head by minimising NLL on the CALIBRATION split only.

    `margins_calib` must come from data the base model never saw during
    training. Fitting here on training-set margins is the classic bug: the base
    model's train margins are separable, so the fitted temperature collapses
    toward 1 and calibration does nothing.

    Optimiser note: plain LBFGS with a large `max_iter` and no line search
    walks past convergence into numerical breakdown and returns a nan loss on
    this problem. We use the strong-Wolfe line search, a bounded iteration
    count, and keep the best FINITE iterate seen, so a late divergence cannot
    silently corrupt the fitted head.
    """
    torch.manual_seed(seed)
    if hasattr(head, "fit_input_scale"):
        head.fit_input_scale(margins_calib)
    x = torch.tensor(margins_calib, dtype=torch.float32).reshape(-1, 1)
    y = torch.tensor(labels_calib, dtype=torch.float32).reshape(-1, 1)

    opt = torch.optim.LBFGS(
        head.parameters(),
        lr=lr,
        max_iter=max_iter,
        line_search_fn="strong_wolfe",
        tolerance_grad=1e-9,
        tolerance_change=1e-11,
    )
    loss_fn = nn.BCEWithLogitsLoss()

    best = {"loss": float("inf"), "state": None}

    def closure():
        opt.zero_grad()
        loss = loss_fn(head(x), y)
        val = float(loss.detach())
        if np.isfinite(val) and val < best["loss"]:
            best["loss"] = val
            best["state"] = {k: v.detach().clone() for k, v in head.state_dict().items()}
        loss.backward()
        return loss

    opt.step(closure)

    with torch.no_grad():
        final = float(loss_fn(head(x), y))

    # Restore the best finite iterate if the optimiser ended somewhere worse.
    if (not np.isfinite(final)) or final > best["loss"]:
        if best["state"] is None:
            raise RuntimeError(
                "calibration head fit produced no finite iterate; "
                "check input scaling before trusting any downstream ECE."
            )
        head.load_state_dict(best["state"])
        final = best["loss"]

    if not np.isfinite(final):
        raise RuntimeError(
            f"calibration head fit diverged (loss={final}). "
            "Check input scaling before trusting any downstream ECE."
        )
    return head, final


def apply_head(head: nn.Module, margins: np.ndarray) -> np.ndarray:
    """Run a calibration head and return calibrated PROBABILITIES."""
    head.eval()
    with torch.no_grad():
        x = torch.tensor(margins, dtype=torch.float32).reshape(-1, 1)
        return torch.sigmoid(head(x)).numpy().ravel()
