// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {BrierMath} from "./BrierMath.sol";
import {Attestation} from "./Attestation.sol";

/// @title StakePool
/// @notice Operators stake collateral per decision class. When a dispute
///         resolves against a decision, stake is slashed in proportion to how
///         MISCALIBRATED the operator was, using the Brier score.
///
/// ============================ SIMULATED =============================
/// Dispute resolution in this MVP is ADMIN-ARBITRATED. A single address
/// decides every outcome, which means a single key decides who loses money.
/// There is no decentralized jury, no oracle, no evidentiary standard, and
/// no appeals process. This is the largest gap between this MVP and anything
/// deployable. See docs/PATH_TO_PRODUCTION.md.
/// ====================================================================
contract StakePool {
    using BrierMath for uint256;

    enum DisputeStatus { None, Open, ResolvedUpheld, ResolvedOverturned }

    struct Dispute {
        address claimant;
        bytes32 attestationId;
        DisputeStatus status;
        uint256 slashed;
    }

    Attestation public immutable attestation;
    address public admin;

    /// @notice Cap on any single slash, in basis points of the operator's stake.
    uint256 public maxSlashBps;

    mapping(address => uint256) public stakeOf;
    mapping(bytes32 => Dispute) public disputes;
    /// @dev One dispute per attestation.
    mapping(bytes32 => bool) public disputed;

    event Staked(address indexed operator, uint256 amount, uint256 newTotal);
    event Withdrawn(address indexed operator, uint256 amount, uint256 newTotal);
    event DisputeOpened(bytes32 indexed disputeId, bytes32 indexed attestationId, address indexed claimant);
    event DisputeResolved(
        bytes32 indexed disputeId,
        bytes32 indexed attestationId,
        bool decisionUpheld,
        uint256 confidence,
        uint256 slashed
    );
    event PaidOut(bytes32 indexed disputeId, address indexed claimant, uint256 amount);

    error NotAdmin();
    error NoStake();
    error InsufficientStake(uint256 requested, uint256 available);
    error AlreadyDisputed(bytes32 attestationId);
    error UnknownDispute(bytes32 disputeId);
    error DisputeNotOpen(bytes32 disputeId);
    error CapOutOfRange(uint256 capBps);
    error PayoutFailed();

    modifier onlyAdmin() {
        if (msg.sender != admin) revert NotAdmin();
        _;
    }

    constructor(address attestation_, address admin_, uint256 maxSlashBps_) {
        if (maxSlashBps_ > 10_000) revert CapOutOfRange(maxSlashBps_);
        attestation = Attestation(attestation_);
        admin = admin_;
        maxSlashBps = maxSlashBps_;
    }

    // ------------------------------------------------------------------
    // Staking
    // ------------------------------------------------------------------

    function stake() external payable {
        if (msg.value == 0) revert NoStake();
        stakeOf[msg.sender] += msg.value;
        emit Staked(msg.sender, msg.value, stakeOf[msg.sender]);
    }

    /// @dev No unbonding period. A production system needs one, or an operator
    ///      front-runs every dispute by withdrawing. Called out in the README.
    function withdraw(uint256 amount) external {
        uint256 bal = stakeOf[msg.sender];
        if (amount > bal) revert InsufficientStake(amount, bal);
        stakeOf[msg.sender] = bal - amount;
        emit Withdrawn(msg.sender, amount, stakeOf[msg.sender]);
        (bool ok,) = msg.sender.call{value: amount}("");
        if (!ok) revert PayoutFailed();
    }

    // ------------------------------------------------------------------
    // Disputes
    // ------------------------------------------------------------------

    function openDispute(bytes32 attestationId) external returns (bytes32 disputeId) {
        if (disputed[attestationId]) revert AlreadyDisputed(attestationId);
        // Reverts if the attestation does not exist.
        attestation.get(attestationId);

        disputed[attestationId] = true;
        disputeId = keccak256(abi.encode(attestationId, msg.sender, block.timestamp));
        disputes[disputeId] = Dispute({
            claimant: msg.sender,
            attestationId: attestationId,
            status: DisputeStatus.Open,
            slashed: 0
        });
        disputeIdFor[attestationId] = disputeId;
        emit DisputeOpened(disputeId, attestationId, msg.sender);
    }

    /// @notice SIMULATED dispute resolution: the admin declares the outcome.
    /// @param decisionUpheld True if the original decision was correct.
    ///
    /// The slash is `stake * (confidence - outcome)^2`, capped at
    /// `maxSlashBps`. A confident-and-wrong operator loses far more than an
    /// uncertain-and-wrong one; a confident-and-right operator loses almost
    /// nothing. That asymmetry is the product.
    function resolveDispute(bytes32 disputeId, bool decisionUpheld) external onlyAdmin {
        Dispute storage d = disputes[disputeId];
        if (d.claimant == address(0)) revert UnknownDispute(disputeId);
        if (d.status != DisputeStatus.Open) revert DisputeNotOpen(disputeId);

        Attestation.Record memory rec = attestation.get(d.attestationId);

        uint256 operatorStake = stakeOf[rec.operator];
        uint256 slash = BrierMath.slashAmount(
            operatorStake, rec.confidence, decisionUpheld, maxSlashBps
        );

        stakeOf[rec.operator] = operatorStake - slash;
        d.slashed = slash;
        d.status = decisionUpheld ? DisputeStatus.ResolvedUpheld : DisputeStatus.ResolvedOverturned;

        emit DisputeResolved(disputeId, d.attestationId, decisionUpheld, rec.confidence, slash);

        if (slash > 0) {
            (bool ok,) = d.claimant.call{value: slash}("");
            if (!ok) revert PayoutFailed();
            emit PaidOut(disputeId, d.claimant, slash);
        }
    }

    /// @notice Dispute id opened against an attestation, if any.
    /// @dev Avoids having to reconstruct the id from event logs off-chain.
    mapping(bytes32 => bytes32) public disputeIdFor;

    /// @notice Preview a slash without changing state. Used by the demo.
    function previewSlash(bytes32 attestationId, bool decisionUpheld)
        external
        view
        returns (uint256)
    {
        Attestation.Record memory rec = attestation.get(attestationId);
        return BrierMath.slashAmount(stakeOf[rec.operator], rec.confidence, decisionUpheld, maxSlashBps);
    }

    function setMaxSlashBps(uint256 newCapBps) external onlyAdmin {
        if (newCapBps > 10_000) revert CapOutOfRange(newCapBps);
        maxSlashBps = newCapBps;
    }

    receive() external payable {}
}
