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

    Attestation attestation;
    StakePool pool;

    address admin = address(0xA11CE);
    address operator = address(0x0BE7A704);
    address claimant = address(0xC1A1);

    bytes emptyProof = hex"";
    uint256[] emptyInstances;

    function setUp() public {
        attestation = new Attestation(address(new AcceptAll()));
        pool = new StakePool(address(attestation), admin, 10_000);
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

    /// Figure C claims an operator can exit before a dispute lands, reducing
    /// the slash to zero. This test executes that path end to end.
    function test_tier2_operatorCanFrontRunDisputeByWithdrawing() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18); // confident, and about to be wrong

        // Operator sees the pending dispute and exits first. Nothing stops it.
        vm.prank(operator);
        pool.withdraw(100 ether);
        assertEq(pool.stakeOf(operator), 0, "withdraw is unguarded");

        // The dispute proceeds and resolves against the operator...
        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);
        vm.prank(admin);
        pool.resolveDispute(dispId, false);

        // ...and recovers nothing. A 98.01% slash became 0.
        (,,, uint256 slashed) = pool.disputes(dispId);
        assertEq(slashed, 0, "Figure C tier 2 assumption B is unenforced");
        assertEq(claimant.balance, 1 ether, "claimant is made whole by nothing");
    }

    /// The same decision, if the operator does NOT exit, costs 98.01 ETH.
    /// The delta between this and the test above is the value of the missing
    /// unbonding period.
    function test_tier2_sameDecisionCosts98EthIfOperatorDoesNotExit() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18);

        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);
        vm.prank(admin);
        pool.resolveDispute(dispId, false);

        (,,, uint256 slashed) = pool.disputes(dispId);
        assertEq(slashed, 98.01 ether, "unexited stake is slashed in full");
    }

    // -----------------------------------------------------------------
    // TIER 3: single admin key
    // -----------------------------------------------------------------

    /// Figure C claims a dishonest admin can shield a miscalibrated operator.
    function test_tier3_adminCanShieldAMiscalibratedOperator() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18); // confident and, in truth, wrong

        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);

        // Admin simply declares the decision upheld. No evidence is consulted
        // because the contract has no notion of evidence.
        vm.prank(admin);
        pool.resolveDispute(dispId, true);

        (,,, uint256 slashed) = pool.disputes(dispId);
        assertEq(slashed, 0.01 ether, "admin fiat reduced a 98.01 ETH slash to 0.01");
    }

    /// And can slash a well-calibrated operator that did nothing wrong.
    function test_tier3_adminCanSlashAnHonestOperator() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18); // confident and, in truth, correct

        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);
        vm.prank(admin);
        pool.resolveDispute(dispId, false); // admin lies

        (,,, uint256 slashed) = pool.disputes(dispId);
        assertEq(slashed, 98.01 ether, "no recourse against a dishonest admin");
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
