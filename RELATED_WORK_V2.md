# Related Work v2: the agentic-payments literature

**Scan date: 3 September 2026.** Companion to `PAPER.md` §2, which covers the
mechanism-design ancestry (proper scoring rules, staking, zkML, arbitration).
This document covers a body of work that did not exist when v0 was written: the
x402 agentic-payment stack and the trust layers being built around it.

Each item is classified as one of:

- **(a) substitute** — solves the same problem Brier solves, so Brier must beat
  it or fold into it;
- **(b) complement** — solves an adjacent problem, and the two compose;
- **(c) orthogonal** — operates on a different layer entirely, so neither
  competes with nor helps the other.

A methodological note, since it changes how the classifications below should be
read: **the classification is a claim about mechanism, not about market
position.** Two systems that both produce "a number representing agent
trustworthiness" are substitutes only if they are scored against the same thing.
Most of the systems below are not, and saying so is the point of the exercise
rather than a way of avoiding the comparison.

---

## Summary table

| # | Work | Layer | Scored against | Class |
|---|---|---|---|---|
| 1 | ACHIVX `@achivx/x402` | Reputation → pricing | Payment behaviour | (b) complement |
| 2 | HeLa Chain §5.5 | Accountability bonds | Governance verdict | (a) **substitute** |
| 3 | ERC-8004 | Identity + reputation registry | Client feedback | (b) complement |
| 4 | Can Trustless Agents Be Trusted? | Empirical audit | — | (b) motivating evidence |
| 5 | TraceRank | Discovery / ranking | Payment graph | (c) orthogonal |
| 6 | Five Attacks on x402 | Protocol security | — | (c) orthogonal |
| 7 | Free-Riding the Agentic Web | Protocol security | — | (c) orthogonal |
| 8 | A402 | Payment↔execution binding | Execution occurred | (c) orthogonal |
| 9 | x402 V2 / Foundation | Payment transport | — | (b) substrate |

The distribution is itself a finding, and it cuts against the reflex that a
crowded field means a crowded niche. Six of the nine are orthogonal or
complementary because **the agentic-payments literature is almost entirely about
whether payment and service delivery are correctly bound, and almost not at all
about whether the delivered decision was any good.** Brier scores the content of
a decision. Nearly everything below scores the transaction around it.

Only one item — HeLa — is a genuine substitute.

---

## 1. ACHIVX `@achivx/x402`

**What it claims.** Portable agent reputation for the x402 economy, sold on the
premise that "better agents pay less." A live product, not a paper.

**Mechanism.** Express/Hono middleware. It extracts the agent's wallet address
from the x402 payment header, queries ACHIVX for a trust level on a 0–5 scale,
applies a provider-configured price multiplier (examples run from 1.00× at
Level 0 to 0.60× at Level 5), and asynchronously reports payment outcomes back
so reputation accrues. The score is a seven-dimension composite: activity
volume, payment reliability, supplier diversity, tenure, feedback score, dispute
frequency, and consistency. Anti-Sybil and velocity detection are built in.

**Classification: (b) complement.**

ACHIVX scores the *buyer* on payment behaviour. Brier scores the *seller* on
decision quality. Note what is absent from all seven ACHIVX dimensions: not one
of them observes whether a decision the agent sold turned out to be right.
"Dispute frequency" is the closest, and it counts disputes rather than scoring
the confidence attached to the disputed claim — an agent that is confidently
wrong and an agent that is tentatively wrong contribute identically.

They compose cleanly, and the composition is the interesting part: ACHIVX's
middleware shape is the correct integration surface for Brier, which is why the
reference integration in `x402-middleware/` is modelled on it rather than
inventing a new one. A provider could run both — ACHIVX to price by
counterparty risk, Brier to gate on attested decision quality.

**Where Brier is not differentiated.** Both produce a number that a provider
consults before serving. If a provider only ever wanted one number, ACHIVX is
live today, has real integrations, and Brier does not.

---

## 2. HeLa Chain Whitepaper v2, §5.5 — agent sponsor accountability bonds

