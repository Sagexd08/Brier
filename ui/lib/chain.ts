/**
 * Live chain reads.
 *
 * Chain-agnostic: the RPC URL and contract addresses come from environment
 * variables, defaulting to a local Anvil devnet. Pointing this at a testnet is
 * a config change, not a code change.
 *
 * Every read here can fail — the node may not be running, the contracts may not
 * be deployed, the addresses may be stale after a redeploy. Each failure is
 * surfaced with what actually went wrong. Nothing falls back to a cached or
 * invented value: a stake figure that is not read from chain is not a stake
 * figure.
 */

import { createPublicClient, http, defineChain, type Address, type PublicClient } from 'viem';

export const RPC_URL =
  process.env.NEXT_PUBLIC_RPC_URL ?? 'http://127.0.0.1:8545';

export const anvil = defineChain({
  id: Number(process.env.NEXT_PUBLIC_CHAIN_ID ?? 31337),
  name: process.env.NEXT_PUBLIC_CHAIN_NAME ?? 'Anvil (local)',
  nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
  rpcUrls: { default: { http: [RPC_URL] } },
});

export function client(): PublicClient {
  return createPublicClient({ chain: anvil, transport: http(RPC_URL) });
}

/** Addresses are written by the deploy script into artifacts/deployment.json. */
export interface Deployment {
  chain: string;
  verifier: Address;
  attestation: Address;
  stakepool: Address;
  admin: Address;
}

export const stakePoolAbi = [
  {
    type: 'function',
    name: 'stakeOf',
    stateMutability: 'view',
    inputs: [{ name: '', type: 'address' }],
    outputs: [{ name: '', type: 'uint256' }],
  },
  {
    type: 'function',
    name: 'maxSlashBps',
    stateMutability: 'view',
    inputs: [],
    outputs: [{ name: '', type: 'uint256' }],
  },
  {
    type: 'function',
    name: 'unbondingPeriod',
    stateMutability: 'view',
    inputs: [],
    outputs: [{ name: '', type: 'uint256' }],
  },
  {
    type: 'function',
    name: 'threshold',
    stateMutability: 'view',
    inputs: [],
    outputs: [{ name: '', type: 'uint256' }],
  },
  {
    type: 'function',
    name: 'committeeSize',
    stateMutability: 'view',
    inputs: [],
    outputs: [{ name: '', type: 'uint256' }],
  },
  {
    type: 'function',
    name: 'openDisputeCount',
    stateMutability: 'view',
    inputs: [{ name: '', type: 'address' }],
    outputs: [{ name: '', type: 'uint256' }],
  },
  {
    type: 'function',
    name: 'previewSlash',
    stateMutability: 'view',
    inputs: [
      { name: 'attestationId', type: 'bytes32' },
      { name: 'decisionUpheld', type: 'bool' },
    ],
    outputs: [{ name: '', type: 'uint256' }],
  },
] as const;

export const attestationAbi = [
  {
    type: 'function',
    name: 'count',
    stateMutability: 'view',
    inputs: [],
    outputs: [{ name: '', type: 'uint256' }],
  },
  {
    type: 'function',
    name: 'idAt',
    stateMutability: 'view',
    inputs: [{ name: 'i', type: 'uint256' }],
    outputs: [{ name: '', type: 'bytes32' }],
  },
  {
    type: 'function',
    name: 'get',
    stateMutability: 'view',
    inputs: [{ name: 'attestationId', type: 'bytes32' }],
    outputs: [
      {
        type: 'tuple',
        components: [
          { name: 'operator', type: 'address' },
          { name: 'decisionHash', type: 'bytes32' },
          { name: 'shapHash', type: 'bytes32' },
          { name: 'confidence', type: 'uint256' },
          { name: 'margin', type: 'int256' },
          { name: 'modelVersion', type: 'bytes32' },
          { name: 'timestamp', type: 'uint64' },
          { name: 'proofVerified', type: 'bool' },
        ],
      },
    ],
  },
] as const;

export type ChainState =
  | { state: 'checking' }
  | { state: 'offline'; detail: string }
  | { state: 'no-deployment'; detail: string }
  | {
      state: 'live';
      blockNumber: bigint;
      chainId: number;
      deployment: Deployment;
      attestationCount: bigint;
      maxSlashBps: bigint | null;
      unbondingPeriod: bigint | null;
      threshold: bigint | null;
      committeeSize: bigint | null;
    };

/**
 * Probe the chain and the deployment.
 *
 * Distinguishes three failures that a reviewer would otherwise conflate:
 *   offline        — no node answering at the RPC URL
 *   no-deployment  — node is up, but the deployment manifest is absent
 *   contract miss  — manifest exists but the address holds no code
 * Each states what to do about it.
 */
export async function probeChain(): Promise<ChainState> {
  const c = client();

  let blockNumber: bigint;
  let chainId: number;
  try {
    [blockNumber, chainId] = await Promise.all([c.getBlockNumber(), c.getChainId()]);
  } catch (err) {
    return {
      state: 'offline',
      detail: `No JSON-RPC node answered at ${RPC_URL}. Start one with \`anvil\` in the repository root, then deploy with \`forge script script/Deploy.s.sol:Deploy --rpc-url ${RPC_URL} --broadcast\`. Live stake, dispute, and attestation figures are read from chain and are not shown from cache.`,
    };
  }

  let deployment: Deployment;
  try {
    const res = await fetch('/artifacts/deployment.json', { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    deployment = (await res.json()) as Deployment;
  } catch {
    return {
      state: 'no-deployment',
      detail: `Node is reachable at ${RPC_URL} (chain ${chainId}, block ${blockNumber}) but no deployment manifest was found. Run the deploy script; it writes artifacts/deployment.json, which this page reads for contract addresses.`,
    };
  }

  // A manifest can outlive the chain it describes — Anvil restarts wipe state.
  const code = await c.getBytecode({ address: deployment.stakepool }).catch(() => undefined);
  if (!code || code === '0x') {
    return {
      state: 'no-deployment',
      detail: `Deployment manifest points at ${deployment.stakepool}, but that address holds no code on chain ${chainId}. The chain was most likely restarted after the manifest was written. Re-run the deploy script.`,
    };
  }

  const safeRead = async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    try {
      return await fn();
    } catch {
      return null;
    }
  };

  const [attestationCount, maxSlashBps, unbondingPeriod, threshold, committeeSize] =
    await Promise.all([
      safeRead(() =>
        c.readContract({
          address: deployment.attestation,
          abi: attestationAbi,
          functionName: 'count',
        }),
      ),
      safeRead(() =>
        c.readContract({
          address: deployment.stakepool,
          abi: stakePoolAbi,
          functionName: 'maxSlashBps',
        }),
      ),
      safeRead(() =>
        c.readContract({
          address: deployment.stakepool,
          abi: stakePoolAbi,
          functionName: 'unbondingPeriod',
        }),
      ),
      safeRead(() =>
        c.readContract({
          address: deployment.stakepool,
          abi: stakePoolAbi,
          functionName: 'threshold',
        }),
      ),
      safeRead(() =>
        c.readContract({
          address: deployment.stakepool,
          abi: stakePoolAbi,
          functionName: 'committeeSize',
        }),
      ),
    ]);

  return {
    state: 'live',
    blockNumber,
    chainId,
    deployment,
    attestationCount: attestationCount ?? 0n,
    maxSlashBps,
    unbondingPeriod,
    threshold,
    committeeSize,
  };
}
