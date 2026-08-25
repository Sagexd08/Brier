# Brier UI

Next.js app reading **real** data only: committed JSON artifacts from the
repository's `artifacts/` directory, and live EVM state over RPC. No database,
no localStorage, no mock data — including in loading and error states.

## Run

```bash
# 1. chain + contracts (from the repository root)
anvil &
PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 \
  forge script script/Deploy.s.sol:Deploy --rpc-url http://127.0.0.1:8545 --broadcast

# 2. refresh the artifacts this app serves
cp ../artifacts/calibration/*.json ../artifacts/shap/*.json ../artifacts/zk/*.json \
   ../artifacts/deployment.json public/artifacts/

# 3. the app
npm install && npm run dev     # http://localhost:3100
```

Runs without a chain: the static measurement sections work offline, and the
live sections state that no node is reachable rather than showing stale or
invented values.

## Configuration

| Variable | Default |
|---|---|
| `NEXT_PUBLIC_RPC_URL` | `http://127.0.0.1:8545` |
| `NEXT_PUBLIC_CHAIN_ID` | `31337` |
| `NEXT_PUBLIC_CHAIN_NAME` | `Anvil (local)` |

Pointing at a testnet is a config change, not a code change.

## Design

`DESIGN.md` records the token system, its derivation, and both critique passes.
