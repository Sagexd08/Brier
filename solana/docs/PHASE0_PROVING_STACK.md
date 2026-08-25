# Phase 0 — Solana proving stack validation

Status of each Phase 0 item, with sources. Written before any program code so
that the feasibility constraints shape the design rather than being discovered
mid-build.

## Why the proving system changes

The EVM implementation proves the calibration head as a **Halo2/KZG circuit
compiled by EZKL**, verified by an EZKL-generated Solidity verifier. That path
does not exist on Solana: there is no production Halo2/KZG verifier for the
Solana runtime.

This port therefore uses a different proving system:

| | EVM (`v0-evm`) | Solana (this port) |
|---|---|---|
| Proving system | Halo2 + KZG (EZKL 23.0.5) | SP1 zkVM, wrapped to Groth16 |
| What is proved | an arithmetic circuit compiled from ONNX | a **Rust program executed in a zkVM** |
| Verifier | EZKL-generated Solidity (`Halo2Verifier.sol`) | `sp1-solana` (BN254 syscalls) |
| Cost unit | gas | compute units (CU) |

The calibration head stops being a circuit and becomes a Rust program. **No EVM
measurement transfers.** Anything below that is not marked MEASURED is not a
result.

## Compute-unit budget — MEASURED FROM DOCS, NOT YET FROM A RUN

| Fact | Value | Source |
|---|---|---|
| Default CU limit per instruction | 200,000 | [Solana docs — Compute Budget](https://solana.com/docs/core/fees/compute-budget) |
| Max CU per **transaction** (via `SetComputeUnitLimit`) | 1,400,000 | same |
| sp1-solana verifier deployment | ~280,000 CU | [succinctlabs/sp1-solana](https://github.com/succinctlabs/sp1-solana) |
| Groth16 verification (general range) | 170,000–500,000 CU | vendor/ecosystem docs, circuit-dependent |

**Conclusion: CU is not the binding constraint.** Groth16 verification fits
inside a single transaction once the limit is raised from the 200K default to
the 1.4M ceiling. The verifier's own ~280K deployment cost already exceeds the
*default*, which is why raising the limit is mandatory rather than optional.

### The actual binding constraint is transaction size

A Solana transaction is capped at **1232 bytes**. A Groth16 proof is **260
bytes**. The remainder must carry the public inputs, the instruction data, and
the account metas.

For this design that is survivable — the calibration head's public interface is
one input (a margin) and one output (a calibrated logit). It would *not* be
survivable for a design that published a large public-input vector, and that is
a real architectural constraint the EVM version never faced (calldata there was
3,300 bytes and no equivalent hard cap applied).

## Prover hardware — GAP, EXPLICITLY NOT MEASURED

Succinct's published requirements for **Groth16** proving
([hardware requirements](https://docs.succinct.xyz/docs/sp1/getting-started/hardware-requirements)):

| Resource | Required for Groth16 | This machine |
|---|---|---|
| CPU cores | **16+** ("more is better") | **6 cores / 12 threads** |
| RAM | **16 GB+**; final wrapping step needs ~14 GB | 23.3 GB total, ~4.5 GB free at time of check |
| Disk | 10 GB+ | 196 GB free — OK |
| GPU (optional) | CUDA CC >= 8.0, 24 GB VRAM, **Linux x86_64 only** | Windows host, no eligible GPU |

**Verdict: proof GENERATION is not performed in this build.** The machine is
below the documented core count, and GPU proving is unavailable on this
platform. Succinct's own documentation recommends the hosted Prover Network for
non-trivial programs.

Consequences, stated plainly so nothing downstream is misread:

- **SP1 proving time on Solana: NOT MEASURED.** There is no number to report,
  and the EVM's 2.13 s figure is a Halo2/EZKL measurement that says nothing
  about SP1.
- **Phase 2's parameter sweep: NOT MEASURED.** The comparative question — is
  SP1's cost curve overhead-dominated like Halo2's, or does it scale with
  executed cycles? — remains **open**. A zkVM charges per RISC-V cycle, so a
  different curve is expected, but expectation is not measurement and no curve
  is claimed here.
- **On-chain verification CU: measurable without local proving**, using a
  fixture proof, and is treated as a separate item from generation.

To close this gap, either (a) a Succinct Prover Network API key, or (b) a
machine meeting the 16-core / 16 GB floor. Everything else in the port is built
and testable without it.

## What Phase 0 delivers

- [x] Toolchain versions and CU budget confirmed against current sources.
- [x] Transaction-size constraint identified as the real limit (not CU).
- [x] Prover-hardware gap quantified against published requirements.
- [x] EVM implementation preserved for comparison (`v0-evm` tag,
      `v0-evm-reference` branch).
- [ ] **Hello-world SP1 proof generated locally** — blocked by prover hardware.
- [ ] **End-to-end on-chain verification CU recorded from a real run** — pending
      a fixture proof.

Items left unchecked are gaps, not omissions. They are repeated in the changelog
and in the proposal's Solana section rather than being quietly dropped.
