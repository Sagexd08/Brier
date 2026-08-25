// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {Attestation, IVerifier} from "../src/Attestation.sol";
import {StakePool} from "../src/StakePool.sol";
import {ReputationRegister} from "../src/ReputationRegister.sol";

contract AlwaysOk is IVerifier {
    function verifyProof(bytes calldata, uint256[] calldata) external pure returns (bool) {
        return true;
    }
}

/// @notice Phase F integration: reputation is driven by REAL resolutions.
///
/// The unit suite drives record() directly. This one goes through the whole
/// path -- stake, attest, dispute, N-of-M resolve -- so a future refactor that
/// stops calling the register, or calls it with the wrong operator, fails here
/// instead of silently producing an empty history.
contract ReputationIntegrationTest is Test {
    uint256 constant WAD = 1e18;

    Attestation attestation;
    StakePool pool;
    ReputationRegister rep;

    address admin = address(0xA11CE);
    address operator = address(0x0BE7A704);
    address claimant = address(0xC1A1);
    address r1 = address(0x00000000000000000000000000000000000000A1);
    address r2 = address(0x00000000000000000000000000000000000000A2);
    address r3 = address(0x00000000000000000000000000000000000000A3);

    bytes emptyProof = hex"";
    uint256[] emptyInstances;
    uint256 nonce;

    function setUp() public {
        attestation = new Attestation(address(new AlwaysOk()));
        address[] memory c = new address[](3);
        c[0] = r1; c[1] = r2; c[2] = r3;

        // Two-way binding fixed at deploy: the register names the pool as its
        // only recorder, and the pool holds the register.
        address predicted = vm.computeCreateAddress(address(this), vm.getNonce(address(this)) + 1);
        rep = new ReputationRegister(predicted, 0.2e18);
        pool = new StakePool(address(attestation), admin, 10_000, 7 days, c, 2, address(rep));
        assertEq(rep.recorder(), address(pool), "recorder must be the pool");

        vm.deal(operator, 1_000 ether);
        vm.deal(claimant, 1 ether);
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

    function _cycle(uint256 confidence, bool upheld) internal {
        bytes32 attId = _attest(confidence);
        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);
        _resolve(dispId, upheld);
    }

    function test_resolutionRecordsReputationForTheOperator() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();

        assertFalse(rep.hasHistory(operator), "no history before any dispute");
        _cycle(0.99e18, false);

        (uint256 score, uint256 n,) = rep.reputationOf(operator);
        assertEq(n, 1);
        assertEq(score, 0.9801e18, "score must equal the Brier score of the resolution");
        assertTrue(rep.hasHistory(operator));
    }

    function test_reputationAndSlashComeFromTheSameConfidence() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();

        bytes32 attId = _attest(0.8e18);
        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);
        _resolve(dispId, false);

        (,,, uint256 slashed) = pool.disputes(dispId);
        (uint256 score,,) = rep.reputationOf(operator);
        // slash = 100 ether * (0.8 - 0)^2 = 64 ether; score = 0.64.
        assertEq(slashed, 64 ether);
        assertEq(score, 0.64e18, "the score is the same squared error the slash used");
    }

    function test_repeatedResolutionsAccumulate() public {
        vm.prank(operator);
        pool.stake{value: 500 ether}();
        _cycle(0.9e18, true);
        _cycle(0.9e18, true);
        _cycle(0.9e18, true);
        (, uint256 n,) = rep.reputationOf(operator);
        assertEq(n, 3);
    }

    function test_unresolvedDisputeDoesNotTouchReputation() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        bytes32 attId = _attest(0.99e18);
        vm.prank(claimant);
        bytes32 dispId = pool.openDispute(attId);

        vm.prank(r1);
        pool.resolveDispute(dispId, false); // one vote, below threshold

        assertFalse(rep.hasHistory(operator),
            "reputation must move only when a dispute actually resolves");
    }

    /// @notice The tier boundary, made executable.
    ///
    /// A colluding committee can manufacture whatever reputation it likes.
    /// Two resolvers declare a confident, genuinely correct decision
    /// overturned and the operator's calibration record is ruined, with no
    /// recourse. The score is exactly as trustworthy as the committee beneath
    /// it, and this test exists so that nobody can describe it as more.
    function test_tierBoundary_colludingCommitteeCanManufactureReputation() public {
        vm.prank(operator);
        pool.stake{value: 100 ether}();
        _cycle(0.99e18, false); // in truth correct; the committee says otherwise

        (uint256 score,,) = rep.reputationOf(operator);
        assertEq(score, 0.9801e18,
            "reputation inherits the trust level of the dispute layer, no better");
    }

    /// @notice A pool deployed without a register still slashes identically.
    /// @dev Reputation must never become load-bearing for the penalty.
    function test_poolWithoutRegisterSlashesIdentically() public {
        address[] memory c = new address[](3);
        c[0] = r1; c[1] = r2; c[2] = r3;
        StakePool bare = new StakePool(address(attestation), admin, 10_000, 7 days, c, 2, address(0));

        vm.prank(operator);
        bare.stake{value: 100 ether}();
        bytes32 attId = _attest(0.8e18);
        vm.prank(claimant);
        bytes32 dispId = bare.openDispute(attId);
        vm.prank(r1);
        bare.resolveDispute(dispId, false);
        vm.prank(r2);
        bare.resolveDispute(dispId, false);

        (,,, uint256 slashed) = bare.disputes(dispId);
        assertEq(slashed, 64 ether, "slash is unchanged when no register is attached");
    }
}
