// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {Attestation} from "../src/Attestation.sol";
import {Halo2Verifier} from "../src/VerifierTemperature.sol";
import {StakePool} from "../src/StakePool.sol";

/// @notice Deploys the full stack to a local chain for the Phase 5 demo.
contract Deploy is Script {
    function run() external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address admin = vm.addr(pk);
        uint256 capBps = vm.envOr("MAX_SLASH_BPS", uint256(10_000));
        uint256 unbonding = vm.envOr("UNBONDING_PERIOD", uint256(7 days));

        // Bounded-trust resolver committee (Phase 3b). Defaults to Anvil
        // accounts 1-3 with a 2-of-3 threshold for the local demo. This is a
        // fixed list chosen by the deployer -- NOT decentralised.
        address[] memory committee = new address[](3);
        committee[0] = vm.envOr("RESOLVER_1", address(0x70997970C51812dc3A010C7d01b50e0d17dc79C8));
        committee[1] = vm.envOr("RESOLVER_2", address(0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC));
        committee[2] = vm.envOr("RESOLVER_3", address(0x90F79bf6EB2c4f870365E785982E1f101E93b906));
        uint256 threshold = vm.envOr("RESOLVER_THRESHOLD", uint256(2));

        vm.startBroadcast(pk);

        Halo2Verifier verifier = new Halo2Verifier();
        Attestation attestation = new Attestation(address(verifier));
        StakePool pool = new StakePool(
            address(attestation), admin, capBps, unbonding, committee, threshold
        );

        vm.stopBroadcast();

        console.log("VERIFIER", address(verifier));
        console.log("ATTESTATION", address(attestation));
        console.log("STAKEPOOL", address(pool));
        console.log("ADMIN", admin);
        console.log("UNBONDING_SECONDS", unbonding);
        console.log("RESOLVER_THRESHOLD", threshold);
        console.log("COMMITTEE_SIZE", committee.length);
    }
}
