# EpochAnchor

One contract. Per `(owner, space)` it keeps the head of a hash-linked chain of encrypted memory
epochs. The ciphertext of every epoch travels in the calldata of `push`; the contract stores only
its `keccak256` digest, the sequence number and the block number. Nothing is ever copied to
storage or to an event except the digest.

No owner, no admin, no pause, no upgrade, no proxy, no constructor arguments, no `receive`, no
`fallback`, no ETH handling. Its only dependency for tests is forge-std. The ECDSA recovery is
inline.

## Model

- `head[owner][space]` is `{digest, seq, blockNumber}`. A fresh space has digest `bytes32(0)`, so
  the first `push` passes `prev = bytes32(0)`.
- `push(owner, space, prev, ct)` reverts `StaleHead(expected, got)` unless `prev` equals the
  current head digest, which makes the chain append-only and gives a writer a cheap compare and
  swap. It reverts `NotAuthorized` unless `canWrite(owner, msg.sender)` and `EmptyCiphertext` on a
  zero-length payload. It emits `Epoch(owner, space, writer, seq, prev, digest, prevBlock)` and
  returns `(digest, seq)`. `prevBlock` lets a reader walk backwards without an archive node index.
- `canWrite(owner, writer)` is true when the writer is the owner, or when
  `sessionKeyExpiry[owner][writer] > block.timestamp`. A session key is per machine: the owner
  authorizes it once, it appends under the owner's name, and `revokeSessionKey` stops it
  immediately, in the same block.
- `setStartSeq(space, seq)` records where a reader should start walking a chain. It is monotone
  non-decreasing and it does not affect `push`.

## The two EIP-712 facts

1. `DOMAIN_SEPARATOR()` is computed at call time from `block.chainid`, not cached at deploy. A
   fork of Base keeps verifying signatures instead of silently accepting replays from the parent
   chain. Domain: `name "kint EpochAnchor"`, `version "1"`, `chainId`, `verifyingContract`.
2. The signed type is
   `SessionKeyAuthorization(address owner,address key,uint64 expiry,uint256 nonce,uint256 deadline)`.
   The `nonce` is `authNonce[owner]` and it increments on every success, so a signature is good
   exactly once. `deadline` is a wall-clock bound checked before anything else.

`setSessionKeyBySig` is what lets the session key pay its own gas: the owner signs offline, the
key submits. Signature checking splits on `owner.code.length`. With code, the contract calls
ERC-1271 `isValidSignature(bytes32,bytes)` and requires the `0x1626ba7e` magic value; a revert
inside the account is treated as a rejection. Without code, the signature must be exactly 65
bytes, `v` is normalized from `{0,1}` to `{27,28}`, `s` must be in the lower half of the curve
order, and `ecrecover` must return the owner and never the zero address.

`authorizationDigest(owner, key, expiry, nonce, deadline)` returns the exact bytes a wallet
signs, so a client never has to rebuild the domain by hand.

### A counterfactual smart account must send its own first transaction

ERC-1271 needs deployed code. A Coinbase Smart Wallet / Base Account that has never sent a
transaction is counterfactual: `owner.code.length` is zero, so `setSessionKeyBySig` falls through
to the EOA path and rejects the account's signature. ERC-6492 wrapped signatures are not
supported here on purpose, the contract stays small. The fix is one transaction: the smart
account calls `setSessionKey(key, expiry)` itself, which deploys the account and authorizes the
key in the same transaction. After that the account has code and `setSessionKeyBySig` works for
every later key.

## Build, test, deploy

```
export FOUNDRY_DISABLE_NIGHTLY_WARNING=1
forge build
forge test -vv                                     # unit suite plus the Base fork suite
forge test -vv --no-match-path 'test/*.fork.t.sol' # offline
```

The fork suite forks `https://mainnet.base.org` (chain id 8453, reads only) and skips itself
cleanly when there is no network.

Deploy with the Python helper, which is what the rest of kint uses:

```
export KINT_RPC_URL=...          # a Base mainnet endpoint
export KINT_DEPLOYER_KEY=0x...   # env only, never a flag, never printed
env -u PYTHONPATH .venv/bin/python contracts/deploy.py
```

It estimates gas, adds 20 percent, sends an EIP-1559 transaction pinned to chain id 8453, prints
the transaction hash, then the address, `gasUsed`, `effectiveGasPrice` and the Base `l1Fee` from
the receipt, and writes `contracts/deployments/base-mainnet.json` with the address, transaction
hash, block number, chain id, deployer and ABI.

`script/Deploy.s.sol` is the forge equivalent, for when a broadcast is more convenient:

```
forge script script/Deploy.s.sol:Deploy --rpc-url "$KINT_RPC_URL" --broadcast
```

The ABI array on its own lives in `abi/EpochAnchor.json`.

## Measured

Deploy costs 879,343 gas (Base fork). For `push`, EVM execution is flat: 61,409 gas for a 4 KB
epoch and 139,387 gas for a 100 KB epoch (storage, event, keccak). That is not the bill. Since
EIP-7623 (live on Base as of Isthmus) a transaction is charged
`max(standard, 21000 + 10 * (zeros + 4 * nonzeros))`, and an AES-GCM ciphertext is essentially
all nonzero bytes, so 40 gas per byte. The floor swallows execution at every bucket and the
receipt's `gasUsed` equals the floor exactly (measured on a Base fork at block 51,081,018):

| bucket | calldata bytes | gasUsed |
|---|---|---|
| 4 KB | 4,356 | 191,040 |
| 8 KB | 8,452 | 355,390 |
| 16 KB | 16,644 | 681,840 |
| 32 KB | 33,028 | 1,336,090 |
| 64 KB | 65,796 | 2,642,640 |
| 96 KB | 98,564 | 3,949,670 |

Calldata is charged twice on Base: as L2 intrinsic gas above and again as the L1 data fee in the
receipt's `l1Fee`. At current conditions the L2 charge is the larger by roughly 10x to 28x. At a
0.005 gwei base fee a 4 KB epoch costs about 0.000001 ETH all in and a 96 KB epoch about
0.00002 ETH. The seeded demo tenant lands in the 4 KB bucket. `kint` records the real `gasUsed`
and `l1Fee` from every receipt; the unit test's `gasleft` delta deliberately excludes the floor.


## Two limits worth knowing

- No owner rotation: losing the owner key ends new writes for every (owner, space) of that owner
  once its session keys expire. Reads never need the owner key.
- The ciphertext lives only in transaction calldata. Reading it back goes through
  `eth_getTransactionByHash`, which depends on the node keeping a transaction index; kint keeps
  its own ciphertext cache per epoch as the backup copy, and the L1 data availability window is
  the blob retention window, not forever.
