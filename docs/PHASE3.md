# Phase 3 — zk proof of the calibration head

## Scope — read this first

**Only the calibration head is in-circuit.** The base XGBoost classifier is not
proved and appears in no circuit in this repo. The proof establishes:

> given a margin `m` committed on-chain, the calibration head identified by
> this verifying key maps `m` to the attested confidence `c`.

It does **not** establish that `m` came from the claimed base model, that the
base model was trained as described, or that the applicant's features were
reported honestly. An operator who fabricates `m` gets a perfectly valid proof.

## Stack

EZKL 23.0.5 (halo2 + KZG, BN254). Public SRS from the EZKL ceremony endpoint.
Input and output are **public** (the margin is committed on-chain, the
confidence is attested); model parameters are **fixed** in the circuit, so the
verifying key identifies the exact head that ran.

## Design choices that made this cheap

1. **The head outputs a logit, not a probability.** The sigmoid is applied
   off-circuit. Circuits are affine + ReLU only — no transcendental in-circuit.
2. **Static shapes, batch size 1.** One proof per decision. A dynamic batch axis
   leaves an undetermined symbol that EZKL's tract frontend rejects outright.
3. **Weights inline in the ONNX file, not external.** ~2.5 KB.
4. **321 parameters.** Well under the 10k ceiling.

## Result: no fallback was needed

The build plan anticipated falling back to 1-parameter temperature scaling if
an MLP circuit proved infeasible. **It did not prove infeasible.** Both heads
are built, proved, and verified; measured numbers are in `RESULTS.md`.

The reason both cost the same is that at logrows=15 the circuit is dominated by
fixed lookup-table and column overhead, not by the 321 multiply-adds. Parameter
count is simply not the binding constraint at this scale — a useful negative
result for anyone sizing a calibration head for circuit budget.

## Soundness is tested, not assumed

A verifier that returns `True` unconditionally would pass a naive "it verifies!"
check. Four cases run on every execution, and a `True` from any tampered case
fails the build:

| Case | Required | Observed |
|---|---|---|
| Honest proof | verifies | verifies |
| Tampered public output (claimed confidence) | rejected | rejected — constraint system not satisfied |
| Flipped byte at proof head | rejected | rejected — invalid EC point encoding |
| Flipped byte mid-proof | rejected | rejected — constraint system not satisfied |
| Wrong verifying key | rejected | rejected — constraint system not satisfied |

An earlier version of the byte-flip test was **broken and silently passed**:
`proof["proof"]` is a list of ints, not a hex string, so slicing it as a string
changed nothing and "verified" an untampered proof. The test now asserts the
tamper actually mutated the proof before verifying.

## Honest constraints

- **Proving key is 138 MB** per head. Fine for an operator, but it is not
  something a browser or a light client holds.
- **Proving is ~2s per decision** on a laptop CPU, no GPU. At scale this is a
  real per-decision cost, though it parallelises trivially across decisions.
- **The proof attests the QUANTISED computation.** At input_scale=13 /
  param_scale=13 the in-circuit fixed-point head differs from the float head by
  up to ~4.2e-04. The on-chain confidence is therefore the quantised one. For a
  Brier-score slash this is far below the noise floor of the decision itself,
  but it is not zero and should not be described as "the same computation".

## A packaging bug worth recording

Two functions in the ezkl **23.0.5 Windows wheel** — `get_srs` and
`create_evm_verifier` — panic inside pyo3:

```
The Python interpreter is not initialized and the `auto-initialize`
feature is not enabled  (thread 'tokio-runtime-worker')
```

Both are tokio-backed. Workarounds, neither of which changes the cryptography:

- `get_srs` → fetch the public SRS over HTTP from the same endpoint the binary
  uses (`https://kzg.ezkl.xyz/kzg{logrows}.srs`), and verify the logrows value
  in the file header rather than trusting the filename.
- `create_evm_verifier` → shell out to the ezkl **CLI at the identical version
  23.0.5** (`tools/ezkl.exe`), which does not use the Python bindings.

The generated verifier is 73 KB of Solidity with 3,300 bytes of calldata per
proof. On-chain verification gas is measured in Phase 4 — a 73 KB verifier is
large and the gas cost is the number that matters, so it is measured rather
than guessed.