**What it claims.** Sponsors (human, organisation, or DAO) stake $HELA as
collateral for the agents they sponsor. The agent's accountability bond is the
aggregate of sponsor stakes, B(a) = Σ_i S_i over sponsors(a).

**Mechanism.** When "an agent's behavior triggers a governance dispute and the
dispute is resolved against the agent," a fraction of B(a) is slashed. Disputes
resolve through DAO token-weighted governance (their §8).

**Classification: (a) substitute — and the only true one in this scan.**

This is Brier's mechanism with the confidence term deleted. Same shape: stake
behind an agent, adjudicated dispute, slash on an adverse verdict. Two
differences, and both matter:

1. **The slash is not scaled by confidence.** The whitepaper specifies "a
   fraction of B(a)" with no scaling formula and no reference to prediction
   quality anywhere in the slashing condition. This is precisely the
   confidence-independent penalty rate that `PAPER.md` §1.2 identifies as the
   gap — under a flat fraction, an agent asserting 99% confidence and an agent
   asserting 51% pay identically for the same wrong call, so there is no reason
   to report 51%. HeLa's mechanism does not elicit calibrated confidence, and
   Proposition 1 explains why: only a strictly proper scoring rule does.

2. **Adjudication is token-weighted DAO voting**, which is worse than Brier's
   N-of-M committee on the same axis Brier is already honest about (§7.2 —
   tier 3). Token-weighted voting is capital-weighted, so an agent with enough
   stake influences the verdict on its own dispute.

**Where Brier is not differentiated.** HeLa ships an integrated L1 with a
governance system, a token, and an actual user base. Brier is a prototype with
no deployment. On adjudication both are tier 3, and Brier's committee is
"admin-appointed," which is not obviously better than token-weighted voting —
it is differently bad. The honest claim is narrow: **Brier's slash function is
strictly proper and HeLa's is not.** That is a claim about the penalty rule,
not about which system is more deployable today.

---

## 3. ERC-8004: Trustless Agents

**What it claims.** A permissionless trust layer for agent economies: three
singleton registries per chain — Identity (ERC-721), Reputation, Validation.
Final audited Identity and Reputation contracts are deployed on Ethereum
mainnet and 20+ networks.

**Mechanism.** Agents are `uint256 agentId` ERC-721 token IDs. Clients write
feedback via:

```solidity
function giveFeedback(uint256 agentId, int128 value, uint8 valueDecimals,
  string calldata tag1, string calldata tag2, string calldata endpoint,
  string calldata feedbackURI, bytes32 feedbackHash) external
```

`valueDecimals` MUST be between 0 and 18. The submitter MUST NOT be the agent
owner or an approved operator. Reads go through `readFeedback` and `getSummary`;
feedback is permanent and revocable-but-not-deletable.

**Classification: (b) complement — and the highest-leverage integration
available.**

ERC-8004 standardises the *transport* for reputation and deliberately does not
standardise its *semantics*: `value` is an arbitrary `int128` at
caller-chosen precision, tagged with free-text strings. This is the right design
for a registry and it is exactly why the registry cannot, by itself, be a trust
signal (see item 4). It is a shelf, and what is on the shelf is unaudited.

Brier fills a slot on that shelf with something structurally different from its
neighbours: a score that is (i) computed by a fixed on-chain rule from resolved
disputes, (ii) reproducible by replaying emitted events, and (iii) backed by
collateral the operator actually loses. The claim this licenses is narrow and
checkable — **on a registry whose feedback is mostly ungrounded, Brier's entry
is one whose write path requires a staked, adjudicated loss.** That is not
"better reputation"; it is reputation with a different and stateable provenance.

`ERC8004ReputationAdapter.sol` implements this. The `int128`/`valueDecimals`
encoding is a good fit: Brier's EMA is WAD (1e18) and `valueDecimals = 18`
carries it without rescaling loss.

