// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {Attestation, IVerifier} from "../src/Attestation.sol";
import {StakePool} from "../src/StakePool.sol";

contract AcceptAll is IVerifier {
    function verifyProof(bytes calldata, uint256[] calldata) external pure returns (bool) {
        return true;
    }
}

/// @notice Executable evidence for the trust tiers in Figure C of the proposal.
///
/// These tests do NOT assert that the system is secure. They assert that the
/// documented weaknesses are real and reachable, so that the threat model
/// cannot silently drift away from the code. A failure here means the
/// proposal's Figure C has become wrong and must be updated.
contract ThreatModelTest is Test {
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
        attestation = new Attestation(address(new AcceptAll()));
        pool = new StakePool(address(attestation), admin, 10_000, UNBONDING, _committee(), 2);
        vm.deal(operator, 1_000 ether);
        vm.deal(claimant, 1 ether);
    }

    function _attest(uint256 confidence) internal returns (bytes32) {
        vm.prank(operator);
        return attestation.attest(
            keccak256("decision"), keccak256("shap"), confidence,
            int256(1), bytes32("v1"), emptyProof, emptyInstances
        );
    }

    // -----------------------------------------------------------------
    // TIER 2, assumption B: BROKEN in v0
    // -----------------------------------------------------------------

    /// REGRESSION TEST for the v0 exploit, now CLOSED (Phase 3a).
    ///
    /// In v0 this exact sequence reduced a 98.01 ETH slash to 0: withdraw()
    /// executed instantly, so an operator watching the mempool could exit
    /// before openDispute() was mined. The unbonding period closes it. This
    /// test now asserts the attack FAILS, and is the acceptance criterion for
    /// Phase 3a -- if it ever passes again, tier 2 has regressed.
    function test_tier2_frontRunDisputeByWithdrawing_isNowBlocked() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18); // confident, and about to be wrong

        // Operator sees the dispute coming and tries to exit. It can only
        // REQUEST -- the stake stays bonded and fully slashable.
        vm.prank(operator);
        pool.requestWithdrawal(100 ether);
        assertEq(pool.stakeOf(operator), 100 ether, "stake must stay bonded during unbonding");

        // Immediate execution fails: the clock has not matured.
        vm.prank(operator);
        vm.expectRevert(
            abi.encodeWithSelector(
                StakePool.WithdrawalNotReady.selector,
                block.timestamp + UNBONDING,
                block.timestamp
            )
        );
        pool.executeWithdrawal();

        // The dispute lands during unbonding.
        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);

        // Even after the clock matures, the open dispute freezes execution.
        vm.warp(block.timestamp + UNBONDING + 1);
        vm.prank(operator);
        vm.expectRevert(
            abi.encodeWithSelector(StakePool.WithdrawalFrozenByOpenDispute.selector, uint256(1))
        );
        pool.executeWithdrawal();

        // Resolution slashes the full amount: the exploit recovered nothing.
        _resolve(dispId, false);
        (,,, uint256 slashed) = pool.disputes(dispId);
        assertEq(slashed, 98.01 ether, "slash must land in full despite the exit attempt");
        assertEq(claimant.balance, 1 ether + 98.01 ether, "claimant is paid");
    }

    /// The freeze lifts once the dispute is resolved -- an operator is not
    /// locked in forever, which would be its own (opposite) design fault.
    function test_tier2_withdrawalUnfreezesAfterDisputeResolves() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.60e18);

        vm.prank(operator);
        pool.requestWithdrawal(10 ether);

        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);
        assertEq(pool.openDisputeCount(operator), 1);

        _resolve(dispId, true);
        assertEq(pool.openDisputeCount(operator), 0, "freeze must lift on resolution");

        vm.warp(block.timestamp + UNBONDING + 1);
        uint256 before = operator.balance;
        vm.prank(operator);
        pool.executeWithdrawal();
        assertEq(operator.balance, before + 10 ether, "withdrawal completes once clear");
    }

    /// Baseline: with no exit attempt at all, the slash is the same 98.01 ETH.
    /// Phase 3a's guarantee is that the attempt above changes nothing.
    function test_tier2_sameDecisionCosts98EthWithNoExitAttempt() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18);

        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);
        _resolve(dispId, false);

        (,,, uint256 slashed) = pool.disputes(dispId);
        assertEq(slashed, 98.01 ether, "unexited stake is slashed in full");
    }

    // -----------------------------------------------------------------
    // TIER 2, RESIDUAL GAPS after Phase 3a
    //
    // The unbonding period closes the mempool front-running exploit. It does
    // NOT make stake unconditionally available at slash time. These two tests
    // document precisely what survives, so "unbonding is enforced" cannot be
    // read as "the economic tier is now guaranteed".
    // -----------------------------------------------------------------

    /// RESIDUAL GAP A: the freeze only bites if a dispute is actually opened
    /// during the unbonding window. A decision nobody disputes in time is
    /// unbacked once the operator exits.
    ///
    /// This is a bound on the DISPUTE WINDOW, not a bug in the timelock: it
    /// says the unbonding period must exceed the time a claimant realistically
    /// needs to notice a bad decision and act. For loan rejections, where the
    /// counterfactual may take months to surface, 7 days is almost certainly
    /// too short. Choosing that parameter is unresolved.
    function test_tier2_residualGap_exitBeforeAnyDisputeIsRaised() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18);

        vm.prank(operator);
        pool.requestWithdrawal(100 ether);
        skip(UNBONDING + 1); // nobody disputes within the window
        vm.prank(operator);
        pool.executeWithdrawal();
        assertEq(pool.stakeOf(operator), 0);

        // The dispute now lands against an operator with nothing at stake.
        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);
        _resolve(dispId, false);

        (,,, uint256 slashed) = pool.disputes(dispId);
        assertEq(slashed, 0, "slash is 0 when no dispute is raised in the window");
    }

    /// RESIDUAL GAP B: the freeze is released by dispute RESOLUTION, and
    /// resolution is a tier-3 admin action. A dishonest admin can resolve
    /// favourably to unfreeze an operator's exit.
    ///
    /// Tier 2 is therefore enforced *against the operator* but still
    /// *downstream of tier 3*. Closing this requires Phase 3b and beyond, not
    /// a longer timelock.
    function test_tier2_residualGap_adminCanUnfreezeByResolvingFavourably() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18);

        vm.prank(operator);
        pool.requestWithdrawal(100 ether);
        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);
        skip(UNBONDING + 1);

        _resolve(dispId, true); // admin declares it upheld
        vm.prank(operator);
        pool.executeWithdrawal();

        assertEq(pool.stakeOf(operator), 0, "tier-3 admin still gates tier-2 enforcement");
    }

    // -----------------------------------------------------------------
    // TIER 3: single admin key
    // -----------------------------------------------------------------

    /// PHASE 3B: N colluding resolvers have EXACTLY the power the single admin
    /// had in v0. This is the test that keeps "bounded trust" from being read
    /// as "trustless". If it ever fails, the trust model changed and every doc
    /// claiming bounded trust must be revisited.
    function test_tier3_nOfMCollusionHasSameEffectAsV0Admin() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18); // confident and, in truth, correct

        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);

        // Two of three resolvers collude and declare the decision overturned.
        // No evidence is consulted, because the contract has no notion of it.
        _resolve(dispId, false);

        (,,, uint256 slashed) = pool.disputes(dispId);
        assertEq(slashed, 98.01 ether,
            "2-of-3 collusion slashes an honest operator exactly as v0's single admin did");
    }

    /// A single resolver cannot act alone: that is the whole of the improvement.
    function test_tier3_singleResolverCannotResolveAlone() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18);
        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);

        vm.prank(r1);
        pool.resolveDispute(dispId, false); // one vote, below threshold

        (,, StakePool.DisputeStatus status, uint256 slashed) = pool.disputes(dispId);
        assertEq(uint256(status), uint256(StakePool.DisputeStatus.Open),
            "one vote must not resolve the dispute");
        assertEq(slashed, 0, "no slash below threshold");
        assertEq(pool.stakeOf(operator), 100 ether, "stake untouched");
        // And the operator stays frozen while it is unresolved.
        assertEq(pool.openDisputeCount(operator), 1);
    }

    /// The admin can replace the committee, so bounded trust bounds the
    /// RESOLUTION step, not committee SELECTION. Stated so nobody mistakes the
    /// multisig for removal of the admin.
    function test_tier3_adminCanReplaceTheCommittee() public {
        address[] memory captured = new address[](2);
        captured[0] = address(0xBAD1);
        captured[1] = address(0xBAD2);

        vm.prank(admin);
        pool.setCommittee(captured, 2);

        assertTrue(pool.isResolver(address(0xBAD1)));
        assertFalse(pool.isResolver(r1), "previous resolver was removed by the admin");
    }

    /// Figure C claims a dishonest committee can shield a miscalibrated operator.
    function test_tier3_committeeCanShieldAMiscalibratedOperator() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18); // confident and, in truth, wrong

        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);

        // Admin simply declares the decision upheld. No evidence is consulted
        // because the contract has no notion of evidence.
        _resolve(dispId, true);

        (,,, uint256 slashed) = pool.disputes(dispId);
        assertEq(slashed, 0.01 ether, "committee fiat reduced a 98.01 ETH slash to 0.01");
    }

    /// And can slash a well-calibrated operator that did nothing wrong.
    function test_tier3_committeeCanSlashAnHonestOperator() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18); // confident and, in truth, correct

        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);
        _resolve(dispId, false); // admin lies

        (,,, uint256 slashed) = pool.disputes(dispId);
        assertEq(slashed, 98.01 ether, "no recourse against a dishonest committee");
    }

    // -----------------------------------------------------------------
    // TIER 1 boundary: what the proof does NOT bind
    // -----------------------------------------------------------------

    /// The attestation stores whatever margin the operator supplies. Nothing
    /// on-chain relates it to the base model. This is the input-logit
    /// provenance gap, shown as a passing test rather than a claim in prose.
    function test_tier1_marginIsUnverifiedOperatorSuppliedInput() public {
        vm.prank(operator);
        bytes32 id = attestation.attest(
            keccak256("decision"),
            keccak256("shap"),
            0.99e18,
            type(int256).max, // an absurd logit no model could produce
            bytes32("v1"),
            emptyProof,
            emptyInstances
        );
        Attestation.Record memory r = attestation.get(id);
        assertEq(r.margin, type(int256).max, "chain accepts any margin");
        assertTrue(r.proofVerified, "and still marks the attestation proved");
    }
}
