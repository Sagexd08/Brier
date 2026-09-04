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
papers, and they are the works this proposal is in conversation with. A reviewer
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

**IEEE S&B and a workshop as fallbacks.** S&B if AFT's cycle does not fit; a
workshop co-located with either if the reviewers' verdict is that the empirical
half needs a second dataset first (§9.4, W5) — which is a fair reading of the
current evidence.

**Not a generic ML venue, and not a blockchain-industry venue.** The first would
review the wrong contribution; the second would not review the propositions at
all.

## What has to be true before submitting

Honest gating, in the same spirit as the rest of the document. Three of these
are not yet met.

| # | Requirement | Status |
|---|---|---|
| 1 | Every number traces to a script or a cited primary source | **met** — Appendix A |
| 2 | Claim-vocabulary guard passes on the full document | **met** — 11 tests |
| 3 | All limitations stated with the same weight as results | **met** — §8, and both new negatives in §10 |
| 4 | A second dataset, or an explicit external-validity limit | **not met** — one dataset, 1,000 rows |
| 5 | Detector false-positive rate on non-synthetic traffic | **not met** — §8.5, W6 |
| 6 | Independent reproduction from a clean checkout | **not met** — never run outside this machine |

Items 4 and 5 are the ones a reviewer will press hardest on, and neither is
concealed: §7.6 states the single-dataset scope, and §8.5 states plainly that an
unvalidated detector has authority over money. A submission can proceed with
them open *if* the paper does not claim otherwise — but item 4 in particular is
the difference between "this mechanism works" and "this mechanism worked once,
on UCI German Credit, at n = 1,000," and only the second is currently supported.

Item 6 is cheap and should be done first: the reproducibility appendix has never
been executed anywhere but the development machine, so its claim to reproduce
from a clean checkout is untested.

## Reproducibility

Appendix A covers every script including the v1 additions
(`21_subgroup_adversary.py`, `22_market_model.py`, the ERC-8004 suite, the
middleware suite), and names which section each produces. Both negative results
carry their own artifacts (`subgroup_adversary.json`, `market_model.json`) and
their own regression tests, so a reader can check the null rather than take it
on trust.

## Title

The working title is *What Does the Proof Actually Buy?*, which was accurate
when the paper was a zkML result about the limits of a proof. With §3.3–§3.4
generalising past credit and §4 making the economic argument, it now reads as
narrower than the content. **Suggested: *Confidence as Collateral*.** Not
changed here — it is the author's call, and the current title is defensible.
