---
slug: verify
title: Verify before acting
description: memory_verify checks a recalled row against Base before the agent acts; memory_history reads old versions.
group: Concepts
order: 7
source: 'src/kint/verify.py'
---

# Recalled is not the same as vouched for.

`memory_verify` re-reads the exact stored text of a recalled row, hashes it and checks it against what Base anchored. The answer is `proceed` or `refuse`, and a changed row is refused with the blocks that prove it.

## The beat

Something the agent remembers is not proof that it still holds what was anchored. So before an agent acts on a recalled row, verify asks Sibyl for it and checks what Sibyl found against the chain. `memory_history` then shows what the row held at every anchored epoch.

The demo tenant `kint-demo`, head at epoch 2, block 51081880. The output below keeps the lines `kint verify` prints; `...` marks lines cut here (one line prints per checked hit), and the placeholders in angle brackets stand for values not recorded in the transcript.

```text
$ kint verify "release rule"
query: release rule
sibyl verdict: ok  hits: <n>
  verified   entity rules/release-gate: stored text matches the leaf anchored on Base
  ...
DECISION: PROCEED: entity rules/release-gate verified against rows_root 390336ff71dbcb85 anchored at epoch 2, block 51081880

$ sqlite3 ~/.sibyl-memory/memory.db "update entities set body = replace(body, 'never', 'always') where name = 'release-gate'"
$ kint verify "release rule"
query: release rule
sibyl verdict: ok  hits: <n>
  drifted    entity rules/release-gate: the stored text of this row no longer matches what was anchored: the chain vouches for 4ac605528bbb00e7 (epoch 2, no later than block 51081880), the store now holds <new leaf> (unanchored, head epoch 2 at block 51081880)
  ...
DECISION: REFUSE: entity rules/release-gate: the stored text of this row no longer matches what was anchored: the chain vouches for 4ac605528bbb00e7 (epoch 2, no later than block 51081880), the store now holds <new leaf> (unanchored, head epoch 2 at block 51081880)
refusal written back as Sibyl entity kint_refusal/entity-rules-release-gate-<unix seconds>

$ kint history entity release-gate --category rules
epoch 1 block <= 51081867 leaf f406bb0919d23360: {"rule":"never ship on a Friday; every release needs a green deadlift test and a second reviewer", ...}
epoch 2 block <= 51081880 leaf 4ac605528bbb00e7: {"rule":"never ship on a Friday; every release needs a green deadlift test, a second reviewer, AND a passing kint verify", ...}
```

The edit went straight into Sibyl's SQLite file, behind Sibyl's back. Sibyl still finds the row and still ranks it. kint catches it because the stored text no longer hashes to the leaf epoch 2 anchored. `history` still shows both anchored versions, because it reads the decrypted epochs, not `memory.db`.

