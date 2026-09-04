/**
 * A toy decision-selling endpoint behind the Brier attestation gate.
 *
 * Runs against a local Anvil chain with the real Attestation.sol deployed, so
 * the gate exercises an actual eth_call rather than a stub. See the README for
 * the three commands that bring it up.
 *
 *   GET /credit-score
 *     header: x-brier-attestation: 0x<32 bytes>
 *
 *   200 -> the attestation exists and its proof verified; the decision is
 *          returned along with the confidence the seller is now slashable on.
 *   402 -> the gate refused, with a `brier_attestation_required` body naming
 *          which check failed.
 *
 * ORDERING NOTE, and it is the point of the example. The gate is mounted
 * BEFORE any x402 payment middleware would be. An attestation gate placed
 * after settlement is decorative: the buyer has already paid for a decision
 * the seller never committed to.
 */

import express from "express";
import { requireBrierAttestation, type AttestationRecord } from "../src/index.js";

const PORT = Number(process.env.PORT ?? 4020);
const RPC_URL = process.env.RPC_URL ?? "http://127.0.0.1:8545";
const ATTESTATION_ADDRESS = process.env.ATTESTATION_ADDRESS as `0x${string}`;

if (!ATTESTATION_ADDRESS) {
  console.error(
    "ATTESTATION_ADDRESS is required. Deploy Attestation.sol to a local Anvil\n" +
      "chain and pass its address -- see x402-middleware/README.md.",
  );
  process.exit(1);
}

const app = express();

const gate = requireBrierAttestation({
  attestationAddress: ATTESTATION_ADDRESS,
  rpcUrl: RPC_URL,
  // Fail closed: an RPC outage must become downtime, not a silent bypass.
  failOpen: false,
});

app.get("/credit-score", gate, (req, res) => {
  const att = (req as any).brierAttestation as AttestationRecord;

  // In a real seller this is where the x402 payment middleware would settle,
  // and where the decision would actually be computed. Here the attestation
  // already carries the committed confidence, so the endpoint just reports it.
  res.json({
    decision: Number(att.confidence) / 1e18 > 0.5 ? "reject" : "approve",
    confidence: att.confidence.toString(),
    confidencePct: `${((Number(att.confidence) / 1e18) * 100).toFixed(2)}%`,
    operator: att.operator,
    modelVersion: att.modelVersion,
    // Stated in the response so a buyer cannot mistake what they bought.
    guarantee:
      "The calibration head's execution is zk-proved and the operator is " +
      "slashable in proportion to (confidence - outcome)^2 if this decision " +
      "is overturned. The base model's logit is NOT proved, and correctness " +
      "is not adjudicated here.",
  });
});

/** Ungated, for contrast: what selling a decision without the gate looks like. */
app.get("/credit-score-ungated", (_req, res) => {
  res.json({
    decision: "reject",
    confidence: "0.99",
    guarantee: "none -- nobody committed to this number and nobody is slashable for it",
  });
});

app.get("/health", (_req, res) => res.json({ ok: true, attestation: ATTESTATION_ADDRESS }));

app.listen(PORT, () => {
  console.log(`brier x402 gate listening on :${PORT}`);
  console.log(`  attestation contract ${ATTESTATION_ADDRESS}`);
  console.log(`  rpc                  ${RPC_URL}`);
});

export { app };
