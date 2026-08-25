// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title Collusion flags from the off-chain detector, with an enforcement path.
///
/// ============================ READ THIS FIRST ============================
///
/// The detector behind these flags is validated ONLY against synthetically
/// injected collusion rings. Its false-positive rate on genuine dispute
/// traffic has never been measured, because no labelled real collusion
/// exists. Every flag this contract stores is therefore an **unvalidated
/// machine-learning output being given authority over money**.
///
/// That is a deliberate decision by the deployer, not an oversight, and it is
/// the single weakest link in the system. This contract is built to contain
/// the damage rather than to pretend it is absent:
///
///   1. A flag NEVER slashes anyone directly. It withholds a claimant's
///      payout and blocks new disputes from that address. The slash itself
///      is still computed and still requires the N-of-M committee.
///   2. Flags take effect only after an APPEAL WINDOW, so a flagged address
///      has a bounded, on-chain period in which to contest before any
///      consequence attaches.
///   3. Withheld payouts are QUARANTINED, not burned and not paid to the
///      operator. A cleared flag returns the money. A false positive is
///      therefore reversible, which is the property that makes an
///      unvalidated detector survivable at all.
///   4. The reporter key is tier 3. It can flag anyone, and
///      `test_dangerous_reporterCanSilenceAnHonestClaimant` proves it.
///
/// TRUST TIER: 3, and arguably below it. The committee at least requires N
/// signatures; this is one key relaying the output of a model nobody has
/// validated against reality. Nothing here is cryptographically guaranteed
/// and nothing here is economically enforced.
/// ========================================================================
contract CollusionOracle {
    /// @notice Minimum detector score, WAD, below which a flag is refused.
    /// @dev A floor, not a calibration. The score is a sigmoid output from an
    ///      unvalidated model; the threshold makes the flag less trigger-happy
    ///      but does not make the model correct.
    uint256 public constant MIN_SCORE = 0.8e18;

    /// @notice Delay between a flag being raised and it taking effect.
    uint256 public immutable appealWindow;

    /// @notice May raise flags. Expected to be the monitoring service.
    address public reporter;

    /// @notice May clear flags and resolve appeals.
    address public immutable admin;

    struct Flag {
        uint256 score;          // detector output, WAD
        uint64 raisedAt;
        uint64 effectiveAt;     // raisedAt + appealWindow
        bool cleared;
        bytes32 modelVersion;   // ModelRegistry id of the detector that fired
        string evidenceUri;     // off-chain evidence bundle
    }

    mapping(address => Flag) internal _flags;

    /// @notice Payouts withheld from flagged claimants, recoverable on clearing.
    mapping(address => uint256) public quarantined;

    /// @notice Total quarantined, so the pool's own balance accounting is checkable.
    uint256 public totalQuarantined;

    event Flagged(address indexed subject, uint256 score, uint64 effectiveAt,
                  bytes32 modelVersion, string evidenceUri);
    event FlagCleared(address indexed subject, string reason, uint256 released);
    event Quarantined(address indexed subject, uint256 amount, uint256 total);
    event QuarantineReleased(address indexed subject, address indexed to, uint256 amount);
    event ReporterChanged(address indexed previous, address indexed next);

    error NotReporter(address caller);
    error NotAdmin();
    error ScoreBelowThreshold(uint256 score, uint256 minimum);
    error AlreadyFlagged(address subject);
    error NotFlagged(address subject);
    error AppealWindowTooShort(uint256 given);
    error NothingQuarantined(address subject);
    error TransferFailed();

    uint256 public constant MIN_APPEAL_WINDOW = 1 days;

    constructor(address admin_, address reporter_, uint256 appealWindow_) {
        // A zero-length appeal window would make a false positive take effect
        // in the same block it was raised, removing the only recourse a
        // wrongly-flagged address has. Rejected at construction.
        if (appealWindow_ < MIN_APPEAL_WINDOW) revert AppealWindowTooShort(appealWindow_);
        admin = admin_;
        reporter = reporter_;
        appealWindow = appealWindow_;
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert NotAdmin();
        _;
    }

    // ------------------------------------------------------------------
    // Raising and clearing
    // ------------------------------------------------------------------

    /// @notice Raise a collusion flag against an address.
    /// @param subject The claimant the detector flagged.
    /// @param score Detector output in WAD. Must be >= MIN_SCORE.
    /// @param modelVersion Registry id of the detector build that fired, so a
    ///        flag can be traced to a specific model rather than to "the AI".
    /// @param evidenceUri Off-chain bundle: the subgraph, features, and score.
    function flag(address subject, uint256 score, bytes32 modelVersion,
                  string calldata evidenceUri) external {
        if (msg.sender != reporter) revert NotReporter(msg.sender);
        if (score < MIN_SCORE) revert ScoreBelowThreshold(score, MIN_SCORE);
        Flag memory existing = _flags[subject];
        if (existing.raisedAt != 0 && !existing.cleared) revert AlreadyFlagged(subject);

        uint64 effective = uint64(block.timestamp + appealWindow);
        _flags[subject] = Flag({
            score: score,
            raisedAt: uint64(block.timestamp),
            effectiveAt: effective,
            cleared: false,
            modelVersion: modelVersion,
            evidenceUri: evidenceUri
        });
        emit Flagged(subject, score, effective, modelVersion, evidenceUri);
    }

    /// @notice Clear a flag and release anything quarantined under it.
    /// @dev The appeal path. Deliberately admin-only and deliberately cheap to
    ///      call: reversing a false positive must be easier than creating one.
    function clearFlag(address subject, string calldata reason) external onlyAdmin {
        Flag storage f = _flags[subject];
        if (f.raisedAt == 0 || f.cleared) revert NotFlagged(subject);
        f.cleared = true;

        uint256 held = quarantined[subject];
        if (held > 0) {
            quarantined[subject] = 0;
            totalQuarantined -= held;
            (bool ok,) = subject.call{value: held}("");
            if (!ok) revert TransferFailed();
            emit QuarantineReleased(subject, subject, held);
        }
        emit FlagCleared(subject, reason, held);
    }

    /// @notice Replace the reporter key.
    function setReporter(address next) external onlyAdmin {
        emit ReporterChanged(reporter, next);
        reporter = next;
    }

    // ------------------------------------------------------------------
    // Queries
    // ------------------------------------------------------------------

    /// @notice Whether a flag is currently in force.
    /// @dev False during the appeal window, and false once cleared. Callers
    ///      must use this rather than reading `flagOf(...).score` directly, or
    ///      they will act on flags that have not taken effect.
    function isEnforced(address subject) public view returns (bool) {
        Flag memory f = _flags[subject];
        return f.raisedAt != 0 && !f.cleared && block.timestamp >= f.effectiveAt;
    }

    /// @notice Whether a flag exists at all, enforced or still appealable.
    function isFlagged(address subject) external view returns (bool) {
        Flag memory f = _flags[subject];
        return f.raisedAt != 0 && !f.cleared;
    }

    function flagOf(address subject) external view returns (Flag memory) {
        return _flags[subject];
    }

    // ------------------------------------------------------------------
    // Quarantine
    // ------------------------------------------------------------------

    /// @notice Accept a withheld payout on behalf of a flagged claimant.
    /// @dev Called by the StakePool at resolution. The money is held here, not
    ///      redirected to the operator: paying the operator would give it a
    ///      motive to get its own claimants flagged, which would be a far worse
    ///      incentive than the one this is meant to remove.
    function quarantine(address subject) external payable {
        quarantined[subject] += msg.value;
        totalQuarantined += msg.value;
        emit Quarantined(subject, msg.value, quarantined[subject]);
    }

    /// @notice Forfeit quarantined funds after an upheld flag.
    /// @dev Admin-only and separate from clearing, so that confiscation is
    ///      always a deliberate human act rather than an automatic consequence
    ///      of a model output. This is the ONLY path by which a detector flag
    ///      can cause a permanent loss, and a person has to take it.
    function forfeit(address subject, address to) external onlyAdmin {
        uint256 held = quarantined[subject];
        if (held == 0) revert NothingQuarantined(subject);
        if (!isEnforced(subject)) revert NotFlagged(subject);
        quarantined[subject] = 0;
        totalQuarantined -= held;
        (bool ok,) = to.call{value: held}("");
        if (!ok) revert TransferFailed();
        emit QuarantineReleased(subject, to, held);
    }

    receive() external payable {}
}
