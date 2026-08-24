"""Phase 3a: export calibration heads to ONNX and verify fidelity.

A proof of an ONNX graph is only meaningful if that graph computes the same
function as the head we actually calibrated. Export fidelity is therefore
checked against PyTorch before any circuit work.
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.config import CALIB, ZK
from brier.models import MLPCalibrationHead, TemperatureScaler

# torch's ONNX exporter prints emoji; the Windows console defaults to cp1252
# and would raise UnicodeEncodeError mid-export.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

TOL = 1e-5


def export(head: torch.nn.Module, name: str, sample: torch.Tensor) -> dict:
    ZK.mkdir(parents=True, exist_ok=True)
    path = ZK / f"{name}.onnx"
    head.eval()
    # Static shapes only. A dynamic batch axis leaves an undetermined symbol in
    # the graph, and EZKL's tract frontend rejects it with
    # "Undetermined symbol in expression: <Sym0>". A circuit is fixed-size by
    # construction, so a dynamic axis was never meaningful here anyway:
    # one proof covers exactly one decision.
    # Static shapes only. A dynamic batch axis leaves an undetermined symbol in
    # the graph and EZKL's tract frontend rejects it ("Undetermined symbol in
    # expression: <Sym0>"). A circuit is fixed-size by construction, so a
    # dynamic axis was never meaningful: one proof covers exactly one decision.
    # torch.export otherwise infers a symbolic batch dim, so dynamic_shapes is
    # pinned off and staticness is asserted below rather than trusted.
    torch.onnx.export(
        head, (sample,), str(path),
        input_names=["margin"], output_names=["calibrated_logit"],
        opset_version=17,
        dynamic_shapes=({0: torch.export.Dim.STATIC, 1: torch.export.Dim.STATIC},),
        # Weights must be INLINE. torch writes a .onnx.data sidecar by default,
        # and EZKL's tract frontend cannot resolve external initialisers -- it
        # fails with "[tract] Translating proto model to model". The head is
        # only 321 parameters, so inlining costs ~2.5 KB.
        external_data=False,
    )

    import onnx, onnxruntime as ort
    model = onnx.load(str(path))
    onnx.checker.check_model(model)

    # Hard requirement for EZKL: every input/output dim must be a concrete int.
    for vi in list(model.graph.input) + list(model.graph.output):
        for dim in vi.type.tensor_type.shape.dim:
            if not dim.HasField("dim_value"):
                raise RuntimeError(
                    f"{name}: non-static dim '{dim.dim_param}' on '{vi.name}'; "
                    "EZKL's tract frontend cannot compile a symbolic shape."
                )

    # Fidelity: ONNX runtime output must match PyTorch on real margins.
    # The graph is batch-1, so feed one decision at a time -- which is exactly
    # how it is used in production (one proof per decision).
    margins = np.load(CALIB / "test_margins.npy").astype(np.float32).reshape(-1, 1)
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    errs = []
    for row in margins:
        x = row.reshape(1, 1)
        with torch.no_grad():
            t_out = head(torch.tensor(x)).numpy()
        o_out = sess.run(None, {"margin": x})[0]
        errs.append(float(np.max(np.abs(t_out - o_out))))
    max_err = max(errs)
    ok = max_err < TOL
    print(f"{name:12s} -> {path.name:28s} max|torch-onnx| = {max_err:.3e}  {'OK' if ok else 'FAIL'}")
    if not ok:
        raise RuntimeError(f"ONNX export for {name} is not faithful ({max_err})")
    return {"name": name, "path": str(path), "max_export_error": max_err,
            "n_parameters": sum(p.numel() for p in head.parameters())}


def main() -> int:
    sample = torch.zeros(1, 1)

    temp = TemperatureScaler()
    temp.load_state_dict(torch.load(CALIB / "temperature_head.pt"))

    mlp = MLPCalibrationHead(16)
    mlp.load_state_dict(torch.load(CALIB / "mlp_head.pt"))

    info = [export(temp, "temperature_head", sample), export(mlp, "mlp_head", sample)]

    # Input file for EZKL: a single decision's margin.
    margins = np.load(CALIB / "test_margins.npy").astype(np.float32)
    (ZK / "input.json").write_text(json.dumps(
        {"input_data": [[float(margins[0])]]}))
    # Calibration data for EZKL settings calibration.
    #
    # This MUST span the full margin range the circuit will ever see. An
    # earlier version used only the first 64 test margins, whose range
    # ([-11.09, 7.41]) excluded 3 of the 200 real margins. Proving one of those
    # then failed at witness generation with
    #   "decomposition error: integer -278756480 is too large to be
    #    represented by base 16384 and n 2"
    # i.e. the circuit simply could not represent that input. We therefore
    # calibrate on ALL margins plus a 20% margin of safety on each side, so
    # that a slightly out-of-distribution decision does not become unprovable.
    lo, hi = float(margins.min()), float(margins.max())
    span = hi - lo
    pad_lo, pad_hi = lo - 0.2 * span, hi + 0.2 * span
    calib_points = sorted(set(
        [float(m) for m in margins] + [pad_lo, pad_hi]
    ))
    (ZK / "calibration_data.json").write_text(json.dumps(
        {"input_data": [calib_points]}))
    print(f"circuit calibration range: [{pad_lo:.4f}, {pad_hi:.4f}] "
          f"covering {len(calib_points)} points "
          f"(actual margins span [{lo:.4f}, {hi:.4f}])")

    (ZK / "onnx_export.json").write_text(json.dumps(info, indent=2))
    print(f"\nwrote ONNX + EZKL inputs to {ZK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
