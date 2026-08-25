// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {Attestation, IVerifier} from "../src/Attestation.sol";
import {StakePool} from "../src/StakePool.sol";
import {CollusionOracle} from "../src/CollusionOracle.sol";

contract OkVerifier2 is IVerifier {
    function verifyProof(bytes calldata, uint256[] calldata) external pure returns (bool) {
        return true;
    }
}

/// @notice The GNN detector wired to an enforcement path, and the cost of that.
///
/// The tests prefixed `test_dangerous_` are the important ones. They do not
/// assert the system is safe; they assert that the documented danger is real
/// and reachable, in the same spirit as ThreatModel.t.sol. The detector behind
/// these flags has never been validated against real collusion, and these
/// tests are what stop that fact being quietly forgotten.
contract CollusionOracleTest is Test {
    uint256 constant WAD = 1e18;
    uint256 constant APPEAL = 3 days;

    Attestation attestation;
    StakePool pool;
    CollusionOracle oracle;

    address admin = address(0xA11CE);
    address reporter = address(0x9E7);
    address operator = address(0x0BE7A704);
    address honestClaimant = address(0xC1A1);
    address ringClaimant = address(0xBAD);
    address r1 = address(0x00000000000000000000000000000000000000A1);
    address r2 = address(0x00000000000000000000000000000000000000A2);
    address r3 = address(0x00000000000000000000000000000000000000A3);

    bytes emptyProof = hex"";
    uint256[] emptyInstances;
    uint256 nonce;

    function setUp() public {
        vm.warp(1_700_000_000);
        attestation = new Attestation(address(new OkVerifier2()));
        oracle = new CollusionOracle(admin, reporter, APPEAL);

        address[] memory c = new address[](3);
        c[0] = r1; c[1] = r2; c[2] = r3;
        pool = new StakePool(address(attestation), admin, 10_000, 7 days, c, 2,
                             address(0), address(oracle));

        vm.deal(operator, 1_000 ether);
        vm.deal(honestClaimant, 1 ether);
        vm.deal(ringClaimant, 1 ether);
    }

    function _attest(uint256 confidence) internal returns (bytes32) {
        nonce++;
        vm.prank(operator);
        return attestation.attest(
            keccak256(abi.encode(confidence, nonce)), keccak256("shap"),
            confidence, int256(1), bytes32("v1"), emptyProof, emptyInstances
        );
    }

    function _resolve(bytes32 disputeId, bool upheld) internal {
        vm.prank(r1);
        pool.resolveDispute(disputeId, upheld);
        vm.prank(r2);
        pool.resolveDispute(disputeId, upheld);
    }

    function _flag(address subject, uint256 score) internal {
        vm.prank(reporter);
        oracle.flag(subject, score, bytes32("gnn-v1"), "ipfs://evidence");
    }

    // ------------------------------------------------------------------
    // Raising flags
    // ------------------------------------------------------------------

    function test_onlyReporterCanFlag() public {
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(CollusionOracle.NotReporter.selector, admin));
        oracle.flag(ringClaimant, 0.95e18, bytes32("gnn-v1"), "ipfs://x");
    }

    function test_lowScoreIsRefused() public {
        // Read the threshold BEFORE the prank: a view call here would consume
        // it, and the flag would then revert as NotReporter instead.
        uint256 minScore = oracle.MIN_SCORE();
        vm.prank(reporter);
        vm.expectRevert(abi.encodeWithSelector(
            CollusionOracle.ScoreBelowThreshold.selector, 0.5e18, minScore));
        oracle.flag(ringClaimant, 0.5e18, bytes32("gnn-v1"), "ipfs://x");
    }

    function test_constructorRejectsInstantEnforcement() public {
        // A zero appeal window would let a false positive bite in the same
        // block it was raised. Rejected outright.
        vm.expectRevert(abi.encodeWithSelector(
            CollusionOracle.AppealWindowTooShort.selector, uint256(0)));
        new CollusionOracle(admin, reporter, 0);
    }

    function test_cannotDoubleFlag() public {
        _flag(ringClaimant, 0.95e18);
        vm.prank(reporter);
        vm.expectRevert(abi.encodeWithSelector(
            CollusionOracle.AlreadyFlagged.selector, ringClaimant));
        oracle.flag(ringClaimant, 0.99e18, bytes32("gnn-v1"), "ipfs://x");
    }

    function test_flagRecordsTheModelThatFiredIt() public {
        _flag(ringClaimant, 0.95e18);
        CollusionOracle.Flag memory f = oracle.flagOf(ringClaimant);
        assertEq(f.modelVersion, bytes32("gnn-v1"),
            "a flag must be traceable to a specific detector build");
        assertEq(f.evidenceUri, "ipfs://evidence");
        assertEq(f.score, 0.95e18);
    }

    // ------------------------------------------------------------------
    // The appeal window
    // ------------------------------------------------------------------

    function test_flagIsNotEnforcedDuringAppealWindow() public {
        _flag(ringClaimant, 0.95e18);
        assertTrue(oracle.isFlagged(ringClaimant), "the flag exists");
        assertFalse(oracle.isEnforced(ringClaimant), "but it has no effect yet");

        // And the claimant can still act during the window.
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.9e18);
        vm.prank(ringClaimant);
        pool.openDispute(attId); // does not revert
    }

    function test_flagTakesEffectAfterTheWindow() public {
        _flag(ringClaimant, 0.95e18);
        skip(APPEAL);
        assertTrue(oracle.isEnforced(ringClaimant));
    }

    function test_clearedFlagIsNeverEnforced() public {
        _flag(ringClaimant, 0.95e18);
        vm.prank(admin);
        oracle.clearFlag(ringClaimant, "appeal upheld");
        skip(APPEAL * 10);
        assertFalse(oracle.isEnforced(ringClaimant));
        assertFalse(oracle.isFlagged(ringClaimant));
    }

    // ------------------------------------------------------------------
    // Enforcement: blocking disputes
    // ------------------------------------------------------------------

    function test_enforcedFlagBlocksNewDisputes() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        _flag(ringClaimant, 0.95e18);
        skip(APPEAL);

        bytes32 attId = _attest(0.9e18);
        vm.prank(ringClaimant);
        vm.expectRevert(abi.encodeWithSelector(
            StakePool.ClaimantFlaggedForCollusion.selector, ringClaimant));
        pool.openDispute(attId);
    }

    function test_unflaggedClaimantIsUnaffected() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        _flag(ringClaimant, 0.95e18);
        skip(APPEAL);

        bytes32 attId = _attest(0.9e18);
        vm.prank(honestClaimant);
        pool.openDispute(attId); // must not revert
    }

    // ------------------------------------------------------------------
    // Enforcement: quarantining the payout
    // ------------------------------------------------------------------

    function test_flaggedClaimantsPayoutIsQuarantinedNotPaid() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();

        // Dispute opened BEFORE the flag takes effect, then flagged.
        bytes32 attId = _attest(0.8e18);
        vm.prank(ringClaimant);
        bytes32 dispId = pool.openDispute(attId);
        _flag(ringClaimant, 0.95e18);
        skip(APPEAL);

        uint256 before = ringClaimant.balance;
        _resolve(dispId, false);

        (,,, uint256 slashed) = pool.disputes(dispId);
        assertEq(slashed, 64 ether, "the slash is computed and taken as normal");
        assertEq(ringClaimant.balance, before, "but the claimant receives nothing");
        assertEq(oracle.quarantined(ringClaimant), 64 ether, "it is held in quarantine");
        assertEq(oracle.totalQuarantined(), 64 ether);
    }

    function test_operatorIsStillSlashedWhenClaimantIsFlagged() public {
        // A suspected colluding claimant does not make the operator's decision
        // retroactively correct, and must not become a way to escape a slash.
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.8e18);
        vm.prank(ringClaimant);
        bytes32 dispId = pool.openDispute(attId);
        _flag(ringClaimant, 0.95e18);
        skip(APPEAL);
        _resolve(dispId, false);

        assertEq(pool.stakeOf(operator), 36 ether, "operator still loses the stake");
    }

    function test_clearingAFlagRefundsTheQuarantinedPayout() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.8e18);
        vm.prank(ringClaimant);
        bytes32 dispId = pool.openDispute(attId);
        _flag(ringClaimant, 0.95e18);
        skip(APPEAL);
        _resolve(dispId, false);

        uint256 before = ringClaimant.balance;
        vm.prank(admin);
        oracle.clearFlag(ringClaimant, "false positive, appeal upheld");

        assertEq(ringClaimant.balance, before + 64 ether,
            "a reversed false positive must return the money in full");
        assertEq(oracle.quarantined(ringClaimant), 0);
        assertEq(oracle.totalQuarantined(), 0);
    }

    function test_forfeitRequiresAHumanAndAnEnforcedFlag() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.8e18);
        vm.prank(ringClaimant);
        bytes32 dispId = pool.openDispute(attId);
        _flag(ringClaimant, 0.95e18);
        skip(APPEAL);
        _resolve(dispId, false);

        // Not the reporter, and not the detector: only the admin.
        vm.prank(reporter);
        vm.expectRevert(CollusionOracle.NotAdmin.selector);
        oracle.forfeit(ringClaimant, admin);

        vm.prank(admin);
        oracle.forfeit(ringClaimant, admin);
        assertEq(admin.balance, 64 ether);
        assertEq(oracle.quarantined(ringClaimant), 0);
    }

    // ==================================================================
    // THE DANGEROUS PART. These assert that the risk is real.
    // ==================================================================

    /// @notice A false positive silences a legitimate claimant.
    ///
    /// The detector's false-positive rate on real dispute traffic has never
    /// been measured. This test executes what that unmeasured rate buys: an
    /// honest claimant, wrongly flagged, cannot file a dispute at all. The
    /// appeal window and the reversible quarantine bound the damage; they do
    /// not remove it.
    function test_dangerous_falsePositiveSilencesAnHonestClaimant() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();

        _flag(honestClaimant, 0.95e18); // the model is simply wrong here
        skip(APPEAL);

        bytes32 attId = _attest(0.99e18); // a genuinely bad, confident decision
        vm.prank(honestClaimant);
        vm.expectRevert(abi.encodeWithSelector(
            StakePool.ClaimantFlaggedForCollusion.selector, honestClaimant));
        pool.openDispute(attId);

        // The operator keeps its stake, and the decision goes unchallenged.
        assertEq(pool.stakeOf(operator), 100 ether,
            "an unvalidated model output just protected a bad decision");
    }

    /// @notice The reporter key can flag anyone, for any reason or none.
    ///
    /// There is no proof on-chain that a flag came from the detector at all.
    /// A compromised or dishonest reporter is indistinguishable from a model
    /// output. This is tier 3, and thinner than the committee: one key, not N.
    function test_dangerous_reporterCanFlagArbitrarily() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();

        // No model was run. No evidence exists. The flag stands regardless.
        vm.prank(reporter);
        oracle.flag(honestClaimant, WAD, bytes32(0), "");
        skip(APPEAL);

        assertTrue(oracle.isEnforced(honestClaimant),
            "nothing on-chain distinguishes a detector output from a lie");
    }

    /// @notice Admin + reporter together can confiscate an honest claimant's payout.
    ///
    /// Flag, wait out the appeal window, let the dispute resolve, forfeit. The
    /// claimant's award is gone and the only recourse was an appeal to the same
    /// admin that took it.
    function test_dangerous_flagPlusForfeitConfiscatesAnHonestAward() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.8e18);
        vm.prank(honestClaimant);
        bytes32 dispId = pool.openDispute(attId);

        _flag(honestClaimant, 0.95e18);
        skip(APPEAL);
        _resolve(dispId, false);

        vm.prank(admin);
        oracle.forfeit(honestClaimant, admin);

        assertEq(oracle.quarantined(honestClaimant), 0);
        assertEq(admin.balance, 64 ether,
            "an unvalidated flag plus an admin signature took a legitimate award");
    }

    /// @notice Detaching the oracle restores the unenforced behaviour exactly.
    /// @dev The escape hatch, asserted. A deployment that has not measured its
    ///      own false-positive rate should pass address(0), and this test shows
    ///      that doing so costs nothing else.
    function test_poolWithoutOracleIgnoresFlagsEntirely() public {
        address[] memory c = new address[](3);
        c[0] = r1; c[1] = r2; c[2] = r3;
        StakePool bare = new StakePool(address(attestation), admin, 10_000, 7 days, c, 2,
                                       address(0), address(0));
        vm.prank(operator);
        bare.stake{value: 100 ether}();

        _flag(honestClaimant, 0.99e18);
        skip(APPEAL);

        bytes32 attId = _attest(0.8e18);
        vm.prank(honestClaimant);
        bytes32 dispId = bare.openDispute(attId); // flag has no effect
        uint256 before = honestClaimant.balance;
        vm.prank(r1);
        bare.resolveDispute(dispId, false);
        vm.prank(r2);
        bare.resolveDispute(dispId, false);

        assertEq(honestClaimant.balance, before + 64 ether, "paid normally");
        assertEq(oracle.quarantined(honestClaimant), 0);
    }
}