**Where Brier is not differentiated.** Nothing stops anyone writing any number
to this registry, including a number they call a Brier score. The registry
cannot enforce that a value means what its writer says it means, and Brier's
entry is only as good as a reader's willingness to check which contract wrote
it. Provenance is legible, not enforced.

---

## 4. Can Trustless Agents Be Trusted? (arXiv 2606.26028)

**What it claims.** The first empirical study of the deployed ERC-8004
ecosystem, across Ethereum, BSC, and Base through 13 May 2026.

**Findings, quantitatively.**

- Only **3% / 4% / 15%** (Ethereum / BSC / Base) of registrations expose a valid
  ERC-8004 registration file with at least one live service endpoint. Most
  registrations are placeholders.
- **73.5% / 59.2% / 90.6%** of reviewers exhibit coordinated Sybil behaviour.
- After removing Sybil-flagged feedback, **15.8% / 77.9% / 86.8%** of rated
  agents lose all valid feedback.
- The Reputation Registry as deployed "cannot function as a trust signal":
  values are not commensurable, feedback is rarely grounded in verifiable
  interactions, and reputation is manipulable at minimal cost.

**Classification: (b) complement — this is the motivating evidence for Task 1.**

This paper is the strongest external support in this scan for the specific thing
Brier does, and it should be cited as evidence rather than paraphrased as
endorsement. Its three named failures map onto three Brier properties:

| Their finding | Brier's corresponding property |
|---|---|
| Values not commensurable | The value is a Brier score, a fixed and published function of (confidence, outcome) |
| Feedback not grounded in verifiable interactions | The write path is a resolved dispute against a staked operator |
| Manipulable at minimal cost | Writing a favourable score requires *not* losing a dispute; the cost of manipulation is the stake |

**The honest caveat, which must travel with the claim.** Brier's grounding
bottoms out at the N-of-M committee. A colluding committee can manufacture any
reputation it likes — `ReputationRegister.sol`'s own header says so. So Brier
does not *solve* ungrounded reputation; it **relocates** the grounding
assumption from "anonymous reviewers are honest" to "the resolver committee is
not colluding." That is a strictly smaller and more auditable assumption, and it
is a real improvement, but it is not the elimination of trust and must never be
written up as one.

---

## 5. Sybil-Resistant Service Discovery for Agent Economies / TraceRank (arXiv 2510.27554)

**What it claims.** Reputation-weighted ranking for x402 service discovery,
where payment transactions act as endorsements.

**Mechanism.** Seeds addresses with precomputed reputation, then propagates it
through the payment graph weighted by transaction value and recency —
PageRank-shaped. Sybil resistance is structural: spam services with many
low-reputation payers rank below legitimate services with few high-reputation
payers. Combined with semantic search for natural-language queries.

**Classification: (c) orthogonal.**

TraceRank answers "which service should this agent pick?" Brier answers "was
the decision this service sold correctly hedged?" TraceRank's signal is
entirely endogenous to the payment graph — it never observes a service's
output, only who paid for it. A service that is confidently wrong but popular
with reputable payers ranks well.

They could compose (TraceRank ranking, Brier as a ranking feature) but neither
needs the other, and asserting a partnership here would overstate the fit.

---

## 6. Five Attacks on x402 (arXiv 2605.11781)

**What it claims.** Five practical attacks on x402's cross-layer surface,
validated on local chains, Base Sepolia, and live endpoints, with audits of
three open-source SDKs.

**The attacks.**

| Attack | Layer | Mechanism |
|---|---|---|
| I-A Revert-grant under optimistic execution | Authorization | Server releases the resource before finality; a reorg invalidates settlement |
| I-B Unauthorized settlement preemption | Payment↔execution binding | An observer extracts a valid authorization and consumes it before the legitimate facilitator |
| II Replay / idempotency across the HTTP–chain boundary | Replay protection | One `X-PAYMENT` payload yields multiple HTTP grants, one on-chain settlement |
| III HTTP/proxy confusion and header manipulation | Web layer | Intermediaries mutate payment headers or cache paid responses |
| IV Server-selection | Discovery | Sybil catalogue listings steer agents to malicious endpoints before payment runs |

