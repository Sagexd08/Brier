# Confidence as Collateral: Strictly Proper Slashing for Accountable Automated Decisions

**Sohom Chatterjee**

Preprint. Code, data, and every artifact behind the numbers below:
<https://github.com/Sagexd08/Brier> · September 2026

---

## Abstract

Accountability mechanisms for automated decisions penalise error at a
confidence-independent rate, so an operator is never punished for asserting 99%
confidence in a decision it privately believes at 60%. We study slashing staked
collateral by the **Brier score** over (reported confidence, adjudicated
outcome). Because that score is strictly proper, expected loss is uniquely
minimised when the operator reports its true subjective probability: honest
confidence becomes the loss-minimising strategy rather than an assumption. We
show the property survives fixed-point on-chain arithmetic, and prove that the
slash cap must be 100% of stake — any lower cap makes maximal overconfidence
optimal, so a prudential-looking parameter silently inverts the mechanism.
Embedding the rule in a decision market yields a participation condition and a
sharp negative: against a *single* buyer an optimally tuned flat bond achieves
exactly the same welfare, and the separation appears only under buyer
heterogeneity.

We report a measured prototype. Across 10 pinned seeds, temperature scaling cuts
Expected Calibration Error from 0.1853 ± 0.0248 to 0.0870 ± 0.0218 on held-out
UCI German Credit data, in every seed, replicating on a second 30,000-row
dataset labelled with observed defaults; an EZKL/halo2 circuit proves the
calibration head in 2.09 s and verifies on-chain for 684,696 gas, flat across a
16,897× parameter increase. The central result is negative and is the paper's
main claim: a proved calibration head is **not** sufficient for a trustworthy
attestation, because the proof binds the map from logit to confidence and
nothing else, so an operator that fabricates the logit obtains a proof that
verifies. Three further measurements ran against the design — a statutory
unbonding period at which capital lockup exceeds the slash eightfold, a subgroup
gap that was estimator bias at one scale and real at another, and a detector
reporting AUC 0.998 that flags 0.94% of honest claimants at the threshold its
contract enforces. Every claimed weakness is executed as a passing test.

**Keywords:** proper scoring rules, mechanism design, zero-knowledge machine
learning, calibration, staking and slashing, agentic payments.

---

## 1. Introduction

Automated credit decisions are entering a compliance regime that demands records
rather than assurances. Under the EU AI Act, credit scoring is high-risk;
Article 26 obliges deployers to monitor operation and retain logs for at least
six months, and Article 86 establishes a right to explanation. These provisions
mandate *logging and explanation*. They do not establish that the logs are
truthful, nor do they price the difference between a wrong decision made
tentatively and a wrong decision made with asserted certainty. A deployer that
logs a confidently wrong decision is compliant [1].

**The gap.** Existing accountability mechanisms penalise error at a rate
independent of the confidence asserted. Chainlink staking slashes a fixed amount
on an SLA breach [3]; Nexus Mutual pays or refuses a claim by member vote [4];
HeLa's agent bonds slash "a fraction" on an adverse governance verdict [29].
Under any such rule, an operator asserting 99% confidence and one asserting 51%
pay identically for the same wrong call — so nothing induces the 51%. Separately,
a literature on proper scoring rules has known since Brier [9] and Gneiting and
Raftery [10] exactly how to price a probabilistic claim so that honesty is
optimal. The two have not been joined: scoring rules elicit beliefs from
forecasters who are paid, not from operators who are *staked*.

**This paper** joins them, implements the result on-chain, and reports what
happens when the implementation is measured rather than described. Six questions
organise it. Slashing by Brier score *does* make truthful confidence
loss-minimising, and the property survives fixed-point on-chain arithmetic
(§3); the confidence-producing step *can* be proved in zero knowledge at
2.09 s and verified for 684,696 gas (§6.2); and proving cost is *flat* in the
size of the proved head, so circuit capacity rather than parameter count binds
(§6.2).

Two answers are negative, and they are the more useful results. A proved
calibration head is **not** sufficient to make an attestation trustworthy (§5).
And of five candidate enhancements ablated on an identical protocol, only one
earns its place: a deeper base model is null and deep-ensemble epistemic
uncertainty is actively harmful (§6.3). A sixth question — when attaching an
attestation is worth its cost, and whether it dominates a simpler bond — is
answered conditionally and partly against the mechanism (§4).

### 1.1 Contributions

1. A slashing rule on a strictly proper scoring rule, with the properness
   argument in closed form and its scope conditions stated as part of the claim.
2. **Proposition 2: the slash cap must be 100% of stake.** Below
   κ ≥ max(*p*, 1−*p*) the minimiser jumps to a boundary report, so a capped
   protocol *pays for* maximal overconfidence — limited liability's risk-shifting
   effect arriving through a parameter that looks prudential. This also settles
   Brier over the log score, which is unbounded and cannot be paid from finite
   stake.
