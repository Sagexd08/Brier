# Phase 3b — dispute resolution: bounded trust, NOT decentralization

**This document was written before the code it describes.** The point is to fix
the language while the implementation is still hypothetical, so the claim cannot
drift upward once the tests go green. Any wording in README, PROPOSAL, or the
diagrams that exceeds what is stated here is a defect.

## The one-sentence claim

> Dispute resolution requires **N of M** signatures from a **fixed, admin-set**
> resolver committee, replacing the single admin key.

## What this is NOT

Say all of it plainly, because each of these is a thing an N-of-M multisig is
routinely mistaken for:

- **It is not decentralized.** The committee is a fixed list. Its members are
  chosen by whoever deploys the contract. There is no permissionless entry, no
  staking, no token, no sortition, and no way for an outsider to become a
  resolver.
- **It is not trustless.** It is *bounded* trust: instead of trusting one key,
  you trust that fewer than N of M members collude. That is a weaker assumption
  than trusting one key, and a much stronger assumption than trusting nobody.
- **It is not a jury.** Kleros-style adjudication draws jurors randomly from a
  staked pool with appeals and Schelling-point incentives. None of that is here.
- **It does not add an evidentiary standard.** Resolvers still vote on a bare
  boolean. Nothing in the contract defines what evidence a resolver should
  consult, or penalises one who consults none.
- **It does not solve ground truth.** For a loan rejection the counterfactual
  remains unobservable — a rejected applicant never demonstrates repayment.
  Moving from one voter to N voters does not create a fact that did not exist.
- **It does not make the committee accountable.** Resolvers have nothing at
  stake. A resolver who votes dishonestly loses nothing.

## What changes, precisely

| | v0 | after 3b |
|---|---|---|
| Who can resolve | one admin address | any N of M committee members |
| Cost to corrupt | compromise 1 key | collude/compromise N keys |
| Who picks the resolvers | — | the admin, at deploy and by later change |
| Resolver accountability | none | none |
| Evidentiary standard | none | none |
| Ground truth | unobservable | unobservable |

The honest summary: **the number of keys that must be corrupted goes from 1 to
N. Nothing else about the trust model changes.**

## Where this sits in the Figure C tiers

Tier 3 ("fully trusted") does **not** become tier 1 ("cryptographically
guaranteed"). It does not become tier 2 either, because there is no economic
mechanism holding resolvers honest — nothing is staked.

Figure C will be redrawn with tier 3 relabelled from

> **FULLY TRUSTED** — a single key decides who loses money

to

> **BOUNDED TRUST** — an N-of-M committee decides who loses money;
> N colluding members can decide it arbitrarily

The tier keeps its red colour. It is a smaller red region, not a different
colour.

## Residual attack, stated in advance

An adversary who controls N committee members has exactly the power the single
admin had in v0: slash an honest operator to zero, or shield a miscalibrated
one indefinitely. The Phase 3a residual gap B — that a resolution can unfreeze
an operator's withdrawal — persists identically, now requiring N signatures
instead of 1.

This will be asserted by a test (`test_tier3_nOfMCollusionHasSameEffectAsV0Admin`)
so the limitation is executable rather than a sentence someone can quietly drop.

## Approved vocabulary

Permitted: "bounded trust", "N-of-M committee", "multi-signature resolution",
"reduces single-key risk", "requires N colluding signers".

The forbidden list is defined in `tests/test_claim_vocabulary.py::FORBIDDEN`
(single source of truth, so the list and its enforcement cannot drift apart). It
covers wording that would attribute to this system properties it does not have:
distributed governance, absence of trusted parties, open membership, or
jury-style adjudication. A grep-based test fails the build if any such wording
appears in README, PROPOSAL, RESULTS, or this document outside an explicit
denial.
