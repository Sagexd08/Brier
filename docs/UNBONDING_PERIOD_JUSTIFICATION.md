# The unbonding period, derived rather than guessed

**Task 4. Companion to `PAPER.md` §7.3 and §6.11.**

`StakePool.sol` takes `unbondingPeriod` as a constructor parameter with no
principled default. The tests use 7 days. §7.3 admits that number is "almost
certainly too short" for decisions with delayed counterfactuals, and offers no
data behind either the 7 or the admission.

This document derives a number from primary sources, then re-runs §6.11's
capital-efficiency arithmetic with it.

**The headline is a negative one for the mechanism, and it is stated first
because it reverses what v0 claimed.** A defensible unbonding period for
consumer credit is **105 days**, fifteen times the value in the tests. At that
length the carrying cost is no longer "a minor cost relative to a single
dispute," as §6.11 says of the 7-day figure — it becomes the **dominant** cost
for any dispute rate below 8.18%, which is every plausible dispute rate. The
tradeoff is materially worse than v0 admitted.

---

## 1. What the unbonding period has to cover

The period exists to stop an operator withdrawing stake before a dispute over
one of its decisions can be filed and resolved. `Unbonding.t.sol` pins the
attack it closes (`test_tier2_frontRunDisputeByWithdrawing_isNowBlocked`).

So the required length is the **worst-case latency from a decision being made
to a dispute over it being filed** — not the time to resolve one, which the
open-dispute counter already handles by freezing withdrawal while a dispute is
open. The question is how long a decision stays disputable.

For a pay-per-decision credit-scoring service — the use case §1.1 builds on and
the one x402 is a plausible transport for — that latency is set by statute, not
by protocol design. It can therefore be read off rather than estimated.

## 2. The statutory chain (US, FCRA)

Three provisions compose, and the total is what matters.

**(a) The consumer must first learn a decision was made.** Under
**15 U.S.C. § 1681m(a)**, a user taking adverse action based on a consumer
report must notify the consumer, disclose the credit score and the reporting
agency, and state that the agency did not make the decision. Critically, **the
statute sets no deadline for providing this notice.** That is an unbounded term,
addressed in §3 below.

**(b) The consumer has 60 days to obtain the file.** § 1681m(a) requires the
notice to include "an indication of the 60-day period under that section for
obtaining such a copy" of the consumer report free of charge, under § 1681j.
This is the window in which a consumer can obtain the evidence a dispute would
rest on.

**(c) Reinvestigation takes up to 45 days.** Under
**15 U.S.C. § 1681i(a)(1)(A)**, the agency must complete a reasonable
reinvestigation "before the end of the 30-day period beginning on the date on
which the agency receives the notice of the dispute from the consumer or
reseller." § 1681i(a)(1)(B) extends this "for not more than 15 additional days
if the consumer reporting agency receives information from the consumer during
that 30-day period that is relevant to the reinvestigation."

### The derivation

```
  60 days   consumer's free-file window (§ 1681j, cited in § 1681m(a))
+ 30 days   statutory reinvestigation period (§ 1681i(a)(1)(A))
+ 15 days   permitted extension (§ 1681i(a)(1)(B))
= 105 days
```

**τ = 105 days.**

Each term is a statutory maximum, so the sum is a worst case rather than an
average — appropriate for a security parameter, where the operator picks the
timing and will pick the worst case if it pays to.

### Why not the alternatives

- **Adding a notice-delivery allowance** would be inventing a number. The
  statute sets no deadline (§2a), so any figure would be a guess dressed as a
  derivation. Left explicitly unbounded in §3 instead.
- **The 2-year FCRA statute of limitations** would give τ = 730 days. That is
  the window for *suing over a violation*, not for disputing an entry, and using
  it would make the carrying cost absurd (10% of stake per cycle at r = 5%)
  while defending against a claim the mechanism does not adjudicate.
- **Prediction-market resolution windows** (Polymarket, via Foresight Arena in
  §2.4) were considered as the prompt suggests, and rejected as the primary
  anchor: those windows are set by contract terms chosen per market, ranging
  from hours to years, so they yield a distribution shaped by market design
  rather than a derivable bound. They remain the right anchor for a *forecasting*
  deployment, where no statutory window exists — and the number would have to be
  derived separately for that case rather than borrowed from this one.

## 3. What 105 days does not cover

Stated because the derivation is only as good as its scope conditions.

1. **Notice delivery is unbounded.** The clock in (b) starts when the consumer
   receives the adverse-action notice, and § 1681m(a) sets no deadline for
   sending it. An operator that delays notice delays the whole window. τ = 105
   days is measured from *notice*, not from *decision*, and the gap between them
   is not bounded by this statute.
