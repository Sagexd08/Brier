"""Phase C: does ensemble disagreement improve calibration beyond temperature?

Deep ensembles (Lakshminarayanan et al.) give an epistemic uncertainty signal
for free once you have trained N copies: where members disagree, the model does
not know. The intuitive claim is that feeding this signal into calibration
should beat calibrating on the point score alone -- a confident score that the
members disagree about ought to be discounted.

That claim sounds obviously true, which is exactly why it is ablated here
rather than assumed. The comparison is:

    baseline   sigmoid(z / T)              1 parameter,  input: margin
    variant    head([z, disagreement])     ~n parameters, input: margin + spread

Both are fitted on the same calibration split, evaluated on the same test
split, over the same pinned seeds.

A note on tiers. The disagreement signal is computed off-chain from N model
copies, so it carries exactly the provenance problem the margin already has:
an operator that fabricates it obtains a proof that verifies. Adding an input
to the circuit does not add a guarantee about that input.

    python scripts/16_phaseC_deep_ensemble.py

Writes artifacts/ablation/phaseC.json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brier.config import ARTIFACTS, EVAL_SEEDS  # noqa: E402
from brier.data import load_frame, split_three_way  # noqa: E402
from brier.deep import _logit, _sigmoid, nn_margins, train_tabular_nn  # noqa: E402
from brier.metrics import brier_score, expected_calibration_error  # noqa: E402
from brier.models import (  # noqa: E402
    TemperatureScaler,
    apply_head,
    base_margins,
    fit_calibration_head,
    train_base_classifier,
)

OUT = ARTIFACTS / "ablation"
N_MEMBERS = 5


class VarianceAwareHead(nn.Module):
    """Calibration head over [margin, disagreement].

    Deliberately tiny, for the same reason every head here is tiny: it has to
    stay inside the logrows=15 budget to be eligible for Tier 2 at all. Two
    inputs, one hidden layer of 8, affine + ReLU only -- no transcendental.
    """

    def __init__(self, hidden: int = 8):
        super().__init__()
        self.register_buffer("in_mean", torch.zeros(2))
        self.register_buffer("in_std", torch.ones(2))
        self.net = nn.Sequential(
            nn.Linear(2, hidden), nn.ReLU(), nn.Linear(hidden, 1)
        )

    def fit_input_scale(self, x: np.ndarray) -> None:
        self.in_mean.copy_(torch.tensor(x.mean(axis=0), dtype=torch.float32))
        std = x.std(axis=0)
        std[std < 1e-8] = 1.0
        self.in_std.copy_(torch.tensor(std, dtype=torch.float32))

    def forward(self, x):
        return self.net((x - self.in_mean) / self.in_std)

    def n_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())


def fit_two_input_head(head, x_calib, y_calib, seed, max_iter=300):
    torch.manual_seed(seed)
    head.fit_input_scale(x_calib)
    x = torch.tensor(x_calib, dtype=torch.float32)
    y = torch.tensor(np.asarray(y_calib, dtype=np.float32)).reshape(-1, 1)
    opt = torch.optim.LBFGS(head.parameters(), lr=0.4, max_iter=max_iter,
                            line_search_fn="strong_wolfe")
    loss_fn = nn.BCEWithLogitsLoss()
    best = {"loss": float("inf"), "state": None}

    def closure():
        opt.zero_grad()
        loss = loss_fn(head(x), y)
        v = float(loss.detach())
        if np.isfinite(v) and v < best["loss"]:
            best["loss"] = v
            best["state"] = {k: t.detach().clone() for k, t in head.state_dict().items()}
        loss.backward()
        return loss

    opt.step(closure)
    with torch.no_grad():
        final = float(loss_fn(head(x), y))
    if (not np.isfinite(final)) or final > best["loss"]:
        if best["state"] is None:
            raise RuntimeError("variance-aware head produced no finite iterate")
        head.load_state_dict(best["state"])
    return head


def apply_two_input(head, x):
    head.eval()
    with torch.no_grad():
        return torch.sigmoid(head(torch.tensor(x, dtype=torch.float32))).numpy().ravel()


def member_seed(seed: int, k: int) -> int:
    """Deterministic per-member seed inside numpy's 32-bit range."""
    return int((seed * 1_000_003 + k * 7919) % (2 ** 32 - 1))


def disagreement(member_margins: list[np.ndarray]) -> np.ndarray:
    """Std of member PROBABILITIES.

    Probability space rather than logit space: a member that is saturated at
    logit -30 versus one at -12 disagree enormously in logit space and not at
    all in the decision they imply. Spread should measure the latter.
    """
    probs = np.stack([_sigmoid(m) for m in member_margins], axis=0)
    return probs.std(axis=0)


