---
slug: sibyl
title: Built on Sibyl Memory
description: What Sibyl decides, what kint decides, and every part of Sibyl that kint relies on.
group: Background
order: 15
source: 'src/kint/server.py'
---

# Built on Sibyl Memory, under it.

Sibyl decides what the agent remembers; kint decides where that memory lives and who can read it. This page names every seam between the two, and what breaks if you take Sibyl away.

## Two jobs, two owners

| question | answered by | how |
|---|---|---|
| what the agent remembers, and in which tier | Sibyl | their eight tools, unmodified |
| which stored row answers a query, and why a search came back empty | Sibyl | `multi_record_search` and the typed verdict from `verdicts.py` |
| how much a free account may store | Sibyl | `CapGate`, 5 MiB (5,242,880 bytes); kint adds its own bytes to the count |
| where the memory lives once it leaves the machine | kint | encrypted epochs in Base calldata under EpochAnchor |
| who can read it | kint | a data key that only the owner's wallet signature, vault passphrase or recovery code opens |
| whether a recalled row is still what the chain vouches for | kint | `memory_verify` |
| what a row held at an earlier block | kint | `memory_history` |

kint never changes how Sibyl ranks, gates or stores a row. Rows enter Sibyl's store through Sibyl's own write methods, whether the agent wrote them, a restore replayed them, or `memory_verify` wrote a refusal. kint's direct reads of the SQLite file open it read-only (`mode=ro`). The one time kint touches the file itself is `kint pull --discard-local` (or `memory_pull` with `discard_local`), which moves `memory.db`, `memory.db-wal` and `memory.db-shm` aside to a `.kint-backup-<YYYYmmdd-HHMMSS>` name before it restores. Nothing is deleted.

## kint-server is their server plus six tools

```python
from sibyl_memory_mcp.server import build_server

def build_kint_server():
    mcp = build_server()   # their eight tools, exactly as shipped
    ...
    @mcp.tool()
    def memory_status() -> dict[str, Any]:
        ...
```

`build_kint_server()` calls Sibyl's `build_server()`, which returns their FastMCP server with their eight tools registered, then adds six `@mcp.tool()` functions to the same object. No line of Sibyl is edited and none of their functions is replaced. kint puts one thing into their module, the client described below, and wraps five write methods on that one client object so it can tell a write through the tools from an edit made behind them ([The writes kint watches](/docs/sibyl#the-writes-kint-watches)).

| tool | from | what it does |
|---|---|---|
| `memory_remember` | Sibyl | store an entity |
| `memory_recall` | Sibyl | read an entity by category and name |
| `memory_search` | Sibyl | FTS5 search across entities, state, reference and journal |
| `memory_list` | Sibyl | list entities, optionally filtered by category |
| `memory_forget` | Sibyl | archive an entity (moved to `archived_entities`, out of recall, list and search) |
| `memory_set_state` | Sibyl | write a HOT-tier state document |
| `memory_get_state` | Sibyl | read a HOT-tier state document |
| `memory_record_event` | Sibyl | append a COLD-tier journal event |
| `memory_status` | kint | owner, space, chain head, mirror, unanchored changes, session key, whether a push is held, cap accounting |
| `memory_connect` | kint | connect this machine to the vault, or return the terminal steps a human runs |
| `memory_pull` | kint | restore or refresh the store from Base |
| `memory_push` | kint | anchor unanchored changes now; `snapshot` anchors the whole state |
| `memory_verify` | kint | search through Sibyl, check every hit against its anchored leaf and the chain head, decide |
| `memory_history` | kint | every anchored version of a row, each with a block-height upper bound |

`tests/test_mcp_stdio.py` starts `python -m kint.server` over real stdio, asserts that all fourteen names are listed, and calls Sibyl's `memory_remember` and `memory_search`, then five of kint's tools, through it. The full parameter list for every tool is in [MCP tools](/docs/tools).

`kint setup` registers `kint-server` with Claude Code, Codex, Hermes and OpenClaw and leaves any `sibyl-memory-mcp` registration alone. For Claude Code it prints a reminder to run `claude mcp remove -s user sibyl-memory` if Sibyl's own server is also registered (one store, one server). A second server over the same store would build its own client, so its copy of the eight tools would not count kint's bytes against the cap, and its writes would look to kint like edits made behind the tools.

## One client, one cap

