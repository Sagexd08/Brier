// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {Attestation, IVerifier} from "../src/Attestation.sol";
import {BrierMath} from "../src/BrierMath.sol";
import {StakePool} from "../src/StakePool.sol";

/// @dev Stand-in verifier for the integration tests. The REAL EZKL verifier is
///      exercised separately in test/Verifier.t.sol against the generated
///      contract; using it here too would make every staking test depend on
///      3.3 KB of calldata for no added coverage.
contract MockVerifier is IVerifier {
    bool public shouldAccept = true;

    function setAccept(bool v) external {
        shouldAccept = v;
    }

    function verifyProof(bytes calldata, uint256[] calldata) external view returns (bool) {
        return shouldAccept;
    }
}

contract RejectingReceiver {
    // No receive/fallback: any ETH transfer to this address fails.
}

contract StakePoolTest is Test {
    uint256 constant WAD = 1e18;
    uint256 constant UNBONDING = 7 days;

    Attestation attestation;
    StakePool pool;
    MockVerifier verifier;

    address admin = address(0xA11CE);
    address operator = address(0x0BE7A704);
    address claimant = address(0xC1A1);
    // Bounded-trust committee: 2-of-3. NOT decentralised; see docs/PHASE3B_TRUST_MODEL.md
    address r1 = address(0x00000000000000000000000000000000000000A1);
    address r2 = address(0x00000000000000000000000000000000000000A2);
    address r3 = address(0x00000000000000000000000000000000000000A3);

    bytes emptyProof = hex"";
    uint256[] emptyInstances;


    function _committee() internal returns (address[] memory) {
        address[] memory c = new address[](3);
        c[0] = r1; c[1] = r2; c[2] = r3;
        return c;
    }


    /// Reach the 2-of-3 threshold. Bounded trust: TWO keys, not one.
    function _resolve(bytes32 disputeId, bool upheld) internal {
        vm.prank(r1);
        pool.resolveDispute(disputeId, upheld);
        vm.prank(r2);
        pool.resolveDispute(disputeId, upheld);
    }

    function setUp() public {
        verifier = new MockVerifier();
        attestation = new Attestation(address(verifier));
        pool = new StakePool(address(attestation), admin, 10_000, UNBONDING, _committee(), 2, address(0), address(0));

        vm.deal(operator, 1_000 ether);
        vm.deal(claimant, 1 ether);
    }

    // ---------------------------------------------------------------
    // helpers
    // ---------------------------------------------------------------

    function _attest(uint256 confidence) internal returns (bytes32) {
        vm.prank(operator);
        return attestation.attest(
            keccak256("decision-1"),
            keccak256("shap-vector-1"),
            confidence,
            int256(1_500_000_000_000_000_000),
            bytes32("brier-mvp-v1"),
            emptyProof,
            emptyInstances
        );
    }

    function _stakeAndAttest(uint256 stakeAmt, uint256 confidence)
        internal
        returns (bytes32 attId, bytes32 dispId)
    {
        vm.prank(operator);
        pool.stake{value: stakeAmt}();
        attId = _attest(confidence);
        vm.prank(claimant);
        dispId = pool.openDispute(attId);
    }

    // ---------------------------------------------------------------
    // staking
    // ---------------------------------------------------------------

    function test_stakeIncreasesBalance() public {
        vm.prank(operator);
        pool.stake{value: 10 ether}();
        assertEq(pool.stakeOf(operator), 10 ether);
        assertEq(address(pool).balance, 10 ether);
    }

    function test_stakeRevertsOnZero() public {
        vm.prank(operator);
        vm.expectRevert(StakePool.NoStake.selector);
        pool.stake{value: 0}();
    }

    function test_withdrawReturnsFundsAfterUnbonding() public {
        vm.startPrank(operator);
        pool.stake{value: 10 ether}();
        uint256 before = operator.balance;
        pool.requestWithdrawal(4 ether);
        vm.stopPrank();

        // Stake is untouched during unbonding: still fully slashable.
        assertEq(pool.stakeOf(operator), 10 ether);

        vm.warp(block.timestamp + UNBONDING);
        vm.prank(operator);
        pool.executeWithdrawal();

        assertEq(pool.stakeOf(operator), 6 ether);
        assertEq(operator.balance, before + 4 ether);
    }

    function test_withdrawRevertsAboveBalance() public {
        vm.startPrank(operator);
        pool.stake{value: 1 ether}();
        vm.expectRevert(
            abi.encodeWithSelector(StakePool.InsufficientStake.selector, 2 ether, 1 ether)
        );
        pool.requestWithdrawal(2 ether);
        vm.stopPrank();
    }

    // ---------------------------------------------------------------
    // the three headline scenarios
    // ---------------------------------------------------------------

    /// (a) confident + correct == no meaningful slash
    function test_scenario_confidentAndCorrect_noSlash() public {
        (, bytes32 dispId) = _stakeAndAttest(100 ether, 0.99e18);
        _resolve(dispId, true); // decision upheld

        // (0.99 - 1)^2 = 0.0001 -> 0.01% of 100 ETH = 0.01 ETH
        assertEq(pool.stakeOf(operator), 100 ether - 0.01 ether);
        (,,, uint256 slashed) = pool.disputes(dispId);
        assertEq(slashed, 0.01 ether);
    }

    /// (b) confident + wrong == large slash
    function test_scenario_confidentAndWrong_largeSlash() public {
        (, bytes32 dispId) = _stakeAndAttest(100 ether, 0.99e18);
        _resolve(dispId, false); // overturned

        // (0.99 - 0)^2 = 0.9801 -> 98.01 ETH
        assertEq(pool.stakeOf(operator), 100 ether - 98.01 ether);
        assertEq(claimant.balance, 1 ether + 98.01 ether);
    }

    /// (c) uncertain + wrong == small slash
    function test_scenario_uncertainAndWrong_smallSlash() public {
        (, bytes32 dispId) = _stakeAndAttest(100 ether, 0.55e18);
        _resolve(dispId, false);

        // (0.55)^2 = 0.3025 -> 30.25 ETH, far below the confident case
        assertEq(pool.stakeOf(operator), 100 ether - 30.25 ether);
        assertEq(claimant.balance, 1 ether + 30.25 ether);
    }

    /// The ordering that makes the mechanism meaningful, in one test.
    function test_scenarioOrdering_confidentWrongCostsMostByFar() public {
        uint256 confidentWrong = BrierMath.rawSlash(100 ether, 0.99e18, false);
        uint256 uncertainWrong = BrierMath.rawSlash(100 ether, 0.55e18, false);
        uint256 confidentRight = BrierMath.rawSlash(100 ether, 0.99e18, true);

        assertGt(confidentWrong, uncertainWrong);
        assertGt(uncertainWrong, confidentRight);
        // And the gap is large, not marginal: >3x between the wrong cases.
        assertGt(confidentWrong, uncertainWrong * 3);
    }

    // ---------------------------------------------------------------
    // dispute mechanics
    // ---------------------------------------------------------------

    function test_openDisputeRevertsForUnknownAttestation() public {
        vm.prank(claimant);
        vm.expectRevert(
            abi.encodeWithSelector(Attestation.UnknownAttestation.selector, bytes32("nope"))
        );
        pool.openDispute(bytes32("nope"));
    }

    function test_cannotDisputeSameAttestationTwice() public {
        (bytes32 attId,) = _stakeAndAttest(10 ether, 0.8e18);
        vm.prank(claimant);
        vm.expectRevert(abi.encodeWithSelector(StakePool.AlreadyDisputed.selector, attId));
        pool.openDispute(attId);
    }

    /// A non-resolver cannot resolve. (Phase 3b: was onlyAdmin in v0.)
    function test_onlyCommitteeMembersCanResolve() public {
        (, bytes32 dispId) = _stakeAndAttest(10 ether, 0.8e18);
        vm.prank(claimant);
        vm.expectRevert(abi.encodeWithSelector(StakePool.NotResolver.selector, claimant));
        pool.resolveDispute(dispId, false);

        // Even the admin cannot resolve unless it is on the committee.
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(StakePool.NotResolver.selector, admin));
        pool.resolveDispute(dispId, false);
    }

    function test_cannotResolveTwice() public {
        (, bytes32 dispId) = _stakeAndAttest(10 ether, 0.8e18);
        _resolve(dispId, false);
        vm.prank(r3);
        vm.expectRevert(abi.encodeWithSelector(StakePool.DisputeNotOpen.selector, dispId));
        pool.resolveDispute(dispId, false);
    }

    function test_resolveUnknownDisputeReverts() public {
        vm.prank(r1);
        vm.expectRevert(abi.encodeWithSelector(StakePool.UnknownDispute.selector, bytes32("x")));
        pool.resolveDispute(bytes32("x"), true);
    }

    // ---------------------------------------------------------------
    // cap, accounting, and edge cases
    // ---------------------------------------------------------------

    function test_capIsEnforcedOnResolution() public {
        StakePool capped = new StakePool(address(attestation), admin, 2_500, UNBONDING, _committee(), 2, address(0), address(0)); // 25%
        vm.prank(operator);
        capped.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18);
        vm.prank(claimant);
        bytes32 dispId = capped.openDispute(attId);

        vm.prank(r1);
        capped.resolveDispute(dispId, false);
        vm.prank(r2);
        capped.resolveDispute(dispId, false);
        // Uncapped would be 98.01 ETH; the cap clamps it to 25 ETH.
        assertEq(capped.stakeOf(operator), 75 ether);
    }

    function test_slashNeverExceedsOperatorStake() public {
        (, bytes32 dispId) = _stakeAndAttest(1 ether, WAD); // confidence 1.0, wrong
        _resolve(dispId, false);
        assertEq(pool.stakeOf(operator), 0, "full stake slashed, never underflows");
    }

    function test_zeroStakeOperatorSlashesZero() public {
        bytes32 attId = _attest(0.99e18); // operator never staked
        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);
        _resolve(dispId, false);
        assertEq(pool.stakeOf(operator), 0);
    }

    function test_previewMatchesActualSlash() public {
        (bytes32 attId, bytes32 dispId) = _stakeAndAttest(100 ether, 0.77e18);
        uint256 preview = pool.previewSlash(attId, false);
        _resolve(dispId, false);
        (,,, uint256 actual) = pool.disputes(dispId);
        assertEq(preview, actual, "preview must not lie");
    }

    function test_payoutFailureRevertsWholeResolution() public {
        RejectingReceiver bad = new RejectingReceiver();
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18);
        vm.prank(address(bad));
        bytes32 dispId = pool.openDispute(attId);

        vm.prank(r1);
        pool.resolveDispute(dispId, false);
        vm.prank(r2);
        vm.expectRevert(StakePool.PayoutFailed.selector);
        pool.resolveDispute(dispId, false);
        // Stake must be untouched after the revert.
        assertEq(pool.stakeOf(operator), 100 ether);
    }

    function test_setMaxSlashBpsOnlyAdmin() public {
        vm.prank(claimant);
        vm.expectRevert(StakePool.NotAdmin.selector);
        pool.setMaxSlashBps(100);

        vm.prank(admin);
        pool.setMaxSlashBps(100);
        assertEq(pool.maxSlashBps(), 100);
    }

    // ---------------------------------------------------------------
    // attestation
    // ---------------------------------------------------------------

    function test_attestRejectsInvalidProof() public {
        verifier.setAccept(false);
        vm.prank(operator);
        vm.expectRevert(Attestation.ProofRejected.selector);
        attestation.attest(
            keccak256("d"),
            keccak256("s"),
            0.9e18,
            int256(1),
            bytes32("v1"),
            emptyProof,
            emptyInstances
        );
    }

    function test_attestRejectsConfidenceAboveOne() public {
        vm.prank(operator);
        vm.expectRevert(
            abi.encodeWithSelector(Attestation.ConfidenceOutOfRange.selector, WAD + 1)
        );
        attestation.attest(
            keccak256("d"), keccak256("s"), WAD + 1, int256(1), bytes32("v1"),
            emptyProof, emptyInstances
        );
    }

    function test_duplicateAttestationReverts() public {
        bytes32 id = _attest(0.9e18);
        // Call attestation directly: vm.expectRevert needs the reverting call
        // to happen at a lower depth than the cheatcode, which an internal
        // helper does not satisfy.
        vm.prank(operator);
        vm.expectRevert(abi.encodeWithSelector(Attestation.AlreadyAttested.selector, id));
        attestation.attest(
            keccak256("decision-1"),
            keccak256("shap-vector-1"),
            0.9e18,
            int256(1_500_000_000_000_000_000),
            bytes32("brier-mvp-v1"),
            emptyProof,
            emptyInstances
        );
    }

    function test_attestationStoresAllFields() public {
        bytes32 id = _attest(0.83e18);
        Attestation.Record memory r = attestation.get(id);
        assertEq(r.operator, operator);
        assertEq(r.confidence, 0.83e18);
        assertEq(r.shapHash, keccak256("shap-vector-1"));
        assertEq(r.modelVersion, bytes32("brier-mvp-v1"));
        assertTrue(r.proofVerified);
        assertEq(attestation.count(), 1);
    }

    // ---------------------------------------------------------------
    // fuzz: conservation of value
    // ---------------------------------------------------------------

    /// Whatever is slashed must land with the claimant, and the pool must stay
    /// solvent for the remaining stake.
    function testFuzz_slashIsConserved(uint256 stakeAmt, uint256 confidence, bool upheld)
        public
    {
        stakeAmt = bound(stakeAmt, 1 wei, 500 ether);
        confidence = bound(confidence, 0, WAD);

        vm.prank(operator);
        pool.stake{value: stakeAmt}();
        bytes32 attId = _attest(confidence);
        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);

        uint256 claimantBefore = claimant.balance;
        _resolve(dispId, upheld);

        (,,, uint256 slashed) = pool.disputes(dispId);
        assertLe(slashed, stakeAmt, "cannot slash more than staked");
        assertEq(claimant.balance, claimantBefore + slashed, "claimant receives exactly the slash");
        assertEq(pool.stakeOf(operator), stakeAmt - slashed, "operator loses exactly the slash");
        assertGe(address(pool).balance, pool.stakeOf(operator), "pool stays solvent");
    }
}
