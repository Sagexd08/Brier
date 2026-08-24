# Phase 2 — explainability vector

## Method

`shap.TreeExplainer` over the base XGBoost model. TreeExplainer is *exact* for
tree ensembles rather than sampling-based, so attributions are deterministic
given a model and an input — there is no Monte-Carlo variance to seed away.
Determinism is still verified rather than assumed
(`test_attributions_are_deterministic` asserts bit-identical reruns, and the
Phase 2 script retrains the base model 3x and compares).

Attributions are computed in **margin space**, matching the quantity the
calibration head consumes. Per decision we keep the **top-5 features by
|SHAP|**, preserving sign: positive pushes toward REJECT (the model's positive
class is "bad credit").

## Correctness check: additivity

SHAP values are an additive decomposition, so

```
sum(shap_values) + base_value == model_margin
```

Measured max absolute error across the test split: ~1.3e-05 (float32 tree
traversal). If this were violated, the attributions would not describe the
model that actually made the decision. The script fails hard above 1e-3.

## Directional sanity checks

Five claims a credit analyst would make were written down **before** looking at
the output, then verified by correlating each feature's value with its SHAP
contribution toward reject. All five pass; results are in `RESULTS.md`.

## A real bug this phase caught

The first run FAILED the `credit_history` check with a correlation of **+0.927**
where the claim predicted a negative value — an emphatic failure, not a
marginal one.

The investigation showed **the encoding was wrong and the model was right.**
Measured bad rates by raw code:

| Raw code | Codebook meaning | Bad rate | n |
|---|---|---|---|
| A30 | no credits taken / all paid back duly | **62.5%** | 40 |
| A31 | all credits at this bank paid back duly | 57.1% | 49 |
| A33 | delay in paying off in the past | 31.8% | 88 |
| A32 | existing credits paid back duly till now | 31.9% | 530 |
| A34 | critical account / other credits existing | **17.1%** | 293 |

The naive reading — "no credits taken/all paid duly" sounds like the best
customer — is backwards for this dataset. A *thin file* is riskier than a
thick, currently-serviced one, because existing serviced credit at other
institutions is evidence of demonstrated creditworthiness. This is a
well-documented quirk of the Statlog German Credit data.

The ordinal map now follows empirical risk order. A32 and A33 differ by 0.0007
in bad rate (noise at these sample sizes) and are ordered by codebook semantics
instead. After the fix `credit_history` correlates **-0.756**, and all five
checks pass.

`tests/test_phase2.py::test_credit_history_encoding_follows_empirical_risk`
pins this so the naive ordering cannot creep back.

**The general lesson:** the explainability layer caught a data-encoding bug
that the accuracy and ECE metrics did not surface. That is a point in favour of
committing explanations as evidence, which is the argument this project makes.

## Manual inspection

Three decisions were read by hand (script output in the build log):

- **Most confident reject** (margin +7.42, truly bad): 36-month term, checking
  balance < 0 DM, no savings — all pushing reject. Coherent.
- **Most confident approve** (margin −12.51, truly good): best checking status,
  established credit history, 4–7 years employment — all pushing approve.
- **Most borderline** (margin +0.014, truly good): genuinely conflicting —
  strong savings pushing approve against a 4,712 DM request over 24 months
  pushing reject. A borderline case looks borderline for legible reasons.

### Caveat

`credit_amount` occasionally attributes *toward approve* at mid-range values
(e.g. 2,302 DM in the confident-reject case). That is not obviously wrong —
tree models learn non-monotonic amount effects, and mid-range requests from
otherwise-weak applicants can be less risky than very small or very large ones
— but it is **not verified** here, and no monotonicity constraint is imposed.

## What the on-chain commitment does and does not prove

The SHAP vector is hashed and committed, **not zk-proved**. The commitment
proves the operator recorded *this* explanation at decision time and did not
alter it afterwards. It does **not** prove the explanation faithfully describes
the model, nor that the model produced the decision. An operator can commit an
arbitrary vector; the hash binds them to it, nothing more.

Serialisation is quantised to a fixed 6 decimal places so that the hash
reproduces across platforms.