3. A welfare model of a decision market (§4) yielding a participation condition
   and an equivalence result that bounds the mechanism's own advantage.
4. A working implementation: fixed-point Brier arithmetic at 543 gas, an
   EZKL/halo2 circuit, and an attestation contract that rejects unverified
   proofs — with a two-dataset evaluation over 10 pinned seeds.
5. **Four negative results**, reported at the weight of the positive ones: the
   insufficiency of a proved head (§5), an unaffordable statutory unbonding
   period (§7.1), a subgroup gap that was estimator bias at one scale and real
   at another (§7.2), and a detector whose headline AUC does not describe its
   deployed operating point (§7.3).

---

## 2. Related work and positioning

**zkML.** EZKL [6] compiles ONNX graphs to halo2 circuits, and the field's
practical constraint — proving cost dominated by circuit capacity rather than
model size — is the design constraint this work is built around: prove the small
calibration head, not the classifier. The consequence, that everything outside
the proved subgraph is unbound, is the subject of §5.

**Staking, and scoring rules.** Chainlink [3], Nexus Mutual [4] and Kleros [7]
stake collateral against adjudicated outcomes, none weighting the penalty by
stated confidence. Modern networks are overconfident and temperature scaling
largely fixes it [11]; the Brier score [9] is strictly proper [10]. Foresight
Arena [5] scores on-chain forecasts by Brier but does not stake them.

**Agentic payments.** A body of work postdating this project targets the same
problem from the payments side, and its distribution is itself a finding: it is
almost entirely about whether payment is correctly bound to *delivery* [25, 26,
27], and almost not at all about whether the delivered decision was any good.
ERC-8004 [23] standardises an agent reputation registry; the first empirical
study of it [24] found that across three chains only 3–15% of registrations
expose a live endpoint while 59–91% of reviewers show coordinated Sybil
behaviour, concluding the registry "cannot function as a trust signal." That is
the strongest external evidence for what this mechanism does, and it must be
cited as evidence rather than paraphrased as endorsement: Brier *relocates* the
grounding assumption from "anonymous reviewers are honest" to "the resolver
committee is not colluding," which is smaller and more auditable but is not the
elimination of trust.

Table: Positioning. *Conf* = the penalty is weighted by the reporter's own
stated confidence; *Stake* = collateral is at risk; *ZK* = the scored quantity is
zero-knowledge proved; *x402* = deployed against the agentic-payments rail today.

| Work | Conf | Stake | ZK | Adjud. | x402 |
|---|---|---|---|---|---|
| Chainlink staking [3] | – | yes | – | alerting | – |
| Nexus Mutual [4] | – | yes | – | member vote | – |
| Kleros [7] | – | yes | – | juror pool | – |
| Foresight Arena [5] | yes | – | – | market | – |
| EZKL [6] | – | – | yes | – | – |
| ERC-8004 [23] | – | – | – | client feedback | **yes** |
| TraceRank [28] | – | – | – | payment graph | **yes** |
| HeLa bonds [29] | – | yes | – | DAO vote | – |
| This work | **yes** | **yes** | **yes** | N-of-M | – |

The final row is the only one carrying both *Conf* and *Stake*, and that
conjunction is the novelty claim. It is also **not** x402-native, and the column
exists so that shows rather than hides: three of the rows above are deployed
against real traffic and this is a prototype.

---

## 3. The mechanism

:::definition Confidence-calibrated slash
Let $S$ be the collateral an operator has staked, $c \in [0,1]$ the confidence it
reported that its decision was correct, and $o \in \{0,1\}$ the adjudicated
outcome of a dispute over that decision. On an upheld dispute the contract
slashes $\text{slash} = S \cdot (c-o)^2$, subject to a protocol maximum fraction
of $S$.
:::

The penalty is the Brier score of a single forecast, denominated in stake.
Everything that follows depends on one property of that score and nothing else
about it. Write $p$ for the operator's private belief that its decision is
correct — unobservable, and the quantity the mechanism must elicit.

### 3.1 Truthful reporting minimises expected loss

:::assumption Truthful adjudication
The adjudicated outcome $o$ equals the true correctness of the decision, and
whether a decision is disputed is independent of the confidence reported.
:::

:::proposition Strict properness of the Brier slash
Under Assumption 1, an operator reporting $c$ faces expected slash
$E[\text{slash}] = S ( (c-p)^2 + p(1-p) )$. This is uniquely minimised at
$c = p$, and every misreport costs $S(c-p)^2$ in expectation.
:::

:::proof
The dispute is upheld with probability $p$, giving slash $S(c-1)^2$; otherwise
the slash is $Sc^2$. Hence $E[\text{slash}] = S ( p(c-1)^2 + (1-p)c^2 ) =
S ( c^2 - 2pc + p )$. Completing the square gives $S ( (c-p)^2 + p(1-p) )$. The
bracket is strictly convex in $c$ with its only stationary point at $c = p$, and
the residual $p(1-p)$ does not depend on $c$.
:::

