// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Script} from "forge-std/Script.sol";
import {console2} from "forge-std/console2.sol";
import {Attestation, IVerifier} from "../src/Attestation.sol";

/// @notice A verifier that accepts or rejects based on the proof bytes.
/// @dev Used to demonstrate, on a live chain, that Attestation.attest REVERTS
///      when the verifier rejects a proof (Attestation.sol:76). That is a
///      stronger guarantee than the middleware assumes: an attestation with
///      proofVerified == false cannot be created through attest() at all, as
///      Attestation.sol:57 states.
///
///      The middleware still checks proofVerified, and the fixture still
///      exercises the rejection path -- but the honest description of that
///      check is defence-in-depth against a future write path, not the gate's
///      primary function. The primary function is rejecting ids that are
///      absent from the chain entirely.
///
///      This is a TEST FIXTURE, deployed only by this script. It is not in
///      src/ and cannot reach a production deployment.
contract SelectiveVerifier is IVerifier {
    function verifyProof(bytes calldata proof, uint256[] calldata)
        external
        pure
        returns (bool)
    {
        return keccak256(proof) != keccak256(bytes("reject"));
    }
}

/// @notice Deploys Attestation with a selective verifier and seeds two
///         attestations for the x402 middleware integration test.
///
/// Prints the addresses and ids as JSON on the last line so the test harness
/// can parse one line rather than scraping the whole log.
contract DeployMiddlewareFixture is Script {
    function run() external {
        uint256 pk = vm.envOr("PRIVATE_KEY", uint256(
            0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
        ));
        address operator = vm.addr(pk);

        vm.startBroadcast(pk);

        SelectiveVerifier verifier = new SelectiveVerifier();
        Attestation attestation = new Attestation(address(verifier));

        uint256[] memory instances = new uint256[](1);
        instances[0] = 0.87e18;

        // (a) A good attestation: the verifier accepts the proof.
        bytes32 goodId = attestation.attest(
            keccak256("application-0001"),
            keccak256("shap-0001"),
            0.87e18,
            int256(2),
            bytes32("brier-mvp-v1"),
            bytes("valid-proof"),
            instances
        );

        // (c) A rejected proof. attest() reverts rather than storing a record
        // with proofVerified == false, so this id never reaches the chain and
        // the gate refuses it as UNKNOWN. Proving that here on a live chain,
        // rather than asserting it from a code comment.
        bytes32 badId = keccak256(
            abi.encode(operator, keccak256("application-0002"), keccak256("shap-0002"),
                       uint256(0.99e18), int256(5), bytes32("brier-mvp-v1"))
        );
        vm.stopBroadcast();

        // Assert the rejection OUTSIDE the broadcast block. forge re-simulates
        // every broadcast call when it submits them, and a reverting call fails
        // the run even when the script itself handled it -- so this check must
        // not be broadcast. It still executes against the same deployed
        // contract on the same chain; it is simply not sent as a transaction,
        // which is correct, because a reverting call changes no state anyway.
        (bool ok,) = address(attestation).call(
            abi.encodeCall(
                Attestation.attest,
                (
                    keccak256("application-0002"),
                    keccak256("shap-0002"),
                    0.99e18,
                    int256(5),
                    bytes32("brier-mvp-v1"),
                    bytes("reject"),
                    instances
                )
            )
        );
        require(!ok, "attest must reject an unverified proof");
        require(!attestation.exists(badId), "a rejected proof must leave no record");

        console2.log("FIXTURE_JSON");
        console2.log(
            string.concat(
                '{"attestation":"', vm.toString(address(attestation)),
                '","operator":"', vm.toString(operator),
                '","verifiedId":"', vm.toString(goodId),
                '","rejectedId":"', vm.toString(badId),
                '"}'
            )
        );
    }
}
