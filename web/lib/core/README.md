# @s0nderlabs/kint-core

The browser-side decrypt path of kint, in framework-free TypeScript. It is a port of the Python in
`src/kint`: the same frozen EIP-712 payload, the same HKDF and scrypt key derivation, the same
envelope bytes, the same canonical leaves and merkle root, and the same head-to-genesis walk over
EpochAnchor on Base. Nothing here writes to the chain and nothing here seals an epoch; the machine
that holds the Sibyl store is the only thing that does that. The one job of this package is to let a
page read a wallet's epochs off Base and open them locally, so nothing decrypted ever leaves the
browser.

## The API

`typedData(owner)`, `canonicalPayloadJson(owner)` and `vaultDigest(owner)` produce the one frozen
message the owner signs. That signature is a **secret**, not a credential: it IS the key, so never
send it anywhere and never accept it as a login. `kekFromSignature(sig, owner, space, passphrase?)`
turns it into a KEK, but only after the signature recovers to the expected signer over the expected
digest; that check is a hard check and it throws rather than deriving a silently different key.
`kekFromPassphrase(passphrase, owner, space)` is the wallet-free path a Base Account owner uses, and
`kekTag(kek)` is how a client finds its own wrap in a header without ever trial-decrypting.

`parseHeader`, `findWrap`, `unwrapDek` and `openEpoch` are the envelope. A header carries the GCM
nonce, the rows root, the `dek_id`, the size bucket and a list of wraps; `findWrap` matches on the
kek tag, `unwrapDek` checks that tag before it touches AES (its tag argument defaults to the tag of
the key you passed, which is the only value that makes the check mean anything), and `openEpoch`
binds the ciphertext to its place in the chain through an AAD over `(chainId, owner, space, seq,
prev, bucket, rows_root, dek_id)`. Get any one of those wrong and the epoch refuses to open.
`decodeRecoveryCode` accepts the grouped base32 code a user types when they have neither wallet nor
passphrase.

`readEpoch` is the call a page should actually make: it opens the epoch, parses the plaintext and
then runs `assertEpochConsistent`, which is what kint's own pull runs (`doc.seq`, `doc.space`,
`doc.prev`, `doc.rows_root` and the snapshot key all have to agree with the chain and the header).
Use it, or call `assertEpochConsistent` yourself. **The header flags are not covered by the AAD**,
so `openEpoch` alone will happily open an epoch whose `FLAG_SNAPSHOT` bit someone flipped in
transit: nothing but the plaintext `"snapshot"` key contradicts it, and a reader that skips that
comparison can be told to throw its state away. `applyEpoch(state, header, doc)` folds one epoch
into a row map and returns the new state and its root.

`rowId`, `leaf`, `leavesOf`, `merkleRoot`, `merkleProof` and `verifyProof` are the canonical view of
a row set. The one thing that is easy to get wrong here is the sort: ids are ordered by Unicode code
point, the way Python orders `str`, and JavaScript's default comparison walks UTF-16 code units
instead, which puts an astral character on the wrong side of anything in U+E000..U+FFFF and changes
the root. `compareCodePoints` is the comparator that fixes it, and there is a vector in the test
suite whose row set only sorts correctly with it.

`readHead`, `walkEpochs`, `epochCiphertext` and `decodePushCalldata` are the chain reads. The walk
goes head to genesis through the `prevBlock` field of each `Epoch` event, one exact-block
`eth_getLogs` per hop, so no RPC log-range cap is ever hit. `assertCiphertextMatchesDigest` is the
check the viewer must not skip: the ciphertext comes out of the transaction's calldata, and only its
keccak256 matching the anchored digest makes it the epoch the chain vouched for.

## How the app uses it

Wrap a viem `PublicClient` once with `fromViem(client)`, then derive the KEK from the wallet
signature or the passphrase, find your wrap in the newest header and unwrap the DEK. With that DEK in
hand, `coldStartEvents` gets the epoch list: it stops the walk at the newest snapshot, but only after
your `tryOpen` has actually opened that epoch, and it walks the whole history instead when the
snapshot refuses. Then apply what comes back in order, oldest first:

