"""Figure D: reliability diagram from the repo's MEASURED bin values.

Every point is read from artifacts/calibration/phase1_report.json, which is
written by scripts/10_train_calibrate.py. No curve is fitted, smoothed, or
approximated.

Styling comes from brier.figstyle so the figure is set in the same Computer
Modern as the paper body. The in-image title was removed: the caption directly
below it already names the figure, and printing the name twice at two sizes in
two typefaces is what made these look pasted in from a slide deck.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brier import figstyle
from brier.figstyle import ACCENT, AFTER, BEFORE, INK, MUTED, RULE

figstyle.use()

r = json.loads((ROOT / "artifacts" / "calibration" / "phase1_report.json").read_text())

fig, axes = plt.subplots(1, 3, figsize=(13.0, 4.15),
                         gridspec_kw={"width_ratios": [1, 1, 0.95]})


def panel(ax, key, colour, marker, title, ece, mce, label):
    rows = [b for b in r[key] if b["count"] > 0]
    xs = [b["mean_conf"] for b in rows]
    ys = [b["empirical_freq"] for b in rows]
    ns = [b["count"] for b in rows]

    ax.plot([0, 1], [0, 1], "--", color=ACCENT, lw=0.9, zorder=2,
            label="perfect calibration")
    # The vertical gaps ARE the quantity ECE integrates, so they are drawn
    # rather than described: each bar is one bin's contribution.
    for x, y in zip(xs, ys):
        ax.plot([x, x], [x, y], color=ACCENT, alpha=0.30, lw=0.9, zorder=2)
    ax.plot(xs, ys, "-", color=colour, lw=1.1, alpha=0.9, zorder=3)
    # Marker shape carries the same distinction as colour, so the panels stay
    # readable in greyscale.
    ax.scatter(xs, ys, s=[max(16, 4.2 * n) for n in ns], color=colour,
               marker=marker, edgecolor="white", linewidth=0.7, zorder=4,
               label=r"bin (area $\propto$ n)")

    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("mean predicted confidence")
    ax.set_title(title, pad=7)
    figstyle.panel_label(ax, label)
    figstyle.note(ax, f"ECE  {ece:.4f}\nMCE  {mce:.4f}", loc="upper left")


panel(axes[1], "reliability_temperature", AFTER, "s",
      f"Temperature scaled, $T = {r['temperature']:.2f}$",
      r["ece"]["temperature"], r["mce"]["temperature"], "(b)")
axes[1].legend(loc="lower right")

panel(axes[0], "reliability_uncalibrated", BEFORE, "o",
      "Uncalibrated (sigmoid of raw margin)",
      r["ece"]["uncalibrated"], r["mce"]["uncalibrated"], "(a)")
axes[0].set_ylabel("empirical frequency")

# ---------------------------------------------------------------------------
# Panel (c): ECE across heads, including the leakage control.
# ---------------------------------------------------------------------------
ax = axes[2]
labels = ["Uncalib.", "Temperature\n(1 param)", "MLP head\n(321 params)",
          "Control:\nfit on TRAIN"]
vals = [r["ece"]["uncalibrated"], r["ece"]["temperature"],
        r["ece"]["mlp"], r["ece"]["control_fitted_on_train"]]

# The control is hatched rather than differently coloured: it is not another
# head, it is the same head fitted wrongly, and hatching says "excluded" in a
# way a fourth hue does not.
bars = ax.bar(range(4), vals, width=0.62, color=[BEFORE, AFTER, "#8fb0c9", "white"],
              edgecolor=[INK, INK, INK, ACCENT], linewidth=0.7)
bars[3].set_hatch("///")
bars[3].set_edgecolor(ACCENT)

base = r["ece"]["uncalibrated"]
ax.axhline(base, color=ACCENT, ls=":", lw=0.9, zorder=1)
# BELOW the line and left-aligned. Above it collides with the first bar's own
# value label (they sit at the same height by construction, since the line IS
# that bar); below it, the region is empty because every other bar is shorter.
ax.text(-0.42, base - 0.012, "uncalibrated baseline", fontsize=8,
        color=ACCENT, ha="left", va="top")

for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.007, f"{v:.4f}",
            ha="center", va="bottom", fontsize=8.5, color=INK)

ax.set_xticks(range(4))
ax.set_xticklabels(labels, fontsize=8.2)
ax.set_ylabel("Expected Calibration Error")
ax.set_ylim(0, 0.335)
ax.set_title("ECE by calibration head", pad=7)
figstyle.panel_label(ax, "(c)")
ax.text(0.5, -0.235, "the control is fitted on TRAIN, and is worse than not "
        "calibrating at all", transform=ax.transAxes, ha="center", va="top",
        fontsize=8, color=MUTED, style="italic")

fig.tight_layout(w_pad=1.8)
out = ROOT / "figures" / "figure-d-calibration.png"
fig.savefig(out)
print("wrote", out)
