// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test, Vm} from "forge-std/Test.sol";
import {ERC8004ReputationAdapter, IERC8004Reputation} from "../src/ERC8004ReputationAdapter.sol";
import {ReputationRegister} from "../src/ReputationRegister.sol";
import {BrierMath} from "../src/BrierMath.sol";
import {Attestation, IVerifier} from "../src/Attestation.sol";
import {StakePool} from "../src/StakePool.sol";

/// @notice A minimal stand-in for the ERC-8004 Reputation Registry.
/// @dev Records what it was called with so the tests can assert on the exact
///      encoding, and can be told to revert on demand to exercise the failure
///      path. The real registry is not vendored; what is being tested here is
///      Brier's side of the call, including its behaviour when the far side
///      misbehaves.
contract MockERC8004Registry is IERC8004Reputation {
    struct Call {
        uint256 agentId;
        int128 value;
        uint8 valueDecimals;
        string tag1;
        string tag2;
    }

    Call[] public calls;
    bool public shouldRevert;
    bool public shouldConsumeAllGas;

    function setShouldRevert(bool v) external {
        shouldRevert = v;
    }

    function setShouldConsumeAllGas(bool v) external {
        shouldConsumeAllGas = v;
    }

    function callCount() external view returns (uint256) {
        return calls.length;
    }

    function giveFeedback(
        uint256 agentId,
        int128 value,
        uint8 valueDecimals,
        string calldata tag1,
        string calldata tag2,
        string calldata,
        string calldata,
        bytes32
    ) external override {
        if (shouldConsumeAllGas) {
            // Burn everything forwarded. Exercises the 63/64 rule: the caller
            // must retain enough gas to catch and finish.
            while (true) {
                assembly {
                    sstore(gas(), gas())
                }
            }
        }
        if (shouldRevert) revert("registry down");
        calls.push(Call(agentId, value, valueDecimals, tag1, tag2));
    }
}

