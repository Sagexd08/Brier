# Host-side check of the on-chain Brier math

`brier_math_host_check.rs` is `src/brier_math.rs` with the Anchor glue shimmed
away, so the arithmetic and its 15 tests can be run **without** the Anchor or
Solana toolchains installed:

```bash
cd solana/programs/brier/tests && cargo test   # (as a standalone crate)
```

This is a convenience for CI environments lacking the Solana toolchain, not a
substitute for `anchor test`. It covers the pure arithmetic only — every
account-model guarantee (signer checks, PDA derivation, unbonding, N-of-M) is
tested by the Anchor/Trident suites, which do require the full toolchain.

All 15 assertions match the EVM `BrierMath.t.sol` known-answer cases exactly
(98.01% / 30.25% / 0.01% of stake), which is the evidence that the two chains
implement the same mechanism rather than two similar ones.
