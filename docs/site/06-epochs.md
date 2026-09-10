---
slug: epochs
title: Epochs on Base
description: What one epoch carries, how it is sealed, where it lives on Base, and what it costs.
group: Concepts
order: 6
source: 'src/kint/crypto.py'
---

# One change set, one transaction, one digest on chain.

An epoch is the unit kint writes to Base: a set of rows, compressed, padded, encrypted and sent as the calldata of one `push` transaction.

## What an epoch is

This page covers what goes inside one, the exact bytes of the envelope, how a reader finds epochs again, and what each one costs.

Every epoch belongs to one owner and one space. The space is `keccak256("kint-space-v1" || tenant)`, so each Sibyl tenant has its own chain of epochs under the same wallet. Epochs are numbered from 1 (`seq`), and each one names the digest of the epoch before it (`prev`, 32 zero bytes for the first).

For each `(owner, space)`, EpochAnchor keeps the head: the latest digest, its `seq` and the block it landed in. `push(owner, space, prev, ct)` reverts with `StaleHead(expected, got)` unless `prev` equals the current head digest, so the chain only ever grows at the end and two writers cannot both extend the same head.

A push runs after Sibyl's write has returned, never inside it; the export reads the store read-only. It happens when you run `kint push`, when the agent calls `memory_push`, when kint-server's watcher fires (after `KINT_QUIET_SECONDS` of quiet, default 300, or on its size trigger), and best effort on exit. When nothing changed, push anchors nothing and says `nothing to push: the store matches the last anchored epoch`.

## Diff epochs and snapshot epochs

| | diff epoch | snapshot epoch |
|---|---|---|
| `rows` | only the rows whose leaf changed since the last anchored epoch | every row in the store (the full state) |
| `deleted` | rows removed since the last anchored epoch | the same list, kept for history only |
| header flags | `0x00` | `FLAG_SNAPSHOT` (`0x02`) |
| plaintext key | absent | `"snapshot": true`, the last key |
| `rows_root` | root of the mirror plus this epoch's changes | root of exactly its own rows |
| written by | `kint push`, `memory_push()`, the watcher, the exit hook | `kint compact`, `memory_push(snapshot=true)`, `kint rekey` |

A snapshot is written even when the diff is empty; that is the point of `kint compact` and of a key rotation. A pull without `--full` stops walking at the newest snapshot, so restore cost is bounded by the size of the memory, not its history. `kint pull --full` (and `memory_pull(full=true)`) walks past snapshots, and afterwards caches, for history, every epoch from the head back to the first that this machine has not decrypted yet, including the diff epochs an earlier pull jumped when it stopped at a newer snapshot. The deletions a snapshot carries are already absent from its `rows`; history and `at_block` use them to record when a row disappeared.

The other defined flag, `0x01` (a signature wrap salted with a passphrase), is set by no kint writer. A reader must not branch on it, and unknown bits are reserved: ignore them, never refuse on them.

### Why the flag and the key must agree

The flags byte sits in the header, which a reader parses before it decrypts anything: that is how a walk knows where to stop. The flags are not part of the AAD (below), so the AES-GCM tag says nothing about them. A writer holding a session key but not the data key can still set that bit. The plaintext `"snapshot"` key lives inside the ciphertext, so it is covered by the tag.

kint acts on a snapshot only when both say the same thing. On a pull, an epoch whose header flag and plaintext key disagree is a gap: the pull stops there with the reason `snapshot flag disagrees between header and plaintext`, and the mirror stays at the last epoch it applied. If a walk stopped at an epoch that claims to be a snapshot and that epoch does not open, kint logs `pull: epoch N claims to be a snapshot but cannot be applied; walking the full history instead`, applies the epochs before it, and reports it by name. The browser core runs the same check (`assertEpochConsistent`) and the same provisional stop (`coldStartEvents`, which names the refused epoch in `refusedSnapshotSeq`); see [Browser core](/docs/kint-core).

