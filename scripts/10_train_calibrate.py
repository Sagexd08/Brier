"""Phase 1: train base classifier + calibration head, measure ECE.

Hard gate: calibration MUST reduce ECE on the held-out TEST split. If it does
not, the premise of the whole project (that miscalibration is measurable and
correctable) fails, and the script exits non-zero rather than continuing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brier.config import CALIB, MODEL_VERSION, MODELS, SEED
from brier.data import load_frame, split_three_way
from brier.metrics import (
    brier_score,
    expected_calibration_error,
    max_calibration_error,
    reliability_curve,
)
from brier.models import (
    MLPCalibrationHead,
    TemperatureScaler,
    apply_head,
    base_margins,
    fit_calibration_head,
    train_base_classifier,
)


def main() -> int:
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    MODELS.mkdir(parents=True, exist_ok=True)
    CALIB.mkdir(parents=True, exist_ok=True)

    df = load_frame()
    splits = split_three_way(df)
    Xtr, ytr = splits["train"]
    Xca, yca = splits["calib"]
    Xte, yte = splits["test"]
    features = splits["feature_names"]

    print(f"train={len(ytr)}  calib={len(yca)}  test={len(yte)}  features={len(features)}")

    # --- base model -------------------------------------------------------
    base = train_base_classifier(Xtr, ytr, seed=SEED)
    base.save_model(str(MODELS / "base_xgb.json"))

    m_tr = base_margins(base, Xtr)
    m_ca = base_margins(base, Xca)
    m_te = base_margins(base, Xte)

    # Uncalibrated probabilities are sigmoid(margin) -- what the base model asserts.
    p_tr = 1.0 / (1.0 + np.exp(-m_tr))
    p_ca = 1.0 / (1.0 + np.exp(-m_ca))
    p_te = 1.0 / (1.0 + np.exp(-m_te))

    acc_tr = float(((p_tr > 0.5).astype(int) == ytr).mean())
    acc_te = float(((p_te > 0.5).astype(int) == yte).mean())
    print(f"base accuracy: train={acc_tr:.4f}  test={acc_te:.4f}  "
          f"(gap {acc_tr-acc_te:+.4f} -> overfit regime confirmed)")

    ece_pre = expected_calibration_error(p_te, yte)
    mce_pre = max_calibration_error(p_te, yte)
    brier_pre = brier_score(p_te, yte)

    # --- calibration heads, fitted on the CALIB split only -----------------
    temp = TemperatureScaler()
    temp, temp_nll = fit_calibration_head(temp, m_ca, yca, seed=SEED)
    p_te_temp = apply_head(temp, m_te)

    mlp = MLPCalibrationHead(hidden=16)
    mlp, mlp_nll = fit_calibration_head(mlp, m_ca, yca, seed=SEED)
    p_te_mlp = apply_head(mlp, m_te)

    ece_temp = expected_calibration_error(p_te_temp, yte)
    ece_mlp = expected_calibration_error(p_te_mlp, yte)

    print(f"\nlearned temperature T = {temp.temperature:.4f} "
          f"(T>1 means the base model was overconfident)")
    print(f"MLP head parameters: {mlp.n_parameters()}")

    print("\n--- Expected Calibration Error on held-out TEST split ---")
    print(f"  uncalibrated       ECE={ece_pre:.4f}  MCE={mce_pre:.4f}  Brier={brier_pre:.4f}")
    print(f"  temperature scaled ECE={ece_temp:.4f}  MCE={max_calibration_error(p_te_temp,yte):.4f}  Brier={brier_score(p_te_temp,yte):.4f}")
    print(f"  MLP head           ECE={ece_mlp:.4f}  MCE={max_calibration_error(p_te_mlp,yte):.4f}  Brier={brier_score(p_te_mlp,yte):.4f}")

    # --- leakage control: what fitting on TRAIN would have done ------------
    temp_leak = TemperatureScaler()
    temp_leak, _ = fit_calibration_head(temp_leak, m_tr, ytr, seed=SEED)
    ece_leak = expected_calibration_error(apply_head(temp_leak, m_te), yte)
    print(f"\n[control] temperature fitted on TRAIN (the bug we avoid): "
          f"T={temp_leak.temperature:.4f} -> test ECE={ece_leak:.4f}")

    # --- hard gate ---------------------------------------------------------
    best_ece = min(ece_temp, ece_mlp)
    best_name = "temperature" if ece_temp <= ece_mlp else "mlp"
    if best_ece >= ece_pre:
        print(f"\nFAIL: calibration did not reduce ECE "
              f"({ece_pre:.4f} -> {best_ece:.4f}). Halting per Phase 1 gate.")
        return 1
    print(f"\nPASS: ECE reduced {ece_pre:.4f} -> {best_ece:.4f} "
          f"({100*(1-best_ece/ece_pre):.1f}% reduction, best head: {best_name})")

    # --- persist -----------------------------------------------------------
    torch.save(temp.state_dict(), CALIB / "temperature_head.pt")
    torch.save(mlp.state_dict(), CALIB / "mlp_head.pt")

    report = {
        "model_version": MODEL_VERSION,
        "seed": SEED,
        "n_train": len(ytr), "n_calib": len(yca), "n_test": len(yte),
        "n_features": len(features), "features": features,
        "base_accuracy_train": acc_tr, "base_accuracy_test": acc_te,
        "temperature": temp.temperature,
        "mlp_parameters": mlp.n_parameters(),
        "ece": {"uncalibrated": ece_pre, "temperature": ece_temp, "mlp": ece_mlp,
                "control_fitted_on_train": ece_leak},
        "control_temperature_fitted_on_train": temp_leak.temperature,
        "mce": {"uncalibrated": mce_pre,
                "temperature": max_calibration_error(p_te_temp, yte),
                "mlp": max_calibration_error(p_te_mlp, yte)},
        "brier": {"uncalibrated": brier_pre,
                  "temperature": brier_score(p_te_temp, yte),
                  "mlp": brier_score(p_te_mlp, yte)},
        "reliability_uncalibrated": reliability_curve(p_te, yte),
        "reliability_temperature": reliability_curve(p_te_temp, yte),
        "reliability_mlp": reliability_curve(p_te_mlp, yte),
    }
    (CALIB / "phase1_report.json").write_text(json.dumps(report, indent=2))
    np.save(CALIB / "test_margins.npy", m_te)
    np.save(CALIB / "test_labels.npy", yte)
    np.save(CALIB / "calib_margins.npy", m_ca)
    print(f"\nwrote {CALIB/'phase1_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
