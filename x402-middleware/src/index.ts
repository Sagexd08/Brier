/**
 * Brier attestation gate for x402-priced endpoints.
 *
 * WHAT THIS GATES, precisely. An x402 resource server sells a decision. This
 * middleware refuses to let the payment flow proceed unless the seller has
 * published an on-chain Brier attestation for that decision whose zk proof the
 * chain accepted. It is a gate on "did the seller commit, verifiably, to a
 * calibrated confidence for this decision", and nothing else.
 *
 * WHAT IT DOES NOT GATE, and these are not hypothetical caveats:
 *
 *   1. It does not adjudicate whether the decision was CORRECT. That is
 *      StakePool's dispute flow, and it is tier 3 -- it rests on the N-of-M
 *      resolver committee. A verified attestation on a wrong decision is still
 *      a verified attestation; what it buys is that the seller is now slashable
 *      for it in proportion to how confident it claimed to be.
 *
 *   2. It does not verify the base model. Only the calibration head is proved
 *      (PAPER.md 7.1). The input logit is supplied by the operator and is
 *      unproved, so an operator that fabricates the logit produces a
 *      cryptographically valid proof of a calibration step applied to a lie.
 *      `proofVerified` means the halo2 verifier accepted the head's execution.
 *      It does not mean the number fed into the head was honest.
 *
 *   3. **It does not bind an attestation to a payment.** This is the sharpest
 *      limitation and it has a citation: Attack II of arXiv:2605.11781 (Five
 *      Attacks on x402) is replay across the HTTP-chain boundary, and an
 *      attestation gate has exactly that shape. One valid attestationId can be
 *      presented against unlimited requests, because nothing here claims it,
 *      scopes it to a resource, or expires it. Their mitigation M3 -- bind
 *      resource scope, claim once before grant, TTL-bounded dedup -- is the
 *      correct pattern and is NOT implemented. `maxAgeSeconds` narrows the
 *      window; it does not close the hole. Gating on an attestation is not the
 *      same as binding a payment to one.
 *
 * Shape is modelled on ACHIVX's `@achivx/x402` provider middleware, which is
 * the integration surface x402 sellers already expect: read something off the
 * request, do one lookup, call next() or reject. Deliberately not a formal
 * x402 V2 extension -- that needs a published schema and an identifier this
 * project has no standing to mint. See README.
 */

import {
  createPublicClient,
  http,
  type Address,
  type Hex,
  type PublicClient,
} from "viem";

/** The slice of Attestation.sol this gate reads. */
export const ATTESTATION_ABI = [
  {
    type: "function",
    name: "get",
    stateMutability: "view",
    inputs: [{ name: "attestationId", type: "bytes32" }],
    outputs: [
      {
        type: "tuple",
        components: [
          { name: "operator", type: "address" },
          { name: "decisionHash", type: "bytes32" },
          { name: "shapHash", type: "bytes32" },
          { name: "confidence", type: "uint256" },
          { name: "margin", type: "int256" },
          { name: "modelVersion", type: "bytes32" },
          { name: "timestamp", type: "uint64" },
          { name: "proofVerified", type: "bool" },
        ],
      },
    ],
  },
  {
    type: "function",
    name: "exists",
    stateMutability: "view",
    inputs: [{ name: "attestationId", type: "bytes32" }],
    outputs: [{ type: "bool" }],
  },
] as const;

export interface AttestationRecord {
  operator: Address;
  decisionHash: Hex;
  shapHash: Hex;
  confidence: bigint;
  margin: bigint;
  modelVersion: Hex;
  timestamp: bigint;
  proofVerified: boolean;
}

/** Machine-readable reasons a request was refused. */
export type GateFailure =
  | "attestation_missing" // no id on the request at all
  | "attestation_malformed" // present but not a bytes32
  | "attestation_unknown" // well-formed, not on chain
  | "attestation_unverified" // on chain, but the zk verifier rejected it
  | "attestation_stale" // older than maxAgeSeconds
  | "attestation_wrong_operator" // not attested by an allowed operator
  | "attestation_lookup_failed"; // RPC failure -- NOT the client's fault

