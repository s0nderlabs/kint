# Frontend contract (for the Next.js session)

Everything the connect page and the memory viewer need to interoperate with the Python kint on
the user's machine. Nothing here is negotiable without a format bump on both sides. The
TypeScript port of the reader's half is `js/` (`@s0nderlabs/kint-core`); where it and this file
disagree with `src/kint`, the Python decides.

## 1. What the page does

Two jobs, both browser-side, nothing decrypted ever leaves the browser:

1. **Connect page.** Log in with the Base Account (Base Account SDK), authorize this machine's
   session key on EpochAnchor (one transaction from the account: `setSessionKey(key, expiry)`;
   for a counterfactual account that first transaction also deploys it), and hand the result to
   the local kint (see section 7). The vault key for a Base Account owner is a passphrase the
   user types into the **terminal** (`kint connect --owner 0x... --smart-account`), never into
   the page and never into an agent chat.
2. **Memory viewer.** Read the owner's epochs from Base, unlock in the browser with the same
   passphrase (or, for an EOA owner, the wallet signature), show the full memory and a per-block
   timeline of every row.

## 2. Addresses and chain

- Chain: Base mainnet, chainId 8453.
- EpochAnchor: `0xa22E03f7a4145Bf4909a83595C90a38E14d79600`, deployed at block 51081696 and
  verified on Basescan (`contracts/deployments/base-mainnet.json`; `kint status` prints it too).
  No owner, no admin, no upgrade path. ABI: `contracts/abi/EpochAnchor.json`.
- Public read RPC: `https://mainnet.base.org`. Use the page's own keyed RPC for anything else,
  and never render a keyed URL: kint itself shows only the scheme and host of an endpoint.

## 3. The two EIP-712 payloads (they are deliberately different domains)

**Vault key (a SECRET, only for EOA owners, never for authorization):**

```json
{"types":{"EIP712Domain":[{"name":"name","type":"string"},{"name":"version","type":"string"},{"name":"chainId","type":"uint256"}],
 "KintVault":[{"name":"owner","type":"address"},{"name":"purpose","type":"string"}]},
 "primaryType":"KintVault","domain":{"name":"kint","version":"1","chainId":8453},
 "message":{"owner":"<checksummed owner>","purpose":"kint-memory-v1: signing this reveals your memory encryption key. Only sign it in a kint terminal or page you opened yourself."}}
```

No `verifyingContract`, no `salt`. The `purpose` string is deliberately a warning sentence: it is
the one field every wallet renders, and this signature IS the key. The wallet must sign it with
RFC 6979 (deterministic). A Base Account cannot produce this (passkey signatures are not
deterministic and are scoped to keys.coinbase.com), which is why Base Account owners use the
passphrase path. The page must never send this signature anywhere and must never use it as a
login.

**Session-key authorization (for `setSessionKeyBySig`, safe to ask any wallet for):**

```json
{"types":{"EIP712Domain":[{"name":"name","type":"string"},{"name":"version","type":"string"},{"name":"chainId","type":"uint256"},{"name":"verifyingContract","type":"address"}],
 "SessionKeyAuthorization":[{"name":"owner","type":"address"},{"name":"key","type":"address"},{"name":"expiry","type":"uint64"},{"name":"nonce","type":"uint256"},{"name":"deadline","type":"uint256"}]},
 "primaryType":"SessionKeyAuthorization",
 "domain":{"name":"kint EpochAnchor","version":"1","chainId":8453,"verifyingContract":"<EpochAnchor>"},
 "message":{"owner":"<owner>","key":"<session key>","expiry":<unix>,"nonce":<authNonce(owner)>,"deadline":<unix>}}
```

The contract checks ERC-1271 when the owner has code, ecrecover otherwise. A counterfactual Base
Account has no code, so its signature is rejected: send `setSessionKey` from the account instead.
That is what `kint authorize page` does, and what the demo did; a Base Account sends it as a user
operation, so on chain it lands inside a bundler's `handleOps` transaction.

