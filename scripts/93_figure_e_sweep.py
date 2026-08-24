"""Figure E: proving cost vs calibration-head parameter count (measured)."""
import json
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
r=json.loads((ROOT/"artifacts"/"zk"/"circuit_sweep.json").read_text())
recs=[x for x in r["records"] if x.get("verify_ok")]
p=np.array([x["n_params"] for x in recs],float)
t=np.array([x["prove_s"] for x in recs],float)
rows=np.array([x["num_rows_used"] for x in recs],float)
cap=2**15
FG,GRID,ACC,BLUE="#1a1a1a","#d8d8d8","#c44536","#2f6f9f"

fig,ax=plt.subplots(1,2,figsize=(12.4,4.6))
a=ax[0]
a.axhline(t.mean(),color=ACC,ls="--",lw=1.2,zorder=1,
          label=f"mean {t.mean():.2f} s (±{t.std(ddof=1):.2f})")
a.scatter(p,t,s=64,color=BLUE,edgecolor="white",linewidth=1,zorder=3)
a.plot(p,t,color=BLUE,lw=1.2,alpha=.55,zorder=2)
a.set_xscale("log"); a.set_xlabel("calibration-head parameters (log scale)")
a.set_ylabel("proving time (s)"); a.set_ylim(0,3)
a.set_title("Proving time is flat across 4 orders of magnitude",fontsize=10.5,color=FG)
a.grid(alpha=.28,color=GRID,lw=.7); a.set_axisbelow(True)
for s in ("top","right"): a.spines[s].set_visible(False)
a.legend(fontsize=8.5,frameon=False,loc="lower left")
a.text(.03,.955,"Spearman rho = -0.188, p = 0.603\nslope +0.009 s/decade\nlogrows = 15 for every point",
       transform=a.transAxes,va="top",fontsize=8.6,
       bbox=dict(boxstyle="round,pad=.4",fc="white",ec=GRID))

b=ax[1]
b.axhline(cap,color=ACC,ls="--",lw=1.3,label=f"circuit capacity 2^15 = {cap:,}")
b.scatter(p,rows,s=64,color="#2e7d4f",edgecolor="white",linewidth=1,zorder=3)
b.plot(p,rows,color="#2e7d4f",lw=1.2,alpha=.55,zorder=2)
b.set_xscale("log"); b.set_yscale("log")
b.set_xlabel("calibration-head parameters (log scale)")
b.set_ylabel("circuit rows used (log scale)")
b.set_title("Rows used DO scale with parameters (r = 0.992)",fontsize=10.5,color=FG)
b.grid(alpha=.28,color=GRID,lw=.7); b.set_axisbelow(True)
for s in ("top","right"): b.spines[s].set_visible(False)
b.legend(fontsize=8.5,frameon=False,loc="upper left")
b.text(.97,.06,f"largest head fills {100*rows.max()/cap:.0f}% of capacity",
       transform=b.transAxes,ha="right",fontsize=8.6,
       bbox=dict(boxstyle="round,pad=.4",fc="white",ec=GRID))

fig.suptitle("Figure E — Proving cost vs calibration-head size (EZKL 23.0.5, laptop CPU, best of 3)",
             fontsize=11.5,y=.99,color=FG)
fig.tight_layout(rect=[0,0,1,.95])
out=ROOT/"figures"/"figure-e-circuit-sweep.png"
fig.savefig(out,dpi=200,facecolor="white"); print("wrote",out)
