# kint

**Sibyl Memory that outlives the laptop.** Wipe the machine, connect the wallet, and the agent
comes back knowing what it knew, and proves it was not tampered with.

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
uv tool install kint            # or: pip install kint       Python 3.10+
kint session-key create         # this machine's key; put a few cents of ETH on it (Base)
kint canonical-payload --owner 0xYOU > kint-canonical.json
cast wallet sign --data --from-file kint-canonical.json --ledger | kint connect --owner 0xYOU --signature -
KINT_OWNER_KEY=... kint authorize direct        # or: kint authorize page   (Base Account owners)
kint setup all                  # Claude Code, Codex, Hermes, OpenClaw now start kint-server
```

Base Account (Coinbase Smart Wallet) owners have no deterministic signature to derive a key from,
so their vault key is a passphrase: `kint connect --owner 0xYourBaseAccount --smart-account`, then
`kint authorize page` opens a loopback page where the account sends `setSessionKey` itself (that
transaction also deploys a counterfactual account).

On a wiped machine: `kint connect ...` again (the data key comes out of the head epoch's own
header), then `kint pull`. A cold start reads the head from two different RPC operators
(`KINT_RPC_URL`, `KINT_RPC_URL_2`; public Base endpoints by default) and refuses if they disagree. `kint verify "release rule"` from a shell, or `memory_verify` from the
agent. `kint doctor` checks every moving part. `kint status` shows the head, the mirror, the
unanchored change count and the cap accounting: kint's own state is volunteered into the same
5 MiB free-tier cap Sibyl enforces, through Sibyl's public `CapGate(db_size_fn=...)` hook.

## Where memory is written and read (the critical path)

- Write: Sibyl's own tools, unchanged (`memory_remember`, `memory_set_state`, ...), served by
  `kint-server` (`src/kint/server.py`, `build_server()` from `sibyl_memory_mcp`).
- Anchor: `src/kint/push.py` diffs the store against the last anchored mirror and pushes the
  changed rows as one encrypted epoch (`src/kint/crypto.py`), after the Sibyl write returned,
  never inside it.
- Restore: `src/kint/pull.py` walks epochs backwards through the `prevBlock` field of each
  `Epoch` event, checks `keccak(ct)` against the event digest and the AEAD tag against an AAD that
  binds chain id, owner, space, seq, prev and the merkle root, then `src/kint/restore.py` replays
  rows through `MemoryClient.set_entity / set_state / set_reference / write_event`.
- Read and decide: `src/kint/verify.py` calls `client.search(query)` (Sibyl's ladder, typed
  verdict), re-reads the stored TEXT by the key the search returned (`src/kint/export.py`), hashes
  it (`src/kint/canon.py`) and proves inclusion against the anchored `rows_root`.

## The six added tools

`memory_status`, `memory_connect`, `memory_pull`, `memory_push`, `memory_verify`, `memory_history`.
Every kint operation is a tool; the human does two things ever: sign once per machine (or type
the vault passphrase) and put a few cents on a session key.

## Honest limits

- Content-exact and search-exact across the four tiers the SDK writes (entities, state,
  reference, journal); uuids and entity timestamps regenerate on replay, the journal ts survives.
  The export reads those tables by SQL in rowid order; the restore goes through the SDK.
- Every exported entity line carries its category and name by construction; Base holds
  ciphertext, but the row count and the size bucket are public.
- One wallet owns one memory; many machines may write under it, one at a time. Two machines
  writing at once is a fork: kint refuses and tells you (`kint pull --discard-local`).
- The ciphertext lives in transaction calldata; reading it back needs a node that keeps its
  transaction index, and Base's L1 data availability is the blob retention window. kint keeps its
  own ciphertext cache per epoch.
- A phished derive signature is a permanent key. The EIP-712 message says so in the one field
  every wallet renders. kint never accepts that signature as a login and never sends it anywhere.

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
env -u PYTHONPATH .venv/bin/python -m pytest -q      # 30 tests: vectors, fidelity, stdio MCP, anvil lifecycle, review regressions
cd contracts && forge test                            # 29 tests incl. a Base mainnet fork
scripts/e2e_cli_anvil.sh                              # the CLI, the way a human runs it
```

MIT. Built for the Sibyl Labs Hackathon, September 2026.
