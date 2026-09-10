---
slug: configuration
title: Configuration
description: Every environment variable kint reads, the files it keeps, and how to hand the settings to kint-server.
group: Reference
order: 10
source: 'src/kint/paths.py'
---

# The environment is the whole configuration.

kint reads no config file. What it can be told arrives as an environment variable or one of two global flags, and what it keeps lives in one directory.

## How values are read

The nineteen variables below are every `os.environ` read in `src/kint`. A few rules hold across all of them:

- Switches take the exact value `1`. Any other value, `true` and `yes` included, leaves the switch off.
- An empty value counts as unset for every variable except `KINT_HOME` and `SIBYL_MEMORY_DB`. Those two take the empty string as a path, which resolves to the current directory, so unset them rather than blank them.
- A CLI flag beats the environment: `--tenant` beats `KINT_TENANT`, `--db` beats `SIBYL_MEMORY_DB`. Both go before the subcommand: `kint --tenant kint-demo status`.
- `kint-server` takes no flags. It resolves the tenant and the store path once, at startup, so a change to its environment takes a restart of the server.
- The terminal and the server must agree. If a harness sets `KINT_TENANT`, `SIBYL_MEMORY_DB` or `KINT_HOME` for `kint-server`, set the same values in the shell where you run `kint`, or the two look at different spaces.

## Every variable

