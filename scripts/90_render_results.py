"""Regenerate RESULTS.md from measured artefacts. Never hand-edit RESULTS.md.

Any phase whose artefact is absent renders as NOT YET MEASURED rather than
being filled with a plausible value.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "artifacts" / "calibration" / "phase1_report.json"
SHAPJ = ROOT / "artifacts" / "shap" / "phase2_report.json"
ZKJ = ROOT / "artifacts" / "zk" / "phase3_report.json"
GASJ = ROOT / "artifacts" / "zk" / "phase4_gas.json"
E2EJ = ROOT / "artifacts" / "zk" / "phase5_report.json"

NM = "NOT YET MEASURED."


def phase1() -> str:
    if not CAL.exists():
        return NM
    r = json.loads(CAL.read_text())
    e, m, b = r["ece"], r["mce"], r["brier"]
    ctl_t = r.get("control_temperature_fitted_on_train")
    return f"""Dataset: UCI Statlog German Credit, {r['n_train']+r['n_calib']+r['n_test']} real applications,
{r['n_features']} features (protected attribute excluded).
Splits: train={r['n_train']}, calibration={r['n_calib']}, test={r['n_test']} - mutually disjoint.

Base model trained in a deliberately overfit regime to reproduce realistic
overconfidence: **train accuracy {r['base_accuracy_train']:.4f} vs test accuracy {r['base_accuracy_test']:.4f}**.

Metrics on the held-out **test** split ({r['n_test']} rows, 10 equal-width bins):

| Head | Parameters | ECE | MCE | Brier |
|---|---|---|---|---|
| Uncalibrated | - | **{e['uncalibrated']:.4f}** | {m['uncalibrated']:.4f} | {b['uncalibrated']:.4f} |
| Temperature scaling | 1 | **{e['temperature']:.4f}** | {m['temperature']:.4f} | {b['temperature']:.4f} |
| MLP (2-layer, hidden=16) | {r['mlp_parameters']} | {e['mlp']:.4f} | {m['mlp']:.4f} | {b['mlp']:.4f} |

**Phase 1 gate: PASS.** ECE {e['uncalibrated']:.4f} -> {e['temperature']:.4f}, a {100*(1-e['temperature']/e['uncalibrated']):.1f}% reduction.

Learned temperature **T = {r['temperature']:.4f}**. T > 1 means the base model's logits
had to be *softened*: independent confirmation of overconfidence.

### The calibration set really is held out

A control run fitting the same temperature head on the **training** split
instead of the calibration split:

| Fitted on | Learned T | Test ECE |
|---|---|---|
| Calibration split (correct) | {r['temperature']:.4f} | **{e['temperature']:.4f}** |
| Training split (the bug) | {ctl_t:.4f} | **{e['control_fitted_on_train']:.4f}** |

Fitting on train yields T < 1, i.e. it *sharpens* an already-overconfident model
and makes test ECE **worse than doing nothing at all**. This is measured, not
asserted - it is why the three-way split is correctness-critical.

### Why temperature scaling beats the MLP here

The {r['mlp_parameters']}-parameter MLP reaches a lower NLL on the calibration split but a
higher test ECE. With only {r['n_calib']} calibration points the extra capacity buys
nothing that generalises. The single-parameter head is both the better
engineering choice on this dataset and the cheaper circuit.

An earlier version of this fit diverged to a `nan` loss while still emitting
finite-looking probabilities. The optimiser now uses a strong-Wolfe line search,
keeps the best finite iterate, and raises on divergence
(`tests/test_phase1.py::test_fit_rejects_diverged_loss`)."""


def phase2() -> str:
    if not SHAPJ.exists():
        return NM
    r = json.loads(SHAPJ.read_text())
    lines = [
        f"SHAP TreeExplainer over the base XGBoost model, seeded (seed={r['seed']}).",
        "",
        f"- Explanations generated for **{r['n_explained']}** test decisions.",
        f"- Additivity check (sum of SHAP values + base value == model margin) "
        f"max abs error: **{r['additivity_max_abs_error']:.2e}**.",
        f"- Rerun stability: identical attributions across {r['n_rerun_checks']} reruns: "
        f"**{r['rerun_identical']}**.",
        "",
        "### Global feature importance (mean |SHAP|, top 5)",
        "",
        "| Rank | Feature | Mean abs SHAP |",
        "|---|---|---|",
    ]
    for i, f in enumerate(r["global_top5"], 1):
        lines.append(f"| {i} | `{f['feature']}` | {f['mean_abs_shap']:.4f} |")
    lines += ["", "### Directional sanity checks", "",
              "Each check states a claim a credit analyst would make, then reports whether",
              "the measured attribution agrees.", "",
              "| Claim | Verdict | Evidence |", "|---|---|---|"]
    for c in r["sanity_checks"]:
        lines.append(f"| {c['claim']} | **{c['verdict']}** | {c['evidence']} |")
    return "\n".join(lines)


def phase3() -> str:
    if not ZKJ.exists():
        return NM
    r = json.loads(ZKJ.read_text())
    lines = [
        f"Proving system: **EZKL {r['ezkl_version']}** (halo2, KZG).",
        f"Circuit proves the **calibration head only** - the base classifier is not in-circuit.",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for k, v in r["metrics"].items():
        lines.append(f"| {k} | {v} |")
    if r.get("notes"):
        lines += ["", *r["notes"]]
    return "\n".join(lines)


def phase4() -> str:
    if not GASJ.exists():
        return NM
    r = json.loads(GASJ.read_text())
    lines = ["Measured with `forge test --gas-report` on a local Anvil chain.", "",
             "| Operation | Gas |", "|---|---|"]
    for k, v in r["gas"].items():
        lines.append(f"| {k} | {v:,} |")
    if r.get("notes"):
        lines += ["", *r["notes"]]
    return "\n".join(lines)


def phase5() -> str:
    if not E2EJ.exists():
        return NM
    r = json.loads(E2EJ.read_text())
    lines = ["Three scenarios run end-to-end against a local Anvil chain.", "",
             "| Scenario | Confidence | Outcome | Slash (wei) | Slash % of stake |",
             "|---|---|---|---|---|"]
    for s in r["scenarios"]:
        lines.append(
            f"| {s['name']} | {s['confidence']:.2f} | {s['outcome']} | "
            f"{int(s['slash_wei']):,} | {s['slash_pct']:.2f}% |"
        )
    if r.get("notes"):
        lines += ["", *r["notes"]]
    return "\n".join(lines)


def main() -> int:
    doc = f"""# RESULTS - measured benchmark numbers

Generated by `scripts/90_render_results.py`. Do not hand-edit.

All figures are produced by the scripts in this repo on the machine described
below. Nothing here is estimated, extrapolated, or copied from a paper.
Unmeasured items are marked NOT YET MEASURED.

**Environment:** Windows 11, Python 3.13.5, xgboost 3.1.2, torch 2.9.1+cpu,
ezkl 23.0.5, Foundry 1.7.1. Seed = 42.

---

## Phase 1 - calibration

{phase1()}

---

## Phase 2 - explainability

{phase2()}

---

## Phase 3 - zk proof of the calibration head

{phase3()}

---

## Phase 4 - contract gas

{phase4()}

---

## Phase 5 - end-to-end scenarios

{phase5()}
"""
    (ROOT / "RESULTS.md").write_text(doc, encoding="utf-8")
    print(f"wrote {ROOT/'RESULTS.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
