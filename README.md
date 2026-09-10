<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/kint-lockup-dark.svg">
    <img src="docs/assets/kint-lockup-light.svg" alt="kint" width="120">
  </picture>
</p>

<p align="center"><b>Sibyl Memory that outlives the laptop.</b><br>
Wipe the machine, connect the wallet, and the agent comes back knowing what it knew, and proves it was not tampered with.</p>

<p align="center">
  <a href="https://kint.s0nderlabs.xyz/docs">Docs</a> ·
  <a href="docs/site/">Docs as markdown</a> ·
  <a href="https://basescan.org/address/0xa22e03f7a4145bf4909a83595c90a38e14d79600">EpochAnchor on Base</a> ·
  <a href="docs/judge.md">Claims a judge can check</a> ·
  <a href="https://github.com/s0nderlabs/kint/releases/tag/v0.3.0">v0.3.0</a> ·
  <a href="LICENSE">MIT</a>
</p>

[Sibyl Memory](https://github.com/Sibyl-Labs/Sibyl-Memory) decides what a coding agent remembers:
five tiers, full-text search, eight MCP tools, one SQLite file. Today that file lives on one
machine. kint keeps it wallet-owned: every change is packed, padded, encrypted to a key only the
owner's wallet (or vault passphrase) can produce, and written to Base as calldata under a small
contract. On any machine the owner connects, kint pulls, verifies every epoch against the chain,
and replays the rows back through Sibyl's own write methods. Before the agent acts on anything it
recalled, `memory_verify` re-reads the exact stored text, hashes it, and checks it against the
leaf the chain vouches for. A row that drifted is refused, naming the block that anchored the last
good value, and the refusal is written back as a Sibyl entity. Because the chain keeps every
version, `memory_history` answers what the agent believed at an earlier block, which Sibyl cannot.

Built on Sibyl Memory, under it: `kint-server` imports their MCP server untouched, keeps their
eight tools exactly as shipped, and adds six of its own.

<details>
<summary><b>For hackathon judges</b> · the memory walkthrough, a 30-second on-chain check, and where to look</summary>

<br>

**Persist.** Every write goes through Sibyl's own tools. When the agent goes quiet, kint diffs the
store against the last anchored mirror and writes the changed rows to Base as one encrypted epoch
(compressed, padded to a size bucket, AES-256-GCM under a key only the owner's wallet or vault
passphrase can produce), under the `EpochAnchor` contract.

**Recall (fresh session).** On a wiped machine the owner connects the wallet; kint pulls every
epoch, checks each against the chain, and replays the rows through `MemoryClient`'s write
methods. The agent then finds a rule by free-text `memory_search` (Sibyl's four FTS5 indexes and
the shadow fallback), which returns ranked hits and a typed verdict from `verdicts.py`.

**Changes the agent's decision by.** kint hashes exactly the `body` text that search returned and
proves it against the `rows_root` anchored on Base. A row whose text no longer matches its
anchored leaf is refused with a reason naming the block that anchored the last good value and the
head block, and the refusal is written back as a Sibyl entity so the next fresh session sees it.
`memory_history` shows every anchored version of the row, each with a block-height upper bound.

**What breaks when memory is deleted.** Without Sibyl there is no ranked candidate and no verdict
to key on: the epoch is a decrypted blob with no query surface, so a fresh session neither refuses
nor proceeds. See [Delete the Sibyl Memory layer and what breaks](#delete-the-sibyl-memory-layer-and-what-breaks).

**Verify on chain in 30 seconds** (no install beyond [foundry](https://getfoundry.sh)). The demo
tenant's head on Base mainnet, read from the verified contract:

```
$ cast keccak "kint-space-v1kint-demo"
0xbd2a3b5b8f3fb4c81658d863b90018f1af511c28b33356fc81c2de406be98cb0
$ cast call 0xa22E03f7a4145Bf4909a83595C90a38E14d79600 "head(address,bytes32)(bytes32,uint64,uint64)" \
    0xC635e6Eb223aE14143E23cEEa9440bC773dc87Ec \
    0xbd2a3b5b8f3fb4c81658d863b90018f1af511c28b33356fc81c2de406be98cb0 \
    --rpc-url https://mainnet.base.org
0x7df5378a8c4fa8664365cf8956033cac2f4e3cbf7a4767a377d759b262f01a13
2
51081880
```

That is epoch 2 of the demo memory: digest `7df5378a…`, sequence 2, anchored at block 51081880.
Its ciphertext is the calldata of the transaction in that block
([`0x369907fb…`](https://basescan.org/tx/0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729)),
and `keccak256` of that ciphertext is the digest.

**Executed on Base mainnet** (chain id 8453):

| what | where |
|---|---|
| `EpochAnchor` (verified, no admin, no upgrade path) | [`0xa22E03f7a4145Bf4909a83595C90a38E14d79600`](https://basescan.org/address/0xa22e03f7a4145bf4909a83595c90a38e14d79600) |
| epoch 1 of the demo tenant, 14 rows, 4 KB bucket | [`0xbe9bb859…`](https://basescan.org/tx/0xbe9bb8596c825a8891c3eafe4381e0c6522d647641735c635ca58fcf4bbe4455), block 51081867 |
| epoch 2, the release rule rewritten | [`0x369907fb…`](https://basescan.org/tx/0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729), block 51081880 |
| a Base Account (Coinbase Smart Wallet) authorizing a machine from the browser, then its epoch | owner `0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3`, [`0x9c64e2c2…`](https://basescan.org/tx/0x9c64e2c21b294843888680bd34d6da8242cb5313bc894864552163e167049c12), block 51082012 |

**Where to look in under two minutes.** [`docs/judge.md`](docs/judge.md) maps every claim to a
file and line: `src/kint/verify.py` for the decision beat, `src/kint/restore.py` for the replay
through the SDK, `src/kint/store.py` for the cap volunteering, `src/kint/server.py` for the
untouched import of Sibyl's server. `pytest -q` (52 tests, six of them on anvil), `forge test` (29, including a Base
mainnet fork) and `bun test` (110) pin them.

**Reproduce.** [Try it](#try-it-5-minutes) below: install from the tagged release, one signature
per machine, a few cents on a session key, and every harness you run starts `kint-server` in
place of Sibyl's. Claude Code, Codex, Hermes and OpenClaw each recalled the demo rule through it
and reported `proceed` at block 51081880 ([`docs/agents.md`](docs/agents.md)).

</details>

## Delete the Sibyl Memory layer and what breaks

The decision beat reaches the row through Sibyl's `memory_search` (four FTS5 indexes plus the
shadow fallback) and keys on the typed verdict from `verdicts.py`. Without Sibyl there is no ranked
candidate and no verdict to key on: the epoch is a decrypted blob with no query surface, so a fresh
session neither refuses nor proceeds. Base holds the ciphertext; Sibyl is what turns it back into
an answerable store. See `docs/judge.md` for the claims table with file and line.

## Live on Base mainnet

| what | where |
|---|---|
| EpochAnchor (verified) | [`0xa22E03f7a4145Bf4909a83595C90a38E14d79600`](https://basescan.org/address/0xa22e03f7a4145bf4909a83595c90a38e14d79600) |
| first epoch of the demo tenant | tx `0xbe9bb8596c825a8891c3eafe4381e0c6522d647641735c635ca58fcf4bbe4455`, block 51081867 |
| a Base Account (Coinbase Smart Wallet) authorizing a machine from the browser | tx from `0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3`, then epoch tx `0x9c64e2c21b294843888680bd34d6da8242cb5313bc894864552163e167049c12`, block 51082012 |

A 4 KB epoch costs about 0.000002 ETH on Base today (EIP-7623 calldata floor, 40 gas per byte,
plus the L1 data fee). Restoring and reading never send a transaction.

## Try it (5 minutes)

```
uv tool install git+https://github.com/s0nderlabs/kint@v0.3.0      # Python 3.10+; not on PyPI yet
kint session-key create         # this machine's key; put a few cents of ETH on it (Base)
kint canonical-payload --owner 0xYOU > kint-canonical.json
cast wallet sign --data --from-file kint-canonical.json --ledger | kint connect --owner 0xYOU --signature -
KINT_OWNER_KEY=... kint authorize direct        # or: kint authorize page   (Base Account owners)
kint setup all                  # Claude Code, Codex, Hermes, OpenClaw now start kint-server
```

If your shell exports `PYTHONPATH`, run the binaries with it unset (`env -u PYTHONPATH kint ...`):
a polluting `PYTHONPATH` shadows the tool's own environment and the binary fails to start.
`kint setup` bakes `/usr/bin/env -u PYTHONPATH` into every harness registration for that reason.

Base Account (Coinbase Smart Wallet) owners have no deterministic signature to derive a key from,
so their vault key is a passphrase: `kint connect --owner 0xYourBaseAccount --smart-account`, then
`kint authorize page` opens a loopback page where the account sends `setSessionKey` itself (that
transaction also deploys a counterfactual account).

On a wiped machine: `kint join --owner 0xYOU ...` does the read half in one command (session key,
connect, restore, harness registration) and writes nothing to the chain; or run `kint connect ...`
again (the data key comes out of the head epoch's own header), then `kint pull`. A cold start reads the head from two different RPC operators
(`KINT_RPC_URL`, `KINT_RPC_URL_2`; by default an Alchemy key from the macOS Keychain item
`dev.api.alchemy` when one exists, otherwise public Base endpoints) and refuses if they disagree;
`KINT_ALLOW_SINGLE_RPC=1` accepts a single endpoint.
`kint verify "release rule"` from a shell, or `memory_verify` from the agent. `kint doctor` checks
every moving part. `kint status` shows the head, the mirror, the unanchored change count and the
cap accounting: kint's own state is volunteered into the same 5 MiB free-tier cap Sibyl enforces,
through Sibyl's public `CapGate(db_size_fn=...)` hook. `kint compact` anchors one snapshot epoch
holding the whole state, which is where the next cold start stops (`kint pull --full` walks past
it for the older versions). `kint rekey` rotates the data key itself: a new key, new wraps under
the same wallet or passphrase, one snapshot epoch under the new key, a new recovery code. Rekey is
a CLI command only, because the wallet signature and the vault passphrase it needs are typed in a
terminal, never in an agent chat.

Every command, flag, tool parameter and environment variable is in the [documentation](docs/site/):
[Quickstart](docs/site/02-quickstart.md), [Restore on a new machine](docs/site/03-new-machine.md),
[MCP tools](docs/site/08-tools.md), [CLI](docs/site/09-cli.md),
[Configuration](docs/site/10-configuration.md), [Harnesses](docs/site/13-harnesses.md),
and [For agents](docs/site/14-agents.md) when an AI agent is doing the install.

## Where memory is written and read (the critical path)

- Write: Sibyl's own tools, unchanged (`memory_remember`, `memory_set_state`, ...), served by
  `kint-server` (`src/kint/server.py`, `build_server()` from `sibyl_memory_mcp`).
- Anchor: `src/kint/push.py` diffs the store against the last anchored mirror and pushes the
  changed rows as one encrypted epoch (`src/kint/crypto.py`), after the Sibyl write returned,
  never inside it; kint-server holds the push (`HELD`) when a row changed behind Sibyl's tools.
- Restore: `src/kint/pull.py` walks epochs backwards through the `prevBlock` field of each
  `Epoch` event, checks `keccak(ct)` against the event digest and the AEAD tag against an AAD that
  binds chain id, owner, space, seq, prev and the merkle root, then `src/kint/restore.py` replays
  rows through `MemoryClient.set_entity / set_state / set_reference / write_event`.
- Read and decide: `src/kint/verify.py` calls `multi_record_search(client, query)`, the same gated
  call Sibyl's own `memory_search` makes (typed verdict, precision gates), refuses when the chain
  head has moved past what this machine last pulled, re-reads the stored TEXT by the key the search
  returned (`src/kint/export.py`), hashes it (`src/kint/canon.py`) and proves inclusion against the
  anchored `rows_root`.

## The six added tools

`memory_status`, `memory_connect`, `memory_pull`, `memory_push`, `memory_verify`, `memory_history`.
Every kint operation is a tool; the human does two things ever: sign once per machine (or type
the vault passphrase) and put a few cents on a session key. `memory_push(snapshot=true)` anchors
the whole state as one snapshot epoch instead of the diff, and `memory_pull(full=true)` walks past
snapshots. Rotating the data key is deliberately NOT a tool: `kint rekey` needs the wallet
signature or the vault passphrase, and those never travel through a chat.

The derive signature is never accepted by a tool: it travels only on stdin, through
`kint connect --signature -`. `memory_connect` does accept a vault passphrase or a recovery code
as parameters, for harnesses whose only door is a tool call; type them in the terminal instead
(`kint connect --passphrase-stdin`, `--recovery-code-stdin`) whenever you can, because anything
that passes through an agent chat lands in its transcript.

## Honest limits

- Content-exact and search-exact across the four tiers the SDK writes (entities, state,
  reference, journal); uuids and entity timestamps regenerate on replay, the journal ts survives.
  The export reads those tables by SQL in rowid order; the restore goes through the SDK. Those are
  four of Sibyl's eleven tables; the other seven (entity_relations, revenue_events, error_events,
  archived_entities, flagged_actors, skill_proposals, learning_runs) are not exported. Sibyl's
  `memory_forget` moves an entity into `archived_entities`, so a restored machine has the deletion,
  not the archive.
- Every exported entity line carries its category and name by construction; Base holds
  ciphertext, but the row count and the size bucket are public.
- One wallet owns one memory; many machines may write under it, one at a time. Two machines
  writing at once is a fork: kint refuses and tells you (`kint pull --discard-local`).
- The ciphertext lives in transaction calldata; reading it back needs a node that keeps its
  transaction index, and Base's L1 data availability is the blob retention window. kint keeps its
  own ciphertext cache per epoch.
- A phished derive signature is a permanent key. The EIP-712 message says so in the one field
  every wallet renders. kint never accepts that signature as a login and never sends it anywhere.
- A space has one data key at a time. `kint rekey` rotates it: a new key, new wraps, one snapshot
  epoch under the new key, a new recovery code. Epochs sealed before the rotation stay readable to
  whoever held the old key; that is a property of any ledger, not something a rotation can undo.
- A cold start stops at the newest snapshot epoch (`kint compact` writes one), so restore cost is
  bounded by the size of the memory, not its history. `kint pull --full` walks past snapshots for
  the older versions, as far back as the newest key rotation: epochs sealed under a retired key stay
  closed to a machine that only holds the current one.
- kint-server holds every push it makes itself (error `HELD`, nothing anchored, nothing dropped) when a
  row the chain vouches for changed behind Sibyl's tools while it ran, or still holds a value
  `memory_verify` refused; `kint push` from a terminal is never held. The hold only sees edits made while
  kint-server runs and since its last successful pull or push: a row edited behind Sibyl's back while no
  server was running is anchored by the next automatic push unless `memory_verify` refused it first.
- A hold stops the whole push, so every other unanchored change waits until the human runs `kint push`
  or `kint pull --discard-local`. Verifying your own unpushed edit to an anchored row refuses it as
  drifted and holds every server push: push an edit before you verify it. A second writer on the same
  store while kint-server runs (another harness's server, an SDK-direct process) also reads as drift.
- A session key can append any bytes as an epoch. A pull steps past an epoch it cannot open when a later
  snapshot opens, and connect and rekey read the newest epoch whose header parses (up to 32 back).
  Otherwise the owner revokes the leaked key and anchors a snapshot over it with
  `kint compact --over-skipped` or `kint rekey --over-skipped` (terminal only). An epoch forged with a
  well-formed header still stops connect, rekey and the recovery code until that snapshot sits on top.
- The exit push is best effort: a harness that kills the server within a second of closing it
  (Claude Code does) ends the push before its transaction lands. The next kint-server session pushes the
  leftover rows at its first quiet period, or `kint push` anchors them at once.
- The cached data key (`KINT_KEY_TTL`, 24 hours by default) is renewed after every successful pull and
  push while kint-server runs; a machine that goes a whole TTL without one still lapses and needs
  `kint connect` again.
- Two machines that both connect before the first push each create their own vault; the second
  opens nothing until it runs `kint connect` again, which then adopts the vault in the head epoch.
- `kint pull --rebase` is not built; `kint pull --discard-local` is the way out of a fork. It moves the
  whole `memory.db` aside, so other tenants' rows in the same store end up only in the backup copy.
- A push whose transaction lands but whose confirmation wait fails is later reported as another
  machine's push and a fork; the Epoch writer on Basescan is this machine's session key, and
  `kint pull --discard-local` recovers the same rows.
- Tool results and kint's log lines keep only the scheme and host of an RPC URL; an error the CLI does
  not catch still prints a raw Python traceback on your own terminal.
- `kint authorize page` loads the Base Account SDK from esm.sh with no integrity check.
- kint is not on PyPI yet; install from the tagged release on GitHub.

## Prior work

- **Sibyl Sovereign** (Sibyl Labs, in development): a cryptographic seal on every critical file,
  re-checked before every action, fail-closed, with an append-only audit trail. kint applies that
  mechanism one tier down, to the memory store itself, on Base. Same idea, theirs first.
- **anima** (s0nderlabs, 0G): anchors a keystore root hash on chain, roots only. On 0G the storage
  primitive is native; on Base a root alone is a receipt for data you still have to store
  somewhere, which is why kint puts the ciphertext itself in calldata.
- **ERC-8350** (Agent Memory State Registry, draft): the vocabulary of a per-space linear chain of
  committed deltas describes kint's epochs exactly. Reference shape only, not implemented.
- The verify-a-local-artifact-against-an-anchor pattern exists in several hackathon entries;
  restoring the memory itself from the chain and showing a superseded belief do not.

## Partner stack

Base: the contract, every epoch, and the authorization transactions above are executed on Base
mainnet and shown in the demo.

## Develop

```
uv sync
env -u PYTHONPATH .venv/bin/python -m pytest -q      # 52 tests: vectors, fidelity, stdio MCP, anvil lifecycle, snapshots and rekey, review and audit regressions
cd contracts && forge test                            # 29 tests incl. a Base mainnet fork
scripts/e2e_cli_anvil.sh                              # the CLI, the way a human runs it
scripts/e2e_cli_snapshot_anvil.sh                     # compact, rekey, a cold start and pull --full through the CLI
cd js && bun install && bun test                      # the browser decrypt path against Python-generated vectors
python3 scripts/build_docs.py --out web               # the documentation site from docs/site/*.md
```

`js/` is `@s0nderlabs/kint-core`, the browser side (read epochs off Base, open them locally, nothing
decrypted leaves the page); `scripts/gen_vectors.py` regenerates its test vectors from the Python.
The documentation is markdown in `docs/site/` (one file per chapter), rendered by
`scripts/build_docs.py` into static pages, per-page markdown, `llms.txt` and `llms-full.txt`.

MIT. Built for the Sibyl Labs Hackathon, September 2026.