export interface GateOptions {
  /** Deployed Attestation.sol address. */
  attestationAddress: Address;
  /** RPC endpoint, or a preconfigured viem client (`client` wins). */
  rpcUrl?: string;
  client?: PublicClient;
  /**
   * Header carrying the attestation id. Default `x-brier-attestation`.
   * Deliberately its own header rather than a field inside the x402 payment
   * payload: Attack III of arXiv:2605.11781 is proxy-level header confusion,
   * and mixing this into the payment header widens that surface.
   */
  header?: string;
  /** Also accept `?attestationId=`. Default false -- query strings leak into logs and caches. */
  allowQueryParam?: boolean;
  /**
   * Reject attestations older than this many seconds. Default 0 (disabled).
   * Narrows the replay window from unbounded to bounded. It does NOT make
   * replay impossible -- see limitation 3 in the file header.
   */
  maxAgeSeconds?: number;
  /** If set, only these operators' attestations pass. */
  allowedOperators?: Address[];
  /** Minimum attested confidence, WAD (1e18 = 100%). Default 0. */
  minConfidence?: bigint;
  /**
   * Fail open if the RPC lookup itself fails. Default false.
   * @remarks Defaults closed on purpose. Failing open converts an RPC outage
   * into a free bypass of the gate, and an attacker who can degrade your RPC
   * gets to choose when the gate stops applying. Failing closed converts the
   * same outage into downtime, which is visible and does not silently sell
   * unattested decisions.
   */
  failOpen?: boolean;
}

export interface GateResult {
  ok: boolean;
  failure?: GateFailure;
  detail?: string;
  record?: AttestationRecord;
}

const BYTES32 = /^0x[0-9a-fA-F]{64}$/;

/**
 * The gate's decision, with no HTTP framework in sight.
 *
 * Kept framework-free so the same logic serves Express, Hono, and the tests
 * without a copy per adapter -- a gate that behaves differently depending on
 * which wrapper called it would be worse than no gate.
 */
export async function checkAttestation(
  attestationId: string | undefined,
  opts: GateOptions,
): Promise<GateResult> {
  if (!attestationId) {
    return { ok: false, failure: "attestation_missing", detail: "no attestation id on the request" };
  }
  if (!BYTES32.test(attestationId)) {
    return {
      ok: false,
      failure: "attestation_malformed",
      detail: "attestation id must be a 0x-prefixed 32-byte hex string",
    };
  }

  const client =
    opts.client ??
    createPublicClient({ transport: http(opts.rpcUrl ?? "http://127.0.0.1:8545") });

  let record: AttestationRecord;
  try {
    record = (await client.readContract({
      address: opts.attestationAddress,
      abi: ATTESTATION_ABI,
      functionName: "get",
      args: [attestationId as Hex],
    })) as unknown as AttestationRecord;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    // Attestation.get reverts UnknownAttestation for an id it has never seen.
    // That is a client error (they sent a bad id); anything else is ours.
    if (/UnknownAttestation|reverted/i.test(message)) {
      return {
        ok: false,
        failure: "attestation_unknown",
        detail: "no attestation with that id exists on chain",
      };
    }
    if (opts.failOpen) {
      return { ok: true, detail: `lookup failed, failing open: ${message}` };
    }
    return { ok: false, failure: "attestation_lookup_failed", detail: message };
  }

  // Defence in depth, and worth being precise about rather than overselling.
  // Attestation.attest REVERTS when the verifier rejects a proof
  // (Attestation.sol:76), so a record with proofVerified == false cannot be
  // created through the current write path at all -- the contract's own
  // comment at Attestation.sol:57 says as much, and the integration test
  // proves it on a live chain. In practice a rejected proof therefore shows up
  // here as `attestation_unknown`, not `attestation_unverified`.
  //
  // The check stays because it is cheap and because the guarantee lives in a
  // contract this middleware does not control: a future write path, a migration
  // that backfills records, or a different Attestation deployment could all
  // produce an unverified record. Gating on a field the chain currently
  // guarantees is a bet worth keeping; assuming it will always hold is not.
  if (!record.proofVerified) {
    return {
      ok: false,
      failure: "attestation_unverified",
      detail: "the on-chain verifier rejected this attestation's proof",
      record,
    };
  }

  if (opts.maxAgeSeconds && opts.maxAgeSeconds > 0) {
    // Age is measured in CHAIN time, against the latest block's timestamp --
    // not against the server's wall clock. record.timestamp is set by
    // block.timestamp, so comparing it to Date.now() mixes two clocks that are
    // free to drift apart. On a chain whose blocks lag, wall-clock comparison
    // would age every attestation by the lag and reject fresh ones; on a chain
    // ahead of the server it would under-age them. Same clock on both sides.
    let now: number;
    try {
      const block = await client.getBlock();
      now = Number(block.timestamp);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (opts.failOpen) {
        return { ok: true, record, detail: `block lookup failed, failing open: ${message}` };
      }
      return { ok: false, failure: "attestation_lookup_failed", detail: message, record };
    }

    const age = now - Number(record.timestamp);
    if (age > opts.maxAgeSeconds) {
      return {
        ok: false,
        failure: "attestation_stale",
        detail: `attestation is ${age}s old in chain time, limit ${opts.maxAgeSeconds}s`,
        record,
      };
    }
  }

  if (opts.allowedOperators?.length) {
    const allowed = opts.allowedOperators.map((a) => a.toLowerCase());
    if (!allowed.includes(record.operator.toLowerCase())) {
      return {
        ok: false,
        failure: "attestation_wrong_operator",
        detail: `operator ${record.operator} is not in the allow-list`,
        record,
      };
    }
  }

  if (opts.minConfidence !== undefined && record.confidence < opts.minConfidence) {
    // Note this is a floor on the ASSERTED confidence, which is not a quality
    // bar: a high number here is a bigger slash if the decision is overturned,
    // not evidence the decision is right. Sellers should think twice before
    // setting it -- it rewards claiming confidence.
    return {
      ok: false,
      failure: "attestation_unverified",
      detail: `attested confidence ${record.confidence} below required ${opts.minConfidence}`,
      record,
    };
  }

  return { ok: true, record };
}