```ts
const space = spaceId(tenant);

async function open(ev: EpochEvent) {
  const { ct } = await epochCiphertext(client, ev.txHash, contract);
  assertCiphertextMatchesDigest(ct, ev.digest);
  return readEpoch(ct, { dek, owner, space, seq: ev.seq, prev: ev.prev });
}

const { events, refusedSnapshotSeq } = await coldStartEvents(client, contract, owner, space, {
  tryOpen: (ev) => open(ev).then(() => true),   // false or a throw both mean "do not stop here"
});

let state = new Map<string, Row>();
for (const ev of events) {                      // already oldest first
  if (ev.seq === refusedSnapshotSeq) continue;  // show this: an epoch the viewer would not open
  const { header, doc } = await open(ev);
  const applied = applyEpoch(state, header, doc);
  if (!applied.matchesRowsRoot) throw new Error(`epoch ${ev.seq} does not reproduce its rows_root`);
  state = applied.state;
}
```

`refusedSnapshotSeq` is not a detail to swallow. It means an epoch on this chain carries a
FLAG_SNAPSHOT the plaintext does not back up, and the viewer read the history the long way round
instead. Put it on screen next to the rows, naming the seq.

The two epoch kinds apply differently, and getting this wrong is how a viewer shows a row its owner
deleted:

- **An ordinary epoch is a diff.** Set `doc.rows` into the state, then delete `doc.deleted`.
- **A snapshot epoch (`FLAG_SNAPSHOT`, 0x02) REPLACES the state.** Clear the row map and set exactly
  `doc.rows`: a snapshot's rows ARE the whole state, and its `rows_root` is the root of exactly
  those rows, nothing folded in. Its `deleted` list is informational, the rows that went away since
  the previous epoch and are already absent from `rows`, and it is not needed to reach the anchored
  root. That is precisely what lets a cold start stop at a snapshot without ever reading the epochs
  before it. Merge one in as though it were a diff and every row the snapshot dropped survives, so
  the root will not match and `matchesRowsRoot` says so.

A row's block height is an upper bound, "existed no later than block N", so the viewer must never
render it as a wall-clock "as of". Stopping at a snapshot is what keeps a cold start cheap: that
epoch carries the full row set, and the epochs before it are only needed for the older versions of a
row. `walkEpochs` with `stopWhen: (ev) => isSnapshotEvent(client, ev, contract)` is the raw form of
that stop, and it trusts a header byte nothing signs, which is exactly why `coldStartEvents` wraps it
in the open-it-first retry above. Reach for `walkEpochs` directly only when you want the full history
regardless.

## Limits

- `seq`, `blockNumber` and `prevBlock` come back as JavaScript numbers, not bigints. They are
  `uint64` on chain, so the values are exact only below 2^53; a real space will not come close, and
  the bigints are still there on the raw viem log if you ever need them.
- `epochCiphertext` and `isSnapshotEvent` both require the contract address: without it a reader
  would decode `push()` calldata out of any transaction at all, and anyone can write that calldata.
- Nothing here seals an epoch or writes to the chain. The machine holding the Sibyl store does that.

## Tests

Every byte format here is pinned by vectors that the Python itself generates, so the two languages
cannot drift apart quietly:

```
env -u PYTHONPATH .venv/bin/python scripts/gen_vectors.py   # writes js/test/vectors.json
cd js && bun install && bun test && bunx tsc --noEmit
```

`scripts/open-epoch.ts` is the end-to-end version of the same idea: seal an epoch in Python, then

```
KINT_DEK=<64 hex chars> bun run scripts/open-epoch.ts <blob> --owner 0x... --tenant demo \
    --seq 1 --prev <64 hex chars>
```

opens it here through `readEpoch` and prints the plaintext. Because it is `readEpoch` and not
`openEpoch`, a blob whose header disagrees with its plaintext (a flipped `FLAG_SNAPSHOT` is the cheap
one to try) exits non-zero naming the field instead of printing the forged flag as fact. The DEK
comes from the environment and never from argv, because a process list is public on a shared
machine.
