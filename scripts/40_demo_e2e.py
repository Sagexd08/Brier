"""Phase 5: end-to-end demo.

Loads a real loan application -> runs base model + calibration head ->
generates the SHAP vector -> generates a zk proof of the CALIBRATION HEAD ->
submits the attestation to a local chain -> simulates a dispute -> triggers
the slash -> reports the payout.

Three scenarios are run:
  (a) confident + correct   -> negligible slash
  (b) confident + wrong     -> large slash
  (c) uncertain + wrong     -> small slash

Everything on-chain here runs against a local Anvil devnet. Dispute outcomes
are declared by an admin key -- there is no jury and no oracle. See the README.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brier.config import CALIB, MODELS, MODEL_VERSION, SEED, SHAP_DIR, ZK
from brier.data import load_frame, split_three_way
from brier.explain import (
    build_explainer,
    canonical_shap_vector,
    shap_values_for,
    top_k_attributions,
)
from brier.models import TemperatureScaler, apply_head, base_margins, train_base_classifier

RPC = "http://127.0.0.1:8545"
# Anvil's first two deterministic accounts. Local devnet only -- these keys are
# published in Foundry's documentation and hold no real value.
OPERATOR_PK = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
CLAIMANT_PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
FOUNDRY_BIN = Path("C:/Users/sohom/.foundry/bin")
CAST = FOUNDRY_BIN / "cast.exe"
EZKL_CLI = ROOT / "tools" / "ezkl.exe"

WAD = 10**18


def cast(*args: str) -> str:
    r = subprocess.run([str(CAST), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"cast {args[0]} failed:\n{r.stderr[-500:]}")
    return r.stdout.strip()


def keccak(text: str) -> str:
    return cast("keccak", text)


def to_wad(x: float) -> int:
    return int(round(x * WAD))


def prove_for_margin(margin: float, workdir: Path) -> dict:
    """Generate a real zk proof of the calibration head for one margin."""
    workdir.mkdir(parents=True, exist_ok=True)
    src = ZK / "temperature_head"
    inp = workdir / "input.json"
    inp.write_text(json.dumps({"input_data": [[float(margin)]]}))

    witness = workdir / "witness.json"
    proof = workdir / "proof.json"

    t0 = time.perf_counter()
    subprocess.run(
        [str(EZKL_CLI), "gen-witness", "--data", str(inp),
         "--compiled-circuit", str(src / "model.compiled"), "--output", str(witness)],
        capture_output=True, text=True, check=True)
    subprocess.run(
        [str(EZKL_CLI), "prove", "--witness", str(witness),
         "--compiled-circuit", str(src / "model.compiled"),
         "--pk-path", str(src / "pk.key"), "--proof-path", str(proof),
         "--srs-path", str(src / "kzg.srs")],
        capture_output=True, text=True, check=True)
    prove_s = time.perf_counter() - t0

    p = json.loads(proof.read_text())
    # EZKL stores instance field elements LITTLE-ENDIAN.
    instances = [int.from_bytes(bytes.fromhex(i), "little") for i in p["instances"][0]]
    return {
        "proof_hex": "0x" + bytes(p["proof"]).hex(),
        "instances": instances,
        "prove_s": prove_s,
        "rescaled_input": p["pretty_public_inputs"]["rescaled_inputs"][0][0],
        "rescaled_output": p["pretty_public_inputs"]["rescaled_outputs"][0][0],
    }


def main() -> int:
    addrs = json.loads((ROOT / "artifacts" / "deployment.json").read_text())
    attestation = addrs["attestation"]
    pool = addrs["stakepool"]

    print("=" * 74)
    print("BRIER END-TO-END DEMO  (local Anvil devnet)")
    print("=" * 74)
    print(f"  Attestation : {attestation}")
    print(f"  StakePool   : {pool}")

    # ---------- model pipeline -----------------------------------------
    df = load_frame()
    splits = split_three_way(df)
    Xtr, ytr = splits["train"]
    Xte, yte = splits["test"]
    features = splits["feature_names"]

    base = train_base_classifier(Xtr, ytr, seed=SEED)
    head = TemperatureScaler()
    head.load_state_dict(torch.load(CALIB / "temperature_head.pt"))

    margins = base_margins(base, Xte)
    confidences = apply_head(head, margins)
    explainer = build_explainer(base)
    sv = shap_values_for(explainer, Xte)

    # Pick three real applications matching the three scenarios.
    # "confidence" below is the model's probability of REJECT; the operator's
    # stated confidence is its probability that its own decision is CORRECT.
    decisions = (confidences > 0.5).astype(int)
    correct = decisions == yte
    stated = np.where(decisions == 1, confidences, 1.0 - confidences)

    idx_conf_right = int(np.argmax(np.where(correct, stated, -1)))
    idx_conf_wrong = int(np.argmax(np.where(~correct, stated, -1)))
    # Uncertain + wrong: wrong, with stated confidence closest to 0.5.
    unc = np.where(~correct, np.abs(stated - 0.5), 9.9)
    idx_unc_wrong = int(np.argmin(unc))

    scenarios = [
        ("(a) confident + CORRECT", idx_conf_right, True),
        ("(b) confident + WRONG", idx_conf_wrong, False),
        ("(c) uncertain + WRONG", idx_unc_wrong, False),
    ]

    operator_addr = cast("wallet", "address", "--private-key", OPERATOR_PK)
    claimant_addr = cast("wallet", "address", "--private-key", CLAIMANT_PK)

    # ---------- stake ---------------------------------------------------
    stake_eth = 100
    stake_wei = stake_eth * WAD
    print(f"\nOperator stakes {stake_eth} ETH ...")
    cast("send", pool, "stake()", "--value", str(stake_wei),
         "--private-key", OPERATOR_PK, "--rpc-url", RPC)
    bal = int(cast("call", pool, "stakeOf(address)(uint256)",
                   operator_addr, "--rpc-url", RPC).split()[0])
    print(f"  staked: {bal/WAD:.4f} ETH")

    results = []
    for name, i, upheld in scenarios:
        print("\n" + "-" * 74)
        print(f"{name}   (test row {i})")
        print("-" * 74)

        margin = float(margins[i])
        p_reject = float(confidences[i])
        decision = "REJECT" if decisions[i] == 1 else "APPROVE"
        stated_conf = float(stated[i])
        truth = "BAD (reject correct)" if yte[i] == 1 else "GOOD (approve correct)"

        print(f"  base margin (logit)   : {margin:+.4f}")
        print(f"  calibrated P(reject)  : {p_reject:.4f}")
        print(f"  decision              : {decision}")
        print(f"  ground truth          : {truth}")
        print(f"  stated confidence     : {stated_conf:.4f}  (P decision is correct)")

        top5 = top_k_attributions(sv[i], features, k=5)
        print("  SHAP top-5:")
        for t in top5:
            arrow = "->reject " if t["shap"] > 0 else "->approve"
            print(f"      {t['feature']:30s} {t['shap']:+8.4f} {arrow}")

        # --- zk proof of the calibration head ---------------------------
        pr = prove_for_margin(margin, ZK / "demo" / f"row{i}")
        print(f"  zk proof generated in {pr['prove_s']:.2f}s "
              f"(in-circuit: {pr['rescaled_input']} -> {pr['rescaled_output']})")

        # --- attest on-chain --------------------------------------------
        decision_hash = keccak(f"loan-{i}-{decision}-reason-code-A34")
        shap_hash = keccak(json.dumps(canonical_shap_vector(top5), separators=(",", ":")))
        model_version = cast("format-bytes32-string", MODEL_VERSION)
        inst_arg = "[" + ",".join(str(x) for x in pr["instances"]) + "]"
        margin_wad = to_wad(margin)

        cast("send", attestation,
             "attest(bytes32,bytes32,uint256,int256,bytes32,bytes,uint256[])",
             decision_hash, shap_hash, str(to_wad(stated_conf)), str(margin_wad),
             model_version, pr["proof_hex"], inst_arg,
             "--private-key", OPERATOR_PK, "--rpc-url", RPC)

        att_id = cast("call", attestation, "idAt(uint256)(bytes32)",
                      str(len(results)), "--rpc-url", RPC).split()[0]
        print(f"  attested on-chain     : {att_id}")

        # --- dispute -----------------------------------------------------
        cast("send", pool, "openDispute(bytes32)", att_id,
             "--private-key", CLAIMANT_PK, "--rpc-url", RPC)

        preview = int(cast("call", pool, "previewSlash(bytes32,bool)(uint256)",
                           att_id, "true" if upheld else "false",
                           "--rpc-url", RPC).split()[0])

        before = int(cast("call", pool, "stakeOf(address)(uint256)",
                          operator_addr, "--rpc-url", RPC).split()[0])

        dispute_id = cast("call", pool, "disputeIdFor(bytes32)(bytes32)",
                          att_id, "--rpc-url", RPC).split()[0]

        print(f"  dispute opened        : {dispute_id}")
        print(f"  predicted slash       : {preview/WAD:.6f} ETH "
              f"({100*preview/before if before else 0:.4f}% of stake)")

        # --- ADMIN-ARBITRATED resolution (SIMULATED) --------------------
        cast("send", pool, "resolveDispute(bytes32,bool)", dispute_id,
             "true" if upheld else "false",
             "--private-key", OPERATOR_PK, "--rpc-url", RPC)

        after = int(cast("call", pool, "stakeOf(address)(uint256)",
                         operator_addr, "--rpc-url", RPC).split()[0])
        slashed = before - after
        claimant_bal = int(cast("balance", claimant_addr, "--rpc-url", RPC).split()[0])

        print(f"  RESOLVED: decision {'UPHELD' if upheld else 'OVERTURNED'}")
        print(f"  slashed               : {slashed/WAD:.6f} ETH "
              f"({100*slashed/before if before else 0:.4f}% of stake)")
        print(f"  operator stake        : {before/WAD:.4f} -> {after/WAD:.4f} ETH")
        print(f"  claimant balance      : {claimant_bal/WAD:.4f} ETH")

        assert slashed == preview, f"preview {preview} != actual {slashed}"

        results.append({
            "name": name, "row": i, "margin": margin,
            "decision": decision, "ground_truth": truth,
            "confidence": stated_conf, "outcome": "upheld" if upheld else "overturned",
            "slash_wei": slashed, "slash_pct": 100 * slashed / before if before else 0.0,
            "stake_before_wei": before, "stake_after_wei": after,
            "prove_s": pr["prove_s"], "attestation_id": att_id,
            "dispute_id": dispute_id,
        })

    # ---------- summary --------------------------------------------------
    print("\n" + "=" * 74)
    print("SUMMARY")
    print("=" * 74)
    print(f"{'scenario':26s} {'conf':>7s} {'outcome':>11s} {'slash ETH':>12s} {'% stake':>9s}")
    for r in results:
        print(f"{r['name']:26s} {r['confidence']:7.4f} {r['outcome']:>11s} "
              f"{r['slash_wei']/WAD:12.6f} {r['slash_pct']:8.4f}%")

    print()
    print("Compare the '% stake' column, not the ETH column: the three scenarios")
    print("run sequentially against ONE shrinking stake, so absolute ETH amounts")
    print("are not comparable across rows.")
    a, b, c = results[0]["slash_pct"], results[1]["slash_pct"], results[2]["slash_pct"]
    print(f"  confident+wrong ({b:.2f}%) > uncertain+wrong ({c:.2f}%) "
          f"> confident+correct ({a:.4f}%)")
    ok = b > c > a
    print(f"  ordering holds: {ok}")
    if not ok:
        print("  FAIL: the scenario ordering did not hold.")
        return 1
    print(f"  confident+wrong costs {b/a:,.0f}x confident+correct "
          f"and {b/c:.2f}x uncertain+wrong (as % of stake)")

    report = {"scenarios": results, "ordering_holds": ok, "notes": [
        "Slash percentages are of the stake remaining when each scenario ran.",
        "The three scenarios execute sequentially against one shrinking stake,",
        "so the '% of stake' column is the comparable one, not absolute ETH.",
        "",
        "Dispute outcomes are declared by an admin key on a local Anvil chain.",
        "There is no jury, no oracle, and no evidentiary standard.",
    ]}
    (ROOT / "artifacts" / "zk" / "phase5_report.json").write_text(json.dumps(report, indent=2))
    print(f"\nwrote {ROOT/'artifacts'/'zk'/'phase5_report.json'}")
    return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
