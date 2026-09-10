---
slug: cli
title: CLI
description: Every kint command and flag with its default, which ones need the owner key, and the kint-server binary.
group: Reference
order: 9
source: 'src/kint/cli.py'
---

# Fifteen commands, and no secret ever on argv.

`kint` is the thin CLI over the same functions `kint-server` exposes as tools, for what needs a shell. This page lists every subcommand, every flag and its default, and marks which ones need the owner key or a secret on stdin.

It covers the connect pipe (a signature on stdin), key rotation, the session key, push and pull for SDK-direct harnesses such as Hermes, and `kint setup` to point a harness at `kint-server`. If your shell sets `PYTHONPATH`, run both binaries with it unset: `env -u PYTHONPATH kint status`. `kint doctor` flags it when it is set.

## Global options

These two go before the subcommand: `kint --tenant kint-demo status`, not `kint status --tenant kint-demo`.

| Option | Default | Used by |
|---|---|---|
| `--tenant TENANT` | `KINT_TENANT`, else `tenant_id` then `account_id` from Sibyl's `credentials.json`, else Sibyl's default tenant `00000000-0000-0000-0000-000000000001` | every command except `canonical-payload` and `setup` |
| `--db DB` | `$SIBYL_MEMORY_DB`, else `~/.sibyl-memory/memory.db` | `push`, `compact`, `rekey`, `pull`, `verify`, `status`, `doctor`, `export` |

The tenant picks the space, `keccak256("kint-space-v1" || tenant_id)`, so it decides which chain of epochs a command reads and writes. Sibyl's credentials file is `$SIBYL_CREDENTIALS`, else `~/.sibyl-memory/credentials.json`. Neither option reaches `kint-server`: a harness passes the tenant and the store path as environment variables (see [setup](#kint-setup)).

## What each command touches

| Command | Reads Base | Sends a transaction | What it needs from you |
|---|---|---|---|
| `canonical-payload` | no | no | nothing |
| `connect` | yes, the head epoch's header, or the newest readable one before it | no | the derive signature on stdin or in a file, the vault passphrase, or the recovery code on stdin |
| `session-key create`, `rotate` | no | no | nothing |
| `session-key show` | yes | no | nothing |
| `authorize payload` | yes | no | nothing; you sign its output with the owner wallet |
| `authorize submit` | yes | yes, from the session key | the owner's authorization signature on stdin |
| `authorize direct` | yes | yes, from the owner | the owner's private key in `KINT_OWNER_KEY` |
| `authorize page` | yes | yes, from the Base Account in the browser | nothing in the terminal |
| `authorize burn-nonce` | yes | yes, from the owner | the owner's private key in `KINT_OWNER_KEY` |
| `push`, `compact` | yes | yes, from the session key | a cached data key |
| `rekey` | yes | yes, from the session key | every key that is to keep opening the vault |
| `pull` | yes | no | a cached data key |
| `join` | yes | no | the owner address and one secret, as for `connect`; the CLIs of the harnesses it registers |
| `recovery-code` | yes, the head header | no | a cached data key |
| `verify` | yes, the chain head (skipped with `KINT_OFFLINE=1`) | no | nothing; it may write a refusal into Sibyl |
| `history`, `export` | no | no | nothing |
| `status` | yes, when connected | no | nothing |
| `doctor` | yes | no | nothing |
| `setup` | no | no | the harness CLI on `PATH` (Codex needs none) |

`KINT_OFFLINE=1` stops `connect`, `rekey` and `recovery-code` from reading the head header, and `verify` from reading the chain head. The owner key is only ever read from the environment, never from argv.

> **Warning.** `--signature` takes `-` (stdin) or a file path, never the signature itself. Any other value is treated as a path: the file is read, then unlinked. The signature an EOA owner signs to connect is the vault key, so pipe it from `cast wallet sign` or keep it in a file you are happy to lose.

## Connect and keys

