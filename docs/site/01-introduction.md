---
slug: introduction
title: Introduction
description: Sibyl Memory that outlives the laptop: wallet-owned, kept on Base, verified before the agent acts on it.
group: Get started
order: 1
source: 'README.md'
---

# Sibyl Memory that outlives the laptop.

Wipe the machine, connect the wallet, and the agent comes back knowing what it knew, and proves it was not tampered with. kint keeps Sibyl Memory wallet-owned, on Base, and checked before the agent acts on it.

## What kint is

kint is a drop-in MCP server for coding agents that keeps [Sibyl Memory](https://github.com/Sibyl-Labs/Sibyl-Memory) wallet-owned: encrypted to a key only the owner can produce, written to Base, restored on any machine the owner connects, and checked against the chain before the agent acts on a recalled row.

This page covers what kint does in v0.3.0, the pieces it is made of, what is live on Base mainnet, and how the rest of these docs are laid out.

## The bet

Sibyl decides what the agent remembers. kint decides where that memory lives and who can read it: the wallet.

Sibyl Memory gives a coding agent five tiers, full-text search, eight MCP tools and one SQLite file. That file lives on one machine. kint is built on Sibyl Memory and sits under it: `kint-server` imports Sibyl's MCP server untouched (`build_server()` from `sibyl_memory_mcp.server`), keeps their eight tools unmodified, and adds six of its own. The agent keeps writing memory the way it always did. kint takes the rows that changed since the last anchored epoch, compresses them, pads them to a size bucket, encrypts them and appends them to a chain of epochs on Base.

s0nderlabs runs no server in that path. The pieces are your machine, the owner wallet, a small contract on Base with no admin, and the RPC endpoints you read it through (`KINT_RPC_URL` and `KINT_RPC_URL_2` when you set them; otherwise public Base RPC endpoints, or an Alchemy key when the macOS Keychain holds one as `dev.api.alchemy`).

Take Sibyl away and nothing is left to decide on. The decision step reaches the row through `multi_record_search`, the same gated search Sibyl's `memory_search` runs, and keys on its typed verdict. Without Sibyl an epoch is a decrypted blob with no query surface. Base holds the ciphertext; Sibyl is what turns it back into a store the agent can ask. [Built on Sibyl Memory](/docs/sibyl) walks through this with file and line.

## What it does today

**Restore by wallet connect.** On a new or wiped machine, `kint connect` recovers the data key: an EOA owner signs one frozen EIP-712 message, a Base Account owner types the vault passphrase, and a recovery code covers the day both are gone. `kint pull` then walks the epochs back from the head. It checks each ciphertext's keccak against the digest in the contract's `Epoch` event and opens it under an AAD that binds chain id, owner, space, seq, prev, bucket, rows_root and dek_id. Each row is replayed through Sibyl's own write methods (`set_entity`, `set_state`, `set_reference`, `write_event`), then re-read and compared. A cold start reads the head from two different RPC operators and refuses if they disagree. An epoch that no key on the machine can open is a gap, unless a later snapshot in the same walk does open: then the pull records the skipped epoch and resumes at that snapshot, whose rows are the whole state. `kint-server` starts a pull as it starts, whenever the machine is connected and its cached data key has not expired, and begins serving after at most `KINT_BOOTSTRAP_SECONDS` (default 20) while a slower pull finishes behind it.

**Verify before acting.** `memory_verify(query)` runs the same gated search Sibyl's `memory_search` runs, and refuses when Sibyl's verdict is anything but `ok`. It re-reads the exact stored text of every hit, hashes it, and proves it against the `rows_root` this machine last saw anchored. When the chain head has moved past what this machine last pulled, it refuses and says to pull first. It returns `proceed` or `refuse`. A row that drifted is refused, and the reason names the block that anchored the last good value and the head block this machine last saw. The refusal is written back as a Sibyl entity (category `kint_refusal`, status `refused`), so the next fresh session sees it too. A row written after the last anchored epoch is never counted as verified. `kint verify "release rule"` does the same from a shell.

**History across an overwrite.** Because the chain keeps every version, `memory_history` (and `kint history`) lists what an entity, state or reference row held at every anchored epoch. With `block` it returns the version live at that block. Each version carries a block-height upper bound, "existed no later than block N", never a wall-clock time. Sibyl cannot answer this question on its own.

**Snapshots and key rotation.** `kint compact` (or `memory_push(snapshot=true)`) anchors one epoch that holds the whole state, flagged `FLAG_SNAPSHOT` (0x02). A cold start stops at the newest snapshot, so restore cost is bounded by the size of the memory, not its history. `kint pull --full` (or `memory_pull(full=true)`) walks past snapshots and caches every older epoch it had not decrypted yet, for history. `kint rekey` rotates the data key: a new key, new wraps under the keys you supply, one snapshot epoch under the new key, and a new recovery code. Rekey is CLI only. There is no rekey tool: rotating needs the wallet signature or the vault passphrase, and `kint rekey` takes them in your own terminal, never in an agent chat.

When a pull stops at an epoch that no key will ever open (a leaked session key can append one), the owner runs `kint compact --over-skipped` or `kint rekey --over-skipped` on that machine. It anchors a snapshot of the machine's store on top of the chain head, and every later pull resumes there. Neither flag is a tool argument.

Writing needs no extra step from the agent. While `kint-server` runs on a connected machine, a watcher pushes unanchored changes once the store has been quiet for `KINT_QUIET_SECONDS` (default 300), or earlier when the estimated size of the change set passes `KINT_SIZE_TRIGGER_BYTES` (default 32 KiB); `memory_push` pushes on demand, and an exit hook tries once more when the server stops. Rows a session leaves unanchored are pushed by the next session at its first quiet period. `KINT_NO_WATCHER=1` turns the watcher off. The anchor always happens after the Sibyl write has returned, never inside it.

Every push `kint-server` makes is held, with error `HELD`, when a row the chain vouches for changed behind Sibyl's tools while the server was running, or still holds a value `memory_verify` refused. Nothing is anchored, nothing is dropped, and `memory_status` says why. `kint push` from your own terminal is never held; it is the way past a hold once you have checked the store.

## The layers

| Layer | Lives on | What it holds or does |
|---|---|---|
| Sibyl store | `~/.sibyl-memory/memory.db`, or `$SIBYL_MEMORY_DB` | Sibyl's own SQLite file, written only by Sibyl's code. kint reads it and replays into it through the SDK. |
| kint-server | a stdio MCP process your harness starts | Sibyl's server with their eight tools unmodified, plus `memory_status`, `memory_connect`, `memory_pull`, `memory_push`, `memory_verify`, `memory_history`. |
| Local state | `~/.kint`, or `$KINT_HOME` (mode 0700) | The machine's session key, the enrolment, the cached data key, the mirror of what was last anchored, a ciphertext cache per epoch, the freshness watermark, the head lock, the recovery code file and `kint.log`. |
| EpochAnchor | Base mainnet, chain id 8453 | Per owner and space, a hash-linked chain of epochs. The ciphertext travels in `push` calldata; the contract keeps only the latest digest, seq and block per owner and space, and emits every epoch's digest in an `Epoch` event. |
| kint-core | the browser | `@s0nderlabs/kint-core`, a TypeScript port of the decrypt path. It reads epochs off Base and opens them locally. It never writes to the chain. |

Two more details hold the layers together. First, kint's own state lives outside every path Sibyl's cap accounting walks, and kint volunteers its footprint back into Sibyl's 5 MiB free-tier cap through Sibyl's public `CapGate(db_size_fn=...)` hook, so `kint status` shows Sibyl's bytes, kint's bytes and the total against the same cap. Second, a space is `keccak256("kint-space-v1" || tenant_id)`, so the Sibyl tenant decides which chain of epochs a machine reads and writes.

Install puts two commands on your path: `kint`, the CLI a human runs, and `kint-server`, which your harness starts. kint is not on PyPI yet; [Quickstart](/docs/quickstart) has the install line.

> **Note.** The signature an EOA owner signs to connect a machine is the key itself, not a login. It travels only on stdin (`kint connect --signature -`), never on argv and never through a tool. `memory_connect` does accept `passphrase` and `recovery_code` parameters, but anything typed into an agent chat lands in the transcript, so prefer the terminal: `kint connect --passphrase-stdin` or `kint connect --recovery-code-stdin`.

## Live on Base mainnet

| What | Where |
|---|---|
| EpochAnchor (verified) | [`0xa22E03f7a4145Bf4909a83595C90a38E14d79600`](https://basescan.org/address/0xa22e03f7a4145bf4909a83595c90a38e14d79600), deployed at block 51081696 |
| Demo tenant `kint-demo`, epoch 1 | [`0xbe9bb8596c825a8891c3eafe4381e0c6522d647641735c635ca58fcf4bbe4455`](https://basescan.org/tx/0xbe9bb8596c825a8891c3eafe4381e0c6522d647641735c635ca58fcf4bbe4455), block 51081867, 14 rows, 4 KB bucket |
| Demo tenant `kint-demo`, epoch 2 | [`0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729`](https://basescan.org/tx/0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729), block 51081880 |
| A Base Account owner authorizing a machine from the browser | owner `0xd3390EDAC3d0EB41248C132792B0DcC5f0b0D4E3`, then epoch [`0x9c64e2c21b294843888680bd34d6da8242cb5313bc894864552163e167049c12`](https://basescan.org/tx/0x9c64e2c21b294843888680bd34d6da8242cb5313bc894864552163e167049c12), block 51082012 |

The contract has no owner, no admin, no pause and no upgrade path; a redeploy would be a new address and a new chain of epochs. A 4 KB epoch costs about 0.000002 ETH on Base (the EIP-7623 calldata floor at 40 gas per byte, 191,040 gas for the 4 KB bucket, plus the L1 data fee). Only the bucket is public, never the true length: 4096, 8192, 16384, 32768, 65536 or 98304 bytes. Restoring and reading never send a transaction.

## Who this is for

kint is for you if you already run Sibyl Memory under a coding agent and want that memory to outlive the machine it was written on, owned by your wallet rather than by any one disk, and checked before the agent acts on it. Claude Code, Codex, Hermes and OpenClaw were each verified reading memory through `kint-server` on Sep 9 2026, and `kint setup` wires any of them. EOA owners (Ledger, MetaMask, Rabby, a keystore) sign once per machine. Base Account owners use a vault passphrase instead. Each machine writes through its own session key, which the owner authorizes with an expiry (30 days by default) and which holds a few cents of ETH on Base for gas.

It is not the right tool if several machines need to write at the same moment. One wallet owns one memory, and many machines may write under it one at a time. Two machines writing at once is a fork: kint refuses and tells you, and `kint pull --discard-local` moves the local store aside and restores from the chain. There is no rebase. Base holds only ciphertext, but each epoch's size bucket is public, and the bucket bounds how many rows it can carry. [Limits and threat model](/docs/limits) lists the rest.

## How the docs are organized

Five groups, sixteen pages.

- **Get started.** This page, [Quickstart](/docs/quickstart) (install, connect, authorize, wire a harness) and [Restore on a new machine](/docs/new-machine).
- **Concepts.** [How it works](/docs/how-it-works) follows one row from a Sibyl write to an epoch and back. [Keys and custody](/docs/keys) covers the signature, the passphrase, the recovery code and the session key. [Epochs on Base](/docs/epochs) covers the envelope, buckets, snapshots and the walk. [Verify before acting](/docs/verify) covers the decision and the refusal.
- **Reference.** [MCP tools](/docs/tools), [CLI](/docs/cli), [Configuration](/docs/configuration), [EpochAnchor contract](/docs/contract) and [Browser core](/docs/kint-core). Every tool, command, flag and environment variable, read from the code.
- **Operate.** [Harnesses](/docs/harnesses) for Claude Code, Codex, Hermes and OpenClaw, and [For agents](/docs/agents), the page an agent reads to run kint itself.
- **Background.** [Built on Sibyl Memory](/docs/sibyl), what kint uses from Sibyl and what breaks without it, and [Limits and threat model](/docs/limits).

kint 0.3.0 is MIT licensed and was built for the Sibyl Labs Hackathon, September 2026.

Read [Quickstart](/docs/quickstart) next.

Source: [`README.md`](https://github.com/s0nderlabs/kint/blob/main/README.md), [`CHANGELOG.md`](https://github.com/s0nderlabs/kint/blob/main/CHANGELOG.md), [`src/kint/server.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/server.py), [`src/kint/paths.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/paths.py), [`src/kint/verify.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/verify.py), [`src/kint/pull.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/pull.py), [`src/kint/push.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/push.py), [`src/kint/connect.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/connect.py), [`src/kint/chain.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/chain.py), [`contracts/src/EpochAnchor.sol`](https://github.com/s0nderlabs/kint/blob/main/contracts/src/EpochAnchor.sol), [`contracts/deployments/base-mainnet.json`](https://github.com/s0nderlabs/kint/blob/main/contracts/deployments/base-mainnet.json).