| Variable | Default | Effect | Read in |
|---|---|---|---|
| `KINT_HOME` | `~/.kint` | The directory for every file kint keeps. Created with mode 0700 and reset to 0700 on each use. | `paths.py` |
| `KINT_TENANT` | unset | The Sibyl tenant id. It picks the space, so it decides which chain of epochs kint reads and writes. See [Tenant resolution](#tenant-resolution). | `store.py` |
| `SIBYL_MEMORY_DB` | `~/.sibyl-memory/memory.db` | The Sibyl store kint wraps and `kint-server` serves. Sibyl reads the same variable. | `paths.py` |
| `KINT_RPC_URL` | unset | The primary Base RPC, for reads and sends. Unset: the Alchemy key in the macOS Keychain, else `https://mainnet.base.org`. | `chain.py` |
| `KINT_RPC_URL_2` | derived | The independent second opinion on a cold start. Unset: `https://base-rpc.publicnode.com` when the primary is `https://mainnet.base.org` (with or without a trailing slash), else `https://mainnet.base.org`. | `chain.py` |
| `KINT_ALLOW_SINGLE_RPC` | off | `1` lets a cold-start pull go ahead on one RPC when the second resolves to the same endpoint or cannot be reached. | `pull.py` |
| `KINT_CONTRACT` | `0xa22E03f7a4145Bf4909a83595C90a38E14d79600` | The EpochAnchor address. Checksummed before use. | `chain.py` |
| `KINT_RPC_TIMEOUT` | `10` | Seconds each JSON-RPC call waits before it gives up. A call that fails on a connection error or a timeout is retried twice with a short backoff; a value that does not parse means 10. | `chain.py` |
| `KINT_NO_KEYCHAIN` | off | `1` skips the macOS Keychain for both the local passphrase and the Alchemy key. | `chain.py`, `keys.py` |
| `KINT_SESSION_PASSPHRASE` | unset | The machine-local secret that encrypts `session.key` and derives the key for the data key cache. Set, it wins over the Keychain and `local.secret`. | `keys.py` |
| `KINT_KEY_TTL` | `24h` | How long the unwrapped data key stays cached. Plain seconds, or a number with `s`, `m`, `h` or `d`; `session` keeps it in process memory only. | `keys.py` |
| `KINT_OFFLINE` | off | `1` stops `connect`, `rekey` and `recovery-code` from reading the head epoch's header off the chain, and `kint verify` and `memory_verify` from reading the chain head. | `connect.py`, `cli.py`, `server.py` |
| `KINT_OWNER_KEY` | unset | The owner's private key. Read only by `kint authorize direct` and `kint authorize burn-nonce`, never from argv. | `cli.py` |
| `KINT_QUIET_SECONDS` | `300` | Watcher: push once the store has been quiet this long. | `server.py` |
| `KINT_POLL_SECONDS` | `15` | Watcher: how often it looks at the store. Floor 1. | `server.py` |
| `KINT_SIZE_TRIGGER_BYTES` | `32768` | Watcher: push early when the estimated diff passes this size. | `server.py` |
| `KINT_NO_WATCHER` | off | `1` starts `kint-server` without the watcher thread. | `server.py` |
| `KINT_BOOTSTRAP_SECONDS` | `20` | How long `kint-server` waits for its startup pull before it serves; the pull then finishes behind the server. | `server.py` |
| `PYTHONPATH` | inherited | Read only by `kint doctor`, which flags it. See [PYTHONPATH](#pythonpath). | `connect.py` |

`KINT_KEY_TTL` falls back to 24 hours when it cannot parse the value. The expiry is written into the cache when you connect, and `kint-server` writes it again after every successful pull and push, with a fresh deadline from the `KINT_KEY_TTL` in its own environment, so set the same value in the harness registration as in the terminal where you connect. With `session` nothing touches the disk: the key lives only in the process that connected, so a `kint connect` run in a terminal with `KINT_KEY_TTL=session` leaves nothing for `kint-server` to use. A number for the watcher or for `KINT_BOOTSTRAP_SECONDS` that does not parse is replaced by its default, with a log line such as `KINT_QUIET_SECONDS='5m' is not a number; using 300.0`.

Two more are read by Sibyl's own code, which kint calls to load credentials and size the cap:

| Variable | Default | Effect |
|---|---|---|
| `SIBYL_CREDENTIALS` | `~/.sibyl-memory/credentials.json` | Sibyl's credentials file. kint takes `tenant_id`, `account_id` and `tier` (default `free`) from it through Sibyl's loader, which treats a symlink or a file that does not parse as absent. |
| `HERMES_HOME` | `~/.hermes` | Sibyl's cap walk also sizes `$HERMES_HOME/sibyl/memory.db` and every `profiles/<p>/memory.db` under it. |

## Tenant resolution

The `kint` CLI takes the first of these that is set:

1. `--tenant`, the global flag.
2. `KINT_TENANT`.
3. `tenant_id` in Sibyl's `credentials.json`.
4. `account_id` in the same file.
5. Sibyl's default tenant, `00000000-0000-0000-0000-000000000001`.

`kint-server` has no flag, so it starts at step 2. The tenant goes to Sibyl's client as well, so their eight tools read and write that tenant's rows, and it names the space: `keccak256("kint-space-v1" || tenant_id)`. The first 16 hex characters of the space name the files in `KINT_HOME`, and `kint status` prints them (`space bd2a3b5b8f3fb4c8` for `kint-demo`).

The vault key is derived per space, so the same wallet under another tenant opens a different vault. When the chain already holds epochs for the space a connect computed, the wrong tenant fails with `Wrong wallet, wrong passphrase, or wrong tenant.` When it holds none, the connect starts a fresh, empty vault for that space and writes a new recovery code, so check the tenant before you connect.

## The store

The store is `SIBYL_MEMORY_DB`, else `~/.sibyl-memory/memory.db`. `--db` overrides it for `push`, `compact`, `rekey`, `pull`, `verify`, `status`, `doctor` and `export`. kint creates the parent directory with mode 0700 when it is missing and builds its client the way Sibyl's server does, plus the volunteered cap. Around the file:

- Sibyl keeps `tier_cache.json` in the same directory.
- `kint pull --discard-local` moves `memory.db`, `memory.db-wal` and `memory.db-shm` aside in that directory, each renamed with a `.kint-backup-<YYYYmmdd-HHMMSS>` suffix, then restores from the chain.
- The watcher notices writes through the modification times of `memory.db` and `memory.db-wal`.

For Hermes' SDK door, point kint at the file Hermes' Sibyl provider uses: `SIBYL_MEMORY_DB=$HERMES_HOME/sibyl/memory.db`. See [Harnesses](/docs/harnesses).

`KINT_HOME` sits outside every path Sibyl's cap walk sizes, and kint volunteers its footprint back: the cap gate it hands Sibyl counts Sibyl's aggregate plus every file under `KINT_HOME`, against the same 5 MiB free-tier cap (5,242,880 bytes). `kint doctor` fails the check `kint home placement` when `KINT_HOME` is inside `~/.sibyl-memory`, a path Sibyl's cap walk already sizes.

## The KINT_HOME tree

`<space16>` is the first 16 hex characters of the space id. One machine can hold several spaces side by side; the session key is shared by all of them.

```text
~/.kint/
├── session.key                  this machine's session key, a V3 scrypt keystore
├── session.key.old              the previous one, after kint session-key rotate
├── local.secret                 the local passphrase, only when neither the Keychain nor KINT_SESSION_PASSPHRASE supplies it
├── kint.log                     kint-server's log
├── enrol-<space16>.json         owner, tenant, space, account kind, key tags, contract
├── wraps-<space16>.json         the wraps of the data key
├── vault-<space16>.aes          the unwrapped data key, encrypted under a key derived from the local passphrase, with its expiry
├── RECOVERY-<space16>.txt       the recovery code, on the machine that created the vault
├── mirror-<space16>.json        the rows and leaves as last anchored or pulled
├── watermark-<space16>.json     the highest head this machine has seen; it never decreases
├── head-<space16>.lock          one pusher or puller per space per machine, 30 second wait
└── epochs/
    └── <space16>/
        ├── 00000001.bin         the ciphertext, as it sat in the push calldata
        ├── 00000001.json        the decrypted epoch, when this machine could open it
        └── 00000001.meta.json   the epoch's metadata
```

Every file except the log is written with mode 0600, through a temporary file and a rename. `kint.log` is created with your umask. `push` refuses on the machine that created the vault while its `RECOVERY-<space16>.txt` is missing or empty; `kint recovery-code` writes it again. The mirror and the `.json` epoch files hold plaintext rows, as Sibyl's own `memory.db` does, so the directory mode is what protects them. See [Keys and custody](/docs/keys) for what each key can and cannot do.

## Keychain, and machines without one

On macOS kint uses two generic-password items through the `security` tool:

| Service | Account | Written by kint | Holds |
|---|---|---|---|
| `dev.kint-session-key` | `passphrase` | yes, on first use, with 32 random bytes as URL-safe text | the local passphrase that seals `session.key` and `vault-<space16>.aes` |
| `dev.api.alchemy` | `api-key` | never | an Alchemy API key; when present the primary RPC becomes `https://base-mainnet.g.alchemy.com/v2/<key>` |

The local passphrase comes from the first source that answers:

1. `KINT_SESSION_PASSPHRASE`.
2. The Keychain item `dev.kint-session-key`, on macOS unless `KINT_NO_KEYCHAIN=1`. Created if absent; if the write fails, kint falls through.
3. `$KINT_HOME/local.secret`, read if present, created with mode 0600 if not. When kint only needs to load the session key and finds none of the three, it stops with `no local passphrase: set KINT_SESSION_PASSPHRASE`.

On Linux, or anywhere that is not macOS, there is no Keychain: set `KINT_SESSION_PASSPHRASE`, or kint writes `local.secret` beside `session.key` and the directory mode is the only thing between them. The primary RPC is `KINT_RPC_URL`, else the public Base endpoint.

**Keep the source stable.** `session.key` and the data key cache are sealed under whatever the local passphrase was when they were written. Switch sources later, for example set `KINT_SESSION_PASSPHRASE` on a Mac that used the Keychain, and the session key no longer decrypts and the cached data key reads as absent.

## Base: chain, RPCs and contract

| Setting | Value |
|---|---|
| Chain | Base mainnet, chain id 8453 |
| Contract | [`0xa22E03f7a4145Bf4909a83595C90a38E14d79600`](https://basescan.org/address/0xa22E03f7a4145Bf4909a83595C90a38E14d79600), deployed at block 51,081,696 in tx [`0xf2e03cd1c4e7ca005ee602a6c61ed50861d2238acee217b2c19f8670ba2cc9f6`](https://basescan.org/tx/0xf2e03cd1c4e7ca005ee602a6c61ed50861d2238acee217b2c19f8670ba2cc9f6) |
| Primary RPC | `KINT_RPC_URL`, else the Keychain Alchemy key, else `https://mainnet.base.org` |
| Second RPC | `KINT_RPC_URL_2`, else `https://base-rpc.publicnode.com` when the primary is `https://mainnet.base.org`, else `https://mainnet.base.org` |
| Request timeout | `KINT_RPC_TIMEOUT`, 10 seconds per RPC call by default; a call that fails on a connection error or a timeout is retried twice |
| Receipt wait | 180 seconds; `push`, `compact` and `rekey` wait for 2 confirmations unless `--confirmations` says otherwise, and `kint-server` uses 2 |

The second RPC matters on a cold start only: a machine with no watermark asks both endpoints for the head and refuses if they disagree. Two URLs count as the same endpoint when host, port and path match (a trailing slash is ignored). When they do, the pull stops with `cold start needs a second, independent RPC and KINT_RPC_URL_2 resolves to the same endpoint as the primary`, unless `KINT_ALLOW_SINGLE_RPC=1`. Once a watermark exists, an RPC that serves an older head is refused as a `stale or lying RPC`. See [Freshness](/docs/new-machine#freshness-two-endpoints-on-a-cold-start).

kint redacts RPC URLs. Each URL keeps its scheme, host and port and loses its path, query and userinfo (`/<redacted>`), and the path and query of the endpoints kint is configured with are scrubbed wherever else they appear. Every error on its way to a tool result, a kint log line, or a `kint status`, `kint verify` or `kint doctor` line passes through it. kint-server logs an unexpected push, pull or verify failure as its error type and the redacted message, never a raw traceback; the CLI still prints a Python traceback, on your own terminal, for an error it does not catch.

## The watcher

The watcher is a thread inside `kint-server`; the CLI has none. It pushes unanchored changes while an agent works, so nothing waits for the session to end.

- Every `KINT_POLL_SECONDS` (15, floor 1) it compares the modification times of `memory.db` and `memory.db-wal`. A change marks the store dirty and restarts the quiet clock.
- It does nothing until this machine is connected and the data key is cached. Each successful push renews the cached key's deadline; if it expires anyway, pushes stop until you connect again, and the changes stay in the store.
- At start it counts the rows an earlier session left unanchored (a harness that killed the last server before its exit push landed) and, when there are any, starts dirty, so the quiet period pushes them.
- While dirty, it counts the changed and deleted rows on its first check and then at most once a minute. None: the dirty mark clears. More than `KINT_SIZE_TRIGGER_BYTES` at an estimated 400 bytes a row: it pushes at once. At the default 32768 that is 82 rows or more.
- Otherwise it pushes when the store has been quiet for `KINT_QUIET_SECONDS` (300).
- Every push it makes checks the store for drift first. A `HELD` push anchors nothing, and the watcher waits for the next store change instead of retrying; `memory_status` shows the reason under `held`.
- `KINT_NO_WATCHER=1` turns it off. `memory_push` and the exit push still work: on exit, SIGTERM or SIGHUP, `kint-server` pushes whatever is unanchored, once and best effort, after the tool call in flight has finished.

Every push is one Base transaction per epoch from the session key, so a shorter quiet period means more epochs.

## Logs

`kint-server` logs to `$KINT_HOME/kint.log` and to stderr, never to stdout: the MCP stdio transport owns stdout. The format is `%(asctime)s %(levelname)s %(message)s` at INFO. The file is appended to and never rotated, and it counts against the cap like every other file under `KINT_HOME`. If kint cannot open it, stderr is all there is.

On startup the server runs its pull on a thread of its own and waits for it up to `KINT_BOOTSTRAP_SECONDS`, then logs the line that says what it is serving. The bootstrap line before it says why there was no pull, or gives the pull's summary; a pull that outlives the budget logs `bootstrap: still running` instead, and its summary follows later:

```text
bootstrap: not connected (no enrolment); serving anyway, memory_connect explains
bootstrap: data key not cached; serving without pull, memory_connect explains
bootstrap: still running; serving now, the pull finishes in the background
kint-server: serving Sibyl's tools plus kint's on stdio (tenant kint-demo, db /Users/you/.sibyl-memory/memory.db)
```

The watcher adds `watcher: store changed`, `watcher: pushing (quiet trigger)` or `(size trigger)`, and the push result, and at start `watcher: N changed and M deleted row(s) were left unanchored by an earlier session; they are pushed at the next quiet period`. A held push logs `push HELD (<reason>): refusing to anchor: ...` once per distinct reason. A `memory_verify` that cannot read the chain head logs `chain head unavailable (...); verifying against the local mirror only`. The `kint` CLI does not use this log: its commands print to the terminal, with errors on stderr as lines that start with `kint:`.

## Handing the environment to kint-server

A harness starts `kint-server` itself, so the variables go into its registration. `kint setup <target> --env KEY=VALUE` (repeatable, split at the first `=`) writes them for you; see [kint setup](/docs/cli#kint-setup). Per target:

- `claude`: removes any user-scope `kint`, then runs `claude mcp add --scope user kint -e PYTHONPATH=x -e KEY=VALUE -- /usr/bin/env -u PYTHONPATH /abs/path/kint-server`.
- `codex`: appends a `[mcp_servers.kint]` table to `~/.codex/config.toml` after copying the file to `config.toml.bak-<unix seconds>`. If the table is already there it prints `codex: already configured` and changes nothing, so edit the file by hand from then on.
- `hermes` and `openclaw`: register `/usr/bin/env PYTHONPATH= KEY=VALUE /abs/path/kint-server`, so `env` sets the variables.

`/abs/path/kint-server` is the binary next to `kint`, else the one on `PATH`. A Codex block with the tenant pinned, a shorter quiet period, and room for the startup pull and for push and pull calls, which wait for Base confirmations (`kint setup` does not write the two timeouts):

```toml
[mcp_servers.kint]
command = "/abs/path/kint-server"
args = []
tool_timeout_sec = 180
startup_timeout_sec = 90

[mcp_servers.kint.env]
PYTHONPATH = ""
KINT_TENANT = "kint-demo"
KINT_QUIET_SECONDS = "120"
```

A harness that reads the common `mcpServers` JSON shape takes the same settings. `env -u PYTHONPATH` drops whatever `PYTHONPATH` the harness passes and keeps the rest:

```json
{
  "mcpServers": {
    "kint": {
      "command": "/usr/bin/env",
      "args": ["-u", "PYTHONPATH", "/abs/path/kint-server"],
      "env": {
        "KINT_TENANT": "kint-demo",
        "SIBYL_MEMORY_DB": "/Users/you/.sibyl-memory/memory.db",
        "KINT_KEY_TTL": "30d"
      }
    }
  }
}
```

Write absolute paths in both. A harness does not run a shell, so nothing expands `~` or `$HOME` for you. A `KINT_SESSION_PASSPHRASE` in a registration sits in a plaintext file, which protects it no better than `local.secret` does.

> **Warning.** Never put `KINT_OWNER_KEY` in a harness registration or a shell profile. `kint-server` never reads it; only `kint authorize direct` and `kint authorize burn-nonce` do, so export it in the one terminal that runs them and close that terminal after.

## PYTHONPATH

A `PYTHONPATH` set in your shell can put other packages ahead of kint's dependencies. Run both binaries with it unset (`env -u PYTHONPATH kint status`). `kint setup` keeps it out of every harness it registers (unset for Claude Code, empty for the others), and `kint doctor` prints `(PYTHONPATH is set: run with env -u PYTHONPATH)` beside the Python version while it is set.

## Check it

`kint doctor` reads the same settings and reports each one as `ok`, `WARN` or `FAIL`. The rows that come from this page:

| Row | What it checks |
|---|---|
| `kint home` | the path and its mode; anything but 0700 warns |
| `kint home placement` | fails when `KINT_HOME` is inside `~/.sibyl-memory` |
| `sibyl store` | the store path and whether the file exists (absent on a fresh machine warns) |
| `rpc primary` | the redacted URL, the chain id (anything but 8453 fails) and the block |
| `rpc secondary` | the redacted second URL; the same endpoint as the primary warns `(SAME as primary: no second opinion on a cold start)` |
| `contract` | whether the EpochAnchor address has code |
| `python` | the Python version, and the `PYTHONPATH` note |

Read [EpochAnchor contract](/docs/contract) next.

Source: [`src/kint/paths.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/paths.py), [`src/kint/chain.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/chain.py), [`src/kint/keys.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/keys.py), [`src/kint/server.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/server.py), [`src/kint/store.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/store.py), [`src/kint/log.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/log.py), [`src/kint/connect.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/connect.py), [`src/kint/pull.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/pull.py), [`src/kint/cli.py`](https://github.com/s0nderlabs/kint/blob/main/src/kint/cli.py).
