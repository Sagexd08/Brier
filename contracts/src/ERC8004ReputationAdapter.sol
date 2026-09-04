// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {ReputationRegister} from "./ReputationRegister.sol";

/// @notice The subset of the ERC-8004 Reputation Registry this adapter writes.
/// @dev Signature taken from the ERC-8004 specification (ERC8004SPEC.md,
///      Reputation Registry). Declared locally rather than imported so this
///      repository does not vendor an external dependency for one function;
///      the tradeoff is that a change to the standard breaks this at runtime
///      rather than at compile time, which is why every call is failure-tolerant
///      (see `record` below).
interface IERC8004Reputation {
    function giveFeedback(
        uint256 agentId,
        int128 value,
        uint8 valueDecimals,
        string calldata tag1,
        string calldata tag2,
        string calldata endpoint,
        string calldata feedbackURI,
        bytes32 feedbackHash
    ) external;
}

/// @title Mirrors Brier's calibration reputation into an ERC-8004 registry.
///
/// TRUST TIER: **unchanged from ReputationRegister -- tier 3.** This adapter
/// adds no guarantee whatsoever. It is a projection of existing data onto an
/// external standard's data model, and publishing a number somewhere more
/// visible does not make it more true.
///
/// Specifically, what this does NOT change:
///   - The score still comes from resolved disputes, which come from the N-of-M
///     resolver committee. A colluding committee can manufacture any reputation
///     it likes, and mirroring that to ERC-8004 mirrors the manufactured value
///     with equal fidelity.
///   - Nothing about the ERC-8004 registry validates the number. Per the
///     standard, `value` is an arbitrary int128 at caller-chosen precision.
///     Anyone may write anything and call it a Brier score.
///
/// What it does add is *provenance*: because this contract is the only writer
/// at its own address, and because the EMA it publishes can be replayed from
/// ReputationUpdated events, a reader who checks the writing address gets a
/// score whose derivation is fully auditable. That is a claim about legibility,
/// not about correctness -- and it is worth stating precisely, because the
/// empirical study of the deployed ERC-8004 ecosystem (arXiv:2606.26028) found
/// that feedback there is mostly ungrounded and Sybil-manipulable at minimal
/// cost. Brier's entry is grounded in a staked, adjudicated loss. It is not
/// therefore trustworthy; it is trustworthy exactly to the degree the committee
/// beneath it is, which is a smaller and more auditable assumption than
/// "anonymous reviewers are honest", and no more than that.
///
/// SIGN CONVENTION, and it is the opposite of what a reader expects.
/// A Brier score is a LOSS: lower is better, 0 is perfect, 1 is maximally
/// confident and wrong. ERC-8004 feedback is conventionally read as a rating,
/// where higher is better. Publishing the raw Brier score would therefore
/// invert the meaning for every reader who does not read this comment, and
/// rank the worst operators highest. The published value is
/// `1 - brierScore`, in [0, 1] at 18 decimals, so that higher is better as
/// readers expect. `tag1` names the quantity so the convention is discoverable
/// on-chain rather than only here.
contract ERC8004ReputationAdapter is ReputationRegister {
    /// @notice The external ERC-8004 Reputation Registry. Immutable.
    /// @dev Immutable so an admin cannot silently repoint the mirror at a
    ///      registry with different semantics after integrators have started
    ///      reading it.
    IERC8004Reputation public immutable registry;

    /// @notice ERC-8004 agent id (an ERC-721 token id in the Identity Registry).
    /// @dev One adapter instance per agent. The ERC-8004 Identity Registry has
    ///      no address-to-agentId resolution function in the specification, so
    ///      the mapping from "this Brier deployment" to "that agent" cannot be
    ///      derived on-chain and must be supplied at construction.
    uint256 public immutable agentId;

    /// @notice Fixed-point precision published to ERC-8004. WAD, so 18.
    /// @dev The standard requires valueDecimals in [0, 18]; 18 is the maximum
    ///      and matches Brier's internal WAD exactly, so the mirror is lossless.
    uint8 public constant VALUE_DECIMALS = 18;

    /// @notice tag1 on every feedback entry written by this adapter.
    string public constant TAG_QUANTITY = "brier-calibration";

    /// @notice tag2 on every feedback entry written by this adapter.
    /// @dev Names the sign convention in the tag itself, so a reader who never
    ///      sees this source file still learns that higher is better.
    string public constant TAG_CONVENTION = "one-minus-brier-higher-better";

    /// @notice Emitted when the external registry accepted the mirrored score.
    event MirroredToERC8004(address indexed operator, uint256 agentId, int128 value);

    /// @notice Emitted when the external registry call reverted.
    /// @dev Carries the raw revert data so an operator can diagnose the failure
    ///      without re-running the transaction. This event firing means the
    ///      Brier-side EMA updated and the mirror did not -- the two are now
    ///      out of sync until the next successful mirror overwrites it.
    event MirrorFailed(address indexed operator, uint256 agentId, bytes reason);

    error ZeroRegistry();

    constructor(address recorder_, uint256 alpha_, address registry_, uint256 agentId_)
        ReputationRegister(recorder_, alpha_)
    {
        if (registry_ == address(0)) revert ZeroRegistry();
        registry = IERC8004Reputation(registry_);
        agentId = agentId_;
    }

    /// @notice Record a resolved dispute and mirror the updated score.
    /// @inheritdoc ReputationRegister
    ///
    /// @dev FAILURE MODE, chosen deliberately: the external call is wrapped in
    ///      try/catch and a failure is swallowed into MirrorFailed rather than
    ///      reverting.
    ///
    ///      The alternative -- letting a failed mirror revert -- would mean an
    ///      unrelated third-party contract could halt Brier's dispute
    ///      resolution. A registry that is paused, upgraded to an incompatible
    ///      interface, out of gas, or simply hostile would block every
    ///      resolveDispute call, freezing slashes and payouts. That hands a
    ///      liveness veto over the core mechanism to a contract outside this
    ///      system's trust boundary, to buy consistency in a mirror that is
    ///      explicitly decorative. Slashing must not depend on a registry
    ///      being up.
    ///
    ///      The cost is real and is not hidden: after a failure the mirror is
    ///      stale while the authoritative EMA has moved on. That is acceptable
    ///      only because the mirror is never read by this system -- nothing in
    ///      Brier consumes the ERC-8004 value, so a stale mirror cannot
    ///      mis-price a slash. External readers must treat the mirror as
    ///      best-effort and read `reputationOf` here for the authoritative
    ///      value. MirrorFailed makes each divergence individually visible.
    ///
    ///      A 63/64 gas note: a callee that consumes all forwarded gas leaves
    ///      1/64 for the caller, which is enough to emit MirrorFailed and
    ///      finish resolution. This is not a griefing vector that can halt
    ///      resolution, only one that can waste the resolver's gas.
    function record(address operator, uint256 confidence, bool decisionUpheld)
        external
        override
        onlyRecorder
    {
        // Update the authoritative EMA first. `_record` is the shared internal
        // body; the parent's external `record` cannot be reached via super()
        // from an override, and duplicating the EMA arithmetic here would let
        // the two copies drift.
        _record(operator, confidence, decisionUpheld);

        // Read back the post-update EMA rather than recomputing it, so the
        // mirrored value is by construction the same number this contract
        // reports through reputationOf.
        uint256 score = uint256(_reputation[operator].score);

        // Invert to the higher-is-better convention. squaredError is bounded
        // by WAD (BrierMath), and the EMA of values in [0, WAD] stays in
        // [0, WAD], so this cannot underflow and the result fits int128
        // comfortably -- WAD is ~1e18, int128 holds ~1.7e38.
        int128 value = int128(uint128(WAD - score));

        try registry.giveFeedback(
            agentId,
            value,
            VALUE_DECIMALS,
            TAG_QUANTITY,
            TAG_CONVENTION,
            "", // endpoint: this score is not tied to one service endpoint
            "", // feedbackURI: the on-chain events are the evidence
            bytes32(0) // feedbackHash: no off-chain document to bind
        ) {
            emit MirroredToERC8004(operator, agentId, value);
        } catch (bytes memory reason) {
            emit MirrorFailed(operator, agentId, reason);
        }
    }
}
