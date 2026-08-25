// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {ModelRegistry} from "../src/ModelRegistry.sol";

/// @notice Phase G: the model-version registry.
///
/// The guarantee under test is narrow and worth naming exactly: bytes that do
/// not hash to the registered value are detectable. The tests are organised so
/// that the boundary of that guarantee is visible -- what it catches, and what
/// it provably does not.
contract ModelRegistryTest is Test {
    ModelRegistry reg;
    address admin = address(0xA11CE);
    address publisher = address(0xB0B);

    bytes32 constant VERSION = keccak256("brier-mvp-v1");
    bytes32 constant DATASET = keccak256("uci-german-credit/60-20-20/seed42");

    function setUp() public {
        reg = new ModelRegistry(admin);
    }

    function _register(bytes32 id, bytes memory artifact) internal returns (bytes32 h) {
        h = keccak256(artifact);
        vm.prank(publisher);
        reg.register(id, h, DATASET, "ipfs://bafyDemoCid");
    }

    // ---------------------------------------------------------------
    // The core guarantee: tamper detection.
    // ---------------------------------------------------------------

    function test_matchingArtifactVerifies() public {
        bytes32 h = _register(VERSION, "weights:T=3.0121");
        assertTrue(reg.verifyArtifact(VERSION, h));
    }

    function test_tamperedArtifactWithSameClaimedVersionIsDetected() public {
        _register(VERSION, "weights:T=3.0121");
        // Same version id, different weights. This is the substitution the
        // registry exists to catch.
        bytes32 tampered = keccak256("weights:T=0.1344");
        assertFalse(reg.verifyArtifact(VERSION, tampered),
            "substituted weights must not verify against the registered version");
    }

    function test_singleBitChangeIsDetected() public {
        _register(VERSION, "weights:T=3.0121");
        assertFalse(reg.verifyArtifact(VERSION, keccak256("weights:T=3.0122")));
    }

    function test_unknownVersionNeverVerifies() public view {
        assertFalse(reg.verifyArtifact(keccak256("never-registered"), keccak256("anything")));
    }

    function test_zeroHashDoesNotVerifyAgainstAnUnregisteredVersion() public view {
        // Guards the sentinel: artifactHash == 0 means "absent", so a caller
        // passing 0 must not accidentally match an empty slot.
        assertFalse(reg.verifyArtifact(keccak256("absent"), bytes32(0)));
    }

    // ---------------------------------------------------------------
    // Immutability of a claimed id.
    // ---------------------------------------------------------------

    function test_versionIdCannotBeRepointed() public {
        _register(VERSION, "weights:v1");
        vm.prank(publisher);
        vm.expectRevert(abi.encodeWithSelector(ModelRegistry.VersionExists.selector, VERSION));
        reg.register(VERSION, keccak256("weights:v2"), DATASET, "ipfs://other");
    }

    function test_evenTheAdminCannotRepointAVersion() public {
        _register(VERSION, "weights:v1");
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(ModelRegistry.VersionExists.selector, VERSION));
        reg.register(VERSION, keccak256("weights:v2"), DATASET, "ipfs://other");
    }

    function test_registrationStoresProvenanceFields() public {
        vm.warp(1_700_000_000);
        bytes32 h = _register(VERSION, "weights:v1");
        ModelRegistry.Version memory v = reg.get(VERSION);
        assertEq(v.artifactHash, h);
        assertEq(v.datasetHash, DATASET);
        assertEq(v.registrant, publisher);
        assertEq(v.registeredAt, 1_700_000_000);
        assertEq(v.uri, "ipfs://bafyDemoCid");
    }

    function test_reverseIndexKeepsFirstClaim() public {
        bytes32 h = _register(VERSION, "weights:v1");
        // A second id registering identical bytes must not steal attribution.
        vm.prank(address(0xDEAD));
        reg.register(keccak256("copycat"), h, DATASET, "ipfs://copy");
        assertEq(reg.versionForArtifact(h), VERSION, "first claim wins");
    }

    function test_rejectsZeroArtifactHash() public {
        vm.prank(publisher);
        vm.expectRevert(ModelRegistry.ZeroArtifactHash.selector);
        reg.register(VERSION, bytes32(0), DATASET, "ipfs://x");
    }

    function test_rejectsEmptyUri() public {
        vm.prank(publisher);
        vm.expectRevert(ModelRegistry.EmptyUri.selector);
        reg.register(VERSION, keccak256("w"), DATASET, "");
    }

    function test_getRevertsForUnknownVersion() public {
        vm.expectRevert(abi.encodeWithSelector(ModelRegistry.UnknownVersion.selector, VERSION));
        reg.get(VERSION);
    }

    // ---------------------------------------------------------------
    // Revocation is advisory, and must not destroy the audit trail.
    // ---------------------------------------------------------------

    function test_revokedVersionStillVerifies() public {
        bytes32 h = _register(VERSION, "weights:v1");
        vm.prank(admin);
        reg.revoke(VERSION, "training data contamination found");

        assertTrue(reg.isRevoked(VERSION));
        assertEq(reg.revocationReason(VERSION), "training data contamination found");
        // Historical attestations referenced this version. Verification of the
        // record must survive revocation, or revoking would retroactively
        // break the audit trail the registry protects.
        assertTrue(reg.verifyArtifact(VERSION, h),
            "revocation is advisory and must not erase the record");
    }

    function test_onlyAdminCanRevoke() public {
        _register(VERSION, "weights:v1");
        vm.prank(publisher);
        vm.expectRevert(ModelRegistry.NotAdmin.selector);
        reg.revoke(VERSION, "nope");
    }

    function test_cannotRevokeTwice() public {
        _register(VERSION, "weights:v1");
        vm.startPrank(admin);
        reg.revoke(VERSION, "first");
        vm.expectRevert(abi.encodeWithSelector(ModelRegistry.AlreadyRevoked.selector, VERSION));
        reg.revoke(VERSION, "second");
        vm.stopPrank();
    }

    function test_cannotRevokeUnknownVersion() public {
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(ModelRegistry.UnknownVersion.selector, VERSION));
        reg.revoke(VERSION, "nothing here");
    }

    // ---------------------------------------------------------------
    // The BOUNDARY of the guarantee, asserted rather than described.
    // ---------------------------------------------------------------

    /// @notice The registry does NOT establish that training was honest.
    ///
    /// A registrant can register a poisoned model perfectly honestly: the
    /// bytes hash correctly, the URI resolves, verification passes. Content
    /// integrity and training integrity are different properties, and only
    /// the first is on offer here. If this test ever needs changing, the
    /// registry's claimed guarantee has been inflated.
    function test_boundary_poisonedModelRegistersAndVerifiesCleanly() public {
        bytes32 h = _register(keccak256("poisoned-v1"), "weights:backdoored");
        assertTrue(reg.verifyArtifact(keccak256("poisoned-v1"), h),
            "the registry cannot and does not detect a dishonestly trained model");
    }

    /// @notice The registry does NOT bind a version to the circuit that ran.
    ///
    /// An attestation carries a version id as a field. Nothing in the proof
    /// ties that id to the verifying key, so an operator may reference one
    /// version and have executed another. This is the same input-provenance
    /// gap the margin has, and Phase G does not close it.
    function test_boundary_anyoneMayReferenceAVersionTheyDidNotRun() public {
        bytes32 h = _register(VERSION, "weights:v1");
        // A completely unrelated party verifies successfully against a version
        // published by someone else -- because verification is about bytes,
        // not about who executed what.
        vm.prank(address(0xBADBAD));
        assertTrue(reg.verifyArtifact(VERSION, h));
        assertEq(reg.get(VERSION).registrant, publisher, "registrant is not the executor");
    }

    function testFuzz_onlyTheExactHashVerifies(bytes32 candidate) public {
        bytes32 h = _register(VERSION, "weights:v1");
        vm.assume(candidate != h);
        assertFalse(reg.verifyArtifact(VERSION, candidate));
    }
}
