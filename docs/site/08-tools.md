---
slug: tools
title: MCP tools
description: The fourteen tools kint-server serves: Sibyl's eight unmodified, kint's six, every parameter and error.
group: Reference
order: 8
source: 'src/kint/server.py'
---

# Their eight tools ship unmodified; kint adds six.

`kint-server` is one MCP server on stdio: Sibyl's own `build_server()` registers their eight `memory_*` tools exactly as shipped, and kint registers six more on the same instance.

## What the server does around the tools

A harness sees fourteen tools. This page lists every one: its parameters and defaults, what it returns, and every error it can return.

- **One client.** kint opens one `MemoryClient` on the store at `SIBYL_MEMORY_DB` (default `~/.sibyl-memory/memory.db`) for the tenant in `KINT_TENANT` (else Sibyl's `credentials.json`, else Sibyl's default), and seeds it into Sibyl's module cache. Their eight tools write through it, so `KINT_TENANT` picks their tenant too, and the cap they enforce counts kint's own footprint against Sibyl's 5 MiB free-tier cap (5,242,880 bytes). If Sibyl's `credentials.json` changes while the server runs, Sibyl's cache builds its own client again; restart `kint-server` after that.
- **Pull on start.** When this machine is connected and the data key is cached, the server pulls from Base as it starts. It waits for that pull at most `KINT_BOOTSTRAP_SECONDS`, then serves while the pull finishes behind it; a `memory_pull` or `memory_push` in the meantime waits for the pull's head lock, up to 30 seconds. A fork, a freshness refusal or a failed pull is logged, and the server serves the local store anyway. [Harnesses](/docs/harnesses) has the timeouts.
- **Push while serving.** A watcher polls the store's modification time and pushes unanchored changes after a quiet period, or sooner when the change set grows past a size estimate. It pushes only when the machine is connected and the data key is cached, and it starts with whatever rows an earlier session left unanchored.
- **Hold instead of launder.** Every push the server makes (the watcher's, the exit push, `memory_push`) checks the store first and answers `HELD`, anchoring nothing, when a row the chain vouches for changed behind Sibyl's tools while the server ran, or when `memory_verify` already refused exactly the value it holds. `kint push` in a terminal is never held. [Limits](/docs/limits#writers) has the edges.
- **Renew the data key.** Every successful pull and push moves the cached data key's deadline forward by `KINT_KEY_TTL`, so a server in use does not lapse.
- **Push on exit.** On a normal exit, `SIGTERM` or `SIGHUP`, the server pushes whatever is unanchored, once and best effort. The signal handler only marks the exit; the push runs after the tool call in flight has finished, never inside a Sibyl write.
- **Logs never touch stdout.** The stdio transport owns stdout. kint logs to stderr and to `kint.log` under `KINT_HOME` (default `~/.kint`).

| variable | default | what it sets |
|---|---|---|
| `KINT_QUIET_SECONDS` | `300` | seconds without a store change before the watcher pushes |
| `KINT_POLL_SECONDS` | `15` (floor 1) | how often the watcher checks the store |
| `KINT_SIZE_TRIGGER_BYTES` | `32768` | push early when (changed + deleted rows) x 400 bytes exceeds this; checked at most once a minute while dirty |
| `KINT_NO_WATCHER` | unset | `1` turns the watcher off |
| `KINT_BOOTSTRAP_SECONDS` | `20` | seconds the server waits for its startup pull before it serves |

The rest of the environment is in [Configuration](/docs/configuration).

## All fourteen

| tool | from | what it does |
|---|---|---|
| `memory_remember` | Sibyl | store an entity by category and name |
| `memory_recall` | Sibyl | read one entity by exact category and name |
| `memory_search` | Sibyl | full-text search across entities, state, reference and journal, with a typed verdict |
| `memory_list` | Sibyl | list entities, most recently updated first |
| `memory_forget` | Sibyl | archive an entity |
| `memory_set_state` | Sibyl | write a HOT-tier state document |
| `memory_get_state` | Sibyl | read a state document |
| `memory_record_event` | Sibyl | append a COLD-tier journal event |
| `memory_status` | kint | owner, space, chain head, mirror, unanchored changes, session key, cap |
| `memory_connect` | kint | connect this machine, or say exactly what the human must run |
| `memory_pull` | kint | restore or refresh the store from Base |
| `memory_push` | kint | anchor unanchored changes on Base now |
| `memory_verify` | kint | search, check every hit against its anchored leaf, decide proceed or refuse |
| `memory_history` | kint | every anchored version of a row, or the one live at a block |

Harnesses prefix the names with the registration: Claude Code shows `mcp__kint__memory_verify`, OpenClaw `kint__memory_verify`.

## Sibyl's eight

This is Sibyl's code, untouched. Everything below is read from `sibyl_memory_mcp/server.py` in the pinned `sibyl-memory-mcp` (>=0.2.1,<0.3).

| tool | parameters | returns |
|---|---|---|
| `memory_remember` | `category`, `name`, `body` | `{ok, category, name}` |
| `memory_recall` | `category`, `name` | `{ok, entity}` with `id, tenant_id, category, name, status, body, created_at, updated_at` |
| `memory_search` | `query`, `limit=10`, `tiers=None` | `{ok, query, count, results, verdict}` |
| `memory_list` | `category=None`, `limit=50` | `{ok, category, count, results}` |
| `memory_forget` | `category`, `name`, `reason=None` | `{ok, archived: {category, name}}` |
| `memory_set_state` | `key`, `body` | `{ok, key}` |
| `memory_get_state` | `key` | `{ok, key, body, updated_at}` |
| `memory_record_event` | `kind`, `body`, `category=None`, `name=None` | `{ok, event_id, kind}` |

- `memory_remember` is idempotent on `(category, name)`: a second call updates the entry. A dict or list `body` is stored as is; a string, number, boolean or null is wrapped as `{"value": ...}`.
- `memory_recall` bounds the body at 1,000,000 characters and sets `truncated` when it cuts.
- `memory_search` clamps `limit` to 1–50 and returns nothing, with a `no_match` verdict, for a query shorter than 3 characters. `tiers` is a comma-separated filter over `entity`, `state`, `reference`, `journal`; passing it calls the raw search directly and skips the multi-record linker and its abstention gate.
- `memory_list` clamps `limit` to 1–200.
- `memory_forget` moves the entity to `archived_entities`, where recall, list and search no longer see it, and records `reason`.
- `memory_set_state` keeps one row per key, overwritten on each set; a primitive body is wrapped as in `memory_remember`.
- `memory_get_state` returns `{ok: false, code: "NOT_FOUND", key}` as an ordinary result when the key is absent, and adds `truncated` when the body was cut.
- `memory_record_event` is append-only. `body` must be an object; `category` and `name` name the entity the event is about.

**Verdicts.** Every `memory_search` result carries `verdict`: `code`, `tokens`, `gate`, `gate_drops`, `best_pre_gate_coverage`, `tokens_total`, `tokens_scored`, `dropped_function`, `candidates`, `returned`, `abstained`, `recovery`, `explain`. `code` is `ok` when rows came back, otherwise exactly one cause: `abstained_on`, `negation_abstain`, `gated`, `empty_store` or `no_match`. `recovery` is one of `none`, `drop_token_and_retry`, `rephrase_without_negation`, `broaden_query`, `write_first`. On `abstained_on`, Sibyl's own instruction is to drop the word in `verdict.tokens[0]`, search again, and stop after two retries.

**Untrusted content.** `memory_recall`, `memory_search`, `memory_list` and `memory_get_state` add an `_untrusted_context` block (`nonce`, `begin`, `end`, `note`) telling the agent to treat stored values as data. They strip forged fence markers from every string and cap each search or list hit's `body` and `snippet` at 1,500 characters, inside a total budget of about 200,000.

**Errors.** Sibyl's tools fail as MCP errors (`isError` true) whose text is JSON: `error` (the exception class), `message`, `code`, and for some codes `recovery` and `upgrade_url`. `code` is one of `CAP_EXCEEDED`, `TIER_GATED`, `TIER_VERIFICATION_FAILED`, `NOT_FOUND`, `VALIDATION_ERROR`, `ERROR`. An argument of the wrong type comes back as `{ok: false, code: "VALIDATION_ERROR", error: "ValidationError", message}` without echoing the value. That guard wraps the server's tool dispatch, so it covers kint's six too.

## kint's six

Called with valid arguments, kint's tools do not raise. Every one returns a dict with `ok`; a failure is an ordinary result with `ok: false`, an `error` string, and usually a `message` or `hint` (`OWNER_REQUIRED` carries neither). An agent that only watches `isError` misses them: read `ok`.

### memory_status

No parameters. It reads local state, plus the chain when an owner is known (the head, the session key's balance, `canWrite`, `sessionKeyExpiry`). It never sends a transaction.

| field | value |
|---|---|
| `ok` | `true` |
| `owner` | the owner address this machine is enrolled under, or `null` |
| `tenant` | the tenant the server resolved |
| `space` | the space id for that tenant, hex |
| `db_path` | the Sibyl store the server wraps |
| `connected` | `true` when an owner is known (the data key may still be absent) |
| `data_key_cached` | whether the unwrapped data key is cached and unexpired |
| `held` | `null`, or why kint-server is holding its pushes: `message`, `reason` (`watcher`, `exit`, `tool`, or `status` when no push was tried yet) and `at` (UTC); recomputed on every call |
| `cap` | `sibyl_bytes`, `kint_bytes`, `volunteered_total`, `cap_bytes`, `db_path` |
| `mirror` | what this machine last saw anchored: `seq`, `digest`, `block`, `rows`; `null` until it connects or pulls |
| `unanchored` | `changed` and `deleted` row counts since that epoch, or `error` |
| `chain_head` | `seq`, `digest`, `block`, `contract`, or `error`; present only when an owner is known |
| `in_step` | `true` when the mirror's seq and digest equal the chain head's |
| `session_key` | `address`, `path`, `exists`, `balance_wei`, `balance_eth`, `authorized`, `expiry`, and `error` if a chain read failed |

`in_step` and `session_key` appear only when the chain head was read.

### memory_connect

| parameter | default | meaning |
|---|---|---|
| `passphrase` | `None` | the vault passphrase (the Base Account path, like `kint connect --smart-account`) |
| `recovery_code` | `None` | the recovery code; used first when both are given |
| `owner` | `None` | the owner address; required on the first connect, otherwise the enrolled owner is used |

Without `passphrase` or `recovery_code` it connects nothing. It returns `{ok: true, connected: true, owner}` when an owner is known and the data key is cached; otherwise it returns the three commands a human runs, verbatim:

```json
{
  "ok": true,
  "connected": false,
  "owner": null,
  "human_steps": [
    "EOA wallet (Ledger, MetaMask, Rabby, keystore): kint canonical-payload --owner 0x... > kint-canonical.json && cast wallet sign --data --from-file kint-canonical.json --ledger | kint connect --owner 0x... --signature -",
    "Base Account / smart wallet owner: kint connect --owner 0x... --smart-account --passphrase-stdin",
    "Lost both? kint connect --owner 0x... --recovery-code-stdin"
  ]
}
```

With `passphrase` or `recovery_code` it connects directly and returns `ok`, `owner`, `space`, `kek_tag8` (the first 8 hex of the key tag, `none` for a recovery code), `fresh_vault`, and `dek_source`: `local wraps`, `chain head header`, `fresh vault` or `recovery code`. A passphrase for an owner with nothing on the chain yet, and no key wraps on this machine, creates a vault; the result then adds `recovery_code_file` and a `note` to copy that code somewhere safe. A recovery code cannot start a vault.

Errors: `OWNER_REQUIRED` when no owner was passed and none is enrolled. Otherwise the exception class with `message`, for example `ConnectError` (wrong key, wrong tenant, a key the last rotation did not carry over, a recovery code for another vault), `ChainUnreadable` (the head could not be read and this machine holds no key wrap that the passphrase opens) or `KintCryptoError` (a recovery code that fails its checksum).

The derive signature is never accepted here. It is a secret: it travels on stdin through `kint connect --signature -` (or in a file that `--signature-file` reads and then deletes), never on argv and never through a tool.

> **Warning.** `memory_connect` does accept `passphrase` and `recovery_code`, and anything typed into an agent chat lands in the transcript. Prefer the terminal: `kint connect --owner 0x... --smart-account --passphrase-stdin` or `kint connect --owner 0x... --recovery-code-stdin`.

### memory_pull

| parameter | default | meaning |
|---|---|---|
| `discard_local` | `false` | move the local store aside and restore from the chain; the way past a fork |
| `force_scan` | `false` | accepted and passed to the pull; v0.3.0 does not act on it |
| `full` | `false` | walk past snapshot epochs to the first epoch; on a store already up to date, walk from the head to the first epoch and cache every one not yet decrypted, for `memory_history` |

It checks freshness first (the local watermark; on a cold start two different RPC endpoints must agree on the head, unless `KINT_ALLOW_SINGLE_RPC=1`), refuses a fork, walks epochs back from the head to the newest snapshot, verifies each against the chain, decrypts, and replays the rows through Sibyl's own write methods. An epoch this machine cannot open (not a kint epoch, or sealed under a key it lacks) is walked past when a later snapshot in the same walk opens; any other epoch it cannot apply stops the pull there. `discard_local` first moves `memory.db` and its `-wal` and `-shm` files to `<name>.kint-backup-<timestamp>`. A pull that walks epochs opens a fresh client and hands it to Sibyl's eight tools. The walk itself is in [Restore on a new machine](/docs/new-machine) and [Epochs on Base](/docs/epochs).

| field | value |
|---|---|
| `applied` | epochs applied in this pull |
| `skipped` | epochs the pull could not apply, as `{seq, block, tx, reason}`. An entry with `superseded_by` names the later snapshot the pull resumed at, and the picture is complete; an entry without it is where the pull stopped, and nothing after it is applied |
| `head_seq`, `head_digest`, `head_block` | the head this machine now holds |
| `rows_total` | rows in the store after the pull (on an up-to-date store, the mirror's row count) |
| `root_ok` | whether the store's merkle root equals the anchored `rows_root`; `null` when the store was already up to date |
| `rpcs_agreed` | on a cold start, whether the second RPC agreed; `null` otherwise |
| `unopenable` | epochs sealed under a data key this machine does not hold, as `{seq, block, tx, reason}` |
| `backfilled` | epochs `full` cached for history that this machine had not decrypted before |
| `message` | one line, including any warning count |

Errors: `NOT_CONNECTED` (hint `call memory_connect`); `FORK` (unanchored local changes while the chain moved, or a local store this machine has no record of); `NOT_FRESH` (the RPC served a head older than one this machine saw, the two RPCs disagree, `KINT_RPC_URL_2` is the same endpoint as the primary, or the second RPC did not answer); `PULL_FAILED` (for example, no data key on this machine); or the exception class, such as `ChainError`, or `TimeoutError` when another kint process held the head lock for 30 seconds.

### memory_push

| parameter | default | meaning |
|---|---|---|
| `snapshot` | `false` | anchor one epoch carrying the whole state instead of the diff, even when nothing changed (what `kint compact` does) |

It first checks whether the push must be held (`HELD`, below), then diffs the store against the last anchored epoch, splits the change set so each epoch compresses to under 90 KB, pads it to a size bucket, encrypts it to the wallet, and sends one Base transaction per epoch from this machine's session key, waiting for two confirmations each.

| field | value |
|---|---|
| `reason` | `tool` for this call (the watcher and the exit hook run the same push as `watcher` and `exit`) |
| `pushed` | epochs anchored |
| `changed_rows`, `deleted_rows` | the diff (for a snapshot, every row) |
| `head_seq`, `head_digest` | the head after the push |
| `epochs` | per epoch: `seq`, `tx`, `block`, `digest`, `bucket`, `rows`, `deleted`, `snapshot`, `cost_wei`, `gas_used`, `l1_fee` |
| `message` | `nothing to push: the store matches the last anchored epoch`, or what was anchored |

| `error` | when | what to do |
|---|---|---|
| `NOT_CONNECTED` | no owner enrolled on this machine | call `memory_connect` (hint `call memory_connect`) |
| `BUSY` | a push is already running in this server | wait (hint `a push is already running`) |
| `HELD` | a row the chain vouches for changed behind Sibyl's tools while this server ran, `memory_verify` already refused exactly the value a row holds, or the store could not be read to check; `message` names up to three rows per ground | stop and tell the human: nothing was anchored and nothing was dropped (hint `nothing was anchored and nothing was dropped; memory_verify still refuses the row`). They check the store, then run `kint push` or `kint pull --discard-local` in their own terminal |
| `KEY_EXPIRED` | the cached data key expired or is missing | the human runs `kint connect`; nothing was dropped |
| `CHAIN_MOVED` | another machine pushed under this owner, or this machine's own last push landed after its confirmation wait failed ([Limits](/docs/limits#writers)) | `memory_pull` (hint `call memory_pull first`); a plain push only reaches this check when it has changes, so that pull answers `FORK` and the human decides |
| `PUSH_FAILED` | no key wraps, the last pull left a gap (for an epoch that will never open, the message names `kint compact --over-skipped`), the recovery code file is gone on the machine that created the vault, one row over 90 KB compressed, a snapshot too big for one epoch, the session key not authorized, or an epoch that could not be sealed | read `message`; it names the fix |
| an exception class | for example `ChainError` (a revert, a confirmation timeout, an event digest that does not match), `KeyError_` (no session key on this machine), `TimeoutError` (another kint process held the head lock for 30 seconds) | read `message` |

### memory_verify

| parameter | default | meaning |
|---|---|---|
| `query` | required | what to search for |
| `limit` | `5` | how many hits to check |

It runs the same search `memory_search` runs without `tiers`: Sibyl's `multi_record_search` through the one client, with its linker and every precision gate, at its own `limit` (5, where `memory_search` defaults to 10). It re-reads the exact stored text of every hit by the key the search returned, hashes it, and compares it with the leaf this machine last saw anchored, with a merkle inclusion proof against the anchored `rows_root`. It also reads the chain head, outside every Sibyl write, and refuses when the head has moved past this machine's mirror. That read is best effort: when the chain cannot be read, the server logs `chain head unavailable (...); verifying against the local mirror only` and checks against the mirror alone; `KINT_OFFLINE=1` skips the read.

| field | value |
|---|---|
| `decision` | `proceed` or `refuse` |
| `reason` | one sentence; a drift names the block that anchored the last good value and the current head block |
| `query` | the query |
| `verdict` | Sibyl's typed verdict: `code`, `returned`, `recovery`, `tokens`, `gate` when Sibyl sets one, `explain`. `code` is `ok`, or one of Sibyl's five causes: `abstained_on`, `negation_abstain`, `gated`, `empty_store`, `no_match` |
| `hits` | per hit: `tier`, `key`, `category`, `snippet`, `rank`, `ts` |
| `checks` | per hit: `tier`, `key`, `category`, `status` (`verified`, `drifted`, `unanchored`, `missing`), `local_leaf`, `anchored_leaf`, `anchored_seq`, `anchored_block`, `anchored_tx`, `head_seq`, `head_block`, `rows_root`, `proof`, `proof_ok`, `reason` |
| `refusal_entity` | `kint_refusal/<tier>-<category or none>-<key>-<unix seconds>` when a refusal was written, else `null` |
| `chain_head` | the head read for this check, `{seq, digest, block}`; `null` when it could not be read, or when the decision was made before the head check |

It refuses when the verdict is not `ok` or there are no hits, when this machine has no mirror (it never connected, pulled or pushed), when the last pull left a gap or the local root differs from the anchored one, when the chain head moved past the mirror (`chain moved to seq N at block B, pull first: ...`), when any hit drifted or is missing, or when every hit is unanchored. An edit made on this machine to a row that was already anchored reads as `drifted` until it is pushed. The first drifted or missing hit is written back as a Sibyl entity in category `kint_refusal` with status `refused`, so the next fresh session finds it through Sibyl's own tools. While a row still holds the value a refusal names, every kint-server push answers `HELD`, so push your own edits before you verify them. A `proceed` whose higher-ranked hits are unanchored says so in `reason`. Errors come back as the exception class with `message`. The whole decision is in [Verify before acting](/docs/verify).

### memory_history

| parameter | default | meaning |
|---|---|---|
| `tier` | required | `entity`, `state` or `reference` |
| `key` | required | the entity name, state key or reference key |
| `category` | `None` | required for entities: the row id includes it, so an entity lookup without it finds nothing |
| `block` | `None` | return the version live at this block instead of the list |

Without `block` it returns `{ok, versions, count}`, oldest first. Each version is `seq`, `block`, `tx`, `leaf`, `body`, `status`, `deleted: false`, plus `snapshot: true` when a snapshot epoch carried it; a snapshot that re-anchors an unchanged row adds no version. A deletion is `{seq, block, tx, deleted: true}`. With `block` it returns `{ok, at_block, version}`: the last version anchored at or before that block, or `null`.

Every `block` is an upper bound: the row existed no later than that block. History reads the local epoch cache only, so it covers the epochs this machine has decrypted. A restore that stopped at a snapshot starts there, and a later pull that jumped to a newer snapshot skips the diff epochs in between; `memory_pull` with `full` caches all of them, as far back as the newest key rotation. Errors come back as the exception class with `message`.

## Which tool, when

1. At the start of a session, call `memory_status`. If `connected` or `data_key_cached` is false, call `memory_connect` with no arguments and give the human its `human_steps`. If `in_step` is false, call `memory_pull`: `memory_verify` refuses while the head is past this machine's mirror. If `held` is not `null`, tell the human its `message`.
2. Recall with Sibyl's tools: `memory_search`, `memory_recall`, `memory_get_state`, `memory_list`.
3. Before acting on anything recalled, call `memory_verify`. Act only on `proceed`. On `refuse`, tell the human the `reason` and do not act. If you changed the row yourself, `memory_push` before you verify it.
4. Write with Sibyl's tools. You do not need to push after each write; the watcher anchors after the quiet period. Call `memory_push` when the change must be on Base now, for example before another machine picks the work up.
5. On `CHAIN_MOVED`, call `memory_pull`; with unanchored changes here it answers `FORK`. On `FORK`, stop and ask the human: `discard_local` throws the unanchored rows away. On `KEY_EXPIRED`, the human runs `kint connect`. On `HELD`, stop: the human checks the store and runs `kint push` or `kint pull --discard-local` in their own terminal.
6. For what the agent believed earlier, call `memory_history`, with `block` for a point in time.
7. When a cold start walks many epochs, `memory_push` with `snapshot` lets the next one stop at the snapshot.

## There is no rekey tool

Rotating the data key is `kint rekey`, in a terminal, and nothing else. It needs every key that is to keep opening the vault (the wallet signature, the vault passphrase), and those are read on stdin or at a prompt in the human's own terminal, never through an agent chat. Creating and authorizing a session key, writing the recovery code file, registering harnesses and `--over-skipped` (the owner's way past an epoch that will never open, on `kint compact` and `kint rekey`) are CLI only too. [Keys and custody](/docs/keys) explains the rotation.

Read [CLI](/docs/cli) next.

Source: [`src/kint/server.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/server.py), [`src/kint/verify.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/verify.py), [`src/kint/push.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/push.py), [`src/kint/pull.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/pull.py), [`src/kint/connect.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/connect.py), [`src/kint/store.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/store.py), [`sibyl_memory_mcp/server.py`](https://github.com/Sibyl-Labs/Sibyl-Memory).
