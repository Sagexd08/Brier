// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title BrierMath
/// @notice Fixed-point Brier-score slashing arithmetic.
///
/// The Brier score is a strictly proper scoring rule: an operator minimises
/// expected loss exactly when the reported confidence equals its true
/// subjective probability. That is the whole point of this project --
/// a flat penalty gives no incentive to report honest uncertainty.
///
///     slash = stake * (confidence - outcome)^2, capped
///
/// All probabilities are WAD fixed-point: 1e18 == 1.0.
library BrierMath {
    /// @dev 1.0 in fixed point.
    uint256 internal constant WAD = 1e18;

    error ConfidenceOutOfRange(uint256 confidence);
    error CapOutOfRange(uint256 capBps);

    uint256 internal constant BPS_DENOMINATOR = 10_000;

    /// @notice Squared error between a confidence and a binary outcome, in WAD.
    /// @param confidence Reported probability that the decision was correct, WAD.
    /// @param outcomeCorrect True if the decision was upheld.
    /// @return WAD-scaled value in [0, 1e18].
    ///
    /// Precision note: `diff` is at most 1e18, so `diff * diff` is at most
    /// 1e36, which is ~2^120 -- far below the 2^256 limit. No intermediate
    /// overflow is possible, and no unchecked block is used.
    function squaredError(uint256 confidence, bool outcomeCorrect)
        internal
        pure
        returns (uint256)
    {
        if (confidence > WAD) revert ConfidenceOutOfRange(confidence);
        uint256 outcome = outcomeCorrect ? WAD : 0;
        uint256 diff = confidence > outcome ? confidence - outcome : outcome - confidence;
        // diff <= 1e18, so diff*diff <= 1e36. Dividing by WAD returns to WAD scale.
        return (diff * diff) / WAD;
    }

    /// @notice Slash amount for a decision.
    /// @param stake Collateral at risk, in wei.
    /// @param confidence Reported confidence the decision was correct, WAD.
    /// @param outcomeCorrect Dispute outcome: true = decision upheld.
    /// @param maxSlashBps Cap on the slash, in basis points of `stake`.
    ///
    /// Overflow analysis: `stake * sqErr` where sqErr <= 1e18. For this to
    /// exceed 2^256 the stake would have to exceed ~1.15e59 wei, i.e. about
    /// 1.15e41 ETH. Total ETH supply is ~1.2e8. Unreachable, but the
    /// multiplication is still checked (no `unchecked`), so an absurd stake
    /// reverts rather than wrapping.
    function slashAmount(
        uint256 stake,
        uint256 confidence,
        bool outcomeCorrect,
        uint256 maxSlashBps
    ) internal pure returns (uint256) {
        if (maxSlashBps > BPS_DENOMINATOR) revert CapOutOfRange(maxSlashBps);
        uint256 sqErr = squaredError(confidence, outcomeCorrect);
        uint256 raw = (stake * sqErr) / WAD;
        uint256 cap = (stake * maxSlashBps) / BPS_DENOMINATOR;
        return raw > cap ? cap : raw;
    }

    /// @notice Uncapped slash, exposed for monotonicity testing.
    /// @dev The cap deliberately destroys monotonicity above the cap point
    ///      (everything past it flattens to the cap), so the monotonicity
    ///      property is stated and tested against the UNCAPPED value.
    function rawSlash(uint256 stake, uint256 confidence, bool outcomeCorrect)
        internal
        pure
        returns (uint256)
    {
        return (stake * squaredError(confidence, outcomeCorrect)) / WAD;
    }
}
