# Phase 1 — account model design

Written before the program code. EVM storage and Solana accounts are different
enough that a struct-by-struct transliteration produces either a broken program
or a subtly insecure one; this document fixes the mapping first.

## Why a 1:1 port does not work

| EVM | Solana | Consequence |
|---|---|---|
| `mapping(bytes32 => Record)` grows without bound in one contract's storage | every record is a separate **account** with a rent-paying owner and a fixed size | sizes must be declared up front; the payer must be explicit |
| `msg.sender` is authenticated by the runtime | any account can be *passed in*; authentication requires an explicit **signer check** | missing signer check is the #1 Anchor vulnerability class |
| a contract implicitly owns its storage | a program must verify it **owns** each account it reads | missing owner check lets an attacker substitute a look-alike account |
| `keccak(abi.encode(...))` ids are just keys | PDAs are addresses **derived from seeds**; seed collisions merge distinct records | seeds must be injective |
| `address(this).balance` holds pooled ETH | lamports live in accounts, and rent-exemption interacts with balances | stake accounting must not be confused with the rent-exempt minimum |

## PDA layout

Every seed set below is prefixed with a distinct literal so that two record
types can never derive the same address, and every variable-length component is
fixed-width (`Pubkey` = 32 B, `[u8; 32]` hashes) so that no two distinct inputs
can concatenate to the same seed byte string.

| Account | Seeds | Notes |
|---|---|---|
| `Config` | `[b"config"]` | singleton: admin, committee, threshold, unbonding period, slash cap |
| `Attestation` | `[b"attestation", operator (32 B), decision_hash (32 B)]` | one per (operator, decision) |
| `StakeAccount` | `[b"stake", operator (32 B)]` | one per operator; holds the bonded lamports |
| `Dispute` | `[b"dispute", attestation PDA (32 B)]` | one per attestation, so double-disputing is impossible by construction |
| `VoteRecord` | `[b"vote", dispute PDA (32 B), resolver (32 B)]` | existence *is* the "has voted" flag — no bitmap to desynchronise |

### Seed injectivity

The EVM version derived ids with `keccak256(abi.encode(...))`, where ABI
encoding is self-delimiting. PDA seeds are raw byte slices concatenated by the
runtime, so a variable-length seed would allow
`("ab", "c")` and `("a", "bc")` to collide.

Every seed component here is either a fixed literal or a fixed 32-byte value.
No component is user-controlled and variable-length. `test_pda_seed_collision_resistance`
asserts this rather than leaving it to inspection.

### One dispute per attestation, enforced structurally

On EVM this needed a `mapping(bytes32 => bool) disputed` plus a check. On Solana
the `Dispute` PDA is derived from the attestation, and `init` fails if the
account already exists — so a second dispute is impossible without a check. This
is a case where the account model is *stronger* than the EVM equivalent, and it
is worth stating because most differences run the other way.

## Guarantees that must be re-established, not inherited

These are the EVM guarantees. Each needs a Solana test; none transfers:

1. Only the operator can attest under their own key → **signer check**.
2. Confidence is in `[0, WAD]` → range check, plus Rust checked arithmetic.
3. One dispute per attestation → PDA uniqueness (above).
4. Withdrawal blocked while a dispute is open → `open_dispute_count` on the
   stake account.
5. Withdrawal blocked before the unbonding clock matures → `Clock` sysvar.
6. Resolution requires N of M → `VoteRecord` PDAs counted against `threshold`.
7. Slash is `stake * (c - o)^2`, capped, no overflow → fixed-point u128 math.
8. Slashed lamports reach the claimant → explicit lamport transfer.

## Arithmetic

Solidity 0.8 reverts on overflow by default. Rust **wraps in release mode**
unless `overflow-checks` is enabled or checked methods are used. The slash path
therefore uses `checked_*` explicitly at every site, and `overflow-checks = true`
is set in the release profile as a second line of defence. This is checked in
Phase 4, and is a real difference in default safety between the two languages.

## What is NOT in the account model

- No equivalent of the EVM `previewSlash` view is strictly needed (clients can
  compute it), but one is provided for parity with the demo.
- Rent: every PDA is created rent-exempt at init, paid by the initialising
  party. Rent-exempt lamports are **not** part of the stake accounting; the
  stake account tracks `bonded` explicitly instead of inferring it from
  `lamports()`, which would otherwise silently include the rent minimum.
