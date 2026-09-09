// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {EpochAnchor, IERC1271} from "../src/EpochAnchor.sol";

/// @notice Contract account used to exercise the ERC-1271 branch of setSessionKeyBySig.
contract MockERC1271 {
    bool public accept;

    constructor(bool accept_) {
        accept = accept_;
    }

    function setAccept(bool accept_) external {
        accept = accept_;
    }

    function isValidSignature(bytes32, bytes memory) external view returns (bytes4) {
        return accept ? bytes4(0x1626ba7e) : bytes4(0xffffffff);
    }

    function setSessionKeyOn(EpochAnchor anchor, address key, uint64 expiry) external {
        anchor.setSessionKey(key, expiry);
    }
}

/// @notice Contract account whose isValidSignature always reverts.
contract RevertingERC1271 {
    function isValidSignature(bytes32, bytes memory) external pure returns (bytes4) {
        revert("nope");
    }
}

contract EpochAnchorTest is Test {
    uint256 internal constant SECP256K1_N =
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;

    EpochAnchor internal anchor;

    uint256 internal ownerPk = 0xA11CE;
    address internal owner;
    address internal sessionKey = address(0x5E551);
    address internal stranger = address(0xDEAD);
    bytes32 internal space = keccak256("default");

    event Epoch(
        address indexed owner,
        bytes32 indexed space,
        address indexed writer,
        uint64 seq,
        bytes32 prev,
        bytes32 digest,
        uint64 prevBlock
    );
    event SessionKeySet(address indexed owner, address indexed key, uint64 expiry);
    event StartSeqSet(address indexed owner, bytes32 indexed space, uint64 seq);

    function setUp() public {
        anchor = new EpochAnchor();
        owner = vm.addr(ownerPk);
        vm.warp(1_757_000_000);
    }

    function _sign(uint256 pk, bytes32 digest) internal pure returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(pk, digest);
        return abi.encodePacked(r, s, v);
    }

    // push

    function test_FirstPushEmitsAndReturns() public {
        bytes memory ct = bytes("epoch one ciphertext");
        vm.expectEmit(true, true, true, true);
        emit Epoch(owner, space, owner, 1, bytes32(0), keccak256(ct), 0);

        vm.prank(owner);
        (bytes32 digest, uint64 seq) = anchor.push(owner, space, bytes32(0), ct);

        assertEq(digest, keccak256(ct));
        assertEq(seq, 1);
        (bytes32 hd, uint64 hs, uint64 hb) = anchor.head(owner, space);
        assertEq(hd, keccak256(ct));
        assertEq(hs, 1);
        assertEq(hb, uint64(block.number));
    }

    function test_SecondPushChainsOnFirst() public {
        bytes memory a = bytes("one");
        bytes memory b = bytes("two");
        vm.prank(owner);
        (bytes32 d1,) = anchor.push(owner, space, bytes32(0), a);

        uint64 firstBlock = uint64(block.number);
        vm.roll(block.number + 5);

        vm.expectEmit(true, true, true, true);
        emit Epoch(owner, space, owner, 2, d1, keccak256(b), firstBlock);
        vm.prank(owner);
        (bytes32 d2, uint64 seq2) = anchor.push(owner, space, d1, b);

        assertEq(d2, keccak256(b));
        assertEq(seq2, 2);
    }

    function test_WrongPrevRevertsStaleHead() public {
        vm.prank(owner);
        (bytes32 d1,) = anchor.push(owner, space, bytes32(0), bytes("one"));

        bytes32 wrong = keccak256("wrong");
        vm.expectRevert(abi.encodeWithSelector(EpochAnchor.StaleHead.selector, d1, wrong));
        vm.prank(owner);
        anchor.push(owner, space, wrong, bytes("two"));
    }

    function test_StrangerCannotPush() public {
        vm.expectRevert(EpochAnchor.NotAuthorized.selector);
        vm.prank(stranger);
        anchor.push(owner, space, bytes32(0), bytes("one"));
    }

    function test_EmptyCiphertextReverts() public {
        vm.expectRevert(EpochAnchor.EmptyCiphertext.selector);
        vm.prank(owner);
        anchor.push(owner, space, bytes32(0), bytes(""));
    }

    function test_TwoSpacesHaveIndependentHeads() public {
        bytes32 spaceB = keccak256("notes");
        vm.startPrank(owner);
        (bytes32 dA,) = anchor.push(owner, space, bytes32(0), bytes("a"));
        (bytes32 dB, uint64 seqB) = anchor.push(owner, spaceB, bytes32(0), bytes("b"));
        vm.stopPrank();

        assertEq(seqB, 1);
        (bytes32 hA, uint64 sA,) = anchor.head(owner, space);
        (bytes32 hB, uint64 sB,) = anchor.head(owner, spaceB);
        assertEq(hA, dA);
        assertEq(hB, dB);
        assertEq(sA, 1);
        assertEq(sB, 1);
    }

    function test_LargeCiphertextPushSucceeds() public {
        bytes memory ct = new bytes(100_000);
        for (uint256 i = 0; i < ct.length; i++) {
            ct[i] = bytes1(uint8(i));
        }
        vm.prank(owner);
        (bytes32 digest, uint64 seq) = anchor.push(owner, space, bytes32(0), ct);
        assertEq(digest, keccak256(ct));
        assertEq(seq, 1);
    }

    function test_GasForFourKilobyteAndHundredKilobytePushes() public {
        bytes memory small = new bytes(4096);
        bytes memory large = new bytes(100_000);
        for (uint256 i = 0; i < large.length; i++) {
            large[i] = bytes1(uint8(i));
            if (i < small.length) small[i] = bytes1(uint8(i));
        }

        vm.startPrank(owner);
        uint256 before = gasleft();
        (bytes32 d1,) = anchor.push(owner, space, bytes32(0), small);
        uint256 smallGas = before - gasleft();

        before = gasleft();
        anchor.push(owner, space, d1, large);
        uint256 largeGas = before - gasleft();
        vm.stopPrank();

        emit log_named_uint("push 4 KB gas (execution, no calldata cost)", smallGas);
        emit log_named_uint("push 100 KB gas (execution, no calldata cost)", largeGas);
        emit log_named_uint("push 4 KB calldata bytes", small.length);
        emit log_named_uint("push 100 KB calldata bytes", large.length);
    }

    // session keys

    function test_CanWriteOwnerWithNoSetup() public view {
        assertTrue(anchor.canWrite(owner, owner));
        assertFalse(anchor.canWrite(owner, stranger));
    }

    function test_SessionKeyPushesUnderOwner() public {
        uint64 expiry = uint64(block.timestamp + 30 days);
        vm.expectEmit(true, true, true, true);
        emit SessionKeySet(owner, sessionKey, expiry);
        vm.prank(owner);
        anchor.setSessionKey(sessionKey, expiry);

        assertTrue(anchor.canWrite(owner, sessionKey));

        bytes memory ct = bytes("from the laptop");
        vm.expectEmit(true, true, true, true);
        emit Epoch(owner, space, sessionKey, 1, bytes32(0), keccak256(ct), 0);
        vm.prank(sessionKey);
        anchor.push(owner, space, bytes32(0), ct);

        (bytes32 hd, uint64 hs,) = anchor.head(owner, space);
        assertEq(hd, keccak256(ct));
        assertEq(hs, 1);
    }

    function test_ExpiredSessionKeyCannotPush() public {
        uint64 expiry = uint64(block.timestamp + 1 days);
        vm.prank(owner);
        anchor.setSessionKey(sessionKey, expiry);

        vm.warp(uint256(expiry) + 1);
        assertFalse(anchor.canWrite(owner, sessionKey));
        vm.expectRevert(EpochAnchor.NotAuthorized.selector);
        vm.prank(sessionKey);
        anchor.push(owner, space, bytes32(0), bytes("late"));
    }

    function test_RevokeStopsKeyImmediately() public {
        vm.prank(owner);
        anchor.setSessionKey(sessionKey, uint64(block.timestamp + 30 days));
        assertTrue(anchor.canWrite(owner, sessionKey));

        vm.expectEmit(true, true, true, true);
        emit SessionKeySet(owner, sessionKey, 0);
        vm.prank(owner);
        anchor.revokeSessionKey(sessionKey);

        assertFalse(anchor.canWrite(owner, sessionKey));
        assertEq(anchor.sessionKeyExpiry(owner, sessionKey), 0);
        vm.expectRevert(EpochAnchor.NotAuthorized.selector);
        vm.prank(sessionKey);
        anchor.push(owner, space, bytes32(0), bytes("revoked"));
    }

    // setSessionKeyBySig

    function test_SetSessionKeyBySigFromEoaOwner() public {
        uint64 expiry = uint64(block.timestamp + 30 days);
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 digest = anchor.authorizationDigest(owner, sessionKey, expiry, 0, deadline);
        bytes memory sig = _sign(ownerPk, digest);

        vm.expectEmit(true, true, true, true);
        emit SessionKeySet(owner, sessionKey, expiry);
        vm.prank(stranger);
        anchor.setSessionKeyBySig(owner, sessionKey, expiry, deadline, sig);

        assertEq(anchor.sessionKeyExpiry(owner, sessionKey), expiry);
        assertEq(anchor.authNonce(owner), 1);

        vm.prank(sessionKey);
        anchor.push(owner, space, bytes32(0), bytes("authorized by signature"));
    }

    function test_ReplayedSignatureReverts() public {
        uint64 expiry = uint64(block.timestamp + 30 days);
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _sign(ownerPk, anchor.authorizationDigest(owner, sessionKey, expiry, 0, deadline));

        vm.prank(stranger);
        anchor.setSessionKeyBySig(owner, sessionKey, expiry, deadline, sig);

        vm.expectRevert(EpochAnchor.BadSignature.selector);
        vm.prank(stranger);
        anchor.setSessionKeyBySig(owner, sessionKey, expiry, deadline, sig);
    }

    function test_HighSSignatureReverts() public {
        uint64 expiry = uint64(block.timestamp + 30 days);
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 digest = anchor.authorizationDigest(owner, sessionKey, expiry, 0, deadline);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(ownerPk, digest);

        bytes32 highS = bytes32(SECP256K1_N - uint256(s));
        uint8 flipped = v == 27 ? 28 : 27;
        bytes memory sig = abi.encodePacked(r, highS, flipped);

        vm.expectRevert(EpochAnchor.BadSignature.selector);
        anchor.setSessionKeyBySig(owner, sessionKey, expiry, deadline, sig);
    }

    function test_WrongLengthSignatureReverts() public {
        uint64 expiry = uint64(block.timestamp + 30 days);
        uint256 deadline = block.timestamp + 1 hours;
        vm.expectRevert(EpochAnchor.BadSignature.selector);
        anchor.setSessionKeyBySig(owner, sessionKey, expiry, deadline, hex"1234");
    }

    function test_PastDeadlineReverts() public {
        uint64 expiry = uint64(block.timestamp + 30 days);
        uint256 deadline = block.timestamp - 1;
        bytes memory sig = _sign(ownerPk, anchor.authorizationDigest(owner, sessionKey, expiry, 0, deadline));
        vm.expectRevert(EpochAnchor.AuthorizationExpired.selector);
        anchor.setSessionKeyBySig(owner, sessionKey, expiry, deadline, sig);
    }

    function test_SetSessionKeyBySigWithContractOwner() public {
        MockERC1271 account = new MockERC1271(true);
        uint64 expiry = uint64(block.timestamp + 30 days);
        uint256 deadline = block.timestamp + 1 hours;

        vm.prank(stranger);
        anchor.setSessionKeyBySig(address(account), sessionKey, expiry, deadline, hex"00");
        assertEq(anchor.sessionKeyExpiry(address(account), sessionKey), expiry);
        assertEq(anchor.authNonce(address(account)), 1);

        account.setAccept(false);
        vm.expectRevert(EpochAnchor.BadSignature.selector);
        vm.prank(stranger);
        anchor.setSessionKeyBySig(address(account), sessionKey, expiry, deadline, hex"00");
    }

    function test_ContractOwnerThatRevertsIsRejected() public {
        RevertingERC1271 account = new RevertingERC1271();
        vm.expectRevert(EpochAnchor.BadSignature.selector);
        anchor.setSessionKeyBySig(
            address(account), sessionKey, uint64(block.timestamp + 1 days), block.timestamp + 1 hours, hex"00"
        );
    }

    function test_ContractOwnerCanPushAndDelegate() public {
        MockERC1271 account = new MockERC1271(true);
        uint64 expiry = uint64(block.timestamp + 30 days);
        account.setSessionKeyOn(anchor, sessionKey, expiry);
        assertTrue(anchor.canWrite(address(account), sessionKey));

        vm.prank(sessionKey);
        (, uint64 seq) = anchor.push(address(account), space, bytes32(0), bytes("smart account epoch"));
        assertEq(seq, 1);
    }

    // startSeq

    function test_SetStartSeqIsMonotone() public {
        vm.expectEmit(true, true, true, true);
        emit StartSeqSet(owner, space, 5);
        vm.prank(owner);
        anchor.setStartSeq(space, 5);
        assertEq(anchor.startSeq(owner, space), 5);

        vm.prank(owner);
        anchor.setStartSeq(space, 5);

        vm.prank(owner);
        anchor.setStartSeq(space, 9);
        assertEq(anchor.startSeq(owner, space), 9);

        vm.expectRevert(EpochAnchor.SeqNotMonotone.selector);
        vm.prank(owner);
        anchor.setStartSeq(space, 8);
    }

    function test_StartSeqDoesNotAffectPush() public {
        vm.startPrank(owner);
        anchor.setStartSeq(space, 42);
        (, uint64 seq) = anchor.push(owner, space, bytes32(0), bytes("one"));
        vm.stopPrank();
        assertEq(seq, 1);
    }

    function test_DomainSeparatorTracksChainId() public {
        bytes32 before = anchor.DOMAIN_SEPARATOR();
        vm.chainId(8453);
        assertTrue(anchor.DOMAIN_SEPARATOR() != before);
    }

    function test_RevokeInvalidatesUnspentAuthorization() public {
        // the owner signs a renewal the machine withholds, then revokes: the held signature must be dead
        uint64 expiry = uint64(block.timestamp + 3650 days);
        uint256 deadline = block.timestamp + 1 hours;
        uint256 nonceBefore = anchor.authNonce(owner);
        bytes memory held = _sign(ownerPk, anchor.authorizationDigest(owner, sessionKey, expiry, nonceBefore, deadline));

        vm.prank(owner);
        anchor.revokeSessionKey(sessionKey);
        assertEq(anchor.authNonce(owner), nonceBefore + 1, "revoke consumes the authorization nonce");
        assertFalse(anchor.canWrite(owner, sessionKey));

        vm.expectRevert(EpochAnchor.BadSignature.selector);
        vm.prank(sessionKey);
        anchor.setSessionKeyBySig(owner, sessionKey, expiry, deadline, held);
        assertFalse(anchor.canWrite(owner, sessionKey), "revocation holds");
    }

    function test_SetSessionKeyInvalidatesUnspentAuthorization() public {
        uint64 expiry = uint64(block.timestamp + 30 days);
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory held = _sign(ownerPk, anchor.authorizationDigest(owner, address(0xBEEF), expiry, 0, deadline));

        vm.prank(owner);
        anchor.setSessionKey(sessionKey, expiry);
        assertEq(anchor.authNonce(owner), 1, "an on-chain authorization consumes the nonce too");

        vm.expectRevert(EpochAnchor.BadSignature.selector);
        anchor.setSessionKeyBySig(owner, address(0xBEEF), expiry, deadline, held);
    }

}
