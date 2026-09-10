---
slug: kint-core
title: Browser core
description: The TypeScript package a page uses to read a wallet's epochs off Base and open them locally.
group: Reference
order: 12
source: 'js/src/index.ts'
---

# Nothing decrypted leaves the page.

`js/` is `@s0nderlabs/kint-core`, a framework-free TypeScript port of kint's Python crypto. It exists so a page can read a wallet's epochs off Base and open them in the browser, with nothing decrypted ever leaving it.

## What it is for

The package does the reader's half of kint and nothing else. It derives the KEK from a wallet signature or a passphrase, finds a wrap by its tag, unwraps the data key, walks EpochAnchor from head to genesis, decodes each epoch's ciphertext out of the `push` calldata, opens it, cross-checks the plaintext against the header, and folds the rows into a state.

There is deliberately no seal in it. The machine that holds the Sibyl store is the only thing that writes an epoch. The package uses exactly three RPC methods, all reads (`readContract`, `getLogs`, `getTransaction`), and every byte they fetch is public ciphertext.

Every format here is a port of `src/kint`, and each one is pinned by vectors the Python itself generates, so the two languages cannot drift apart quietly. See [The vectors](/docs/kint-core#the-vectors).

## Status

| Field | Value |
|---|---|
| Package | `@s0nderlabs/kint-core` |
| Version | 0.3.0, the same as the Python |
| License | MIT |
| Published | No. `"private": true` in `js/package.json`, so it is not on npm |
| Module format | ESM only (`"type": "module"`) |
| Entry point | `./src/index.ts`, which both `main` and `exports` name |

There is no build step and no bundle: the entry point is the TypeScript source, so an app compiles it with its own bundler. Because it is not published, a page consumes it from the repository (a workspace, a link or a vendored copy).

Dependencies are pinned exactly: `@noble/hashes` 2.4.0 (keccak, SHA-256, HMAC, HKDF, scrypt), `fflate` 0.8.3 (gunzip), `viem` 2.56.3 (address checksums, EIP-712 hashing, ABI coding, signature recovery, the `PublicClient` seam). Dev dependencies are `typescript` 5.9.3 and `@types/bun` 1.4.2. AES-256-GCM is not a dependency: it comes from WebCrypto, so the page needs a secure context. Without one, every decrypt fails and the error carries `WebCrypto subtle is unavailable; kint needs a secure context`.

## Install and test

From the repository root:

```sh
cd js
bun install
bun test          # 110 tests
bun run typecheck # tsc --noEmit
```

The 110 tests split as 8 for `bytes`, 21 for `derive` (typed data, the KEK paths, the `dek_id` and the recovery code), 23 for `canon`, 32 for `envelope` and 26 for `chain`.

`bun run open-epoch` is the cross-language check: it opens one Python-sealed blob with the TypeScript path and prints the plaintext.

```sh
KINT_DEK=<64 hex chars> bun run scripts/open-epoch.ts <blob-file> \
    --owner 0x... --tenant demo [--seq 1] [--prev <64 hex chars>] [--raw]
```

`--space <64 hex chars>` replaces `--tenant` when the caller already holds the 32-byte space id. `--seq` defaults to 1 and `--prev` to 32 zero bytes. `--raw` writes the plaintext bytes to stdout with no trailing newline. `--help` prints the usage. The data key comes from `KINT_DEK` and never from argv, because a process list is public on a shared machine. The script goes through `readEpoch`, so a blob whose header disagrees with its plaintext exits 1 naming the field instead of printing the forged flag as fact.

## The API by module

Everything is re-exported from `src/index.ts`, so an app imports from the package root. The package's own refusals throw `KintCryptoError`, which has the same shape as Python's `KintCryptoError`.

### typedData

The one frozen EIP-712 payload the owner signs. That signature is a secret, not a credential: it IS the key, so the page must never send it anywhere and never accept it as a login. See [Keys and custody](/docs/keys).

- `typedData(owner: string): KintVaultTypedData`. The payload with the owner checksummed.
- `canonicalPayloadJson(owner: string): string`. Byte-stable JSON with a trailing newline, byte-equal to Python's `canonical_payload_json`; this is what `cast wallet sign --data --from-file` reads.
- `vaultDigestHex(owner: string): Hex` and `vaultDigest(owner: string): Uint8Array`. `keccak256(0x19 0x01 || domainSeparator || hashStruct(KintVault))`.

### kek

- `spaceId(tenantId: string): Uint8Array`. `keccak256("kint-space-v1" || tenant)`, 32 bytes.
- `owner20(owner: string): Uint8Array`. The 20 raw bytes of a checksummed address.
- `kekInfo(owner: string, space: Uint8Array): Uint8Array`. `"kint-kek-v1" || owner20 || space`, always 63 bytes.
- `parseSignature(sig: Uint8Array): ParsedSignature`. Returns `{ r, s, v }` with `v` normalised to 0 or 1. Refuses anything but 65 bytes, a `v` outside 27/28/0/1, or an `r` or `s` outside the curve order.
- `normaliseLowS(sig: Uint8Array): { sig: Uint8Array; r: bigint; s: bigint }`. A malleated twin derives the same KEK.
- `recoverSigner(digest: Uint8Array, sig: Uint8Array): Promise<string>`. The checksummed address that produced the signature.
- `passphraseStretch(passphrase: string, owner: string): Uint8Array`. `scrypt` with N = 2^17 (131072), r = 8, p = 1, dkLen = 32, salt = `owner20`, maxmem 536870912 bytes. UTF-8 as typed, with no Unicode normalisation, exactly like Python's `str.encode`. An empty passphrase throws `empty passphrase`, as the Python does.
- `kekTag(kek: Uint8Array): Uint8Array`. `HMAC-SHA256(kek, "kint-kek-check-v1")[:16]`, how a client finds its own wrap without trial-decrypting.
- `kekFromSignature(sig, owner, space, passphrase?, opts?): Promise<Kek>`. Kind `0x01`. `opts` takes `digest` and `signer`; `signer` defaults to `owner` and is the EOA whose 65 bytes are the ikm when the owner is an EOA-owned smart account. The recover check is hard, never behind a `try`: a signature that recovers to anyone else throws `derive signature recovers to <address>, expected <address>; refusing to derive a key from it` rather than deriving a silently different key. With a passphrase the HKDF salt is `passphraseStretch`; without one it is empty.
- `kekFromPassphrase(passphrase, owner, space): Kek`. Kind `0x02`, the wallet-free path a Base Account owner uses.

Both return `{ kek, tag }`.

### envelope

- `dekId(dek: Uint8Array): Uint8Array`. `HMAC-SHA256(dek, "kint-dek-id-v1")[:8]`.
- `parseWrap(b: Uint8Array): Wrap` and `wrapToBytes(w: Wrap): Uint8Array`. A wrap is `kind(1) | kek_tag(16) | wrap_nonce(12) | wrapped_dek(48)`, 77 bytes.
- `findWrap(wraps: readonly Wrap[], kekTagBytes: Uint8Array): Wrap | null`. Compares tags; it never trial-decrypts.
- `unwrapDek(wrap, kek, kekTagBytes = kekTag(kek)): Promise<Uint8Array>`. The tag must match before AES is touched, because AES-GCM is not key-committing. The default is the tag of the key you passed, which is the only value that makes the check mean anything; passing `wrap.tag` compares the wrap to itself and disables it. A mismatch throws `kek_tag mismatch: this key does not open this wrap`, and a wrap that fails to authenticate throws `wrap did not authenticate`.
- `decodeRecoveryCode(code: string): Uint8Array`. Base32 of `DEK || sha256(DEK)[:2]`, accepting the grouped, lowercase and space-separated forms a user actually types. A typo fails on the checksum: `recovery code checksum failed (typo?)`.
- `bucketFor(length: number): number` and `nextBucket(length: number, previousBucket: number): number`. The buckets are 4096, 8192, 16384, 32768, 65536 and 98304 bytes, and the ratchet is monotone per space.
- `unpad(padded: Uint8Array): Uint8Array`. `uint32(len) || gz || zeros` back to `gz`.
- `parseHeader(blob: Uint8Array): { header: Header; offset: number }`, `peekHeader(blob): Header`, `isSnapshotHeader(header): boolean`. The fixed header is 59 bytes: `version(1) | flags(1) | nonce(12) | rows_root(32) | dek_id(8) | bucket(4) | n_wraps(1)`, then the wraps.
- `epochAad(input: EpochAadInput): Uint8Array`. `keccak256(abi.encode(chainId, owner, space, seq, prev, bucket, rows_root, dek_id))`.
- `openEpoch(blob, input: OpenEpochInput): Promise<OpenedEpoch>`. `input` is `{ dek, owner, space, seq, prev }`. It checks the ciphertext length against `bucket + 16`, checks `dekId(dek)` against the header (`dek_id mismatch: wrong data key for this epoch`), builds the AAD and decrypts, then gunzips. A wrong key, seq, prev, owner or space all land on `epoch did not authenticate: wrong key, wrong seq/prev/owner/space, or tampered ciphertext`.
- `ciphertextDigest(ct): Uint8Array` and `ciphertextDigestHex(ct): Hex`. The digest the `Epoch` event carries.

### epoch

- `parsePlaintext(data: Uint8Array | string): EpochPlaintext`. Refuses any version but 1. The document is `{ v, tenant, space, seq, prev, rows, deleted, rows_root, n_rows, created_at, snapshot }`, and `snapshot` is `true` only when the plaintext carries the key.
- `assertEpochConsistent(header, doc, expected: EpochExpectation): void`. `expected` is `{ seq, prev, spaceHex }`, each of which takes raw bytes or hex with or without `0x`, in either case. See below.
- `readEpoch(blob, input: OpenEpochInput): Promise<ReadEpoch>`. `openEpoch` plus `parsePlaintext` plus `assertEpochConsistent`, returning `{ header, doc, plaintext }`.
- `applyEpoch(state: RowState, header: Header, doc: EpochPlaintext): AppliedEpoch`. Folds one epoch into a row map and returns `{ state, root, rootHex, snapshot, matchesRowsRoot, dropped }`. The state passed in is never mutated; use the one that comes back. `dropped` names the row ids the prior state held and this epoch does not, which is what a viewer shows as gone rather than unchanged.

The two epoch kinds apply differently, and getting it wrong is how a viewer shows a row its owner deleted. An ordinary epoch is a diff: set `doc.rows`, then delete `doc.deleted`. A snapshot epoch (`FLAG_SNAPSHOT`, `0x02`) replaces the state: the map is cleared and set to exactly `doc.rows`, because a snapshot's rows are the whole state and its `rows_root` is the root of exactly those rows. Its `deleted` list is informational and is not needed to reach the anchored root, which is what lets a cold start stop at a snapshot. Merge one in as though it were a diff and every row the snapshot dropped survives, so `matchesRowsRoot` comes back false. More in [Epochs on Base](/docs/epochs).

### canon

- `lp(x: string | null | undefined): Uint8Array`. `uint32(len(utf8)) || utf8`, and `0xFFFFFFFF` for a null column.
- `journalContentKey(ts, evaluated, acted, forward, extra): string`. Journal rows get a new uuid on replay, so their identity is their content. A second identical event in one store carries the key with `:1` appended, a third `:2`, in rowid order; the exporter assigns that ordinal and it travels in the epoch's rows.
- `rowId(row: Row): string`. `tier \0 category \0 key`. An unknown tier throws; the tiers are `entity`, `state`, `reference` and `journal`.
- `deletedId(triple: readonly (string | null | undefined)[]): string`. The same id from the `[tier, category, key]` triple an epoch carries.
- `leaf(row: Row): Uint8Array`. `keccak256("kint-leaf-v1" || the length-prefixed columns)`. Nothing in this file ever re-encodes a body: the leaf hashes the exact stored text.
- `leavesOf(rows: readonly Row[]): Map<string, Uint8Array>` and `sortedIds(leaves: Leaves): string[]`. `Leaves` is a `Map` or a plain object.
- `merkleRoot(leaves: Leaves): Uint8Array`. Pairs hashed as `keccak256(left || right)`, an odd last node carried up unchanged, and the empty state is `keccak256("kint-empty-v1")`. The return is always a fresh array, so a careless write cannot corrupt the shared empty root.
- `merkleProof(leaves: Leaves, targetId: string): ProofStep[]` and `verifyProof(leafHash, proof, root): boolean`. A step is `{ sibling, siblingIsLeft }`.

### chain

Constants: `DEFAULT_CONTRACT` (EpochAnchor on Base mainnet, `0xa22E03f7a4145Bf4909a83595C90a38E14d79600`), `BASE_CHAIN_ID` (8453), `PUBLIC_RPC` (Base's public read endpoint), `EPOCH_EVENT` and `EPOCH_ANCHOR_ABI`, the reader's slice of the ABI (`head`, `sessionKeyExpiry`, `startSeq`, `push` and the `Epoch` event). The full ABI is `contracts/abi/EpochAnchor.json`; see [EpochAnchor contract](/docs/contract).

- `fromViem(client: PublicClient): EpochReadClient`. Wraps a viem client into the three-call seam the readers use. A fake object satisfies the same interface, which is how the walk is tested without a network.
- `readHead(client, contract, owner, space): Promise<Head>`. `{ digest, seq, blockNumber }`.
- `readSessionKeyExpiry(client, contract, owner, key): Promise<number>`. A unix second, 0 when the key was never authorized.
- `readStartSeq(client, contract, owner, space): Promise<number>`. The lowest seq the owner still vouches for.
- `epochsAtBlock(client, contract, owner, space, blockNumber): Promise<EpochEvent[]>`. One exact-block `eth_getLogs` for that owner and space.
- `walkEpochs(client, contract, owner, space, options?): Promise<EpochEvent[]>`. Head to genesis, newest first, hopping through each event's `prevBlock`, so no RPC log-range cap is ever hit. `WalkOptions` is `stopSeq` (an exclusive floor, default 0), `head` (skip the `head()` call when the caller has it), `maxEpochs` (default 100000) and `stopWhen`, evaluated after an event is appended and allowed to be async. A missing hop throws `no Epoch event for seq N at block B; the RPC may be pruned or lying`.
- `decodePushCalldata(data: Hex): PushCall`. `{ owner, space, prev, ct }`.
- `epochCiphertext(client, txHash, contract): Promise<PushCall>`. Fetches the transaction and refuses one not addressed to EpochAnchor: `tx <hash> is not addressed to EpochAnchor`. The contract argument is required, because without it a reader would decode `push()` calldata out of any transaction at all, and anyone can write that calldata.
- `assertCiphertextMatchesDigest(ct, digest): void`. The check a viewer must not skip: only `keccak256(ct)` matching the anchored digest makes those bytes the epoch the chain vouched for.
- `isSnapshotEvent(client, ev, contract): Promise<boolean>`. Fetches the calldata and peeks the header flag. An epoch whose header it cannot even read is not a place to stop, so it returns false rather than throwing.
- `coldStartEvents(client, contract, owner, space, options): Promise<ColdStart>`. The walk a cold start should use. Options are `stopSeq`, `head` and the required `tryOpen`. It returns `{ events, refusedSnapshotSeq, stoppedAtSnapshot }`, and `events` is oldest first, ready for `applyEpoch`.

### bytes

`utf8Bytes`, `utf8String` (a fatal UTF-8 decoder: invalid bytes throw), `concatBytes`, `bytesEqual` (every byte compared, no early exit, when the lengths match), `toHex`, `fromHex`, `to0x`, `normaliseAddress`, `u32be`, `readU32be`, `bytesToBigInt`, `bigIntTo32`, `compareCodePoints`, `sortCodePoints`, and the shared `encoder` and `decoder`.

`fromHex` validates the whole string before it parses a byte, because `parseInt` reads `"1z"` as 1 and a digest silently short of what the sender wrote is the bug this package exists to catch. `normaliseAddress` accepts the `0X` prefix that viem's `getAddress` rejects and re-checksums the body, exactly as Python's `to_checksum_address` does, so a caller that wants to reject a bad checksum has to compare its own input against what comes back.

### constants

The frozen values, ported byte for byte from `src/kint/crypto.py` and `src/kint/canon.py`.

| Constant | Value |
|---|---|
| `CHAIN_ID` | 8453 |
| `PURPOSE` | the one warning sentence the wallet renders |
| `DOMAIN`, `TYPES`, `PRIMARY_TYPE` | domain `kint` version `1`, type `KintVault(owner, purpose)` |
| `SPACE_PREFIX` | `kint-space-v1` |
| `KEK_INFO_PREFIX` | `kint-kek-v1` |
| `KEK_CHECK` | `kint-kek-check-v1` |
| `DEK_ID_INFO` | `kint-dek-id-v1` |
| `WRAP_AAD_PREFIX` | `kint-wrap-v1` |
| `LEAF_PREFIX` | `kint-leaf-v1` |
| `JOURNAL_KEY_PREFIX` | `kint-journal-key-v1` |
| `SCRYPT_N`, `SCRYPT_R`, `SCRYPT_P`, `SCRYPT_DKLEN`, `SCRYPT_MAXMEM` | 131072, 8, 1, 32, 536870912 |
| `SECP256K1_N`, `SECP256K1_HALF_N` | the curve order and half of it |
| `KEK_KIND_SIGNATURE`, `KEK_KIND_PASSPHRASE` | `0x01`, `0x02` |
| `KEK_KIND_PRF`, `KEK_KIND_SMART_ACCOUNT` | `0x03`, `0x04`, both reserved |
| `FLAG_SIGNATURE_WRAP_PASSPHRASE_SALTED`, `FLAG_SNAPSHOT` | `0x01`, `0x02` |
| `ENVELOPE_VERSION`, `EPOCH_VERSION` | 1, 1 |
| `BUCKETS` | 4096, 8192, 16384, 32768, 65536, 98304 |
| `WRAP_LEN`, `HEADER_FIXED_LEN`, `GCM_TAG_LEN` | 77, 59, 16 |
| `TIERS` | `entity`, `state`, `reference`, `journal` |
| `EMPTY_ROOT` | `keccak256("kint-empty-v1")` |
| `LP_NULL` | `0xFFFFFFFF` |

## Reading the head epoch

Wrap a viem client once, read the head, take the data key out of the newest header, then walk.

```ts
import {
  DEFAULT_CONTRACT, applyEpoch, assertCiphertextMatchesDigest, coldStartEvents,
  epochCiphertext, epochsAtBlock, findWrap, fromViem, kekFromPassphrase,
  peekHeader, readEpoch, readHead, spaceId, unwrapDek,
} from '@s0nderlabs/kint-core';
import type { EpochEvent, Row } from '@s0nderlabs/kint-core';

const client = fromViem(publicClient);
const space = spaceId('kint-demo');

const head = await readHead(client, DEFAULT_CONTRACT, owner, space);
const at = await epochsAtBlock(client, DEFAULT_CONTRACT, owner, space, head.blockNumber);
const headEvent = at.find((e) => e.seq === head.seq)!;

const { ct } = await epochCiphertext(client, headEvent.txHash, DEFAULT_CONTRACT);
assertCiphertextMatchesDigest(ct, headEvent.digest);

const { kek, tag } = kekFromPassphrase(passphrase, owner, space);  // or kekFromSignature
const wrap = findWrap(peekHeader(ct).wraps, tag);
if (!wrap) throw new Error('no wrap in the head epoch carries this key');
const dek = await unwrapDek(wrap, kek);
```

`peekHeader` throws when the head epoch is not a kint epoch at all. [An epoch that does not open](/docs/kint-core#an-epoch-that-does-not-open) covers what kint's Python does then.

With the data key in hand, `coldStartEvents` gets the epoch list. It stops the walk at the newest snapshot, but only after your `tryOpen` has actually opened that epoch, and it walks the whole history instead when the snapshot refuses.

```ts
async function open(ev: EpochEvent) {
  const { ct } = await epochCiphertext(client, ev.txHash, DEFAULT_CONTRACT);
  assertCiphertextMatchesDigest(ct, ev.digest);
  return readEpoch(ct, { dek, owner, space, seq: ev.seq, prev: ev.prev });
}

const { events, refusedSnapshotSeq } = await coldStartEvents(
  client, DEFAULT_CONTRACT, owner, space,
  { tryOpen: (ev) => open(ev).then(() => true) },  // false or a throw both mean "do not stop here"
);

let state = new Map<string, Row>();
for (const ev of events) {                      // already oldest first
  if (ev.seq === refusedSnapshotSeq) continue;  // show this: an epoch the viewer would not open
  const { header, doc } = await open(ev);
  const applied = applyEpoch(state, header, doc);
  if (!applied.matchesRowsRoot) throw new Error(`epoch ${ev.seq} does not reproduce its rows_root`);
  state = applied.state;
}
```

`refusedSnapshotSeq` is not a detail to swallow. It means an epoch on this chain carries a `FLAG_SNAPSHOT` its plaintext does not back up, and the viewer read the history the long way round instead. Put it on screen next to the rows, naming the seq. A row's block height is an upper bound, "existed no later than block N", so the viewer must never render it as a wall-clock "as of".

A key rotation (`kint rekey`) changes the `dek_id`: epochs before it are sealed under the old data key and refuse with `dek_id mismatch`. The rotation anchors a snapshot under the new key, so a viewer holding only the current key stops there.

`walkEpochs` with `stopWhen: (ev) => isSnapshotEvent(client, ev, contract)` is the raw form of that stop, and it trusts a header byte nothing signs. Reach for it directly only when you want the full history regardless.

## An epoch that does not open

Any authorized session key can append bytes as the next epoch, including bytes that are not a kint epoch or that no key opens. kint's Python handles two such cases that this package leaves to the page, and the loop above throws on both.

**A head that is not a kint epoch.** `kint connect` and `kint rekey` take the key wraps from the newest epoch whose header parses: when the head's header does not, they walk back through `prevBlock`, looking at most 31 epochs before the head. A fetch that fails, or calldata whose digest disagrees with the event, is never walked past; that is the chain not being read, not an epoch that is not a kint epoch (`_chain_head_header` in `src/kint/connect.py`). A page does the same walk with `walkEpochs`, `epochCiphertext`, `assertCiphertextMatchesDigest` and `peekHeader`.

**An epoch in the middle.** `kint pull` steps past an epoch only when it cannot open it and a later snapshot in the same walk opens with the same key. It resumes at that snapshot with the snapshot event's own `prev`, and reports the skipped seq together with the snapshot that superseded it. Every other failure stops the pull where it is (`_open_one` and the apply loop in `src/kint/pull.py`). In this package's terms:

| What failed | kint's kind | A later snapshot may supersede it |
|---|---|---|
| `peekHeader` or `parseHeader` throws, no wrap or `dek_id mismatch`, `epoch did not authenticate` | unreadable | yes |
| `epochCiphertext` throws, the calldata disagrees with the event, `assertCiphertextMatchesDigest` throws, or `prev` does not chain | chain | no |
| `parsePlaintext` or `assertEpochConsistent` throws | content | no |

A viewer that follows this rule names the skipped seq on screen, as it does `refusedSnapshotSeq`.

## The consistency check is mandatory

> **Warning.** The header flags are not covered by the AAD. `openEpoch` alone will happily open an epoch whose `FLAG_SNAPSHOT` bit someone flipped in transit: the ciphertext still authenticates, and nothing but the plaintext `"snapshot"` key contradicts it. A reader that skips that comparison can be told to throw its state away.

`readEpoch` is the call a page should actually make. It runs `assertEpochConsistent`, a port of the block kint's own pull runs after `open_epoch`, comparing four plaintext fields and one flag against what the reader already knew:

| Field | Compared against | Error |
|---|---|---|
| `doc.seq` | the seq the chain gave | `epoch seq disagrees` |
| `doc.space` | the space id the reader asked for | `epoch space disagrees` |
| `doc.prev` | the previous epoch's digest | `epoch prev disagrees` |
| `doc.rows_root` | `header.rowsRoot` | `epoch rows_root disagrees` |
| `doc.snapshot` | `isSnapshotHeader(header)` | `epoch snapshot flag disagrees` |

Each message names the field and both values. `applyEpoch` re-checks the flag on its own and refuses an epoch whose header and plaintext disagree rather than folding it in. Use `readEpoch`, or call `assertEpochConsistent` yourself. The same rule holds on the Python side; see [Verify before acting](/docs/verify).

## The code-point sort

Leaves are ordered by their canonical id, and that ordering is Python's: by Unicode code point. JavaScript's default comparison walks UTF-16 code units instead, which puts an astral character (a surrogate pair starting at `0xD800`) before anything in U+E000..U+FFFF where Python puts it after. Row ids carry user text, so the difference is real and it changes the merkle root.

`compareCodePoints` is the comparator that fixes it, and `merkleRoot`, `sortedIds` and `merkleProof` all sort with it. The vector row set contains a key starting U+FB01 and one starting U+1F525 under the same category, so it only sorts correctly with the comparator: one test asserts the order matches Python's `sorted()`, and another asserts that the default `sort()` does not.

## The vectors

`scripts/gen_vectors.py` makes the Python say what the bytes are, and writes `js/test/vectors.json`:

```sh
env -u PYTHONPATH .venv/bin/python scripts/gen_vectors.py
```

It signs the frozen payload with a throwaway key (`0x11` repeated 32 times, never used for anything real), derives all three KEK paths (signature, signature salted with a passphrase, passphrase), wraps a fixed data key under each, builds eight rows across all four tiers with a null category, a null status, a null meta, accents and the code-point trap, and seals two epochs: epoch 1 as an ordinary diff, epoch 2 as a genuine snapshot with one row dropped and one changed. The file records the typed data, the canonical payload JSON, the vault digest, the space id, the KEK info, every KEK and tag, the scrypt parameters, the `dek_id`, a recovery code, a foreign wrap `findWrap` must skip, the empty root, every row id and leaf, the sorted ids, the root, two merkle proofs, both sealed blobs with their headers and AADs, and one `push` calldata.

Do not hand-edit that file. Regenerate it when the Python format moves, and the TypeScript tests fail until the port moves with it.

## Limits

- `seq`, `blockNumber` and `prevBlock` come back as JavaScript numbers, not bigints. They are `uint64` on chain, so the values are exact only below 2^53; the bigints are still on the raw viem log if you ever need them.
- `epochCiphertext` and `isSnapshotEvent` both require the contract address, for the reason given above.
- There is no helper for the walk past an unreadable head or past an epoch that does not open; the page implements the rule above itself.
- The session-key authorization typed data (`SessionKeyAuthorization`, for `setSessionKeyBySig`) is not ported. A page that asks a wallet for one builds it from [`docs/frontend-contract.md`](https://github.com/s0nderlabs/kint/blob/main/docs/frontend-contract.md).
- Nothing here seals an epoch or writes to the chain, and reading never sends a transaction.

Read [Harnesses](/docs/harnesses) next.

Source: [`js/src/index.ts`](https://github.com/s0nderlabs/kint/blob/main/js/src/index.ts), [`js/src/kek.ts`](https://github.com/s0nderlabs/kint/blob/main/js/src/kek.ts), [`js/src/envelope.ts`](https://github.com/s0nderlabs/kint/blob/main/js/src/envelope.ts), [`js/src/epoch.ts`](https://github.com/s0nderlabs/kint/blob/main/js/src/epoch.ts), [`js/src/canon.ts`](https://github.com/s0nderlabs/kint/blob/main/js/src/canon.ts), [`js/src/chain.ts`](https://github.com/s0nderlabs/kint/blob/main/js/src/chain.ts), [`js/src/bytes.ts`](https://github.com/s0nderlabs/kint/blob/main/js/src/bytes.ts), [`js/src/constants.ts`](https://github.com/s0nderlabs/kint/blob/main/js/src/constants.ts), [`js/README.md`](https://github.com/s0nderlabs/kint/blob/main/js/README.md), [`js/package.json`](https://github.com/s0nderlabs/kint/blob/main/js/package.json), [`js/scripts/open-epoch.ts`](https://github.com/s0nderlabs/kint/blob/main/js/scripts/open-epoch.ts), [`scripts/gen_vectors.py`](https://github.com/s0nderlabs/kint/blob/main/scripts/gen_vectors.py), [`src/kint/connect.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/connect.py), [`src/kint/pull.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/pull.py), [`docs/frontend-contract.md`](https://github.com/s0nderlabs/kint/blob/main/docs/frontend-contract.md).
