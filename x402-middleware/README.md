# `@brier/x402-attestation-gate`

Express/Hono middleware that refuses an x402-priced request unless the seller
has published an on-chain Brier attestation for the decision being sold.

**Status: reference integration.** It runs, it is tested against a real chain,
and it is not a product. Its purpose is to make the "structural fit with x402"
claim in `PROPOSAL.md` a measured one rather than an assertion.

---

## What this does and does not guarantee

Read this section before the install instructions. The gate is narrow on
purpose, and a reader who takes it for more than it is will be worse off than
one who does not use it at all.

**It guarantees:** the seller published an attestation on chain, binding
themselves to a specific calibrated confidence for a specific decision hash,
with a zk proof of the calibration head's execution that the chain accepted —
and is therefore slashable by `S·(c−o)²` if that decision is later overturned.

**It does not guarantee the decision is correct.** Correctness is adjudicated
by `StakePool`'s dispute flow, which rests on an N-of-M resolver committee —
tier 3 in `PROPOSAL.md` §7.2. A verified attestation on a wrong decision is
still a verified attestation. What the attestation buys is that being wrong now
costs the seller money in proportion to how confident they claimed to be.

**It does not verify the base model.** Only the calibration head is proved
(§7.1). The input logit is supplied by the operator and is unproved, so an
operator who fabricates the logit produces a cryptographically valid proof of a
calibration step applied to a lie. `proofVerified` means the halo2 verifier
accepted the head's execution — not that the number fed into it was honest.

