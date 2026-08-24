# Brier — Confidence-Calibrated AI Decision Insurance (MVP)

An on-chain insurance mechanism that slashes AI model operators in proportion to
**miscalibration**, not merely error, on a single deterministic decision class:
automated loan-rejection reason codes.

> **Status: research MVP / technical demo.** Parts of this are real cryptography
> and real trained models. Parts are deliberately simulated. The
> [What's real vs. simulated](#whats-real-vs-simulated-in-this-mvp) table is the
> authoritative list — read it before drawing any conclusion from this repo.

## The core idea

A model that is wrong is not necessarily a problem. A model that is wrong *while
claiming 99% confidence* is a different kind of problem, and it is the kind
existing accountability mechanisms handle badly. Flat penalties ("you were
wrong, pay X") give an operator no reason to report honest uncertainty — under a
flat penalty an operator is never punished for overclaiming.

Brier prices the confidence itself, using a strictly proper scoring rule:

```
slash = stake * (confidence - outcome)^2      (capped)
```

Because the rule is strictly proper, expected loss is minimised exactly when the
reported confidence equals the operator's true subjective probability.
Overconfidence is expensive, honest uncertainty is cheap, and hedging every
decision at 0.5 is mediocre rather than free. That claim is not asserted here —
it is [verified as a unit test](contracts/test/BrierMath.t.sol) at two separate
probabilities.

## Headline measured results

Every number below was produced by the scripts in this repo. None is estimated.
Full detail in [`RESULTS.md`](RESULTS.md).

| | Measured |
|---|---|
| Calibration: ECE on held-out test | **0.2164 → 0.1111** (48.7% reduction) |
| Learned temperature | **T = 3.01** (T>1 confirms the base model was overconfident) |
| zk proving time (calibration head) | **~2.0 s** per decision, laptop CPU, no GPU |
| On-chain proof verification | **684,696 gas** (≈ $62 at 30 gwei / $3k ETH) |
| Tests | **48 Solidity + 29 Python, all passing** |

End-to-end demo, three scenarios against a local chain, as a share of stake:

| Scenario | Confidence | Outcome | Slash (% of stake) |
|---|---|---|---|
| Confident + correct | 0.9845 | upheld | **0.024%** |
| Confident + wrong | 0.9367 | overturned | **87.75%** |
| Uncertain + wrong | 0.5012 | overturned | **25.12%** |

Confident-and-wrong costs **3,667x** confident-and-correct and **3.49x**
uncertain-and-wrong. That spread is the entire product.

## Decision loop

1. Base classifier produces an approve/reject decision on a loan application.
2. A small **calibration head** maps the base model's logit to a calibrated confidence.
3. SHAP attributions over the top-5 features form an explainability vector.
4. Decision hash + confidence + SHAP hash + model version are attested on-chain.
5. A zk proof attests that **the calibration head only** ran correctly on that logit.
6. On a dispute resolving against the decision, stake is slashed by the Brier formula.

## What is and is not zk-proved

**Only the calibration head is proved in zero knowledge.** The base classifier is
*not* proved in-circuit, and this repo never claims otherwise.

What the proof establishes: given a logit committed on-chain, the calibration
head identified by this verifying key maps it to the attested confidence.

What the proof does **not** establish: that the logit came from the claimed base
model, that the base model was trained as described, or that the applicant's
features were reported truthfully. **An operator who fabricates the input logit
still produces a perfectly valid proof.** Closing that gap requires proving the
base classifier in-circuit, which this MVP does not attempt.

This is a load-bearing limitation, not a footnote. Any claim that "the AI
decision is zero-knowledge proved" would be false against this architecture.

## What's real vs. simulated in this MVP

| Component | Status | Notes |
|---|---|---|
| Dataset | **Real** | UCI Statlog German Credit, 1,000 real credit applications. |
| Base classifier | **Real** | Trained XGBoost, held-out evaluation. Deliberately overfit — see below. |
| Calibration head | **Real** | Trained on a split disjoint from both train and test. |
| ECE / reliability | **Real, measured** | Including a control run proving the split matters. |
| SHAP vectors | **Real** | `shap` TreeExplainer, additivity-checked, deterministic. |
| zk proof of calibration head | **Real cryptography** | EZKL 23.0.5 / halo2. Real proving, real verification, tamper-tested. |
| zk proof of base classifier | **NOT BUILT** | Out of scope by design. Never claimed. |
| Smart contracts | **Real Solidity** | Foundry, 48 tests, real proof verified on-chain. |
| Chain | **Simulated** | Local Anvil devnet. Not a testnet, not mainnet. |
| **Dispute resolution** | **SIMULATED** | A single admin address decides every outcome. **No jury, no oracle, no evidentiary standard, no appeals.** The largest gap to anything deployable. |
| Staking economics | **Simulated** | Demonstration parameters, not actuarial. |
| Operator identity / KYC | **NOT BUILT** | Operators are bare addresses. |
| Unbonding period | **NOT BUILT** | An operator can withdraw stake before a dispute is opened. Real vulnerability, documented not fixed. |
| Legal / regulatory wrapper | **NOT BUILT** | See [Path to production](docs/PATH_TO_PRODUCTION.md). |

### On the base model's 71.5% accuracy

The base classifier is trained in a **deliberately overfit regime** (depth-8
trees, no regularisation, train accuracy 1.0000 vs test 0.7150). This is not a
tuned model and its accuracy is not a selling point.

The reason is honest: demonstrating a calibration-insurance mechanism on an
already-well-calibrated model would prove nothing. The overfit regime reproduces
the realistic condition — deployed models are routinely overconfident — that
makes calibration worth insuring. Stated in [`docs/PHASE1.md`](docs/PHASE1.md)
as well, so it cannot be missed.

## Bugs this build actually caught

Recorded because they are the useful part of a technical demo:

- **A `nan`-diverged calibration fit** silently produced finite-looking
  probabilities and a published ECE. The optimiser now uses a strong-Wolfe line
  search, keeps the best finite iterate, and raises on divergence.
- **A wrong data encoding that SHAP caught.** `credit_history` was ordered by a
  naive reading of the codebook, but "no credits taken" has a **62.5%** bad rate
  versus **17.1%** for "critical account/other credits existing" — a thin file
  is riskier than a thick serviced one. The model was right; the encoding was
  wrong. Accuracy and ECE did not surface this; the explainability layer did.
- **A soundness test that silently passed.** `proof["proof"]` is a list of ints,
  not a hex string; slicing it as a string changed nothing and "verified" an
  untampered proof. The test now asserts the tamper actually mutated the proof.
- **A circuit that could not represent 3 of 200 real inputs.** EZKL was
  calibrated on a 64-row subset whose range excluded the most extreme margins;
  proving one failed outright. Now calibrated across the full range with 20%
  padding — verified at **200/200**.

## Repository layout

```
src/brier/        Library: data, models, calibration, metrics, SHAP
scripts/          Numbered, runnable pipeline stages (10 → 90)
contracts/        Foundry: BrierMath, Attestation, StakePool + EZKL verifier
tests/            Python tests (metrics known-answer, phase correctness)
docs/             Per-phase notes, design decisions, path to production
RESULTS.md        Measured numbers (generated, never hand-edited)
```

## Reproducing

```bash
pip install -r requirements.txt

python scripts/10_train_calibrate.py    # train + ECE gate
python scripts/11_reliability_plot.py   # reliability diagram
python scripts/20_explain.py            # SHAP + sanity checks
python scripts/30_export_onnx.py        # ONNX export (fidelity-checked)
python scripts/31_zk_prove.py           # circuits, proofs, soundness
cd contracts && forge test              # 48 contract tests

# End-to-end demo (needs a local chain)
anvil &
forge script script/Deploy.s.sol:Deploy --rpc-url http://127.0.0.1:8545 --broadcast
python scripts/40_demo_e2e.py
python scripts/90_render_results.py     # regenerate RESULTS.md
```

Requires the EZKL CLI v23.0.5 at `tools/ezkl.exe` (two functions in the Python
wheel panic inside pyo3 on Windows — see [`docs/PHASE3.md`](docs/PHASE3.md)) and
Foundry on `PATH`.

## From MVP to something an insurer or regulator would take seriously

The mechanism design is the easy part and is essentially done: the Brier rule is
correct, monotonic in miscalibration, and verified proper. **Four things stand
between this and a real product, and none is a coding task.** First, the dispute
layer must stop being a single admin key: loan rejections have an unobservable
counterfactual (a rejected applicant never demonstrates repayment), so
production needs a defined evidentiary standard — regulator findings, successful
appeals, or lender outcome data on overturned decisions — plus independent
adjudicators with economic security exceeding the value at risk, an appeals
path, and a statute of limitations measured in months. Second, the proof must
cover the pipeline rather than one component: today an operator can fabricate an
input logit and still produce a valid proof, so the base classifier needs to be
committed and proved (expensive for tree ensembles) or attested through trusted
execution. Third, the economics need actuarial work rather than invented
constants, with specific attention to **correlated tail risk** — one bad model
version produces thousands of simultaneous correlated claims, unlike the
independent risks insurance pools assume, and can wipe out a pool. Fourth, gas:
at 684,696 gas per verification this costs ~$62 per decision on L1, which needs
an L2 and proof aggregation. Underneath all of it sits the fairness gap that
matters most for this use case: a model can be well calibrated overall and badly
miscalibrated *within* a protected group, which is precisely the harm this
mechanism should catch and currently does not measure.

## Licence and data provenance

Code: MIT. The UCI German Credit dataset is downloaded at build time and is not
redistributed here.

**Fairness note.** The source data encodes a protected attribute (Attribute 9
combines personal status and sex). It is **excluded from the feature set by
default**. This is a minimum bar, not a fairness solution: proxy discrimination
through correlated features is untested, and no fairness audit has been
performed.