Two consequences. Overclaiming is not merely unrewarded but priced
quadratically, so shading slightly is cheap while asserting near-certainty about
a coin flip costs nearly the whole stake. And the residual $p(1-p)$ is
irreducible: a well-calibrated operator that is sometimes wrong still pays, which
is what makes the rule a price rather than a punishment. The operator need not be
honest, only selfish.

### 3.2 The cap must be 100%, and why the Brier score

A protocol that slashes stake will be tempted to cap the penalty. It must not.

:::proposition Capping the slash destroys strict properness
Let the slash be $\min(S(c-o)^2, \kappa S)$ for a cap $\kappa \in (0,1]$.
Truthful reporting remains optimal iff $\kappa \ge \max(p, 1-p)$. For
$\kappa$ below that bound the expected-loss minimiser is a boundary report:
$c = 0$ when $p < \tfrac12$, and $c = 1$ when $p > \tfrac12$.
:::

:::proof
The cap binds exactly where $(c-o)^2 > \kappa$. For $p > \tfrac12$ and
$\kappa < p$, reporting $c = 1$ caps the loss on the $o=0$ branch at $\kappa S$
while paying nothing on the $o=1$ branch, giving expected loss
$(1-p)\kappa S$. The truthful report pays $S p(1-p)$, and
$(1-p)\kappa S < S p(1-p)$ whenever $\kappa < p$. The case $p < \tfrac12$ is
symmetric.
:::

This is limited liability's risk-shifting effect arriving through a parameter
that looks prudential: a capped protocol *pays for* maximal overconfidence.
Verified numerically and pinned by three tests against the deployed
`BrierMath.sol`, whose `maxSlashBps` is 10,000.

It also settles the choice of scoring rule. The logarithmic score is strictly
proper too, but unbounded — an operator confidently wrong owes infinity, which no
finite stake can pay, and truncating it triggers exactly Proposition 2. The
Brier score is the natural strictly proper rule bounded on $[0,1]$.

**Scope conditions**, stated as part of the claim rather than as caveats: the
circuit takes the base model's logit as an *unverified* public input, so a
fabricated logit yields a proof that verifies (§5); nothing forces the operator
to feed the circuit the logit its deployed model produced; and if only
rejections are ever disputed, Assumption 1 fails and the loss surface is
asymmetric in a way not analysed here.

---

## 4. An economic framework for decision markets

§3 shows the slash elicits truthful confidence. It does not show anyone should
want it. A buyer-agent purchases a decision through a priced endpoint and must
act on it: acting on a correct decision yields $V$, acting on a wrong one costs
$K$, abstaining yields 0. A rational buyer acts iff its posterior exceeds
$t = K/(V+K)$ — the buyer's threshold, determined entirely by its own payoff
asymmetry and **private to it**.

:::proposition Uninformative reporting without a penalty
With no penalty attached to the report, every $c$ yields the seller the same
payoff and $c = 1$ weakly dominates. The buyer's posterior is therefore
independent of $c$.
:::

Costless signals are uninformative signals — the same gap the ERC-8004 study [24]
measured empirically. Attaching Definition 1 makes $c$ a sufficient statistic for
$p$, and the buyer can act iff $c \ge t$.

:::proposition Participation condition
Let $G = E_F[\max(0, pV-(1-p)K)] - E_F[pV-(1-p)K]$ be the screening value.
Attaching an attestation at per-decision cost $g$ raises welfare **iff $g < G$**,
and the gain is exactly $G - g$.
:::

$G$ is the value of being able to decline, and it is bounded — a mechanism
costing more than the mistakes it prevents is not worth running. With a
Beta(5,2) decision population (mean 0.714, matching the prototype's measured
accuracy) and $V = 100$, $K = 400$, $G = 56.19$.

Table: The participation condition at measured per-attestation costs. Welfare is
per decision, in the buyer's units.

| Setting | $g$ | Welfare | Gain | Verdict |
|---|---|---|---|---|
| L1, busy (30 gwei) | $79.86 | −66.58 | −23.67 | **does not pay** |
| L1, quiet (10 gwei) | $26.62 | −13.34 | +29.57 | pays |
| L2, typical (0.05 gwei) | $0.13 | +13.15 | +56.06 | pays |

**On a busy L1 the mechanism is welfare-negative.** The relevant comparison is
not gas against the decision's price but gas against $G$. The condition also says
when the mechanism is pointless for reasons unrelated to cost: $G \to 0$ when
payoffs are near-symmetric and most decisions are worth acting on. Confidence
attestation is worth paying for exactly where decisions are consequential,
asymmetric, and genuinely uncertain — a narrower market than "all agentic
commerce."

### 4.1 Against a flat bond, in the same model