The plaintext key is present only on a snapshot, so every ordinary epoch stays byte-identical to the v1 format.

## The plaintext

Before anything is compressed, an epoch is one JSON document, serialised with no spaces (`separators=(",", ":")`, `ensure_ascii=False`, UTF-8) in this key order. Abridged, with placeholders where values vary; the row shown is the demo tenant's release rule (`rules/release-gate`), the row epoch 2 rewrote:

```json
{
  "v": 1,
  "tenant": "kint-demo",
  "space": "<64 hex: keccak256(\"kint-space-v1\" || tenant)>",
  "seq": 2,
  "prev": "<64 hex: digest of epoch 1>",
  "rows": [
    {"tier": "entity", "key": "release-gate", "category": "rules", "status": "<stored status>",
     "body": "<the exact stored TEXT>", "meta": null, "ts": "<stored updated_at>",
     "evaluated": null, "acted": null, "forward": null, "extra": null}
  ],
  "deleted": [["<tier>", "<category or null>", "<key>"]],
  "rows_root": "<64 hex: root of the full state after this epoch>",
  "n_rows": "<integer: rows in the full state after this epoch>",
  "created_at": "<UTC, %Y-%m-%dT%H:%M:%SZ>"
}
```

- `rows` are wire rows: `tier`, `key`, `category`, `status`, `body`, `meta`, `ts`, `evaluated`, `acted`, `forward`, `extra`. The local `rowid` and journal uuid are dropped.
- `body`, `meta` and the journal fields are the exact stored TEXT from Sibyl's tables, never re-serialised. Sibyl's `dumps()` keeps insertion order on purpose; a re-serialised hash would refuse every row on the next machine.
- `deleted` entries are `[tier, category or null, key]`.
- `n_rows` is the total row count after the epoch. `created_at` is the writer's own clock; kint states when a row existed as a block height upper bound instead.

## Leaves and rows_root

Every row has a canonical id, `tier\0category\0key` (empty category outside entities), and a leaf. With `lp(x) = uint32(len) || utf8(x)` (big-endian) and `lp(null) = 0xFFFFFFFF`:

```text
entity, state, reference:
  leaf = keccak256("kint-leaf-v1" || lp(tier) || lp(category) || lp(key) || lp(status) || lp(body) || lp(meta))

journal:
  leaf = keccak256("kint-leaf-v1" || lp("journal") || lp(null) || lp(key) || lp(null)
                   || lp(ts) || lp(evaluated) || lp(acted) || lp(forward) || lp(extra))
  key  = hex(keccak256("kint-journal-key-v1" || lp(ts) || lp(evaluated) || lp(acted) || lp(forward) || lp(extra)))
```

Timestamps Sibyl regenerates on replay (`updated_at` on entities, state and reference) are not in the leaf. The journal `ts` is content and is. Journal rows get a new uuid on replay, so their key is their content; a second identical event gets `:1`, a third `:2`, assigned in rowid order.

`rows_root` is the merkle root over the leaves of the full state after the epoch, sorted by canonical id. Pairs hash as `keccak256(left || right)`, an odd last node is carried up unchanged, and an empty state has the root `keccak256("kint-empty-v1")`. Because it covers the whole state, a single row can be proven against any one epoch's `rows_root` with a merkle path; see [Verify before acting](/docs/verify).

## Sealing the payload

1. **Compress.** `gzip` at level 9 with `mtime 0`, so the same plaintext compresses to the same bytes.
2. **Pick a bucket.** The smallest of 4096, 8192, 16384, 32768, 65536 or 98304 bytes that holds the compressed length plus 4. The choice ratchets per space: an epoch never uses a smaller bucket than the one before it.
3. **Pad.** `padded = uint32(len(gz)) || gz || zeros` up to the bucket.
4. **Encrypt.** AES-256-GCM under the space's data key, a fresh random 12-byte nonce, and the AAD below. The ciphertext is exactly `bucket + 16` bytes (the GCM tag).
5. **Frame.** `blob = header || ciphertext`. That blob is the `ct` argument of `push`.