`store.open_client()` builds the `MemoryClient` "exactly the way Sibyl's server does, plus the volunteered cap". It reads the same credentials (Sibyl's `_load_credentials()`), takes the tier from them (default `free`), and keeps Sibyl's `tier_cache.json` beside the store. The store is `SIBYL_MEMORY_DB`, or `~/.sibyl-memory/memory.db` when that is unset. The tenant is `KINT_TENANT`, then the credentials' `tenant_id`, then their `account_id`, then Sibyl's `DEFAULT_TENANT`.

`store.seed_sibyl_server_cache()` then writes that client into Sibyl's module-level `_client_cache`, under Sibyl's own `_client_lock`, together with the current `credentials.json` mtime and whether the file exists. Sibyl's `_open_client()` rebuilds its client only when there is none, or when that mtime or existence changed, so their eight tools find kint's client and use it.

If `credentials.json` changes while the server runs (Sibyl's trigger for `sibyl upgrade`), Sibyl rebuilds its own client, with a gate that counts only Sibyl's stores, and their tools use it until a kint-server pull that finds new epochs builds kint's client again and reseeds the cache, or until a restart. kint's own tools keep kint's client. The rebuilt client is not one kint watches, so while their tools use it, a write through them to a row that is already anchored reads as a change made behind them, and kint-server holds its own pushes until you run `kint push` from a terminal or restart the server. More on the client in [How it works](/docs/how-it-works#one-client).

The cap is volunteered through the size function Sibyl's gate calls. `MemoryClient` takes a `cap_gate`, and `CapGate` takes a `db_size_fn`:

```python
def volunteered_size_fn(db_path: Path):
    def fn() -> int:
        return aggregate_db_size(db_path) + paths.footprint_bytes()
    return fn

gate = CapGate(..., db_size_fn=volunteered_size_fn(db_path), local_tier_hint=tier, ...)
MemoryClient(storage, ..., cap_gate=gate, ...)
```

`aggregate_db_size` is Sibyl's own count across every store it resolves on the machine; `footprint_bytes()` is every file under `KINT_HOME` (default `~/.kint`). Before each write, Sibyl's gate checks that size plus the size of the proposed write. The cap (`FREE_TIER_CAP_BYTES`, 5 MiB), the tier decision and the refusal stay Sibyl's; kint changes only what the size counts. A write that would take the sum past the cap meets Sibyl's gate the way Sibyl's own overflow would, and that includes rows a pull replays. Inside the write transaction Sibyl re-checks the store's own absolute size, which leaves kint's bytes out unless that measurement fails and the gate falls back to the size function. The size function can run under Sibyl's `BEGIN IMMEDIATE` write lock (`archive_entity` checks the cap inside its transaction, and so does that fallback), which is why kint's half is a local file walk: nothing in `store.py` touches the chain, an RPC or a signer.

The last four lines of `kint status`:

```text
cap accounting (the same 5 MiB free cap Sibyl enforces):
  sibyl stores      <size>
  kint state        <size>   (mirror, epoch cache, keys; volunteered)
  enforced total    <size> of 5.00 MB
```

Sizes print in KB with one decimal below 1 MiB, and in MB with two decimals from 1 MiB up. `memory_status` returns the same numbers as `cap`: `sibyl_bytes`, `kint_bytes`, `volunteered_total`, `cap_bytes` and `db_path`.

On an activated free-tier account, Sibyl's own `sibyl status` reports one store's WAL-inclusive size as a share of the free cap, and lists every store it resolves when there is more than one. It knows nothing about `~/.kint`, so its percentage leaves kint's bytes out. The number the gate checks before writes made through kint's client is the `enforced total` line. `KINT_HOME` is outside every store `aggregate_db_size` sizes, so kint's bytes enter the count once, through the size function, and `kint doctor` fails its `kint home placement` check when `KINT_HOME` is inside `~/.sibyl-memory` ([why](/docs/how-it-works#why-kint-sits-outside-sibyls-paths)).

## The writes kint watches

On the one client, `kint-server` wraps five write methods: `set_entity`, `set_state`, `set_reference`, `archive_entity` and `delete_entity`. Each wrapper calls Sibyl's method first, unchanged, and returns its result. Only after it returns does kint re-read that one row read-only and note its leaf as the value the tool path wrote; a failure in that bookkeeping never reaches the caller. Their eight tools, kint's own tools and a pull's replay all write through this client.

Those notes are what let kint tell a write through the tools from an edit made behind them. The watcher, the exit hook and `memory_push` check them before anchoring. A row whose stored text differs from the leaf this machine last saw anchored holds the push when either:

- it changed, or vanished, while the server was running, with no write through the tools to account for it (edited straight in SQLite, say); or
- a `kint_refusal` entity names exactly the value it holds now.

A held push returns error `HELD` with nothing anchored and nothing dropped, `memory_status` carries the message under `held`, and the watcher waits for the store to change again instead of retrying. The notes reset to the store's current leaves at start and after every successful pull and push, so a row changed before the server started is not held on that ground alone. `write_event` is not wrapped: a journal event has no key to overwrite, so an edited one shows up as a new row plus a vanished anchored one, and the vanished one holds the push. `kint push` from a terminal never runs this check.

## What kint relies on inside Sibyl

kint uses a short, fixed list of Sibyl's code. Everything else in Sibyl is theirs to change.

| Sibyl | kint uses it for | kint file |
|---|---|---|
| `build_server()` in `sibyl_memory_mcp.server` | serving their eight tools | `server.py` |
| `_client_cache`, `_client_lock`, `_credentials_mtime()`, `DEFAULT_CRED_PATH`, `_load_credentials()` in `sibyl_memory_mcp.server` | seeding the one client; reading the same credentials | `store.py` |
| `MemoryClient`, `DEFAULT_TENANT`, `storage.Storage` | building the client | `store.py` |
| `CapGate`, `TierCache`, `aggregate_db_size`, `FREE_TIER_CAP_BYTES` in `sibyl_memory_client._capcheck` | volunteering the cap; printing the cap numbers | `store.py` |
| `multi_record_search` in `sibyl_memory_client.multi_record`, `verdicts.VerdictCode`, `verdicts.explain` | finding the row through every precision gate and keying the decision on the verdict | `verify.py` |
| `set_entity`, `set_state`, `set_reference`, `write_event`, `delete_entity` | replaying rows and deletions; writing the refusal entity | `restore.py`, `verify.py` |
| `set_entity`, `set_state`, `set_reference`, `archive_entity`, `delete_entity` on the shared client | noting which rows the tool path wrote, for the hold | `server.py` |
| `storage.loads`, and the TEXT `storage.dumps` wrote | decoding stored TEXT for replay; hashing it as stored | `restore.py`, `canon.py` |
| the `entities`, `state_documents`, `reference_documents` and `journal_events` tables | the read-only export, and the re-read of one row by key | `export.py` |

> **Note.** `MemoryClient`, `Storage`, `DEFAULT_TENANT`, `CapGate`, `TierCache`, `FREE_TIER_CAP_BYTES`, `VerdictCode` and `explain` are exported by `sibyl_memory_client` itself (kint imports the cap names from `_capcheck`, where they are defined). The rest is not published as API: the server's `_client_cache`, `_client_lock`, `_credentials_mtime()`, `_load_credentials()` and `DEFAULT_CRED_PATH`, `aggregate_db_size`, `multi_record_search` (not in the package's `__all__`; kint imports it from `sibyl_memory_client.multi_record`, where Sibyl's own `memory_search` imports it from), and the table and column names the export reads. That is why kint pins `sibyl-memory-client>=0.8.1,<0.9` and `sibyl-memory-mcp>=0.2.1,<0.3`: an install of kint never resolves a Sibyl release outside those ranges.

### Search and the typed verdict

`memory_verify` calls `multi_record_search(client, query, limit=limit)` (`limit` defaults to 5) on the same client that serves Sibyl's tools. It is the call Sibyl's `memory_search` makes when it is given no `tiers`: a two-stage search that retrieves candidates with `client.search` (Sibyl's cross-tier FTS5 search over `entities_fts`, `state_documents_fts`, `reference_documents_fts` and `journal_events_fts`, with the folded-trigram shadow table as a fallback), then drops the ones Sibyl's precision gates reject. It returns a `SearchResults`: a list of hits in the shape `client.search` returns, with one typed `verdict` attached.

Six verdict codes are reachable. `ok` comes with hits; the other five name why a result is empty:

| code | what Sibyl found |
|---|---|
| `ok` | ranked hits that cleared every gate |
| `abstained_on` | a content word in the query has no support anywhere in the store |
| `negation_abstain` | a negation word was dropped from the query, and Sibyl's negation policy abstains |
| `gated` | candidates were found, then dropped by a scoring gate |
| `empty_store` | the tenant has no searchable row in any tier |
| `no_match` | the query ran with every gate armed and nothing matched |

kint keys on the code: anything but `ok`, or zero hits, refuses with `no ranked candidate to act on: Sibyl's verdict is <code>`. Sibyl's `memory_search` given `tiers` calls `client.search` directly and skips those gates, so a tier-filtered search can return a row that `memory_verify` then refuses. The rest of the decision is in [Verify before acting](/docs/verify#sibyl-finds-the-row).

After the verdict, verify checks the chain head when its caller could read it. `memory_verify` reads the head outside every Sibyl write and passes it in; `kint verify` does the same unless `KINT_OFFLINE=1`. A head that differs from this machine's mirror refuses with `chain moved to seq N at block B, pull first`, because another machine may have superseded the row. When the head cannot be read, verify checks against the local mirror only and says so, in `kint.log` for the tool and on stderr for the CLI.

A refusal over a drifted row goes back into Sibyl as an entity: `client.set_entity("kint_refusal", name, {...}, status="refused")`, with the name `<tier>-<category or none>-<key>-<unix seconds>` cut to 200 characters. A fresh session finds it through Sibyl's own tools, and kint-server reads it back: while the row still holds the value a refusal named, every push the server makes itself is held.

### The four write methods

A restore replays rows through the SDK, never through SQL (`restore.py`):

```python
def write_row(client, row: Row) -> None:
    if row.tier == "entity":
        client.set_entity(row.category, row.key, loads(row.body), status=row.status)
    elif row.tier == "state":
        client.set_state(row.key, loads(row.body))
    elif row.tier == "reference":
        client.set_reference(row.key, row.body if row.body is not None else "",
                             metadata=loads(row.meta) if row.meta is not None else None)
    elif row.tier == "journal":
        client.write_event(
            evaluated=loads(row.evaluated), acted=loads(row.acted),
            forward=loads(row.forward), extra=loads(row.extra), ts=row.ts,
        )
```

Deletions replay first, then rows in the order the export read them (rowid order on the machine that pushed). Only entities have an SDK delete, so a deletion replays as `delete_entity` and any other tier is reported as `no SDK delete for this tier`. After the replay every row is exported again and its leaf compared with the anchored one; a row that differs is reported as `stored text differs from the anchored leaf after replay`, and one that did not come back as `row missing after replay`. Pull records either as a warning on that epoch, never as a silent success. When the epoch is a snapshot, only rows whose stored text differs are replayed, because writing a journal event again would duplicate it (an event has no key to overwrite).

Going through the SDK is what makes the restored store answerable: Sibyl's indexes, its shadow table and its cap gate see a replayed row the way they see any write. The row ids (uuids) and the entity, state and reference timestamps regenerate on replay. The journal `ts` survives, because `write_event` takes it as an argument.

### The exact stored TEXT

Sibyl's `storage.dumps()` turns every JSON value the SDK stores into TEXT (entity and state bodies, journal payloads, reference metadata, and a reference body passed as a dict or list) with `json.dumps(payload, separators=(",", ":"), ensure_ascii=False)`. It does not sort keys; its docstring says `sort_keys=False`, to preserve insertion order. A reference body passed as a string is stored as given. kint's leaf hashes the stored TEXT column exactly as it sits in SQLite, read by SQL and never re-serialised. In `canon.py`'s words, re-serialising "would refuse every row on device two".

On replay, `loads()` hands the SDK a value with its keys in stored order, and `dumps()` writes it back as the same TEXT (a reference body goes back as the stored string itself), so the leaf a new machine computes is the leaf the chain anchored. The leaf leaves out the timestamps Sibyl regenerates (entity, state and reference `updated_at`) and includes the journal `ts`. Leaves are ordered by their canonical key, never by rowid, so every machine computes the same root over the same content.

## What the export covers

`export.py` reads the four tiers the SDK writes, for one tenant, by raw SQL in rowid order, over a read-only connection. The SDK has no enumeration for state or reference documents and no rowid ordering anywhere (`list_entities` orders by `updated_at DESC` and clamps), so the export reads the tables directly. The restore is the half that goes through the SDK.

| tier | table | columns read | key |
|---|---|---|---|
| entity | `entities` | `rowid, category, name, status, body, updated_at` | `name`, with `category` |
| state | `state_documents` | `rowid, document_key, body, updated_at` | `document_key` |
| reference | `reference_documents` | `rowid, doc_key, body, metadata, updated_at` | `doc_key` |
| journal | `journal_events` | `rowid, id, ts, evaluated, acted, forward, extra` | a content key over `ts, evaluated, acted, forward, extra`; identical events get `:1`, `:2` in rowid order |

`read_row()` re-reads one row by the key Sibyl's search returned: an entity by tenant, category and name, a state or reference document by its key, a journal event by its Sibyl event id (and recomputes the same ordinal the export assigns). That is the text `memory_verify` hashes.

### What it does not cover

- **Other tables.** `entity_relations`, `revenue_events`, `error_events`, `archived_entities`, `flagged_actors`, `skill_proposals` and `learning_runs` are not exported.
- **The archive.** `memory_forget` moves an entity from `entities` into `archived_entities` with its reason. kint sees the entity leave `entities` and anchors a deletion, so the anchored state is right, but the archived copy is not carried: a restore replays the forget as a plain delete, and the restored machine has the entity gone and no archive row.
- **Derived indexes.** The FTS5 indexes and the shadow table are not exported. Sibyl's own insert triggers fill them as the replay writes rows.
- **Other tenants.** Every query filters on the one tenant kint serves.
- **Row ids and write timestamps.** They regenerate on replay, as above.
- **Account files.** `credentials.json` and `tier_cache.json` are not rows and are not exported.

## Delete the Sibyl Memory layer and what breaks

In the README's words:

The decision beat reaches the row through Sibyl's `memory_search` (four FTS5 indexes plus the shadow fallback) and keys on the typed verdict from `verdicts.py`. Without Sibyl there is no ranked candidate and no verdict to key on: the epoch is a decrypted blob with no query surface, so a fresh session neither refuses nor proceeds. Base holds the ciphertext; Sibyl is what turns it back into an answerable store. See `docs/judge.md` for the claims table with file and line.

Precisely, kint calls `multi_record_search`, the call `memory_search` makes, on the same client. Taken one call at a time:

- Remove the `multi_record_search(...)` call in `src/kint/verify.py` and there is no ranked candidate and no verdict: the decision cannot be made.
- Remove `sibyl_memory_mcp.build_server()` from `src/kint/server.py` and no harness can read or write memory at all.
- Remove the four SDK write calls in `src/kint/restore.py` and a restored machine has an encrypted blob and an empty store.

## Prior work

- **Sibyl Sovereign** (Sibyl Labs, in development): a cryptographic seal on every critical file, re-checked before every action, fail-closed, with an append-only audit trail. kint applies that mechanism one tier down, to the memory store itself, on Base. Same idea, theirs first.
- **anima** (s0nderlabs, 0G): anchors a keystore root hash on chain, roots only. On 0G the storage primitive is native; on Base a root alone is a receipt for data you still have to store somewhere, which is why kint puts the ciphertext itself in calldata.
- **ERC-8350** (Agent Memory State Registry, draft): the vocabulary of a per-space linear chain of committed deltas describes kint's epochs exactly. Reference shape only, not implemented.
- The verify-a-local-artifact-against-an-anchor pattern exists in several hackathon entries. Restoring the memory itself from the chain, and showing a superseded belief, do not.

## The claims table

[`docs/judge.md`](https://github.com/s0nderlabs/kint/blob/main/docs/judge.md) pairs kint's claims with the file and line that implement them, against Sibyl Memory at revision 761bfc6 (client 0.8.1, mcp 0.2.1), and lists what is not built. `pytest -q` and `forge test` run the tests that pin the claims; `tests/test_audit_fixes.py` pins the hold, the verdict and chain-head refusals, and the pull past an epoch that never opens. `scripts/gen_judge.py` regenerates the table by searching each file for the line that implements each claim.

Read [Limits and threat model](/docs/limits) next.

Source: [`src/kint/server.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/server.py), [`src/kint/store.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/store.py), [`src/kint/export.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/export.py), [`src/kint/restore.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/restore.py), [`src/kint/verify.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/verify.py), [`src/kint/canon.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/canon.py), [`src/kint/paths.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/paths.py), [`tests/test_audit_fixes.py`](https://github.com/s0nderlabs/kint/blob/main/tests/test_audit_fixes.py), [`README.md`](https://github.com/s0nderlabs/kint/blob/main/README.md), [`docs/judge.md`](https://github.com/s0nderlabs/kint/blob/main/docs/judge.md), and Sibyl's `sibyl_memory_mcp/server.py`, `sibyl_memory_client/_capcheck.py`, `client.py`, `multi_record.py`, `schema.sql`, `shadow.py`, `storage.py` and `verdicts.py` in [Sibyl-Memory](https://github.com/Sibyl-Labs/Sibyl-Memory).