**Classification: (c) orthogonal — with one direct consequence for Brier's
middleware.**

Every attack concerns whether payment is correctly bound to service delivery.
None concerns whether the delivered decision was well-calibrated. Brier neither
mitigates nor worsens any of them.

**But Attack II is a live constraint on `x402-middleware/`.** An attestation
gate that verifies an attestation and calls `next()` is a *second* grant surface
with the same replay shape: the same `attestationId` can be presented against
many requests. Their mitigation M3 — bind resource scope, claim once before
grant, TTL-bounded dedup — is the correct pattern, and the middleware README
must state plainly that the reference implementation gates on attestation
validity and does **not** implement per-request attestation binding. Gating on
an attestation is not the same as binding a payment to one.

---

## 7. Free-Riding the Agentic Web (arXiv 2605.30998)

**What it claims.** A systematic security analysis showing x402 implementations
let attackers consume services while evading payment.

**Mechanism.** Exploits the gap between payment verification and service
delivery — timing windows where service is rendered before payment confirmation
completes, and paths where verification is bypassable. Proposes both
protocol-level fixes and deployment-layer defences.

**Classification: (c) orthogonal.** Same reasoning as item 6: the vulnerabilities
concern payment authorization, explicitly not the quality of returned results.
Attackers are avoiding payment, not degrading decisions.

I was unable to extract the per-endpoint vulnerability counts from the PDF's
compressed streams, so no quantitative finding from this paper is cited anywhere
in the proposal. Recording the failed extraction rather than a plausible-sounding
number.

---

## 8. A402: Binding Cryptocurrency Payments to Service Execution (arXiv 2603.01179)

**What it claims.** Atomic service channels binding payment finalisation to
service delivery via adaptor signatures, so payment settles only on release of
execution-dependent secrets.

**Mechanism.** Identifies that x402 providers must execute optimistically before
finalisation (exposing them to non-payment) and that facilitators broadcast
payments without verifying execution occurred. Reported: up to 2,875 RPS,
340–370 ms average latency, 28.4–46× cost reduction versus Ethereum on-chain
settlement.

**Classification: (c) orthogonal — and the cleanest illustration of the
distinction this whole document turns on.**

A402 proves **that the service ran**. Brier prices **how good the answer was**.
An A402 channel closes correctly when a credit-scoring endpoint returns a score;
it is entirely indifferent to whether that score was 0.9 on an applicant who
defaulted. The two guarantees stack without overlapping, and neither substitutes
for the other. If both existed, a buyer would have execution atomicity from A402
and calibrated confidence from Brier.

---

## 9. x402 V2 and the x402 Foundation

**Status.** V2 is the recommended baseline: CAIP-2 network identifiers,
separated transports/schemes/extensions. Technical charter dated 31 March 2026;
the Foundation went operational 14 July 2026 with roughly forty member
organisations, having moved from Coinbase to the Linux Foundation. The `exact`
scheme has per-network documents for EVM, Solana, Stellar, Sui, Aptos, Hedera,
Algorand, and Keeta.

`PaymentRequirements` fields: `scheme`, `network` (CAIP-2), `amount` (atomic
units, string), `asset`, `payTo`, `maxTimeoutSeconds`, and optional `extra`.
Facilitator `POST /verify` → `{isValid, payer}`; `POST /settle` →
`{success, payer, transaction, network}`.

**Classification: (b) substrate.**

Not a competitor — the transport Brier's integration targets. The V2
**extension** mechanism is the architecturally correct home for a Brier
attestation: resource servers advertise supported extensions in
`PaymentRequired` and clients echo them in `PaymentPayload`. A Brier attestation
is exactly "modular optional functionality beyond core payment mechanics."

The reference middleware in `x402-middleware/` gates *around* the payment flow
rather than registering a formal extension, because a registered extension
requires a published schema and an identifier this project has no standing to
mint. That is a deliberate scope limit, not an oversight, and the README says so.

---

## Adoption figures, and why this document does not quote a single one