HeLa's accountability bond [29] slashes a fraction $\varphi$ of a bond $B$ at
dispute rate $d$. The expected penalty $\varphi B d(1-p)$ **does not depend on
$c$**, so the reporting margin is untouched and Proposition 3 still applies. What
the bond constrains is the participation margin: the seller sells only when
$\rho > \varphi B d(1-p)$, i.e. when $p \ge 1 - \rho/(\varphi B d)$.

:::proposition Equivalence against a single buyer
For any single buyer with threshold $t$, the bond level
$\varphi B d = \rho/(1-t)$ achieves exactly the same welfare as the Brier
mechanism, gross of attestation cost.
:::

*Proof.* The bond induces seller-side threshold
$p_{\min} = 1 - \rho/(\varphi B d)$; setting $\varphi B d = \rho/(1-t)$ gives
$p_{\min} = t$, so both mechanisms act on exactly $\{p \ge t\}$. ∎

The numbers confirm it: both attain 13.2757. **Identical, not merely close.**
This cuts against the mechanism and is stated plainly — for a single buyer,
confidence elicitation buys nothing a correctly tuned bond does not. What it buys
is robustness to mis-tuning (at half the optimal bond, welfare falls to −6.23),
which is a weaker claim than the positioning table alone would suggest.

:::proposition Pooling loss of threshold mechanisms
With buyers heterogeneous in $t$, the Brier mechanism attains
$E_j E_F[\max(0, pV_j-(1-p)K_j)]$, while any flat bond attains at most
$\max_q E_j E_F[\mathbb{1}\{p \ge q\}(pV_j-(1-p)K_j)]$. The first weakly
dominates, strictly whenever two buyers have distinct thresholds.
:::

:::proof
The report $c = p$ is a sufficient statistic, so each buyer $j$ attains its
first-best set $\{p \ge t_j\}$. A bond fixes one pooled threshold $q$ for all
buyers; where $t_j \neq q$, buyer $j$ either acts on decisions with $p < t_j$ or
abstains on decisions with $p \ge t_j$, and either strictly lowers its payoff.
:::

With four buyers whose thresholds span 0.50–0.95, an optimally tuned bond attains
4.67 against Brier's 15.83 — an efficiency loss of **70.5%**. The loss is not
mis-tuning; the bond is at its optimum. It is the structural cost of compressing
a continuous signal into one binary sell/don't-sell rule.

**This is the mechanism's actual economic claim, and it is narrower than
"accountability."** A bond communicates *the seller declined to sell you bad
decisions at the protocol's threshold*; an attestation communicates *here is how
good this decision is, apply your own threshold*. The second is more valuable
exactly when buyers differ, and worth nothing when they do not. Buyer
heterogeneity is modelled here, not measured.

---

## 5. System, and the boundary of the proof

