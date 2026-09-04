# Venue

**Recommendation: arXiv `cs.CR`, cross-listed `cs.GT`, as the first public
artifact; then AFT (Advances in Financial Technologies) as the submission
target.**

## Why this community and not a machine-learning one

The instinct to send anything with a calibration experiment to an ML venue would
be wrong here, and the Phase 0 scan is what settles it. The papers actually
engaging this problem — *Five Attacks on x402* (arXiv:2605.11781), *Free-Riding
the Agentic Web* (arXiv:2605.30998), *A402* (arXiv:2603.01179), *Can Trustless
Agents Be Trusted?* (arXiv:2606.26028) — are security and crypto-economics
papers, and they are the works this paper is in conversation with. A reviewer
who has read them is the reviewer who can falsify §4.

The contribution is also not an ML contribution. Temperature scaling is
Guo et al. 2017; the calibration result reproduces known technique on a small
dataset and would be correctly desk-rejected as incremental at an ML venue. What
is new is a *mechanism*: a slashing rule that is strictly proper, its circuit
cost, and the market analysis of when attaching it is worth the gas. That is
crypto-economics with a measured systems component.

**AFT specifically**, over IEEE S&B or a workshop:

- It reviews mechanism design with formal results *and* deployed measurements,
  which is the shape of this paper — Propositions 1–6 alongside gas tables and
  proving times. A pure-theory venue would have no use for §7, and a pure-systems
  venue would not review the propositions.
- Its audience includes the people building the staking and slashing mechanisms
  §2.2 and §2.5 position against.
- The negative results are publishable there rather than a liability. AFT
  reviews economic mechanisms, and "an optimally tuned flat bond matches this
  exactly against a single buyer" (Proposition 5) is a result that community
  wants stated, not one it wants hidden.

**IEEE S&B as the fallback**, if AFT's cycle does not fit. The workshop route
was previously the honest option because the empirical half rested on one
dataset; with §8.6's replication that is no longer the binding weakness, and a
full submission is defensible.

**Not a generic ML venue, and not a blockchain-industry venue.** The first would
review the wrong contribution; the second would not review the propositions at
all.

## What has to be true before submitting

Honest gating, in the same spirit as the rest of the document. Each was closed
by doing the work, and two of the three closures found something unwelcome.

| # | Requirement | Status |
|---|---|---|
| 1 | Every number traces to a script or a cited primary source | **met** — Appendix B |
| 2 | Claim-vocabulary guard passes on the full document | **met** — 11 tests |
| 3 | All limitations stated with the same weight as results | **met** — §8, negatives in §10 |
| 4 | A second dataset, or an explicit external-validity limit | **met** — §8.6, 30,000 rows |
| 5 | Detector false-positive rate at the enforced threshold | **met, unfavourably** — §8.5 |
| 6 | Reproduction from a clean checkout | **met** — verified 4 Sep 2026 |

**Item 4 replicated, and resolved a question the first dataset could not.** UCI
*Default of Credit Card Clients* (Taiwan, 30,000 rows) differs from German
Credit on size, geography, vintage and — the axis that matters — label
semantics: an observed default event rather than an analyst's credit grade. The
protocol was held fixed rather than retuned. All five core claims replicate,
with a 54.8% mean ECE reduction against 52.8% (*p* = 0.002).

It also supplied the ~20× data §8.4 named as the missing ingredient for the
subgroup question. There, the effect **survives its permutation null** —
gap 0.0067 vs null 0.0042, 8/10 seeds, *p* = 0.037 — where on German Credit the
same control returned *p* = 0.92. Subgroup miscalibration is real, and it is
about 12% of aggregate ECE: much smaller than the naive comparison suggested
before the null was run, and large enough to matter.

**Item 5 was closed by measuring what is measurable, and the answer argues
against attaching the oracle.** The false-positive rate on *real* traffic
remains unobtainable — the protocol has never run. But on synthetic traffic
containing no rings, every flag is false by construction, and at the threshold
the contract enforces (`MIN_SCORE = 0.8e18`) the detector flags 0.94% of honest
claimants (95% Wilson upper bound 1.51%). With rings present, the false
*discovery* rate — the fraction of flagged claimants who are honest — is 19.9%
at the easiest setting and 50% at the hardest, where recall is 16%.

That sits badly beside §A.5's headline AUC of 0.998. AUC is threshold-free and
integrates over operating points the contract cannot use; the deployed system
has one fixed operating point, and its precision there is what governs whether
attaching the oracle is defensible. §8.5's recommendation is now explicit: pass
`address(0)`.

**Item 6's closure found a defect.** Running Appendix B against a fresh
`git clone` revealed that `contracts/lib/` is not committed, so `forge test`
failed immediately — the appendix was missing a `forge install` line and its
claim to reproduce from a clean checkout was false as written. With that line
added, the clean checkout runs the full suites green and regenerates
`market_model.json` and `subgroup_adversary.json` **byte-identical** to the
artifacts behind §4 and §8.4. Two limits are recorded in Appendix B: it ran on
the development machine and OS, so it shows self-containment rather than
portability; and the zkML stages were not re-run.

**What is still not established, and a reviewer should press on it.** Both
datasets are credit, tabular and binary — one model family, one decision class.
Calibration drift over time is unevaluated. The detector figures are synthetic
throughout, and a generator's realism is an assumption, not a measurement.
Staking parameters remain demonstration values. None of this is concealed: §8.6
states the residual scope directly.

## Reproducibility

Appendix B covers every script including the v1 additions
(`21_subgroup_adversary.py`, `22_market_model.py`, the ERC-8004 suite, the
middleware suite), and names which section each produces. Both negative results
carry their own artifacts (`subgroup_adversary.json`, `market_model.json`) and
their own regression tests, so a reader can check the null rather than take it
on trust.

## Title

**Settled: *Confidence as Collateral: Strictly Proper Slashing for Accountable
Automated Decisions*.**

The earlier working title, *What Does the Proof Actually Buy?*, was accurate
when the document was a zkML result about the limits of a proof. Once §3.3–§3.4
generalised past credit and §4 added the economic argument, it described
roughly half the paper. The current title leads with the mechanism, which is the
contribution that survives both broadenings, and drops the question mark for
arXiv/AFT house style.
