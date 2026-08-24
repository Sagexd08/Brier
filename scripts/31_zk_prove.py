"""Phase 3b: EZKL circuit generation, proving, and verification.

Every timing number printed here is measured with time.perf_counter around the
real call. Nothing is estimated.

Only the CALIBRATION HEAD is in-circuit. The base XGBoost classifier is not
proved and is not part of any circuit in this repo.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import ezkl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from brier.config import ZK

EZKL_CLI = Path(__file__).resolve().parents[1] / "tools" / "ezkl.exe"


def cli(*args: str) -> None:
    """Invoke the ezkl CLI (same version as the wheel).

    Two wheel functions -- get_srs and create_evm_verifier -- panic inside
    pyo3 on Windows with "The Python interpreter is not initialized" from a
    tokio worker thread. The CLI does not use the Python bindings and is
    unaffected.
    """
    import subprocess
    if not EZKL_CLI.exists():
        raise RuntimeError(
            f"ezkl CLI not found at {EZKL_CLI}. Download the v23.0.5 "
            "windows-msvc release from github.com/zkonduit/ezkl/releases "
            "and place the binary at tools/ezkl.exe."
        )
    r = subprocess.run([str(EZKL_CLI), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ezkl {args[0]} failed: {r.stderr[-400:]}")


SRS_URL = "https://kzg.ezkl.xyz/kzg{logrows}.srs"
SRS_CACHE = ZK / "srs"


def fetch_srs(logrows: int, dest: Path) -> Path:
    """Download (and cache) the public KZG SRS for `logrows`."""
    import urllib.request
    SRS_CACHE.mkdir(parents=True, exist_ok=True)
    cached = SRS_CACHE / f"kzg{logrows}.srs"
    if not cached.exists():
        url = SRS_URL.format(logrows=logrows)
        with urllib.request.urlopen(url, timeout=600) as r, open(cached, "wb") as f:
            shutil.copyfileobj(r, f)
    # The SRS header is the logrows value as a little-endian u32; verify it
    # rather than trusting the filename.
    head = cached.read_bytes()[:4]
    got = int.from_bytes(head, "little")
    if got != logrows:
        raise RuntimeError(f"SRS header says logrows={got}, expected {logrows}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached, dest)
    return dest


def timed(label, fn):
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    print(f"  {label:34s} {dt:8.2f}s")
    return out, dt


def _rejects(fn) -> bool:
    """True if the verifier rejected (returned False or raised)."""
    try:
        return fn() is False
    except Exception:
        return True


def check_soundness(d: Path, proof: Path, settings: Path, vk: Path, srs: Path) -> dict:
    """Tampered proofs must not verify.

    Note on writing these: `proof["proof"]` is a LIST OF INTS, not a hex
    string. An earlier version sliced it as a string, which silently changed
    nothing and made a no-op "tamper" look like a soundness hole.
    """
    base = json.loads(proof.read_text())
    checks = {}

    # (a) honest proof must verify
    checks["honest_proof_verifies"] = ezkl.verify(
        str(proof), str(settings), str(vk), str(srs)) is True

    # (b) tampered public output (the claimed confidence)
    t = json.loads(proof.read_text())
    inst = t["instances"][0]
    inst[-1] = "0" * len(inst[-1]) if isinstance(inst[-1], str) else int(inst[-1]) + 1
    pa = d / "tamper_output.json"; pa.write_text(json.dumps(t))
    checks["tampered_output_rejected"] = _rejects(
        lambda: ezkl.verify(str(pa), str(settings), str(vk), str(srs)))

    # (c) flipped byte at the start of the proof
    t = json.loads(proof.read_text())
    t["proof"][0] = (t["proof"][0] + 1) % 256
    assert t["proof"] != base["proof"]
    pb = d / "tamper_first.json"; pb.write_text(json.dumps(t))
    checks["tampered_proof_head_rejected"] = _rejects(
        lambda: ezkl.verify(str(pb), str(settings), str(vk), str(srs)))

    # (d) flipped byte in the middle of the proof
    t = json.loads(proof.read_text())
    mid = len(t["proof"]) // 2
    t["proof"][mid] = (t["proof"][mid] + 7) % 256
    assert t["proof"] != base["proof"]
    pc = d / "tamper_mid.json"; pc.write_text(json.dumps(t))
    checks["tampered_proof_body_rejected"] = _rejects(
        lambda: ezkl.verify(str(pc), str(settings), str(vk), str(srs)))

    return checks


def run_head(name: str, timeout_stage_s: float = 1800.0) -> dict:
    print(f"\n=== {name} ===")
    d = ZK / name
    d.mkdir(parents=True, exist_ok=True)

    onnx = ZK / f"{name}.onnx"
    settings = d / "settings.json"
    compiled = d / "model.compiled"
    pk, vk = d / "pk.key", d / "vk.key"
    witness, proof = d / "witness.json", d / "proof.json"
    srs = d / "kzg.srs"

    result = {"head": name, "stages": {}, "status": "ok"}
    try:
        # 1. settings
        run_args = ezkl.PyRunArgs()
        run_args.input_visibility = "public"    # the margin is committed on-chain
        run_args.output_visibility = "public"   # the confidence is attested
        run_args.param_visibility = "fixed"     # weights are baked into the circuit
        _, t = timed("gen_settings", lambda: ezkl.gen_settings(str(onnx), str(settings), py_run_args=run_args))
        result["stages"]["gen_settings_s"] = t

        # 2. calibrate settings against real margins
        _, t = timed("calibrate_settings", lambda: ezkl.calibrate_settings(
            str(ZK / "calibration_data.json"), str(onnx), str(settings), "resources"))
        result["stages"]["calibrate_settings_s"] = t

        cfg = json.loads(settings.read_text())
        logrows = int(cfg["run_args"]["logrows"]) if "logrows" in cfg.get("run_args", {}) else int(cfg.get("logrows", 0))
        result["logrows"] = logrows
        result["circuit_rows"] = 2 ** logrows if logrows else None
        print(f"  logrows = {logrows}  (circuit rows = 2^{logrows} = {2**logrows if logrows else '?'})")

        # 3. compile
        _, t = timed("compile_circuit", lambda: ezkl.compile_circuit(str(onnx), str(compiled), str(settings)))
        result["stages"]["compile_s"] = t

        # 4. SRS
        # ezkl.get_srs() is unusable in this wheel: the pyo3 binding panics with
        # "The Python interpreter is not initialized" from a tokio worker
        # thread on Windows. The call only downloads a public structured
        # reference string, so we fetch it over HTTP from the same endpoint the
        # binary uses (https://kzg.ezkl.xyz/kzg{logrows}.srs) and cache it.
        # This changes nothing cryptographically -- it is the same public SRS
        # from the same source; only the transport differs.
        _, t = timed("get_srs (http)", lambda: fetch_srs(logrows, srs))
        result["stages"]["get_srs_s"] = t
        result["srs_bytes"] = srs.stat().st_size

        # 5. setup
        _, t = timed("setup (keygen)", lambda: ezkl.setup(str(compiled), str(vk), str(pk), str(srs)))
        result["stages"]["setup_s"] = t

        # 6. witness
        _, t = timed("gen_witness", lambda: ezkl.gen_witness(str(ZK / "input.json"), str(compiled), str(witness)))
        result["stages"]["witness_s"] = t

        # 7. PROVE  <- the headline number
        _, t = timed("prove", lambda: ezkl.prove(str(witness), str(compiled), str(pk), str(proof), str(srs)))
        result["stages"]["prove_s"] = t
        result["proving_time_s"] = t
        result["proof_bytes"] = proof.stat().st_size

        # 8. VERIFY
        ok, t = timed("verify", lambda: ezkl.verify(str(proof), str(settings), str(vk), str(srs)))
        result["stages"]["verify_s"] = t
        result["verify_ok"] = bool(ok)
        print(f"  verification result: {ok}")

        result["pk_bytes"] = pk.stat().st_size
        result["vk_bytes"] = vk.stat().st_size

        # 9. SOUNDNESS: a verifier that accepts everything is worthless, so
        # assert that tampered proofs are rejected. Each case must either
        # return False or raise -- returning True is a hard failure.
        result["soundness"] = check_soundness(d, proof, settings, vk, srs)
        print(f"  soundness checks: {result['soundness']}")
        if not all(result["soundness"].values()):
            raise RuntimeError(f"SOUNDNESS FAILURE: {result['soundness']}")

        # 10. EVM verifier contract + calldata (used by Phase 4/5).
        # ezkl.create_evm_verifier() hits the same pyo3 "no running event loop"
        # panic as get_srs, so we shell out to the ezkl CLI at the SAME version
        # (23.0.5). Identical code path, no Python bindings involved.
        sol = d / "Verifier.sol"
        _, t = timed("create_evm_verifier (cli)", lambda: cli(
            "create-evm-verifier", "--srs-path", str(srs),
            "--settings-path", str(settings), "--vk-path", str(vk),
            "--sol-code-path", str(sol), "--abi-path", str(d / "verifier.abi")))
        result["stages"]["create_evm_verifier_s"] = t
        result["evm_verifier_bytes"] = sol.stat().st_size
        result["evm_verifier"] = str(sol)

        calldata = d / "calldata.bytes"
        _, t = timed("encode_evm_calldata (cli)", lambda: cli(
            "encode-evm-calldata", "--proof-path", str(proof),
            "--calldata-path", str(calldata)))
        result["stages"]["encode_calldata_s"] = t
        result["calldata_bytes"] = calldata.stat().st_size
    except Exception as e:
        result["status"] = "failed"
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"  FAILED: {result['error']}")
    return result


def main() -> int:
    results = [run_head("temperature_head"), run_head("mlp_head")]
    (ZK / "phase3_raw.json").write_text(json.dumps(results, indent=2))
    print("\n--- summary ---")
    for r in results:
        if r["status"] == "ok":
            print(f"  {r['head']:18s} logrows={r.get('logrows')} "
                  f"prove={r.get('proving_time_s',0):.2f}s "
                  f"verify_ok={r.get('verify_ok')} proof={r.get('proof_bytes')}B")
        else:
            print(f"  {r['head']:18s} FAILED: {r['error'][:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
