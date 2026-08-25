# brier-calibration-core

The fixed-point calibration head proved inside SP1, split out of the guest
binary so it is testable without an SP1 toolchain.

`cargo test` — 15 tests. The load-bearing one is
`matches_pytorch_head_on_real_margins`, which checks this Rust implementation
against the actual trained PyTorch head from the EVM build
(`artifacts/calibration/temperature_head.pt`, T = 3.01210355758667) on real
margins from the test split. Fixture: `crosscheck.json`.

**Quantisation error is measured here, for this implementation.** EZKL reported
~4.2e-4 for the Halo2 circuit; that number belongs to a different proving system
and is not inherited. `quantisation_error_is_bounded_and_measured_here` asserts
this implementation's own bound (< 3 ulps at SCALE = 1e6).
