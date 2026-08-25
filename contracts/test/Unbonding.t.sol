// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {Attestation, IVerifier} from "../src/Attestation.sol";
import {StakePool} from "../src/StakePool.sol";

contract OkVerifier is IVerifier {
    function verifyProof(bytes calldata, uint256[] calldata) external pure returns (bool) {
        return true;
    }
}

/// @notice Phase 3a: the unbonding period, fuzzed across randomised timing.
///
/// The single-path regression test lives in ThreatModel.t.sol. This suite
/// asserts the INVARIANT rather than one sequence: no withdrawal can ever
/// complete while a dispute against that operator is open, regardless of when
/// the request, the dispute, and the execution attempt are interleaved.
contract UnbondingTest is Test {
    uint256 constant WAD = 1e18;
    uint256 constant UNBONDING = 7 days;

    Attestation attestation;
    StakePool pool;

    address admin = address(0xA11CE);
    address operator = address(0x0BE7A704);
    address claimant = address(0xC1A1);
    address r1 = address(0x00000000000000000000000000000000000000A1);
    address r2 = address(0x00000000000000000000000000000000000000A2);
    address r3 = address(0x00000000000000000000000000000000000000A3);

    bytes emptyProof = hex"";
    uint256[] emptyInstances;

    function _committee() internal view returns (address[] memory) {
        address[] memory c = new address[](3);
        c[0] = r1; c[1] = r2; c[2] = r3;
        return c;
    }

    /// Reach the 2-of-3 threshold.
    function _resolve(bytes32 disputeId, bool upheld) internal {
        vm.prank(r1);
        pool.resolveDispute(disputeId, upheld);
        vm.prank(r2);
        pool.resolveDispute(disputeId, upheld);
    }

    function setUp() public {
        attestation = new Attestation(address(new OkVerifier()));
        pool = new StakePool(address(attestation), admin, 10_000, UNBONDING, _committee(), 2, address(0), address(0));
        vm.deal(operator, 10_000 ether);
        vm.deal(claimant, 1 ether);
    }

    function _attest(uint256 confidence, uint256 nonce) internal returns (bytes32) {
        vm.prank(operator);
        return attestation.attest(
            keccak256(abi.encode("decision", nonce)),
            keccak256("shap"),
            confidence,
            int256(uint256(nonce)),
            bytes32("v1"),
            emptyProof,
            emptyInstances
        );
    }

    // -----------------------------------------------------------------
    // THE invariant
    // -----------------------------------------------------------------

    /// No withdrawal completes while a dispute is open, for ANY interleaving
    /// of request time, dispute time, and execution attempt time.
    function testFuzz_noWithdrawalCompletesWhileDisputeIsOpen(
        uint256 stakeAmt,
        uint256 withdrawAmt,
        uint256 delayBeforeRequest,
        uint256 delayBeforeDispute,
        uint256 delayBeforeExecute,
        uint256 confidence
    ) public {
        stakeAmt = bound(stakeAmt, 1 ether, 1_000 ether);
        withdrawAmt = bound(withdrawAmt, 1, stakeAmt);
        delayBeforeRequest = bound(delayBeforeRequest, 0, 30 days);
        delayBeforeDispute = bound(delayBeforeDispute, 0, 30 days);
        delayBeforeExecute = bound(delayBeforeExecute, 0, 60 days);
        confidence = bound(confidence, 0, WAD);

        vm.prank(operator);
        pool.stake{value: stakeAmt}();
        bytes32 attId = _attest(confidence, 1);

        skip(delayBeforeRequest);
        vm.prank(operator);
        pool.requestWithdrawal(withdrawAmt);

        skip(delayBeforeDispute);
        vm.prank(claimant);
        pool.openDispute(attId);

        // A dispute is now open. No amount of waiting may let it through.
        skip(delayBeforeExecute);
        uint256 stakeBefore = pool.stakeOf(operator);
        uint256 balBefore = operator.balance;

        vm.prank(operator);
        try pool.executeWithdrawal() {
            revert("INVARIANT VIOLATED: withdrawal completed with an open dispute");
        } catch {
            // expected
        }

        assertEq(pool.stakeOf(operator), stakeBefore, "stake must be untouched");
        assertEq(operator.balance, balBefore, "no ETH may leave the pool");
        assertGe(address(pool).balance, pool.stakeOf(operator), "pool stays solvent");
    }

    /// Stake requested for withdrawal is still fully slashable while unbonding.
    /// If earmarking reduced the slashable balance, the exploit would survive
    /// in a weaker form.
    function testFuzz_requestedStakeRemainsSlashable(
        uint256 stakeAmt,
        uint256 withdrawAmt,
        uint256 confidence,
        uint256 delay
    ) public {
        stakeAmt = bound(stakeAmt, 1 ether, 1_000 ether);
        withdrawAmt = bound(withdrawAmt, 1, stakeAmt);
        confidence = bound(confidence, 0, WAD);
        delay = bound(delay, 0, 30 days);

        vm.prank(operator);
        pool.stake{value: stakeAmt}();
        bytes32 attId = _attest(confidence, 2);

        vm.prank(operator);
        pool.requestWithdrawal(withdrawAmt);
        skip(delay);

        // The full stake, including the earmarked part, backs the slash.
        assertEq(pool.stakeOf(operator), stakeAmt, "earmarking must not reduce stake");
        uint256 expected = pool.previewSlash(attId, false);

        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);
        _resolve(dispId, false);

        (,,, uint256 slashed) = pool.disputes(dispId);
        assertEq(slashed, expected, "slash must match the pre-request preview");
    }

    /// Execution before maturity always reverts, for any sub-period delay.
    function testFuzz_cannotExecuteBeforeMaturity(uint256 stakeAmt, uint256 earlyDelay) public {
        stakeAmt = bound(stakeAmt, 1 ether, 1_000 ether);
        earlyDelay = bound(earlyDelay, 0, UNBONDING - 1);

        vm.prank(operator);
        pool.stake{value: stakeAmt}();
        vm.prank(operator);
        pool.requestWithdrawal(stakeAmt);

        skip(earlyDelay);
        vm.prank(operator);
        vm.expectRevert();
        pool.executeWithdrawal();
    }

    /// With no dispute, a matured withdrawal must succeed -- the freeze must
    /// not be a permanent lock.
    function testFuzz_maturedWithdrawalSucceedsWithoutDispute(
        uint256 stakeAmt,
        uint256 withdrawAmt,
        uint256 extraDelay
    ) public {
        stakeAmt = bound(stakeAmt, 1 ether, 1_000 ether);
        withdrawAmt = bound(withdrawAmt, 1, stakeAmt);
        extraDelay = bound(extraDelay, 0, 365 days);

        vm.prank(operator);
        pool.stake{value: stakeAmt}();
        vm.prank(operator);
        pool.requestWithdrawal(withdrawAmt);

        skip(UNBONDING + extraDelay);
        uint256 before = operator.balance;
        vm.prank(operator);
        pool.executeWithdrawal();

        assertEq(operator.balance, before + withdrawAmt);
        assertEq(pool.stakeOf(operator), stakeAmt - withdrawAmt);
    }

    // -----------------------------------------------------------------
    // multiple concurrent disputes
    // -----------------------------------------------------------------

    /// Every open dispute must be resolved before the freeze lifts, not just
    /// the first. An off-by-one in the counter would let stake escape while a
    /// second dispute is still live.
    function test_allDisputesMustResolveBeforeFreezeLifts() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 a1 = _attest(0.9e18, 11);
        bytes32 a2 = _attest(0.8e18, 12);

        vm.prank(operator);
        pool.requestWithdrawal(1 ether);

        vm.startPrank(claimant);
        bytes32 d1 = pool.openDispute(a1);
        bytes32 d2 = pool.openDispute(a2);
        vm.stopPrank();
        assertEq(pool.openDisputeCount(operator), 2);

        skip(UNBONDING + 1);

        _resolve(d1, true);
        assertEq(pool.openDisputeCount(operator), 1, "one dispute still open");

        vm.prank(operator);
        vm.expectRevert(
            abi.encodeWithSelector(StakePool.WithdrawalFrozenByOpenDispute.selector, uint256(1))
        );
        pool.executeWithdrawal();

        _resolve(d2, true);
        assertEq(pool.openDisputeCount(operator), 0);

        vm.prank(operator);
        pool.executeWithdrawal(); // now clear
    }

    /// A slash during unbonding can leave less than was requested; execution
    /// must pay out what remains rather than reverting or over-paying.
    function test_withdrawalAfterPartialSlashPaysRemainder() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18, 21);

        vm.prank(operator);
        pool.requestWithdrawal(100 ether); // request everything

        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);
        _resolve(dispId, false); // slashes 98.01 ETH

        skip(UNBONDING + 1);
        uint256 before = operator.balance;
        vm.prank(operator);
        pool.executeWithdrawal();

        assertEq(operator.balance, before + 1.99 ether, "pays only what survived the slash");
        assertEq(pool.stakeOf(operator), 0);
    }

    // -----------------------------------------------------------------
    // request lifecycle
    // -----------------------------------------------------------------

    function test_cannotStackTwoRequests() public {
        vm.startPrank(operator);
        pool.stake{value: 10 ether}();
        pool.requestWithdrawal(1 ether);
        vm.expectRevert();
        pool.requestWithdrawal(1 ether);
        vm.stopPrank();
    }

    function test_cancelReleasesTheRequest() public {
        vm.startPrank(operator);
        pool.stake{value: 10 ether}();
        pool.requestWithdrawal(4 ether);
        pool.cancelWithdrawal();
        assertEq(pool.pendingWithdrawal(operator), 0);
        pool.requestWithdrawal(6 ether); // a new request is now allowed
        vm.stopPrank();
    }

    function test_executeWithoutRequestReverts() public {
        vm.prank(operator);
        vm.expectRevert(StakePool.NoPendingWithdrawal.selector);
        pool.executeWithdrawal();
    }

    function test_zeroUnbondingPeriodIsRejectedAtConstruction() public {
        vm.expectRevert(
            abi.encodeWithSelector(StakePool.UnbondingPeriodTooShort.selector, uint256(0))
        );
        new StakePool(address(attestation), admin, 10_000, 0, _committee(), 2, address(0), address(0));
    }
}