![Figure 1 — Component architecture, with measured cost at each step. Hatching marks the only subgraph inside the zk circuit; dashed outlines are specified but unbuilt. The heavy arrow is the base model's logit, which the circuit takes as an unverified public input — the boundary this section turns on.](figures/figure-a-architecture.png)

An XGBoost classifier produces a logit $L$; a one-parameter temperature head maps
it to a confidence $c$; EZKL proves *that mapping only*; `Attestation.sol` stores
the record and reverts if the proof does not verify; `StakePool.sol` computes the
slash on resolution. The base classifier and the SHAP explainer sit outside the
circuit by design — the vectors they produce are hash-committed as evidence,
which establishes that the operator recorded a particular explanation and nothing
about whether it is faithful.

:::theorem Scope of the tier-1 guarantee
The zk proof establishes that a committed head with verifying key $vk$ maps the
public input $L$ to the attested $c$. It establishes nothing about the
provenance of $L$.
:::

**An operator that fabricates $L$ obtains a proof that verifies and a chain that
accepts it.** This is not a defect to be patched but a statement of what the
cryptography buys, and it is asserted by a passing test
(`test_tier1_marginIsUnverifiedOperatorSuppliedInput`) rather than conceded in
prose. Three trust tiers follow:

- **Tier 1 — cryptographic.** Calibration-head execution and slash arithmetic.
  Holds against a fully malicious operator, and covers nothing else.
- **Tier 2 — economic.** Honest reporting (Proposition 1) and stake availability.
  Enforced in code by a two-step withdrawal behind an unbonding delay, with any
  open dispute freezing execution — but released by a tier-3 action.
- **Tier 3 — bounded trust.** Who loses money. An admin-appointed N-of-M
  committee whose $N$ colluding members carry exactly the authority v0's single
  admin key had. Reputation, being computed from tier-3 outcomes, inherits this
  exactly.

The cheapest attack today requires breaking no cryptography: attest over a
fabricated $L$, or corrupt $N$ committee members.

---

## 6. Results

All figures are produced by scripts in the repository. Environment: Windows 11,
Python 3.13.5, xgboost 3.1.2, torch 2.9.1, EZKL 23.0.5, Foundry 1.7.1, laptop
CPU, no GPU.

### 6.1 Calibration, on two datasets

Seeds are pinned in `config.EVAL_SEEDS` and the full list is always run, so a
favourable subset cannot be reported selectively.

Table: Calibration across 10 pinned seeds, UCI German Credit. The train-fitted
control is worse than not calibrating at all, in every seed.

| Head | ECE | Brier | Accuracy |
|---|---|---|---|
| Uncalibrated | 0.1853 ± 0.0248 | 0.2060 ± 0.0191 | 0.7505 ± 0.0209 |
| **Temperature (1 param)** | **0.0870 ± 0.0218** | **0.1758 ± 0.0113** | 0.7505 ± 0.0209 |
| MLP (321 params) | 0.1055 ± 0.0234 | 0.1908 ± 0.0119 | 0.7330 ± 0.0199 |
| *Control: fitted on TRAIN* | *0.2434 ± 0.0212* | — | — |

Learned $T = 3.47 \pm 0.45$, with $T > 1$ in every seed — the base model required
softening everywhere. Accuracy is unchanged, as it must be: a monotone rescaling
cannot move the decision boundary. Calibration buys a better-priced confidence,
not a better classifier.

The 321-parameter MLP head does not beat the 1-parameter head, and the strength
is reported as the data supports it: temperature wins in **7 of 10** seeds,
Wilcoxon $p = 0.037$ — a *majority* result, not a uniform one, where a single run
per head would have supported the stronger and less accurate claim.

**The result replicates.** Running the identical protocol — same splits, seeds,
head, fitting, metrics, and deliberately the same base-learner hyperparameters —
on UCI *Default of Credit Card Clients* (Taiwan, 30,000 rows, labelled with
**observed defaults** rather than an analyst's credit grade):

| Claim | German Credit | Taiwan default |
|---|---|---|
| ECE reduced in every seed | 10/10 | 10/10 |
| Mean ECE reduction | 52.8% | 54.8% |
| Learned $T > 1$ | 3.47 ± 0.45 | 2.80 ± 0.06 |
| Realised Brier — what is slashed | 0.2060 → 0.1758 | 0.1642 → 0.1490 |

The label change carries the weight: a finding that held on adjudicated opinion
but not on realised outcomes would be much weaker. Hyperparameters were not
retuned, so the base model is under-fit on the larger corpus and absolute
accuracy is not the comparison to read — retuning would have tested whether the
data can be modelled well, not whether the finding travels.

### 6.2 Proving and on-chain cost

Proving cost is **flat across a 16,897× parameter increase**: mean 2.13 s, sd
0.09, regression slope +0.009 s per decade, Spearman $-0.188$ at $p = 0.603$.
Rows used scale linearly with parameters (0.98 rows/param, $r = 0.992$), so fixed
lookup-argument and column overhead dominate the multiply-accumulate count
entirely. The boundary — where cost steps past logrows 15 — is unmeasured, and we
say so rather than extrapolating.

Table: Measured gas. The Brier arithmetic that is the substance of the mechanism
is 0.08% of the per-decision cost.

| Operation | Gas |
|---|---|
| `Halo2Verifier` deployment (one-off) | 2,942,192 |
| `verifyProof` (real EZKL proof) | **684,696** |
| `attest` (verify + store) | 887,376 |
| `openDispute` | 134,608 |
| `resolveDispute` incl. slash + payout | 97,390 |
| `BrierMath.slashAmount` (pure) | **543** |

End-to-end on a local chain, confident-and-wrong costs 3,667× confident-and-correct
and 3.49× uncertain-and-wrong — the ordering the mechanism exists to produce.

### 6.3 Five enhancements, ablated

Each candidate ran under the identical seed protocol and was kept only if it
earned its place.

| Enhancement | Effect on the priced quantity | Verdict |
|---|---|---|
| Conformal prediction | Distribution-free coverage, no measurable proving cost | **kept** |
| Deeper base model | Null | rejected |
| Deep-ensemble epistemic uncertainty | **Degrades** calibration | rejected |
| Counterfactual evidence | Evidence only, not proved | kept, tier 1 |
| Collusion detection | Synthetic rings only | kept, **unvalidated** |

The deep-ensemble result is the clearest: epistemic uncertainty is standard
practice and it made calibration *worse*, interpretable only because a capacity
control was run alongside — the architecture helps, the epistemic signal destroys
the gain.

---

## 7. Three measurements that ran against the design

Reported at the same weight as the results that favour the mechanism, because a
document reporting only its confirmations is not evidence of much.

### 7.1 The unbonding period is unaffordable

The period must exceed the time a claimant needs to notice a bad decision and
act. For US consumer credit that is statutory, not estimable: 60 days for the
consumer's free-file window (15 U.S.C. § 1681j, cited in § 1681m(a)), 30 days for
reinvestigation (§ 1681i(a)(1)(A)), and 15 days for the permitted extension
(§ 1681i(a)(1)(B)) — **τ = 105 days**, fifteen times the value used in tests.
Each term is a statutory maximum, the right posture for a security parameter.

Re-running the carrying cost $r \tau S$ at $r = 5\%$ inverts the earlier
conclusion. At 7 days the carry is 0.0959% per cycle; at 105 days it is
**1.4384%**, exceeding the expected slash (realised Brier 0.1758 times the
dispute rate) for **any dispute rate below 8.18%** — roughly 8× at 1%.

This weakens the paper's own incentive argument: if the slash is an eighth of
the total cost, the 15% saving from calibration is about 1.7% of what
participation costs. τ is pinned by statute above and by capital cost below, and
the bounds do not meet, so closing the gap needs a different instrument —
bonded insurance, rolling tranche release, or an at-risk fraction below the full
stake — none of which is a parameter change.

### 7.2 A subgroup gap that was noise, then real

Aggregate ECE averages over the population, so it is blind to a defect confined
to a subgroup — the sharpest scientific gap in the mechanism. The plan was to
construct the adversary, show aggregate ECE misses it, and track a within-group
variant on-chain.

The first-order result looked like confirmation: within-group ECE exceeds
aggregate in **10 of 10** seeds, 0.1349 against 0.0870. **It does not survive a
control.** Permuting subgroup labels while holding group sizes fixed reproduces
the entire effect — null gap 0.0559 against the real partition's 0.0548, Wilcoxon
$p = 0.92$, the real partition beating its own null in 3 of 10 seeds.

The cause is a small-sample bias in ECE itself. Within-bin accuracy is estimated
from a handful of points and $|acc - conf|$ is an absolute value, so sampling
error accumulates instead of cancelling. A model calibrated *by construction*
($p \sim U(0,1)$, $y \sim \text{Bernoulli}(p)$) scores:

| n | 68 | 106 | 200 | 500 | 2,000 | 10,000 |
|---|---|---|---|---|---|---|
| ECE | 0.1188 | 0.0989 | 0.0695 | 0.0451 | 0.0223 | 0.0098 |

The test split is 200 rows and the measurable subgroups hold 68 and 106. **At
n = 68 the estimator's own bias (0.1188) exceeds the pipeline's aggregate ECE
(0.0870).**

On the 30,000-row dataset, where subgroups hold 2,336–3,664, the same analysis
resolves it: the effect **survives its permutation null** (gap 0.0067 vs 0.0042,
8/10 seeds, $p = 0.037$) and is about 12% of aggregate ECE. Both halves matter.
The effect exists, *and* the first measurement of it was noise — reporting only
the first would have overstated the problem sevenfold (an apparent 0.0479 against
a measured 0.0067); reporting only the second would have missed that the
instrument was what was being measured.

`SubgroupReputationRegister.sol` was **not built** either way, because binned
ECE's bias at realistic group sizes is twenty times the effect it would enforce
on. Tests pin the null against erosion: shrinking the minimum group size,
dropping the permutation control, or letting $p$ fall below 0.05 all fail loudly.

### 7.3 A detector whose AUC does not describe it

The collusion detector reports **AUC 0.998** on injected rings and is wired to
withhold a claimant's payout. Its false-positive rate on real traffic is
unobtainable — the protocol has never run. But on synthetic traffic containing
*no rings*, every flag is false by construction, and at the threshold the
contract actually enforces (`MIN_SCORE = 0.8e18`, below which `flag()` reverts):

| Traffic | FPR | Recall | FDR |
|---|---|---|---|
| No rings present | **0.94%** (95% Wilson upper bound **1.51%**) | — | — |
| Rings at intensity 0.85 | 2.41% | 87.2% | **19.9%** |
| Rings at intensity 0.40 | 1.79% | 16.1% | **50.0%** |

17 of 1,800 honest claimants flagged in a world with no collusion in it. One
flagged claimant in five is honest at the easiest setting; at the hardest the
detector recalls 16% while half of everyone it flags is innocent.

**AUC is threshold-free and integrates over operating points the contract cannot
reach.** The deployed system has one fixed operating point, and its precision
there is what governs whether attaching the oracle is defensible. Reporting a
threshold-free metric while enforcing at a fixed threshold is how a system comes
to look validated for something it is not. The recommendation is explicit: pass
`address(0)`.

This does not close the limitation: synthetic traffic from a generator whose
realism is itself an assumption clears the lowest available bar. What changes is
that an operator now has a measured number where there was none.

---

## 8. Limitations

Stated as the security model rather than as omissions from it. Five capabilities
an adversary retains today, each demonstrated by a passing test:

| Adversary capability | Covered | Mechanism, or reason not |
|---|---|---|
| Forge a proof for a head it did not run | yes | halo2 soundness; 4/4 tamper checks |
| Alter an attested confidence after the fact | yes | stored on chain, proof-bound |
| Substitute weights under a claimed version | yes | content hash |
| Exit stake ahead of a pending dispute | yes | unbonding delay + dispute freeze |
| Act alone as a single resolver | yes | N-of-M threshold |
| **Fabricate the input logit $L$** | **no** | tier 1 binds the head, not the pipeline |
| **Corrupt N of M resolvers** | **no** | equals v0's single-key power |
| **Exit before any dispute is raised** | **no** | a bound on the dispute window, not the lock |
| **Misreport within a protected subgroup** | **no** | measurable only at scale (§7.2) |
| **Flag an honest claimant** | **no** | detector unvalidated on real traffic (§7.3) |
| Train dishonestly, register truthfully | no | content integrity ≠ training integrity |

Beyond these: **ground truth for a rejection is unobservable** — a rejected
applicant never demonstrates repayment, so "the decision was wrong" has no
on-chain referent, and moving from one voter to $N$ does not create a fact that
did not exist. This is unsolved, not merely unimplemented.

**Empirical scope.** Two datasets, but both credit, tabular, binary, and run on
one model family — nothing here separates "this calibration result holds
generally" from "this holds for gradient-boosted trees." Calibration drift over
time is unevaluated. Staking parameters are demonstration values with no
actuarial basis, and correlated tail risk is not modelled.

**Vocabulary.** `docs/PHASE3B_TRUST_MODEL.md` fixes the vocabulary for describing
dispute resolution, and was written before the code it describes.
`tests/test_claim_vocabulary.py` greps this document for language attributing
properties the system lacks — the forbidden list lives in the test rather than in
prose, so a later edit cannot quietly upgrade a claim.

---

## 9. Open problems

Ordered by what blocks what. Two items are recorded as closed by measurements in
this paper, and every item that was actually executed came back different from
how it was specified — which is the pattern worth noting.

1. **Input-logit provenance.** Three routes, in decreasing order of guarantee:
   prove the base classifier in-circuit (prohibitive for depth-8, 400 trees);
   commit to the feature vector and weights, making fabrication *detectable*
   rather than impossible (cheap, closest to shippable); or attest the base model
   in an enclave (weakest — hardware trust replacing cryptographic trust).
2. **A defensible dispute layer.** A staked jury with an evidentiary standard and
   appeals. Blocked on a definition of the adjudicated event that does not yet
   exist.
3. **Decoupling the dispute window from capital lockup** — opened by §7.1, since
   no value of τ is satisfactory.
4. **A debiased calibration estimator**, characterised at the group sizes a
   deployment will see — opened by §7.2, and blocking any subgroup slashing rule.
5. **A second model family, and drift.** Now the more glaring empirical gap, and
   cheaper than the replication already done.
6. **Real labelled disputes**, without which §7.3's limitation cannot close.

**Explicitly out of scope.** Non-deterministic decision classes such as LLM
outputs are *substantially harder, not a natural extension*: free-form generation
has no canonical scalar confidence, no binary ground truth, and no stable notion
of "the same decision" across sampling seeds. Applying a proper scoring rule
there requires first defining the event space being scored, which is a research
problem rather than an engineering task.

---

## 10. Conclusion

The mechanism-design claim is supported: slashing by a strictly proper scoring
rule makes honest confidence loss-minimising, the property survives fixed-point
on-chain arithmetic, and it is cheap — 543 gas for the arithmetic itself, 2.09 s
to prove the head. Proposition 2 adds a condition a deployer would otherwise get
wrong, since capping the slash looks prudential and inverts the mechanism.

The systems claim is **not** supported. A proved calibration head is not
sufficient for a trustworthy attestation: the proof binds the map from logit to
confidence and nothing else, so an operator that fabricates the logit obtains a
proof that verifies. Dispute resolution remains an admin-appointed committee
whose collusion carries the authority a single key did.

That invariance is the most durable result here. A better base model, a stronger
uncertainty quantifier, a richer evidence bundle, a reputation history and a
version registry all now sit on top of the same unproven input. **Sophistication
above the trust boundary does not move the trust boundary**, and this work is a
fairly thorough demonstration of that.

The economic answer is narrower still. Attaching an attestation pays only where
verification costs less than the errors it screens out — at measured L1 prices it
does not — and against a single buyer an optimally tuned flat bond achieves
*exactly* the same welfare. The separation is real but specific: a bond
compresses quality into one pooled threshold, while an attested confidence is a
sufficient statistic each buyer applies its own threshold to, worth 70.5% of the
available gain across a heterogeneous buyer mix. That heterogeneity is modelled
and not measured.

The three measurements of §7 ran against the design and are reported at full
weight. Two of them are cautions about instruments rather than about the
mechanism — an estimator whose small-sample bias exceeded the effect it was
measuring, and a threshold-free metric that did not describe the fixed threshold
its contract enforces. Both are mistakes a careful reader of the earlier
literature could have made.

The most useful result may be the negative one: it establishes precisely which
parts of "verifiable AI accountability" the cryptography actually buys, and which
parts remain a matter of whom you trust.

---

## Reproducibility

Every number is produced by a script; none is transcribed by hand. This sequence
was executed against a fresh `git clone`, which found a real defect —
`contracts/lib/` is not committed, so `forge test` failed until the
`forge install` line below was added. With it, the clean checkout runs **144
Solidity and 113 Python tests green** and regenerates the market-model and
subgroup artifacts **byte-identical**.

```bash
pip install -r requirements.txt
bash scripts/00_setup_tools.sh
cd contracts
forge install foundry-rs/forge-std@v1.16.2 --no-git
cd ..
python scripts/10_train_calibrate.py
python scripts/12_multiseed_eval.py
python scripts/31_zk_prove.py
python scripts/23_second_dataset.py
python scripts/22_market_model.py
python scripts/21_subgroup_adversary.py
python scripts/24_detector_fpr.py
cd contracts && forge test
python -m pytest tests/ -q
```

In order: EZKL v23.0.5 and the un-committed Foundry library; calibration with
its ECE gate and the 10-seed pass (§6.1); circuits and proofs (§6.2); the
second-dataset replication (§6.1); the market model, which produces every number
in §4; the subgroup null (§7.2); the detector's false-positive rate at the
enforced threshold (§7.3); then both suites.

Two limits on that verification, stated so it is not read as more than it is: it
ran on the development machine and OS, so it establishes self-containment rather
than portability; and the zkML stages were not re-run in the clean checkout, so
§6.2's proving figures come from committed artifacts rather than a fresh proving
run.

`ThreatModel.t.sol` does **not** assert the system is secure — it asserts that
each documented weakness is real and reachable, so a failure there means the
threat model has drifted from the code and this paper is wrong.

---

## References

[1] European Union, *Artificial Intelligence Act*, Articles 26 and 86.
<https://eur-lex.europa.eu/eli/reg/2024/1689/oj>

[3] Chainlink Labs, *Chainlink Staking v0.2*.
<https://blog.chain.link/chainlink-staking-v0-2-overview/>

[4] Nexus Mutual, *Claims Assessment*.
<https://docs.nexusmutual.io/overview/claims/>

[5] M. Nechepurenko and P. Shuvalov, *Foresight Arena: An On-Chain Benchmark for
Forecasting*, 2025. <https://arxiv.org/abs/2510.11009>

[6] ZKonduit, *EZKL: Zero-Knowledge Inference for ONNX Graphs*.
<https://github.com/zkonduit/ezkl>

[7] C. Lesaege, F. Ast, and W. George, *Kleros Short Paper v1.0.7*, 2019.
<https://kleros.io/whitepaper.pdf>

[9] G. W. Brier, *Verification of Forecasts Expressed in Terms of Probability*,
Monthly Weather Review 78(1), 1950.

[10] T. Gneiting and A. E. Raftery, *Strictly Proper Scoring Rules, Prediction,
and Estimation*, JASA 102(477), 2007.

[11] C. Guo, G. Pleiss, Y. Sun, and K. Q. Weinberger, *On Calibration of Modern
Neural Networks*, ICML 2017. <https://arxiv.org/abs/1706.04599>

[16] V. Vovk, A. Gammerman, and G. Shafer, *Algorithmic Learning in a Random
World*, Springer, 2005 — the conformal prediction framework.

[22] M. Kearns, S. Neel, A. Roth, and Z. S. Wu, *Preventing Fairness
Gerrymandering*, ICML 2018. <https://arxiv.org/abs/1711.05144>

[23] *ERC-8004: Trustless Agents*, Ethereum Improvement Proposals.
<https://eips.ethereum.org/EIPS/eip-8004>

[24] X. Xiong, Z. Li, W. Wei, Q. Wang, W. Knottenbelt, and Z. Wang, *Can
Trustless Agents Be Trusted? An Empirical Study of the ERC-8004 Decentralized AI
Agent Ecosystem*, arXiv:2606.26028.

[25] Z. Li, Q. Wang, and Z. Wang, *Five Attacks on x402 Agentic Payment
Protocol*, arXiv:2605.11781.

[26] *Free-Riding the Agentic Web: A Systematic Security Analysis of x402
Payments*, arXiv:2605.30998.

[27] Y. Li, L. Wang, K. Wang, Z. Yang, K. Wang, Z. Guan, and J. Gao, *A402:
Binding Cryptocurrency Payments to Service Execution for Agentic Commerce*,
arXiv:2603.01179.

[28] D. Shi and K. Joo, *Sybil-Resistant Service Discovery for Agent Economies*,
arXiv:2510.27554.

[29] HeLa Labs, *HeLa Chain Whitepaper v2*, §5.5.
<https://blog.helachain.com/whitepaper/>

**Statutory sources for §7.1.** 15 U.S.C. § 1681i(a)(1)(A) and (B);
15 U.S.C. § 1681m(a). <https://www.law.cornell.edu/uscode/text/15/1681i>
