---
slug: how-it-works
title: How it works
description: The four paths a Sibyl row takes through kint, and the state on disk that each path leans on.
group: Concepts
order: 4
source: 'src/kint/server.py'
---

# What happens to one row.

A row starts as an ordinary Sibyl write, gets anchored on Base inside an encrypted epoch, comes back on another machine through Sibyl's own write methods, and is checked before the agent acts on it.

## Four paths

This page follows one row through those four paths (write, anchor, restore, read and decide), then names the pieces they share and every file kint keeps on disk.

```text
agent (Claude Code, Codex, Hermes, OpenClaw)
  │  MCP over stdio
  ▼
kint-server
  ├── Sibyl's eight tools, unmodified ──┐
  └── kint's six tools ─────────────────┤  one MemoryClient, one cap gate
                                        ▼
            Sibyl's store: $SIBYL_MEMORY_DB or ~/.sibyl-memory/memory.db
                                        │
      anchor: diff against the mirror, after the write returned
                                        ▼
            EpochAnchor on Base: one transaction per epoch, ciphertext in calldata
                                        │
      restore: walk, check, decrypt, replay through Sibyl's write methods
                                        ▼
            the same store on the next machine
                                        │
      read and decide: Sibyl's search, then each hit's leaf against the mirror
                                        ▼
            proceed, or refuse and write the refusal back
```

## Write: Sibyl's tools, unchanged

`kint-server` calls `build_server()` from `sibyl_memory_mcp.server` and gets Sibyl's eight tools exactly as shipped: `memory_remember`, `memory_recall`, `memory_search`, `memory_list`, `memory_forget`, `memory_set_state`, `memory_get_state` and `memory_record_event`. Then it adds six of its own: `memory_status`, `memory_connect`, `memory_pull`, `memory_push`, `memory_verify` and `memory_history`.

When the agent calls `memory_remember`, Sibyl's tool calls `set_entity` on its client, and the row lands in Sibyl's SQLite file in Sibyl's format. kint changes nothing in that write. On the one client it builds, kint wraps `set_entity`, `archive_entity`, `delete_entity`, `set_state` and `set_reference` so that, once a write has returned, it re-reads that row and notes its leaf: that is how kint-server tells a write through the tools from an edit behind them ([When a push is held](#when-a-push-is-held)). The store is `$SIBYL_MEMORY_DB`, or `~/.sibyl-memory/memory.db` when that is unset. The tenant is `KINT_TENANT`, falling back to the `tenant_id` and then the `account_id` in Sibyl's credentials, and last to Sibyl's default tenant.

