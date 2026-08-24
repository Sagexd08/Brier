"""Phase 2 (research pass): characterise proving cost vs calibration-head size.

v0 observed that a 1-parameter head and a 321-parameter head both proved in
~2.0 s at logrows=15, and attributed this to fixed lookup/column overhead
dominating. That was a TWO-POINT observation, which cannot distinguish

    (H1) cost is overhead-dominated and flat in parameter count, from
    (H2) cost grows with parameter count, but 1 and 321 both happen to fit in
         the same circuit and the growth only shows up later.

This script sweeps head sizes over four orders of magnitude and measures
logrows, proving time, proof size, and EVM verification gas at each point, so
the two hypotheses can be separated. The critical control is logrows: if it is
constant across the sweep, the fixed cost is genuinely fixed; the moment it
steps, we should see cost step with it. That step -- if it exists -- is the
actual finding.
"""
from __future__ import annotations

import argparse
import io
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ezkl

from brier.config import CALIB, SEED, ZK
from brier.data import load_frame, split_three_way
from brier.metrics import expected_calibration_error
from brier.models import (
    MLPCalibrationHead,
    TemperatureScaler,
    apply_head,
    base_margins,
    fit_calibration_head,
    train_base_classifier,
)

# torch's ONNX exporter prints emoji; the Windows console defaults to cp1252
# and raises UnicodeEncodeError mid-export. Same guard as scripts/30_export_onnx.py.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

EZKL_CLI = ROOT / "tools" / "ezkl.exe"
SRS_URL = "https://kzg.ezkl.xyz/kzg{logrows}.srs"
SRS_CACHE = ZK / "srs"

# hidden width -> parameter count for a 1->h->h->1 MLP:
#   (1h + h) + (h^2 + h) + (h + 1)
# Sized to bracket the logrows=15 capacity boundary. h=128 uses 16,511 of the
# 32,768 available rows, so h=160/192/256 should cross it -- and the crossing is
# the point of the sweep, not an accident to be avoided.
SWEEP_HIDDEN = [1, 2, 4, 8, 16, 32, 64, 96, 128, 160, 192, 256]


