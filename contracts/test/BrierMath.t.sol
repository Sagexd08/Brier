// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {BrierMath} from "../src/BrierMath.sol";

contract BrierMathTest is Test {
    uint256 constant WAD = 1e18;
    uint256 constant STAKE = 100 ether;

    // ---------------------------------------------------------------
    // Known-answer cases from the build spec
    // ---------------------------------------------------------------

    /// confidence = 0.5 -> squared error 0.25 regardless of outcome.
    /// The "hedge everything" case: never cheap, never catastrophic.
    function test_confidenceHalf_isSymmetric() public pure {
        uint256 right = BrierMath.squaredError(WAD / 2, true);
        uint256 wrong = BrierMath.squaredError(WAD / 2, false);
        assertEq(right, wrong, "0.5 must cost the same either way");
        assertEq(right, 0.25e18, "(0.5-1)^2 = 0.25");
    }

    /// confidence = 0.99 and WRONG -> near-maximal penalty.
    function test_confident_and_wrong_is_severe() public pure {
        uint256 sq = BrierMath.squaredError(0.99e18, false);
        assertEq(sq, 0.9801e18, "(0.99-0)^2 = 0.9801");
        assertEq(BrierMath.rawSlash(STAKE, 0.99e18, false), 98.01 ether);
    }

    /// confidence = 0.99 and RIGHT -> almost nothing.
    function test_confident_and_right_is_cheap() public pure {
        assertEq(BrierMath.squaredError(0.99e18, true), 0.0001e18, "(0.99-1)^2 = 0.0001");
        assertEq(BrierMath.rawSlash(STAKE, 0.99e18, true), 0.01 ether);
    }

    /// Uncertain and wrong must cost far less than confident and wrong.
    function test_uncertain_and_wrong_is_mild() public pure {
        uint256 uncertain = BrierMath.rawSlash(STAKE, 0.55e18, false);
        uint256 confident = BrierMath.rawSlash(STAKE, 0.99e18, false);
        assertLt(uncertain, confident);
        assertEq(uncertain, 30.25 ether, "(0.55)^2 = 0.3025");
    }

    function test_extremes() public pure {
        assertEq(BrierMath.squaredError(0, false), 0, "0 confidence, wrong -> 0");
        assertEq(BrierMath.squaredError(WAD, true), 0, "1 confidence, right -> 0");
        assertEq(BrierMath.squaredError(WAD, false), WAD, "1 confidence, wrong -> max");
        assertEq(BrierMath.squaredError(0, true), WAD, "0 confidence, right -> max");
    }

    // ---------------------------------------------------------------
    // THE property: slash is monotonic in miscalibration
    // ---------------------------------------------------------------

    /// As confidence rises while the decision is WRONG, the slash must rise.
    /// If this failed, an operator could reduce its penalty by claiming MORE
    /// confidence in a wrong answer and the mechanism would be worthless.
    function test_monotonic_in_miscalibration_whenWrong() public pure {
        uint256 prev = 0;
        for (uint256 c = 0; c <= 100; c++) {
            uint256 conf = (c * WAD) / 100;
            uint256 s = BrierMath.rawSlash(STAKE, conf, false);
            if (c > 0) assertGt(s, prev, "slash must strictly increase with confidence when wrong");
            prev = s;
        }
    }

    /// As confidence rises while the decision is RIGHT, the slash must fall.
    function test_monotonic_in_miscalibration_whenRight() public pure {
        uint256 prev = type(uint256).max;
        for (uint256 c = 0; c <= 100; c++) {
            uint256 conf = (c * WAD) / 100;
            uint256 s = BrierMath.rawSlash(STAKE, conf, true);
            assertLt(s, prev, "slash must strictly decrease with confidence when right");
            prev = s;
        }
    }

    function testFuzz_monotonic_whenWrong(uint256 a, uint256 b) public pure {
        a = bound(a, 0, WAD);
        b = bound(b, 0, WAD);
        if (a > b) (a, b) = (b, a);
        assertLe(BrierMath.rawSlash(STAKE, a, false), BrierMath.rawSlash(STAKE, b, false));
    }

    function testFuzz_monotonic_whenRight(uint256 a, uint256 b) public pure {
        a = bound(a, 0, WAD);
        b = bound(b, 0, WAD);
        if (a > b) (a, b) = (b, a);
        assertGe(BrierMath.rawSlash(STAKE, a, true), BrierMath.rawSlash(STAKE, b, true));
    }

    // ---------------------------------------------------------------
    // Properness: honest reporting minimises expected loss
    // ---------------------------------------------------------------

    /// The economic claim. If the true probability of being right is p, the
    /// expected slash must be minimised by REPORTING p.
    function test_properScoringRule_honestyIsOptimal() public pure {
        uint256 p = 0.70e18;
        uint256 best = type(uint256).max;
        uint256 bestReport = 0;

        for (uint256 c = 0; c <= 100; c++) {
            uint256 report = (c * WAD) / 100;
            uint256 expected = (p * BrierMath.rawSlash(STAKE, report, true)) / WAD
                + ((WAD - p) * BrierMath.rawSlash(STAKE, report, false)) / WAD;
            if (expected < best) {
                best = expected;
                bestReport = report;
            }
        }
        assertEq(bestReport, p, "expected loss must be minimised at the true probability");
    }

    /// Same claim at a second point, to rule out a coincidence at p=0.7.
    function test_properScoringRule_honestyIsOptimal_atLowP() public pure {
        uint256 p = 0.30e18;
        uint256 best = type(uint256).max;
        uint256 bestReport = 0;
        for (uint256 c = 0; c <= 100; c++) {
            uint256 report = (c * WAD) / 100;
            uint256 expected = (p * BrierMath.rawSlash(STAKE, report, true)) / WAD
                + ((WAD - p) * BrierMath.rawSlash(STAKE, report, false)) / WAD;
            if (expected < best) {
                best = expected;
                bestReport = report;
            }
        }
        assertEq(bestReport, p, "honest reporting must win at p=0.3 too");
    }

    // ---------------------------------------------------------------
    // The cap is a CORRECTNESS parameter, not a safety knob.
    //
    // maxSlashBps looks like a prudential limit -- lower it and the
    // protocol risks less per decision. It is not. Capping a proper
    // scoring rule below 100% destroys the property the whole mechanism
    // rests on, and destroys it in the worst possible direction: the
    // expected-loss minimiser jumps from the operator's true belief to
    // the nearest boundary, so a capped protocol pays operators to report
    // maximal confidence.
    //
    // Truthful reporting survives iff cap >= max(p, 1-p). The tests below
    // pin both halves of that, so nobody can lower the cap "to be safe"
    // without a red suite.
    // ---------------------------------------------------------------

    /// Search the report grid under a cap and return the argmin.
    function _bestReportUnderCap(uint256 p, uint256 capBps)
        internal
        pure
        returns (uint256 bestReport)
    {
        uint256 best = type(uint256).max;
        for (uint256 c = 0; c <= 100; c++) {
            uint256 report = (c * WAD) / 100;
            uint256 expected =
                (p * BrierMath.slashAmount(STAKE, report, true, capBps)) / WAD
                + ((WAD - p) * BrierMath.slashAmount(STAKE, report, false, capBps)) / WAD;
            if (expected < best) {
                best = expected;
                bestReport = report;
            }
        }
    }

    /// At the deployed cap of 100% the rule is proper, as Proposition 1 states.
    function test_cap_atOneHundredPercent_preservesProperness() public pure {
        assertEq(_bestReportUnderCap(0.30e18, 10_000), 0.30e18);
        assertEq(_bestReportUnderCap(0.70e18, 10_000), 0.70e18);
        assertEq(_bestReportUnderCap(0.05e18, 10_000), 0.05e18);
        assertEq(_bestReportUnderCap(0.95e18, 10_000), 0.95e18);
    }

    /// A 50% cap pays the operator to report maximal confidence, in whichever
    /// direction it privately leans. This is the failure the cap introduces,
    /// and it is the opposite of what the mechanism is for.
    function test_cap_belowHalf_rewardsMaximalOverconfidence() public pure {
        assertEq(_bestReportUnderCap(0.30e18, 5_000), 0,
            "under a 50% cap an operator leaning low reports 0, not 0.30");
        assertEq(_bestReportUnderCap(0.70e18, 5_000), WAD,
            "under a 50% cap an operator leaning high reports 1, not 0.70");
    }

    /// The boundary is exact: properness holds precisely on p in [1-k, k].
    /// At cap 75% the truth wins at p = 0.30 and 0.70, and loses outside.
    function test_cap_propernessHoldsExactlyOnTheInterval() public pure {
        assertEq(_bestReportUnderCap(0.30e18, 7_500), 0.30e18, "inside: truth wins");
        assertEq(_bestReportUnderCap(0.70e18, 7_500), 0.70e18, "inside: truth wins");
        assertEq(_bestReportUnderCap(0.10e18, 7_500), 0, "outside: boundary wins");
        assertEq(_bestReportUnderCap(0.90e18, 7_500), WAD, "outside: boundary wins");
    }

    // ---------------------------------------------------------------
    // Cap behaviour
    // ---------------------------------------------------------------

    function test_capLimitsSlash() public pure {
        uint256 capped = BrierMath.slashAmount(STAKE, 0.99e18, false, 5_000);
        assertEq(capped, STAKE / 2, "must clamp to the cap");
    }

    function test_capNotBindingBelowThreshold() public pure {
        assertEq(BrierMath.slashAmount(STAKE, 0.55e18, false, 5_000), 30.25 ether);
    }

    function test_zeroCapMeansNoSlash() public pure {
        assertEq(BrierMath.slashAmount(STAKE, WAD, false, 0), 0);
    }

    // ---------------------------------------------------------------
    // Precision and overflow
    // ---------------------------------------------------------------

    /// Truncation is bounded and always rounds DOWN, in the favour of the
    /// operator. Documented rather than accidental.
    function test_precision_smallestConfidenceUnit() public pure {
        assertEq(BrierMath.squaredError(1, false), 0, "sub-WAD^2 truncates to zero");
    }

    function test_noOverflow_atAbsurdStake() public pure {
        uint256 huge = 1e30;
        assertEq(BrierMath.rawSlash(huge, WAD, false), huge);
    }

    function testFuzz_slashNeverExceedsStake(uint256 stakeAmt, uint256 conf, bool right)
        public
        pure
    {
        stakeAmt = bound(stakeAmt, 0, 1e30);
        conf = bound(conf, 0, WAD);
        assertLe(BrierMath.rawSlash(stakeAmt, conf, right), stakeAmt);
    }

    function testFuzz_cappedSlashNeverExceedsCap(uint256 conf, uint256 capBps) public pure {
        conf = bound(conf, 0, WAD);
        capBps = bound(capBps, 0, 10_000);
        assertLe(BrierMath.slashAmount(STAKE, conf, false, capBps), (STAKE * capBps) / 10_000);
    }

    // ---------------------------------------------------------------
    // Input validation
    // ---------------------------------------------------------------

    function test_revertsOnConfidenceAboveOne() public {
        vm.expectRevert(abi.encodeWithSelector(BrierMath.ConfidenceOutOfRange.selector, WAD + 1));
        this.callSquaredError(WAD + 1, true);
    }

    function test_revertsOnCapAboveOneHundredPercent() public {
        vm.expectRevert(abi.encodeWithSelector(BrierMath.CapOutOfRange.selector, uint256(10_001)));
        this.callSlashAmount(STAKE, WAD / 2, false, 10_001);
    }

    // External wrappers so vm.expectRevert sees a real call boundary.
    function callSquaredError(uint256 c, bool ok) external pure returns (uint256) {
        return BrierMath.squaredError(c, ok);
    }

    function callSlashAmount(uint256 s, uint256 c, bool ok, uint256 cap)
        external
        pure
        returns (uint256)
    {
        return BrierMath.slashAmount(s, c, ok, cap);
    }
}