**It does not bind an attestation to a payment.** This is the sharpest
limitation, and it has a citation. Attack II of
[arXiv:2605.11781](https://arxiv.org/abs/2605.11781) (*Five Attacks on x402*) is
replay across the HTTP–chain boundary, and an attestation gate has exactly that
shape: one valid `attestationId` can be presented against unlimited requests,
because nothing here claims it, scopes it to a resource, or spends it. Their
mitigation M3 — bind resource scope, claim once before grant, TTL-bounded dedup
— is the correct pattern and is **not implemented**. `maxAgeSeconds` narrows the
window; it does not close the hole.

There is a test that pins this (`does not prevent replay …`). It asserts the
limitation rather than a feature: if someone adds claim-once semantics, that
test should fail and be rewritten. That is the signal it exists to give.

---

## Install and run

```bash
cd x402-middleware
npm install
npm test          # starts anvil, deploys the real contracts, runs the gate
```

The test suite brings up its own chain, so `npm test` is the whole command. It
requires `anvil` and `forge` on `PATH` (Foundry). If either is missing the
suite **fails** rather than skipping — a silently skipped integration test is
indistinguishable from a passing one on a dashboard.

### The example server

```bash
# 1. a local chain
anvil --port 8545

# 2. deploy Attestation.sol and seed a decision
cd contracts
forge script script/DeployMiddlewareFixture.s.sol:DeployMiddlewareFixture \
  --rpc-url http://127.0.0.1:8545 --broadcast

# 3. run the seller, using the address the script printed
cd ../x402-middleware
ATTESTATION_ADDRESS=0x... npm run example
```

Then:

```bash
# passes: the id the deploy script printed as verifiedId
curl -H "x-brier-attestation: 0x<verifiedId>" localhost:4020/credit-score

# 402 brier_attestation_required: no attestation on the request
curl localhost:4020/credit-score

# 402 brier_attestation_required: well-formed id that is not on chain
curl -H "x-brier-attestation: 0xabab...abab" localhost:4020/credit-score
```

---

## Usage

```ts
import express from "express";
import { requireBrierAttestation } from "@brier/x402-attestation-gate";

const app = express();

app.get(
  "/credit-score",
  requireBrierAttestation({
    attestationAddress: "0x...",
    rpcUrl: process.env.RPC_URL,
    maxAgeSeconds: 3600,
    allowedOperators: ["0x..."],
  }),
  handler,
);
```

Hono is the same decision behind a different wrapper:

```ts
import { brierAttestationHono } from "@brier/x402-attestation-gate";
app.use("/credit-score", brierAttestationHono({ attestationAddress: "0x..." }));
```

**Mount it before the x402 payment middleware.** Ordering is the point: gating
after settlement means the buyer has already paid for a decision the seller
never committed to.

### Options

| Option | Default | Notes |
|---|---|---|
| `attestationAddress` | required | Deployed `Attestation.sol` |
| `rpcUrl` / `client` | `http://127.0.0.1:8545` | `client` wins if both are given |
| `header` | `x-brier-attestation` | Its own header, not a field in the payment payload — Attack III is proxy-level header confusion, and mixing the two widens that surface |
| `allowQueryParam` | `false` | Query strings leak into logs and caches |
| `maxAgeSeconds` | `0` (off) | Measured in **chain** time, against the latest block — not the server's wall clock |
| `allowedOperators` | unset | Allow-list |
| `minConfidence` | `0` | See the warning below |
| `failOpen` | `false` | See below |

**`failOpen` defaults closed, deliberately.** Failing open turns an RPC outage
into a free bypass, and hands an attacker who can degrade your RPC the ability
to choose when the gate stops applying. Failing closed turns the same outage
into downtime — visible, and it does not silently sell unattested decisions.

**`minConfidence` is a floor on *asserted* confidence, which is not a quality
bar.** A high number means a bigger slash if the decision is overturned, not
evidence that the decision is right. Setting it rewards sellers for claiming
confidence, which is the opposite of what the mechanism is for. Think twice.

### Failure reasons

The 402 body carries `error: "brier_attestation_required"` — deliberately
distinct from a plain x402 `payment required`, because the client's payment may
be perfectly good and a client that cannot tell these apart will retry payment
forever.

| `reason` | Meaning |
|---|---|
| `attestation_missing` | No id on the request |
| `attestation_malformed` | Present, not a bytes32 (rejected without touching the chain) |
| `attestation_unknown` | Well-formed, not on chain |
| `attestation_unverified` | On chain but the proof did not verify — see below |
| `attestation_stale` | Older than `maxAgeSeconds` in chain time |
| `attestation_wrong_operator` | Not in `allowedOperators` |
| `attestation_lookup_failed` | RPC failure — **your** fault, not the client's |

**A note on `attestation_unverified`, because the honest description is less
impressive than it sounds.** `Attestation.attest` *reverts* when the verifier
rejects a proof ([`Attestation.sol:76`](../contracts/src/Attestation.sol#L76)),
so a record with `proofVerified == false` cannot be created through the current
write path at all — the contract says so at line 57, and the integration test
proves it on a live chain rather than trusting the comment. In practice a
rejected proof surfaces as `attestation_unknown`.

The check stays because it is cheap and because the guarantee lives in a
contract this middleware does not control: a future write path, a backfill
migration, or a different `Attestation` deployment could all produce an
unverified record. It is defence in depth, not the gate's primary function.

---

## Why this is not a formal x402 V2 extension

x402 V2 has an extension mechanism — resource servers advertise supported
extensions in `PaymentRequired` and clients echo them in `PaymentPayload` — and
that is architecturally the right home for a Brier attestation, which is
exactly "modular optional functionality beyond core payment mechanics."

This gate deliberately sits *around* the payment flow instead. Registering a
real extension requires a published schema and an identifier, and this project
has no standing to mint one. Shipping a middleware that gates alongside the
payment flow is an honest reference integration; shipping something that
presents itself as a standard extension would not be.

`RELATED_WORK_V2.md` §9 records this as the natural next step if the mechanism
is ever taken up.

## Related

- `RELATED_WORK_V2.md` §1 — ACHIVX, whose provider middleware shape this follows
- `RELATED_WORK_V2.md` §6 — the five x402 attacks, and which constrain this gate
- `PROPOSAL.md` §7 — the full limitations, of which this file repeats the three
  that bear on an integrator
