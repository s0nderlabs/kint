---
slug: contract
title: EpochAnchor contract
description: Every function, event and error of EpochAnchor on Base mainnet, who may call it, and what it costs.
group: Reference
order: 11
source: 'contracts/src/EpochAnchor.sol'
---

# A digest, a sequence number and a block height for each owner and space.

EpochAnchor is the one contract under kint. It keeps the head of each owner's chain of epochs per space; the ciphertext rides in the calldata of `push` and never touches contract storage.

## The deployment

| field | value |
|---|---|
| address | [`0xa22E03f7a4145Bf4909a83595C90a38E14d79600`](https://basescan.org/address/0xa22E03f7a4145Bf4909a83595C90a38E14d79600) |
| chain | Base mainnet, chain id `8453` |
| deploy tx | [`0xf2e03cd1c4e7ca005ee602a6c61ed50861d2238acee217b2c19f8670ba2cc9f6`](https://basescan.org/tx/0xf2e03cd1c4e7ca005ee602a6c61ed50861d2238acee217b2c19f8670ba2cc9f6) |
| deploy block | 51081696 (Sep 9 2026) |
| deployer | `0xC635e6Eb223aE14143E23cEEa9440bC773dc87Ec` |
| deploy receipt | gasUsed 885,843; effective gas price 7,833,683 wei; L1 fee 1,526,707,829 wei |
| compiler | solc 0.8.28, evm cancun, optimizer 200 runs, `bytecode_hash none` |
| source | verified on Basescan |

The contract has no owner, no admin, no pause, no proxy, no upgrade path, no constructor arguments, no `receive`, no `fallback`, and it never handles ETH. Its only dependency is forge-std, and only for tests; the ECDSA recovery is inline. A change to the contract means a redeploy, which is a new address and a new chain of epochs that starts empty.

kint reads the address from `KINT_CONTRACT` and falls back to the address above (`DEFAULT_CONTRACT` in `src/kint/chain.py`). The browser core exports the same default as `DEFAULT_CONTRACT` in `js/src/chain.ts`, and its read functions take the contract address as a parameter. The ABI ships in three identical copies: `contracts/abi/EpochAnchor.json`, the `abi` field of `contracts/deployments/base-mainnet.json`, and `src/kint/EpochAnchor.abi.json` inside the Python package.

## State

Four public mappings, each with a generated getter:

| mapping | key | value |
|---|---|---|
| `head` | `(address owner, bytes32 space)` | `Head { bytes32 digest; uint64 seq; uint64 blockNumber; }` |
| `sessionKeyExpiry` | `(address owner, address key)` | `uint64 expiry`, a unix timestamp; `0` means revoked or never set |
| `startSeq` | `(address owner, bytes32 space)` | `uint64 seq`, a reader hint; it does not affect `push` |
| `authNonce` | `address owner` | `uint256 nonce`, the replay counter for `setSessionKeyBySig` |

### The head record

`head[owner][space]` is the newest epoch for that owner and space. `digest` is `keccak256` of its ciphertext, `seq` is its 1-based sequence number, and `blockNumber` is the block it landed in. A space nobody has written to returns all zeros, so the first `push` passes `prev = bytes32(0)` and gets `seq` 1.

A space is a `bytes32` that kint derives from the tenant id: `keccak256("kint-space-v1" || tenant_id)` over the UTF-8 bytes, with no separator (`space_id` in `src/kint/crypto.py`). Two tenants under the same owner have independent heads, and so do two owners using the same tenant id.

## Functions

| function | who may call | what it does |
|---|---|---|
| `push(address owner, bytes32 space, bytes32 prev, bytes ct) returns (bytes32 digest, uint64 seq)` | the owner, or a session key whose expiry is still ahead | Appends one epoch. Reverts unless `canWrite(owner, msg.sender)`, then unless `ct` is non-empty, then unless `prev` equals the current head digest. Stores `keccak256(ct)`, `seq + 1` and `block.number`; emits `Epoch`. |
| `setSessionKey(address key, uint64 expiry)` | anyone, for their own address | Sets `sessionKeyExpiry[msg.sender][key] = expiry` (`0` revokes). Increments `authNonce[msg.sender]`. Emits `SessionKeySet`. |
| `revokeSessionKey(address key)` | anyone, for their own address | Sets the key's expiry to `0` in this same block. Increments `authNonce[msg.sender]`. Emits `SessionKeySet` with expiry `0`. |
| `setSessionKeyBySig(address owner, address key, uint64 expiry, uint256 deadline, bytes signature)` | anyone who holds a valid owner signature; normally the session key itself | Checks `deadline`, then the owner's EIP-712 signature over the current nonce. On success sets the expiry, sets `authNonce[owner]` to nonce + 1, emits `SessionKeySet`. |
| `setStartSeq(bytes32 space, uint64 seq)` | anyone, for their own address | Records where a reader should start walking `msg.sender`'s chain in `space`. Monotone non-decreasing; setting the same value again is allowed. Emits `StartSeqSet`. |
| `canWrite(address owner, address writer) view returns (bool)` | anyone | True when `writer == owner`, or when `sessionKeyExpiry[owner][writer] > block.timestamp`. |
| `DOMAIN_SEPARATOR() view returns (bytes32)` | anyone | The EIP-712 domain separator, computed at call time from `block.chainid` and `address(this)`. |
| `authorizationDigest(address owner, address key, uint64 expiry, uint256 nonce, uint256 deadline) view returns (bytes32)` | anyone | The exact digest an owner signs to authorize a session key, so a client never rebuilds the domain by hand. |
| `head`, `sessionKeyExpiry`, `startSeq`, `authNonce` | anyone | The getters for the four mappings above. |

The order of checks in `push` matters when you read a revert: authorization first, then the empty payload, then the head comparison. The compare against `prev` is a cheap compare-and-swap. Two machines racing on the same head cannot both land, and the loser gets `StaleHead` with the digest it should have built on.

kint rarely gets that far. Before it sends, `kint push` compares the chain head with the head this machine last saw, anchored or pulled; when they differ it stops, says another machine pushed, and tells you to run `kint pull` first. The one exception is the owner's way past an epoch that never opens: after a pull that stopped at such an epoch, `kint compact --over-skipped` (or `kint rekey --over-skipped`) builds its snapshot on the chain head's digest instead of this machine's, which is exactly the `prev` that `push` checks ([Epochs on Base](/docs/epochs#an-epoch-nobody-can-open)). It then checks `canWrite` for its session key and stops with `session key ... is not authorized for owner ...: authorize it (kint authorize) and fund it`. Every send is gas-estimated first, so a push that would still revert fails as `transaction would revert: ...` without spending gas.

No kint command sends `setStartSeq` in v0.3.0. The browser core exposes a reader for it (`readStartSeq` in `js/src/chain.ts`, documented there as the lowest seq the owner still vouches for).

## Events

| event | indexed | data |
|---|---|---|
| `Epoch` | `address owner`, `bytes32 space`, `address writer` | `uint64 seq`, `bytes32 prev`, `bytes32 digest`, `uint64 prevBlock` |
| `SessionKeySet` | `address owner`, `address key` | `uint64 expiry` |
| `StartSeqSet` | `address owner`, `bytes32 space` | `uint64 seq` |

`writer` in `Epoch` is `msg.sender`: the owner itself or the session key that pushed. `prevBlock` is the block of the previous head (`0` for the first epoch in a space). It lets a reader walk from the head back to genesis with one exact-block `eth_getLogs` per epoch, filtered on the `Epoch` topic, the owner and the space, so no RPC log-range cap is ever hit (`walk_epochs` in `src/kint/chain.py`, `walkEpochs` in `js/src/chain.ts`).

The ciphertext is in no event. A reader fetches it from the `push` transaction's calldata with `eth_getTransactionByHash`, checks that the transaction is addressed to EpochAnchor and calls `push`, and checks that `keccak256` of the decoded `ct` equals the event's `digest`.

## Errors

| error | raised by | when |
|---|---|---|
| `NotAuthorized()` | `push` | `canWrite(owner, msg.sender)` is false: a stranger, or a session key that is revoked, expired or never set. |
| `EmptyCiphertext()` | `push` | `ct` is zero bytes long. |
| `StaleHead(bytes32 expected, bytes32 got)` | `push` | `prev` is not the current head digest. `expected` is the digest on chain, `got` is the `prev` you sent. |
| `AuthorizationExpired()` | `setSessionKeyBySig` | `block.timestamp > deadline`. Checked before anything else. |
| `BadSignature()` | `setSessionKeyBySig` | The signature does not verify for the current nonce. [The signature setSessionKeyBySig checks](/docs/contract#the-signature-setsessionkeybysig-checks) lists every case. |
| `SeqNotMonotone()` | `setStartSeq` | `seq` is lower than the value already stored. |

### Selectors and topics

Computed from the signatures with `cast sig` and `cast sig-event`. Use them to name a raw revert or to filter logs by hand.

| signature | selector or topic0 |
|---|---|
| `push(address,bytes32,bytes32,bytes)` | `0xa2483825` |
| `setSessionKey(address,uint64)` | `0x580da310` |
| `revokeSessionKey(address)` | `0x84f4fc6a` |
| `setSessionKeyBySig(address,address,uint64,uint256,bytes)` | `0x5247dcff` |
| `setStartSeq(bytes32,uint64)` | `0x15e2058b` |
| `head(address,bytes32)` | `0x24e8393d` |
| `canWrite(address,address)` | `0xedf2c387` |
| `sessionKeyExpiry(address,address)` | `0x6844536f` |
| `startSeq(address,bytes32)` | `0x1408deb9` |
| `authNonce(address)` | `0x8b524b7a` |
| `DOMAIN_SEPARATOR()` | `0x3644e515` |
| `authorizationDigest(address,address,uint64,uint256,uint256)` | `0x09c9881f` |
| `NotAuthorized()` | `0xea8e4eb5` |
| `StaleHead(bytes32,bytes32)` | `0x7fe83496` |
| `BadSignature()` | `0x5cd5d233` |
| `AuthorizationExpired()` | `0x0f05f5bf` |
| `SeqNotMonotone()` | `0x4863002e` |
| `EmptyCiphertext()` | `0xdbe0cd78` |
| `Epoch(address,bytes32,address,uint64,bytes32,bytes32,uint64)` | `0x86da9d02e15b0a4ed66c7fca89e82bdb54f4f39993c59a4c9a5256f0eedf86bc` |
| `SessionKeySet(address,address,uint64)` | `0x0775f7c38a29f43cd7fbc9f49b6e6ce64501452fd077c83ed52fa3e847da5625` |
| `StartSeqSet(address,bytes32,uint64)` | `0x429767075b5fba88ebcab612058dbfc8613825fa68a59fa886f002c46636fa3e` |

## Session keys

A session key is a plain EOA, one per machine, that appends under the owner's name. The owner authorizes it once with an expiry. Until that timestamp is reached, the key may call `push` for any space of that owner; after it, the key gets `NotAuthorized`. Because `canWrite` compares with a strict `>`, a key stops working in the second its expiry is reached. `revokeSessionKey` ends it at once, in the same block. A session key can decrypt nothing; [Keys and custody](/docs/keys) covers how custody splits between the two keys.

`kint authorize payload`, `page` and `direct` set the expiry to now plus `--days` (default `30`) days, and `submit` sends the expiry `payload` printed. The five actions reach the contract like this:

- `kint authorize payload` prints the EIP-712 typed data for the owner to sign, with the current `authNonce(owner)` and a deadline 300 seconds out. `kint authorize submit --deadline <d> --expiry <e> --signature -` then sends `setSessionKeyBySig` from the session key, which pays the gas. `--signature -` reads the signature from stdin; a path is read and then deleted.
- `kint authorize page` serves a one-shot loopback page for a Base Account owner, and the account sends `setSessionKey(key, expiry)` itself. kint then polls `canWrite(owner, key)` until the key shows up.
- `kint authorize direct` sends `setSessionKey` from an owner key read from `KINT_OWNER_KEY` (env only, never argv), and refuses when that key is not the owner.
- `kint authorize burn-nonce` re-sends `setSessionKey` with the key's current expiry, from the account in `KINT_OWNER_KEY`, which only consumes the nonce. Like `direct`, it refuses when that account is not the owner.

`kint session-key show` prints the key's address, keystore path, balance, and, when an owner is known, `authorized` (from `canWrite`) and `expiry` (from `sessionKeyExpiry`). `kint session-key rotate` is local only: it moves the old keystore aside to `session.key.old` and creates a new key. The old key stays authorized on chain until its expiry. kint ships no command that sends `revokeSessionKey`, and the authorize page sends only `setSessionKey`, so to cut an old key off early the owner sends `revokeSessionKey(key)` (or `setSessionKey(key, 0)`) from their own wallet.

### The signature setSessionKeyBySig checks

The domain is `name "kint EpochAnchor"`, `version "1"`, `chainId`, `verifyingContract`. The signed type is:

```text
SessionKeyAuthorization(address owner,address key,uint64 expiry,uint256 nonce,uint256 deadline)
```

The contract reads `nonce` from `authNonce[owner]`, so the caller never passes it. This is a different EIP-712 domain from the vault message a wallet signs to derive the data key, so an authorization signature can never double as a derive signature. Because the separator is rebuilt from `block.chainid` on every call, a signature made for chain 8453 does not verify on a chain with another id, even one forked from Base.

Checking splits on whether the owner address has code:

- **Deployed contract account** (`owner.code.length > 0`). The contract calls ERC-1271 `isValidSignature(digest, signature)` on the owner and requires the magic value `0x1626ba7e`. Any other `bytes4`, or a revert inside the account, is `BadSignature`. A reply that does not decode as a `bytes4` (too short, say) reverts without an error name instead, because Solidity's `try`/`catch` does not catch a failure to decode the return data.
- **No code** (an EOA, or a smart account that is not deployed yet). The signature must be exactly 65 bytes laid out as `r || s || v`. A `v` of 0 or 1 is normalised to 27 or 28, and any other `v` is rejected. An `s` above half the secp256k1 order is rejected, so `s` has one encoding. `ecrecover` must return the owner and never the zero address. Every failure is `BadSignature`.

A signature that already went through is rejected on replay, because the nonce it signed over has moved on. That is also `BadSignature`, not a separate error.

> **Warning.** A counterfactual smart account cannot use `setSessionKeyBySig`. A Base Account that has never sent a transaction has no code, so the contract takes the ecrecover path and rejects its signature, and ERC-6492 wrapped signatures are deliberately not supported. The account must send `setSessionKey(key, expiry)` itself: that one transaction deploys the account and authorizes the key. After that the account has code, and `setSessionKeyBySig` works for every later key. `kint authorize page` does exactly this.

The live Base Account `0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3` went through that path on Sep 9 2026. Its own `setSessionKey` transaction, sent from kint's authorize page, deployed it, and its machine then anchored an epoch ([tx](https://basescan.org/tx/0x9c64e2c21b294843888680bd34d6da8242cb5313bc894864552163e167049c12), block 51082012). The fork suite checks both sides: an address with no code falls through to ecrecover and fails, and the now-deployed account takes the ERC-1271 path.

### Why owner actions consume the nonce

`setSessionKey` and `revokeSessionKey` both increment `authNonce[msg.sender]`, even though neither checks a signature. The point is revocation. Suppose the owner signs a long authorization for a machine, the machine holds it back without submitting it, and the owner later revokes that machine's key. Without the increment, the machine could submit the withheld signature and re-arm itself. With it, any signed-but-unsubmitted authorization dies the moment the owner acts on chain. The unit tests `test_RevokeInvalidatesUnspentAuthorization` and `test_SetSessionKeyInvalidatesUnspentAuthorization` pin this down. `kint authorize burn-nonce` exists for when you want that cancellation without changing any key.

## Reading the head with cast

Every read is a free `eth_call`, and nothing below needs a key. The space is the keccak of the literal string `kint-space-v1` followed by the tenant id, which `cast keccak` computes from the string's bytes.

For any owner and tenant:

```sh
OWNER=0xYourOwnerAddress
TENANT=your-tenant-id
cast call 0xa22E03f7a4145Bf4909a83595C90a38E14d79600 \
  "head(address,bytes32)(bytes32,uint64,uint64)" \
  "$OWNER" "$(cast keccak "kint-space-v1$TENANT")" \
  --rpc-url https://mainnet.base.org
```

For the demo tenant `kint-demo`, `cast keccak "kint-space-v1kint-demo"` returns `0xbd2a3b5b8f3fb4c81658d863b90018f1af511c28b33356fc81c2de406be98cb0`. Its first 16 hex characters are the `space bd2a3b5b8f3fb4c8` that `kint status` prints. With the demo owner:

```sh
cast call 0xa22E03f7a4145Bf4909a83595C90a38E14d79600 \
  "head(address,bytes32)(bytes32,uint64,uint64)" \
  0xC635e6Eb223aE14143E23cEEa9440bC773dc87Ec \
  0xbd2a3b5b8f3fb4c81658d863b90018f1af511c28b33356fc81c2de406be98cb0 \
  --rpc-url https://mainnet.base.org
```

```text
0x7df5378a8c4fa8664365cf8956033cac2f4e3cbf7a4767a377d759b262f01a13
2
51081880
```

The three values come back in order: the head digest, its seq, and the block it landed in (some cast versions append a scientific-notation hint to the block, such as `[5.108e7]`). This is epoch 2 of the demo memory, whose ciphertext is the calldata of [`0x369907fb…`](https://basescan.org/tx/0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729). If the demo anchors more epochs, the seq and block rise. Read the block as an upper bound: the head existed no later than that block. `kint status` prints the same head on its `chain head:` line (the seq, the first 16 hex characters of the digest, the block, whether this machine is in step, and the contract address).

The other reads take the same shape:

```sh
KEY=0xSessionKeyAddress
SPACE="$(cast keccak "kint-space-v1$TENANT")"
cast call 0xa22E03f7a4145Bf4909a83595C90a38E14d79600 "canWrite(address,address)(bool)" "$OWNER" "$KEY" --rpc-url https://mainnet.base.org
cast call 0xa22E03f7a4145Bf4909a83595C90a38E14d79600 "sessionKeyExpiry(address,address)(uint64)" "$OWNER" "$KEY" --rpc-url https://mainnet.base.org
cast call 0xa22E03f7a4145Bf4909a83595C90a38E14d79600 "authNonce(address)(uint256)" "$OWNER" --rpc-url https://mainnet.base.org
cast call 0xa22E03f7a4145Bf4909a83595C90a38E14d79600 "startSeq(address,bytes32)(uint64)" "$OWNER" "$SPACE" --rpc-url https://mainnet.base.org
```

## Gas

The contract's own execution is flat and small. `contracts/README.md` records 61,409 gas for a 4 KB epoch and 139,387 for a 100 KB one (storage write, event, keccak); `test_GasForFourKilobyteAndHundredKilobytePushes` logs that execution-only delta. That is not the bill. Since EIP-7623 (live on Base since the Isthmus upgrade), a transaction is charged `max(standard, 21000 + 10 * (zeros + 4 * nonzeros))`. An AES-GCM ciphertext is almost all nonzero bytes, so that works out to 40 gas per byte, and the floor absorbs execution at every bucket. Measured on a Base fork at block 51,081,018, the receipt's `gasUsed` equals the floor exactly:

| bucket | calldata bytes | gasUsed |
|---|---|---|
| 4 KB | 4,356 | 191,040 |
| 8 KB | 8,452 | 355,390 |
| 16 KB | 16,644 | 681,840 |
| 32 KB | 33,028 | 1,336,090 |
| 64 KB | 65,796 | 2,642,640 |
| 96 KB | 98,564 | 3,949,670 |

Base charges calldata a second time, as the L1 data fee in the receipt's `l1Fee`. A 4 KB epoch costs about 0.000002 ETH on Base all in; the exact figure moves with the base fee (`contracts/README.md` works it out at about 0.000001 ETH at a 0.005 gwei base fee). kint records the real `gasUsed`, `effectiveGasPrice` and `l1Fee` from every receipt. Deploying costs 879,343 gas on a Base fork, and the mainnet deploy receipt shows 885,843. Restoring and reading never send a transaction. [Epochs on Base](/docs/epochs) covers what goes into the calldata.

## Deploying your own copy

You do not need to: every owner uses the one deployment, and its heads are keyed by owner. If you want your own, build first so the artifact exists, then run the Python helper from the repository root:

```sh
(cd contracts && forge build)
export KINT_RPC_URL=...          # a Base mainnet endpoint
export KINT_DEPLOYER_KEY=0x...   # env only, never a flag, never printed
env -u PYTHONPATH .venv/bin/python contracts/deploy.py
```

It stops when either variable is unset, when the build artifact is missing, when the RPC cannot be reached or reports a chain other than 8453 (`wrong chain: RPC reports N, expected 8453`), or when the deployer has no ETH. It estimates gas, adds 20 percent, sends an EIP-1559 transaction, prints the hash, address, `gasUsed`, `effectiveGasPrice` and the Base `l1Fee`, and overwrites `contracts/deployments/base-mainnet.json` with the address, transaction hash, block number, chain id, deployer and ABI. The forge equivalent, run from `contracts/`, is `forge script script/Deploy.s.sol:Deploy --rpc-url "$KINT_RPC_URL" --broadcast` plus a signer flag such as `--ledger`. Point kint at the new address with `KINT_CONTRACT` ([Configuration](/docs/configuration)); epochs anchored at the old address stay there.

## Tests

The forge suite is 29 tests. `contracts/test/EpochAnchor.t.sol` has 25 unit tests covering push chaining, stale heads, empty payloads, independent spaces, expiry, revocation, EOA and ERC-1271 signatures, replay, high `s`, wrong length, past deadlines, a reverting account, `startSeq` monotonicity, the chain-id-bound domain separator, and the two nonce-consumption cases. `contracts/test/EpochAnchor.fork.t.sol` has 4 tests against a Base mainnet fork of `https://mainnet.base.org`, and it skips itself cleanly when the network is unreachable.

Run them from `contracts/`:

```sh
export FOUNDRY_DISABLE_NIGHTLY_WARNING=1
forge build
forge test -vv                                     # unit suite plus the Base fork suite
forge test -vv --no-match-path 'test/*.fork.t.sol' # offline
```

## Limits

- `push` checks who writes, not what. An authorized session key can append an epoch that no key opens; how kint gets past one, including the owner's `--over-skipped` snapshot, is in [Epochs on Base](/docs/epochs#an-epoch-nobody-can-open). Revoke a leaked key first.
- There is no owner rotation. If the owner key is lost, new writes for every space of that owner stop once its session keys expire. Reads never need the owner key.
- The ciphertext lives only in transaction calldata, and reading it back depends on the node keeping a transaction index. kint keeps its own ciphertext cache per epoch as the backup copy. The L1 data availability window is the blob retention window, not forever. [Limits and threat model](/docs/limits) has the rest.

Read [Browser core](/docs/kint-core) next.

Source: [`contracts/src/EpochAnchor.sol`](https://github.com/s0nderlabs/kint/blob/main/contracts/src/EpochAnchor.sol), [`contracts/README.md`](https://github.com/s0nderlabs/kint/blob/main/contracts/README.md), [`contracts/abi/EpochAnchor.json`](https://github.com/s0nderlabs/kint/blob/main/contracts/abi/EpochAnchor.json), [`contracts/deployments/base-mainnet.json`](https://github.com/s0nderlabs/kint/blob/main/contracts/deployments/base-mainnet.json), [`contracts/deploy.py`](https://github.com/s0nderlabs/kint/blob/main/contracts/deploy.py), [`contracts/test/EpochAnchor.t.sol`](https://github.com/s0nderlabs/kint/blob/main/contracts/test/EpochAnchor.t.sol), [`contracts/test/EpochAnchor.fork.t.sol`](https://github.com/s0nderlabs/kint/blob/main/contracts/test/EpochAnchor.fork.t.sol), [`src/kint/chain.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/chain.py), [`src/kint/cli.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/cli.py), [`js/src/chain.ts`](https://github.com/s0nderlabs/kint/blob/main/js/src/chain.ts).
