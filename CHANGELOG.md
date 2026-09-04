# v0 → v1: from proposal to paper

v0 (`PROPOSAL.md`) was a research proposal: a mechanism-design result with a
measured prototype, scoped to credit decisions, organised around questions it
intended to answer. v1 (`PAPER.md`) is a paper — the same evidence, restructured
around what the measurements found, plus an economic framework and four items
closed from v0's own sequencing table.

**Two of those four closed against the mechanism.** Both are reported at the
same visibility as the results that favour it, because a document that only
reports confirmations is not evidence of anything.

## What "proposal to paper" changed structurally

| Aspect | v0 proposal | v1 paper |
|---|---|---|
| Title | *What Does the Proof Actually Buy?* | *Confidence as Collateral: Strictly Proper Slashing for Accountable Automated Decisions* |
| §1.3 | Five questions and the evidence that *would* answer them | Six questions, each with its answer and the evidence that settled it |
| §1.4 | Six contributions | Ten, grouped mechanism / market / systems / **negative results** |
| §9 | "Proposed work" — deliverables and intentions | "Open problems" — what would close each gap, and which two this work closed |
| §7.5–§7.9 | Five per-phase ablation sections in the body | Condensed to a verdict table in §7.5; detail moved to **Appendix A** |
| Voice | "this proposal argues…" | paper voice throughout |
| Status | Version v0 (prototype) | Preprint, arXiv `cs.CR` (cross-list `cs.GT`) |

Section numbers moved twice. v0's §4–§9 became §5–§10 when the economic
framework was inserted as §4; then §7.10–§7.12 became §7.6–§7.8 when the
ablations moved to the appendix. All cross-references were remapped and checked
programmatically — the check surfaced three citations of §7.5 for the realised
Brier score that were **already wrong in v0**, since that figure is reported in
§7.1.

`docs/VENUE.md` records the venue reasoning and lists three submission gates
that are **not** met.

---

## Summary

| # | Change | Where | Evidence |
|---|---|---|---|
| 1 | New §2.5 on the agentic-payments literature | §2.5 | `RELATED_WORK_V2.md`, 9 works classified |
| 2 | Positioning table gains 4 rows and an x402-native axis | §2.6 | Cited sources |
| 3 | **New §4: economic framework**, 4 propositions | §4 | `scripts/22_market_model.py` |
| 4 | ERC-8004 reputation mirror | §5.1, §7.8 | `ERC8004ReputationAdapter.sol`, 13 tests |
| 5 | x402 reference middleware | §2.5, §7.8 | `x402-middleware/`, 11 live-chain tests |
| 6 | **Unbonding period derived — result is unfavourable** | §8.3, §9.1 | `docs/UNBONDING_PERIOD_JUSTIFICATION.md` |
| 7 | **Subgroup calibration: null result, on-chain half not built** | §8.4, §9.4 | `scripts/21_subgroup_adversary.py`, 11 tests |
| 8 | Test counts corrected, 3 suites added to the table | §7.8 | Live runs |
| 9 | Claim-vocabulary guard extended | `tests/test_claim_vocabulary.py` | 6 new abuse-bounding tests |
| 10 | Abstract and conclusion state the x402 contribution | Abstract, §10 | — |

Section numbering shifted: v0's §4–§9 are v1's §5–§10, because §4 is new.

---

## 1–2. Related work and positioning (§2.5, §2.6)

`RELATED_WORK_V2.md` scans nine required works plus the x402 V2 spec and
classifies each as a substitute, a complement, or orthogonal.

**The distribution is the finding.** Six of nine are orthogonal or
complementary, because the agentic-payments literature is overwhelmingly about
whether payment is correctly bound to service *delivery* — A402's atomic service
channels, the five x402 attacks, the free-riding analysis — and almost not at
all about whether the delivered *decision* was any good. Only HeLa's
accountability bonds are a true substitute.

Two consequences travel into the paper:

- The positioning table gains ACHIVX, ERC-8004, TraceRank and HeLa, plus an
  **x402-native** column on which this work scores "no". The column exists so
  that shows rather than hides: three of the new rows are deployed against real
  traffic and this is a prototype.
- Attack II of arXiv:2605.11781 (replay across the HTTP–chain boundary) applies
  directly to the new middleware, which documents the limitation and pins it
  with a test rather than leaving a reader to infer it.

**Adoption figures were removed rather than updated.** v0 carried "69,000 agents
/ 165M transactions / ~$50M volume". Re-verification found a later third-party
tracker reporting *fewer* transactions and *less* volume than the earlier
Coinbase figure — so these are not the same quantity measured twice. The model
in §4 is parameterised by per-decision value and dispute rate instead, which are
the quantities it is actually sensitive to.

## 3. New §4 — the economic framework

Four propositions with proofs, a worked numerical example on measured gas
figures, and both named competitors modelled inside the same framework.

- **Proposition 3.** Under plain x402 the reported confidence is uninformative,
  because reporting is costless and $c = 1$ weakly dominates.
- **Proposition 4 (participation condition).** Attaching a Brier attestation at
  cost $g$ raises welfare iff $g < G$, the screening value. **At the measured L1
  gas price of \$79.86 it does not** — the mechanism is welfare-negative there.
  This turns §7.7's L2 cost observation into a formal condition and sharpens
  it: the comparison is gas against *G*, not gas against the decision's price.
- **Proposition 5 (equivalence).** Against a *single* buyer, an optimally tuned
  flat-fraction bond — HeLa's mechanism — achieves **exactly** the same welfare
  (13.2757 both). Confidence elicitation buys nothing a correctly set parameter
  does not. This result cuts against the mechanism and is stated as such.
- **Proposition 6 (pooling loss).** The separation is real but specific. A bond
  implements one pooled threshold; an attested confidence is a sufficient
  statistic each buyer applies its own threshold to. With buyers spanning
  thresholds 0.50–0.95, an optimally tuned bond still forfeits **70.5%**.

The chapter states its own limits: it assumes truthful adjudication (so it
inherits tier 3), and it is comparative statics, not a market prediction —
buyer heterogeneity is modelled, not measured.

## 4–5. Two integrations

**ERC-8004 adapter.** Mirrors the calibration EMA into the standard's Reputation
Registry. Two design decisions are load-bearing and both are tested:

- The published value is $1 - \text{Brier}$. A Brier score is a *loss* and
  ERC-8004 feedback reads as a *rating*, so publishing raw would rank the worst
  operators highest.
- A failed mirror emits `MirrorFailed` rather than reverting. Letting a
  third-party registry halt `resolveDispute` would hand a liveness veto over
  slashing to a contract outside the trust boundary.

The adapter changes no trust tier, and its header says so: it makes tier-3 data
visible to an external standard, which is legibility, not a guarantee.

**x402 middleware.** Express/Hono gate, modelled on ACHIVX's provider middleware
shape, tested against a real Anvil chain with the real contracts — not a mocked
RPC. One test pins a *limitation* rather than a feature: the gate does not
prevent attestation replay, and if claim-once semantics are ever added that test
should fail and be rewritten.

Writing it surfaced a fact worth recording: `Attestation.attest` *reverts* when
the verifier rejects a proof, so a record with `proofVerified == false` cannot
exist through the current write path. The middleware's check is defence in depth
against a future write path, not the gate's primary function, and the README
says so rather than claiming the stronger version.

## 6. Unbonding period — derived, and the answer is unfavourable

v0 §7.3 called 7 days "almost certainly too short" with no data behind either
the number or the admission. v1 derives τ from primary statutory sources:

```
  60 days   consumer's free-file window (15 U.S.C. § 1681j, cited in § 1681m(a))
+ 30 days   statutory reinvestigation    (15 U.S.C. § 1681i(a)(1)(A))
+ 15 days   permitted extension          (15 U.S.C. § 1681i(a)(1)(B))
= 105 days
```