def run_seed(df, seed: int) -> dict:
    split = split_three_way(df, seed=seed)
    (X_tr, y_tr) = split["train"]
    (X_ca, y_ca) = split["calib"]
    (X_te, y_te) = split["test"]
    names = split["feature_names"]

    xgb = train_base_classifier(X_tr, y_tr, seed=seed)
    m_ca, m_te = base_margins(xgb, X_ca), base_margins(xgb, X_te)

    t0 = time.time()
    # Member seeds are derived, not multiplied: seed*1000 overflows numpy's
    # 32-bit seed range for the largest pinned seed (8675309). The derivation
    # is deterministic, so members stay reproducible.
    members = [train_tabular_nn(X_tr, y_tr, names, seed=member_seed(seed, k))
               for k in range(N_MEMBERS)]
    train_s = time.time() - t0

    mem_ca = [nn_margins(m, X_ca) for m in members]
    mem_te = [nn_margins(m, X_te) for m in members]
    dis_ca, dis_te = disagreement(mem_ca), disagreement(mem_te)

    # Baseline: temperature on the XGBoost margin. Identical to Phase A.
    head = TemperatureScaler()
    head, _ = fit_calibration_head(head, m_ca, y_ca, seed=seed)
    p_base = apply_head(head, m_te)

    # Variant: the same margin, plus the epistemic signal.
    x_ca = np.stack([m_ca, dis_ca], axis=1)
    x_te = np.stack([m_te, dis_te], axis=1)
    vhead = fit_two_input_head(VarianceAwareHead(), x_ca, y_ca, seed)
    p_var = apply_two_input(vhead, x_te)

    # Control: the same head shape, but fed a CONSTANT in place of the signal.
    # If the variant wins only because it has more parameters, this control
    # wins too, and the epistemic story is wrong.
    x_ca_c = np.stack([m_ca, np.zeros_like(dis_ca)], axis=1)
    x_te_c = np.stack([m_te, np.zeros_like(dis_te)], axis=1)
    chead = fit_two_input_head(VarianceAwareHead(), x_ca_c, y_ca, seed)
    p_ctrl = apply_two_input(chead, x_te_c)

    def metrics(p):
        return {"ece": expected_calibration_error(p, y_te),
                "brier": brier_score(p, y_te),
                "accuracy": float(((p >= 0.5).astype(int) == y_te).mean())}

    return {
        "seed": seed,
        "ensemble_train_seconds": train_s,
        "head_parameters": VarianceAwareHead().n_parameters(),
        "mean_disagreement_test": float(dis_te.mean()),
        "temperature_baseline": metrics(p_base),
        "variance_aware": metrics(p_var),
        "capacity_control": metrics(p_ctrl),
    }


def _agg(rows, model, key):
    v = np.array([r[model][key] for r in rows], dtype=float)
    return {"mean": float(v.mean()), "std": float(v.std(ddof=0))}


def main() -> int:
    df = load_frame()
    rows = []
    for seed in EVAL_SEEDS:
        print(f"  seed {seed} ({N_MEMBERS} members) ...", flush=True)
        rows.append(run_seed(df, seed))

    arms = ("temperature_baseline", "variance_aware", "capacity_control")
    summary = {a: {k: _agg(rows, a, k) for k in ("ece", "brier", "accuracy")}
               for a in arms}

    from scipy.stats import wilcoxon
    base = np.array([r["temperature_baseline"]["ece"] for r in rows])
    comparisons = {}
    for a in ("variance_aware", "capacity_control"):
        other = np.array([r[a]["ece"] for r in rows])
        stat, p = wilcoxon(other, base)
        comparisons[f"{a}_vs_temperature_ece"] = {
            "wins": int((other < base).sum()), "losses": int((other > base).sum()),
            "median_diff": float(np.median(other - base)),
            "wilcoxon_W": float(stat), "p_value": float(p),
        }

    total_train = float(np.mean([r["ensemble_train_seconds"] for r in rows]))
    payload = {"seeds": list(EVAL_SEEDS), "n_members": N_MEMBERS,
               "per_seed": rows, "summary": summary, "comparisons": comparisons,
               "mean_ensemble_train_seconds": total_train}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phaseC.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n  arm                    ECE              Brier            accuracy")
    for a in arms:
        s = summary[a]
        print("  {:21s}  {:.4f}+/-{:.4f}  {:.4f}+/-{:.4f}  {:.4f}+/-{:.4f}".format(
            a, s["ece"]["mean"], s["ece"]["std"], s["brier"]["mean"],
            s["brier"]["std"], s["accuracy"]["mean"], s["accuracy"]["std"]))
    print()
    for k, v in comparisons.items():
        print(f"  {k}: {v['wins']}W/{v['losses']}L  median {v['median_diff']:+.5f}  p={v['p_value']:.4f}")
    print(f"\n  cost: {N_MEMBERS} model copies, {total_train:.1f}s mean per seed")
    print(f"  wrote {(OUT / 'phaseC.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