/** The 402 body returned when the gate refuses. */
export function gateErrorBody(result: GateResult) {
  return {
    // Distinct from a plain x402 "payment required": the client's payment may
    // be perfectly good. What is missing is the seller-side attestation, and a
    // client that cannot tell these apart will retry payment forever.
    error: "brier_attestation_required",
    reason: result.failure,
    detail: result.detail,
    documentation: "https://github.com/Sagexd08/Brier",
  };
}

/**
 * Express middleware.
 *
 * Sits BEFORE the x402 payment middleware, so an unattested request never
 * reaches settlement. Ordering is the whole point: gating after payment means
 * the buyer has already paid for a decision the seller never committed to.
 */
export function requireBrierAttestation(opts: GateOptions) {
  const headerName = (opts.header ?? "x-brier-attestation").toLowerCase();

  return async function brierGate(req: any, res: any, next: any) {
    const fromHeader = req.headers?.[headerName];
    const fromQuery = opts.allowQueryParam ? req.query?.attestationId : undefined;
    const id = (Array.isArray(fromHeader) ? fromHeader[0] : fromHeader) ?? fromQuery;

    const result = await checkAttestation(id, opts);

    if (!result.ok) {
      // 402 rather than 403: the request is not forbidden, it is incomplete in
      // the same class of way a missing payment is, and x402 clients already
      // know how to read a 402 body and retry.
      res.status(402);
      // Attack III (arXiv:2605.11781) is intermediaries caching payment-gated
      // responses. A cached 402 would pin a client to a stale refusal.
      res.setHeader("Cache-Control", "no-store");
      return res.json(gateErrorBody(result));
    }

    req.brierAttestation = result.record;
    return next();
  };
}

/** Hono middleware. Same decision, different wrapper. */
export function brierAttestationHono(opts: GateOptions) {
  const headerName = (opts.header ?? "x-brier-attestation").toLowerCase();

  return async function brierGateHono(c: any, next: any) {
    const id =
      c.req.header(headerName) ??
      (opts.allowQueryParam ? c.req.query("attestationId") : undefined);

    const result = await checkAttestation(id, opts);

    if (!result.ok) {
      c.header("Cache-Control", "no-store");
      return c.json(gateErrorBody(result), 402);
    }

    c.set("brierAttestation", result.record);
    await next();
  };
}