Only the bucket is public. The true compressed length is the first four bytes of the padded payload, inside the ciphertext.

## The header

Big-endian, byte-exact. The fixed part is 59 bytes, and each wrap adds 77.

| offset | bytes | field | contents |
|---|---|---|---|
| 0 | 1 | `version` | `0x01`; anything else is refused as `unsupported envelope version` |
| 1 | 1 | `flags` | `0x02` snapshot; `0x01` defined, never set |
| 2 | 12 | `gcm_nonce` | the AES-GCM nonce of the payload |
| 14 | 32 | `rows_root` | merkle root of the full state after this epoch |
| 46 | 8 | `dek_id` | `HMAC-SHA256(DEK, "kint-dek-id-v1")[:8]` |
| 54 | 4 | `lenBucket` | the padded length (one of the six buckets) |
| 58 | 1 | `n_wraps` | how many wraps follow |
| 59 | 77 each | wraps | `kek_kind` (1), `kek_tag` (16), `wrap_nonce` (12), `wrapped_dek` (48) |

Each wrap is the data key encrypted under one key-encryption key: `AES-256-GCM(KEK, wrap_nonce, DEK, aad = "kint-wrap-v1" || kek_kind || kek_tag)`. Kinds are `0x01` wallet signature, `0x02` passphrase, with `0x03` and `0x04` reserved. A reader finds its wrap by comparing `kek_tag`, never by trial decryption, because GCM does not commit to its key. Every epoch carries its own wraps, which is why a wiped machine gets the data key out of the head epoch's header. [Keys and custody](/docs/keys) covers how each KEK is derived.

Opening checks the ciphertext length against `lenBucket + 16` and the `dek_id` against the key in hand (`dek_id mismatch: wrong data key for this epoch`) before it decrypts.

## The AAD

```text
aad = keccak256(abi.encode(
    uint256 chainId,      8453
    address owner,
    bytes32 space,
    uint64  seq,
    bytes32 prev,
    uint32  lenBucket,
    bytes32 rows_root,
    bytes8  dek_id))
```

Chain id, owner and space pin an epoch to one vault on Base. `seq` and `prev` pin it to one position, so a valid ciphertext cannot be replayed at another. `lenBucket`, `rows_root` and `dek_id` bind the header fields a reader acts on to the payload. What the AAD leaves out: the version byte, the flags byte, the nonce itself, and the wraps, which carry their own AAD.

## Why calldata

For each `(owner, space)` the contract stores a digest, a sequence number and a block number, and its `Epoch` event carries the digest. The ciphertext itself is never copied to storage or into an event: it stays in the calldata of the `push` transaction that carried it there. Base charges those bytes as calldata: L2 gas under the EIP-7623 floor, plus the L1 data fee. The contract's own work (the head write, the event, the keccak) is flat, 61,409 gas at 4 KB and 139,387 gas at 100 KB, and the calldata floor absorbs it at every bucket, so the calldata is the bill. A root alone on Base is a receipt for data you still have to keep somewhere else; here the calldata is the store.

## The Epoch event and the prevBlock walk

```solidity
event Epoch(address indexed owner, bytes32 indexed space, address indexed writer,
            uint64 seq, bytes32 prev, bytes32 digest, uint64 prevBlock);
```

`writer` is the address that sent the push (the owner or a session key). `digest` is `keccak256(ct)`. `prevBlock` is the block the previous head landed in, 0 for the first epoch. That field is what lets a reader walk backwards with one exact-block query per epoch:

1. Read `head(owner, space)` for the newest `seq` and its block.
2. Call `eth_getLogs` with `fromBlock` and `toBlock` both set to that block, filtered by the contract, the `Epoch` topic, the owner and the space, and take the event with the wanted `seq`. If it is missing, the walk stops with `no Epoch event for seq N at block B; the RPC may be pruned or lying`.
3. Move to `prevBlock` and `seq - 1`. Repeat until `prevBlock` is 0, the walk reaches epochs this machine already applied, or, without `--full`, it reaches a snapshot.

