# Phase 4 — smart contracts

Three contracts, Foundry, Solidity 0.8.24, 48 tests passing.

| Contract | Role |
|---|---|
| `BrierMath.sol` | Pure fixed-point Brier slashing arithmetic. |
| `Attestation.sol` | Records decision + confidence + SHAP hash + zk proof. |
| `StakePool.sol` | Staking, disputes, slashing, payout. |
| `VerifierTemperature.sol` | EZKL-generated halo2 verifier (not hand-written). |

## The slashing rule

```
slash = min( stake * (confidence - outcome)^2 , stake * maxSlashBps / 10000 )
```

WAD fixed point (1e18 = 1.0). Confidence is the operator's stated probability
that its decision was correct; outcome is 1 if upheld, 0 if overturned.

## Precision and overflow analysis

Requested explicitly in the build plan, so it is stated rather than assumed:

- **`diff * diff` cannot overflow.** `diff <= 1e18`, so the product is at most
  1e36 ≈ 2^120, far below 2^256. No `unchecked` blocks are used anywhere in
  the library; every arithmetic op is checked.
- **`stake * sqErr` cannot overflow in practice.** Overflow needs a stake above
  ~1.15e59 wei ≈ 1.15e41 ETH; total supply is ~1.2e8 ETH. Tested at 1e30 wei.
- **Truncation is bounded and directional.** `(diff*diff)/WAD` rounds *down*, so
  rounding always favours the operator, never the claimant. A confidence of
  1 wei-of-WAD yields a squared error of 0 rather than 1e-36. This is a
  deliberate, documented choice; the alternative (rounding toward the claimant)
  would let a claimant extract dust from a perfectly calibrated operator.
- **`slash <= stake` always**, verified by fuzzing, so the subtraction in
  `resolveDispute` can never underflow.

## The properties that make this meaningful

Two are worth more than the rest, and both are verified numerically rather
than argued:

**1. Monotonicity in miscalibration.** As stated confidence rises on a *wrong*
decision, the slash must strictly rise; on a *right* decision it must strictly
fall. Checked at 101 points deterministically and by fuzzing (256 runs each
direction). If this failed, an operator could reduce its penalty by claiming
*more* confidence in a wrong answer, and the mechanism would be worthless.

**2. Properness — honest reporting is optimal.** If the true probability of
being correct is `p`, expected slash is minimised by *reporting* `p`. Verified
by scanning all 101 reports at `p = 0.70` and again at `p = 0.30` (a second
point, so it is not a coincidence of one value). This is the economic claim of
the whole project, reduced to a passing test.

Note the cap deliberately *breaks* monotonicity above the cap point — every
value past it flattens. So the property is stated and tested against the
**uncapped** `rawSlash`, and the cap is tested separately.

## The three headline scenarios (unit-tested)

Stake 100 ETH, cap 100%:

| Scenario | Confidence | Outcome | Slash | % of stake |
|---|---|---|---|---|
| Confident + correct | 0.99 | upheld | 0.01 ETH | 0.01% |
| Confident + wrong | 0.99 | overturned | 98.01 ETH | 98.01% |
| Uncertain + wrong | 0.55 | overturned | 30.25 ETH | 30.25% |

Confident-and-wrong costs **3.2x** uncertain-and-wrong, and **9,801x**
confident-and-correct. That spread is the product.

## Gas: the honest number

On-chain verification of a real EZKL proof costs **684,696 gas**; a full
attestation (verify + store) costs **887,376 gas**. At 30 gwei / $3,000 ETH
that is roughly **$62 per attested decision**, plus ~$265 once to deploy the
2.94M-gas verifier.

This is the most serious practical obstacle in the design, and it is measured
on a real proof rather than estimated. The Brier arithmetic is irrelevant by
comparison at ~543 gas — essentially all cost is halo2 verification.

An L2 or proof aggregation would change this by 1–2 orders of magnitude.
Neither is implemented here.

## What the tests deliberately do NOT cover

- **Dispute resolution is `onlyAdmin`.** The tests verify that only the admin
  can resolve and that the arithmetic is right. They cannot verify that the
  admin is *honest*, because nothing in this design makes it so.
- **`withdraw` has no unbonding period.** An operator watching the mempool can
  withdraw stake before a dispute is opened against it. This is a real
  vulnerability, left in deliberately and documented rather than papered over
  with a half-measure — a correct fix needs the dispute-window design that the
  MVP does not have.
- **No reentrancy guard on `resolveDispute`.** State is updated before the
  external call (checks-effects-interactions), and a failed payout reverts the
  whole resolution, which is tested. A production version should still add an
  explicit guard.
