---
slug: limits
title: Limits and threat model
description: What kint does not do, what each attacker gets, and what anyone reading Base can see.
group: Background
order: 16
source: 'README.md'
---

# What kint guards, and where it stops.

Every limit kint ships with, then one attacker at a time: what each one gets, what the code or the contract still refuses, and what anyone reading Base can see.

## The honest limits

These are the README's limits, each checked against the code, plus the few the code adds. Paths below use `~/.kint`, the default of `KINT_HOME`; `<space16>` is the first 16 hex characters of the space id.

### What comes back on a restore

- Content-exact and search-exact across the four tiers the SDK writes: entities, state, reference and journal. `tests/test_export_restore.py` replays a store into a second one and compares every body, status and metadata, then Sibyl's own search results and their verdict for a set of queries. Uuids and the `updated_at` of entities, state and reference documents regenerate on replay; the journal `ts` survives. The export reads those tables by SQL in rowid order (`src/kint/export.py`); the restore goes through the SDK's write methods (`src/kint/restore.py`).
- Those are four of the eleven data tables in Sibyl's schema (not counting its schema-version table and search indexes). The other seven (`entity_relations`, `revenue_events`, `error_events`, `archived_entities`, `flagged_actors`, `skill_proposals`, `learning_runs`) are not exported. Sibyl's `memory_forget` moves an entity into `archived_entities`, so a restored machine has the deletion, not the archive.
- Deletions replay for entities only, because `delete_entity` is the SDK's only delete. Sibyl never deletes a state, reference or journal row itself; one removed behind its back is reported by the pull as a warning, not removed.
- The ciphertext lives in transaction calldata. Reading it back needs a node that keeps its transaction index, and Base's L1 data availability is the blob retention window. kint keeps its own copy of every epoch it pushes or fetches under `~/.kint/epochs/<space16>/` and checks a cached blob's keccak against the Epoch event before trusting it.

### What a restore costs

- A cold start stops at the newest snapshot epoch (`kint compact` writes one), so restore cost is bounded by the size of the memory, not its history. `kint pull --full` walks past snapshots for the older versions, as far back as the newest key rotation: epochs sealed under a retired key stay closed to a machine that only holds the current one. On a machine already up to date, `--full` walks from the head to the first epoch and caches every one it has not decrypted, including the diff epochs a warm pull jumped on its way to a snapshot, so `memory_history` sees their versions.
- One epoch carries at most 90 KB of measured compressed change (`MAX_COMPRESSED_PER_EPOCH` in `src/kint/push.py`, the gzip size plus 512 bytes of headroom; the largest bucket is 98,304 bytes). A bigger change set is split across epochs, and a single row that does not fit on its own is refused by name. A snapshot is always one epoch, so once the whole state compresses past that limit, `kint compact` and `kint rekey` refuse. Ordinary pushes carry on.

### Keys and what leaks

