# Brier — Confidence-Calibrated AI Decision Insurance (MVP)

An on-chain insurance mechanism that slashes AI model operators in proportion to
**miscalibration**, not merely error, on a single deterministic decision class:
automated loan-rejection reason codes.

> **Status: research MVP / technical demo.** Real cryptography and real trained
> models in places, deliberately simulated in others. Start with
> [What this proves and doesn't prove](#what-this-proves-and-doesnt-prove).

## The paper

**[Confidence as Collateral: Strictly Proper Slashing for Accountable Automated
Decisions](PAPER.md)** — the full write-up, also rendered as
[a PDF](landing/brier-proposal.pdf). Preprint; the venue reasoning and three
open submission gates are in [`docs/VENUE.md`](docs/VENUE.md).

The central result is negative: a proved calibration head is **not** sufficient
for a trustworthy attestation, because the proof binds the map from logit to
confidence and nothing else. An operator that fabricates the input logit obtains
a proof that verifies.

## The numbers

Everything below was produced by the scripts in this repo on a laptop CPU. None
is estimated, extrapolated, or copied from a paper. Detail in
[`RESULTS.md`](RESULTS.md).

| | Measured |
|---|---|
| zk proving time (calibration head) | **2.09 s**, flat from 1 to 16,897 params, no GPU |
| On-chain proof verification | **684,696 gas** (≈ $62 at 30 gwei / $3k ETH) |
| Verifier deployment | **2,942,192 gas**, one-off |
| Proving key size | **132 MiB** per head (operator-side, not on-chain) |
| Calibration: ECE on held-out test | **0.1853 ± 0.0248 → 0.0870 ± 0.0218** (mean ± std over 10 pinned seeds; 52.8% ± 10.3% reduction) |
| Learned temperature | **T = 3.47 ± 0.45** (T > 1 in every seed, confirming the base model was overconfident) |
| Tests | **144 Solidity + 98 Python + 11 middleware, all passing** |

End-to-end, three scenarios against a local chain, as a share of stake:

| Scenario | Confidence | Outcome | Slash (% of stake) |
|---|---|---|---|
| Confident + correct | 0.9845 | upheld | **0.024%** |
| Confident + wrong | 0.9367 | overturned | **87.75%** |
| Uncertain + wrong | 0.5012 | overturned | **25.12%** |

Confident-and-wrong costs **3,667x** confident-and-correct and **3.49x**
uncertain-and-wrong.

## Two results that went against the mechanism

Recorded here rather than only in the paper, because a repository that
advertises only its confirmations is not evidence of much.

**The unbonding period is worse than v0 admitted.** Deriving it from the FCRA
statutory chain rather than convenience gives 105 days, not the 7 used in tests
(60-day file window + 30-day reinvestigation + 15-day extension). At that
length, capital lockup — not the slash — becomes an operator's dominant cost,
by roughly 8× at a 1% dispute rate. That substantially weakens the argument
that calibration pays for itself. See
[`docs/UNBONDING_PERIOD_JUSTIFICATION.md`](docs/UNBONDING_PERIOD_JUSTIFICATION.md).

**The subgroup-calibration gap could not be measured here, so the contract for
it was not built.** Within-group ECE exceeds aggregate ECE in 10/10 seeds — but
a permutation null reproduces the entire effect (Wilcoxon p = 0.92), because
ECE is biased upward at small n: a model calibrated *by construction* scores
0.1188 at n = 68, above this pipeline's aggregate ECE of 0.0870. The dataset
cannot answer the question either way, so the limitation stays open and
`SubgroupReputationRegister.sol` does not exist. `tests/test_subgroup_calibration.py`
pins the null so it cannot be eroded by quietly shrinking a threshold.

## What this proves and doesn't prove

**The trust-model gap, stated first.** The zk proof covers the **calibration
head only** — a 1-parameter temperature scaler, or a 321-parameter MLP, mapping
one logit to one confidence. The base classifier that actually decides the loan
is **not in-circuit**. The proof binds this statement and no larger one:

> *given a logit committed on-chain, the head identified by this verifying key
> maps it to the attested confidence.*

The logit is an unverified input. **An operator who fabricates it produces a
proof that verifies perfectly.** Nothing forces the number entering the circuit
to have come from the claimed model, from the applicant's real features, or from
any model at all. Verifying the honest link says nothing about the link carrying
the weight — here, the base classifier. Any claim that "the AI decision is
zero-knowledge proved" is false against this architecture.

**What is genuinely demonstrated.** Miscalibration is measurable and correctable
on real data — ECE 0.1853 → 0.0870 averaged over 10 pinned seeds, reduced in
**every** seed, with a control run showing that fitting on the wrong split makes
it *worse* than not calibrating at all (also in every seed). A proper scoring
rule works in fixed-point Solidity, monotonicity and properness verified
numerically rather than argued. Proving a calibration head is cheap, and the
16,897-parameter head costs the same as the 1-parameter one (measured across a
10-point sweep spanning 4 orders of magnitude, all at logrows=15) because fixed
lookup overhead dominates — though only up to the circuit's capacity, which the
sweep does not cross. The proof verifies on a real EVM, with tampered proofs,
tampered outputs, and wrong verifying keys all rejected.

**What the numbers say about viability.** 684,696 gas is ~33x a plain transfer,
~$62 per decision on L1, and the Brier arithmetic is ~543 gas of it — the cost
is almost entirely halo2 verification. This needs an L2 and proof aggregation
before it is economic; neither is implemented here.

**What is not built at all:** proving the base classifier, decentralized dispute
resolution (a single admin key decides every outcome), an unbonding period (an
operator can withdraw stake before a dispute opens), actuarial economics, and
any legal wrapper. Full breakdown in
[What's real vs. simulated](#whats-real-vs-simulated-in-this-mvp).

**Two things a reviewer will notice, said before they have to ask.** The base
model scores 71.5% on test against 100% on train — it is *deliberately* overfit,
because demonstrating a calibration-insurance mechanism on an already-calibrated
model would prove nothing, and its accuracy is not a selling point. And the
three demo scenarios run sequentially against one shrinking stake, so the
percentage column is the comparable one; the absolute ETH figures are not.

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

## Decision loop

1. Base classifier produces an approve/reject decision on a loan application.
2. A small **calibration head** maps the base model's logit to a calibrated confidence.
3. SHAP attributions over the top-5 features form an explainability vector.
4. Decision hash + confidence + SHAP hash + model version are attested on-chain.
5. A zk proof attests that **the calibration head only** ran correctly on that logit.
6. On a dispute resolving against the decision, stake is slashed by the Brier formula.

## Diagrams

Generated from the repo's own artifacts; sources in [`figures/`](figures/) and
regenerable via `scripts/91_figure_d_reliability.py` and `scripts/92_render_svg.py`.

### Component architecture

Solid = implemented and measured here. Dashed amber = specified, not built. Red
= the single component inside the zk circuit.

![Component architecture](figures/figure-a-architecture.png)

### Protocol sequence

![Protocol sequence](figures/figure-b-sequence.png)

### Trust boundaries

The three assurance tiers. Only tier 1 is cryptography; tier 2 is currently
**unenforced**; tier 3 is a single key. Each weakness names the test in
[`contracts/test/ThreatModel.t.sol`](contracts/test/ThreatModel.t.sol) that
demonstrates it.

![Trust boundaries and threat model](figures/figure-c-threat-model.png)

### Proving cost vs head size

Proving time is flat across 4 orders of magnitude of parameters, while circuit
rows used scale linearly with them.

![Proving cost vs calibration-head size](figures/figure-e-circuit-sweep.png)

### Calibration reliability

Bin values read directly from `artifacts/calibration/phase1_report.json` — no
curve is fitted or smoothed.

![Calibration reliability](figures/figure-d-calibration.png)

## Closing the trust-model gap

The gap itself is stated in
[What this proves and doesn't prove](#what-this-proves-and-doesnt-prove). What
it would take to close:

- **Prove the base classifier in-circuit.** Honest but expensive for tree
  ensembles today — a depth-8, 400-tree XGBoost is orders of magnitude beyond
  the 2^15-row circuit used here.
- **Or commit to the inputs.** Bind the feature vector and model weights to a
  hash the applicant or a regulator can independently check, so a fabricated
  logit is detectable even when it is not proved.
- **Or attest the base model through trusted execution**, accepting a hardware
  trust assumption instead of a cryptographic one.

The third is the only one that is cheap today, and it is a strictly weaker
guarantee. Whichever path is taken, the honest description of the current
system remains *"the calibration step is proved"* — not *"the decision is
proved"*.

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
| Smart contracts | **Real Solidity** | Foundry, 144 tests, real proof verified on-chain. |
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
src/brier/        Library: data, models, calibration, metrics, SHAP, subgroup
scripts/          Numbered, runnable pipeline stages (10 → 95)
contracts/        Foundry: BrierMath, Attestation, StakePool + EZKL verifier
x402-middleware/  Reference x402 integration: attestation gate (Express/Hono)
tests/            Python tests (metrics known-answer, phase correctness)
docs/             Per-phase notes, design decisions, path to production
RESULTS.md        Measured numbers (generated, never hand-edited)
ABLATION.md       Five enhancements ablated against the baseline (generated)
PAPER.md          The paper: mechanism, market model, results, limitations
RELATED_WORK_V2.md  The agentic-payments literature, classified
CHANGELOG.md      Proposal -> paper: what changed and why
```

## Reproducing

```bash
pip install -r requirements.txt

python scripts/10_train_calibrate.py    # train + ECE gate
python scripts/11_reliability_plot.py   # reliability diagram
python scripts/20_explain.py            # SHAP + sanity checks
python scripts/30_export_onnx.py        # ONNX export (fidelity-checked)
python scripts/31_zk_prove.py           # circuits, proofs, soundness
cd contracts && forge test              # 144 contract tests

# End-to-end demo (needs a local chain)
anvil &
forge script script/Deploy.s.sol:Deploy --rpc-url http://127.0.0.1:8545 --broadcast
python scripts/40_demo_e2e.py
python scripts/90_render_results.py     # regenerate RESULTS.md

# v1: the agentic-payments work
python scripts/21_subgroup_adversary.py  # subgroup null + ECE noise floor
python scripts/22_market_model.py        # welfare model (paper §4)
cd x402-middleware && npm install && npm test   # gates against a live chain
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