If `kint-server` is running when an edit like that lands, its automatic push does not anchor it. The row changed behind Sibyl's tools while the server ran, so the watcher's push comes back `HELD`, anchoring nothing and dropping nothing, and `memory_status` shows why under `held`. Once verify has refused the value, the refusal entity holds it too, in this session and the next. [When a push is held](/docs/how-it-works#when-a-push-is-held) has the rules.

## Sibyl finds the row

Verify starts with the search Sibyl's own `memory_search` runs by default: `multi_record_search(client, query, limit=limit)` from `sibyl_memory_client.multi_record`. Inside `kint-server` the client is the same `MemoryClient` that serves Sibyl's eight tools; `kint verify` builds its client the same way. It is Sibyl's two-stage retrieve-then-verify search. Candidates come from the client's own full-text search over four FTS5 indexes (`entities_fts`, `state_documents_fts`, `reference_documents_fts`, `journal_events_fts`), then Sibyl's precision gates drop any candidate the query does not support, or abstain on the whole query. So verify applies the same gates the agent's own search does.

Every Sibyl search returns a `SearchResults`: a list of hits that carries a typed `verdict` from `sibyl_memory_client/verdicts.py`. The `VerdictCode` set is closed:

| code | meaning (from Sibyl's `explain`) |
|---|---|
| `ok` | rows matched; the only code on a non-empty result |
| `no_match` | the query ran with every gate armed and matched nothing, or carried no searchable terms |
| `empty_store` | the store holds no searchable rows for this tenant |
| `abstained_on` | one content word in the query appears nowhere in the store and blocks the whole query |
| `negation_abstain` | the query is negated and full-text search cannot honour a negation |
| `gated` | candidates were found, then dropped by a relevance gate |

Through this search every code is reachable; Sibyl's `NEGATION_POLICY` is `abstain`, so a negated query comes back `negation_abstain`. kint keys the decision on the code: anything other than `ok`, or zero hits, means there is no ranked candidate to act on, and verify refuses. The plain `client.search` primitive has no abstention gate and would have answered some of these queries with rows. kint's test asks for `Friday spaceship` on a store that has a Friday rule and no spaceship: `client.search` answers `ok`, and verify refuses on `abstained_on`. kint returns its own copy of the verdict with `code`, `returned`, `recovery`, `tokens`, `gate` (only when set) and `explain`:

```json
{"code": "ok", "returned": 3, "recovery": "none", "tokens": [], "explain": "3 row(s) matched."}
```

Take Sibyl out and nothing gets decided: the epoch is a decrypted blob with no query surface, and there is no verdict to key on.

## Re-read the exact stored text

A search hit carries a `snippet`, a highlighted excerpt. kint never hashes the snippet. For every hit it re-reads the row by the key the search returned (`tier`, `key`, `category`) through a read-only SQLite connection (`mode=ro`), the same columns the exporter reads:

| tier | lookup | columns hashed |
|---|---|---|
| entity | `category` and `name` | `category`, `name`, `status`, `body` |
| state | `document_key` | `document_key`, `body` |
| reference | `doc_key` | `doc_key`, `body`, `metadata` |
| journal | the event `id` the search returned | `ts`, `evaluated`, `acted`, `forward`, `extra` |

The text is hashed exactly as stored. Sibyl's `storage.dumps()` keeps insertion order on purpose, so a row parsed and re-serialised with sorted keys would hash differently and every row would refuse on a second machine.

A journal event gets a new uuid when it is replayed on another machine, so its identity is its content: the key is keccak256 over `kint-journal-key-v1` and the five content columns. A second identical event gets `:1`, the third `:2`, in rowid order.

## The leaf

The leaf is keccak256 over the prefix `kint-leaf-v1` followed by the row's fields, each written as a 4-byte big-endian length and its UTF-8 bytes (a null field is the length `0xFFFFFFFF` and no bytes):

```text
entity, state, reference:  kint-leaf-v1 | tier | category | key | status | body | meta
journal:                   kint-leaf-v1 | "journal" | null | key | null | ts | evaluated | acted | forward | extra
```

`updated_at` is left out, because Sibyl regenerates it when a row is replayed. The journal `ts` is content (`write_event` takes it explicitly), so it is in.

## The proof

The mirror is this machine's record of what the chain last saw: every row, its leaf, and the head (seq, digest, block). It lives at `~/.kint/mirror-<first 16 hex of the space>.json` (under `KINT_HOME`). Pull and push fill it; connecting a machine that has none writes an empty one at seq 0. Its `anchored_root` is the `rows_root` anchored with the head epoch.

The root orders leaves by canonical id (`tier`, `category`, `key` joined by a null byte), never by rowid, so every machine computes the same root over the same content. Pairs hash as keccak256 of the two children; an odd node is carried up unchanged; an empty set has the root keccak256 of `kint-empty-v1`.

When the stored leaf equals the mirror's leaf, verify builds a merkle inclusion proof for the row, a list of `[sibling, sibling_is_left]` pairs, and checks that it reproduces the mirror's root. Past seq 0 the decision has already required that root to equal the anchored `rows_root` (step 3 below). The proof and its result travel back in the check as `proof` and `proof_ok`.

> **Note.** Verify sends no transaction and makes one read: the chain head for this owner and space, taken before verify runs and outside every Sibyl write. When that head is not the one this machine last pulled or pushed, verify refuses before it checks a row. When the read fails, or `KINT_OFFLINE=1`, verify checks against the mirror and the epoch cache alone and says so: `kint verify` on stderr, `memory_verify` in the server's log.

## Four statuses per hit

| status | when | reason |
|---|---|---|
| `verified` | the stored leaf equals the anchored leaf and the proof reproduces the root | `stored text matches the leaf anchored on Base` |
| `drifted` | the stored leaf differs from the anchored leaf | `the stored text of this row no longer matches what was anchored: the chain vouches for <leaf> (epoch <seq>, no later than block <block>), the store now holds <leaf> (unanchored, head epoch <seq> at block <block>)` |
| `drifted` | the leaves match but the proof fails | `leaf matches but the inclusion proof against the anchored rows_root failed` |
| `unanchored` | the row is in the store but not in the mirror | `this row was written after the last anchored epoch; nothing on the chain vouches for it yet (push first)` |
| `missing` | the key the search returned no longer reads back | `the row the search returned is no longer in the store` |

Two blocks appear in a drift. The anchoring block comes from the epoch cache: the last epoch that changed this row. A snapshot epoch re-anchors every row, but it does not move the provenance of a row it did not change, so a `kint compact` leaves the named block where the value was written. (On a machine that restored from a snapshot and never ran `kint pull --full`, the snapshot is the oldest epoch it holds, and its block is the one named.) The head block is the mirror's head: the newest epoch this machine applied.

## The decision

Verify walks these checks in order and stops at the first that applies:

1. Sibyl's verdict is not `ok`, or there are no hits: refuse with `no ranked candidate to act on: Sibyl's verdict is <code>`.
2. There is no mirror file at all (normally a machine never connected under this `KINT_HOME`): refuse with `this machine has never pulled or pushed: nothing on the chain has been checked`. A machine that connected but never pulled has an empty mirror at seq 0 instead; step 4 refuses when the chain has moved past it, and otherwise every hit comes back `unanchored` and step 6 refuses.
3. The mirror is past seq 0 but incomplete: refuse with `this machine's picture of the memory is not the one the chain vouches for: <why>; pull again`. The why is `epochs <list> could not be applied on the last pull` when a pull stopped at a gap, or `the local mirror's root does not equal the rows_root anchored on the chain` when the replayed rows did not reproduce the anchored root.
4. The chain head was read and its seq or digest is not the mirror's: refuse with `chain moved to seq <N> at block <B>, pull first: this machine last saw seq <M> (<12 hex>), so the row it would check may be superseded`. Another machine anchored something this one has not pulled, and nothing is checked against a stale picture.
5. Any hit is `drifted` or `missing`: refuse on the first one in rank order, with `<tier> <category>/<key>: <reason>` (state, reference and journal rows have no `<category>/`), and write the refusal back.
6. No hit is `verified` and at least one is `unanchored`: refuse with `every candidate is unanchored: nothing on the chain vouches for it yet; push, then verify`.
7. Otherwise proceed, on the highest-ranked verified hit: `<tier> <category>/<key> verified against rows_root <16 hex> anchored at epoch <seq>, block <block>`, where the epoch and block are the mirror's head.

An unanchored hit is never credited as verified, even when Sibyl ranks it first. If unanchored hits outrank the verified one, the reason says so: `; NOTE <n> higher-ranked hit(s) are UNANCHORED and not vouched for by the chain (<names>): act on the verified row, push before relying on the others`. The test for this writes `rules/release-gate-v2` saying "ship on a Friday whenever" on top of an anchored `rules/release-gate`; the decision is `proceed` on `release-gate`, and when `release-gate-v2` ranks first the reason names it as unanchored.

## The refusal is written back

A refusal over a drifted or missing row is written into the store as a Sibyl entity, through Sibyl's own `set_entity`, so the next fresh session finds it with Sibyl's tools like any other entity:

| field | value |
|---|---|
| category | `kint_refusal` |
| name | `<tier>-<category or none>-<key>-<unix seconds>`, cut to 200 characters |
| status | `refused` |
| body | `refused` (true), `query`, `tier`, `category`, `key`, `reason`, `local_leaf`, `anchored_leaf`, `anchored_seq`, `anchored_block`, `anchored_tx`, `head_seq`, `head_block`, `at` (UTC) |

The result names it as `kint_refusal/<name>`. It is an ordinary entity, and itself an unanchored change. While the row still holds exactly the refused value, the refusal also holds kint-server's automatic pushes ([When a push is held](/docs/how-it-works#when-a-push-is-held)), so it reaches Base with whatever settles the row: `kint push` from your terminal anchors both, and `kint pull --discard-local` restores the anchored value and leaves the refusal in the backup copy. The other refusals (no candidate, no mirror, incomplete mirror, chain moved, every candidate unanchored) write nothing. `memory_verify` always writes the refusal; `kint verify --no-write` skips it.

## kint verify

```sh
kint [--tenant TENANT] [--db PATH] verify QUERY [--limit N] [--json] [--no-write]
```

| argument | default | effect |
|---|---|---|
| `QUERY` | required | the text Sibyl searches for |
| `--limit` | `5` | how many hits Sibyl returns and kint checks |
| `--json` | off | print the whole result as JSON instead of the lines below |
| `--no-write` | off | do not write a refusal entity |
| `--tenant` | `KINT_TENANT`, then `credentials.json`, then Sibyl's default | the Sibyl tenant (before the subcommand) |
| `--db` | `$SIBYL_MEMORY_DB` or `~/.sibyl-memory/memory.db` | the Sibyl store (before the subcommand) |

Before it verifies, it reads the chain head for the connected owner (not under `KINT_OFFLINE=1`, and not on a machine that is not connected). When that read fails it prints `kint: chain head unavailable (<error, URLs redacted>); verifying against the local mirror only` to stderr and carries on. Without `--json` it prints `query:`, then `sibyl verdict: <code>  hits: <n>`, one line per checked hit (status, row, reason; none when verify refused before checking rows), then `DECISION: PROCEED: ...` or `DECISION: REFUSE: ...`, then the refusal entity if one was written. The exit code is `0` on proceed and `1` on refuse. With `--json` it exits `0` either way, so read `decision`.

## memory_verify

The MCP tool runs the same function inside `kint-server`.

| parameter | type | default |
|---|---|---|
| `query` | string | required |
| `limit` | integer | `5` |

It returns `ok: true` with the result, or `ok: false` with `error` (the exception type) and `message` if verify raised.

| field | content |
|---|---|
| `query` | the query as given |
| `verdict` | kint's copy of Sibyl's verdict, shown above |
| `decision` | `proceed` or `refuse` |
| `reason` | one line, as in the decision list |
| `hits` | per hit, as Sibyl returned it: `tier`, `key`, `category`, `snippet`, `rank`, `ts` |
| `checks` | per hit: `tier`, `key`, `category`, `status`, `local_leaf`, `anchored_leaf`, `anchored_seq`, `anchored_block`, `anchored_tx`, `head_seq`, `head_block`, `rows_root`, `proof`, `proof_ok`, `reason`; empty when verify refused before checking rows |
| `refusal_entity` | `kint_refusal/<name>` when a refusal was written, otherwise null |
| `chain_head` | `{"seq", "digest", "block"}` as read for this call; null when it could not be read, under `KINT_OFFLINE=1`, or when verify refused before comparing it |

## What the agent believed at an earlier block

Sibyl's store holds a row's current text. The epochs on Base hold every version that was anchored. `memory_history` and `kint history` list them, oldest first, each with the block of the epoch that carried it.

That block is an upper bound. The version existed no later than block N: it was written on some machine before the push, and the chain says nothing about how long before. It is never a wall-clock "as of". With a block given, you get the newest entry anchored at or before that block (a deletion entry when the row was deleted by then), or null if the row had no anchored version by then.

Versions come from the local epoch cache, `~/.kint/epochs/<first 16 hex of the space>/`, which keeps the decrypted plaintext of every epoch this machine pushed, or pulled and could open. History makes no RPC call. A cold start stops at the newest snapshot epoch, so a freshly restored machine sees versions from that snapshot on, and a later pull that stops at a newer snapshot skips the diff epochs before it. `kint pull --full` (or `memory_pull` with `full`) walks past snapshots and caches every epoch this machine has not decrypted, those skipped ones included. Epochs sealed under a data key this machine does not hold, after a `kint rekey`, are reported by the pull and stay closed, so their versions do not appear.

A snapshot re-anchors every row. Its entry is marked `snapshot: true` and is dropped when the row did not change, so a compaction or a rotation never invents a version. A deletion shows as its own entry.

### kint history

```sh
kint [--tenant TENANT] history {entity,state,reference} KEY [--category CATEGORY] [--block N]
```

`KEY` is the entity name, state key or reference key. `--category` is part of an entity's identity: without it an entity never matches and nothing prints. State and reference rows have no category. Each version prints as `epoch <seq> block <= <block> leaf <16 hex>: <stored body>`, a deletion as `epoch <seq> block <= <block>: DELETED`. With `--block N` it prints the version live at that block as JSON, or `null`.

### memory_history

| parameter | type | default |
|---|---|---|
| `tier` | string: `entity`, `state` or `reference` | required |
| `key` | string | required |
| `category` | string, required for entities | null |
| `block` | integer | null |

Without `block` it returns `{"ok": true, "versions": [...], "count": n}`. With `block` it returns `{"ok": true, "at_block": N, "version": ...}`, where `version` is null when nothing was anchored by then. Each version carries `seq`, `block`, `tx`, `leaf` (full hex), `body` (the stored text), `status`, `deleted: false`, and `snapshot: true` on a snapshot entry; a deletion carries `seq`, `block`, `tx` and `deleted: true`.

Read [MCP tools](/docs/tools) next.

Source: [`src/kint/verify.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/verify.py), [`src/kint/canon.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/canon.py), [`src/kint/export.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/export.py), [`src/kint/epoch.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/epoch.py), [`src/kint/server.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/server.py), [`src/kint/cli.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/cli.py), and Sibyl's `sibyl_memory_client/verdicts.py` in [Sibyl-Memory](https://github.com/Sibyl-Labs/Sibyl-Memory).