Walking back from epoch 2 of the demo tenant takes two queries: block 51081880 for epoch 2, whose `prevBlock` points to 51081867 for epoch 1, whose `prevBlock` is 0. No query in the walk spans a block range, so no RPC range cap is hit. For each event, kint first checks `prev` continuity. Then it takes the ciphertext from the local cache, or fetches the transaction, requires it to call `push` on EpochAnchor with the same owner, space and `prev`, and requires `keccak256(ct)` to equal the event's digest. Only then does it open the epoch.

The writer checks the chain too. Before sending it compares the chain head with what this machine last saw and refuses if another machine pushed first (the owner's override [below](#an-epoch-nobody-can-open) is the one exception). After the transaction has its confirmations (`kint push --confirmations`, default 2), it reads the event back at the receipt's block and stops with `epoch N landed but the Epoch event digest does not match what was sent` if they differ.

If the transaction lands but the wait for its receipt or its confirmations fails (a timeout, an RPC that drops), this machine never records the epoch. Its next push then reads its own epoch as another machine's push, and its next pull calls the rows it sent a fork. `kint pull --discard-local` gets out of it: the chain already carries that epoch, so the restore brings those rows back, and only rows changed after that push stay behind in the `.kint-backup-` copy.

## An epoch nobody can open

`push` checks who writes, never what: any authorized writer can append any non-empty bytes as the next epoch. A session key holds no data key, so an epoch appended with a leaked one opens for nobody, and it sits in the chain like any other. kint deals with it in three places.

- **Pull.** A walk that goes past snapshots (`--full`) can meet an epoch this machine cannot open: its header does not parse, no key here opens it, or AES-GCM refuses it. When a later snapshot in the same walk opens, the pull resumes there, because a snapshot's rows are the whole state. It reports the epoch as skipped with `superseded_by` and ends complete. An epoch the RPC would not serve, or one that opened and contradicts the chain, is never walked past: nobody has read what is in it. A pull without `--full` starts at the newest snapshot and never opens what lies before it.
- **Connect and rekey.** When the head epoch does not parse as a kint header, they take the wraps from the newest epoch that does, walking back through `prevBlock` at most 32 epochs. `kint rekey` logs both steps.
- **The owner's snapshot.** Anywhere else the pull stops at the epoch, and push and verify refuse on that machine. The push refusal ends by naming `kint compact --over-skipped`. Run where the data key is cached, after a pull that recorded the gap, that command anchors a snapshot of this machine's store on top of the chain head, whatever sits between; `kint rekey --over-skipped` does the same while rotating the key. Every later pull stops at that snapshot and never needs the bad epoch.

The override is scoped on purpose: a snapshot, from a terminal, on a machine whose last pull reported an epoch it could not apply. No MCP tool takes it. It logs `push: OVERRIDE, anchoring a snapshot on top of chain head seq N (<12 hex>) although this machine stopped at seq M and could not apply epoch(s) [K]`. The snapshot carries this machine's store as it is, so run it where the memory is the one to keep, and revoke the leaked key first ([Keys and custody](/docs/keys#expiry-and-revocation)) or it can append again. Connect and rekey step over a header that does not parse and nothing else: a bad epoch with a well-formed header whose wraps none of your keys open still stops them until the owner's snapshot sits on top of it.

## Splitting a large diff

One epoch carries at most 90 KB (92,160 bytes) of compressed rows, measured rather than estimated: kint gzips the candidate chunk's rows and deletions and adds 512 bytes of headroom. Rows are added in order; when the next row would cross the limit, the chunk closes and a new epoch starts. Deletions travel in the first epoch. Each chunk is its own transaction, `seq` and `prev` chain them in order, and each carries the `rows_root` of the state after it.

A single row that does not fit on its own is refused by name before anything is sent (the category and its slash appear only for entities):

```text
row <tier> <category>/<key> compresses to more than 90 KB on its own and cannot fit one epoch; shrink or split it in Sibyl (push refuses until then, nothing else is blocked)
```

A snapshot is always a single epoch. When the full state is over the limit, `kint compact` refuses with `the full state (N rows) compresses to S bytes, more than the 92160 bytes one epoch can carry, and snapshots are single-epoch`, and ordinary epochs keep working. `--dry-run` on `kint push` or `kint compact` reports what would be anchored and sends nothing.

## What it costs

Base charges calldata under EIP-7623's floor, `max(standard, 21000 + 10 * (zeros + 4 * nonzeros))`. Ciphertext is almost all nonzero bytes, so that comes to 40 gas per byte, and the floor absorbs the contract's own execution at every bucket. Measured on a Base fork at block 51,081,018, the receipt's `gasUsed` equals the floor exactly:

| bucket | calldata bytes | gasUsed |
|---|---|---|
| 4 KB | 4,356 | 191,040 |
| 8 KB | 8,452 | 355,390 |
| 16 KB | 16,644 | 681,840 |
| 32 KB | 33,028 | 1,336,090 |
| 64 KB | 65,796 | 2,642,640 |
| 96 KB | 98,564 | 3,949,670 |

On top of that comes the L1 data fee, reported as `l1Fee` in the receipt. All in, a 4 KB epoch costs about 0.000002 ETH on Base. Epoch 1 of the demo tenant carried 14 rows in the 4 KB bucket ([tx](https://basescan.org/tx/0xbe9bb8596c825a8891c3eafe4381e0c6522d647641735c635ca58fcf4bbe4455), block 51081867); epoch 2 followed at block 51081880 ([tx](https://basescan.org/tx/0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729)). kint records the real `gasUsed`, `l1Fee` and total from every receipt in the push report. Restoring and reading never send a transaction.

## Where the bytes live

The ciphertext lives only in transaction calldata. Reading it back goes through `eth_getTransactionByHash`, which needs a node that keeps its transaction index, and the walk needs `eth_getLogs`. Base's data availability on L1 is the blob retention window, not forever.

So kint keeps its own copy. Every epoch a push sends or a pull fetches goes into a local cache under `KINT_HOME` (default `~/.kint`):

```text
~/.kint/epochs/<first 16 hex of the space>/
├── 00000001.bin          the ciphertext, byte for byte as sent
├── 00000001.json         the decrypted plaintext
├── 00000001.meta.json    seq, digest, prev, block, tx, bucket, rows_root, writer
└── 00000002.bin ...
```

A pull reads the cache first and trusts a cached blob only when its keccak equals the digest in the `Epoch` event; anything else is fetched from calldata again. The decrypted `.json` files also feed `memory_history` and the read of a row at an earlier block. The directory sits outside every path Sibyl's cap accounting walks, and kint volunteers its size into that cap.

> **Note.** The cache is a backup of the ciphertext, not a replacement for the chain. The chain still decides which epochs exist and which digest each one must have; the cache only saves a fetch on a machine that already holds it. Files are written with mode 0600, and `KINT_HOME` itself is mode 0700.

Read [Verify before acting](/docs/verify) next.

Source: [`src/kint/crypto.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/crypto.py), [`src/kint/canon.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/canon.py), [`src/kint/push.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/push.py), [`src/kint/epoch.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/epoch.py), [`src/kint/chain.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/chain.py), [`src/kint/pull.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/pull.py), [`contracts/src/EpochAnchor.sol`](https://github.com/s0nderlabs/kint/blob/main/contracts/src/EpochAnchor.sol), [`contracts/README.md`](https://github.com/s0nderlabs/kint/blob/main/contracts/README.md), [`docs/frontend-contract.md`](https://github.com/s0nderlabs/kint/blob/main/docs/frontend-contract.md).
