"""Figure E: proving cost vs calibration-head parameter count (measured).

Every point is read from artifacts/zk/circuit_sweep.json. The correlation
statistics in the annotations are COMPUTED here rather than typed as strings --
the previous version hardcoded "Spearman rho = -0.188, p = 0.603" and
"r = 0.992" into the labels, so a re-run on new data would have silently kept
the old numbers.

Styling comes from brier.figstyle: Computer Modern to match the paper body, no
in-image title (the caption names the figure), and no gridlines.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import pearsonr, spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brier import figstyle
from brier.figstyle import ACCENT, AFTER, INK, MUTED, SUPPORT

figstyle.use()

r = json.loads((ROOT / "artifacts" / "zk" / "circuit_sweep.json").read_text())
recs = [x for x in r["records"] if x.get("verify_ok")]
p = np.array([x["n_params"] for x in recs], float)
t = np.array([x["prove_s"] for x in recs], float)
rows = np.array([x["num_rows_used"] for x in recs], float)
cap = 2 ** 15

# Computed, not asserted.
rho, rho_p = spearmanr(p, t)
slope = np.polyfit(np.log10(p), t, 1)[0]
# Raw-scale Pearson, matching the claim in the paper: rows scale LINEARLY with
# parameter count. Computing it log-log would give 0.999 and would be answering
# a different question (is the relationship a power law?) from the one 7.3 asks.
r_rows, _ = pearsonr(p, rows)
slope_rows = np.polyfit(p, rows, 1)[0]
logrows = {x.get("logrows") for x in recs}

fig, ax = plt.subplots(1, 2, figsize=(11.6, 4.1))

# ---------------------------------------------------------------------------
# (a) Proving time is flat. The point of this panel is a NON-result, so the
#     mean line is the visual anchor and the scatter should read as noise
#     around it rather than as a trend.
# ---------------------------------------------------------------------------
a = ax[0]
a.axhline(t.mean(), color=ACCENT, ls="--", lw=0.9, zorder=1)
# A band at ±1 sd makes "flat" a measured statement rather than an eyeball one.
a.fill_between([p.min() * 0.6, p.max() * 1.7],
               t.mean() - t.std(ddof=1), t.mean() + t.std(ddof=1),
               color=ACCENT, alpha=0.07, zorder=0, linewidth=0)
a.plot(p, t, "-", color=AFTER, lw=0.8, alpha=0.45, zorder=2)
a.scatter(p, t, s=26, color=AFTER, marker="o", edgecolor="white",
          linewidth=0.6, zorder=3)

a.set_xscale("log")
a.set_xlim(p.min() * 0.6, p.max() * 1.7)
a.set_ylim(0, 3)
a.set_xlabel("calibration-head parameters")
a.set_ylabel("proving time (s)")
a.set_title("Proving time does not scale with head size", pad=7)
figstyle.panel_label(a, "(a)")
a.text(p.min() * 0.75, t.mean() + t.std(ddof=1) + 0.07,
       f"mean {t.mean():.2f} s $\\pm$ {t.std(ddof=1):.2f}",
       fontsize=8, color=ACCENT, va="bottom")
figstyle.note(
    a,
    f"Spearman $\\rho$ = {rho:+.3f},  p = {rho_p:.3f}\n"
    f"slope {slope:+.3f} s/decade\n"
    f"logrows = {sorted(logrows)[0]} at every point",
    loc="lower left")

# ---------------------------------------------------------------------------
# (b) Rows DO scale -- the contrast that explains (a). Capacity is the ceiling
#     that makes the flatness intelligible, so it is annotated on the line.
# ---------------------------------------------------------------------------
b = ax[1]
b.axhline(cap, color=ACCENT, ls="--", lw=0.9, zorder=1)
b.plot(p, rows, "-", color=SUPPORT, lw=0.8, alpha=0.45, zorder=2)
b.scatter(p, rows, s=26, color=SUPPORT, marker="^", edgecolor="white",
          linewidth=0.6, zorder=3)

b.set_xscale("log")
b.set_yscale("log")
b.set_xlim(p.min() * 0.6, p.max() * 1.7)
b.set_xlabel("calibration-head parameters")
b.set_ylabel("circuit rows used")
b.set_title("Circuit rows do, and the ceiling is why", pad=7)
figstyle.panel_label(b, "(b)")
b.text(p.min() * 0.75, cap * 1.12, f"circuit capacity $2^{{15}}$ = {cap:,}",
       fontsize=8, color=ACCENT, va="bottom")
figstyle.note(
    b,
    f"{slope_rows:.2f} rows/param,  Pearson $r$ = {r_rows:.3f}\n"
    f"largest head fills {100 * rows.max() / cap:.0f}% of capacity",
    loc="lower right")

fig.tight_layout(w_pad=2.4)
out = ROOT / "figures" / "figure-e-circuit-sweep.png"
fig.savefig(out)
print("wrote", out)
print(f"  computed: rho={rho:+.3f} p={rho_p:.3f} slope={slope:+.4f} "
      f"rows/param={slope_rows:.3f} r_rows={r_rows:.4f}")