Re-running §7.7's `carry = r · τ · S` at r = 5% **reverses that section's
conclusion**. At 7 days the carry is 0.0959% per cycle and §7.7 correctly calls
it minor. At 105 days it is 1.4384%, and it exceeds the expected slash for any
dispute rate below **8.18%** — roughly 8× at a 1% rate.

The consequence is not a tuning problem. It weakens §7.7's own incentive
argument: if the slash is an eighth of the total cost, the 15% saving from
calibration is about 1.7% of what participation costs. τ is pinned by statute
above and capital cost below, and the bounds do not meet. §9.4 therefore opens a
new item (W1b) for a different instrument rather than marking W1a closed and
moving on.

## 7. Subgroup calibration — a null result, and a contract deliberately not built

v0 §8.4 named aggregate ECE's blindness to subgroup miscalibration as the
sharpest scientific gap, and §9.4 planned to close it: build the adversary, show
aggregate ECE misses it, implement the within-group variant, track it on-chain.

The first-order result looked like confirmation — within-group ECE exceeds
aggregate in 10/10 seeds, 0.1349 vs 0.0870. **It does not survive a control.**
Permuting subgroup labels while holding group sizes fixed reproduces the entire
effect (null 0.0559 vs real 0.0548; Wilcoxon *p* = 0.92; the real partition beats
its own null in 3/10 seeds).

The cause is ECE's small-sample bias. A model calibrated *by construction*
scores ECE 0.1188 at n = 68 — above this pipeline's aggregate ECE. The test
split is 200 rows and the measurable subgroups hold 68 and 106, so the
estimator's bias at subgroup sizes exceeds the quantity being measured.

**`SubgroupReputationRegister.sol` was therefore not built.** An on-chain
register tracking a quantity this measurement cannot establish would key
enforcement to noise, and worse, would sit in the repository implying the gap
had been closed. §8.4 stays open and §9.4 gains W4a: a debiased estimator, or
~20× the data.

`tests/test_subgroup_calibration.py` pins the null against erosion. Shrinking
the minimum group size, dropping the permutation control, or letting the
Wilcoxon *p* fall below 0.05 all fail loudly — because a null is easy to erode
quietly and this one blocks a deliverable.

## 8–9. Housekeeping that was not housekeeping

**Test counts were stale by a full phase.** §7.8 claimed 110 Solidity and 81
Python tests against a table listing 8 suites; the live suites are 144 Solidity
(10 suites, 3 missing from the table) and 98 Python, plus 11 middleware
integration tests. Corrected against actual runs, not incremented.

**The claim-vocabulary guard was extended, not relaxed.** Citing ERC-8004 broke
it, because the standard is literally named *Trustless Agents*. The exemption
added is deliberately narrow — italicised titles inside numbered reference
entries only — and six new tests bound it: body prose still fails, commentary
appended to a reference still fails, italics outside the reference list are not
a licence, and an unclosed italic cannot leak into the next entry. An exemption
without those tests would have been an unfalsifiable excuse.

## 10. Abstract and conclusion

Both now state the x402 contribution at the same evidentiary standard as the
rest: the participation condition and the buyer-heterogeneity separation, with
the single-buyer equivalence stated rather than omitted, and both negative
results carried into the conclusion rather than left in the limitations.

---

## What did not change

- **No limitation was softened.** §8.3 and §8.4 both got *harder*, not weaker.
- **No trust tier moved.** The ERC-8004 adapter and the x402 gate are both
  explicitly tier-inheriting, and their headers say what they do not change.
- **Tier 1 is untouched.** The input logit is as unverified in v1 as in v0.
- **`BrierMath.sol` and the slash formula are unmodified.** Nothing in this work
  required changing the proven mechanism, only what surrounds it.
- **`MIN_UNBONDING_PERIOD` is unchanged.** The tests still use 7 days, which
  exercise mechanism behaviour rather than parameter choice; what changed is
  that a deployer now has a derivation instead of a guess.
