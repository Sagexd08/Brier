"""Figure D: reliability diagram from the repo's MEASURED bin values.

Every point is read from artifacts/calibration/phase1_report.json, which is
written by scripts/10_train_calibrate.py. No curve is fitted, smoothed, or
approximated.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
r = json.loads((ROOT / "artifacts" / "calibration" / "phase1_report.json").read_text())

FG, GRID, ACC = "#1a1a1a", "#d8d8d8", "#c44536"
PRE, POST = "#b0b0b0", "#2f6f9f"

fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.9), gridspec_kw={"width_ratios": [1, 1, 0.92]})

def panel(ax, key, colour, title, ece, mce):
    rows = [b for b in r[key] if b["count"] > 0]
    xs = [b["mean_conf"] for b in rows]
    ys = [b["empirical_freq"] for b in rows]
    ns = [b["count"] for b in rows]

    ax.plot([0, 1], [0, 1], "--", color=ACC, lw=1.3, zorder=2, label="perfect calibration")
    # Gap bars: the quantity ECE actually integrates.
    for x, y in zip(xs, ys):
        ax.plot([x, x], [x, y], color=ACC, alpha=0.35, lw=1.1, zorder=2)
    ax.plot(xs, ys, "-", color=colour, lw=1.6, alpha=0.85, zorder=3)
    ax.scatter(xs, ys, s=[max(22, 5.5 * n) for n in ns], color=colour,
               edgecolor="white", linewidth=0.9, zorder=4, label=r"bin (area $\propto$ n)")

    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("mean predicted confidence")
    ax.set_title(title, fontsize=10.5, color=FG, pad=9)
    ax.grid(alpha=0.28, color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.text(0.035, 0.955, f"ECE = {ece:.4f}\nMCE = {mce:.4f}",
            transform=ax.transAxes, va="top", ha="left", fontsize=9.5,
            bbox=dict(boxstyle="round,pad=0.42", fc="white", ec=GRID, alpha=0.95))
    ax.legend(loc="lower right", fontsize=8, frameon=False)

panel(axes[0], "reliability_uncalibrated", PRE,
      "Uncalibrated (sigmoid of raw margin)",
      r["ece"]["uncalibrated"], r["mce"]["uncalibrated"])
axes[0].set_ylabel("empirical frequency")
panel(axes[1], "reliability_temperature", POST,
      f"Temperature scaled, $T$ = {r['temperature']:.2f}",
      r["ece"]["temperature"], r["mce"]["temperature"])

# Third panel: ECE across all heads plus the leakage control.
ax = axes[2]
labels = ["Uncalibrated", "Temperature\n(1 param)", "MLP head\n(321 params)",
          "Control:\nfit on TRAIN"]
vals = [r["ece"]["uncalibrated"], r["ece"]["temperature"],
        r["ece"]["mlp"], r["ece"]["control_fitted_on_train"]]
cols = [PRE, POST, "#7aa6c2", ACC]
bars = ax.bar(range(4), vals, color=cols, edgecolor="white", linewidth=1.1, width=0.66)
ax.axhline(r["ece"]["uncalibrated"], color=ACC, ls=":", lw=1.2, zorder=1)
ax.text(0.02, r["ece"]["uncalibrated"] + 0.007, "uncalibrated baseline",
        fontsize=8, color=ACC, ha="left")
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.006, f"{v:.4f}",
            ha="center", fontsize=9, color=FG)
ax.set_xticks(range(4)); ax.set_xticklabels(labels, fontsize=8.6)
ax.set_ylabel("Expected Calibration Error")
ax.set_ylim(0, 0.335)
ax.set_title("ECE by calibration head (held-out test)", fontsize=10.5, color=FG, pad=9)
ax.grid(axis="y", alpha=0.28, color=GRID, lw=0.7); ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)

fig.suptitle(
    f"Figure D — Calibration reliability, held-out test split (n = {r['n_test']}), "
    f"{len(r['reliability_uncalibrated'])} equal-width bins",
    fontsize=11.5, y=0.995, color=FG)
fig.tight_layout(rect=[0, 0, 1, 0.965])
out = ROOT / "figures" / "figure-d-calibration.png"
fig.savefig(out, dpi=200, facecolor="white")
print("wrote", out)
