// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {EpochAnchor} from "../src/EpochAnchor.sol";

/// @notice Base mainnet fork checks against a real Coinbase Smart Wallet address.
///         The suite skips itself cleanly when the public RPC is unreachable.
contract EpochAnchorForkTest is Test {
    string internal constant BASE_RPC = "https://mainnet.base.org";
    /// @dev A real Base Account address, counterfactual at the time of writing (no code on chain).
    address internal constant SMART_ACCOUNT = 0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3;

    EpochAnchor internal anchor;
    address internal sessionKey = address(0x5E551);
    bytes32 internal space = keccak256("default");
    bool internal forked;

    function setUp() public {
        try vm.createSelectFork(BASE_RPC) returns (uint256) {
            forked = true;
            anchor = new EpochAnchor();
        } catch {
            forked = false;
            vm.skip(true);
        }
    }

    function test_ForkChainIdIsBase() public view {
        assertEq(block.chainid, 8453);
    }

    function test_SmartAccountOwnerAuthorizesAndPushes() public {
        uint64 expiry = uint64(block.timestamp + 30 days);

        vm.prank(SMART_ACCOUNT);
        anchor.setSessionKey(sessionKey, expiry);
        assertTrue(anchor.canWrite(SMART_ACCOUNT, sessionKey));

        vm.prank(SMART_ACCOUNT);
        (bytes32 digest, uint64 seq) = anchor.push(SMART_ACCOUNT, space, bytes32(0), bytes("hello"));
        assertEq(digest, keccak256(bytes("hello")));
        assertEq(seq, 1);

        vm.prank(sessionKey);
        (, uint64 seq2) = anchor.push(SMART_ACCOUNT, space, digest, bytes("second epoch"));
        assertEq(seq2, 2);
    }

    /// @dev A counterfactual account has no code, so the EOA path runs and a garbage signature
    ///      is rejected there. ERC-1271 needs deployed code, and ERC-6492 wrappers are not supported.
    function test_CounterfactualAccountFallsThroughToEcrecoverAndFails() public {
        address counterfactual = address(uint160(uint256(keccak256("kint fork test: never deployed"))));
        assertEq(counterfactual.code.length, 0, "expected an address with no code");

        bytes32 r = keccak256("r");
        bytes32 s = bytes32(uint256(0x1234));
        bytes memory sig = abi.encodePacked(r, s, uint8(27));

        vm.expectRevert(EpochAnchor.BadSignature.selector);
        anchor.setSessionKeyBySig(
            counterfactual, sessionKey, uint64(block.timestamp + 1 days), block.timestamp + 1 hours, sig
        );
    }

    /// @dev The real Base Account was deployed on Sep 9 2026 by its own setSessionKey transaction
    ///      (sent from kint's authorize page), so it now takes the ERC-1271 path. Its
    ///      isValidSignature rejects a garbage 65-byte blob, which surfaces as BadSignature.
    function test_DeployedSmartAccountTakesErc1271PathAndRejectsGarbage() public {
        assertGt(SMART_ACCOUNT.code.length, 0, "the Base Account should be deployed by now");

        bytes32 r = keccak256("r");
        bytes32 s = bytes32(uint256(0x1234));
        bytes memory sig = abi.encodePacked(r, s, uint8(27));

        vm.expectRevert(EpochAnchor.BadSignature.selector);
        anchor.setSessionKeyBySig(
            SMART_ACCOUNT, sessionKey, uint64(block.timestamp + 1 days), block.timestamp + 1 hours, sig
        );
    }
}
