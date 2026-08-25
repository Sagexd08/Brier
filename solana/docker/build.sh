#!/usr/bin/env sh
# Build the Brier Anchor program inside the pinned container.
#
# Why the extra steps: the solanafoundation/anchor:v0.31.1 image ships
# platform-tools v1.43, whose bundled cargo is 1.79.0 and predates edition2024.
# Several transitive dependencies (crypto-common, zeroize, block-buffer,
# toml_datetime, ...) have since adopted edition2024, so a plain `anchor build`
# in that image fails with:
#     feature `edition2024` is required ... not stabilized in this version of
#     Cargo (1.79.0)
#
# Chasing per-crate pins is a treadmill. Installing the current Agave CLI brings
# platform-tools v1.54 (cargo >= 1.84), which supports edition2024, and removing
# the stale v1.43 cache forces cargo-build-sbf to use it.
set -e
export PATH="/root/.local/share/solana/install/active_release/bin:$PATH"
rm -rf /root/.cache/solana/v1.43
cd /work/programs/brier
cargo-build-sbf "$@"
echo "artifact:"
ls -la /work/target/deploy/*.so
