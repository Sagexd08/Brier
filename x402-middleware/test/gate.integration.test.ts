/**
 * Integration tests for the Brier attestation gate.
 *
 * These run against a REAL Anvil chain with the REAL Attestation.sol deployed,
 * and every gate decision comes from an actual eth_call. Nothing here is
 * mocked: a mocked chain would test that the test's own stub returns what the
 * test told it to, which is not evidence about the contract.
 *
 * Anvil and the fixture deployment are started by the suite itself, so
 * `npm test` is the whole command. If `anvil` or `forge` are missing the suite
 * fails loudly rather than skipping -- a silently skipped integration test is
 * indistinguishable from a passing one on a dashboard.
 */

import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createPublicClient, http, type Address, type PublicClient } from "viem";

import { checkAttestation, gateErrorBody } from "../src/index.js";

const RPC_URL = "http://127.0.0.1:8546"; // not 8545, to avoid a dev chain
const CONTRACTS_DIR = new URL("../../contracts", import.meta.url).pathname.replace(
  /^\/([A-Za-z]:)/,
  "$1",
);

let anvil: ChildProcess;
let client: PublicClient;

let attestationAddress: Address;
let operator: Address;
let verifiedId: string;
let rejectedId: string; // never reached the chain: attest() reverted

const UNKNOWN_ID = "0x" + "ab".repeat(32);

function waitForRpc(timeoutMs = 30_000): Promise<void> {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        await fetch(RPC_URL, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_chainId", params: [] }),
        });
        resolve();
      } catch {
        if (Date.now() - started > timeoutMs) reject(new Error("anvil did not come up"));
        else setTimeout(tick, 250);
      }
    };
    tick();
  });
}

beforeAll(async () => {
  anvil = spawn("anvil", ["--port", "8546", "--silent"], { stdio: "ignore", shell: true });
  await waitForRpc();

  const deploy = spawnSync(
    "forge",
    [
      "script",
      "script/DeployMiddlewareFixture.s.sol:DeployMiddlewareFixture",
      "--rpc-url",
      RPC_URL,
      "--broadcast",
    ],
    { cwd: CONTRACTS_DIR, encoding: "utf-8", shell: true },
  );

  if (deploy.status !== 0) {
    throw new Error(`fixture deployment failed:\n${deploy.stdout}\n${deploy.stderr}`);
  }

  const line = deploy.stdout.split("\n").find((l) => l.trim().startsWith('{"attestation"'));
  if (!line) throw new Error(`no FIXTURE_JSON in deploy output:\n${deploy.stdout}`);

  const fixture = JSON.parse(line.trim());
  attestationAddress = fixture.attestation;
  operator = fixture.operator;
  verifiedId = fixture.verifiedId;
  rejectedId = fixture.rejectedId;

  client = createPublicClient({ transport: http(RPC_URL) }) as PublicClient;
}, 90_000);

afterAll(() => {
  anvil?.kill();
});

const opts = () => ({ attestationAddress, client });

describe("the three cases the DoD names", () => {
  it("(a) a valid attestation passes", async () => {
    const result = await checkAttestation(verifiedId, opts());
    expect(result.ok).toBe(true);
    expect(result.record?.proofVerified).toBe(true);
    expect(result.record?.operator.toLowerCase()).toBe(operator.toLowerCase());
    expect(result.record?.confidence).toBe(870000000000000000n);
  });

  it("(b) a missing attestation is refused with the distinct error body", async () => {
    const result = await checkAttestation(undefined, opts());
    expect(result.ok).toBe(false);
    expect(result.failure).toBe("attestation_missing");

    const body = gateErrorBody(result);
    // Distinct from a plain x402 "payment required" -- a client that cannot
    // tell these apart will retry payment forever against a seller that never
    // attested anything.
    expect(body.error).toBe("brier_attestation_required");
    expect(body.error).not.toBe("payment_required");
    expect(body.reason).toBe("attestation_missing");
  });

  it("(c) an attestation whose proof failed verification is refused", async () => {
    // The important finding, proved on a live chain rather than read off a
    // comment: Attestation.attest REVERTS when the verifier rejects, so this
    // id was never written. The gate refuses it as UNKNOWN, and the guarantee
    // is stronger than "we check a boolean" -- an unverified attestation
    // cannot exist through this write path at all.
    const exists = await client.readContract({
      address: attestationAddress,
      abi: [
        {
          type: "function",
          name: "exists",
          stateMutability: "view",
          inputs: [{ name: "attestationId", type: "bytes32" }],
          outputs: [{ type: "bool" }],
        },
      ] as const,
      functionName: "exists",
      args: [rejectedId as `0x${string}`],
    });
    expect(exists).toBe(false);

    const result = await checkAttestation(rejectedId, opts());
    expect(result.ok).toBe(false);
    expect(result.failure).toBe("attestation_unknown");
    expect(gateErrorBody(result).error).toBe("brier_attestation_required");
  });
});

