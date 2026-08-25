# Succinct Prover Network — manual setup

> **Everything in this document is performed by you, by hand.**
> No script in this repository generates a keypair, requests tokens, bridges,
> deposits, or signs a funding transaction. Those are custody and financial
> actions and are deliberately out of scope for automation here.

The repo defaults to `mock` proving, which is free and needs none of this. Read
on only if you specifically want network-mode proving — for example to produce
the Phase 2 proving-cost measurements that local hardware cannot.

## Why you might need this

`solana/docs/PHASE0_PROVING_STACK.md` records that this machine is below
Succinct's published Groth16 proving floor (16+ cores / 16 GB RAM; GPU proving
is Linux-x86_64 only). Local proving is therefore unavailable here, which is why
SP1 proving time and the Phase 2 parameter sweep are currently marked
**NOT MEASURED**. The prover network is one way to close that gap; a machine
meeting the floor is the other.

## Cost, stated plainly

**Network-mode proving spends real $PROVE per proof request.** A Phase 2 sweep
is one request per parameter count, plus re-runs. This is the entire reason
`mock`/`local` remains the default in every test, CI job, and `make` target:
nothing in this repo may spend your funds without you opting in for that run.

## Manual steps (you do these)

### 1. Create a requester keypair

Any EVM keypair works. Two common routes:

```bash
# Foundry — prints an address and a private key
cast wallet new
```

or create a fresh account in MetaMask and export its private key.

**Use a dedicated key for this.** Not an account holding other assets, and not
one you use anywhere else.

### 2. Fund it with $PROVE

$PROVE is an ERC-20 on Ethereum mainnet. Acquire it and send it to the address
from step 1. This step involves real money and is entirely yours — no part of
this repo assists with, automates, or observes it.

### 3. Deposit to the prover network

Open the Succinct Explorer, connect the funded wallet, and deposit $PROVE to
your requester account. Consult Succinct's current documentation for the exact
flow — it changes, and this file is not a substitute for the vendor's docs:

- <https://docs.succinct.xyz/>
- <https://explorer.succinct.xyz/>

### 4. Put the key in your local environment

```bash
cp .env.example .env
# then edit .env and set:
#   SP1_PROVER_MODE=network
#   NETWORK_PRIVATE_KEY=<your key>
```

`.env` is gitignored at every directory depth, and `.env.example` is committed
with the key field **empty**. Verify before you start:

```bash
git check-ignore -v .env      # must print a .gitignore rule
git status --short            # .env must NOT appear
```

For a single run, exporting in the shell avoids writing the key to disk at all:

```bash
SP1_PROVER_MODE=network NETWORK_PRIVATE_KEY=0x... cargo run --release -- ...
```

## What the code does with the key

`solana/sp1-calibration/script/src/prover.rs` reads `NETWORK_PRIVATE_KEY` from
the process environment and nowhere else. It is never written to a file, never
logged, never placed in an error message, and never returned to a caller —
there is deliberately no accessor that hands the value back, because anything
that returns a secret eventually ends up in a log line.

`secret_is_never_rendered` asserts this with a canary value: it sets a
recognisable fake key, renders every mode and error type, and fails if the
canary or any fragment of it appears. `MissingNetworkKey` carries no payload —
not the value, not its length, not a prefix.

## Safety rails already in place

| Rail | Where |
|---|---|
| Default is `mock`; unset means `mock` | `ProverMode::from_env` |
| A typo (`netwrok`) is an **error**, not a silent mock run | `unknown_mode_is_an_error` |
| `local`/`mock` never read the key | `local_mode_never_requires_network_key` |
| Network mode without a key **fails closed** | `network_mode_without_key_fails_closed` |
| Free modes never write the cost log | `cost_logging_is_a_noop_for_free_modes` |
| No CI job or `make research-eval` target selects `network` | `make bench-network` only, run by hand |

## Cost tracking

In network mode each request appends one JSON line to `SP1_COST_LOG`
(default `artifacts/prover/network_costs.jsonl`): timestamp, program identifier,
parameter count, cycle count, reported cost, duration, success. Where the SDK
does not report a cost, the field is `null` — recorded as unknown rather than
estimated. This is the dataset Phase 2's proving-cost table is built from, which
is why it is collected from the first request rather than reconstructed later.