/// @notice Task 1: mirroring Brier's calibration EMA into an ERC-8004 registry.
///
/// The tests that matter here are not the happy path. They are:
///   1. the mirrored value carries the INVERTED sign convention, because
///      publishing a loss where readers expect a rating would rank the worst
///      operators highest;
///   2. a dead or hostile registry cannot halt dispute resolution, because that
///      would hand a liveness veto over slashing to a contract outside this
///      system's trust boundary;
///   3. after a failed mirror the authoritative EMA is still correct, since the
///      whole justification for swallowing the failure is that nothing in
///      Brier reads the mirror.
contract ERC8004ReputationAdapterTest is Test {
    uint256 constant WAD = 1e18;
    uint256 constant ALPHA = 0.2e18;
    uint256 constant AGENT_ID = 8004;

    MockERC8004Registry registry;
    ERC8004ReputationAdapter adapter;

    address pool = address(0xB001);
    address operator = address(0x0BE7A704);

    event MirroredToERC8004(address indexed operator, uint256 agentId, int128 value);
    event MirrorFailed(address indexed operator, uint256 agentId, bytes reason);

    function setUp() public {
        registry = new MockERC8004Registry();
        adapter = new ERC8004ReputationAdapter(pool, ALPHA, address(registry), AGENT_ID);
    }

    function _record(uint256 confidence, bool upheld) internal {
        vm.prank(pool);
        adapter.record(operator, confidence, upheld);
    }

    // ---------------------------------------------------------------
    // Construction
    // ---------------------------------------------------------------

    function test_constructorRejectsZeroRegistry() public {
        vm.expectRevert(ERC8004ReputationAdapter.ZeroRegistry.selector);
        new ERC8004ReputationAdapter(pool, ALPHA, address(0), AGENT_ID);
    }

    function test_inheritsRecorderAndAlpha() public view {
        assertEq(adapter.recorder(), pool);
        assertEq(adapter.alpha(), ALPHA);
        assertEq(adapter.agentId(), AGENT_ID);
        assertEq(adapter.VALUE_DECIMALS(), 18);
    }

    // ---------------------------------------------------------------
    // Access control survives the override. If the override had dropped
    // onlyRecorder, anyone could write their own reputation -- and it would
    // still have looked wired up correctly from the outside.
    // ---------------------------------------------------------------

    function test_onlyRecorderCanRecord() public {
        vm.prank(operator);
        vm.expectRevert(
            abi.encodeWithSelector(ReputationRegister.NotRecorder.selector, operator)
        );
        adapter.record(operator, 0.9e18, true);
        assertEq(registry.callCount(), 0, "unauthorised call must not reach the mirror");
    }

    // ---------------------------------------------------------------
    // Both registries are written by one resolution.
    // ---------------------------------------------------------------

    function test_recordWritesBothRegisters() public {
        _record(0.9e18, true);

        (uint256 score, uint256 samples,) = adapter.reputationOf(operator);
        assertEq(samples, 1);
        // Upheld at 0.9 confidence: (1 - 0.9)^2 = 0.01. First sample seeds.
        assertEq(score, 0.01e18);

        assertEq(registry.callCount(), 1, "mirror must have been written");
        (uint256 agentId, int128 value, uint8 decimals,,) = registry.calls(0);
        assertEq(agentId, AGENT_ID);
        assertEq(decimals, 18);
        // 1 - 0.01 = 0.99, higher-is-better.
        assertEq(value, int128(uint128(0.99e18)));
    }

    /// @dev The sign convention is the single most dangerous detail in this
    ///      adapter: a Brier score is a loss and ERC-8004 feedback reads as a
    ///      rating. Publishing raw would rank a maximally overconfident wrong
    ///      operator at the top. Pinned explicitly at both extremes.
    function test_mirroredValueIsInvertedSoHigherIsBetter() public {
        // Confidently wrong: Brier score 1.0, the worst possible.
        _record(WAD, false);
        (uint256 badScore,,) = adapter.reputationOf(operator);
        assertEq(badScore, WAD, "worst case is a Brier score of 1");

        (, int128 badValue,,,) = registry.calls(0);
        assertEq(badValue, 0, "worst operator must publish the LOWEST rating");

        // A different operator, confidently right: Brier score 0, the best.
        address good = address(0x600D);
        vm.prank(pool);
        adapter.record(good, WAD, true);
        (uint256 goodScore,,) = adapter.reputationOf(good);
        assertEq(goodScore, 0, "best case is a Brier score of 0");

        (, int128 goodValue,,,) = registry.calls(1);
        assertEq(goodValue, int128(uint128(WAD)), "best operator must publish the HIGHEST rating");

        assertGt(goodValue, badValue, "the ordering readers rely on");
    }

    function test_mirrorTagsNameTheConvention() public {
        _record(0.9e18, true);
        (,,, string memory tag1, string memory tag2) = registry.calls(0);
        assertEq(tag1, "brier-calibration");
        // The convention has to be discoverable on-chain, not only in a comment.
        assertEq(tag2, "one-minus-brier-higher-better");
    }

    function test_mirroredValueTracksTheEmaAcrossSamples() public {
        _record(0.9e18, true);   // sample 0.01, seeds
        _record(0.2e18, false);  // sample 0.04

        (uint256 score,,) = adapter.reputationOf(operator);
        uint256 expected = (ALPHA * 0.04e18 + (WAD - ALPHA) * 0.01e18) / WAD;
        assertEq(score, expected);

        // The mirror must publish the same number this contract reports, not a
        // separately recomputed one that could drift.
        (, int128 value,,,) = registry.calls(1);
        assertEq(value, int128(uint128(WAD - expected)));
    }

    function test_emitsMirroredEventOnSuccess() public {
        vm.expectEmit(true, false, false, true);
        emit MirroredToERC8004(operator, AGENT_ID, int128(uint128(0.99e18)));
        _record(0.9e18, true);
    }

    // ---------------------------------------------------------------
    // The failure mode. This is the design decision the header comment
    // justifies, so it gets tested rather than asserted.
    // ---------------------------------------------------------------

    function test_registryRevertDoesNotRevertRecord() public {
        registry.setShouldRevert(true);

        _record(0.9e18, true); // must not revert

        (uint256 score, uint256 samples,) = adapter.reputationOf(operator);
        assertEq(samples, 1, "the authoritative EMA still recorded the sample");
        assertEq(score, 0.01e18, "and recorded it correctly");
        assertEq(registry.callCount(), 0, "the mirror did not take the write");
    }

    function test_registryRevertEmitsMirrorFailed() public {
        registry.setShouldRevert(true);
        vm.recordLogs();
        _record(0.9e18, true);

        // MirrorFailed must be observable: a silent divergence between the
        // authoritative score and the mirror would be undetectable off-chain.
        Vm.Log[] memory logs = vm.getRecordedLogs();
        bool found;
        for (uint256 i = 0; i < logs.length; i++) {
            if (logs[i].topics[0] == MirrorFailed.selector) found = true;
        }
        assertTrue(found, "a divergence must be individually visible on-chain");
    }

    function test_emaStaysCorrectAcrossAMirrorOutage() public {
        _record(0.9e18, true); // mirrored

        registry.setShouldRevert(true);
        _record(0.2e18, false); // dropped by the mirror
        registry.setShouldRevert(false);

        _record(0.9e18, true); // mirrored again

        // The whole justification for swallowing mirror failures is that
        // nothing in Brier reads the mirror. That is only safe if the
        // authoritative EMA is untouched by the outage.
        uint256 s1 = 0.01e18;
        uint256 s2 = (ALPHA * 0.04e18 + (WAD - ALPHA) * s1) / WAD;
        uint256 s3 = (ALPHA * 0.01e18 + (WAD - ALPHA) * s2) / WAD;

        (uint256 score, uint256 samples,) = adapter.reputationOf(operator);
        assertEq(samples, 3, "every sample counted, including during the outage");
        assertEq(score, s3, "EMA unaffected by the mirror being down");

        // The mirror skipped one and resynced on the next success -- stale in
        // between, self-healing after, exactly as documented.
        assertEq(registry.callCount(), 2);
        (, int128 latest,,,) = registry.calls(1);
        assertEq(latest, int128(uint128(WAD - s3)));
    }

    function test_gasGriefingRegistryCannotHaltRecording() public {
        registry.setShouldConsumeAllGas(true);

        // A registry that burns every forwarded wei of gas leaves 1/64 to the
        // caller under EIP-150, which must be enough to catch and finish.
        _record(0.9e18, true);

        (, uint256 samples,) = adapter.reputationOf(operator);
        assertEq(samples, 1, "a gas-burning registry must not halt recording");
    }

    // ---------------------------------------------------------------
    // End-to-end through StakePool: the adapter must be substitutable for a
    // plain ReputationRegister wherever one is wired, or the integration is
    // theoretical.
    // ---------------------------------------------------------------

    function test_stakePoolResolutionWritesThroughAdapter() public {
        AcceptingVerifier verifier = new AcceptingVerifier();
        Attestation att = new Attestation(address(verifier));

        address admin = address(0xA11CE);
        address[] memory resolvers = new address[](3);
        resolvers[0] = address(0xE51);
        resolvers[1] = address(0xE52);
        resolvers[2] = address(0xE53);

        // The pool address is not known until after construction, but the
        // adapter's recorder is immutable -- so precompute it, exactly as a
        // real deployment must.
        address predictedPool = vm.computeCreateAddress(address(this), vm.getNonce(address(this)) + 1);
        ERC8004ReputationAdapter wired =
            new ERC8004ReputationAdapter(predictedPool, ALPHA, address(registry), AGENT_ID);

        StakePool pool_ = new StakePool(
            address(att), admin, 10_000, 7 days, resolvers, 2, address(wired), address(0)
        );
        assertEq(address(pool_), predictedPool, "address prediction held");

        address op = address(0x0FF1);
        vm.deal(op, 10 ether);
        vm.prank(op);
        pool_.stake{value: 10 ether}();

        // The operator attests its own decision: attest() keys on msg.sender.
        uint256[] memory instances = new uint256[](1);
        instances[0] = 0.9e18;
        vm.prank(op);
        bytes32 attId = att.attest(
            keccak256("decision"), keccak256("shap"), 0.9e18, int256(1),
            bytes32("m"), bytes("proof"), instances
        );

        address claimant = address(0xC1A1);
        vm.prank(claimant);
        bytes32 disputeId = pool_.openDispute(attId);

        // 2-of-3 committee, both voting to overturn.
        vm.prank(resolvers[0]);
        pool_.resolveDispute(disputeId, false);
        vm.prank(resolvers[1]);
        pool_.resolveDispute(disputeId, false);

        // Overturned at 0.9 confidence: Brier score (0.9 - 0)^2 = 0.81.
        (uint256 score, uint256 samples,) = wired.reputationOf(op);
        assertEq(samples, 1, "resolution recorded through the adapter");
        assertEq(score, 0.81e18);

        assertEq(registry.callCount(), 1, "and mirrored to ERC-8004");
        (, int128 value,,,) = registry.calls(0);
        assertEq(value, int128(uint128(WAD - 0.81e18)), "confidently wrong publishes a low rating");
    }
}

contract AcceptingVerifier is IVerifier {
    function verifyProof(bytes calldata, uint256[] calldata) external pure returns (bool) {
        return true;
    }
}
