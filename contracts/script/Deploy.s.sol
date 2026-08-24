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

        vm.startBroadcast(pk);

        Halo2Verifier verifier = new Halo2Verifier();
        Attestation attestation = new Attestation(address(verifier));
        StakePool pool = new StakePool(address(attestation), admin, capBps, unbonding);

        vm.stopBroadcast();

        console.log("VERIFIER", address(verifier));
        console.log("ATTESTATION", address(attestation));
        console.log("STAKEPOOL", address(pool));
        console.log("ADMIN", admin);
        console.log("UNBONDING_SECONDS", unbonding);
    }
}
