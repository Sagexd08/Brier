// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {Halo2Verifier} from "../src/VerifierTemperature.sol";
import {Attestation} from "../src/Attestation.sol";

/// @notice Verifies a REAL EZKL proof on-chain and measures the actual gas.
///
/// This is the test that turns "we generated a proof" into "the chain accepts
/// it". The proof fixture is produced by scripts/31_zk_prove.py from the
/// trained temperature calibration head; it is not hand-written.
contract VerifierTest is Test {
    Halo2Verifier verifier;

    bytes proof;
    uint256[] instances;

    function setUp() public {
        verifier = new Halo2Verifier();

        string memory root = vm.projectRoot();
        string memory path = string.concat(root, "/test/fixtures/temperature_proof.json");
        string memory json = vm.readFile(path);

        proof = vm.parseJsonBytes(json, ".proof_hex");
        instances = vm.parseJsonUintArray(json, ".instances");
    }

    /// The headline claim: a real proof of the calibration head verifies
    /// on-chain.
    function test_realProofVerifiesOnChain() public {
        uint256 gasBefore = gasleft();
        bool ok = verifier.verifyProof(proof, instances);
        uint256 gasUsed = gasBefore - gasleft();

        assertTrue(ok, "the EZKL proof must verify on-chain");
        console.log("VERIFY_GAS", gasUsed);
        console.log("PROOF_BYTES", proof.length);
        console.log("NUM_INSTANCES", instances.length);
    }

    /// Soundness on-chain, not just in the EZKL library: a tampered public
    /// output must not verify. Without this, the on-chain verifier could be
    /// accepting everything and the test above would still pass.
    function test_tamperedInstanceIsRejectedOnChain() public {
        uint256[] memory bad = new uint256[](instances.length);
        for (uint256 i = 0; i < instances.length; i++) {
            bad[i] = instances[i];
        }
        bad[bad.length - 1] = bad[bad.length - 1] ^ 1; // flip one bit

        // The generated verifier either returns false or reverts. Both are
        // acceptable rejections; silently returning true is not.
        try verifier.verifyProof(proof, bad) returns (bool ok) {
            assertFalse(ok, "tampered public output must not verify on-chain");
        } catch {
            assertTrue(true);
        }
    }

    function test_tamperedProofIsRejectedOnChain() public {
        bytes memory bad = proof;
        bad[bad.length - 1] = bytes1(uint8(bad[bad.length - 1]) ^ 0xFF);

        try verifier.verifyProof(bad, instances) returns (bool ok) {
            assertFalse(ok, "tampered proof must not verify on-chain");
        } catch {
            assertTrue(true);
        }
    }

    /// End-to-end: the Attestation contract accepts a decision only when the
    /// real verifier accepts the real proof.
    function test_attestationAcceptsRealProof() public {
        Attestation att = new Attestation(address(verifier));

        uint256 gasBefore = gasleft();
        bytes32 id = att.attest(
            keccak256("loan-application-42"),
            keccak256("shap-top5-vector"),
            0.71e18,
            int256(-7_908_813_476_562_500_000), // -7.9088... in WAD
            bytes32("brier-mvp-v1"),
            proof,
            instances
        );
        uint256 gasUsed = gasBefore - gasleft();

        console.log("ATTEST_WITH_PROOF_GAS", gasUsed);
        assertTrue(att.exists(id));

        Attestation.Record memory r = att.get(id);
        assertTrue(r.proofVerified);
        assertEq(r.confidence, 0.71e18);
    }
}
