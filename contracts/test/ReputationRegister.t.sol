// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {ReputationRegister} from "../src/ReputationRegister.sol";
import {BrierMath} from "../src/BrierMath.sol";
import {Attestation, IVerifier} from "../src/Attestation.sol";
import {StakePool} from "../src/StakePool.sol";

/// @notice Phase F: the reputation EMA, and the ways an operator might try to
///         game it.
///
/// The gaming tests matter more than the arithmetic ones. A reputation score
/// is only worth having if an operator cannot manufacture a good one, and the
/// obvious attack -- dispute your own decisions, on cases you know you got
/// right, until the average looks excellent -- is checked explicitly.
contract ReputationRegisterTest is Test {
    uint256 constant WAD = 1e18;
    uint256 constant ALPHA = 0.2e18; // 20% weight on each new sample

    ReputationRegister rep;
    address pool = address(0xB001);
    address operator = address(0x0BE7A704);

    function setUp() public {
        rep = new ReputationRegister(pool, ALPHA);
    }

    function _record(uint256 confidence, bool upheld) internal {
        vm.prank(pool);
        rep.record(operator, confidence, upheld);
    }

    // ---------------------------------------------------------------
    // Access control: the whole point of the recorder being immutable.
    // ---------------------------------------------------------------

    function test_onlyRecorderCanRecord() public {
        vm.prank(operator);
        vm.expectRevert(abi.encodeWithSelector(ReputationRegister.NotRecorder.selector, operator));
        rep.record(operator, 0.9e18, true);
    }

    function test_operatorCannotSelfReportPerfectScores() public {
        // The direct attack: call record() yourself with a flawless sample.
        vm.prank(operator);
        vm.expectRevert();
        rep.record(operator, WAD, true);
        assertFalse(rep.hasHistory(operator), "no history may be created by the operator");
    }

    function test_constructorRejectsZeroRecorder() public {
        vm.expectRevert(ReputationRegister.ZeroRecorder.selector);
        new ReputationRegister(address(0), ALPHA);
    }

    function test_constructorRejectsOutOfRangeAlpha() public {
        vm.expectRevert(abi.encodeWithSelector(ReputationRegister.AlphaOutOfRange.selector, uint256(0)));
        new ReputationRegister(pool, 0);
        vm.expectRevert(abi.encodeWithSelector(ReputationRegister.AlphaOutOfRange.selector, WAD + 1));
        new ReputationRegister(pool, WAD + 1);
    }

    // ---------------------------------------------------------------
    // The EMA itself.
    // ---------------------------------------------------------------

    function test_firstSampleSeedsTheEmaOutright() public {
        // Confident (0.9) and WRONG -> Brier = 0.81.
        _record(0.9e18, false);
        (uint256 score, uint256 n,) = rep.reputationOf(operator);
        assertEq(score, 0.81e18, "first sample must seed, not blend toward zero");
        assertEq(n, 1);
    }

    function test_secondSampleBlendsAtAlpha() public {
        _record(0.9e18, false);           // 0.81
        _record(0.9e18, true);            // 0.01
        // 0.2*0.01 + 0.8*0.81 = 0.002 + 0.648 = 0.650
        (uint256 score, uint256 n,) = rep.reputationOf(operator);
        assertEq(score, 0.65e18);
        assertEq(n, 2);
    }

    function test_perfectlyCalibratedConfidentOperatorConvergesLow() public {
        for (uint256 i = 0; i < 40; i++) {
            _record(0.99e18, true); // Brier = 0.0001
        }
        (uint256 score,,) = rep.reputationOf(operator);
        assertLt(score, 0.001e18, "a consistently correct confident operator scores near zero");
    }

    function test_confidentlyWrongOperatorConvergesHigh() public {
        for (uint256 i = 0; i < 40; i++) {
            _record(0.99e18, false); // Brier = 0.9801
        }
        (uint256 score,,) = rep.reputationOf(operator);
        assertGt(score, 0.9e18, "a consistently confidently-wrong operator scores near one");
    }

    function test_uncertainOperatorConvergesToIrreducibleFloor() public {
        // Reporting 0.5 and being right half the time: Brier is 0.25 either
        // way, so the EMA sits at 0.25. This is p(1-p) at p=0.5 -- the
        // irreducible term from the proposal's section 3.2, showing up on
        // chain. Honest uncertainty is not free, and should not look free.
        for (uint256 i = 0; i < 30; i++) {
            _record(0.5e18, i % 2 == 0);
        }
        (uint256 score,,) = rep.reputationOf(operator);
        assertApproxEqAbs(score, 0.25e18, 0.001e18);
    }

    function test_scoreMatchesBrierMathExactly() public {
        // The score and the slash must be driven by the same arithmetic, or
        // an operator could be penalised on one basis and rated on another.
        _record(0.73e18, false);
        (uint256 score,,) = rep.reputationOf(operator);
        assertEq(score, BrierMath.squaredError(0.73e18, false));
    }

    // ---------------------------------------------------------------
    // Gaming.
    // ---------------------------------------------------------------

    function test_selfDisputingCorrectDecisionsStillCostsTheIrreducibleTerm() public {
        // An operator that farms disputes on decisions it KNOWS are correct,
        // reporting honest 0.85 confidence, cannot drive its score to zero:
        // each sample contributes (0.85-1)^2 = 0.0225.
        for (uint256 i = 0; i < 50; i++) {
            _record(0.85e18, true);
        }
        (uint256 score,,) = rep.reputationOf(operator);
        assertApproxEqAbs(score, 0.0225e18, 0.0005e18);
        assertGt(score, 0, "reputation farming cannot reach a zero score");
    }

    function test_historyCannotBeErasedByFurtherSamples() public {
        _record(0.99e18, false);              // catastrophic
        (uint256 bad,,) = rep.reputationOf(operator);
        for (uint256 i = 0; i < 5; i++) {
            _record(0.99e18, true);           // then a clean run
        }
        (uint256 after_, uint256 n,) = rep.reputationOf(operator);
        assertLt(after_, bad, "recent good behaviour must improve the score");
        assertGt(after_, 0.2e18, "but five samples cannot erase a 0.98 event at alpha=0.2");
        assertEq(n, 6, "sample count is monotonic and never resets");
    }

    // ---------------------------------------------------------------
    // The "no history" trap.
    // ---------------------------------------------------------------

    function test_freshOperatorHasZeroScoreButNoHistory() public view {
        (uint256 score, uint256 n,) = rep.reputationOf(address(0xFEED));
        assertEq(score, 0);
        assertEq(n, 0);
        // A zero score with no samples must never be read as good calibration.
        assertFalse(rep.hasHistory(address(0xFEED)));
    }

    function test_sampleCountAndTimestampAreRecorded() public {
        vm.warp(1_700_000_000);
        _record(0.6e18, true);
        (, uint256 n, uint256 at) = rep.reputationOf(operator);
        assertEq(n, 1);
        assertEq(at, 1_700_000_000);
    }

    // ---------------------------------------------------------------
    // Bounds.
    // ---------------------------------------------------------------

    function testFuzz_scoreAlwaysStaysWithinUnitInterval(uint256 c, bool upheld) public {
        c = bound(c, 0, WAD);
        _record(c, upheld);
        (uint256 score,,) = rep.reputationOf(operator);
        assertLe(score, WAD, "a Brier score can never exceed 1");
    }

    function testFuzz_emaIsBoundedByTheSamplesItSaw(uint256 c1, uint256 c2) public {
        c1 = bound(c1, 0, WAD);
        c2 = bound(c2, 0, WAD);
        uint256 s1 = BrierMath.squaredError(c1, false);
        uint256 s2 = BrierMath.squaredError(c2, false);
        _record(c1, false);
        _record(c2, false);
        (uint256 score,,) = rep.reputationOf(operator);
        uint256 lo = s1 < s2 ? s1 : s2;
        uint256 hi = s1 < s2 ? s2 : s1;
        assertGe(score + 1, lo);
        assertLe(score, hi + 1);
    }
}
