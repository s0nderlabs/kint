// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {console} from "forge-std/console.sol";
import {EpochAnchor} from "../src/EpochAnchor.sol";

/// @notice Deploys EpochAnchor. Takes no arguments; the contract has no constructor args.
/// @dev forge script script/Deploy.s.sol:Deploy --rpc-url <url> --broadcast
contract Deploy is Script {
    function run() external returns (EpochAnchor anchor) {
        vm.startBroadcast();
        anchor = new EpochAnchor();
        vm.stopBroadcast();

        console.log("EpochAnchor deployed at", address(anchor));
        console.log("chain id", block.chainid);
    }
}
