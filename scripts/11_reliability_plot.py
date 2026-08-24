"""Render the reliability diagram from the Phase 1 report."""
import json, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
r = json.loads((ROOT / "artifacts" / "calibration" / "phase1_report.json").read_text())

fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
for ax, key, title in [
    (axes[0], "reliability_uncalibrated", f"Uncalibrated (ECE={r['ece']['uncalibrated']:.4f})"),
    (axes[1], "reliability_temperature", f"Temperature T={r['temperature']:.2f} (ECE={r['ece']['temperature']:.4f})"),
]:
    rows = [x for x in r[key] if x["count"] > 0]
    xs = [x["mean_conf"] for x in rows]
    ys = [x["empirical_freq"] for x in rows]
    sz = [max(18, 6 * x["count"]) for x in rows]
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect calibration")
    ax.scatter(xs, ys, s=sz, alpha=0.75, zorder=3, label="bin (area = count)")
    ax.plot(xs, ys, lw=1.2, alpha=0.6, zorder=2)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xlabel("mean predicted confidence")
    ax.set_ylabel("empirical frequency")
    ax.set_title(title, fontsize=10)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8, loc="upper left")

fig.suptitle("Reliability diagram - held-out test split (n=%d)" % r["n_test"], fontsize=11)
fig.tight_layout()
out = ROOT / "artifacts" / "calibration" / "reliability.png"
fig.savefig(out, dpi=150)
print("wrote", out)