2. **US only.** The RBI grievance-redressal timelines relevant to the Indian
   setting §1.1 discusses, and the GDPR/EU AI Act windows relevant to Article 86,
   would each yield a different number. A deployment picks the maximum across
   the regimes it operates in.
3. **Credit only.** A forecasting or risk-flag service has no statutory dispute
   window at all; its τ is set by when the forecast resolves, which is a
   property of the question and not of any law.
4. **It does not bound resolution**, only filing. Committee resolution latency
   is separate and is handled by the open-dispute freeze.

## 4. Re-running §6.11 with τ = 105 days

§6.11 gives the carrying cost of locked stake as `carry = r · τ · S` per cycle,
at opportunity cost `r`. With r = 5% annually:

| τ | Carry (% of stake per cycle) | §6.11's characterisation |
|---|---|---|
| 7 days (tests) | 0.0959% | "comparable to a single dispute" |
| **105 days (derived)** | **1.4384%** | **dominant cost** |

Against the expected slash per cycle, which is the realised Brier score (0.1758
calibrated, §6.5) times the dispute rate:

| Dispute rate | Expected slash | Carry at τ=7d | Carry at τ=105d |
|---|---|---|---|
| 0.1% | 0.0176% | 0.0959% | 1.4384% |
| 1% | 0.1758% | 0.0959% | 1.4384% |
| 5% | 0.8790% | 0.0959% | 1.4384% |

**The crossover.** Carry exceeds the expected slash whenever the dispute rate
falls below `r · τ / B`:

- at τ = 7 days: below **0.545%** — so at a 1% dispute rate the slash dominates
  and §6.11's characterisation is correct;
- at τ = 105 days: below **8.18%** — so carry dominates across the entire
  plausible range.

Equivalently, at a 1% dispute rate the two costs are equal at τ = 12.8 days.
Any statutorily defensible period for consumer credit is far past that point.

**The honest conclusion, which contradicts §7.3's framing.** §7.3 treats the
7-day period as too short and implies lengthening it is straightforwardly
correct. Lengthening it *is* correct on the security axis — the front-running
attack is real and 7 days does not close it for credit decisions. But the cost
is not incidental: a defensible τ makes capital lockup the largest single cost
of participating, roughly **8× the expected slash** at a 1% dispute rate. An
operator's dominant expense becomes holding stake idle, not being wrong.

That is a genuine and unresolved tension, and it should be read as a limitation
of the mechanism rather than a tuning problem:

- **It weakens the incentive story.** §6.11 argues calibration pays because it
  cuts expected loss by 15%. If the slash is an eighth of the total cost, that
  15% saving is roughly **1.7% of what participation actually costs** — a much
  weaker inducement than §6.11 implies.
- **It advantages large operators.** Carry is linear in stake but so is the
  slash cap, so the ratio is scale-invariant; what is not scale-invariant is
  access to cheap capital. A τ this long selects for operators with the lowest
  `r`.
- **It is not fixable by tuning τ.** τ is pinned by statute on one side and by
  capital cost on the other, and the two do not meet. Closing it needs a
  different instrument — bonded insurance, a rolling tranche release, or
  slashing from a smaller at-risk fraction than the full stake. None is
  implemented, and none is a parameter change.

## 5. What changes in the code

**Nothing yet, deliberately.** `MIN_UNBONDING_PERIOD` stays as it is and the
tests keep using 7 days: they exercise mechanism behaviour, and a 105-day
period would make every time-warp test slower without testing anything the
7-day case does not. What changes is that the *deployment* guidance now has a
derivation behind it.

This document is the justification a deployer needs to pick the parameter, and
the §4 arithmetic is the cost they are accepting when they do. A deployment
serving US consumer credit should pass **105 days** and budget for a 1.44%
per-cycle carrying cost.

## 6. Sources

All primary. No blog summaries; §1.1's RBI citation correction is the standard
this repository holds itself to.

1. **15 U.S.C. § 1681i(a)(1)(A)** — 30-day reinvestigation period.
   <https://www.law.cornell.edu/uscode/text/15/1681i>
2. **15 U.S.C. § 1681i(a)(1)(B)** — 15-day extension.
   Same source.
3. **15 U.S.C. § 1681m(a)** — adverse-action notice; the 60-day free-file
   indication; no stated deadline for the notice itself.
   <https://www.law.cornell.edu/uscode/text/15/1681m>
4. **`PAPER.md` §6.5** — realised Brier score 0.1758 (calibrated), 0.2060
   (uncalibrated), over 10 pinned seeds.
5. **`PAPER.md` §6.11** — `carry = r · τ · S`, and the r = 5% assumption
   carried forward here unchanged.