`PAPER.md` §2 previously carried "69,000 agents / 165M transactions / ~$50M
volume." Re-verification found the sources disagree materially:

| Source | Date | Transactions | Volume | Agents |
|---|---|---|---|---|
| Coinbase | late Apr 2026 | 165M | ~$50M | 69,000 |
| Third-party tracker (7 chains, 18 facilitators) | 19 Jul 2026 | 157.4M | $41.1M | — |
| Chainalysis | 2026 | ~100M (Base) | — | — |

A later date reporting *fewer* transactions and *less* volume than an earlier one
means these are not the same quantity measured twice. They differ in chain
coverage, facilitator coverage, and what counts as a transaction.

There is also a validity problem independent of the arithmetic: raw settlement
counts include tests, infrastructure traffic, repeated service calls, and
self-directed usage. Item 4 found that most ERC-8004 registrations are
placeholders and the majority of reviewers are Sybils; there is no reason to
assume x402's counts are cleaner.

**Consequence for Phase 2.** The economic model must not be calibrated on a
headline adoption number. It should be parameterised by per-decision value and
dispute rate — quantities the model is actually sensitive to — with adoption
figures cited, attributed, and dated where they appear at all. A welfare result
that depends on whether the true count is 157M or 165M would be a result about
a disputed statistic rather than about the mechanism.

---

## What this scan changes in the proposal

1. **§2.5 Positioning gains four rows and an axis.** ACHIVX, HeLa, ERC-8004, and
   TraceRank on Conf / Stake / ZK / Adjud., plus **x402-native**. Brier is the
   only row with `Conf = yes` and `Stake = yes` together — and is *not*
   x402-native, which the table must show rather than hide.
2. **A sharpened novelty claim, in one sentence.** Of the mechanisms that stake
   collateral behind an agent, Brier is the only one whose slash is a strictly
   proper function of reported confidence; of the mechanisms that publish agent
   reputation, it is the only one whose write path requires an adjudicated loss.
3. **HeLa is the comparison to run in Phase 2's model**, being the only true
   substitute. Same framework, flat-fraction slash substituted for the Brier
   slash, and show where the welfare result changes.
4. **Item 4 supplies the empirical case for Task 1** — and its caveat travels
   with it: Brier relocates the grounding assumption, it does not remove it.
5. **Item 6's Attack II constrains the middleware's claims.** Attestation gating
   is not payment binding, and the README says so.

---

## References

1. ACHIVX, *Agent Reputation for x402*. <https://agents.achivx.com/> and
   `@achivx/x402` provider integration documentation.
2. HeLa Labs, *HeLa Chain Whitepaper v2 — Sovereign Infrastructure for the
   AI-Native Economy*, §5.5. <https://blog.helachain.com/whitepaper/>
3. *ERC-8004: Trustless Agents*. <https://eips.ethereum.org/EIPS/eip-8004>;
   reference contracts <https://github.com/erc-8004/erc-8004-contracts>
4. X. Xiong, Z. Li, W. Wei, Q. Wang, W. Knottenbelt, Z. Wang, *Can Trustless
   Agents Be Trusted? An Empirical Study of the ERC-8004 Decentralized AI Agent
   Ecosystem*, arXiv:2606.26028.
5. D. Shi, K. Joo, *Sybil-Resistant Service Discovery for Agent Economies*,
   arXiv:2510.27554.
6. Z. Li, Q. Wang, Z. Wang, *Five Attacks on x402 Agentic Payment Protocol*,
   arXiv:2605.11781.
7. *Free-Riding the Agentic Web: A Systematic Security Analysis of x402
   Payments*, arXiv:2605.30998.
8. Y. Li, L. Wang, K. Wang, Z. Yang, K. Wang, Z. Guan, J. Gao, *A402: Binding
   Cryptocurrency Payments to Service Execution for Agentic Commerce*,
   arXiv:2603.01179.
9. *x402 Specification v2*.
   <https://github.com/coinbase/x402/blob/main/specs/x402-specification-v2.md>
