// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {BrierMath} from "./BrierMath.sol";
import {Attestation} from "./Attestation.sol";

/// @title StakePool
/// @notice Operators stake collateral per decision class. When a dispute
///         resolves against a decision, stake is slashed in proportion to how
///         MISCALIBRATED the operator was, using the Brier score.
///
/// ========================= BOUNDED TRUST ============================
/// Dispute resolution requires N-of-M signatures from a FIXED, admin-set
/// resolver committee. This is NOT decentralization: the committee is a fixed
/// list chosen by the deployer, resolvers have nothing at stake, there is no
/// evidentiary standard, no appeal, and no permissionless entry.
///
/// The only thing that changes versus a single admin key is the number of keys
/// an adversary must corrupt: 1 -> N. N colluding resolvers have exactly the
/// power the single admin had. See docs/PHASE3B_TRUST_MODEL.md.
/// ====================================================================
contract StakePool {
    using BrierMath for uint256;

    /// @notice Floor on the unbonding period, enforced at construction.
    uint256 public constant MIN_UNBONDING_PERIOD = 1 hours;

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

    // ------------------------------------------------------------------
    // Bounded-trust resolution (Phase 3b): N-of-M committee
    // ------------------------------------------------------------------

    /// @notice Fixed resolver committee. Membership is set by the admin.
    address[] public resolvers;
    mapping(address => bool) public isResolver;

    /// @notice Signatures required to resolve a dispute.
    uint256 public threshold;

    /// @dev disputeId => resolver => whether that resolver has voted.
    mapping(bytes32 => mapping(address => bool)) public hasVoted;
    /// @dev disputeId => votes cast for "decision upheld".
    mapping(bytes32 => uint256) public votesUpheld;
    /// @dev disputeId => votes cast for "decision overturned".
    mapping(bytes32 => uint256) public votesOverturned;

    mapping(address => uint256) public stakeOf;
    mapping(bytes32 => Dispute) public disputes;
    /// @dev One dispute per attestation.
    mapping(bytes32 => bool) public disputed;

    // ------------------------------------------------------------------
    // Unbonding (Phase 3a)
    // ------------------------------------------------------------------

    /// @notice Delay between requesting a withdrawal and being able to execute it.
    /// @dev Must exceed the window in which a claimant could realistically
    ///      notice a bad decision and open a dispute. Set at construction.
    uint256 public immutable unbondingPeriod;

    struct WithdrawalRequest {
        uint256 amount;
        uint256 readyAt;
    }

    /// @notice Pending withdrawal per operator. At most one at a time.
    mapping(address => WithdrawalRequest) public withdrawalRequest;

    /// @notice Amount an operator has earmarked for withdrawal but not yet taken.
    /// @dev Still slashable: it remains part of stakeOf until executed. Earmarking
    ///      does not reduce the collateral backing outstanding decisions.
    mapping(address => uint256) public pendingWithdrawal;

    /// @notice Count of currently-open disputes naming this operator.
    /// @dev A non-zero count freezes withdrawal execution. Maintained on
    ///      openDispute (increment) and resolveDispute (decrement).
    mapping(address => uint256) public openDisputeCount;

    event Staked(address indexed operator, uint256 amount, uint256 newTotal);
    event Withdrawn(address indexed operator, uint256 amount, uint256 newTotal);
    event WithdrawalRequested(address indexed operator, uint256 amount, uint256 readyAt);
    event WithdrawalCancelled(address indexed operator, uint256 amount);
    event DisputeOpened(bytes32 indexed disputeId, bytes32 indexed attestationId, address indexed claimant);
    event DisputeResolved(
        bytes32 indexed disputeId,
        bytes32 indexed attestationId,
        bool decisionUpheld,
        uint256 confidence,
        uint256 slashed
    );
    event PaidOut(bytes32 indexed disputeId, address indexed claimant, uint256 amount);
    event ResolverVoted(bytes32 indexed disputeId, address indexed resolver, bool upheld,
                        uint256 votesUpheld, uint256 votesOverturned);
    event CommitteeChanged(address[] resolvers, uint256 threshold);

    error NotAdmin();
    error NoStake();
    error InsufficientStake(uint256 requested, uint256 available);
    error AlreadyDisputed(bytes32 attestationId);
    error UnknownDispute(bytes32 disputeId);
    error DisputeNotOpen(bytes32 disputeId);
    error CapOutOfRange(uint256 capBps);
    error PayoutFailed();
    error NoPendingWithdrawal();
    error WithdrawalNotReady(uint256 readyAt, uint256 nowTs);
    error WithdrawalFrozenByOpenDispute(uint256 openDisputes);
    error WithdrawalAlreadyPending(uint256 amount, uint256 readyAt);
    error UnbondingPeriodTooShort(uint256 given);
    error NotResolver(address caller);
    error AlreadyVoted(bytes32 disputeId, address resolver);
    error InvalidCommittee(uint256 m, uint256 n);
    error DuplicateResolver(address resolver);

    modifier onlyAdmin() {
        if (msg.sender != admin) revert NotAdmin();
        _;
    }

    constructor(
        address attestation_,
        address admin_,
        uint256 maxSlashBps_,
        uint256 unbondingPeriod_,
        address[] memory resolvers_,
        uint256 threshold_
    ) {
        if (maxSlashBps_ > 10_000) revert CapOutOfRange(maxSlashBps_);
        // A zero-length unbonding period would reintroduce the v0 front-running
        // exploit exactly, so it is rejected at construction rather than left
        // as a footgun for a deployer.
        if (unbondingPeriod_ < MIN_UNBONDING_PERIOD) {
            revert UnbondingPeriodTooShort(unbondingPeriod_);
        }
        attestation = Attestation(attestation_);
        admin = admin_;
        maxSlashBps = maxSlashBps_;
        unbondingPeriod = unbondingPeriod_;
        _setCommittee(resolvers_, threshold_);
    }

    // ------------------------------------------------------------------
    // Committee management
    // ------------------------------------------------------------------

    function _setCommittee(address[] memory resolvers_, uint256 threshold_) internal {
        // A threshold of 1, or a threshold above the committee size, would make
        // "N-of-M" meaningless; both are rejected.
        if (threshold_ < 2 || threshold_ > resolvers_.length) {
            revert InvalidCommittee(resolvers_.length, threshold_);
        }
        for (uint256 i = 0; i < resolvers.length; i++) {
            isResolver[resolvers[i]] = false;
        }
        delete resolvers;
        for (uint256 i = 0; i < resolvers_.length; i++) {
            address r = resolvers_[i];
            if (r == address(0) || isResolver[r]) revert DuplicateResolver(r);
            isResolver[r] = true;
            resolvers.push(r);
        }
        threshold = threshold_;
        emit CommitteeChanged(resolvers_, threshold_);
    }

    /// @notice Replace the resolver committee.
    /// @dev NOTE: the admin retains this power, so the admin can appoint a
    ///      committee it controls. Bounded trust bounds the RESOLUTION step,
    ///      not committee selection. Documented in docs/PHASE3B_TRUST_MODEL.md
    ///      and asserted by test_tier3_adminCanReplaceTheCommittee.
    function setCommittee(address[] calldata resolvers_, uint256 threshold_)
        external
        onlyAdmin
    {
        _setCommittee(resolvers_, threshold_);
    }

    function committeeSize() external view returns (uint256) {
        return resolvers.length;
    }

    // ------------------------------------------------------------------
    // Staking
    // ------------------------------------------------------------------

    function stake() external payable {
        if (msg.value == 0) revert NoStake();
        stakeOf[msg.sender] += msg.value;
        emit Staked(msg.sender, msg.value, stakeOf[msg.sender]);
    }

    /// @notice Step 1 of 2: request a withdrawal, starting the unbonding clock.
    /// @dev The amount stays in `stakeOf` and remains fully slashable during
    ///      unbonding. Requesting a withdrawal is not a way to move collateral
    ///      out of reach of a dispute -- that was precisely the v0 exploit.
    function requestWithdrawal(uint256 amount) external {
        uint256 bal = stakeOf[msg.sender];
        if (amount == 0 || amount > bal) revert InsufficientStake(amount, bal);

        WithdrawalRequest memory existing = withdrawalRequest[msg.sender];
        if (existing.amount != 0) {
            revert WithdrawalAlreadyPending(existing.amount, existing.readyAt);
        }

        uint256 readyAt = block.timestamp + unbondingPeriod;
        withdrawalRequest[msg.sender] = WithdrawalRequest({amount: amount, readyAt: readyAt});
        pendingWithdrawal[msg.sender] = amount;
        emit WithdrawalRequested(msg.sender, amount, readyAt);
    }

    /// @notice Step 2 of 2: execute a matured withdrawal.
    ///
    /// Blocked while ANY dispute naming this operator is open. This is the
    /// check that closes the v0 front-running exploit: an operator who sees a
    /// dispute coming cannot exit, because either
    ///   (a) the unbonding clock has not matured, or
    ///   (b) the dispute is open and freezes execution.
    /// Both conditions are re-checked at execution time, not at request time.
    function executeWithdrawal() external {
        WithdrawalRequest memory req = withdrawalRequest[msg.sender];
        if (req.amount == 0) revert NoPendingWithdrawal();
        if (block.timestamp < req.readyAt) {
            revert WithdrawalNotReady(req.readyAt, block.timestamp);
        }
        uint256 open = openDisputeCount[msg.sender];
        if (open != 0) revert WithdrawalFrozenByOpenDispute(open);

        uint256 bal = stakeOf[msg.sender];
        // A slash during unbonding can have reduced the stake below the
        // requested amount; pay out at most what is actually left.
        uint256 amount = req.amount > bal ? bal : req.amount;

        delete withdrawalRequest[msg.sender];
        pendingWithdrawal[msg.sender] = 0;
        stakeOf[msg.sender] = bal - amount;

        emit Withdrawn(msg.sender, amount, stakeOf[msg.sender]);
        if (amount > 0) {
            (bool ok,) = msg.sender.call{value: amount}("");
            if (!ok) revert PayoutFailed();
        }
    }

    /// @notice Abandon a pending withdrawal and keep the stake bonded.
    function cancelWithdrawal() external {
        WithdrawalRequest memory req = withdrawalRequest[msg.sender];
        if (req.amount == 0) revert NoPendingWithdrawal();
        delete withdrawalRequest[msg.sender];
        pendingWithdrawal[msg.sender] = 0;
        emit WithdrawalCancelled(msg.sender, req.amount);
    }

    // ------------------------------------------------------------------
    // Disputes
    // ------------------------------------------------------------------

    function openDispute(bytes32 attestationId) external returns (bytes32 disputeId) {
        if (disputed[attestationId]) revert AlreadyDisputed(attestationId);
        // Reverts if the attestation does not exist.
        Attestation.Record memory rec = attestation.get(attestationId);

        disputed[attestationId] = true;
        disputeId = keccak256(abi.encode(attestationId, msg.sender, block.timestamp));
        disputes[disputeId] = Dispute({
            claimant: msg.sender,
            attestationId: attestationId,
            status: DisputeStatus.Open,
            slashed: 0
        });
        // Freeze this operator's withdrawals until the dispute resolves.
        openDisputeCount[rec.operator] += 1;
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
    function resolveDispute(bytes32 disputeId, bool decisionUpheld) external {
        if (!isResolver[msg.sender]) revert NotResolver(msg.sender);

        Dispute storage d = disputes[disputeId];
        if (d.claimant == address(0)) revert UnknownDispute(disputeId);
        if (d.status != DisputeStatus.Open) revert DisputeNotOpen(disputeId);
        if (hasVoted[disputeId][msg.sender]) revert AlreadyVoted(disputeId, msg.sender);

        hasVoted[disputeId][msg.sender] = true;
        uint256 up = votesUpheld[disputeId];
        uint256 over = votesOverturned[disputeId];
        if (decisionUpheld) {
            up += 1;
            votesUpheld[disputeId] = up;
        } else {
            over += 1;
            votesOverturned[disputeId] = over;
        }
        emit ResolverVoted(disputeId, msg.sender, decisionUpheld, up, over);

        // Below threshold on both sides: record the vote and stop. The dispute
        // stays Open, so the operator's withdrawal stays frozen meanwhile.
        uint256 t = threshold;
        if (up < t && over < t) return;

        // One side reached the threshold; that side is the outcome.
        decisionUpheld = up >= t;

        Attestation.Record memory rec = attestation.get(d.attestationId);

        uint256 operatorStake = stakeOf[rec.operator];
        uint256 slash = BrierMath.slashAmount(
            operatorStake, rec.confidence, decisionUpheld, maxSlashBps
        );

        stakeOf[rec.operator] = operatorStake - slash;
        d.slashed = slash;
        d.status = decisionUpheld ? DisputeStatus.ResolvedUpheld : DisputeStatus.ResolvedOverturned;
        // Dispute closed: release this operator's withdrawal freeze by one.
        openDisputeCount[rec.operator] -= 1;

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