- Base holds ciphertext, but the size bucket is public, and the README counts the row count as public too. No cleartext field carries it (`n_rows` is inside the ciphertext), but the bucket and the cadence of epochs say roughly how much memory there is, so plan as if it were public. The full list is under [What is public on Base](/docs/limits#what-is-public-on-base).
- A vault passphrase can be guessed offline. Every header carries each wrap's 16-byte key tag, so anyone reading Base can test guesses against it at the cost of one scrypt per guess. For a Base Account owner that passphrase is the whole lock: make it long and random.
- A phished derive signature is a permanent key. The EIP-712 message says so in the one field every wallet renders. kint never accepts that signature as a login and never sends it anywhere. See [A phished derive signature](/docs/limits#a-phished-derive-signature).
- A space has one data key at a time. `kint rekey` rotates it: a new key, new wraps, one snapshot epoch under the new key, a new recovery code. Epochs sealed before the rotation stay readable to whoever held the old key; that is a property of any ledger, not something a rotation can undo.
- The cached data key lasts `KINT_KEY_TTL`, 24 hours by default. kint-server renews it after every successful pull and push, so a server in use keeps it; one that goes a whole TTL without a successful pull or push (no writes, or every push held) still lapses. Once it lapses, kint-server skips the pull at its next start and every automatic push until `kint connect` runs again; `memory_verify` and `memory_history` keep working. Set `KINT_KEY_TTL=30d` on a machine that stays up, in the harness registration as well as the terminal.
- `kint authorize page` handles no secret, but it loads the Base Account SDK from esm.sh (`@base-org/account@2.5.10`), so that CDN is trusted for the one `setSessionKey` transaction the page asks the account to send.

### Writers

- One wallet owns one memory per Sibyl tenant; many machines may write under it, one at a time. Two machines writing at once is a fork: kint refuses and tells you (`kint pull --discard-local`).
- Two machines that both connect before the first push each create their own vault. The second opens nothing until it runs `kint connect` again, which adopts the vault in the head epoch (its pull is also a fork if its store holds rows the chain never saw). The recovery code it wrote first opens nothing; `kint recovery-code` writes the right one.
- kint-server holds a push rather than anchor drift. Every push it makes (the watcher's, the exit push, `memory_push`) answers `HELD`, anchoring nothing and dropping nothing, when a row the chain already vouches for changed behind Sibyl's tools while the server ran, or when `memory_verify` already refused exactly the value the row holds. The first ground only sees changes made while the server runs and since its last successful pull or push. A row edited while no kint-server was running, or before one of those, is anchored by the next automatic push unless `memory_verify` refused it first; `memory_history` still shows the edit as a new version. `KINT_NO_WATCHER=1` turns the automatic push off where that matters (the exit push still runs, checked the same way).
- A hold stops the whole push, so every other unanchored change waits with it until the human runs `kint push`, which is never held, or `kint pull --discard-local`, which restores the anchored state and moves every unanchored change to a backup.
- Verifying your own unpushed edit holds the server. An edit to an anchored row reads as `drifted` until it is pushed, so `memory_verify` refuses it and writes a `kint_refusal` naming that value; from then on every kint-server push answers `HELD` until the human decides. Push an edit before you verify it.
- A second writer on the same store while kint-server runs (another harness's server, an SDK-direct process) makes its updates to anchored rows read as changes behind Sibyl's tools, and the server holds its pushes until those rows are anchored.
- A session key can append any bytes as the next epoch. A pull walks past an epoch it cannot open when a later snapshot in the same walk opens; otherwise it stops there, and push and verify refuse on that machine. The owner revokes the key, then runs `kint compact --over-skipped` (or `kint rekey --over-skipped`) on a machine whose last pull stopped there: that machine's store is anchored as one snapshot chained on the chain head, and every later pull stops at it. See [A stolen session key](/docs/limits#a-stolen-session-key).
- `kint connect` and `kint rekey` read the key wraps from the head epoch, stepping back up to 32 epochs over one whose header does not parse. An epoch forged with a header that parses (the parser checks only the version byte and the length) still stops them: the key or the recovery code is refused. From a machine whose data key is still cached, `kint pull` then `kint compact --over-skipped` makes the head readable again.
- A push whose transaction lands but whose confirmation wait fails (an RPC timeout, say) leaves this machine's mirror behind the chain: the next push reports that another machine pushed, and the next pull a fork. The Epoch event's `writer` on Basescan is then this machine's session key; `kint pull --discard-local` takes the same rows back from the chain, and anything written since stays in the backup.
- The exit push is best effort: a harness that kills the server soon after closing it ends the push before its transaction lands (`src/kint/server.py` notes that Claude Code allows about 500 ms). The next kint-server session on that machine starts with those rows marked and pushes them after its quiet period; `kint push` anchors them at once.

### Install

kint is not on PyPI yet. Install from the tagged release: `uv tool install git+https://github.com/s0nderlabs/kint@v0.3.0` (Python 3.10+).

## Who has what

Seven actors, each set against the code or the contract that stops it. The sections after the table carry the detail.

| Who | Can | Cannot | Enforced in |
|---|---|---|---|
| Someone reading Base | Read every epoch's ciphertext and cleartext header, every Epoch event, each head, and which session keys may write until when; confirm a guessed tenant name; test passphrase guesses offline | Read a row, a key or a category; get an altered epoch accepted | `crypto.py` `seal_epoch`, `epoch_aad`; `pull.py` `_open_one` |
| A phished derive signature | Derive the wallet's KEK for every space that owner has, and so the data key from every epoch carrying a signature wrap, past and future | Send a transaction or authorize a key; open a vault salted with `--passphrase-prompt` without that passphrase; open epochs sealed after a rotation that dropped its wrap | `crypto.py` `derive_kek_from_signature`; `connect.py` `rekey` |
| A stolen session key | Append epochs under the owner until it expires or is revoked, each naming it as the writer; with one that does not open, stop pushes and verify on every machine whose pull stops at it, until the owner anchors a snapshot over it | Decrypt anything; rewrite or remove an anchored epoch; extend its own expiry or authorize another key; make a cold start stop at a forged snapshot | `EpochAnchor.sol` `canWrite`, `push`; `pull.py`; `push.py` `override_skipped` |
| A compromised machine or VPS | Everything that machine can do: read the whole memory in the clear, seal epochs that open and verify, edit the store and anchor the edit with `kint push` | Derive a KEK, unless you connect or rekey there again; authorize a session key, unless the owner key is there; open epochs sealed after a rotation done elsewhere | `keys.py`; `connect.py` `read_secret`, `rekey` |
| A malicious or lagging RPC | Withhold or delay data; learn which owner and space this machine reads; on a single-RPC cold start, choose which head counts as newest | Forge an epoch that opens; roll back a machine that has pulled before; disagree with the second operator on a cold start unnoticed | `pull.py` `_check_freshness`, `_fetch_blob_uncached`, `_open_one` |
| A second machine writing at once | Take the head if its push lands first | Overwrite the other machine's epoch; make kint merge blindly | `EpochAnchor.sol` `push`; `push.py`; `pull.py` |
| You, with the owner key lost | Keep writing with existing session keys until they expire; open the memory with the recovery code or a passphrase wrap | Authorize or extend a session key; rotate the owner; rotate the data key without a passphrase wrap | `EpochAnchor.sol` `canWrite`, `setSessionKey`, `setSessionKeyBySig`; `connect.py` `rekey` |

### Someone reading Base

Anyone with an RPC reads every `push` calldata and every `Epoch` event. That is the design: the ciphertext has to live where a wiped machine can find it. `seal_epoch` in `src/kint/crypto.py` compresses with gzip, pads to a size bucket and encrypts with AES-256-GCM under a random 32-byte data key, with an AAD of `keccak256(abi.encode(chainId, owner, space, seq, prev, lenBucket, rows_root, dek_id))`. The digest the contract stores is the keccak of the whole blob, header included, and the AAD ties the ciphertext to one owner, space, position and chain, so an epoch lifted anywhere else fails to open.

The attack on the keys that a reader can run offline is a passphrase guess. A passphrase wrap's key is HKDF over `scrypt(passphrase, salt = owner address, n = 2^17, r = 8, p = 1)`, and the header publishes each wrap's tag, the first 16 bytes of an HMAC under that key. A guess that reproduces the tag is the passphrase. scrypt makes each guess slow; it does not make a short or common passphrase safe. The passphrase `--passphrase-prompt` mixes into a wallet key falls the same way, but only to someone who also holds the signature.

### A phished derive signature

The vault message carries no nonce, no space and no contract: `KintVault(owner, purpose)` under the domain `kint`, version `1`, chain id 8453. The KEK is HKDF-SHA256 over the signature's `r || s` (low-S normalised, so a malleated twin derives the same key) with `info = "kint-kek-v1" || owner || space`. One signature therefore derives the KEK of every space that wallet owns, on any machine, for good, and every epoch header carries its wraps in the clear. The docstring of `src/kint/crypto.py` says it plainly: permanent, retroactive over all public calldata, unrevocable, covering every space of that wallet.

Wallets render the warning in `purpose`: "kint-memory-v1: signing this reveals your memory encryption key. Only sign it in a kint terminal or page you opened yourself." Before deriving anything, kint checks that the signature recovers to the owner and refuses otherwise. The signature cannot authorize a session key either: that authorization is a different EIP-712 type under a different domain (`kint EpochAnchor`, pinned to the contract address), so the digests never match.

Two things narrow the damage. A vault whose signature wrap was made with `kint connect --passphrase-prompt` salts the wallet key with a passphrase, so the signature alone opens nothing. And a rotation can leave the signature wrap behind. Add a passphrase wrap with `kint connect --add-passphrase`, let one epoch carry it onto the chain (`kint compact` writes one even when nothing changed), then run `kint rekey --smart-account --drop-missing` and type that passphrase at the prompt. A passphrase wrap is derived the same way whichever flag created it, so it is carried over and the signature wrap is dropped. The phished signature then opens every epoch up to the rotation and nothing after it, and the passphrase becomes the lock described above (connect with `--smart-account` from then on).

### A stolen session key

The session key is a plain EOA in a V3 scrypt keystore at `~/.kint/session.key` (mode 0600), unlocked by a local secret: `KINT_SESSION_PASSPHRASE` when set, else the macOS Keychain item `dev.kint-session-key`, else `~/.kint/local.secret`. It signs `push` and `setSessionKeyBySig` transactions and holds nothing that decrypts. On chain, `canWrite(owner, writer)` is true for the owner or for a key whose expiry is still in the future (`kint authorize` sets 30 days unless you pass `--days`). `push` only appends: it must name the current head as `prev` or it reverts with `StaleHead`, and the contract keeps only the new digest, seq and block. The thief cannot extend its own expiry: `setSessionKey` writes under the caller's own address, and `setSessionKeyBySig` needs the owner's signature over the current `authNonce`.

What it can do is append epochs until it expires or is revoked, each naming it as the `writer` in the Epoch event. Those epochs do not open, since it has no data key. A pull walks past one when a later snapshot in the same walk opens, because a snapshot's rows are the whole state; the report names the epoch and the snapshot that superseded it. Otherwise the pull stops there, and push and verify refuse on that machine. Only an epoch this machine cannot open is walked past: one the RPC would not serve, or one that opened and disagrees with the chain, still stops the pull, so the next pull retries (`tests/test_audit_fixes.py`).

The owner's way past an epoch that will never open is `kint compact --over-skipped`, or `kint rekey --over-skipped` to rotate at the same time, run on a machine whose last pull stopped there. It anchors that machine's store as one snapshot chained on the chain head, over the epoch it could not apply, so every later pull stops at the snapshot and never needs that epoch. The flag is honoured only for a snapshot on a machine whose last pull reported such an epoch, and it is a CLI flag, never a tool argument. Revoke the key first, or it can append another. `kint connect` and `kint rekey` read the key wraps from the newest epoch whose header parses, up to 32 back from the head; a forged epoch with a header that parses still stops them until such a snapshot sits on top.

It cannot shorten a cold start: the snapshot flag sits outside the AAD, so a pull that stops at a claimed snapshot which cannot be applied walks the full history instead (`tests/test_e2e_anvil.py` pins this).

kint has no revoke command. `kint session-key rotate` makes a new key on this machine and keeps the old file as `session.key.old`; it revokes nothing on chain. `kint authorize burn-nonce` consumes the owner's nonce but sets this machine's key again with its current expiry. Revoke from the owner wallet with the contract's `revokeSessionKey(key)`, which zeroes the expiry in the same block and consumes the nonce, so a signed authorization the thief still holds cannot re-arm the key:

```sh
cast send 0xa22E03f7a4145Bf4909a83595C90a38E14d79600 "revokeSessionKey(address)" 0xSESSION_KEY \
    --ledger --rpc-url https://mainnet.base.org
```

A Base Account owner sends the same call from the account, or `setSessionKey(key, 0)`, which has the same effect. The authorize page only ever sends `setSessionKey` with a future expiry.

### A compromised machine or VPS

A connected machine holds what it needs to work, and an attacker on it holds the same:

- the session key and the local secret that unlocks it;
- the cached data key at `~/.kint/vault-<space16>.aes`, encrypted under a key derived from that same local secret and valid for `KINT_KEY_TTL` (24 hours by default, renewed by kint-server after every successful pull and push; `session` keeps it in memory only);
- on the machine that created the vault, and wherever `kint recovery-code` or `kint rekey` ran, `~/.kint/RECOVERY-<space16>.txt`: the data key itself in base32. Push refuses on the creating machine when that file is gone, so it stays;
- the Sibyl store (`~/.sibyl-memory/memory.db` or `$SIBYL_MEMORY_DB`, plain SQLite), the mirror `~/.kint/mirror-<space16>.json` (the full row set) and the decrypted plaintext of every cached epoch;
- `KINT_OWNER_KEY`, if you left it in the environment after `kint authorize direct`.

With the session key and the data key together, an attacker can seal epochs that open and verify, or edit the store and anchor the edit with `kint push`, which kint-server's hold does not cover. `memory_verify` proves a row matches what the chain anchored; it does not prove the machine that anchored it was honest. What the machine never holds: the owner key (unless you left it there), the derive signature (read from stdin, or from a file that is read and then unlinked), any vault passphrase (used to derive a KEK, never stored) and any KEK. That stays true only while you never connect or rekey on it again.

To recover, revoke its session key first, then run `kint rekey` from a clean machine. The order matters: a key that is still live can append another epoch that does not open, which then takes `--over-skipped` again. The new data key is wrapped under KEKs the compromised machine never stored, so it opens nothing sealed after the rotation. What it already read stays read.

### A malicious or lagging RPC

Reads and sends go to `KINT_RPC_URL`, else an Alchemy key from the macOS Keychain item `dev.api.alchemy`, else `https://mainnet.base.org`. That endpoint sees which owner and space this machine asks about. It can refuse, time out or serve a pruned node; the pull then stops, at a gap or with an error, and the next pull retries. It cannot forge an epoch: kint checks that the calldata's owner, space and prev agree with the event and that `keccak(ct)` equals the event digest, then opens the AEAD, which nothing made without the data key passes and which binds each epoch to its seq and prev. It cannot roll back a machine that has pulled before: the watermark (`~/.kint/watermark-<space16>.json`) never decreases, and an older head, or a different digest at the same seq, is refused as a "stale or lying RPC".

The weak moment is the cold start, before there is a watermark. kint asks a second, independently operated endpoint (`KINT_RPC_URL_2`, else `https://base-rpc.publicnode.com` when the primary is the public Base RPC, else `https://mainnet.base.org`) for the head, retries once after 3 seconds, and refuses "to restore from a contested head" if the two still disagree on seq and digest. It also refuses when both URLs resolve to the same host, port and path. The second opinion covers the head only; the epochs come from the primary and pass the checks above. `KINT_ALLOW_SINGLE_RPC=1` accepts one operator, which then decides alone which head is newest on that first pull. Every error on its way to a tool result, a kint log line, or a `kint status`, `kint verify` or `kint doctor` line passes through `redact` in `src/kint/chain.py`, which keeps each URL's scheme and host and scrubs the path and query of the configured endpoints wherever they appear. kint-server logs an unexpected push, pull or verify failure as its error type and the redacted message, never a raw traceback; the CLI still prints a Python traceback, on your own terminal, for an error it does not catch.

### Two machines writing at once

`EpochAnchor.push` reverts with `StaleHead` when `prev` is not the current head, so two epochs can never claim the same seq. Before sending, `kint push` compares the chain head with this machine's mirror and refuses: "another machine pushed. Run `kint pull` first". The machine that lost holds rows the chain never saw while the chain moved on: a fork, and `kint pull` refuses rather than lose them, telling you to save what you need out of the store first. `kint pull --discard-local` moves `memory.db` and its `-wal` and `-shm` files aside to a `.kint-backup-<timestamp>` copy and restores from the chain; the unanchored rows stay in that backup and are not replayed. It moves the whole file, so the rows of any other tenant in the same store are only in that backup too. On one machine, a file lock per space (`~/.kint/head-<space16>.lock`) keeps two kint processes from pushing or pulling at once. The second waits up to 30 seconds, then stops with "another kint process holds the head lock for this space".

### Losing the owner key

The contract has no owner rotation. `canWrite` admits the owner or an unexpired session key, so existing session keys keep writing until they expire. No new key can be authorized and no expiry extended: `setSessionKey` must come from the owner, and `setSessionKeyBySig` needs the owner's signature. Reads never need the owner key once you have the data key: the recovery code (`kint connect --recovery-code-stdin`) or a passphrase wrap opens the memory on a new machine, and a connected machine keeps pushing until its session key expires, reconnecting with the recovery code whenever its cached data key lapses. An EOA owner without the key cannot sign the vault message again, so keep the recovery code somewhere that is not the machine. For a Base Account owner the vault key is already a passphrase, so losing the account ends new authorizations, not reads.

## What is public on Base

| On chain | What a reader learns |
|---|---|
| `head(owner, space)` | The latest digest, seq and block of every owner and space |
| `Epoch` event | `owner`, `space` and `writer` (all indexed), `seq`, `prev`, `digest`, `prevBlock`: who wrote each epoch and in which block, so when the memory changed |
| `push` calldata | `owner`, `space`, `prev` and `ct`, which is the cleartext header followed by the ciphertext |
| The header | Envelope version, flags (a snapshot epoch is visible), nonce, `rows_root`, `dek_id` (8 bytes, new after every rotation), the bucket, the wrap count and every wrap: kind (`0x01` signature, `0x02` passphrase), 16-byte key tag, nonce, wrapped data key. The tag is what a passphrase guess is tested against |
| The ciphertext length | Exactly the bucket plus a 16-byte tag, so only which bucket: 4096, 8192, 16384, 32768, 65536 or 98304 bytes. A space never publishes a smaller bucket than before |
| `sessionKeyExpiry`, `SessionKeySet`, `authNonce` | Which session keys may write for an owner, and until when. A session key pays its own gas, so the transfer that funded it is public too |
| The space id | keccak256 of `kint-space-v1` followed by the tenant id, so a guessable tenant name can be confirmed by hashing it |

Not public: row text, keys, categories, statuses, tier names, the row count (`n_rows` is inside the ciphertext), the data key, any KEK, the derive signature, any passphrase and the recovery code. `rows_root` is a 32-byte merkle root over keccak leaves: it commits to the whole state without spelling out any row.

## What is not built

- `kint pull --rebase` (row-level last-writer-wins over a fork). Refuse-and-tell ships; rebase is next, and `kint pull` does not accept the flag.
- A hosted (HTTPS) door for Claude on the web. The owner and session-key split makes it possible without uploading a key; the user hosts.
- The EOA-owned smart account as a key source (Coinbase Smart Wallet with an EOA owner). Measured on a fork, not shipped; Base Account owners use the passphrase path. Wrap kind `0x04` is reserved for it, and `0x03` for WebAuthn PRF.
- Owner rotation. Losing the owner key ends new writes for that owner once its session keys expire; reads never need it.
- The frontend viewer. [`docs/frontend-contract.md`](https://github.com/s0nderlabs/kint/blob/main/docs/frontend-contract.md) is its contract.

## Secrets stay in the terminal

The derive signature travels only on stdin (`kint connect --signature -`) or through `--signature-file`, a file kint reads and then unlinks. Any other value given to `--signature` is read as a file path, never as the signature. No MCP tool takes it: `memory_connect` has no parameter for it. kint prints the owner and the first 8 hex characters of the key tag, never the signature, the KEK or the data key.

`memory_connect` does accept two secrets as parameters (`src/kint/server.py`): `passphrase` and `recovery_code`, plus `owner`, which is required the first time. Either secret connects this machine directly, and it passes through the agent's context on the way. With `passphrase` the tool takes the Base Account path, and where no vault exists yet for that owner and tenant it creates one; it returns the path of the recovery code file, never the code.

> **Warning.** Anything typed into an agent chat lands in the transcript. Type the vault passphrase and the recovery code into a terminal instead: `kint connect --owner 0x... --smart-account --passphrase-stdin` or `kint connect --owner 0x... --recovery-code-stdin`. Called with no arguments on a machine that is not connected, `memory_connect` returns those commands for the human to run.

Rotating the data key is CLI only: `kint rekey` needs the wallet signature or the vault passphrase, and there is no rekey tool. `kint authorize direct` and `kint authorize burn-nonce` read the owner key from `KINT_OWNER_KEY` in the environment, never from argv; clear it when you are done.

Read [Introduction](/docs/introduction) next.

Source: [`README.md`](https://github.com/s0nderlabs/kint/blob/main/README.md), [`docs/judge.md`](https://github.com/s0nderlabs/kint/blob/main/docs/judge.md), [`src/kint/crypto.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/crypto.py), [`src/kint/pull.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/pull.py), [`src/kint/verify.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/verify.py), [`src/kint/connect.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/connect.py), [`src/kint/push.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/push.py), [`src/kint/keys.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/keys.py), [`src/kint/chain.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/chain.py), [`src/kint/restore.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/restore.py), [`src/kint/server.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/server.py), [`src/kint/page.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/page.py), [`contracts/src/EpochAnchor.sol`](https://github.com/s0nderlabs/kint/blob/main/contracts/src/EpochAnchor.sol).
