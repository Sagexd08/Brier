"""Phase B feasibility gate: can conformal set construction go in the circuit?

Same discipline as the Phase 0 circuit-size validation. A method is not
promoted to Tier 2 because it sounds stronger; it is promoted only if it fits
the established budget, and the budget is logrows = 15 -- the boundary every
existing head sits inside.

The construction being tested rests on one observation. The conformal set is

    include_1  <=>  1 - p <= q  <=>  p >= 1 - q
    include_0  <=>      p <= q

and p = sigmoid(z) is monotone, so both comparisons can be pushed through the
sigmoid into LOGIT space and evaluated against two constants:

    include_1  <=>  z >= logit(1 - q)
    include_0  <=>  z <= logit(q)

That matters because it keeps the sigmoid out of the circuit entirely. The head
stays affine, and the only additions are two comparisons against fixed
constants -- which is the cheapest possible way to express this.

The quantile q itself is NOT computed in-circuit. Computing it requires sorting
the calibration scores, which is exactly the kind of data-dependent operation a
circuit is bad at, and it is a per-deployment constant rather than a
per-decision one. It is fitted off-chain and committed, precisely as the
temperature T already is.

    python scripts/15_phaseB_circuit_gate.py

Writes artifacts/ablation/phaseB_circuit.json.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ezkl  # noqa: E402

from brier.config import ARTIFACTS, EVAL_SEEDS, SEED, ZK  # noqa: E402
from brier.conformal import (  # noqa: E402
    conformal_quantile,
    nonconformity,
    split_calibration,
)
from brier.data import load_frame, split_three_way  # noqa: E402
from brier.models import (  # noqa: E402
    TemperatureScaler,
    apply_head,
    base_margins,
    fit_calibration_head,
    train_base_classifier,
)

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

EZKL_CLI = ROOT / "tools" / "ezkl.exe"
SRS_URL = "https://kzg.ezkl.xyz/kzg{logrows}.srs"
SRS_CACHE = ZK / "srs"
OUT = ARTIFACTS / "ablation"
BUDGET_LOGROWS = 15


def fetch_srs(logrows: int, dest: Path) -> Path:
    import shutil
    import urllib.request
    SRS_CACHE.mkdir(parents=True, exist_ok=True)
    cached = SRS_CACHE / f"kzg{logrows}.srs"
    if not cached.exists():
        with urllib.request.urlopen(SRS_URL.format(logrows=logrows), timeout=900) as r, \
                open(cached, "wb") as f:
            shutil.copyfileobj(r, f)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached, dest)
    return dest


class TemperatureOnly(nn.Module):
    """The current Tier 2 head. The baseline the gate is measured against."""

    def __init__(self, t: float):
        super().__init__()
        self.register_buffer("inv_t", torch.tensor([1.0 / t], dtype=torch.float32))

    def forward(self, margin):
        return margin * self.inv_t


class TemperaturePlusConformal(nn.Module):
    """Temperature scaling, plus conformal set membership as two comparisons.

    Returns [z, include_0, include_1]. The membership flags are 0/1 floats so
    the graph stays in one dtype through export.
    """

    def __init__(self, t: float, q: float):
        super().__init__()
        eps = 1e-6
        qq = float(np.clip(q, eps, 1.0 - eps))
        lo = float(np.log(qq / (1.0 - qq)))              # logit(q)
        hi = float(np.log((1.0 - qq) / qq))              # logit(1 - q)
        self.register_buffer("inv_t", torch.tensor([1.0 / t], dtype=torch.float32))
        self.register_buffer("c_lo", torch.tensor([lo], dtype=torch.float32))
        self.register_buffer("c_hi", torch.tensor([hi], dtype=torch.float32))

    def forward(self, margin):
        z = margin * self.inv_t
        include_0 = (self.c_lo - z).relu().sign()   # 1 when z <= logit(q)
        include_1 = (z - self.c_hi).relu().sign()   # 1 when z >= logit(1-q)
        return torch.cat([z, include_0, include_1], dim=1)


def export(head: nn.Module, path: Path) -> None:
    head.eval()
    torch.onnx.export(
        head, (torch.zeros(1, 1),), str(path),
        input_names=["margin"], output_names=["out"],
        opset_version=17,
        dynamic_shapes=({0: torch.export.Dim.STATIC, 1: torch.export.Dim.STATIC},),
        external_data=False,
    )


def measure(name: str, head: nn.Module, calib_points: list[float],
            sample: float) -> dict:
    d = ZK / "phaseB" / name
    d.mkdir(parents=True, exist_ok=True)
    onnx_path, settings, compiled = d / "head.onnx", d / "settings.json", d / "model.compiled"
    pk, vk = d / "pk.key", d / "vk.key"
    witness, proof, srs = d / "witness.json", d / "proof.json", d / "kzg.srs"

    rec: dict = {"name": name}
    export(head, onnx_path)

    (d / "input.json").write_text(json.dumps({"input_data": [[float(sample)]]}))
    (d / "calibration_data.json").write_text(json.dumps({"input_data": [calib_points]}))

    ra = ezkl.PyRunArgs()
    ra.input_visibility = "public"
    ra.output_visibility = "public"
    ra.param_visibility = "fixed"

    ezkl.gen_settings(str(onnx_path), str(settings), py_run_args=ra)
    ezkl.calibrate_settings(str(d / "calibration_data.json"), str(onnx_path),
                            str(settings), "resources")

    cfg = json.loads(settings.read_text())
    rec["logrows"] = int(cfg["run_args"]["logrows"])
    rec["circuit_rows"] = 2 ** rec["logrows"]
    rec["num_rows_used"] = cfg.get("num_rows")
    rec["total_assignments"] = cfg.get("total_assignments")

    ezkl.compile_circuit(str(onnx_path), str(compiled), str(settings))
    fetch_srs(rec["logrows"], srs)

    t0 = time.perf_counter()
    ezkl.setup(str(compiled), str(vk), str(pk), str(srs))
    rec["setup_s"] = time.perf_counter() - t0

    ezkl.gen_witness(str(d / "input.json"), str(compiled), str(witness))
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        ezkl.prove(str(witness), str(compiled), str(pk), str(proof), str(srs))
        times.append(time.perf_counter() - t0)
    rec["prove_s"] = min(times)
    rec["proof_bytes"] = proof.stat().st_size

    t0 = time.perf_counter()
    ezkl.verify(str(proof), str(settings), str(vk), str(srs))
    rec["verify_s"] = time.perf_counter() - t0
    return rec


def main() -> int:
    df = load_frame()
    split = split_three_way(df, seed=SEED)
    (X_tr, y_tr) = split["train"]
    (X_ca, y_ca) = split["calib"]

    model = train_base_classifier(X_tr, y_tr, seed=SEED)
    m_ca = base_margins(model, X_ca)

    head_idx, conf_idx = split_calibration(len(y_ca), SEED)
    head = TemperatureScaler()
    head, _ = fit_calibration_head(head, m_ca[head_idx], y_ca[head_idx], seed=SEED)
    T = head.temperature

    p_conf = apply_head(head, m_ca[conf_idx])
    q = conformal_quantile(nonconformity(p_conf, y_ca[conf_idx]), alpha=0.10)

    calib_points = [float(v) for v in m_ca[:64]]
    sample = float(m_ca[0])

    print(f"  T = {T:.4f}, conformal q = {q:.4f} (alpha = 0.10)\n")

    results = {}
    for name, mod in (("temperature_only", TemperatureOnly(T)),
                      ("temperature_plus_conformal", TemperaturePlusConformal(T, q))):
        print(f"  measuring {name} ...", flush=True)
        results[name] = measure(name, mod, calib_points, sample)

    base, conf = results["temperature_only"], results["temperature_plus_conformal"]
    verdict = {
        "budget_logrows": BUDGET_LOGROWS,
        "fits_budget": conf["logrows"] <= BUDGET_LOGROWS,
        "logrows_delta": conf["logrows"] - base["logrows"],
        "rows_used_delta": (conf.get("num_rows_used") or 0) - (base.get("num_rows_used") or 0),
        "prove_s_ratio": conf["prove_s"] / base["prove_s"],
        "tier": "2 (in-circuit)" if conf["logrows"] <= BUDGET_LOGROWS else "1 (off-chain, hash-committed)",
    }

    payload = {"temperature": T, "conformal_quantile": q, "alpha": 0.10,
               "results": results, "verdict": verdict}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phaseB_circuit.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n  head                        logrows  rows used   prove s   proof B")
    for k, r in results.items():
        print("  {:26s}  {:^7d}  {:>9}  {:>7.2f}  {:>7d}".format(
            k, r["logrows"], str(r.get("num_rows_used")), r["prove_s"], r["proof_bytes"]))
    print(f"\n  budget logrows <= {BUDGET_LOGROWS}: {'PASS' if verdict['fits_budget'] else 'FAIL'}")
    print(f"  verdict: Tier {verdict['tier']}")
    print(f"  wrote {(OUT / 'phaseB_circuit.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
