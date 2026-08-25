// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {BrierMath} from "./BrierMath.sol";

/// @title Per-operator calibration reputation, as an EMA of realised Brier score.
///
/// TRUST TIER: this is **not** a new cryptographic guarantee, and the naming
/// throughout is chosen so it cannot be read as one.
///
/// The aggregation is on-chain and auditable: anyone can replay the update rule
/// against the emitted events and reproduce the score exactly. But the *inputs*
/// are resolved dispute outcomes, which come from the N-of-M resolver committee
/// -- tier 3. A reputation score therefore inherits the trust level of the
/// dispute layer beneath it and is worth exactly as much as that layer, no
/// more. A colluding committee can manufacture any reputation it likes for any
/// operator, in either direction.
///
/// What the score does add is *legibility*: a single number, updated by a rule
/// fixed in advance, that makes an operator's realised calibration history
/// visible without trusting anyone's summary of it.
///
/// The quantity tracked is the Brier score of each disputed decision --
/// (confidence - outcome)^2 -- so LOWER is better, exactly as for the slash.
/// A well-calibrated operator that is occasionally wrong converges to a small
/// positive value, not to zero: p(1-p) is irreducible (see the proposal, 3.2).
contract ReputationRegister {
    uint256 internal constant WAD = 1e18;

    /// @notice Smoothing factor, WAD. score' = alpha*sample + (1-alpha)*score.
    /// @dev Immutable so an admin cannot retune history's weighting after the
    ///      fact. A higher alpha forgets faster.
    uint256 public immutable alpha;

    /// @notice The only address permitted to record outcomes: the StakePool.
    /// @dev Set once at construction. If any address could record, an operator
    ///      would simply report its own perfect scores.
    address public immutable recorder;

    struct Reputation {
        uint128 score;      // EMA of Brier score, WAD. 0 until first sample.
        uint64 samples;     // resolved disputes counted
        uint64 lastUpdated; // block timestamp of the most recent sample
    }

    mapping(address => Reputation) internal _reputation;

    event ReputationUpdated(
        address indexed operator,
        uint256 sample,
        uint256 newScore,
        uint256 samples
    );

    error NotRecorder(address caller);
    error AlphaOutOfRange(uint256 alpha);
    error ZeroRecorder();

    constructor(address recorder_, uint256 alpha_) {
        if (recorder_ == address(0)) revert ZeroRecorder();
        // alpha == 0 would freeze the score at its first sample forever;
        // alpha > WAD would overshoot and is meaningless.
        if (alpha_ == 0 || alpha_ > WAD) revert AlphaOutOfRange(alpha_);
        recorder = recorder_;
        alpha = alpha_;
    }

    modifier onlyRecorder() {
        if (msg.sender != recorder) revert NotRecorder(msg.sender);
        _;
    }

    /// @notice Fold one resolved dispute into an operator's reputation.
    /// @param operator The operator whose decision was disputed.
    /// @param confidence Confidence the operator attested, WAD.
    /// @param decisionUpheld True if the committee upheld the decision.
    ///
    /// @dev Called by the StakePool at resolution, from the same
    ///      (confidence, outcome) pair that drives the slash -- so the score
    ///      and the penalty can never diverge.
    function record(address operator, uint256 confidence, bool decisionUpheld)
        external
        onlyRecorder
    {
        uint256 sample = BrierMath.squaredError(confidence, decisionUpheld);
        Reputation memory r = _reputation[operator];

        // The first sample seeds the EMA outright. Blending it against a zero
        // initial score would report a brand-new operator as better calibrated
        // than one with a long clean record, which is precisely backwards.
        uint256 next = r.samples == 0
            ? sample
            : (alpha * sample + (WAD - alpha) * uint256(r.score)) / WAD;

        _reputation[operator] = Reputation({
            score: uint128(next),
            samples: r.samples + 1,
            lastUpdated: uint64(block.timestamp)
        });

        emit ReputationUpdated(operator, sample, next, r.samples + 1);
    }

    /// @notice Current EMA Brier score. Lower is better.
    /// @dev Returns (score, samples, lastUpdated). `samples == 0` means no
    ///      resolved disputes yet, which is NOT the same as good calibration
    ///      and callers must not treat a zero score as a positive signal.
    function reputationOf(address operator)
        external
        view
        returns (uint256 score, uint256 samples, uint256 lastUpdated)
    {
        Reputation memory r = _reputation[operator];
        return (uint256(r.score), uint256(r.samples), uint256(r.lastUpdated));
    }

    /// @notice Whether an operator has any resolved history at all.
    /// @dev Exposed separately so integrators are forced to distinguish
    ///      "no history" from "perfect history" rather than reading a 0 score.
    function hasHistory(address operator) external view returns (bool) {
        return _reputation[operator].samples > 0;
    }
}