describe("the rest of the gate", () => {
  it("refuses an id that is well-formed but not on chain", async () => {
    const result = await checkAttestation(UNKNOWN_ID, opts());
    expect(result.ok).toBe(false);
    expect(result.failure).toBe("attestation_unknown");
  });

  it("refuses a malformed id without touching the chain", async () => {
    const result = await checkAttestation("not-a-bytes32", {
      attestationAddress,
      // No client: if this reached the RPC it would throw instead of returning.
      rpcUrl: "http://127.0.0.1:1",
    });
    expect(result.ok).toBe(false);
    expect(result.failure).toBe("attestation_malformed");
  });

  it("enforces an operator allow-list", async () => {
    const stranger = "0x000000000000000000000000000000000000dEaD" as Address;
    const result = await checkAttestation(verifiedId, {
      ...opts(),
      allowedOperators: [stranger],
    });
    expect(result.ok).toBe(false);
    expect(result.failure).toBe("attestation_wrong_operator");

    const allowed = await checkAttestation(verifiedId, {
      ...opts(),
      allowedOperators: [operator],
    });
    expect(allowed.ok).toBe(true);
  });

  it("enforces a minimum attested confidence", async () => {
    const result = await checkAttestation(verifiedId, {
      ...opts(),
      minConfidence: 950000000000000000n, // 0.95 > the attested 0.87
    });
    expect(result.ok).toBe(false);
  });

  it("rejects a stale attestation once it is older than maxAgeSeconds", async () => {
    // Advance the chain well past the bound rather than sleeping, so the test
    // asserts on the gate's arithmetic instead of on wall-clock timing.
    await fetch(RPC_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "evm_increaseTime",
        params: [3600],
      }),
    });
    await fetch(RPC_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 2, method: "evm_mine", params: [] }),
    });

    const fresh = await checkAttestation(verifiedId, { ...opts(), maxAgeSeconds: 86_400 });
    expect(fresh.ok).toBe(true);

    const stale = await checkAttestation(verifiedId, { ...opts(), maxAgeSeconds: 60 });
    expect(stale.ok).toBe(false);
    expect(stale.failure).toBe("attestation_stale");
  });

  it("fails CLOSED when the RPC is unreachable", async () => {
    // The security-relevant default. Failing open would let anyone who can
    // degrade the seller's RPC turn the gate off.
    const result = await checkAttestation(verifiedId, {
      attestationAddress,
      rpcUrl: "http://127.0.0.1:1",
    });
    expect(result.ok).toBe(false);
  });

  it("fails open only when explicitly asked to", async () => {
    const result = await checkAttestation(verifiedId, {
      attestationAddress,
      rpcUrl: "http://127.0.0.1:1",
      failOpen: true,
    });
    expect(result.ok).toBe(true);
    expect(result.detail).toMatch(/failing open/);
  });

  it("does not prevent replay of the same attestation (Attack II, documented)", async () => {
    // Pinning a KNOWN LIMITATION rather than a feature. arXiv:2605.11781
    // Attack II is replay across the HTTP-chain boundary; this gate does not
    // claim a payment per attestation, so one id passes unlimited times. If a
    // future change adds claim-once semantics this test SHOULD fail and be
    // rewritten -- that is the signal it exists to give.
    const a = await checkAttestation(verifiedId, opts());
    const b = await checkAttestation(verifiedId, opts());
    const c = await checkAttestation(verifiedId, opts());
    expect([a.ok, b.ok, c.ok]).toEqual([true, true, true]);
  });
});