The only kint code that runs during a Sibyl write is the size function inside the [cap gate](#the-cap-gate): Sibyl's own measurement plus a sum of the file sizes under `KINT_HOME`. Nothing touches the chain, an RPC or a signer inside a Sibyl write transaction.

## Anchor: push, after the write returned

Push reads the store after Sibyl has committed, and it never runs once per write. Inside kint-server every push (the watcher's, the exit hook's and `memory_push`) first passes the [drift hold](#when-a-push-is-held); `kint push` and `kint compact` in a terminal do not. One push goes like this:

1. It takes the [head lock](#the-head-lock) for the space.
2. It refuses when this machine is not connected; when the machine created the vault but its recovery code file is gone; when the data key is missing or expired ("nothing was dropped, the changes stay in the store until the next push"); when no key wraps are recorded for the space; or when the last pull left a gap. The one way past a gap is the owner's `--over-skipped` snapshot, from a terminal ([Epochs on Base](/docs/epochs#an-epoch-nobody-can-open)).
3. It exports every row this tenant holds in the four tiers the SDK writes (entities, state, reference, journal), reading the store with read-only SQL in rowid order.
4. It diffs those rows against the [mirror](#the-mirror-and-the-watermark). A row counts as changed when its leaf (a hash of its exact stored text) differs from the leaf the mirror holds, and as deleted when the mirror has it and the store does not. An empty diff stops here with `nothing to push: the store matches the last anchored epoch`, and no RPC is called. A snapshot (`kint compact`, `memory_push(snapshot=true)`, `kint rekey`) skips that stop and carries every row, even when nothing changed.
5. It reads the chain head. If that is not the head the mirror recorded, another machine has pushed, so it refuses (`CHAIN_MOVED`): run `kint pull` first, or `kint pull --discard-local` when unanchored local changes make that pull a fork. Under `--over-skipped` the snapshot chains on the chain head instead.
6. It checks on chain that this machine's session key may write for the owner.
7. It splits the change set so that each epoch's measured gzip size stays under 90 KB. A single row too large to fit one epoch on its own is named in a refusal before anything is sent, and push refuses until that row is shrunk or split in Sibyl. A snapshot is never split.
8. For each epoch it computes the merkle root of the full state after that epoch, then compresses, pads to a size bucket, and encrypts under the data key. It sends one transaction from the session key and waits for its confirmations (2 by default). It checks that the `Epoch` event's digest is the keccak of what was sent. Finally it caches the epoch, saves the mirror and raises the watermark.

The epoch format, and what Base can see of an epoch, are covered in [Epochs on Base](/docs/epochs).

> **Note.** Push anchors whatever the store holds when the diff runs, and a push from your terminal does exactly that. kint-server's own pushes are held instead when a row the chain vouches for changed behind Sibyl's tools while the server ran, or when verify already refused the value a row now holds ([When a push is held](#when-a-push-is-held)). An edit made while no server was running, and never refused, still goes out with the next session's first push. Checking a row against what the chain vouched for is the job of [read and decide](#read-and-decide-verify), which is why the agent runs that step before acting.

### When push runs

| Trigger | What starts it |
|---|---|
| Quiet | The store changed and then stayed unchanged for `KINT_QUIET_SECONDS` |
| Size | The estimated unanchored change (400 bytes per changed or deleted row) passed `KINT_SIZE_TRIGGER_BYTES`. This is checked at most once a minute while the store is dirty, however busy the agent is |
| On demand | `memory_push` or `kint push`, or a snapshot: `memory_push(snapshot=true)` or `kint compact` |
| On exit | kint-server exits normally or receives `SIGTERM` or `SIGHUP`. The signal handler only unwinds, so nothing touches the chain inside a Sibyl write; then an exit hook makes one best-effort push, when this machine is connected, the data key is cached and the push is not held |

The quiet and size triggers come from the watcher, a background thread that kint-server starts after its startup pull. Every `KINT_POLL_SECONDS` the watcher reads the modification time of the store and of its `-wal` file, and any change marks the store dirty. The watcher pushes nothing while this machine is not connected or the data key is not cached. Some writes change nothing that needs anchoring (a pull's replay also moves the modification time), so when the once-a-minute diff finds nothing unanchored, the watcher clears the dirty mark. At the defaults, the size trigger fires at 82 changed or deleted rows.

| Variable | Default | Meaning |
|---|---|---|
| `KINT_QUIET_SECONDS` | `300` | Seconds without a store change before the watcher pushes |
| `KINT_POLL_SECONDS` | `15` | How often the watcher looks at the store. Values below `1` become `1` |
| `KINT_SIZE_TRIGGER_BYTES` | `32768` | The estimated unanchored size at which the watcher pushes without waiting for quiet |
| `KINT_NO_WATCHER` | unset | `1` starts kint-server without the watcher. The exit push still runs |

If a value is not a number, kint logs a warning and uses the default. The other variables are listed in [Configuration](/docs/configuration).

Two pushes never overlap. Inside one server, a second request gets `BUSY` ("a push is already running"). Between processes on one machine, the head lock makes them take turns.

The exit push is best effort. A server killed before its exit push lands anchors nothing, and Claude Code gives a closing server about half a second before it kills it, less than a push with its confirmations takes, so under Claude Code the exit push rarely completes. The rows it missed stay in the store, unanchored, and the next kint-server session over that store picks them up: its watcher starts dirty, logs `watcher: N changed and M deleted row(s) were left unanchored by an earlier session; they are pushed at the next quiet period`, and pushes them once the quiet period passes. `kint push` anchors them at once.

### When a push is held

kint-server follows every row its own tool path writes. Sibyl's eight tools and kint's six share one client, and the wrapped write methods move a row's baseline to the leaf that was just written. The baseline becomes the whole store again when the server starts and after every successful pull and push.

Before a server-side push (the watcher, the exit hook, `memory_push`), kint looks at every row whose stored leaf differs from the leaf the mirror says was anchored, and holds the push when either is true:

- a `kint_refusal` entity in the store names exactly the value the row holds now, so `memory_verify` already refused it;
- the row changed, or an anchored row vanished, while this server ran, and no write through its tool path explains it (an edit straight into SQLite, say).

A row that was never anchored is not drift. A store kint cannot read holds the push too, because an unchecked push is what the hold exists to stop. A held push anchors nothing and drops nothing:

```json
{"ok": false, "error": "HELD", "message": "refusing to anchor: 1 row(s) changed behind Sibyl's tools while this server was running (entity rules/release-gate). Anchoring would make the chain vouch for a value kint cannot account for. Check the store, then `kint push` from your own terminal (or `kint pull --discard-local` to restore the anchored value).", "hint": "nothing was anchored and nothing was dropped; memory_verify still refuses the row"}
```

The log gets `push HELD (<reason>): <message>` once per distinct message, and the watcher waits for the next store change instead of retrying. `memory_status` works the hold out again on every call and returns it as `held`: `{"message", "reason", "at"}`, where `reason` names what tried to push (`watcher`, `exit`, `tool`, or `status` when the status call found it first), or null when nothing is held.

The way out is yours to take. `kint push` from a terminal is never held: check the store, then anchor it as it is. `kint pull --discard-local` moves the store aside and restores the anchored values; the unanchored rows, a refusal entity included, stay in the `.kint-backup-` copy.

The hold only knows this server's own tool path. A write into the same store from another process (a second session's kint-server, an SDK-direct agent) looks like an edit behind Sibyl's back, so this server holds until that process's push anchors the row, or until you run `kint push`. An edit made while no server was running is not seen at all: the next session's baseline starts from the edited store, and its first push anchors the edit unless verify refused it first.

## Restore: pull, through Sibyl's write methods

A pull runs in three places. kint-server starts one when it starts, if this machine is connected and the data key is cached, and waits for it up to `KINT_BOOTSTRAP_SECONDS` (default 20) before it serves. A pull still running by then finishes in the background (`bootstrap: still running; serving now, the pull finishes in the background`), and every RPC call gives up after `KINT_RPC_TIMEOUT` seconds (default 10), so a hung endpoint cannot keep the tools from being listed. The agent can call `memory_pull`, and a human can run `kint pull`. If the startup pull hits a fork, a freshness refusal or any other failure, kint logs it and the server serves the local store as it is.

Pull takes the [head lock](#the-head-lock) and refuses when this machine holds no data key. Then the checks run in this order, each one before the next:

1. **Freshness.** The watermark is a floor. A pull refuses a head older than the one this machine already saw, or one with the same seq and a different digest, as a stale or lying RPC. When there is no watermark (a cold start), a second RPC that is a different endpoint must agree on the head's seq and digest, or the pull refuses. `KINT_ALLOW_SINGLE_RPC=1` accepts a single RPC instead.
2. **Fork.** If the store already holds rows while this machine has no mirror, pull never merges them blindly. If the store has unanchored changes while the chain moved, that is a fork, and pull refuses rather than lose them. `kint pull --discard-local` (`memory_pull(discard_local=true)`) moves the store file and its `-wal` and `-shm` files aside to timestamped `.kint-backup-` copies and restores from the chain.
3. **Walk.** The walk starts at the head and goes back through the `prevBlock` field of each `Epoch` event, one exact-block log query per epoch, down to the epoch this machine already holds. Without `--full` it also stops at the newest snapshot epoch, whose rows are the whole state. `--full` (`full=true`) walks past snapshots, and afterwards caches, for history, every epoch from the head to the first that this machine has not decrypted yet.
4. **Each epoch.** Pull checks prev continuity, then takes the ciphertext from the epoch cache or the transaction's calldata (a `push` call whose owner, space and prev match the event) and trusts it only when its keccak equals the event digest. It checks the header and the data key, then the AES-GCM tag against an AAD that binds chain id, owner, space, seq, prev, bucket, rows root and data key id. The plaintext's own seq, space, prev and rows root must agree with the chain and the header, and its snapshot key must agree with the header's snapshot flag.
5. **Replay.** Rows go back through `MemoryClient.set_entity`, `set_state`, `set_reference` and `write_event`, the SDK's own write methods, so each one passes Sibyl's cap gate and is searchable again. Deleted entities go through `delete_entity`. Pull re-reads every replayed row and compares its leaf, and compares the running merkle root with the rows root in the epoch header. A row that does not come back byte-exact, or a root that does not match, is reported as a warning in the pull report.
6. **Record.** One epoch at a time, pull caches the epoch, saves the mirror and raises the watermark.

An epoch that cannot be applied is a gap. When this machine cannot open it and a later snapshot in the walk opens, the pull resumes at that snapshot and ends complete. Otherwise the pull stops there and the mirror stays at the last epoch it applied. Push and verify refuse until the gap is applied, and the next pull retries from that point ([Gaps](/docs/new-machine#gaps)). A snapshot epoch replaces the local picture. Rows the store already holds byte for byte are not written again, because a journal event has no key to overwrite. Replay is content-exact: row uuids and the entity, state and reference timestamps regenerate, but none of those fields are in the leaf, and the journal timestamp survives.

The pull ends by hashing the store itself and reporting whether the `store root matches the anchored root`. Restoring sends no transaction. The steps for a wiped machine are in [Restore on a new machine](/docs/new-machine).

## Read and decide: verify

`memory_verify(query, limit=5)`, or `kint verify "query"` from a shell, is the step between recall and action:

1. It calls `multi_record_search` on the shared client, the search Sibyl's own `memory_search` runs by default, with every precision gate, and gets ranked hits with a typed verdict. A verdict other than `ok` (`no_match`, `empty_store`, `abstained_on`, `negation_abstain`, `gated`), or no hit at all, means a refusal, because there is nothing to key a decision on.
2. It refuses when this machine has never pulled or pushed, or when its mirror is incomplete (a gap, or a root that differs from the anchored one).
3. It refuses when the chain head, read just before verify ran, is not the head the mirror recorded: another machine anchored something this one has not pulled (`chain moved to seq N at block B, pull first: ...`).
4. For every hit it re-reads the exact stored text by the key the search returned and hashes it into a leaf. It compares that with the leaf in the mirror and checks a merkle inclusion proof against the anchored root. Each hit comes out as `verified`, `drifted`, `unanchored` or `missing`.
5. If any hit is `drifted` or `missing`, verify refuses. For a drifted row the reason names the block that anchored the last good value and the head block this machine last saw. It writes the refusal back through `set_entity` as a Sibyl entity in category `kint_refusal` with status `refused` (`kint verify --no-write` skips that write). The next fresh session finds it with Sibyl's own tools, and while the row keeps the refused value, the refusal holds kint-server's automatic pushes.
6. If every hit is unanchored, it refuses. Otherwise it proceeds on the top verified hit and names any higher-ranked hit that is not anchored yet.

Verify sends no transaction. It reads the chain head once, outside every Sibyl write. When that read fails (or under `KINT_OFFLINE=1`) it says so and checks against what this machine last saw anchored, which push and pull checked against the chain when they ran. `memory_status` reports whether the mirror is still the chain head (`in_step`). The rules, the reasons and the temporal read are in [Verify before acting](/docs/verify).

## The pieces

### One client

Sibyl's MCP server keeps a single `MemoryClient` in a module-level `_client_cache` and rebuilds it only when `credentials.json` changes, appears or disappears. kint builds its client first (`store.open_client`) and writes it into that cache under Sibyl's own `_client_lock`, along with the current credentials mtime. Sibyl's tools then find a cached client that looks fresh and use it. No line of Sibyl is patched. kint's tools use the same client, and a pull that has epochs to apply builds a new one, after any wipe, and seeds it again.

The client reads the same credentials file as Sibyl's own and keeps the same `tier_cache.json` beside the store. The change kint makes on purpose is the cap gate's size function. If `credentials.json` changes while the server runs (Sibyl's own trigger, for `sibyl upgrade`), Sibyl rebuilds its cached client its own way. Until the next pull or restart, their tools then run on Sibyl's client instead of kint's. That client carries none of kint's wrapped write methods, so their writes look like edits behind the tools, and kint-server's automatic pushes are held until the next pull, a restart or a `kint push`.

### The cap gate

Sibyl's free tier is capped at 5 MiB (5,242,880 bytes) per account. Sibyl measures usage with `aggregate_db_size`, which sums the stores at five known paths (listed at the end of this page). kint builds the client with Sibyl's public `CapGate` and sets `db_size_fn` to that same aggregate plus `footprint_bytes()`, the size of every file under `KINT_HOME`. The gate enforces the cap, it does not just report it. A write that would take the sum past the cap meets Sibyl's gate exactly as Sibyl's own overflow would, and that includes rows a pull replays.

`kint status` prints the three numbers: Sibyl's stores, kint's state, and the enforced total against the cap. `memory_status` returns them as `cap`, with the fields `sibyl_bytes`, `kint_bytes`, `volunteered_total`, `cap_bytes` and `db_path`.

Sibyl can consult the gate while it holds its `BEGIN IMMEDIATE` write lock. That is why kint's part of the gate is a local file walk and nothing more.

### The head lock

`head_lock` takes an exclusive `flock` on `~/.kint/head-<space>.lock`. It retries every 0.2 seconds for up to 30 seconds, then fails with `another kint process holds the head lock for this space`. Push, pull and `kint rekey` hold it, so two harness sessions over one store take turns instead of racing. The lock only covers one machine. Between machines the chain head decides: a push that finds the head moved refuses, and a pull over unanchored changes refuses as a fork.

### The mirror and the watermark

The mirror (`mirror-<space>.json`) is what this machine believes the chain last saw. It holds every row in wire form (text included), each row's leaf, and the head those rows came from: seq, digest, block, bucket, transaction, the anchored rows root, and any epochs a pull had to skip. Push diffs against the mirror, verify compares leaves against it, and pull advances it one applied epoch at a time. The mirror is complete when no epoch was skipped and the root of its leaves equals the anchored root. Verify refuses while it is not complete, and also when the chain head has moved past it; push refuses while an epoch is skipped, except for the owner's `--over-skipped` snapshot.

The watermark (`watermark-<space>.json`) holds the seq, digest and block of the newest epoch this machine has pushed or applied, and its seq never decreases. A pull checks it first as the freshness floor. A pull is a cold start precisely when there is no watermark.

### The epoch cache

`epochs/<space>/` keeps three files per epoch, named by the eight-digit seq:

- the ciphertext (`.bin`)
- the decrypted plaintext (`.json`)
- the metadata (`.meta.json`): seq, digest, prev, block, transaction, bucket, rows root and writer, plus the cost for an epoch this machine pushed

Pull uses a cached ciphertext only when its keccak still equals the event digest, and otherwise fetches the calldata again. `memory_history` and verify's provenance read the plaintext files, so a machine's history covers only the epochs it has decrypted. After a cold start that stopped at a snapshot, the history begins at that snapshot, a later pull that stops at a newer snapshot skips the diff epochs before it, and `kint pull --full` backfills both.

## Where kint keeps its state

Everything lives under `KINT_HOME`, which defaults to `~/.kint`:

```text
~/.kint/                        mode 0700
├── kint.log                    the server's log (stdout belongs to the MCP transport)
├── session.key                 this machine's session key, a V3 scrypt keystore
├── session.key.old             the previous one, after kint session-key rotate
├── local.secret                only when neither the macOS Keychain nor KINT_SESSION_PASSPHRASE supplies the machine secret
├── enrol-<space>.json          owner, tenant, and the key tags this machine can open
├── wraps-<space>.json          the data key's wraps
├── vault-<space>.aes           the cached data key, encrypted, with an expiry
├── RECOVERY-<space>.txt        the recovery code: written for a fresh vault, by kint recovery-code, and by kint rekey
├── mirror-<space>.json         what this machine last saw anchored
├── watermark-<space>.json      the freshness floor
├── head-<space>.lock           the head lock
└── epochs/
    └── <space>/
        ├── 00000001.bin        ciphertext
        ├── 00000001.json       decrypted plaintext
        └── 00000001.meta.json  seq, digest, prev, block, tx, bucket, rows_root, writer
```

`<space>` is the first 16 hex characters of the space id, `keccak256("kint-space-v1" || tenant)`. kint writes its state files with mode 0600 and replaces them atomically (the log and the lock file are opened in place). The keys, the wraps and the recovery code are explained in [Keys and custody](/docs/keys).

### Why ~/.kint sits outside Sibyl's paths

Sibyl's `aggregate_db_size` sizes the stores at these five paths, WAL included, and counts each store once by resolved path:

1. the store the client is writing to
2. `~/.sibyl-memory/memory.db`
3. `$HERMES_HOME/sibyl/memory.db` (`HERMES_HOME` defaults to `~/.hermes`)
4. `$HERMES_HOME/sibyl/profiles/<profile>/memory.db`, for every profile
5. `$SIBYL_MEMORY_DB`, when it is set

kint's state sits outside all of them so that the two halves of the count never overlap. Sibyl's number is exactly what Sibyl measures without kint, kint's number covers every file under `KINT_HOME`, and the gate enforces the sum. A `KINT_HOME` that contained one of those stores would count it twice. `kint doctor` fails its `kint home placement` check when `KINT_HOME` is inside `~/.sibyl-memory`. Kept apart, the bytes kint adds to a machine stay visible, counted, and held to the cap Sibyl already enforces.

Read [Keys and custody](/docs/keys) next.

Source: [`src/kint/server.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/server.py), [`src/kint/push.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/push.py), [`src/kint/pull.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/pull.py), [`src/kint/store.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/store.py), [`src/kint/paths.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/paths.py), [`src/kint/epoch.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/epoch.py), [`src/kint/restore.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/restore.py), [`src/kint/verify.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/verify.py).