`js/` does not port this payload (it is the reader's half only). A page that asks a wallet for
it builds the JSON above itself, reading `nonce` from `authNonce(owner)` on the contract.

## 4. Key derivation (TypeScript port must match these bytes)

Test vector (throwaway key `0x11...11`, owner `0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A`,
tenant `demo`):

| value | hex |
|---|---|
| vault digest | `39fec015d21465d81dd5611129982b7a310e070a126f41dfdd8c87cc04a31517` |
| space = keccak256("kint-space-v1" \|\| tenant) | `fd83319f25a64bb2952805bd9bf32719080d37c6a83b6a51db74e409eb42bff6` |
| KEK (signature path) | `c69d894607fac5813904d32c44c4603835b746a529ada52fae1834ac28cc418f` |
| kek_tag = HMAC-SHA256(KEK, "kint-kek-check-v1")[:16] | `9710b041b39054fa3ad68ee22c8f2e79` |

- **Signature path (kind 0x01):** parse the 65-byte signature; require it recovers to the owner
  over the vault digest; low-S normalise (`s > n/2 -> s = n - s`); `ikm = r || s` (64 bytes, never
  v); `info = "kint-kek-v1" || owner20 || space` (63 bytes); `KEK = HKDF-SHA256(ikm, salt = "",
  info, 32)`. With a 2FA passphrase the salt is `scrypt(passphrase, owner20, N=2^17, r=8, p=1, 32)`.
- **Passphrase path (kind 0x02, Base Account owners):** `ikm = scrypt(passphrase, salt = owner20,
  N=2^17, r=8, p=1, dkLen=32)`; `KEK = HKDF-SHA256(ikm, salt = "", info, 32)`. Same `info`.
- **Passphrase bytes:** UTF-8 exactly as given, with no Unicode normalisation (Python
  `passphrase.encode("utf-8")` in `src/kint/crypto.py`; `passphraseStretch` in `js/src/kek.ts`).
  An empty passphrase is refused on both sides. A page must not NFC or NFKC normalise what the
  user typed, or the scrypt output changes. One CLI detail: `kint connect --passphrase-stdin`
  strips leading and trailing whitespace before deriving (`read_secret` in
  `src/kint/connect.py`); the interactive prompt does not.
- `kek_tag` is how a client finds its wrap in a header: compare tags, never trial-decrypt.

## 5. Envelope (what an epoch ciphertext looks like)

`push(owner, space, prev, ct)`; `ct = header || AES-256-GCM(DEK, nonce, padded, aad)`.

Header, big-endian, byte-exact:

```text
version(1)=0x01 | flags(1) | gcm_nonce(12) | rows_root(32) | dek_id(8) | lenBucket(4) | n_wraps(1)
wrap x n_wraps: kek_kind(1) | kek_tag(16) | wrap_nonce(12) | wrapped_dek(48)
```

- `flags` bits: `0x02` FLAG_SNAPSHOT, this epoch's `rows` are the FULL state rather than a diff.
  `0x01` is defined (signature wrap salted with a passphrase) but NO kint writer sets it, so a
  reader must never branch on it: a salted and an unsalted signature wrap look the same in the
  header. Derive the unsalted KEK first; if no wrap carries its `kek_tag`, ask for the salt
  passphrase and derive again. Unknown bits are reserved: ignore them, never refuse on them.
- `wrapped_dek = AES-256-GCM(KEK, wrap_nonce, DEK, aad = "kint-wrap-v1" || kek_kind || kek_tag)` (32 + 16 tag).
- `dek_id = HMAC-SHA256(DEK, "kint-dek-id-v1")[:8]`.
- `aad = keccak256(abi.encode(uint256 chainId = 8453, address owner, bytes32 space, uint64 seq, bytes32 prev, uint32 lenBucket, bytes32 rows_root, bytes8 dek_id))`.
- `padded = uint32(len(gz)) || gz || zeros` up to `lenBucket` (one of 4096, 8192, 16384, 32768, 65536, 98304). The bucket is the only public length.
- `gz = gzip(plaintext, level 9, mtime 0)`.
- Plaintext is JSON: `{"v":1,"tenant","space","seq","prev","rows":[...],"deleted":[[tier,category,key]...],"rows_root","n_rows","created_at"}`, plus `"snapshot":true` as the LAST key on a snapshot epoch and absent on every other one, where each row is `{tier,key,category,status,body,meta,ts,evaluated,acted,forward,extra}` with `body`/`meta`/journal fields as the EXACT stored TEXT (strings), never re-serialised.
- `rows_root` is the merkle root over the leaves of the FULL state after the epoch, leaves sorted by canonical id `tier\0category\0key`; pairs hashed with keccak256(left || right), an odd last node carried up unchanged; empty state root = keccak256("kint-empty-v1"). Leaf = keccak256("kint-leaf-v1" || lp(tier) || lp(category) || lp(key) || lp(status) || lp(body) || lp(meta)) with `lp(x) = uint32(len) || utf8(x)` and `lp(null) = 0xFFFFFFFF`. Journal leaf: `"journal" || null || key || null || lp(ts) || lp(evaluated) || lp(acted) || lp(forward) || lp(extra)` where key = keccak256("kint-journal-key-v1" || lp(ts) || lp(evaluated) || lp(acted) || lp(forward) || lp(extra)) as hex.
- **Duplicate journal events.** A second event with identical `ts, evaluated, acted, forward, extra` in the same store gets the key with `:1` appended, a third `:2`, in rowid order; the first keeps the bare key (`export_rows` in `src/kint/export.py`). The epoch rows carry the suffixed key, so a reader uses the key it finds and never recomputes the ordinal.
- **The sort is by Unicode code point**, Python's `sorted()` over `str`. JavaScript's default string sort walks UTF-16 code units and puts an astral character (a surrogate pair) before U+E000..U+FFFF, which changes the root. `compareCodePoints` in `js/src/bytes.ts` is the comparator `merkleRoot`, `sortedIds` and `merkleProof` use.

## 6. Reading the chain (the viewer)

1. `head(owner, space)` -> `{digest, seq, blockNumber}`; `space = keccak256("kint-space-v1" || tenant)`.
2. `eth_getLogs` at exactly `blockNumber` for `Epoch(owner indexed, space indexed, writer indexed, seq, prev, digest, prevBlock)`; take the event with that `seq`; fetch the transaction, require it is addressed to EpochAnchor, decode `push(owner, space, prev, ct)` from its input; require `keccak256(ct) == digest`; then walk to `prevBlock` and repeat until `prevBlock == 0`.
3. For each epoch, find your wrap by `kek_tag`, unwrap the DEK, decrypt with the AAD above (`prev` is the previous epoch's digest, zero for seq 1), gunzip, apply rows and deletions in seq order. The row's block height is an UPPER bound ("existed no later than block N"); never show a wall-clock "as of".
4. **Snapshots.** An epoch whose header carries `FLAG_SNAPSHOT` (0x02) holds the whole state, so a
   viewer that only needs the CURRENT memory may stop walking there: it is the epoch that says
   what everything is, and its `rows_root` is the root of exactly its own rows. Walk past it only
   when you are showing the timeline. When a snapshot is applied, rows the viewer already holds
   and the snapshot does not are gone, not merely unchanged. A snapshot's `deleted` list names
   the rows deleted since the previous epoch; they are already absent from its `rows`, so it is
   informational for the state (a timeline uses it to show when a row disappeared) and never
   needed to reach `rows_root`.
5. **The flags are not covered by the AAD**, so a header flag on its own is not authenticated. A
   reader MUST check that `FLAG_SNAPSHOT` and the plaintext `"snapshot"` key agree, and treat an
   epoch where they disagree as unreadable (kint's pull stops there and says so by name).
6. The `dek_id` in a header is what a rotation changes (`kint rekey`): epochs before the rotation
   are sealed under the old data key. A viewer holding only the current key stops at the newest
   epoch it can open, which after a rotation is the snapshot the rotation wrote.
7. **A head that is not a kint epoch.** Any authorized session key can append bytes as the next
   epoch. When the head epoch's header does not parse, kint's connect and rekey walk back through
   `prevBlock` and take the wraps from the newest epoch whose header does, looking at most 31
   epochs before the head. A fetch that fails, or calldata whose digest disagrees with the event,
   is never walked past (`_chain_head_header` in `src/kint/connect.py`). A viewer that finds no
   readable header at the head does the same.
8. **An epoch that does not open.** kint's pull steps past an epoch only when it cannot open it
   (no kint header, no wrap or `dek_id` for this key, or an AEAD failure) AND a later snapshot in
   the same walk opens with this key. It resumes at that snapshot, taking `prev` from the snapshot
   event itself, and reports the skipped seq with the snapshot that superseded it. A fetch
   failure, calldata that disagrees with the event, a broken prev chain, or an epoch that opens
   and then disagrees with the chain (item 5 included) stops the walk there
   (`_open_one` in `src/kint/pull.py`). A viewer follows the same rule and names the skipped seq
   on screen. `js/` has no helper for items 7 and 8.

## 7. Handoff from the page to the local kint

A hosted page does not talk to the local kint: there is no loopback endpoint for it in this
build. kint serves its own loopback page for the one step that needs the Base Account:
`kint authorize page` binds `127.0.0.1` on a random port with a 32-byte token in the path,
checks Origin and Sec-Fetch-Site on the result POST, has the account send
`setSessionKey(key, expiry)`, polls `canWrite` on the chain, and exits after one result or 15
minutes. It loads the Base Account SDK from esm.sh (`@base-org/account@2.5.10`) with no
integrity check.

A hosted page that authorizes instead hands the user the owner address, the authorized session
key and the transaction hash. The user runs, in the terminal:

```sh
kint session-key create                               # prints the address the page authorizes
kint connect --owner 0x<BaseAccount> --smart-account  # prompts for the vault passphrase
kint pull                                             # or kint-server does it on start
```

A loopback endpoint for a hosted page (`http://127.0.0.1:<port>/kint/connect`, session token in
the URL, Origin and Sec-Fetch-Site checks) is not built; do not depend on it.