### kint canonical-payload

Prints the frozen EIP-712 message an EOA owner signs to derive the vault key: domain `kint`, version `1`, chain id 8453, primary type `KintVault` with `owner` and `purpose`. The output is byte-stable and ends with a newline, which is what `cast wallet sign --data --from-file` reads. It ignores `--tenant`.

| Flag | Default | Meaning |
|---|---|---|
| `--owner` | required | the owner wallet address |

```sh
kint canonical-payload --owner 0xYOU > kint-canonical.json
```

### kint connect

Connects this machine to the vault. It finds the data key in this order: the local wraps (while they hold the key the head epoch was sealed with), then the head epoch's own header on Base, else it starts a fresh vault. When the head epoch's header does not parse, it reads the newest epoch within 32 before it whose header does (see [Limits](/docs/limits#writers)). On a fresh vault it writes the recovery code to `~/.kint/RECOVERY-<first 16 hex of the space>.txt`, and `push` refuses until that file exists.

| Flag | Default | Meaning |
|---|---|---|
| `--owner` | none; the command fails with `--owner 0x... is required` | the owner wallet address |
| `--signature` | none | `-` reads the 65-byte hex signature from stdin |
| `--signature-file PATH` | none | the signature from a file, read then unlinked |
| `--smart-account` | off | the owner is a smart account (Base Account): the key comes from a vault passphrase |
| `--passphrase-stdin` | off | read the passphrase from stdin |
| `--passphrase-prompt` | off | EOA mode: salt the wallet key with a passphrase, prompted |
| `--add-passphrase` | off | EOA mode: also add a passphrase wrap for the data key, prompted |
| `--recovery-code-stdin` | off | read the recovery code from stdin |

Three modes, checked in this order. With `--recovery-code-stdin`, the code is checked against the vault on the chain (or the cached epoch or key) before it is trusted; a recovery code cannot start a new vault. With `--smart-account`, the vault passphrase comes from stdin or from the prompt `vault passphrase: `. Otherwise it is EOA mode, which needs `--signature -` or `--signature-file`. `--passphrase-stdin` and `--signature -` cannot share stdin: use `--passphrase-prompt` or `--signature-file`. A passphrase that salts the wallet key has to be given again on every later connect and rekey.

```sh
cast wallet sign --data --from-file kint-canonical.json --ledger | kint connect --owner 0xYOU --signature -
kint connect --owner 0xYourBaseAccount --smart-account
kint connect --owner 0xYOU --recovery-code-stdin < code.txt
```

It prints the owner, the first 16 hex of the space, the first 8 hex of the key tag, where the data key came from (`local wraps`, `chain head header`, `fresh vault` or `recovery code`) and the session key address. It never prints the signature or either key.

### kint session-key

This machine's session key: a plain EOA that signs Base transactions to EpochAnchor and never decrypts. It lives at `~/.kint/session.key`, a V3 scrypt keystore with mode 0600. The keystore passphrase comes from `KINT_SESSION_PASSPHRASE`, else the macOS Keychain item `dev.kint-session-key` (created on first use, skipped with `KINT_NO_KEYCHAIN=1`), else `~/.kint/local.secret`.

| Argument or flag | Default | Meaning |
|---|---|---|
| `create`, `show` or `rotate` | required | the action |
| `--owner` | the connected owner | `show` only: the owner to check the authorization against |

`create` prints `created: 0x...`, or `exists: 0x...` if a key is already there. `rotate` moves the old keystore to `session.key.old` and creates a new key, which then needs its own authorization and funding. `show` prints JSON: `address`, `path`, `exists`, and when Base answers `balance_wei`, `balance_eth`, `authorized` and `expiry`.

```sh
kint session-key create
kint session-key show
```

### kint authorize

Authorizes this machine's session key to push under the owner. Every action needs a session key on this machine and an owner (`--owner`, else the connected owner).

| Argument or flag | Default | Meaning |
|---|---|---|
| `payload`, `submit`, `direct`, `page` or `burn-nonce` | required | the action |
| `--owner` | the connected owner | the owner wallet address |
| `--days` | `30` | the authorization's lifetime, from now (`payload`, `direct`, `page`) |
| `--signature` | `-` (stdin) | `submit`: the owner's authorization signature |
| `--expiry` | none | `submit`: the expiry `payload` printed |
| `--deadline` | none | `submit`: the deadline `payload` printed |

- `payload` prints the `SessionKeyAuthorization` typed data (domain `kint EpochAnchor`, version `1`, chain id 8453, the contract as verifying contract) with the owner's current `authNonce` and a deadline 300 seconds out. The JSON goes to stdout; the next command, with its `--deadline` and `--expiry`, goes to stderr.
- `submit` sends `setSessionKeyBySig` from the session key, which pays the gas. The deadline has to be in the future when the transaction lands.
- `direct` reads the owner's private key from `KINT_OWNER_KEY`, refuses if it is not the owner's, and sends `setSessionKey` from the owner.
- `page` is for Base Account owners. It serves one page on `127.0.0.1` with a random port and a random token in the path, waits up to 900 seconds for the browser to report, then polls `canWrite(owner, key)` every 3 seconds, 120 times. No secret crosses the page.
- `burn-nonce` sends `setSessionKey` from `KINT_OWNER_KEY`, keeping the key's current expiry. That increments `authNonce`, which cancels any authorization that was signed and never submitted. Like `direct`, it refuses when the key is not the owner's: `KINT_OWNER_KEY is 0x..., not the owner 0x...`.

```sh
kint authorize payload > auth.json
cast wallet sign --data --from-file auth.json --ledger | kint authorize submit --deadline D --expiry E --signature -
KINT_OWNER_KEY=... kint authorize direct --days 7
kint authorize page
```

### kint rekey

Rotates the data key: a new key, new wraps under the same keys, one snapshot epoch sealed under the new key, and a new recovery code. Every key that is to keep opening the vault must be supplied in the same command, because a wrap can only be made by whoever holds its key. Nothing on this machine changes until the snapshot epoch is on Base. There is no rekey tool: this is CLI only.

| Flag | Default | Meaning |
|---|---|---|
| `--owner` | the connected owner | the owner wallet address |
| `--signature` | none | `-` reads the 65-byte hex signature from stdin |
| `--signature-file PATH` | none | the signature from a file, read then unlinked |
| `--smart-account` | off | carry over the vault passphrase wrap (prompted); combine with a signature to carry both |
| `--passphrase-stdin` | off | read one passphrase from stdin: the salt when a signature is given, else the vault passphrase |
| `--passphrase-prompt` | off | EOA mode: the passphrase that salts the wallet key |
| `--add-passphrase` | off | also carry over the extra passphrase wrap, prompted |
| `--drop-missing` | off | rotate even though a key that opens the vault today was not supplied |
| `--over-skipped` | off | rotate even though the last pull stopped at an epoch this machine could not apply: the new snapshot chains on the chain head |
| `--confirmations` | `2` | blocks to wait for after the snapshot transaction |

It refuses unless this machine is connected, unless at least one supplied key opens the current vault (read from the head epoch's header, or the newest readable one within 32 before it), and, without `--drop-missing`, if it would drop a key. Like `push`, it refuses when the last pull stopped at an epoch this machine could not apply, unless `--over-skipped`. The refusal names each key it would drop by kind and tag. A dropped key keeps opening the epochs sealed before the rotation and opens nothing after it. The old recovery code is in the same position, so copy the new one off the machine.

```sh
cast wallet sign --data --from-file kint-canonical.json --ledger | kint rekey --signature -
cast wallet sign --data --from-file kint-canonical.json --ledger | kint rekey --signature - --smart-account
```

### kint recovery-code

Writes `~/.kint/RECOVERY-<first 16 hex of the space>.txt` (mode 0600) from the cached data key. It is the fix when `push` refuses because the machine that created the vault lost its recovery file. It refuses with `no data key cached on this machine: kint connect first`, and it refuses when the cached key is not the one the head epoch was sealed with (a rotation happened elsewhere; connect again first). No flags.

## Anchor and restore

### kint push

Diffs the store against what this machine last anchored, then anchors the changes on Base: one transaction per epoch from the session key. A change set too large for the 96 KB bucket is split across epochs; a single row that compresses to more than 90 KB on its own is refused by name.

| Flag | Default | Meaning |
|---|---|---|
| `--owner` | the connected owner | the owner wallet address |
| `--dry-run` | off | read the chain head and report what would be anchored; send nothing |
| `--confirmations` | `2` | blocks to wait for after each transaction |

It prints `nothing to push: the store matches the last anchored epoch` when that is true, otherwise one line per epoch with its seq, tx, block, bucket, rows, deletions and cost in ETH. It refuses when another machine pushed first (the message says to run `kint pull`, or `kint pull --discard-local` when this machine's unanchored changes may go), when the session key is not authorized, when the last pull left a gap (for an epoch that will never open it names `kint compact --over-skipped`), and on the machine that created the vault when its recovery file is gone. `kint push` is never held: it is how the human anchors a value kint-server held back (`HELD` in [MCP tools](/docs/tools)), so check the store before you run it.

```sh
kint push --dry-run
kint push
```

### kint compact

Anchors one snapshot epoch carrying the whole state, even when nothing changed. A cold start stops at the newest snapshot. It takes the same flags as `push` (`--owner`, `--dry-run`, `--confirmations` default `2`), plus one. Snapshots are single-epoch, so it refuses when the whole state compresses to more than 92,160 bytes; keep using `kint push` then.

| Flag | Default | Meaning |
|---|---|---|
| `--over-skipped` | off | anchor the snapshot on the chain head even though the last pull stopped at an epoch this machine could not apply |

`--over-skipped` is the owner's way past an epoch that will never open, such as one a leaked session key appended. It is honoured only on a machine whose last pull reported such an epoch. It prints `push: OVERRIDE, anchoring a snapshot on top of chain head seq N (...)` and chains the snapshot on the head, so every later pull stops at it, with this machine's store as the whole state. Revoke the key that wrote the epoch first.

```sh
kint compact
kint compact --over-skipped
```

### kint pull

Restores or refreshes the store from Base. It checks freshness first: the head may not be older than the watermark this machine already saw, and on a cold start two different RPC operators must agree on the head (`KINT_ALLOW_SINGLE_RPC=1` accepts one). It then walks the epochs back from the head, stopping at the newest snapshot, verifies each against the chain, and replays the rows through Sibyl's own write methods. It needs a cached data key, so connect first.

| Flag | Default | Meaning |
|---|---|---|
| `--owner` | the connected owner | the owner wallet address |
| `--discard-local` | off | move the local store aside and restore from the chain |
| `--force-scan` | off | accepted and passed through, but the 0.3.0 pull never reads it |
| `--full` | off | walk past snapshot epochs to the first epoch (the whole history, not just the current state); on a store already up to date, cache every epoch not yet decrypted, for `history` |

It refuses over a fork: rows this machine never anchored while the chain moved, or a store holding rows for the tenant that this machine has no record of. The fork message says to save what you need out of the store, then run `--discard-local`, which moves `memory.db` and its `-wal` and `-shm` files to `<name>.kint-backup-<YYYYmmdd-HHMMSS>` before restoring (the whole file, other tenants' rows included). Epochs sealed under a retired data key are printed as `CLOSED`. An epoch it could not apply is printed as `SKIPPED`: when it could not open that epoch and a later snapshot in the same walk opens, the line ends `(snapshot epoch S carries the whole state, the pull carried on)` and the pull completes; otherwise the pull stopped there, and push and verify refuse until it applies.

```sh
kint pull
kint pull --full
kint pull --discard-local
```

### kint join

The read half of setting up a machine in one command: this machine's session key, connect, restore and harness registration. It sends no transaction and spends nothing, and every step reads the state first, so running it again resumes rather than starting over. [Restore on a new machine](/docs/new-machine#one-command-kint-join) walks through what it prints.

| Flag | Default | Meaning |
|---|---|---|
| `--owner` | required | the wallet that owns the memory |
| `--base-account` | off | the owner is a Base Account: the vault passphrase is the key, prompted for |
| `--passphrase-stdin` | off | read the passphrase from stdin instead of prompting |
| `--passphrase-prompt` | off | EOA mode: prompt for the passphrase that salts the wallet key |
| `--signature` | none | EOA owners: `-` reads the 65-byte hex derive signature from stdin |
| `--signature-file` | none | EOA owners: a file holding the signature, read then unlinked |
| `--recovery-code-stdin` | off | either owner: the recovery code on stdin |
| `--new-vault` | off | allowed to start a vault when the chain holds no epochs for this owner and tenant |
| `--discard-local` | off | move a local store aside and restore from the chain |
| `--full` | off | walk past snapshot epochs for the older versions |
| `--setup` | `all` | which harnesses to register: `all`, `claude`, `codex`, `hermes` or `openclaw` |
| `--no-setup` | off | register no harness |
| `--env` | none | `KEY=VALUE` for the server process, repeatable; `KINT_TENANT` is always set to the tenant it joined |
| `--tenant`, `--db` | the global values | the same as the global options, accepted after the command |

Exactly one of `--base-account`, `--signature -`, `--signature-file PATH` and `--recovery-code-stdin` is required, and `--passphrase-stdin` cannot share stdin with `--signature -` (use `--passphrase-prompt` or `--signature-file`). With no epochs under that owner and tenant it stops at the vault step unless `--new-vault` is passed. A failure prints `join stopped at <step>: <message>`; a failed join creates no store, and a session key it created before the failure is kept for the retry. Its last line says `writes: on`, or `writes: off until the session key is funded and authorized by the owner; reads work now` followed by the next step.

```sh
kint join --owner 0xYourBaseAccount --base-account
cast wallet sign --data --from-file kint-canonical.json --ledger | kint join --owner 0xYOU --signature -
kint join --owner 0xYOU --recovery-code-stdin --setup claude
```

## Read and decide

### kint verify

Runs the same search Sibyl's `memory_search` runs (`multi_record_search`, every precision gate included), re-reads the exact stored text of every hit, hashes it and proves it against the `rows_root` this machine last saw anchored. It also reads the chain head and refuses with `chain moved to seq N at block B, pull first` when another machine anchored past this machine's mirror. When the head cannot be read it prints `kint: chain head unavailable (...); verifying against the local mirror only` to stderr and checks against the mirror; `KINT_OFFLINE=1` skips the read. It never sends a transaction. On a refusal it writes a Sibyl entity in category `kint_refusal`, unless `--no-write`; a running kint-server then holds its pushes while the row keeps the refused value.

| Argument or flag | Default | Meaning |
|---|---|---|
| `query` | required | the search query |
| `--limit` | `5` | how many hits to check |
| `--json` | off | print the full result as JSON |
| `--no-write` | off | do not write a refusal entity |

Each hit gets one status: `verified`, `drifted`, `unanchored` or `missing`. The last line is `DECISION: PROCEED: ...` or `DECISION: REFUSE: ...`. The exit status is 0 on proceed and 1 on refuse, except with `--json`, which always exits 0; read the `decision` field instead.

```text
$ kint verify "release rule"
query: release rule
sibyl verdict: ok  hits: 3
  verified   entity rules/release-gate: stored text matches the leaf anchored on Base
DECISION: PROCEED: entity rules/release-gate verified against rows_root <16 hex> anchored at epoch 2, block 51081880
```

### kint history

Every anchored version of an entity, state or reference row, oldest first. Each version carries a block-height upper bound: it existed no later than that block. It reads the local epoch cache, so it lists the versions this machine has decrypted; `kint pull --full` fills in the older ones. A snapshot that re-anchored an unchanged row does not add a version.

| Argument or flag | Default | Meaning |
|---|---|---|
| `entity`, `state` or `reference` | required | the tier (the journal tier is not accepted) |
| `key` | required | the entity name, state key or reference key |
| `--category` | none | the entity's category; entities are keyed by it, so give it for them |
| `--block` | none | print, as JSON, the version live at that block (`null` if none) |

```text
$ kint history entity release-gate --category rules
epoch 1 block <= 51081867 leaf f406bb0919d23360: {"rule":"never ship on a Friday; ...", ...}
epoch 2 block <= 51081880 leaf 4ac605528bbb00e7: {"rule":"never ship on a Friday; ...", ...}
```

A deleted row prints `epoch N block <= B: DELETED`.

## Inspect

### kint status

The tenant, the space and the store path; the owner and whether the data key is cached; what this machine last anchored (seq, block, rows); how many rows changed or were deleted since. When the machine is connected, it also prints the chain head with `in step` or `NOT in step: pull or push`, the contract address, and the session key's balance and authorization. It ends with the cap accounting: Sibyl's bytes, kint's bytes (mirror, epoch cache, keys) and the total against the 5 MiB free-tier cap Sibyl enforces. No flags.

### kint doctor

Checks every moving part and prints one `[ok  ]`, `[WARN]` or `[FAIL]` line per check: the Sibyl packages, the kint home (mode 0700 expected), the Sibyl store, whether the kint home sits inside `~/.sibyl-memory`, the enrolment, the cached data key, the recovery file, the primary RPC (chain id 8453), the secondary RPC (a warning when it is the same endpoint), the contract's code, the session key (ok when authorized with more than 0.00002 ETH), the head against the mirror, unanchored changes, and the Python version. RPC URLs are printed as scheme and host only. It exits 1 when any check fails.

| Flag | Default | Meaning |
|---|---|---|
| `--owner` | the connected owner | the owner to check the session key and head against |

### kint export

Prints the four tiers the Sibyl SDK writes (entity, state, reference, journal) for the tenant, one JSON object per line, in rowid order, read-only. It is a debug tool and the output is plaintext memory. No flags.

## Harnesses

### kint setup

Points a harness at `kint-server` instead of `sibyl-memory-mcp`. It looks for `kint-server` next to the `kint` binary, then on `PATH`, and fails with `kint-server not found next to kint or on PATH`. A harness whose CLI is missing is skipped.

| Argument or flag | Default | Meaning |
|---|---|---|
| `all`, `claude`, `codex`, `hermes` or `openclaw` | required | `all` runs the four in that order |
| `--env KEY=VALUE` | none | set in the server process; repeatable, for example `KINT_TENANT=kint-demo` |

| Target | What it does |
|---|---|
| `claude` | removes any user-scope `kint`, then runs `claude mcp add --scope user kint -e PYTHONPATH=x [-e KEY=VALUE ...] -- /usr/bin/env -u PYTHONPATH /abs/path/kint-server`, and reminds you to remove Sibyl's own `sibyl-memory` registration |
| `codex` | appends `[mcp_servers.kint]` (the absolute `kint-server` path, `args = []`, env `PYTHONPATH = ""` plus your `--env` pairs) to `~/.codex/config.toml`, after copying it to `config.toml.bak-<unix time>`; if a `kint` block exists it prints `codex: already configured` and changes nothing |
| `hermes` | runs `hermes mcp add kint --command /usr/bin/env --args PYTHONPATH= [KEY=VALUE ...] /abs/path/kint-server` |
| `openclaw` | runs `openclaw mcp set kint` with `{"command":"/usr/bin/env","args":["PYTHONPATH=", ..., "/abs/path/kint-server"]}` |

Global `--tenant` and `--db` do not reach the server. Pin them with `--env KINT_TENANT=...` and `--env SIBYL_MEMORY_DB=...`. Registration is user scope only for Claude Code. For project scope, run it by hand: `claude mcp add --scope project kint -e PYTHONPATH=x -e KINT_TENANT=... -- /usr/bin/env -u PYTHONPATH /abs/path/kint-server` writes `.mcp.json`, and Claude Code asks you to approve it until the folder is trusted. [Harnesses](/docs/harnesses) covers each one.

```sh
kint setup all --env KINT_TENANT=kint-demo
```

## kint-server

The binary your harness starts. It takes no flags or arguments and speaks MCP on stdio: Sibyl's `build_server()` with their eight tools unmodified, plus kint's six. It reads the tenant from `KINT_TENANT` (else Sibyl's credentials, else Sibyl's default) and the store from `SIBYL_MEMORY_DB` (else `~/.sibyl-memory/memory.db`).

- On start, when the machine is connected and the data key is cached, it pulls. It waits for that pull up to `KINT_BOOTSTRAP_SECONDS` (default 20), then serves while the pull finishes. A fork or a freshness refusal is logged and it serves the local store.
- While serving, a watcher checks the store every `KINT_POLL_SECONDS` (default 15, at least 1). It pushes after `KINT_QUIET_SECONDS` of quiet (default 300), or sooner when the change set passes `KINT_SIZE_TRIGGER_BYTES` (default 32768, estimated as 400 bytes per changed row and checked once a minute). It starts with the rows an earlier session left unanchored. `KINT_NO_WATCHER=1` turns the watcher off.
- Every push it makes is held (`HELD`, nothing anchored) when a row the chain vouches for changed behind Sibyl's tools while it ran, or when `memory_verify` refused exactly the value a row holds. `kint push` is not.
- Every successful pull and push renews the cached data key's deadline.
- On exit, `SIGTERM` or `SIGHUP` it pushes whatever is unanchored, once and best effort, after the tool call in flight has finished.
- It logs to stderr and `~/.kint/kint.log`, never stdout, because the MCP transport owns stdout.

## Exit status

| Status | Meaning |
|---|---|
| 0 | done; `verify` decided proceed |
| 1 | `verify` refused; `doctor` found a failing check; or an error kint does not catch (an RPC failure, the head lock held by another kint process for 30 seconds), shown as a Python traceback |
| 2 | a line starting `kint:` (a missing flag, a refusal from `connect`, `authorize`, `rekey` or `recovery-code`), or a usage error from argparse |
| 3 | `push`, `compact`, `rekey`: the data key on this machine expired or is missing, or the session key cannot be loaded (`pull` too, for the session key) |
| 4 | `push`, `compact`, `rekey`: the chain moved, another machine pushed; `pull`: a fork |
| 5 | `push`, `compact`, `rekey`, `pull`: any other push or pull refusal (a pull with no cached data key lands here) |
| 6 | `pull`: freshness refusal, a stale RPC or two RPCs that disagree on a cold start |

`join` exits 2 when it stops before the restore, and with the `pull` codes (3, 4, 5 or 6) when the restore refuses.

Read [Configuration](/docs/configuration) next.

Source: [`src/kint/cli.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/cli.py), [`src/kint/connect.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/connect.py), [`src/kint/keys.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/keys.py), [`src/kint/push.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/push.py), [`src/kint/pull.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/pull.py), [`src/kint/page.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/page.py), [`src/kint/server.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/server.py), [`src/kint/join.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/join.py), [`src/kint/setup.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/setup.py).
