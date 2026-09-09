// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @notice Minimal ERC-1271 view used to verify a signature made by a contract account.
interface IERC1271 {
    function isValidSignature(bytes32 hash, bytes memory signature) external view returns (bytes4);
}

/// @title EpochAnchor
/// @notice Per (owner, space) head of a hash-linked chain of encrypted memory epochs.
///         The ciphertext of every epoch travels in the calldata of `push`; the contract
///         keeps only its keccak256 digest, the sequence number and the block number.
/// @dev No owner, no admin, no pause, no upgrade, no ETH. Every write is authorized by the
///      memory owner directly or by a session key the owner has given an expiry to.
contract EpochAnchor {
    /// @param digest keccak256 of the ciphertext of the latest epoch.
    /// @param seq 1-based sequence number of the latest epoch.
    /// @param blockNumber block the latest epoch landed in.
    struct Head {
        bytes32 digest;
        uint64 seq;
        uint64 blockNumber;
    }

    /// @notice Latest epoch per owner and space.
    mapping(address owner => mapping(bytes32 space => Head)) public head;
    /// @notice Unix timestamp a session key stays usable until. 0 means revoked.
    mapping(address owner => mapping(address key => uint64 expiry)) public sessionKeyExpiry;
    /// @notice Reader hint for where a chain of epochs begins. Does not affect `push`.
    mapping(address owner => mapping(bytes32 space => uint64 seq)) public startSeq;
    /// @notice Replay counter for `setSessionKeyBySig`.
    mapping(address owner => uint256 nonce) public authNonce;

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

    error NotAuthorized();
    error StaleHead(bytes32 expected, bytes32 got);
    error BadSignature();
    error AuthorizationExpired();
    error SeqNotMonotone();
    error EmptyCiphertext();

    bytes32 private constant _DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 private constant _AUTH_TYPEHASH = keccak256(
        "SessionKeyAuthorization(address owner,address key,uint64 expiry,uint256 nonce,uint256 deadline)"
    );
    bytes32 private constant _NAME_HASH = keccak256("kint EpochAnchor");
    bytes32 private constant _VERSION_HASH = keccak256("1");
    /// @dev Upper half of the secp256k1 order is rejected, so `s` has one encoding. `v` is accepted
    ///      as 0/1 or 27/28; replay is prevented by `authNonce`, not by signature uniqueness.
    bytes32 private constant _MAX_S = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0;

    /// @notice Authorize `key` to append under the caller's name until `expiry`. 0 revokes.
    /// @dev Also consumes the caller's authorization nonce, so any signed-but-unsubmitted
    ///      `setSessionKeyBySig` authorization is cancelled by an owner acting on chain.
    function setSessionKey(address key, uint64 expiry) external {
        unchecked {
            authNonce[msg.sender]++;
        }
        sessionKeyExpiry[msg.sender][key] = expiry;
        emit SessionKeySet(msg.sender, key, expiry);
    }

    /// @notice Drop a session key immediately, in this same block.
    /// @dev Consumes the authorization nonce too: a signed authorization the revoked machine
    ///      is still holding can no longer re-arm it.
    function revokeSessionKey(address key) external {
        unchecked {
            authNonce[msg.sender]++;
        }
        sessionKeyExpiry[msg.sender][key] = 0;
        emit SessionKeySet(msg.sender, key, 0);
    }

    /// @notice Authorize a session key with an EIP-712 signature from the owner, submitted by anyone.
    /// @dev The session key normally submits this itself and pays the gas.
    function setSessionKeyBySig(
        address owner,
        address key,
        uint64 expiry,
        uint256 deadline,
        bytes calldata signature
    ) external {
        if (block.timestamp > deadline) revert AuthorizationExpired();
        uint256 nonce = authNonce[owner];
        bytes32 digest = authorizationDigest(owner, key, expiry, nonce, deadline);

        if (owner.code.length > 0) {
            try IERC1271(owner).isValidSignature(digest, signature) returns (bytes4 magic) {
                if (magic != IERC1271.isValidSignature.selector) revert BadSignature();
            } catch {
                revert BadSignature();
            }
        } else {
            if (signature.length != 65) revert BadSignature();
            bytes32 r = bytes32(signature[0:32]);
            bytes32 s = bytes32(signature[32:64]);
            uint8 v = uint8(signature[64]);
            if (v < 27) v += 27;
            if (v != 27 && v != 28) revert BadSignature();
            if (uint256(s) > uint256(_MAX_S)) revert BadSignature();
            address signer = ecrecover(digest, v, r, s);
            if (signer == address(0) || signer != owner) revert BadSignature();
        }

        unchecked {
            authNonce[owner] = nonce + 1;
        }
        sessionKeyExpiry[owner][key] = expiry;
        emit SessionKeySet(owner, key, expiry);
    }

    /// @notice Record where a reader should start walking the caller's chain in `space`.
    function setStartSeq(bytes32 space, uint64 seq) external {
        if (seq < startSeq[msg.sender][space]) revert SeqNotMonotone();
        startSeq[msg.sender][space] = seq;
        emit StartSeqSet(msg.sender, space, seq);
    }

    /// @notice True when `writer` may append under `owner`.
    function canWrite(address owner, address writer) public view returns (bool) {
        return writer == owner || sessionKeyExpiry[owner][writer] > block.timestamp;
    }

    /// @notice Append one epoch. The ciphertext stays in calldata; only its digest is stored.
    /// @param prev The digest currently at the head, bytes32(0) for the first epoch in a space.
    /// @return digest keccak256 of `ct`.
    /// @return seq The sequence number this epoch was given.
    function push(address owner, bytes32 space, bytes32 prev, bytes calldata ct)
        external
        returns (bytes32 digest, uint64 seq)
    {
        if (!canWrite(owner, msg.sender)) revert NotAuthorized();
        if (ct.length == 0) revert EmptyCiphertext();

        Head memory h = head[owner][space];
        if (h.digest != prev) revert StaleHead(h.digest, prev);

        digest = keccak256(ct);
        seq = h.seq + 1;
        head[owner][space] = Head({digest: digest, seq: seq, blockNumber: uint64(block.number)});

        emit Epoch(owner, space, msg.sender, seq, prev, digest, h.blockNumber);
    }

    /// @notice EIP-712 domain separator, built at call time so a fork of this chain still works.
    function DOMAIN_SEPARATOR() public view returns (bytes32) {
        return keccak256(
            abi.encode(_DOMAIN_TYPEHASH, _NAME_HASH, _VERSION_HASH, block.chainid, address(this))
        );
    }

    /// @notice The digest an owner signs to authorize a session key.
    function authorizationDigest(
        address owner,
        address key,
        uint64 expiry,
        uint256 nonce,
        uint256 deadline
    ) public view returns (bytes32) {
        bytes32 structHash = keccak256(abi.encode(_AUTH_TYPEHASH, owner, key, expiry, nonce, deadline));
        return keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR(), structHash));
    }
}