def cli(*args: str) -> None:
    r = subprocess.run([str(EZKL_CLI), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ezkl {args[0]} failed: {r.stderr[-400:]}")


def fetch_srs(logrows: int, dest: Path) -> Path:
    import shutil
    import urllib.request
    SRS_CACHE.mkdir(parents=True, exist_ok=True)
    cached = SRS_CACHE / f"kzg{logrows}.srs"
    if not cached.exists():
        with urllib.request.urlopen(SRS_URL.format(logrows=logrows), timeout=900) as r, \
                open(cached, "wb") as f:
            shutil.copyfileobj(r, f)
    got = int.from_bytes(cached.read_bytes()[:4], "little")
    if got != logrows:
        raise RuntimeError(f"SRS header logrows={got}, expected {logrows}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached, dest)
    return dest


def export_onnx(head: torch.nn.Module, path: Path, margins: np.ndarray) -> float:
    """Export with static shapes and inline weights; return max |torch-onnx|."""
    import onnx
    import onnxruntime as ort

    head.eval()
    torch.onnx.export(
        head, (torch.zeros(1, 1),), str(path),
        input_names=["margin"], output_names=["calibrated_logit"],
        opset_version=17,
        dynamic_shapes=({0: torch.export.Dim.STATIC, 1: torch.export.Dim.STATIC},),
        external_data=False,
    )
    model = onnx.load(str(path))
    onnx.checker.check_model(model)
    for vi in list(model.graph.input) + list(model.graph.output):
        for dim in vi.type.tensor_type.shape.dim:
            if not dim.HasField("dim_value"):
                raise RuntimeError(f"{path.name}: non-static dim")

    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    errs = []
    for row in margins[:64].astype(np.float32).reshape(-1, 1):
        x = row.reshape(1, 1)
        with torch.no_grad():
            t_out = head(torch.tensor(x)).numpy()
        errs.append(float(np.max(np.abs(t_out - sess.run(None, {"margin": x})[0]))))
    return max(errs)


def measure(name: str, head: torch.nn.Module, n_params: int,
            m_ca: np.ndarray, m_te: np.ndarray, yte: np.ndarray,
            calib_points: list[float], sample_margin: float) -> dict:
    d = ZK / "sweep" / name
    d.mkdir(parents=True, exist_ok=True)
    onnx_path = d / "head.onnx"
    settings, compiled = d / "settings.json", d / "model.compiled"
    pk, vk = d / "pk.key", d / "vk.key"
    witness, proof, srs = d / "witness.json", d / "proof.json", d / "kzg.srs"

    rec: dict = {"name": name, "n_params": n_params}
    rec["onnx_export_max_err"] = export_onnx(head, onnx_path, m_ca)
    rec["test_ece"] = expected_calibration_error(apply_head(head, m_te), yte)

    (d / "input.json").write_text(json.dumps({"input_data": [[float(sample_margin)]]}))
    (d / "calibration_data.json").write_text(json.dumps({"input_data": [calib_points]}))

    ra = ezkl.PyRunArgs()
    ra.input_visibility = "public"
    ra.output_visibility = "public"
    ra.param_visibility = "fixed"

    t0 = time.perf_counter()
    ezkl.gen_settings(str(onnx_path), str(settings), py_run_args=ra)
    ezkl.calibrate_settings(str(d / "calibration_data.json"), str(onnx_path),
                            str(settings), "resources")
    rec["settings_s"] = time.perf_counter() - t0

    cfg = json.loads(settings.read_text())
    logrows = int(cfg["run_args"]["logrows"])
    rec["logrows"] = logrows
    rec["circuit_rows"] = 2 ** logrows
    # Circuit-shape detail: what actually fills the circuit.
    rec["num_rows_used"] = cfg.get("num_rows")
    rec["total_assignments"] = cfg.get("total_assignments")
    rec["total_const_size"] = cfg.get("total_const_size")

    ezkl.compile_circuit(str(onnx_path), str(compiled), str(settings))
    fetch_srs(logrows, srs)

    t0 = time.perf_counter()
    ezkl.setup(str(compiled), str(vk), str(pk), str(srs))
    rec["setup_s"] = time.perf_counter() - t0
    rec["pk_bytes"] = pk.stat().st_size
    rec["vk_bytes"] = vk.stat().st_size

    ezkl.gen_witness(str(d / "input.json"), str(compiled), str(witness))

    # Proving time is the headline: take the best of 3 to suppress scheduler noise.
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        ezkl.prove(str(witness), str(compiled), str(pk), str(proof), str(srs))
        times.append(time.perf_counter() - t0)
    rec["prove_s_runs"] = times
    rec["prove_s"] = min(times)
    rec["prove_s_median"] = float(np.median(times))
    rec["proof_bytes"] = proof.stat().st_size

    t0 = time.perf_counter()
    rec["verify_ok"] = bool(ezkl.verify(str(proof), str(settings), str(vk), str(srs)))
    rec["verify_s"] = time.perf_counter() - t0

    sol = d / "Verifier.sol"
    cli("create-evm-verifier", "--srs-path", str(srs), "--settings-path", str(settings),
        "--vk-path", str(vk), "--sol-code-path", str(sol),
        "--abi-path", str(d / "verifier.abi"))
    rec["verifier_sol_bytes"] = sol.stat().st_size

    calldata = d / "calldata.bytes"
    cli("encode-evm-calldata", "--proof-path", str(proof),
        "--calldata-path", str(calldata))
    rec["calldata_bytes"] = calldata.stat().st_size

    # Instances for the on-chain gas measurement (EZKL stores them little-endian).
    p = json.loads(proof.read_text())
    rec["instances"] = [hex(int.from_bytes(bytes.fromhex(i), "little"))
                        for i in p["instances"][0]]
    rec["proof_hex"] = "0x" + bytes(p["proof"]).hex()
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ZK / "circuit_sweep.json"))
    args = ap.parse_args()

    np.random.seed(SEED)
    torch.manual_seed(SEED)

    df = load_frame()
    splits = split_three_way(df, seed=SEED)
    Xtr, ytr = splits["train"]
    Xca, yca = splits["calib"]
    Xte, yte = splits["test"]
    base = train_base_classifier(Xtr, ytr, seed=SEED)
    m_ca, m_te = base_margins(base, Xca), base_margins(base, Xte)
    all_m = np.concatenate([m_ca, m_te])

    lo, hi = float(all_m.min()), float(all_m.max())
    span = hi - lo
    calib_points = sorted(set([float(x) for x in all_m] + [lo - 0.2 * span, hi + 0.2 * span]))
    sample_margin = float(m_te[0])

    heads: list[tuple[str, torch.nn.Module, int]] = []
    t, _ = fit_calibration_head(TemperatureScaler(), m_ca, yca, seed=SEED)
    heads.append(("temp_p1", t, sum(p.numel() for p in t.parameters())))
    for h in SWEEP_HIDDEN:
        mlp, _ = fit_calibration_head(MLPCalibrationHead(h), m_ca, yca, seed=SEED)
        heads.append((f"mlp_h{h}", mlp, mlp.n_parameters()))

    print(f"{'head':<12} {'params':>7} {'logrows':>8} {'rows_used':>10} "
          f"{'prove_s':>8} {'proof_B':>8} {'pk_MiB':>8}")
    records = []
    for name, head, npar in heads:
        try:
            rec = measure(name, head, npar, m_ca, m_te, yte, calib_points, sample_margin)
            records.append(rec)
            print(f"{name:<12} {npar:>7} {rec['logrows']:>8} "
                  f"{str(rec['num_rows_used']):>10} {rec['prove_s']:>8.2f} "
                  f"{rec['proof_bytes']:>8} {rec['pk_bytes']/1048576:>8.1f}")
        except Exception as e:
            print(f"{name:<12} {npar:>7}  FAILED: {type(e).__name__}: {str(e)[:90]}")
            records.append({"name": name, "n_params": npar, "status": "failed",
                            "error": f"{type(e).__name__}: {e}"})

    ok = [r for r in records if r.get("verify_ok")]
    logrows_set = sorted({r["logrows"] for r in ok})
    report = {
        "seed": SEED,
        "environment": {"python": platform.python_version(),
                        "platform": platform.platform(),
                        "ezkl": "23.0.5", "torch": torch.__version__},
        "records": records,
        "distinct_logrows": logrows_set,
        "logrows_constant": len(logrows_set) == 1,
    }
    Path(args.out).write_text(json.dumps(report, indent=2))
    print(f"\ndistinct logrows across sweep: {logrows_set}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
